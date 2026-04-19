import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import plotly.express as px

import gspread
from google.oauth2.service_account import Credentials

# --- Columns (existing + new TF fields) ---
COLUMNS = [
    "Date","Day","Previous day Close","Gap Points","Nifty Open",
    "Nifty Spot at 9.45 AM","Trigger High (+0.3%)","Trigger Low (-0.3%)",
    "IV Percentile at 9.45 AM","Trade Signal","Buy Strike","Sell Strike",
    "Buy Strike Entry Premium","Sell Strike Entry Premium",
    "Buy Strike Exit Premium","Sell Strike Exit Premium",
    "Debit Paid","Exit Price","Qty","PnL","Result","Balance",
    "Drawdown","Streak","Remarks",
    "TF_Monthly_Zone","TF_Near_Daily_SR","TF_Hourly_Trend",
    "TF_Trade_Allowed","No_Trade_Reason"
]

# ---------- Google Sheets backend ----------

def _get_worksheet():
    """Return gspread worksheet using service-account credentials."""
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(st.secrets["gcp_service_account"]["GCP_SHEET_ID"])
    # Use the first sheet; change to .worksheet("Sheet1") if you rename it
    return sheet.sheet1

def load_data() -> pd.DataFrame:
    """Load all data from the Google Sheet into a DataFrame."""
    ws = _get_worksheet()
    records = ws.get_all_records()  # list of dicts (skips header row)

    if not records:
        df = pd.DataFrame(columns=COLUMNS)
    else:
        df = pd.DataFrame(records)

    # Ensure all expected columns exist and in correct order
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[COLUMNS]

def save_data(df: pd.DataFrame):
    """Overwrite the Google Sheet with the full DataFrame."""
    ws = _get_worksheet()

    # Clear entire sheet
    ws.clear()

    # Write header row
    ws.append_row(COLUMNS, value_input_option="RAW")

    # Write data rows (if any)
    if not df.empty:
        rows = df[COLUMNS].where(pd.notna(df), "").values.tolist()
        ws.append_rows(rows, value_input_option="USER_ENTERED")

def append_row(row_dict: dict):
    """Append a single row to the sheet."""
    ws = _get_worksheet()

    # If sheet is empty (no header), initialise it
    if not ws.get_all_values():
        ws.append_row(COLUMNS, value_input_option="RAW")

    # Build row in correct column order
    row = [row_dict.get(col, "") for col in COLUMNS]
    ws.append_row(row, value_input_option="USER_ENTERED")

def today_str():
    return datetime.now().strftime("%d/%b/%Y")  # e.g. 10/Mar/2026

def get_day_from_date(date_str):
    """Convert date string to day name"""
    try:
        date_obj = datetime.strptime(date_str, "%d/%b/%Y")
        return date_obj.strftime("%A")
    except:
        return ""

def round_to_nearest_50(value):
    """Round value to nearest 50"""
    return round(value / 50) * 50

def calculate_strikes(spot, signal):
    """Calculate suggested strikes based on signal"""
    atm = round_to_nearest_50(spot)
    
    if signal == "CALL":
        buy_strike = atm + 100
        sell_strike = atm + 200
    elif signal == "PUT":
        buy_strike = atm - 100
        sell_strike = atm - 200
    else:
        buy_strike = 0
        sell_strike = 0
    
    return atm, buy_strike, sell_strike

# ---------- Page 1: Trade Validation ----------

