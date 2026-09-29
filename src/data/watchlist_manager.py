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
            print(f"  {ticker}: scored {len(scored_articles)} articles")
        except Exception as e:
            print(f"  ERROR scoring sentiment for {ticker}: {e}")
            scored_data[ticker] = []

    return scored_data


def aggregate_ticker_sentiment(
    scored_news: Dict[str, List[Dict]]
) -> Dict[str, float]:
    """Aggregate sentiment scores for each ticker.

    Args:
        scored_news: Dictionary mapping ticker to list of scored articles

    Returns:
        Dictionary mapping ticker to aggregated sentiment score (-1 to 1)
    """
    print("Aggregating ticker sentiment scores...")
    ticker_scores = {}

    for ticker, scored_articles in scored_news.items():
        if not scored_articles:
            ticker_scores[ticker] = 0.0  # Neutral if no news
            continue

        sentiment_values = []
        for article in scored_articles:
            sentiment_label = article.get("sentiment", "neutral")
            confidence = article.get("confidence", 0.0)

            sentiment_map = {
                "positive": 1.0,
                "neutral": 0.0,
                "negative": -1.0
            }
            base_score = sentiment_map.get(sentiment_label, 0.0)
            weighted_score = base_score * confidence
            sentiment_values.append(weighted_score)

        if sentiment_values:
            avg_score = sum(sentiment_values) / len(sentiment_values)
            avg_score = max(-1.0, min(1.0, avg_score))
            ticker_scores[ticker] = avg_score
        else:
            ticker_scores[ticker] = 0.0

    return ticker_scores


