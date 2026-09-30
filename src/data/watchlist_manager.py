# File: src/data/watchlist_manager.py
"""
Dynamic watchlist management for RAATS trading system.
Fetches news for a large ticker universe, scores sentiment, and generates
trading lists based on sentiment rankings.

ADDED: total_article_cap - caps the TOTAL number of articles scored
(via Ollama) across the whole universe, distributed as evenly as
possible per ticker. Without this, scanning a 50+ ticker universe at
even 3 articles/ticker means 150+ sequential Ollama calls before
trading can even start - the original 15-ticker demo already took
~19 minutes for 45 articles. A total cap makes latency predictable
regardless of how large the universe grows.

LIMITATION, stated explicitly: each ticker gets at least 1 article
(a floor), so if total_article_cap < number of tickers, the actual
articles scored will exceed the cap (e.g. 50 tickers, cap=30 -> 50
articles, 1 each) rather than leaving some tickers with zero real
sentiment data, which would otherwise default them to a neutral 0.0
score and bias the ranking. A warning is printed when this happens.

NEW: article_split - if provided, each ticker will be fetched with a specific
number of articles from Google News and Yahoo Finance (e.g., (2,3) for 2 Google
and 3 yfinance articles). When article_split is used, max_articles_per_ticker
is set to the sum of the split and total_article_cap is ignored (since each
ticker gets a fixed number of articles).
"""

import json
import time
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

import feedparser
from urllib.parse import quote

from src.data.fetch_news import fetch_financial_news, fetch_yfinance_news, fetch_mixed_news_for_ticker
from src.data.score_sentiment import score_articles, summarize_ticker_sentiment
from src.utils.logger import log_scan


