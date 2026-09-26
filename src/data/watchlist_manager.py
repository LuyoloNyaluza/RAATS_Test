# File: src/data/watchlist_manager.py
"""
Dynamic watchlist management for RAATS trading system.
Fetches news for a large ticker universe, scores sentiment, and generates
trading lists based on sentiment rankings.
"""

import json
import time
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

import feedparser
from urllib.parse import quote

from src.data.fetch_news import fetch_financial_news, fetch_news_for_watchlist
from src.data.score_sentiment import score_articles, summarize_ticker_sentiment
from src.data.process_news import load_and_clean_news


def fetch_universe_news(
    tickers: List[str], 
    max_articles_per_ticker: int = 5,
    pause: float = 0.5
) -> Dict[str, List[Dict]]:
    """
    Fetch news for a large universe of tickers.
    
    Args:
        tickers: List of stock tickers to fetch news for
        max_articles_per_ticker: Maximum articles to fetch per ticker
        pause: Pause between requests to avoid rate limiting
        
    Returns:
        Dictionary mapping ticker to list of news articles
    """
    print(f"Fetching news for {len(tickers)} tickers...")
    all_articles = {}
    
    for i, ticker in enumerate(tickers):
        if i > 0 and i % 10 == 0:
            print(f"  Progress: {i}/{len(tickers)} tickers processed")
            
        try:
            articles = fetch_financial_news(
                ticker=ticker,
                max_articles=max_articles_per_ticker
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
    """
    Score sentiment for all news articles in the universe.
    
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
    """
    Aggregate sentiment scores for each ticker.
    
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
        
        # Extract sentiment and confidence from each article
        sentiment_values = []
        for article in scored_articles:
            sentiment_label = article.get("sentiment", "neutral")
            confidence = article.get("confidence", 0.0)
            
            # Convert sentiment to numerical value: positive=1, neutral=0, negative=-1
            sentiment_map = {
                "positive": 1.0,
                "neutral": 0.0,
                "negative": -1.0
            }
            base_score = sentiment_map.get(sentiment_label, 0.0)
            
            # Weight by confidence
            weighted_score = base_score * confidence
            sentiment_values.append(weighted_score)
        
        # Calculate average sentiment score
        if sentiment_values:
            avg_score = sum(sentiment_values) / len(sentiment_values)
            # Ensure score is in [-1, 1] range
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
    """
    Generate active trading list and waiting list based on sentiment scores.
    
    Args:
        sentiment_scores: Dictionary mapping ticker to sentiment score
        top_n: Number of tickers for active trading list
        waitlist_n: Number of tickers for waiting list
        
    Returns:
        Tuple of (active_list, waitlist) where each is a list of tickers
    """
    print("Generating trading lists from sentiment scores...")
    
    # Filter out tickers with zero score (no news or neutral)
    scored_tickers = {t: s for t, s in sentiment_scores.items() if abs(s) > 0.01}
    
    if not scored_tickers:
        print("WARNING: No scored tickers found, returning empty lists")
        return [], []
    
    # Sort by sentiment score (descending - most positive first)
    sorted_tickers = sorted(
        scored_tickers.items(), 
        key=lambda x: x[1], 
        reverse=True
    )
    
    # Extract ticker symbols
    ticker_symbols = [ticker for ticker, score in sorted_tickers]
    
    # Generate lists
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
    """
    Update trading lists when positions close.
    
    Args:
        closed_positions: List of tickers that just closed positions
        current_active: Current active trading list
        current_waitlist: Current waiting list
        all_tickers: Complete universe of tickers
        sentiment_scores: Current sentiment scores for all tickers
        top_n: Desired size of active list
        waitlist_n: Desired size of waiting list
        
    Returns:
        Tuple of (updated_active_list, updated_waitlist)
    """
    print(f"Updating lists due to {len(closed_positions)} closed positions: {closed_positions}")
    
    # Remove closed positions from current lists
    updated_active = [t for t in current_active if t not in closed_positions]
    updated_waitlist = [t for t in current_waitlist if t not in closed_positions]
    
    # Calculate how many spots we need to fill
    active_slots_needed = top_n - len(updated_active)
    waitlist_slots_needed = waitlist_n - len(updated_waitlist)
    
    print(f"Need to fill {active_slots_needed} active slots and {waitlist_slots_needed} waitlist slots")
    
    # Get available tickers (not in either list and not closed)
    in_use = set(updated_active) | set(updated_waitlist) | set(closed_positions)
    available_tickers = [t for t in all_tickers if t not in in_use]
    
    # Sort available tickers by sentiment score (descending)
    available_scored = [
        (t, sentiment_scores.get(t, 0.0)) 
        for t in available_tickers
    ]
    available_scored.sort(key=lambda x: x[1], reverse=True)
    available_sorted = [t for t, score in available_scored]
    
    # Fill active list first
    if active_slots_needed > 0 and available_sorted:
        to_add_to_active = available_sorted[:active_slots_needed]
        updated_active.extend(to_add_to_active)
        available_sorted = available_sorted[active_slots_needed:]
        print(f"Added to active: {to_add_to_active}")
    
    # Fill waiting list
    if waitlist_slots_needed > 0 and available_sorted:
        to_add_to_waitlist = available_sorted[:waitlist_slots_needed]
        updated_waitlist.extend(to_add_to_waitlist)
        print(f"Added to waitlist: {to_add_to_waitlist}")
    
    # Ensure we don't exceed desired sizes (in case of duplicates or other issues)
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
    model_name: str = "mistral",
    pause: float = 0.5
) -> Tuple[List[str], List[str], Dict[str, float]]:
    """
    Complete workflow: fetch news, score sentiment, and generate trading lists.
    
    Args:
        tickers: Universe of tickers to evaluate
        top_n: Number of tickers for active trading list
        waitlist_n: Number of tickers for waiting list
        max_articles_per_ticker: Max news articles to fetch per ticker
        model_name: Ollama model for sentiment scoring
        pause: Pause between API requests
        
    Returns:
        Tuple of (active_list, waitlist, all_sentiment_scores)
    """
    print(f"Starting watchlist generation for {len(tickers)} tickers...")
    start_time = time.time()
    
    # Step 1: Fetch news for universe
    news_data = fetch_universe_news(
        tickers=tickers,
        max_articles_per_ticker=max_articles_per_ticker,
        pause=pause
    )
    
    # Step 2: Score sentiment
    scored_news = score_universe_sentiment(
        news_data=news_data,
        model_name=model_name
    )
    
    # Step 3: Aggregate scores
    sentiment_scores = aggregate_ticker_sentiment(scored_news)
    
    # Step 4: Generate trading lists
    active_list, waitlist = generate_trading_lists(
        sentiment_scores=sentiment_scores,
        top_n=top_n,
        waitlist_n=waitlist_n
    )
    
    elapsed_time = time.time() - start_time
    print(f"Watchlist generation completed in {elapsed_time:.1f} seconds")
    
    return active_list, waitlist, sentiment_scores


