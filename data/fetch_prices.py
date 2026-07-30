import yfinance as yf
import pandas as pd
import os
from datetime import datetime, timedelta

def fetch_price_data(
        symbols: List[str],
        period: str = "60d",
        interval: str = "1d",
        save_to_csv: bool = True
    ) -> dict:
        """
        Fetch price data for given symbols
        Args:
            symbols: List of ticker symbols (e.g., ['AAPL', 'MSFT'])
            period: Data period (e.g., '1d', '5d', '1mo', '60d')
            interval: Data interval (e.g., '1m', '5m', '1h', '1d')
            save_to_csv: Whether to save data to CSV files
        Returns:
            Dictionary of DataFrames keyed by symbol
        """
        data = {}
        data_dir = "src/data"
        os.makedirs(data_dir, exist_ok=True)

        for symbol in symbols:
            try:
                print(f"Fetching {symbol}...", end=" ")
                ticker = yf.Ticker(symbol)
                df = ticker.history(period=period, interval=interval)

                if df.empty:
                    print("❌ No data returned")
                    continue

                # Clean column names
                df.columns = [col.lower().replace(' ', '_') for col in df.columns]

                if save_to_csv:
                    filename = f"{data_dir}/{symbol}{period}{interval}.csv"
                    df.to_csv(filename)
                    print(f"✅ Saved to {filename} ({df.shape[0]} rows)")
                else:
                    print(f"✅ Fetched ({df.shape[0]} rows)")

                data[symbol] = df

            except Exception as e:
                print(f"❌ Error fetching {symbol}: {str(e)}")

        return data

if name == "main":
        # Example usage
        symbols = ["AAPL", "MSFT", "GOOGL"]
        fetch_price_data(symbols, period="5d", interval="1d")