

import os
import time
import pandas as pd
import pandas_ta as ta  # noqa: F401 (registers the .ta accessor on DataFrame)
import yfinance as yf


def fetch_price_data(tickers, start, end, pause=2.0):
    """Download OHLCV data for given tickers and date range.

    Args:
        tickers: list of ticker symbols.
        start, end: date range (anything pd.Timestamp-compatible).
        pause: seconds to wait between requests, to reduce rate-limiting.

    Returns:
        dict of {ticker: DataFrame}. Tickers with no data returned are
        omitted rather than included as empty DataFrames.
    """
    data_dict = {}
    for ticker in tickers:
        print(f'Fetching {ticker}...')
        df = yf.download(ticker, start=start, end=end, progress=False)

        if df is None:
            print(f'  WARNING: no data returned for {ticker} — skipping '
                  f'(check yfinance version / possible rate-limiting).')
            time.sleep(pause)
            continue

        # yfinance returns MultiIndex columns even for a single ticker —
        # flatten them so pandas_ta's .str column matching works.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if df.empty:
            print(f'  WARNING: no data returned for {ticker} — skipping '
                  f'(check yfinance version / possible rate-limiting).')
            time.sleep(pause)
            continue

        data_dict[ticker] = df
        time.sleep(pause)  # be gentle with Yahoo's endpoint between requests

    return data_dict


def add_technical_indicators(df):
    """Add SMA, EMA, RSI, MACD indicators to a single-ticker OHLCV DataFrame."""
    df.ta.sma(length=10, append=True)
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.ema(length=10, append=True)
    df.ta.ema(length=20, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    return df


def save_data(data_dict, base_dir, min_rows=50):
    """Save raw, full-indicator, and clean-indicator CSVs for each ticker.

    Args:
        data_dict: {ticker: DataFrame} as returned by fetch_price_data.
        base_dir: root output directory (e.g. 'data').
        min_rows: tickers with fewer rows than this are skipped, since the
                  50-period indicators would be entirely NaN anyway.

    Returns:
        list of (ticker, total_rows, clean_rows) tuples for reporting.
    """
    raw_dir = os.path.join(base_dir, 'raw', 'prices')
    proc_dir = os.path.join(base_dir, 'processed', 'indicators')
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(proc_dir, exist_ok=True)

    summary = []

    for ticker, df in data_dict.items():
        if df.empty or len(df) < min_rows:
            print(f'  Skipping {ticker}: insufficient rows ({len(df)}) for indicators.')
            continue

        # Raw prices
        df.to_csv(os.path.join(raw_dir, f'{ticker}_ohlcv.csv'))

        # Full indicators (keeps warm-up NaNs)
        df_with_ind = add_technical_indicators(df.copy())
        df_with_ind.to_csv(os.path.join(proc_dir, f'{ticker}_indicators.csv'))

        # Clean indicators (all NaNs dropped, ready for direct downstream use)
        df_clean = df_with_ind.dropna()
        df_clean.to_csv(os.path.join(proc_dir, f'{ticker}_indicators_clean.csv'))

        total_rows, clean_rows = len(df_with_ind), len(df_clean)
        summary.append((ticker, total_rows, clean_rows))

        print(
            f'Saved {ticker}: {total_rows} total rows, {clean_rows} clean rows '
            f'(dropped {total_rows - clean_rows}) -> {raw_dir} and {proc_dir}'
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