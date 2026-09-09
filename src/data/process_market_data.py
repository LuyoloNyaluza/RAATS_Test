import pandas as pd
import pandas_ta as ta
import os
import time
import yfinance as yf


def fetch_price_data(tickers, start, end, pause=2.0):
    """Download OHLCV data for given tickers and date range, one at a time
    with a pause between requests to avoid Yahoo's rate limiting."""
    data_dict = {}
    for ticker in tickers:
        print(f'Fetching {ticker}...')
        df = yf.download(ticker, start=start, end=end, progress=False)

        # yfinance may return None or an empty result when the request fails or
        # is rate-limited; guard before accessing df.columns.
        if df is None:
            print(f'  WARNING: no data returned for {ticker} — skipping (likely rate-limited).')
            time.sleep(pause)
            continue

        # yfinance returns MultiIndex columns even for a single ticker —
        # flatten them so pandas_ta's .str column matching works
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if df.empty:
            print(f'  WARNING: no data returned for {ticker} — skipping (likely rate-limited).')
            time.sleep(pause)
            continue

        data_dict[ticker] = df
        time.sleep(pause)  # be gentle with Yahoo's endpoint between requests

    return data_dict


def add_technical_indicators(df):
    """Add SMA, EMA, RSI, MACD indicators to DataFrame."""
    df.ta.sma(length=10, append=True)
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.ema(length=10, append=True)
    df.ta.ema(length=20, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    return df


def save_data(data_dict, base_dir):
    """Save each ticker's DataFrame as CSV in base_dir/prices and base_dir/indicators.
    Saves both a full indicators file (with warm-up NaNs) and a clean version
    (all NaNs dropped) ready for direct use downstream."""
    prices_dir = os.path.join(base_dir, 'raw', 'prices')
    indicators_dir = os.path.join(base_dir, 'processed', 'indicators')
    os.makedirs(prices_dir, exist_ok=True)
    os.makedirs(indicators_dir, exist_ok=True)

    summary = []

    for ticker, df in data_dict.items():
        if df.empty or len(df) < 50:
            print(f'  Skipping {ticker}: insufficient rows ({len(df)}) for indicators.')
            continue

        # Save raw price data
        df.to_csv(os.path.join(prices_dir, f'{ticker}_ohlcv.csv'))

        # Add indicators and save full (with warm-up NaNs) version
        df_with_indicators = add_technical_indicators(df.copy())
        df_with_indicators.to_csv(os.path.join(indicators_dir, f'{ticker}_indicators.csv'))

        # Save clean version (all warm-up NaNs dropped) for downstream use
        df_clean = df_with_indicators.dropna()
        df_clean.to_csv(os.path.join(indicators_dir, f'{ticker}_indicators_clean.csv'))

        rows_total = len(df_with_indicators)
        rows_clean = len(df_clean)
        summary.append((ticker, rows_total, rows_clean))

        print(
            f'Saved {ticker}: {rows_total} total rows, '
            f'{rows_clean} clean rows (dropped {rows_total - rows_clean}) '
            f'-> {prices_dir} and {indicators_dir}'
        )

    return summary


if __name__ == '__main__':
    watchlist = ["TSLA", "AAPL", "MSFT", "GOOGL", "AMZN",
                 "NVDA", "META", "NFLX", "AMD", "INTC"]
    end = pd.Timestamp.now()
    start = end - pd.DateOffset(months=6)

    data = fetch_price_data(watchlist, start, end, pause=2.0)
    print(f'\nSuccessfully fetched {len(data)}/{len(watchlist)} tickers: {list(data.keys())}\n')

    summary = save_data(data, 'data')

    print('\n' + '=' * 50)
    print('Summary')
    print('=' * 50)
    for ticker, total, clean in summary:
        print(f'{ticker:6s} | total: {total:4d} | clean: {clean:4d} | dropped: {total - clean}')