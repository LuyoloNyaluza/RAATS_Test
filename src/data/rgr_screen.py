"""
src/data/rgr_screen.py

Pre-trade RGR screen for candidates BEFORE they join the active list.

RGRCalculator is built for an OPEN position (it needs an entry price and a
direction).  A candidate has neither, so we build a hypothetical position:

    entry price : close `hold_days` trading days ago
    direction   : +1 if close > SMA(10) else -1   (trend direction)

RGR = (RoR - RPR) * (1 + volatility scaling) is then computed with the real
calculator.  RGR > threshold  ->  the recent move has beaten the hurdle in
the direction of the trend  ->  candidate passes.

Two unit fixes are applied on the way in (RGRCalculator is not modified):

  * ATR is passed as a FRACTION OF PRICE (ATR / close).  RGRCalculator adds
    ATR * risk_tolerance to a *return*, so a raw ATR in price units would make
    a $300 stock's hurdle enormous and EURUSD's hurdle ~zero.
  * A fresh calculator is built for every ticker, because RGRCalculator keeps
    its benchmark closes in an attribute that is never cleared between
    positions.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from src.strategist.rgr_calculator import RGRCalculator

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None


ATR_PERIOD = 14
SMA_PERIOD = 10
WARMUP_BARS = 20          # bars replayed into the calculator (needs >= 10)


# ------------------------------------------------------------------
# DATA
# ------------------------------------------------------------------

def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance returns MultiIndex columns for single tickers in new versions."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def download_history(
    ticker: str,
    as_of: Optional[str] = None,
    calendar_days: int = 200,
) -> pd.DataFrame:
    """Daily OHLC for `ticker`, ending on `as_of` (inclusive) or today."""
    if yf is None:
        raise ImportError("yfinance is required for RGR screening.")

    end = (
        pd.Timestamp(as_of) + timedelta(days=1)
        if as_of
        else pd.Timestamp(datetime.now()) + timedelta(days=1)
    )
    start = end - timedelta(days=calendar_days)

    df = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        progress=False,
        auto_adjust=False,
    )
    if df is None or df.empty:
        raise ValueError(f"No price history for {ticker}.")
    return _flatten(df).dropna(subset=["Close"])


# ------------------------------------------------------------------
# CORE (pure function - easy to test with synthetic data)
# ------------------------------------------------------------------

def _atr_fraction(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return (tr.rolling(period).mean() / df["Close"]).dropna()


def evaluate_rgr(
    df: pd.DataFrame,
    benchmark: pd.DataFrame,
    hold_days: int = 5,
    threshold: float = 0.0,
    k_factor: float = 1.0,
    risk_tolerance: float = 0.02,
) -> Dict[str, Any]:
    """Compute RGR for a hypothetical position on `df`. Never raises on
    thin data - returns passed=None with an 'error' instead."""

    atr = _atr_fraction(df)
    need = max(hold_days + 1, SMA_PERIOD, WARMUP_BARS)
    if len(df) < ATR_PERIOD + need or len(atr) < WARMUP_BARS:
        return {"passed": None, "rgr": None, "error": "insufficient history"}

    close = df["Close"].astype(float)
    bench_close = (
        benchmark["Close"].astype(float)
        .reindex(close.index)
        .ffill()
        .bfill()
    )
    if bench_close.isna().any():
        return {"passed": None, "rgr": None, "error": "benchmark unavailable"}

    last = float(close.iloc[-1])
    entry = float(close.iloc[-(hold_days + 1)])
    sma = float(close.tail(SMA_PERIOD).mean())
    direction = 1 if last > sma else -1

    calc = RGRCalculator(k_factor=k_factor, risk_tolerance=risk_tolerance)
    calc.initialize_position(
        entry_price=entry,
        direction=direction,
        benchmark_data=pd.DataFrame({"Close": bench_close}),
    )

    # Warm up ATR history + benchmark closes the way a live loop would.
    for ts in atr.index[-WARMUP_BARS:]:
        calc.update_market_data(
            current_price=float(close.loc[ts]),
            current_atr=float(atr.loc[ts]),
            benchmark_close=float(bench_close.loc[ts]),
        )

    rgr, diag = calc.calculate_rgr(
        current_price=last,
        current_atr=float(atr.iloc[-1]),
        benchmark_close=float(bench_close.iloc[-1]),
    )

    diag.update(
        {
            "rgr": rgr,
            "passed": bool(rgr > threshold),
            "threshold": threshold,
            "direction": "LONG" if direction == 1 else "SHORT",
            "entry_price": entry,
            "last_price": last,
            "hold_days": hold_days,
        }
    )
    return diag


# ------------------------------------------------------------------
# PUBLIC ENTRY POINT
# ------------------------------------------------------------------

def screen_candidate(
    ticker: str,
    as_of: Optional[str] = None,
    benchmark_ticker: str = "SPY",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Download data and run evaluate_rgr. Raises on download errors so the
    caller decides whether to fail open or closed."""
    df = download_history(ticker, as_of)
    bench = download_history(benchmark_ticker, as_of)
    result = evaluate_rgr(df, bench, **kwargs)
    result["ticker"] = ticker
    return result
