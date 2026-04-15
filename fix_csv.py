import pandas as pd

# Read the CSV
df = pd.read_csv('Trade-Journal-2025-26-Journal.csv')

print(f"Total records: {len(df)}")
print("\nLast 5 records:")
print(df[['Date', 'Trade Signal', 'Result', 'No_Trade_Reason']].tail())

# Find and fix March 9th and 10th NO TRADE records
for idx, row in df.iterrows():
    if row['Date'] in ['09/Mar/2026', '10/Mar/2026'] and row['Result'] == 'NO TRADE':
        reason = str(row['No_Trade_Reason'])
        print(f"\nFound NO TRADE on {row['Date']}")
        print(f"  Current Trade Signal: {row['Trade Signal']}")
        print(f"  Reason: {reason}")
        
        # Update Trade Signal based on reason
        if 'IV' in reason:
            df.at[idx, 'Trade Signal'] = '⚠️ NO TRADE (IV TOO HIGH)'
        elif 'Gap' in reason:
            df.at[idx, 'Trade Signal'] = '⚠️ NO TRADE (GAP > 100)'
        elif 'Hourly' in reason:
            df.at[idx, 'Trade Signal'] = 'NO TRADE (HOURLY MISALIGNED)'
        elif 'monthly' in reason.lower():
            df.at[idx, 'Trade Signal'] = 'NO TRADE (MONTHLY ZONE)'
        elif '0.3%' in reason:
            df.at[idx, 'Trade Signal'] = 'NO TRADE (NO SIGNAL)'
        
        print(f"  Updated to: {df.at[idx, 'Trade Signal']}")

# Save back
df.to_csv('Trade-Journal-2025-26-Journal.csv', index=False)
print("\n✅ CSV updated successfully!")
print("\nUpdated records:")
print(df[df['Date'].isin(['09/Mar/2026', '10/Mar/2026'])][['Date', 'Trade Signal', 'Result', 'No_Trade_Reason']])