def page_validation():
    st.header("Trade Signal")

    # Basic date/day
    col1, col2 = st.columns(2)
    with col1:
        date = st.text_input("Date", value=today_str())
    with col2:
        day = get_day_from_date(date)
        st.text_input("Day", value=day, disabled=True)

    # Market inputs
    st.subheader("Market Inputs")
    prev_close = st.number_input("Previous day Close", value=0, step=1, format="%d")
    today_open = st.number_input("Today Open", value=0, step=1, format="%d")

    gap_points = int(today_open - prev_close) if prev_close else 0
    st.write(f"Gap Points (auto): **{gap_points}**")

    spot_945 = st.number_input("Nifty Spot at 9:45 AM", value=0, step=1, format="%d")
    iv_945   = st.number_input("IV Percentile at 9:45 AM", value=0, step=1, format="%d")

    trig_high = round(prev_close * 1.003) if prev_close else 0
    trig_low  = round(prev_close * 0.997) if prev_close else 0
    st.write(f"Trigger High (+0.3%): **{trig_high}**")
    st.write(f"Trigger Low (-0.3%): **{trig_low}**")

    # Timeframe filters
    st.subheader("Timeframe Filters")
    tf_monthly = st.selectbox("Monthly zone nearby?", ["N","Y"])
    tf_daily   = st.selectbox("Near strong Daily S/R?", ["N","Y"])
    tf_hourly  = st.selectbox("Hourly trend", ["UP","DOWN","SIDE"])

    # Check if all data is filled
    data_filled = (
        prev_close > 0
        and today_open != 0
        and spot_945 > 0
        and tf_monthly != ""
        and tf_daily != ""
        and tf_hourly != ""
    )

    # ---------- Core validation logic ----------

    signal = "NONE"
    trade_allowed = "NO"
    type_field = "NO TRADE (NO SIGNAL)"
    no_trade_reason = ""
    warning_message = ""

    if data_filled:
        # Step 1: derive signal
        if spot_945 and prev_close:
            if spot_945 > trig_high:
                signal = "CALL"
            elif spot_945 < trig_low:
                signal = "PUT"

        # Step 2: apply filters
        if signal == "NONE":
            no_trade_reason = "No 0.3% move"
            type_field = "NO TRADE (NO SIGNAL)"

        elif tf_monthly == "Y":
            no_trade_reason = "Near monthly level"
            type_field = "NO TRADE (MONTHLY ZONE)"

        elif tf_daily == "Y":
            warning_message = "⚠️ WARNING: Near strong Daily S/R - proceed with caution"
            # keep checking further; do not block

        # IV filter
        if signal != "NONE" and tf_monthly != "Y" and iv_945 > 60:
            no_trade_reason = "IV too high"
            type_field = "⚠️ NO TRADE (IV TOO HIGH)"

        # Gap filter
        elif signal != "NONE" and tf_monthly != "Y" and abs(gap_points) > 100:
            no_trade_reason = "Gap > 100"
            type_field = "⚠️ NO TRADE (GAP > 100)"

        # Hourly alignment
        elif signal != "NONE" and tf_monthly != "Y" and iv_945 <= 60 and abs(gap_points) <= 100:
            if (signal == "CALL" and tf_hourly == "DOWN") or (signal == "PUT" and tf_hourly == "UP"):
                no_trade_reason = "Hourly misaligned (opposite to signal)"
                type_field = "NO TRADE (HOURLY MISALIGNED)"
            else:
                trade_allowed = "YES"
                type_field = f"BUY {signal} SPREAD"

    # ---------- Display validation card ----------

    with st.container(border=True):
        st.markdown("### ✓ Trade Signal Validation")

        if not data_filled:
            st.info("📝 Kindly update all the data above to see validation results.")
        else:
            c1, c2, c3 = st.columns(3)
            with c1:
                status_color = "🟢" if trade_allowed == "YES" else "🔴"
                st.metric("Trade Allowed", f"{status_color} {trade_allowed}")
            with c2:
                signal_display = signal if trade_allowed == "YES" else "NA"
                st.metric("Signal Type", signal_display)
            with c3:
                st.metric("Status", type_field)

            if trade_allowed == "NO":
                st.error(f"❌ Reason: {no_trade_reason}")
            if warning_message:
                st.warning(warning_message)

    # If required inputs are missing, stop here
    if not data_filled:
        return

    # ---------- NO-TRADE logging ----------

    if trade_allowed == "NO":
        if not no_trade_reason and signal == "NONE":
            no_trade_reason = "No 0.3% move"
            type_field = "NO TRADE (NO SIGNAL)"

        if st.button("📝 Log as NO TRADE", use_container_width=True):
            row = {c: None for c in COLUMNS}
            row.update({
                "Date": date,
                "Day": day,
                "Previous day Close": int(prev_close),
                "Gap Points": gap_points,
                "Nifty Open": int(today_open),
                "Nifty Spot at 9:45 AM": int(spot_945),
                "Trigger High (+0.3%)": trig_high,
                "Trigger Low (-0.3%)": trig_low,
                "IV Percentile at 9:45 AM": int(iv_945),
                "Trade Signal": type_field,
                "PnL": 0,
                "Result": "NO TRADE",
                "Remarks": "",
                "TF_Monthly_Zone": tf_monthly,
                "TF_Near_Daily_SR": tf_daily,
                "TF_Hourly_Trend": tf_hourly,
                "TF_Trade_Allowed": trade_allowed,
                "No_Trade_Reason": no_trade_reason,
            })
            append_row(row)
            st.success("✅ No-trade day logged.")
        return

    # ---------- Trade entry form (only when allowed) ----------

    # At this point: data_filled is True and trade_allowed == "YES"

    st.markdown("---")

    # Suggested strikes
    atm, buy_strike_suggest, sell_strike_suggest = calculate_strikes(spot_945, signal)
    st.info(f"💡 **Suggested Strikes:** ATM = {atm} | Buy Strike = {buy_strike_suggest} | Sell Strike = {sell_strike_suggest}")

    st.markdown("#### ⚡ Strike Details")
    c1, c2 = st.columns(2)
    with c1:
        buy_strike  = st.number_input("Buy Strike", value=buy_strike_suggest, step=50, format="%d")
    with c2:
        sell_strike = st.number_input("Sell Strike", value=sell_strike_suggest, step=50, format="%d")

    # Entry premiums
    st.markdown("#### 📈 Entry Premiums")
    c3, c4 = st.columns(2)
    with c3:
        buy_entry = st.number_input("Buy Entry Premium", value=0.0, step=0.05, format="%.2f")
    with c4:
        sell_entry = st.number_input("Sell Entry Premium", value=0.0, step=0.05, format="%.2f")

    # Quantity
    st.markdown("#### 💼 Position Details")
    qty = st.number_input("Quantity", value=65, step=1, format="%d")

    # Entry spread metrics
    net_spread = buy_entry - sell_entry
    spread_target = net_spread * 1.5 if net_spread > 0 else 0
    spread_sl = net_spread * 0.75 if net_spread > 0 else 0
    buy_strike_target = buy_entry * 1.5 if buy_entry > 0 else 0
    buy_strike_sl = buy_entry * 0.75 if buy_entry > 0 else 0

    st.markdown("**Entry Spread Analysis:**")
    s1, s2, s3 = st.columns(3)
    with s1:
        st.metric("Net Spread (Entry)", f"₹{net_spread:.2f}", delta="Credit" if net_spread < 0 else "Debit")
    with s2:
        st.metric("Spread Target", f"₹{spread_target:.2f}")
    with s3:
        st.metric("Spread SL", f"₹{spread_sl:.2f}")

    s4, s5, s6 = st.columns(3)
    max_profit = (spread_target - net_spread) * qty if spread_target > 0 else 0
    max_loss = (net_spread - spread_sl) * qty if spread_sl > 0 else 0
    rr = max_profit / max_loss if max_loss != 0 else 0

    with s4:
        st.metric("Max Profit", f"₹{max_profit:.0f}")
    with s5:
        st.metric("Max Loss", f"₹{abs(max_loss):.0f}")
    with s6:
        st.metric("Risk:Reward", f"{rr:.2f}" if max_loss != 0 else "N/A")

    s7, s8 = st.columns(2)
    with s7:
        st.metric("Buy Strike Target", f"₹{buy_strike_target:.2f}")
    with s8:
        st.metric("Buy Strike SL", f"₹{buy_strike_sl:.2f}")

    # Exit premiums
    st.markdown("#### 📉 Exit Premiums (Fill after closing trade)")
    e1, e2 = st.columns(2)
    with e1:
        buy_exit = st.number_input("Buy Exit Premium", value=0.0, step=0.05, format="%.2f")
    with e2:
        sell_exit = st.number_input("Sell Exit Premium", value=0.0, step=0.05, format="%.2f")

    net_spread_sell = buy_exit - sell_exit
    pnl = (net_spread_sell - net_spread) * qty if net_spread != 0 else 0

    if buy_exit > 0 or sell_exit > 0:
        st.markdown("**Trade Exit Analysis:**")
        e3, e4, e5 = st.columns(3)
        with e3:
            st.metric("Net Spread (Exit)", f"₹{net_spread_sell:.2f}")
        with e4:
            st.metric("Calculated PnL", f"₹{pnl:.0f}", delta=pnl)
        with e5:
            auto_result = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "NO TRADE"
            st.metric("Auto Result", auto_result)

    # Result & remarks
    st.markdown("#### 📝 Trade Outcome & Notes")
    r1, r2 = st.columns(2)
    with r1:
        default_result = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
        result_index = ["WIN","LOSS","BREAKEVEN"].index(default_result)
        result = st.selectbox("Result Override (auto-set)", ["WIN","LOSS","BREAKEVEN"], index=result_index)
    with r2:
        st.write("")

    remarks_options = [
        "DISCIPLINE – No trade signal",
        "DISCIPLINE – IV too high",
        "DISCIPLINE – Gap > 100",
        "DISCIPLINE – Wednesday ban",
        "DISCIPLINE – Monthly zone filter",
        "PROCESS WIN – Executed as per plan",
        "PROCESS LOSS – Executed as per plan",
        "VIOLATION – Early exit before 2 PM",
        "VIOLATION – Did not respect SL",
        "VIOLATION – Discretionary exit at level",
        "MARKET – Trend day",
        "MARKET – Choppy / rangebound",
        "MARKET – Reversal from daily resistance",
        "MARKET – Support broken cleanly",
        "SYSTEM – Entry good, exit needs work",
        "SYSTEM – Consider adjusting TP",
        "SYSTEM – TF misaligned but trade ok",
    ]

    st.markdown("**Remarks Category**")
    remarks_category = st.selectbox("Select reason/category", [""] + remarks_options, index=0)

    st.markdown("**Additional Notes (Optional)**")
    additional_notes = st.text_area("Add extra details if needed", "", height=50)

    remarks = remarks_category
    if additional_notes.strip():
        remarks = f"{remarks_category} | {additional_notes}" if remarks_category else additional_notes

    st.divider()

    if st.button("✅ Save Trade & Log", use_container_width=True):
        row = {c: None for c in COLUMNS}
        row.update({
            "Date": date,
            "Day": day,
            "Previous day Close": int(prev_close),
            "Gap Points": gap_points,
            "Nifty Open": int(today_open),
            "Nifty Spot at 9:45 AM": int(spot_945),
            "Trigger High (+0.3%)": trig_high,
            "Trigger Low (-0.3%)": trig_low,
            "IV Percentile at 9:45 AM": int(iv_945),
            "Trade Signal": signal,
            "Buy Strike": int(buy_strike),
            "Sell Strike": int(sell_strike),
            "Buy Strike Entry Premium": buy_entry,
            "Sell Strike Entry Premium": sell_entry,
            "Buy Strike Exit Premium": buy_exit,
            "Sell Strike Exit Premium": sell_exit,
            "Debit Paid": net_spread * qty,
            "Exit Price": net_spread_sell * qty,
            "Qty": int(qty),
            "PnL": pnl,
            "Result": result,
            "Remarks": remarks,
            "TF_Monthly_Zone": tf_monthly,
            "TF_Near_Daily_SR": tf_daily,
            "TF_Hourly_Trend": tf_hourly,
            "TF_Trade_Allowed": trade_allowed,
        })
        append_row(row)
        st.success(f"✅ Trade saved! PnL: ₹{pnl:.0f} | Result: {result}")
        st.balloons()

