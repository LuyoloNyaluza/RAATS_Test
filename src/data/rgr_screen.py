"""
src/data/rgr_screen.py

RGR screen: decides whether a ticker may JOIN the active list.

Called by DynamicTradingManager._passes_rgr_gate() for the initial top-10 and
for every waiting-list promotion, before any news is fetched or scored.

Why this is not RGRCalculator
-----------------------------
RGRCalculator measures an OPEN position (RoR since entry). At screening time
there is no entry, so RoR from entry is always 0. This module applies the same
formula to a TRAILING window instead:

    direction = sign of the price gradient (same functions and deadband the
                RiskManager uses, so the screen and the executor agree)
    RoR       = direction * (close_now / close_N_days_ago - 1)
    RPR       = benchmark return over the SAME N days
                + risk_tolerance * ATR%                (ATR / close, unitless)
    vol_ratio = ATR_now / mean(last `vol_lookback` ATR values)
    RGR       = (RoR - RPR) * (1 + k_factor / vol_ratio)

    PASS  if direction != 0 and RGR > threshold

Fixes relative to rgr_calculator.py: ATR is converted to a fraction of price
(the old penalty scaled with share price); the benchmark return covers the
same horizon as RoR; benchmark data is actually used; no state leaks between
tickers.

Failure policy: data problems return {"passed": None, "error": ...}. The
caller treats that as "allowed" (fail open). A ticker is only REJECTED when
the numbers were computed and failed.

Look-ahead: every series is cut at `as_of` before use.
"""

import logging
import os
from typing import Any, Callable, Dict, Optional

import numpy as np
import pandas as pd

from src.risk.risk_manager import (
    compute_gradient,
    direction_from_gradient,
    normalize_gradient,
)

logger = logging.getLogger("raats.data.rgr_screen")

INDICATOR_DIR = os.path.join("data", "processed", "indicators")

# Raw history per symbol, kept for the session so SPY is downloaded once.
_HISTORY_CACHE: Dict[str, pd.DataFrame] = {}


class _DataUnavailable(Exception):
    pass


