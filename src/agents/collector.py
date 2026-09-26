
import glob
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import pandas_ta as ta  # noqa: F401 (registers the .ta accessor)
import yfinance as yf

logger = logging.getLogger("raats.agents.collector")

_ATR_COLUMN_CANDIDATES = ("ATRr_14", "ATRs_14", "ATRe_14", "ATR_14")


def _find_atr_column(df: pd.DataFrame):
    for name in _ATR_COLUMN_CANDIDATES:
        if name in df.columns:
            return name
    return None


def _ensure_atr(df: pd.DataFrame, length: int = 14):
    """Return (df, atr_column_name), computing ATR if not already present."""
    existing = _find_atr_column(df)
    if existing is not None:
        return df, existing

    required = {"High", "Low", "Close"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(
            f"Cannot compute ATR: missing column(s) {sorted(missing)}. "
            f"Re-run the data pipeline (src/data/market_data.py) for this ticker."
        )

    df = df.copy()
    df.ta.atr(length=length, append=True)

    atr_col = _find_atr_column(df)
    if atr_col is None:
        raise RuntimeError(
            "pandas_ta.atr() did not produce a recognized ATR column. "
            f"Columns present: {list(df.columns)}"
        )
    return df, atr_col


def _truncate_to_as_of(df: pd.DataFrame, as_of: Optional[str], ticker: str) -> pd.DataFrame:
    """Restrict df to rows with index <= as_of, guarding against look-ahead
    bias in simulation. Returns df unchanged when as_of is None (live mode).
    """
    if as_of is None:
        return df

    cutoff = pd.Timestamp(as_of)
    truncated = df[df.index <= cutoff]

    if truncated.empty:
        raise RuntimeError(
            f"No data for {ticker} on or before {as_of} - cannot simulate "
            f"this date (it's earlier than the cached history starts)."
        )
    return truncated


def collect_market_data(ticker: str = "AAPL", as_of: Optional[str] = None) -> dict:
    """
    Args:
        ticker: e.g. "AAPL"
        as_of: optional "YYYY-MM-DD" - when given, only data up to and
               including this date is visible (simulation mode). When
               None (default), behaves as before: latest available row
               (live mode).
    """
    data_path = f"data/processed/indicators/{ticker}_indicators.csv"

    if not os.path.exists(data_path):
        if as_of is not None:
            raise RuntimeError(
                f"No cached data for {ticker} and as_of={as_of} was requested - "
                f"simulation requires pre-fetched historical data; run "
                f"src/data/market_data.py for this ticker first."
            )
        # Live-mode fallback: download recent data directly.
        end = datetime.now()
        start = end - timedelta(days=90)

        df = yf.download(ticker, start=start, end=end, progress=False)
        if df is None or df.empty:
            raise RuntimeError(
                f"No data returned for {ticker} — check ticker symbol, "
                f"yfinance version, or possible rate limiting."
            )

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.ta.sma(length=10, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.atr(length=14, append=True)

        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        df.to_csv(data_path)

    df = pd.read_csv(data_path, index_col=0, parse_dates=True)

    if df.empty:
        raise RuntimeError(f"{data_path} exists but contains no rows.")

    df, atr_col = _ensure_atr(df)
    df = _truncate_to_as_of(df, as_of, ticker)

    latest = df.iloc[-1]

    for col in ("RSI_14", "SMA_10", atr_col):
        if pd.isna(latest.get(col)):
            raise RuntimeError(
                f"Latest row for {ticker}"
                f"{f' as of {as_of}' if as_of else ''} has NaN {col} — "
                f"not enough history yet at this point."
            )

    latest_timestamp = pd.to_datetime(df.index[-1])
    recent_closes = [float(x) for x in df["Close"].iloc[-30:].tolist()]

    return {
        "close": float(latest["Close"]),
        "sma_10": float(latest["SMA_10"]),
        "rsi": float(latest["RSI_14"]),
        "atr": float(latest[atr_col]),
        "closes": recent_closes,
        "timestamp": latest_timestamp.isoformat(),
    }


def _load_latest_scored_sentiment(ticker: str, news_dir: str = "data/raw/news"):
    path = os.path.join(news_dir, f"{ticker}_news_scored.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            articles = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return None
    if not articles:
        return None
    return articles


def _sentiment_score_from_articles(articles: list) -> float:
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for a in articles:
        s = a.get("sentiment", "neutral")
        counts[s] = counts.get(s, 0) + 1
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return (counts["positive"] - counts["negative"]) / total


def collect_sentiment(
    ticker: str = "AAPL", allow_rsi_fallback: bool = True, as_of: Optional[str] = None
) -> float:
    """
    NOTE on as_of and sentiment: real scored news (fetch_news.py +
    score_sentiment.py) only ever captures "latest" headlines, not a dated
    history - there is no per-day historical sentiment archive. So for
    as_of != None (simulation), this ALWAYS falls back to the RSI-derived
    proxy (computed from that date's own indicators, so it IS correctly
    dated and free of look-ahead bias) rather than real news sentiment,
    which cannot be dated retroactively with the current pipeline. This
    is a genuine data limitation, not a bug - worth stating explicitly in
    the dissertation rather than silently mixing "today's real sentiment"
    into a simulation of a past date.
    """
    if as_of is None:
        articles = _load_latest_scored_sentiment(ticker)
        if articles is not None:
            return _sentiment_score_from_articles(articles)

        if not allow_rsi_fallback:
            raise RuntimeError(
                f"No scored sentiment file for {ticker} at "
                f"data/raw/news/{ticker}_news_scored.json - run "
                f"src/data/update_vector_store.py first, or pass "
                f"allow_rsi_fallback=True."
            )
        logger.warning(
            "%s: no real sentiment file found - falling back to RSI-derived "
            "proxy. Run src/data/update_vector_store.py to generate real "
            "sentiment data.",
            ticker,
        )
    else:
        logger.info(
            "%s: simulating as_of=%s - using RSI-derived sentiment proxy "
            "(real news sentiment cannot be dated retroactively).",
            ticker, as_of,
        )

    data = collect_market_data(ticker, as_of=as_of)
    rsi = data["rsi"]
    sentiment = (rsi - 50) / 50
    return max(-1.0, min(1.0, sentiment))


def collect_ohlcv_frame(ticker: str = "AAPL", as_of: Optional[str] = None) -> pd.DataFrame:
    """Full OHLCV DataFrame for a ticker, needed by the stability filter
    (which requires a window of bars, not just the latest row).

    as_of: when given, only rows up to and including this date are
           returned - required so the stability filter's trend/gradient
           checks don't see future data during simulation.
    """
    data_path = f"data/processed/indicators/{ticker}_indicators.csv"
    if not os.path.exists(data_path):
        collect_market_data(ticker, as_of=as_of)
    df = pd.read_csv(data_path, index_col=0, parse_dates=True)
    df, _ = _ensure_atr(df)
    df = _truncate_to_as_of(df, as_of, ticker)
    return df
