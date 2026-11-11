"""
src/agents/collector.py

Collects market data, sentiment and OHLCV data.

Sentiment can come from two sources:

1. Discovery news supplied by trading_loop_dynamic.py.
   These articles are scored directly using score_sentiment.py.

2. Existing *_news_scored.json files for backward compatibility.

For historical simulation (as_of is supplied), discovered live news is
NOT used because it could introduce look-ahead bias. The RSI-derived
proxy remains the fallback for historical simulation unless a properly
dated historical sentiment dataset is available.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import numpy as np
import pandas as pd
import pandas_ta as ta  # noqa: F401
import yfinance as yf

from src.data.score_sentiment import (
    score_articles,
    summarize_ticker_sentiment,
)

logger = logging.getLogger("raats.agents.collector")

# How much daily history the cached indicator file holds. 90 days (~62 bars) left RSI/ATR with a
# poorly seeded warm-up and SMA_50 / MACD unusable; ~6 months (~125 bars) fixes both.
HISTORY_DAYS = int(os.environ.get("RAATS_HISTORY_DAYS", "180"))
RSI_LENGTH = 14


_ATR_COLUMN_CANDIDATES = (
    "ATRr_14",
    "ATRs_14",
    "ATRe_14",
    "ATR_14",
)


def _find_atr_column(df: pd.DataFrame):
    for name in _ATR_COLUMN_CANDIDATES:
        if name in df.columns:
            return name

    return None


def _ensure_atr(
    df: pd.DataFrame,
    length: int = 14,
):
    """Return (df, atr_column_name), computing ATR if necessary."""

    existing = _find_atr_column(df)

    if existing is not None:
        return df, existing

    required = {
        "High",
        "Low",
        "Close",
    }

    missing = required - set(df.columns)

    if missing:
        raise RuntimeError(
            f"Cannot compute ATR: missing column(s) "
            f"{sorted(missing)}. "
            f"Re-run the data pipeline "
            f"(src/data/market_data.py) for this ticker."
        )

    df = df.copy()

    df.ta.atr(
        length=length,
        append=True,
    )

    atr_col = _find_atr_column(df)

    if atr_col is None:
        raise RuntimeError(
            "pandas_ta.atr() did not produce "
            "a recognized ATR column. "
            f"Columns present: {list(df.columns)}"
        )

    return df, atr_col


def _truncate_to_as_of(
    df: pd.DataFrame,
    as_of: Optional[str],
    ticker: str,
) -> pd.DataFrame:
    """
    Restrict df to rows <= as_of.

    Used during simulation to prevent look-ahead bias.
    """

    if as_of is None:
        return df

    cutoff = pd.Timestamp(as_of)

    truncated = df[
        df.index <= cutoff
    ]

    if truncated.empty:
        raise RuntimeError(
            f"No data for {ticker} on or before "
            f"{as_of} - cannot simulate this date "
            f"(it is earlier than the cached history starts)."
        )

    return truncated


def _indicator_path(ticker: str) -> str:
    return f"data/processed/indicators/{ticker}_indicators.csv"


def _download_history(ticker: str, data_path: str) -> None:
    """Download HISTORY_DAYS of daily bars, add the indicators and (re)write the cache file.

    The full indicator set from src/data/market_data.py is used when importable, so a refresh
    never removes columns (SMA_20/50, EMA, MACD) that other modules read from the same file."""
    end = datetime.now()
    start = end - timedelta(days=HISTORY_DAYS)
    df = yf.download(ticker, start=start, end=end, progress=False)
    if df is None or df.empty:
        raise RuntimeError(
            f"No data returned for {ticker} - check ticker symbol, yfinance version, "
            f"or possible rate limiting."
        )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    try:
        from src.data.market_data import add_technical_indicators
        df = add_technical_indicators(df)
    except Exception:                       # fall back to the three indicators RAATS needs
        df.ta.sma(length=10, append=True)
        df.ta.rsi(length=RSI_LENGTH, append=True)
        df.ta.atr(length=14, append=True)
    os.makedirs(os.path.dirname(data_path), exist_ok=True)
    df.to_csv(data_path)


def _is_stale(df: pd.DataFrame) -> bool:
    """True when the cached file is older than the previous business day (so a cache written
    once is never served for weeks). A market holiday can trigger one harmless extra refresh."""
    last_bar = pd.Timestamp(df.index[-1]).normalize()
    expected = pd.Timestamp.now().normalize() - pd.offsets.BDay(1)
    return last_bar < expected


def _mask_rsi_warmup(df: pd.DataFrame) -> pd.DataFrame:
    """RSI needs RSI_LENGTH bars before it means anything; earlier values (0.0, 6.5, ...) are
    warm-up artefacts. Blank them, including in older cached files."""
    if "RSI_14" not in df.columns or len(df) == 0:
        return df
    df = df.copy()
    rsi = df["RSI_14"].astype(float)        # Series.iloc slice assignment: type-safe
    rsi.iloc[:RSI_LENGTH] = np.nan
    df["RSI_14"] = rsi
    return df


def _load_indicator_frame(ticker: str, as_of: Optional[str]):
    """Cached indicator frame (refreshed when stale, live mode only) -> (df, atr_column)."""
    data_path = _indicator_path(ticker)

    if not os.path.exists(data_path):
        if as_of is not None:
            raise RuntimeError(
                f"No cached data for {ticker} and as_of={as_of} was requested. "
                f"Simulation requires pre-fetched historical data; "
                f"run src/data/market_data.py first."
            )
        _download_history(ticker, data_path)

    df = pd.read_csv(data_path, index_col=0, parse_dates=True)
    if df.empty:
        raise RuntimeError(f"{data_path} exists but contains no rows.")

    if as_of is None and _is_stale(df):
        try:
            _download_history(ticker, data_path)
            df = pd.read_csv(data_path, index_col=0, parse_dates=True)
            logger.info("%s: indicator cache refreshed (last bar %s).", ticker, df.index[-1])
        except Exception as exc:            # keep serving the cache, but say so
            logger.warning("%s: cache is stale (last bar %s) and refresh failed: %s",
                           ticker, df.index[-1], exc)

    df = _mask_rsi_warmup(df)
    df, atr_col = _ensure_atr(df)
    df = _truncate_to_as_of(df, as_of, ticker)
    return df, atr_col


def collect_market_data(
    ticker: str = "AAPL",
    as_of: Optional[str] = None,
) -> dict:
    """
    Collect the latest available market data.

    When as_of is supplied, only historical data up to that date is visible.
    In live mode a cache older than the previous business day is refreshed first.
    """
    df, atr_col = _load_indicator_frame(ticker, as_of)
    latest = df.iloc[-1]

    for col in ("RSI_14", "SMA_10", atr_col):
        if pd.isna(latest.get(col)):
            raise RuntimeError(
                f"Latest row for {ticker}"
                f"{f' as of {as_of}' if as_of else ''} "
                f"has NaN {col} - not enough history yet at this point."
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


def _load_latest_scored_sentiment(
    ticker: str,
    news_dir: str = "data/raw/news",
):
    """
    Load an existing scored-news file.

    Kept for backward compatibility.
    """

    path = os.path.join(
        news_dir,
        f"{ticker}_news_scored.json",
    )

    if not os.path.exists(path):
        return None

    try:
        with open(
            path,
            "r",
            encoding="utf-8",
        ) as f:
            articles = json.load(f)

    except (
        json.JSONDecodeError,
        OSError,
    ) as exc:

        logger.warning(
            "Could not read %s: %s",
            path,
            exc,
        )

        return None

    if not articles:
        return None

    return articles


def _sentiment_score_from_articles(
    articles: list,
) -> float:

    counts = {
        "positive": 0,
        "negative": 0,
        "neutral": 0,
    }

    for article in articles:

        sentiment = article.get(
            "sentiment",
            "neutral",
        )

        counts[sentiment] = (
            counts.get(sentiment, 0) + 1
        )

    total = sum(
        counts.values()
    )

    if total == 0:
        return 0.0

    return (
        counts["positive"]
        - counts["negative"]
    ) / total


def _extract_discovery_articles(
    discovery_news: Optional[
        Dict[str, List[Dict[str, Any]]]
    ],
) -> List[Dict[str, Any]]:
    """
    Flatten the discovery news structure into one article list.

    Expected:

    {
        "yfinance_news": [...],
        "google_news": [...]
    }
    """

    if not discovery_news:
        return []

    articles = []

    for source_key in (
        "yfinance_news",
        "google_news",
    ):

        source_articles = discovery_news.get(
            source_key,
            [],
        )

        if not isinstance(
            source_articles,
            list,
        ):
            continue

        for article in source_articles:

            if not isinstance(
                article,
                dict,
            ):
                continue

            article_copy = dict(article)

            # Preserve the discovery source.
            if source_key == "yfinance_news":
                article_copy[
                    "discovery_source"
                ] = "Yahoo Finance"

            else:
                article_copy[
                    "discovery_source"
                ] = "Google News"

            articles.append(
                article_copy
            )

    return articles


def _score_discovery_news(
    ticker: str,
    discovery_news: Optional[
        Dict[str, List[Dict[str, Any]]]
    ],
) -> Optional[float]:
    """
    Score news already fetched by discovery.py.

    No network request is made here.
    """

    articles = _extract_discovery_articles(
        discovery_news
    )

    if not articles:
        return None

    logger.info(
        "%s: scoring %d discovered news articles.",
        ticker,
        len(articles),
    )

    scored_articles = score_articles(
        ticker,
        articles,
        model_name=os.environ.get(
            "RAATS_SENTIMENT_MODEL",
            "qwen2.5:3b",
        ),
    )

    summary = summarize_ticker_sentiment(
        scored_articles
    )

    logger.info(
        "%s: discovered news sentiment = %s "
        "(positive=%d, negative=%d, neutral=%d, total=%d)",
        ticker,
        summary["overall"],
        summary["positive"],
        summary["negative"],
        summary["neutral"],
        summary["total"],
    )

    sentiment = _sentiment_score_from_articles(
        scored_articles
    )

    return max(
        -1.0,
        min(1.0, sentiment),
    )


def collect_sentiment(
    ticker: str = "AAPL",
    allow_rsi_fallback: bool = True,
    as_of: Optional[str] = None,
    discovery_news: Optional[dict] = None,
) -> float:
    """Sentiment in [-1, 1].

    Historical simulation (as_of) never uses live news: RSI-derived proxy.
    Live: discovery's scored articles (confidence-weighted) -> an existing scored file ->
    RSI proxy (when allowed). Articles whose scores carry no confidence are NOT treated as a
    neutral 0.0: they fall through to the next source with a warning."""

    def _rsi_proxy(**kw) -> float:
        rsi = collect_market_data(ticker, **kw)["rsi"]
        return max(-1.0, min(1.0, (rsi - 50) / 50))

    if as_of is not None:
        return _rsi_proxy(as_of=as_of)

    articles = _flatten_discovery_news(discovery_news)
    if articles:
        score_values = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
        weighted_score = 0.0
        total_weight = 0.0
        for article in articles:
            sentiment = str(article.get("sentiment", "neutral")).lower()
            confidence = float(article.get("confidence", 0.0) or 0.0)
            weighted_score += score_values.get(sentiment, 0.0) * confidence
            total_weight += confidence
        if total_weight > 0:
            return max(-1.0, min(1.0, weighted_score / total_weight))
        logger.warning("%s: %d discovered articles carry no sentiment confidence - "
                       "trying the next source.", ticker, len(articles))

    scored = _load_latest_scored_sentiment(ticker)
    if scored:
        logger.info("%s: using existing scored-news file.", ticker)
        return _sentiment_score_from_articles(scored)

    if not allow_rsi_fallback:
        raise RuntimeError(
            f"No scored sentiment available for {ticker}. Discovery supplied no usable "
            f"news and no scored file exists at data/raw/news/{ticker}_news_scored.json."
        )

    logger.warning("%s: no discovered/scored news found - falling back to RSI-derived proxy.",
                   ticker)
    return _rsi_proxy()


def collect_ohlcv_frame(
    ticker: str = "AAPL",
    as_of: Optional[str] = None,
) -> pd.DataFrame:
    """Full OHLCV DataFrame (with indicators) for the stability filter."""
    df, _ = _load_indicator_frame(ticker, as_of)
    return df


def _flatten_discovery_news(discovery_news):
    if not discovery_news:
        return []

    articles = []

    for source_key in (
        "google_news",
        "yfinance_news",
    ):
        for article in (
            discovery_news.get(source_key, []) or []
        ):
            articles.append(article)

    return articles