# ---------- Page 2: Log (trade history view only) ----------

def page_log():
    st.header("📋 Trade Log")

    df = load_data()

    if df.empty:
        st.info("No trades logged yet.")
        return

    # Summary stats at top
    st.markdown("### 📊 Summary Statistics")
    total_records = len(df)
    total_trades = len(df[df["Result"].isin(["WIN","LOSS","BREAKEVEN"])])
    no_trades = len(df[df["Result"] == "NO TRADE"])
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Records", total_records)
    col2.metric("Executed Trades", total_trades)
    col3.metric("No-Trade Days", no_trades)

    st.markdown("---")
    
    # All records table - select specific columns to display
    st.markdown("### 📈 All Records")
    display_columns = [
        "Date", "Day", "Previous day Close", "Nifty Spot at 9.45 AM", 
        "Trade Signal", "Buy Strike", "Sell Strike",
        "Buy Strike Entry Premium", "Sell Strike Entry Premium",
        "Buy Strike Exit Premium", "Sell Strike Exit Premium",
        "Qty", "PnL", "Result", "Remarks"
    ]
    df_display = df[[col for col in display_columns if col in df.columns]]
    st.dataframe(df_display, width='stretch', height=500)

        # Download current log as CSV (so you can back it up to GitHub)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Download full CSV (backup)",
        data=csv_bytes,
        file_name="Trade-Journal-2025-26-Journal.csv",
        mime="text/csv",
        use_container_width=True,
    )
    st.markdown("---")
    st.markdown("### 🗑️ Manage Records")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("🗑️ Delete Last Entry", width='stretch'):
            if len(df) > 0:
                df_updated = df.iloc[:-1]  # Remove last row
                save_data(df_updated)
                st.success("✅ Last entry deleted successfully!")
                st.rerun()
            else:
                st.warning("⚠️ No entries to delete")
    with col2:
        st.info("💡 Click to remove the most recent trade record. This action cannot be undone.")
    with col3:
        st.write("")  # Spacer