def generate_trading_lists(
    sentiment_scores: Dict[str, float],
    top_n: int = 10,
    waitlist_n: int = 10
) -> Tuple[List[str], List[str]]:
    """Generate active trading list and waiting list based on sentiment scores.

    Args:
        sentiment_scores: Dictionary mapping ticker to sentiment score
        top_n: Number of tickers for active trading list
        waitlist_n: Number of tickers for waiting list

    Returns:
        Tuple of (active_list, waitlist) where each is a list of tickers
    """
    print("Generating trading lists from sentiment scores...")

    scored_tickers = {t: s for t, s in sentiment_scores.items() if abs(s) > 0.01}

    if not scored_tickers:
        print("WARNING: No scored tickers found, returning empty lists")
        return [], []

    sorted_tickers = sorted(
        scored_tickers.items(),
        key=lambda x: x[1],
        reverse=True
    )

    ticker_symbols = [ticker for ticker, score in sorted_tickers]

    active_list = ticker_symbols[:top_n]
    waitlist = ticker_symbols[top_n:top_n + waitlist_n]

    print(f"Active list ({len(active_list)}): {active_list}")
    print(f"Waiting list ({len(waitlist)}): {waitlist}")

    return active_list, waitlist


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
        current_active: Current active list before update
        current_waitlist: Current waitlist before update
        all_tickers: Full universe of tickers
        sentiment_scores: Dictionary mapping ticker to sentiment score
        top_n: Number of tickers for active trading list
        waitlist_n: Number of tickers for waiting list

    Returns:
        Tuple of (updated_active, updated_waitlist)
    """
    print(f"Updating lists due to {len(closed_positions)} closed positions: {closed_positions}")

    updated_active = [t for t in current_active if t not in closed_positions]
    updated_waitlist = [t for t in current_waitlist if t not in closed_positions]

    active_slots_needed = top_n - len(updated_active)
    waitlist_slots_needed = waitlist_n - len(updated_waitlist)

    print(f"Need to fill {active_slots_needed} active slots and {waitlist_slots_needed} waitlist slots")

    in_use = set(updated_active) | set(updated_waitlist) | set(closed_positions)
    available_tickers = [t for t in all_tickers if t not in in_use]

    available_scored = [
        (t, sentiment_scores.get(t, 0.0))
        for t in available_tickers
    ]
    available_scored.sort(key=lambda x: x[1], reverse=True)
    available_sorted = [t for t, score in available_scored]

    if active_slots_needed > 0 and available_sorted:
        to_add_to_active = available_sorted[:active_slots_needed]
        updated_active.extend(to_add_to_active)
        available_sorted = available_sorted[active_slots_needed:]
        print(f"Added to active: {to_add_to_active}")

    if waitlist_slots_needed > 0 and available_sorted:
        to_add_to_waitlist = available_sorted[:waitlist_slots_needed]
        updated_waitlist.extend(to_add_to_waitlist)
        available_sorted = available_sorted[waitlist_slots_needed:]
        print(f"Added to waitlist: {to_add_to_waitlist}")

    updated_active = updated_active[:top_n]
    updated_waitlist = updated_waitlist[:waitlist_n]

    print(f"Updated active list ({len(updated_active)}): {updated_active}")
    print(f"Updated waitlist ({len(updated_waitlist)}): {updated_waitlist}")

    return updated_active, updated_waitlist


def get_top_tickers_by_sentiment(
    tickers: List[str],
    top_n: int = 10,
    waitlist_n: int = 10,
    max_articles_per_ticker: int = 5,
    total_article_cap: Optional[int] = None,
    model_name: str = "mistral",
    pause: float = 0.5,
    log_scans: bool = True,
    article_split: Optional[Tuple[int, int]] = None,
) -> Tuple[List[str], List[str], Dict[str, float]]:
    """Complete workflow: fetch news, score sentiment, and generate trading lists.

    Args:
        tickers: Universe of tickers to evaluate
        top_n: Number of tickers for active trading list
        waitlist_n: Number of tickers for waiting list
        max_articles_per_ticker: Max news articles to fetch per ticker (ignored if article_split is not None)
        total_article_cap: Optional cap on TOTAL articles scored across the whole universe (ignored if article_split is not None)
        model_name: Ollama model for sentiment scoring
        pause: Pause between API requests
        log_scans: write each ticker's scan result to the weekly JSONL log via src.utils.logger.log_scan (default True)
        article_split: Optional tuple (google_count, yf_count) to fetch a mixed of Google News and yfinance articles per ticker.
                       If provided, each ticker gets exactly google_count + yf_count articles (e.g., (2,3) for 2 Google and 3 yfinance).

    Returns:
        Tuple of (active_list, waitlist, all_sentiment_scores)
    """
    print(f"Starting watchlist generation for {len(tickers)} tickers...")
    start_time = time.time()

    news_data = fetch_universe_news(
        tickers=tickers,
        max_articles_per_ticker=max_articles_per_ticker,
        total_article_cap=total_article_cap,
        pause=pause,
        article_split=article_split,
    )

    scored_news = score_universe_sentiment(
        news_data=news_data,
        model_name=model_name
    )

    sentiment_scores = aggregate_ticker_sentiment(scored_news)

    active_list, waitlist = generate_trading_lists(
        sentiment_scores=sentiment_scores,
        top_n=top_n,
        waitlist_n=waitlist_n
    )

    if log_scans:
        active_set, waitlist_set = set(active_list), set(waitlist)
        for ticker, score in sentiment_scores.items():
            assignment = (
                "active" if ticker in active_set
                else "waitlist" if ticker in waitlist_set
                else "excluded"
            )
            log_scan(
                ticker=ticker,
                sentiment_score=score,
                n_articles=len(scored_news.get(ticker, [])),
                list_assignment=assignment,
            )

    elapsed_time = time.time() - start_time
    print(f"Watchlist generation completed in {elapsed_time:.1f} seconds")

    return active_list, waitlist, sentiment_scores


if __name__ == "__main__":
    print("=== RAATS Watchlist Manager Demo ===")

    example_universe = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
        "META", "NVDA", "NFLX", "AMD", "INTC",
        "CSCO", "ADBE", "CRM", "ORCL", "IBM",
        "QCOM", "TXN", "HON", "UNH", "JNJ",
        "PG", "JPM", "BAC", "WFC", "C",
        "V", "MA", "DIS", "NKE", "SBUX",
        "MCD", "WMT", "TGT", "COST", "HD",
        "LOW", "CL", "KMB", "GE",
        "CAT", "MMM", "BA", "F", "GM",
        "XOM", "CVX", "COP", "EOG", "SLB",
    ]

    demo_universe = example_universe[:20]
    print(f"Using demo universe of {len(demo_universe)} tickers: {demo_universe}")

    try:
        active, waitlist, scores = get_top_tickers_by_sentiment(
            tickers=demo_universe,
            top_n=5,
            waitlist_n=5,
            total_article_cap=15,
            pause=1.0
        )

        print("\n=== RESULTS ===")
        print(f"Active list (top 5): {active}")
        print(f"Waiting list (next 5): {waitlist}")

        print("\nTop 5 scores:")
        active_scores = [(t, scores.get(t, 0.0)) for t in active]
        active_scores.sort(key=lambda x: x[1], reverse=True)
        for ticker, score in active_scores:
            print(f"  {ticker}: {score:.3f}")

    except Exception as e:
        print(f"Error in demo: {e}")
        print("Make sure Ollama is running and required packages are installed")

    print("\nDemo completed.")