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

import pandas as pd
import pandas_ta as ta  # noqa: F401
import yfinance as yf

from src.data.score_sentiment import (
    score_articles,
    summarize_ticker_sentiment,
)

logger = logging.getLogger("raats.agents.collector")


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


def collect_market_data(
    ticker: str = "AAPL",
    as_of: Optional[str] = None,
) -> dict:
    """
    Collect the latest available market data.

    When as_of is supplied, only historical data up to that date
    is visible.
    """

    data_path = (
        f"data/processed/indicators/"
        f"{ticker}_indicators.csv"
    )

    if not os.path.exists(data_path):

        if as_of is not None:
            raise RuntimeError(
                f"No cached data for {ticker} and "
                f"as_of={as_of} was requested. "
                f"Simulation requires pre-fetched historical "
                f"data; run src/data/market_data.py first."
            )

        end = datetime.now()
        start = end - timedelta(days=90)

        df = yf.download(
            ticker,
            start=start,
            end=end,
            progress=False,
        )

        if df is None or df.empty:
            raise RuntimeError(
                f"No data returned for {ticker} - "
                f"check ticker symbol, yfinance version, "
                f"or possible rate limiting."
            )

        if isinstance(
            df.columns,
            pd.MultiIndex,
        ):
            df.columns = (
                df.columns
                .get_level_values(0)
            )

        df.ta.sma(
            length=10,
            append=True,
        )

        df.ta.rsi(
            length=14,
            append=True,
        )

        df.ta.atr(
            length=14,
            append=True,
        )

        os.makedirs(
            os.path.dirname(data_path),
            exist_ok=True,
        )

        df.to_csv(data_path)

    df = pd.read_csv(
        data_path,
        index_col=0,
        parse_dates=True,
    )

    if df.empty:
        raise RuntimeError(
            f"{data_path} exists but contains no rows."
        )

    df, atr_col = _ensure_atr(df)

    df = _truncate_to_as_of(
        df,
        as_of,
        ticker,
    )

    latest = df.iloc[-1]

    for col in (
        "RSI_14",
        "SMA_10",
        atr_col,
    ):
        if pd.isna(
            latest.get(col)
        ):
            raise RuntimeError(
                f"Latest row for {ticker}"
                f"{f' as of {as_of}' if as_of else ''} "
                f"has NaN {col} - not enough history yet "
                f"at this point."
            )

    latest_timestamp = pd.to_datetime(
        df.index[-1]
    )

    recent_closes = [
        float(x)
        for x in df["Close"]
        .iloc[-30:]
        .tolist()
    ]

    return {
        "close": float(
            latest["Close"]
        ),
        "sma_10": float(
            latest["SMA_10"]
        ),
        "rsi": float(
            latest["RSI_14"]
        ),
        "atr": float(
            latest[atr_col]
        ),
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
            "mistral",
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

    # Historical simulation must not use current discovery news.
    if as_of is not None:
        data = collect_market_data(
            ticker,
            as_of=as_of,
        )

        rsi = data["rsi"]
        sentiment = (rsi - 50) / 50

        return max(
            -1.0,
            min(1.0, sentiment),
        )

    articles = _flatten_discovery_news(
        discovery_news
    )

    if articles:

        score_values = {
            "positive": 1.0,
            "negative": -1.0,
            "neutral": 0.0,
        }

        weighted_score = 0.0
        total_weight = 0.0

        for article in articles:

            sentiment = str(
                article.get(
                    "sentiment",
                    "neutral",
                )
            ).lower()

            confidence = float(
                article.get(
                    "confidence",
                    0.0,
                )
                or 0.0
            )

            weighted_score += (
                score_values.get(
                    sentiment,
                    0.0,
                )
                * confidence
            )

            total_weight += confidence

        if total_weight > 0:
            return max(
                -1.0,
                min(
                    1.0,
                    weighted_score / total_weight,
                ),
            )

        return 0.0

    # Existing scored-file fallback
    articles = _load_latest_scored_sentiment(
        ticker
    )

    if articles:
        return _sentiment_score_from_articles(
            articles
        )

    if not allow_rsi_fallback:
        raise RuntimeError(
            f"No scored sentiment available for {ticker}."
        )

    logger.warning(
        "%s: no discovered/scored news found - "
        "falling back to RSI-derived proxy.",
        ticker,
    )

    data = collect_market_data(ticker)

    rsi = data["rsi"]
    sentiment = (rsi - 50) / 50

    return max(
        -1.0,
        min(1.0, sentiment),
    )   
    # ---------------------------------------------------------
    # LIVE MODE - DISCOVERY NEWS
    # ---------------------------------------------------------
    if discovery_news:

        scored_sentiment = (
            _score_discovery_news(
                ticker,
                discovery_news,
            )
        )

        if scored_sentiment is not None:
            return scored_sentiment

    # ---------------------------------------------------------
    # LIVE MODE - EXISTING SCORED FILE
    # ---------------------------------------------------------
    articles = _load_latest_scored_sentiment(
        ticker
    )

    if articles is not None:

        logger.info(
            "%s: using existing scored-news file.",
            ticker,
        )

        return _sentiment_score_from_articles(
            articles
        )

    # ---------------------------------------------------------
    # LIVE MODE - RSI FALLBACK
    # ---------------------------------------------------------
    if not allow_rsi_fallback:

        raise RuntimeError(
            f"No scored sentiment available for "
            f"{ticker}. Discovery supplied no usable "
            f"news and no scored file exists at "
            f"data/raw/news/{ticker}_news_scored.json."
        )

    logger.warning(
        "%s: no discovered/scored news found - "
        "falling back to RSI-derived proxy.",
        ticker,
    )

    data = collect_market_data(
        ticker
    )

    rsi = data["rsi"]

    sentiment = (
        rsi - 50
    ) / 50

    return max(
        -1.0,
        min(1.0, sentiment),
    )


def collect_ohlcv_frame(
    ticker: str = "AAPL",
    as_of: Optional[str] = None,
) -> pd.DataFrame:
    """
    Full OHLCV DataFrame for the stability filter.
    """

    data_path = (
        f"data/processed/indicators/"
        f"{ticker}_indicators.csv"
    )

    if not os.path.exists(data_path):
        collect_market_data(
            ticker,
            as_of=as_of,
        )

    df = pd.read_csv(
        data_path,
        index_col=0,
        parse_dates=True,
    )

    df, _ = _ensure_atr(df)

    df = _truncate_to_as_of(
        df,
        as_of,
        ticker,
    )

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