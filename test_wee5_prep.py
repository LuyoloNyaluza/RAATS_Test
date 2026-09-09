import os
import time
import pandas as pd
import yfinance as yf
import pandas_ta as ta

data = None

tickers = [
    "TSLA", "AAPL", "MSFT", "GOOGL", "AMZN",
    "NVDA", "META", "NFLX", "AMD", "INTC",
]

# Change this once - both the download and the saved filename below
# reference this same variable, so they can never drift out of sync.
PERIOD = "6mo"

print("Testing yfinance and pandas-ta setup:")
print("=" * 50)

os.makedirs("data/raw/market", exist_ok=True)

succeeded = []
failed = []

for ticker in tickers:
    print(f"\nProcessing {ticker}...")
    print("-" * 40)

    try:
        data = yf.download(ticker, period=PERIOD, progress=False)

        if data is not None and isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        if data is not None and not data.empty:
            print(f"Downloaded {len(data)} rows for {ticker}")

            data.ta.rsi(append=True)
            data.ta.macd(append=True)
            data.ta.bbands(append=True)
            print(f"Technical indicators calculated for {ticker}")
            print(data.tail(3))

            filename = f"data/raw/market/{ticker}_{PERIOD}.csv"
            data.to_csv(filename)
            print(f"Saved: {filename}")
            succeeded.append(ticker)
        else:
            print(f"No market data returned for {ticker}")
            failed.append(ticker)

    except Exception as e:
        print(f"Error processing {ticker}: {e}")
        failed.append(ticker)

    # Small pause between requests - reduces the chance of Yahoo
    # rate-limiting a burst of 10 sequential downloads.
    time.sleep(1)

print("\n" + "=" * 50)
print("Market data collection completed.")
print(f"Succeeded: {len(succeeded)}/{len(tickers)} -> {succeeded}")
if failed:
    print(f"Failed: {len(failed)}/{len(tickers)} -> {failed}")