# ---------- Page 3: Dashboard ----------

def page_dashboard():
    st.header("📊 Dashboard")

    df = load_data()
    trade_df = df[df["Result"].isin(["WIN","LOSS","BREAKEVEN"])].copy()

    if trade_df.empty:
        st.info("No trades logged yet.")
        return

    total_trades = len(trade_df)
    wins = (trade_df["Result"] == "WIN").sum()
    losses = (trade_df["Result"] == "LOSS").sum()
    breakevens = (trade_df["Result"] == "BREAKEVEN").sum()
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0

    total_pnl = trade_df["PnL"].sum()
    avg_win = trade_df.loc[trade_df["Result"]=="WIN","PnL"].mean()
    avg_loss = trade_df.loc[trade_df["Result"]=="LOSS","PnL"].mean()

    profit_factor = None
    loss_sum = trade_df.loc[trade_df["Result"]=="LOSS","PnL"].sum()
    win_sum = trade_df.loc[trade_df["Result"]=="WIN","PnL"].sum()
    if loss_sum != 0:
        profit_factor = abs(win_sum / loss_sum)

    # Key Metrics - Better aligned layout
    st.subheader("🎯 Key Metrics")

    # First row: Total Trades, Wins, Losses, Total P&L
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Trades", int(total_trades))
    c2.metric("🏆 Wins", int(wins))
    c3.metric("📉 Losses", int(losses))
    c4.metric("💰 Total P&L", f"₹{total_pnl:.0f}")

    # Second row: Win Rate, Avg Win, Avg Loss, Profit Factor
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Win Rate", f"{win_rate:.1f}%")
    c6.metric("Avg Win", f"₹{avg_win:.1f}" if not pd.isna(avg_win) else "–")
    c7.metric("Avg Loss", f"₹{avg_loss:.1f}" if not pd.isna(avg_loss) else "–")
    c8.metric("Profit Factor", f"{profit_factor:.2f}" if profit_factor else "–")

    st.markdown("---")

    # Charts - Performance Charts moved up
    st.markdown("### 📈 Performance Charts")
    
    chart_col1, chart_col2 = st.columns(2, gap="medium")
    
    with chart_col1:
        # Cumulative P&L chart with axis titles using Plotly
        trade_df["CumPnL"] = trade_df["PnL"].cumsum()
        trade_df_sorted = trade_df.reset_index(drop=True)
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=trade_df_sorted["CumPnL"],
            mode='lines+markers',
            name='Cumulative P&L',
            line=dict(color='#1f77b4', width=2),
            fill='tozeroy',
            fillcolor='rgba(31, 119, 180, 0.2)'
        ))
        fig.update_layout(
            title="Cumulative P&L Over Trades",
            xaxis_title="Trade Number",
            yaxis_title="Cumulative P&L (₹)",
            hovermode='x unified',
            height=400
        )
        st.plotly_chart(fig, use_container_width=True, key="cum_pnl_chart")
    
    with chart_col2:
        # Win/Loss Donut chart with colors
        labels = ['Wins', 'Losses']
        values = [wins, losses]
        colors = ['#2ecc71', '#e74c3c']  # Green for wins, Red for losses
        
        fig_donut = go.Figure(data=[go.Pie(
            labels=labels,
            values=values,
            hole=0.4,
            marker=dict(colors=colors),
            hovertemplate='<b>%{label}</b><br>Count: %{value}<extra></extra>'
        )])
        fig_donut.update_layout(
            title="Win/Loss Distribution",
            height=400
        )
        st.plotly_chart(fig_donut, use_container_width=True, key="winloss_donut")

    st.markdown("---")
    
    # Activity Analysis - moved up
    st.markdown("### 📅 Activity Analysis")
    df_all = load_data()
    total_days = len(df_all)
    total_trade_days = len(trade_df)
    no_trade_days = total_days - total_trade_days
    
    activity_col = st.columns(1)[0]
    with activity_col:
        fig_days = go.Figure()
        fig_days.add_trace(go.Bar(
            x=['Total Days', 'Trade Days', 'No-Trade Days'],
            y=[total_days, total_trade_days, no_trade_days],
            marker=dict(color=['#3498db', '#2ecc71', '#f39c12']),
            text=[total_days, total_trade_days, no_trade_days],
            textposition='auto'
        ))
        fig_days.update_layout(
            title="Days Breakdown",
            yaxis_title="Number of Days",
            height=400,
            showlegend=False
        )
        st.plotly_chart(fig_days, use_container_width=True, key="days_breakdown")

    st.markdown("---")

    # No-Trade Analysis - moved up
    st.markdown("### ⏭️ No-Trade Analysis")
    no_trade_df = df_all[df_all["Result"] == "NO TRADE"]
    if not no_trade_df.empty:
        no_trade_reasons = no_trade_df["Trade Signal"].value_counts()
        fig_reasons = go.Figure()
        fig_reasons.add_trace(go.Bar(
            x=no_trade_reasons.index,
            y=no_trade_reasons.values,
            marker=dict(color='#e74c3c'),
            text=no_trade_reasons.values,
            textposition='auto'
        ))
        fig_reasons.update_layout(
            title="No-Trade Reasons",
            xaxis_title="Reason",
            yaxis_title="Count",
            height=400,
            xaxis_tickangle=-45
        )
        st.plotly_chart(fig_reasons, use_container_width=True, key="notrade_reasons")
    else:
        st.info("No no-trade records found.")

    st.markdown("---")

    # --- 1) Expectancy (₹ per trade) ---
    # Win% and Loss% (ignoring breakeven)
    traded = trade_df[trade_df["Result"].isin(["WIN", "LOSS"])]
    if not traded.empty:
        win_trades = traded[traded["Result"] == "WIN"]
        loss_trades = traded[traded["Result"] == "LOSS"]

        win_pct = len(win_trades) / len(traded) if len(traded) else 0
        loss_pct = len(loss_trades) / len(traded) if len(traded) else 0

        avg_win_for_exp = win_trades["PnL"].mean() if not win_trades.empty else 0
        avg_loss_for_exp = loss_trades["PnL"].mean() if not loss_trades.empty else 0

        expectancy = (win_pct * avg_win_for_exp) - (loss_pct * avg_loss_for_exp)
    else:
        expectancy = 0

    st.subheader("Additional Edge Metrics")
    st.metric("Expectancy (₹ per trade)", f"{expectancy:.1f}")

    # --- 2) Rule-adherence rate (%), based on Remarks tags ---
    # Assumption: remarks containing 'PROCESS' = followed rules,
    # remarks containing 'VIOLATION' = rule broken.
    remarks_series = trade_df["Remarks"].fillna("").astype(str)

    process_mask = remarks_series.str.contains("PROCESS", case=False, na=False)
    violation_mask = remarks_series.str.contains("VIOLATION", case=False, na=False)

    total_evaluated = (process_mask | violation_mask).sum()
    if total_evaluated > 0:
        adherence_rate = process_mask.sum() / total_evaluated * 100
        st.metric("Rule-Adherence Rate", f"{adherence_rate:.1f}%")
    else:
        st.info("Rule-Adherence Rate: not enough tagged remarks yet (PROCESS / VIOLATION).")

    # ========= STRUCTURE / REGIME AWARENESS =========

    # --- A) Performance by Weekday (Win rate + P&L) ---
    st.subheader("Structure: Performance by Weekday")

    if "Day" in trade_df.columns:
        # Order weekdays
        order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        tmp = trade_df.copy()
        tmp = tmp[tmp["Day"].isin(order)]

        if not tmp.empty:
            # Total P&L by day
            pnl_by_day = tmp.groupby("Day")["PnL"].sum().reindex(order)

            # Win-rate by day (only WIN/LOSS)
            wl = tmp[tmp["Result"].isin(["WIN","LOSS"])]
            winrate_by_day = (
                wl.assign(is_win = wl["Result"].eq("WIN").astype(int))
                  .groupby("Day")["is_win"]
                  .mean()
                  .reindex(order) * 100
            )

            # Show two charts
            st.write("**P&L by Weekday (₹)**")
            st.bar_chart(pnl_by_day.dropna())

            st.write("**Win Rate by Weekday (%)**")
            st.bar_chart(winrate_by_day.dropna())
        else:
            st.info("No weekday data to display yet.")
    else:
        st.info("Column 'Day' not found for weekday analysis.")

    # --- B) Performance by Signal / Type ---
    st.subheader("Structure: Performance by Signal / Type")

    # CALL vs PUT spreads
    if "Trade Signal" in trade_df.columns:
        sig_pnl = trade_df.groupby("Trade Signal")["PnL"].sum()
        sig_pnl = sig_pnl.loc[[s for s in ["CALL","PUT","NONE"] if s in sig_pnl.index]]
        if not sig_pnl.empty:
            st.write("**Total P&L by Signal (CALL / PUT / NONE)**")
            st.bar_chart(sig_pnl)
    else:
        st.info("Column 'Trade Signal' not found.")

    # Trend day vs Range day from Remarks tags
    remarks = trade_df["Remarks"].fillna("").astype(str)
    is_trend = remarks.str.contains("Trend day", case=False, na=False)
    is_range = remarks.str.contains("rangebound", case=False, na=False)

    trend_pnl = trade_df.loc[is_trend, "PnL"].sum()
    range_pnl = trade_df.loc[is_range, "PnL"].sum()

    if is_trend.any() or is_range.any():
        st.write("**Trend vs Range Day P&L (from Remarks tags)**")
        st.bar_chart(
            pd.Series(
                {"Trend day": trend_pnl, "Range day": range_pnl}
            )
        )
    else:
        st.info("No 'Trend day' / 'rangebound' tags found in Remarks yet.")

    # --- C) Performance by IV regime (Expectancy per bucket) ---
    st.subheader("Regime: Performance by IV Regime")

    iv_col = "IV Percentile at 9.45 AM"
    if iv_col in trade_df.columns:
        iv_df = trade_df.copy()
        iv_df = iv_df[pd.notna(iv_df[iv_col])]

        if not iv_df.empty:
            # Define IV buckets
            bins = [0, 33, 66, 100]
            labels = ["Low (0-33)", "Medium (34-66)", "High (67-100)"]
            iv_df["IV_Bucket"] = pd.cut(iv_df[iv_col], bins=bins, labels=labels, include_lowest=True)

            # Only WIN/LOSS for expectancy
            iv_wl = iv_df[iv_df["Result"].isin(["WIN","LOSS"])]

            def calc_expectancy(df_bucket):
                if df_bucket.empty:
                    return 0.0
                wins_b = df_bucket[df_bucket["Result"] == "WIN"]
                losses_b = df_bucket[df_bucket["Result"] == "LOSS"]
                win_pct_b = len(wins_b) / len(df_bucket) if len(df_bucket) else 0
                loss_pct_b = len(losses_b) / len(df_bucket) if len(df_bucket) else 0
                avg_win_b = wins_b["PnL"].mean() if not wins_b.empty else 0
                avg_loss_b = losses_b["PnL"].mean() if not losses_b.empty else 0
                return (win_pct_b * avg_win_b) - (loss_pct_b * avg_loss_b)

            exp_by_bucket = iv_wl.groupby("IV_Bucket").apply(calc_expectancy)
            exp_by_bucket = exp_by_bucket.reindex(labels)

            st.write("**Expectancy (₹ per trade) by IV Regime**")
            st.bar_chart(exp_by_bucket.fillna(0))
        else:
            st.info("No IV data available for regime analysis.")
    else:
        st.info(f"Column '{iv_col}' not found; cannot compute IV regimes.")

# ---------- Main ----------

def set_custom_background():
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #9F8383;  /* change to any hex colour */
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

PAGES = {
    "1. Trade Validation": page_validation,
    "2. Log": page_log,
    "3. Dashboard": page_dashboard,
}

def main():
    set_custom_background()
    st.set_page_config(page_title="Nifty Trading Journal", page_icon="📈", layout="wide")
    
    # Custom styling
    st.markdown("""
    <style>
    .main {
        padding-top: 2rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #1f77b4;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.sidebar.title("📊 Nifty Journal")
    st.sidebar.markdown("---")
    choice = st.sidebar.radio("Navigation", list(PAGES.keys()))
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("""
    ### About
    Trade Signal & Entry System for Nifty Options
    """)
    
    PAGES[choice]()

if __name__ == "__main__":
    main()
