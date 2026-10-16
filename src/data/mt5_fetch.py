"""
MetaTrader5 data fetching utilities for RAATS.

This module provides a thin wrapper around the MetaTrader5 Python package
to fetch historical and live data. It does not handle initialization or
shutdown of the MT5 connection; the caller must ensure that MetaTrader5
is initialized and the appropriate account is selected before calling
these functions.

Typical usage (in a script or strategy):
    import MetaTrader5 as mt5
    from src.data.mt5_fetch import get_historical_rates, get_latest_tick

    # Initialize MT5 (once per session)
    if not mt5.initialize():
        print("MT5 initialize() failed")
        mt5.shutdown()
        # handle error

    # Fetch data
    rates = get_historical_rates(symbol="EURUSD", timeframe=mt5.TIMEFRAME_H1, count=1000)
    tick = get_latest_tick(symbol="EURUSD")

    # Shutdown MT5 (when done)
    mt5.shutdown()
"""

from typing import Optional, List, Dict, Any
import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # type: ignore
    # The functions below will raise an error if called without the package.


def _ensure_mt5_available() -> None:
    if mt5 is None:
        raise ImportError(
            "MetaTrader5 package is not installed. Install it with: "
            "pip install MetaTrader5"
        )


def get_historical_rates(
    symbol: str,
    timeframe: int,
    count: int = 1000,
    start_pos: int = 0,
) -> Optional[pd.DataFrame]:
    """
    Fetch historical bar (OHLCV) data from MetaTrader5.

    Parameters
    ----------
    symbol : str
        The symbol to fetch, e.g., "EURUSD".
    timeframe : int
        MT5 timeframe constant (e.g., mt5.TIMEFRAME_H1).
    count : int, default 1000
        Number of bars to retrieve.
    start_pos : int, default 0
        Start position (0 means the most recent bar).

    Returns
    -------
    pandas.DataFrame or None
        DataFrame with columns ['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume'].
        Returns None if no data is received or an error occurs.
    """
    _ensure_mt5_available()
    rates = mt5.copy_rates_from_pos(symbol, timeframe, start_pos, count)
    if rates is None:
        print(f"No rates returned for {symbol}, error: {mt5.last_error()}")
        return None
    df = pd.DataFrame(rates)
    # Convert time to datetime
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df


def get_latest_tick(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the latest tick for a symbol.

    Parameters
    ----------
    symbol : str
        The symbol to fetch, e.g., "EURUSD".

    Returns
    -------
    dict or None
        Dictionary with tick information (time, bid, ask, last, volume, etc.)
        Returns None if no tick is available.
    """
    _ensure_mt5_available()
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"No tick for {symbol}, error: {mt5.last_error()}")
        return None
    # Convert the named tuple to a dict
    return tick._asdict()


def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetch symbol information (e.g., contract size, tick size, etc.).

    Parameters
    ----------
    symbol : str
        The symbol to query.

    Returns
    -------
    dict or None
        Symbol information as a dictionary, or None if not found.
    """
    _ensure_mt5_available()
    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"Symbol info not found for {symbol}, error: {mt5.last_error()}")
        return None
    return info._asdict()


if __name__ == "__main__":
    # Simple self-test when run as a script.
    # This block is for demonstration and will not run when imported.
    if mt5 is None:
        print("MetaTrader5 package not installed. Skipping self-test.")
    else:
        if not mt5.initialize():
            print("MT5 initialize() failed, error:", mt5.last_error())
        else:
            print("MT5 initialized successfully.")
            # Example: get symbol info for EURUSD
            info = get_symbol_info("EURUSD")
            if info:
                print("Symbol info for EURUSD:", info)
            # Example: get latest tick
            tick = get_latest_tick("EURUSD")
            if tick:
                print("Latest tick for EURUSD:", tick)
            # Example: get 5 hourly bars
            rates = get_historical_rates("EURUSD", mt5.TIMEFRAME_H1, count=5)
            if rates is not None:
                print("Last 5 hourly bars for EURUSD:")
                print(rates[['time', 'open', 'high', 'low', 'close']])
            mt5.shutdown()