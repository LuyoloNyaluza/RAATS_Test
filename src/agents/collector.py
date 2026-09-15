import glob
import json
import logging
import os
from datetime import datetime, timedelta

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


def collect_market_data(ticker: str = "AAPL") -> dict:
    data_path = f"data/processed/indicators/{ticker}_indicators.csv"

    if not os.path.exists(data_path):
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

    latest = df.iloc[-1]

    for col in ("RSI_14", "SMA_10", atr_col):
        if pd.isna(latest.get(col)):
            raise RuntimeError(
                f"Latest row for {ticker} has NaN {col} — not enough history yet. "
                f"Check the data source or widen the fetch window."
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
    """Load {ticker}_news_scored.json written by update_vector_store.py."""
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
    """(positive - negative) / total -> -1..1."""
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for a in articles:
        s = a.get("sentiment", "neutral")
        counts[s] = counts.get(s, 0) + 1
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return (counts["positive"] - counts["negative"]) / total


def collect_sentiment(ticker: str = "AAPL", allow_rsi_fallback: bool = True) -> float:
    """Real news sentiment from fetch_news.py + score_sentiment.py output.

    Reads the cached {ticker}_news_scored.json (does NOT call Ollama live —
    that already takes minutes across a full watchlist). Falls back to the
    RSI-derived proxy, with a logged warning, if no scored file exists yet.
    """
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
    data = collect_market_data(ticker)
    rsi = data["rsi"]
    sentiment = (rsi - 50) / 50
    return max(-1.0, min(1.0, sentiment))


def collect_ohlcv_frame(ticker: str = "AAPL") -> pd.DataFrame:
    """Full OHLCV DataFrame for a ticker (needed by the stability filter,
    which requires a window of bars, not just the latest row)."""
    data_path = f"data/processed/indicators/{ticker}_indicators.csv"
    if not os.path.exists(data_path):
        collect_market_data(ticker)
    df = pd.read_csv(data_path, index_col=0, parse_dates=True)
    df, _ = _ensure_atr(df)
    return df