if __name__ == "__main__":
    # Example usage
    print("=== RAATS Watchlist Manager Demo ===")
    
    # Example ticker universe (in practice, this would be 50-100 tickers)
    example_universe = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
        "META", "NVDA", "NFLX", "AMD", "INTC",
        "CSCO", "ADBE", "CRM", "ORCL", "IBM",
        "QCOM", "TXN", "HON", "UNH", "JNJ",
        "PG", "JPM", "BAC", "WFC", "C",
        "V", "MA", "DIS", "NKE", "SBUX",
        "MCD", "WMT", "TGT", "COST", "HD",
        "LOW", "PG", "CL", "KMB", "GE",
        "CAT", "MMM", "BA", "IBM", "F",
        "GM", "XOM", "CVX", "COP", "EOG",
        "SLB", "HAL", "OKE", "WMB", "DUK",
        "SO", "D", "AEP", "EXC", "XEL"
    ]
    
    # Limit to first 20 for demo speed
    demo_universe = example_universe[:20]
    print(f"Using demo universe of {len(demo_universe)} tickers: {demo_universe}")
    
    try:
        # Generate trading lists
        active, waitlist, scores = get_top_tickers_by_sentiment(
            tickers=demo_universe,
            top_n=5,  # Smaller for demo
            waitlist_n=5,
            max_articles_per_ticker=3,
            pause=1.0  # Longer pause for demo to be nice to APIs
        )
        
        print("\n=== RESULTS ===")
        print(f"Active list (top 5): {active}")
        print(f"Waiting list (next 5): {waitlist}")
        
        # Show scores for active list
        print("\nTop 5 scores:")
        active_scores = [(t, scores.get(t, 0.0)) for t in active]
        active_scores.sort(key=lambda x: x[1], reverse=True)
        for ticker, score in active_scores:
            print(f"  {ticker}: {score:.3f}")
            
    except Exception as e:
        print(f"Error in demo: {e}")
        print("Make sure Ollama is running and required packages are installed")
    
    print("\nDemo completed.")