def clear_cache() -> None:
    """Drop cached history (tests, or a long-running process across days)."""
    _HISTORY_CACHE.clear()


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Sorted, de-duplicated, timezone-naive DatetimeIndex."""
    df = df.copy()
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _load_history(symbol: str, as_of: Optional[str]) -> pd.DataFrame:
    """
    OHLC history for `symbol`, cut at `as_of`.

    Prefers the same cached indicator CSV the collector reads, so the screen
    and the agent see identical data. Falls back to a yfinance download
    (truncated at as_of, so it cannot leak the future).
    """
    raw = _HISTORY_CACHE.get(symbol)

    if raw is None:
        path = os.path.join(INDICATOR_DIR, f"{symbol}_indicators.csv")
        if os.path.exists(path):
            raw = pd.read_csv(path, index_col=0, parse_dates=True)
        else:
            try:
                import yfinance as yf
            except ImportError as exc:
                raise _DataUnavailable("yfinance not installed") from exc

            raw = yf.download(
                symbol, period="1y", progress=False, auto_adjust=False
            )
            if raw is None or raw.empty:
                raise _DataUnavailable(f"no data returned for {symbol}")
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)

        missing = {"High", "Low", "Close"} - set(raw.columns)
        if missing:
            raise _DataUnavailable(
                f"{symbol} history lacks column(s) {sorted(missing)}"
            )
        raw = _clean(raw)
        _HISTORY_CACHE[symbol] = raw

    df = raw
    if as_of is not None:
        df = df[df.index <= pd.Timestamp(as_of)]
    if df.empty:
        raise _DataUnavailable(f"no {symbol} data on or before {as_of}")
    return df


def _wilder_atr(df: pd.DataFrame, length: int) -> pd.Series:
    """Wilder-smoothed ATR (same smoothing family as pandas_ta ATRr_14)."""
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    prev_close = df["Close"].astype(float).shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1, skipna=False)
    return tr.iloc[1:].ewm(alpha=1.0 / length, adjust=False).mean()


def _skip(ticker: str, error: str) -> Dict[str, Any]:
    logger.info("RGR screen skipped for %s: %s", ticker, error)
    return {"passed": None, "error": error, "ticker": ticker}


def screen_candidate(
    ticker: str,
    as_of: Optional[str] = None,
    hold_days: int = 10,
    threshold: float = 0.0,
    benchmark: str = "SPY",
    gradient_lookback: int = 10,
    gradient_deadband: float = 0.3,
    atr_length: int = 14,
    vol_lookback: int = 10,
    k_factor: float = 1.0,
    risk_tolerance: float = 0.5,
    loader: Optional[Callable[[str, Optional[str]], pd.DataFrame]] = None,
) -> Dict[str, Any]:
    """
    Returns a diagnostics dict.

        passed     True / False, or None when the screen could not run
        rgr, ror, rpr, direction ("LONG" | "SHORT" | "NONE"), m_norm,
        ticker_return, benchmark_return, atr_pct, vol_ratio,
        vol_scaling, hold_days, data_end, reason, error

    `hold_days` is the trailing window N (in bars) for RoR and the benchmark.
    `loader(symbol, as_of)` can be injected for tests.
    """
    load = loader or _load_history

    try:
        df = _clean(load(ticker, as_of))
        bench = _clean(load(benchmark, as_of))
    except _DataUnavailable as exc:
        return _skip(ticker, str(exc))
    except Exception as exc:  # network, parse, ...
        return _skip(ticker, f"{type(exc).__name__}: {exc}")

    df = df.dropna(subset=["High", "Low", "Close"])
    need = max(
        atr_length + vol_lookback + 1, hold_days + 1, gradient_lookback + 1
    )
    if len(df) < need:
        return _skip(ticker, f"only {len(df)} bars, need {need}")

    closes = df["Close"].astype(float)
    atr_series = _wilder_atr(df, atr_length).dropna()
    if len(atr_series) < vol_lookback:
        return _skip(ticker, "ATR history too short")

    close_now = float(closes.iloc[-1])
    atr_now = float(atr_series.iloc[-1])
    if close_now <= 0 or not np.isfinite(atr_now) or atr_now <= 0:
        return _skip(ticker, "invalid price or ATR")

    # ---- direction: identical rule to RiskManager ----
    try:
        m = compute_gradient(closes.tolist(), gradient_lookback)
        m_norm = normalize_gradient(m, gradient_lookback, atr_now)
    except ValueError as exc:
        return _skip(ticker, f"gradient unavailable: {exc}")
    d = direction_from_gradient(m_norm, gradient_deadband)
    direction = {1: "LONG", -1: "SHORT", 0: "NONE"}[d]

    # ---- trailing returns over the same dates ----
    t_end = closes.index[-1]
    t_start = closes.index[-1 - hold_days]
    p_start = float(closes.iloc[-1 - hold_days])
    if p_start <= 0:
        return _skip(ticker, "invalid start price")
    ticker_return = close_now / p_start - 1.0

    bclose = bench["Close"].astype(float).dropna()
    b_end = bclose.asof(t_end)
    b_start = bclose.asof(t_start)
    if np.asarray(pd.isna(b_end)).item() or np.asarray(pd.isna(b_start)).item():
        return _skip(
            ticker, f"{benchmark} has no data covering {t_start.date()}..{t_end.date()}"
        )
    b_end_value = float(np.asarray(b_end).item())
    b_start_value = float(np.asarray(b_start).item())
    if (
        not np.isfinite(b_end_value)
        or not np.isfinite(b_start_value)
        or b_start_value <= 0
    ):
        return _skip(
            ticker, f"{benchmark} has no data covering {t_start.date()}..{t_end.date()}"
        )
    benchmark_return = b_end_value / b_start_value - 1.0

    # ---- RGR ----
    atr_pct = atr_now / close_now
    rpr = benchmark_return + risk_tolerance * atr_pct
    vol_ratio = atr_now / float(atr_series.iloc[-vol_lookback:].mean())
    vol_scaling = k_factor / vol_ratio

    ror = d * ticker_return
    rgr = (ror - rpr) * (1.0 + vol_scaling)

    diag: Dict[str, Any] = {
        "ticker": ticker,
        "passed": None,
        "error": None,
        "reason": "",
        "rgr": float(rgr),
        "ror": float(ror),
        "rpr": float(rpr),
        "direction": direction,
        "m_norm": float(m_norm),
        "ticker_return": float(ticker_return),
        "benchmark_return": float(benchmark_return),
        "atr_pct": float(atr_pct),
        "vol_ratio": float(vol_ratio),
        "vol_scaling": float(vol_scaling),
        "hold_days": hold_days,
        "data_end": str(t_end.date()),
    }

    if d == 0:
        diag["passed"] = False
        diag["reason"] = (
            f"no clear direction (|m_norm|={abs(m_norm):.3f} < {gradient_deadband})"
        )
        diag["rgr"] = 0.0
        diag["ror"] = 0.0
        return diag

    diag["passed"] = bool(rgr > threshold)
    diag["reason"] = (
        f"RGR {rgr:+.5f} {'>' if diag['passed'] else '<='} threshold {threshold}"
    )
    return diag
