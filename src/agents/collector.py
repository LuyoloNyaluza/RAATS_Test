import os
from datetime import datetime, timedelta

import pandas as pd
import pandas_ta as ta  
import yfinance as yf


def collect_market_data(ticker: str = "AAPL") -> dict:
    data_path = f"data/processed/indicators/{ticker}_indicators.csv"

    if not os.path.exists(data_path):
        # Fallback: download recent data directly.
        # Use 90 days, not 7 — RSI(14) needs at least 14 rows of history
        # to produce a non-NaN value at all; 7 days guarantees NaN.
        end = datetime.now()
        start = end - timedelta(days=90)

        df = yf.download(ticker, start=start, end=end, progress=False)
        if df is None or df.empty:
            raise RuntimeError(
                f"No data returned for {ticker} — check ticker symbol, "
                f"yfinance version, or possible rate limiting."
            )

        # yfinance returns MultiIndex columns even for a single ticker;
        # flatten them so pandas_ta's column matching works (same fix
        # as src/data/market_data.py).
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.ta.sma(length=10, append=True)
        df.ta.rsi(length=14, append=True)

        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        df.to_csv(data_path)

    df = pd.read_csv(data_path, index_col=0, parse_dates=True)

    if df.empty:
        raise RuntimeError(f"{data_path} exists but contains no rows.")

    latest = df.iloc[-1]

    if pd.isna(latest.get("RSI_14")) or pd.isna(latest.get("SMA_10")):
        raise RuntimeError(
            f"Latest row for {ticker} has NaN indicators — not enough "
            f"history yet. Check the data source or widen the fetch window."
        )

    latest_timestamp = pd.to_datetime(df.index[-1])
    return {
        "close": float(latest["Close"]),
        "sma_10": float(latest["SMA_10"]),
        "rsi": float(latest["RSI_14"]),
        "timestamp": latest_timestamp.isoformat(),
    }


def collect_sentiment(ticker: str = "AAPL") -> float:
    # Placeholder: in later weeks we'll fetch from real news/RSS sentiment
    # (see src/data/fetch_news.py + score_sentiment.py). For now, simulate
    # sentiment based on RSI as a rough proxy.
    data = collect_market_data(ticker)  # <-- was missing `ticker`, always defaulted to AAPL
    rsi = data["rsi"]
    sentiment = (rsi - 50) / 50  # RSI 0-100 -> -1..1
    return max(-1.0, min(1.0, sentiment))