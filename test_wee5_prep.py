import os
import pandas as pd
import yfinance as yf
import pandas_ta as ta

# Initialize so static analyzers and runtime checks
# do not see an unbound variable.
data = None

# List of stock tickers
tickers = [
    "TSLA",
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "NFLX",
    "AMD",
    "INTC"
]

print("Testing yfinance and pandas-ta setup:")
print("=" * 50)

# Create directory for market data
os.makedirs("data/raw/market", exist_ok=True)

# Loop through all tickers
for ticker in tickers:

    print(f"\nProcessing {ticker}...")
    print("-" * 40)

    try:
        # Download 6 months of data
        data = yf.download(
            ticker,
            period="6mo",
            progress=False
        )

        # Fix MultiIndex columns if returned by yfinance
        if data is not None and isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Check whether data was downloaded
        if data is not None and not data.empty:

            print(f"Downloaded {len(data)} rows for {ticker}")

            # Calculate RSI
            data.ta.rsi(append=True)

            # Calculate MACD
            data.ta.macd(append=True)

            # Calculate Bollinger Bands
            data.ta.bbands(append=True)

            print(f"Technical indicators calculated for {ticker}")

            # Display the latest rows
            print(data.tail(3))

            # Save individual ticker data
            filename = f"data/raw/market/{ticker}_6mo.csv"

            data.to_csv(filename)

            print(f"Saved: {filename}")

        else:
            print(f"No market data returned for {ticker}")

    except Exception as e:
        print(f"Error processing {ticker}: {e}")


print("\n" + "=" * 50)
print("Market data collection completed.")
print(f"Total tickers processed: {len(tickers)}")