def _resolve_per_ticker_cap(
    n_tickers: int,
    max_articles_per_ticker: int,
    total_article_cap: Optional[int],
    article_split: Optional[Tuple[int, int]] = None,
) -> int:
    """Resolve the effective per-ticker article cap.

    If article_split is given, we ignore max_articles_per_ticker and total_article_cap
    and use the split (google_count + yf_count) as the fixed per-ticker count.

    If total_article_cap is given (and no split), distribute it evenly across tickers
    (floor of 1 each - see module docstring for why). Otherwise fall back
    to max_articles_per_ticker unchanged.
    """
    if n_tickers == 0:
        return 0
    if article_split is not None:
        google_count, yf_count = article_split
        return google_count + yf_count

    if total_article_cap is None:
        return max_articles_per_ticker

    per_ticker = max(1, total_article_cap // n_tickers)
    actual_total = per_ticker * n_tickers
    if actual_total > total_article_cap:
        print(
            f"WARNING: total_article_cap={total_article_cap} with {n_tickers} tickers "
            f"cannot be met without leaving some tickers unscored - using "
            f"{per_ticker} article(s)/ticker instead ({actual_total} articles total), "
            f"so every ticker gets at least one real sentiment data point."
        )
    return min(per_ticker, max_articles_per_ticker) if max_articles_per_ticker else per_ticker


def fetch_universe_news(
    tickers: List[str],
    max_articles_per_ticker: int = 5,
    total_article_cap: Optional[int] = None,
    pause: float = 0.5,
    article_split: Optional[Tuple[int, int]] = None,
) -> Dict[str, List[Dict]]:
    """Fetch news for a large universe of tickers.

    Args:
        tickers: List of stock tickers to fetch news for
        max_articles_per_ticker: Maximum articles to fetch per ticker (ignored if article_split is not None)
        total_article_cap: Optional cap on TOTAL articles across the whole universe (ignored if article_split is not None)
        pause: Pause between requests to avoid rate limiting
        article_split: Optional tuple (google_count, yf_count) to fetch a mixed of Google News and yfinance articles per ticker.
                       If provided, each ticker gets exactly google_count + yf_count articles.

    Returns:
        Dictionary mapping ticker to list of news articles
    """
    effective_cap = _resolve_per_ticker_cap(len(tickers), max_articles_per_ticker, total_article_cap, article_split)
    if article_split is not None:
        google_count, yf_count = article_split
        print(f"Fetching news for {len(tickers)} tickers ({google_count} Google + {yf_count} yfinance = {effective_cap} article(s) each)...")
    else:
        print(f"Fetching news for {len(tickers)} tickers ({effective_cap} article(s) each)...")
    all_articles = {}

    for i, ticker in enumerate(tickers):
        if i > 0 and i % 10 == 0:
            print(f"  Progress: {i}/{len(tickers)} tickers processed")

        try:
            if article_split is not None:
                google_count, yf_count = article_split
                articles = fetch_mixed_news_for_ticker(
                    ticker=ticker,
                    max_articles=effective_cap,
                    google_count=google_count,
                    yf_count=yf_count,
                    company_name=None,  # We don't have company names here; fetch_mixed_news_for_ticker will use ticker only
                )
            else:
                articles = fetch_financial_news(
                    ticker=ticker,
                    max_articles=effective_cap
                )
            all_articles[ticker] = articles
            print(f"  {ticker}: {len(articles)} articles")
        except Exception as e:
            print(f"  ERROR fetching news for {ticker}: {e}")
            all_articles[ticker] = []

        time.sleep(pause)

    return all_articles


def score_universe_sentiment(
    news_data: Dict[str, List[Dict]],
    model_name: str = "mistral"
) -> Dict[str, List[Dict]]:
    """Score sentiment for all news articles in the universe.

    Args:
        news_data: Dictionary mapping ticker to list of news articles
        model_name: Ollama model to use for sentiment scoring

    Returns:
        Dictionary mapping ticker to list of scored articles
    """
    print("Scoring sentiment for all articles...")
    scored_data = {}

    for ticker, articles in news_data.items():
        if not articles:
            scored_data[ticker] = []
            continue

        try:
            scored_articles = score_articles(
                ticker=ticker,
                articles=articles,
                model_name=model_name
            )
            scored_data[ticker] = scored_articles
        except Exception as e:
            print(f"  ERROR scoring sentiment for {ticker}: {e}")
            scored_data[ticker] = []

    return scored_data


def summarize_universe_sentiment(
    scored_data: Dict[str, List[Dict]]
) -> Dict[str, float]:
    """Summarize sentiment scores per ticker.

    Args:
        scored_data: Dictionary mapping ticker to list of scored articles

    Returns:
        Dictionary mapping ticker to average sentiment score
    """
    print("Summarizing sentiment per ticker...")
    ticker_scores = {}

    for ticker, articles in scored_data.items():
        if not articles:
            ticker_scores[ticker] = 0.0
            continue

        try:
            score = summarize_ticker_sentiment(articles)
            ticker_scores[ticker] = score
        except Exception as e:
            print(f"  ERROR summarizing sentiment for {ticker}: {e}")
            ticker_scores[ticker] = 0.0

    return ticker_scores


def get_top_tickers_by_sentiment(
    tickers: List[str],
    top_n: int = 10,
    waitlist_n: int = 10,
    max_articles_per_ticker: int = 5,
    total_article_cap: Optional[int] = None,
    model_name: str = "mistral",
    pause: float = 0.5,
    article_split: Optional[Tuple[int, int]] = None,
) -> Tuple[List[str], List[str], Dict[str, float]]:
    """Fetch news, score sentiment, and return top tickers and waitlist.

    Args:
        tickers: List of ticker symbols to consider
        top_n: Number of top tickers to return as active list
        waitlist_n: Number of tickers to return as waitlist
        max_articles_per_ticker: Maximum articles to fetch per ticker (ignored if article_split is not None)
        total_article_cap: Optional cap on TOTAL articles across the whole universe (ignored if article_split is not None)
        model_name: Ollama model to use for sentiment scoring
        pause: Pause between news fetch requests
        article_split: Optional tuple (google_count, yf_count) to fetch a mixed of Google News and yfinance articles per ticker.
                       If provided, each ticker gets exactly google_count + yf_count articles.

    Returns:
        Tuple of (active_list, waitlist, sentiment_scores)
        active_list: Top top_n tickers by sentiment score
        waitlist: Next waitlist_n tickers by sentiment score
        sentiment_scores: Dictionary mapping ticker to its sentiment score
    """
    if not tickers:
        return [], [], {}

    # Fetch news for the universe
    news_data = fetch_universe_news(
        tickers=tickers,
        max_articles_per_ticker=max_articles_per_ticker,
        total_article_cap=total_article_cap,
        pause=pause,
        article_split=article_split
    )

    # Score sentiment
    scored_data = score_universe_sentiment(news_data, model_name=model_name)

    # Summarize per ticker
    ticker_scores = summarize_universe_sentiment(scored_data)

    # Sort tickers by score descending
    sorted_tickers = sorted(ticker_scores.items(), key=lambda x: x[1], reverse=True)

    # Extract top_n and waitlist_n
    active_list = [ticker for ticker, _ in sorted_tickers[:top_n]]
    waitlist = [ticker for ticker, _ in sorted_tickers[top_n:top_n + waitlist_n]]

    return active_list, waitlist, ticker_scores


def update_trading_lists(
    closed_positions: List[str],
    current_active: List[str],
    current_waitlist: List[str],
    all_tickers: List[str],
    sentiment_scores: Dict[str, float],
    top_n: int = 10,
    waitlist_n: int = 10
) -> Tuple[List[str], List[str]]:
    """Update trading lists when positions close.

    Args:
        closed_positions: List of tickers that were closed today
        current_active: Current active list
        current_waitlist: Current waitlist
        all_tickers: Full list of tickers to consider for replacement
        sentiment_scores: Sentiment scores for all tickers
        top_n: Desired size of active list
        waitlist_n: Desired size of waitlist

    Returns:
        Tuple of (updated_active, updated_waitlist)
    """
    # Remove closed positions from active list and waitlist
    active_list = [t for t in current_active if t not in closed_positions]
    waitlist = [t for t in current_waitlist if t not in closed_positions]

    # Determine how many we need to fill active list and waitlist
    need_active = top_n - len(active_list)
    need_waitlist = waitlist_n - len(waitlist)

    # Create a sorted list of available tickers (not in active or waitlist, not closed)
    excluded = set(active_list) | set(waitlist) | set(closed_positions)
    available = [ticker for ticker in all_tickers if ticker not in excluded]
    available.sort(key=lambda ticker: sentiment_scores.get(ticker, 0.0), reverse=True)

    # Fill active list first, then waitlist
    if need_active > 0:
        active_list.extend(available[:need_active])
        available = available[need_active:]

    if need_waitlist > 0:
        waitlist.extend(available[:need_waitlist])

    # Trim to exact sizes (in case we added too many)
    active_list = active_list[:top_n]
    waitlist = waitlist[:waitlist_n]

    return active_list, waitlist


def get_top50(ticker_scores: Dict[str, float]) -> List[str]:
    """Get top 50 tickers by sentiment score."""
    sorted_tickers = sorted(ticker_scores.items(), key=lambda x: x[1], reverse=True)
    return [ticker for ticker, _ in sorted_tickers[:50]]


def get_random_list(tickers: List[str], seed: Optional[int] = None, count: int = 35) -> List[str]:
    """Get a deterministic random list of tickers for logging purposes.

    Args:
        tickers: List of tickers to choose from
        seed: Optional seed for reproducibility (if None, use date-based seed)
        count: Number of tickers to return

    Returns:
        List of randomly selected tickers
    """
    import random
    if seed is None:
        # Use today's date for daily determinism
        today = datetime.now().strftime("%Y-%m-%d")
        seed = sum(ord(c) for c in today)
    random.seed(seed)
    return random.sample(tickers, min(count, len(tickers)))


def get_top10(ticker_scores: Dict[str, float]) -> List[str]:
    """Get top 10 tickers by sentiment score."""
    sorted_tickers = sorted(ticker_scores.items(), key=lambda x: x[1], reverse=True)
    return [ticker for ticker, _ in sorted_tickers[:10]]