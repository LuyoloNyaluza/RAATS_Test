# File: src/data/fetch_news.py
"""
News fetching utilities for Google News RSS and Yahoo Finance (yfinance).
"""
import json
import os
import time
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import feedparser
import yfinance as yf  # Already used elsewhere in the project


def fetch_financial_news(ticker: str, company_name: Optional[str] = None, max_articles: int = 10):
    """Fetch recent news headlines for a ticker via Google News RSS."""
    query = f"{company_name} {ticker} stock" if company_name else f"{ticker} stock"
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"

    feed = feedparser.parse(url)
    if feed.bozo:
        print(f"  WARNING: could not parse feed for {ticker}: {feed.bozo_exception}")
        return []

    articles = []
    for entry in feed.entries[:max_articles]:
        articles.append({
            "source": {"name": getattr(entry, "source", {}).get("title", "Google News")
                       if hasattr(entry, "source") else "Google News"},
            "author": None,
            "title": entry.get("title", ""),
            "description": entry.get("summary", ""),
            "url": entry.get("link", ""),
            "publishedAt": entry.get("published", datetime.utcnow().isoformat()),
            "content": entry.get("summary", ""),
            "ticker": ticker,
        })
    return articles


def fetch_yfinance_news(ticker: str, max_articles: int = 10):
    """Fetch recent news headlines for a ticker via Yahoo Finance (yfinance)."""
    try:
        ticker_obj = yf.Ticker(ticker)
        news_list = ticker_obj.news  # list of dicts
    except Exception as exc:
        print(f"  WARNING: could not fetch yfinance news for {ticker}: {exc}")
        return []

    articles = []
    for item in news_list[:max_articles]:
        # yfinance news dict keys: uuid, title, publisher, link, providerPublishTime,
        # type, relatedTickers, thumbnail, etc.
        articles.append({
            "source": {"name": item.get("publisher", "Yahoo Finance")},
            "author": None,
            "title": item.get("title", ""),
            "description": item.get("summary", ""),  # yfinance may not have summary; fallback to empty
            "url": item.get("link", ""),
            "publishedAt": datetime.fromtimestamp(item.get("providerPublishTime", 0)).isoformat()
                           if item.get("providerPublishTime") else datetime.utcnow().isoformat(),
            "content": item.get("summary", ""),
            "ticker": ticker,
        })
    return articles


def fetch_mixed_news_for_ticker(ticker: str,
                                max_articles: int = 5,
                                google_count: int = 2,
                                yf_count: int = 3,
                                company_name: Optional[str] = None):
    """
    Fetch news for a ticker aiming for a specific split:
    google_count from Google News, yf_count from Yahoo Finance.
    If a source has insufficient articles, we fill from the other source up to max_articles.
    """
    # Fetch from each source (request a bit more to have buffer)
    google_articles = fetch_financial_news(ticker, company_name=company_name, max_articles=google_count * 2)
    yf_articles = fetch_yfinance_news(ticker, max_articles=yf_count * 2)

    selected = []
    # Take up to google_count from Google
    selected.extend(google_articles[:google_count])
    # Take up to yf_count from Yahoo Finance
    selected.extend(yf_articles[:yf_count])

    # If we still need more to reach max_articles, fill from remaining of either source
    if len(selected) < max_articles:
        remaining_needed = max_articles - len(selected)
        # Remaining Google articles after the ones we took
        remaining_google = google_articles[google_count:]
        # Remaining Yahoo Finance articles after the ones we took
        remaining_yf = yf_articles[yf_count:]
        # Combine remaining, preserving order (Google first then Yahoo)
        remaining = remaining_google + remaining_yf
        selected.extend(remaining[:remaining_needed])

    # Trim to max_articles just in case
    return selected[:max_articles]


def fetch_news_for_watchlist(tickers_with_names: dict, max_articles: int = 10, pause: float = 1.0):
    """Fetch news for multiple tickers (Google News only). Kept for backward compatibility."""
    all_articles = {}
    for ticker, name in tickers_with_names.items():
        print(f"Fetching news for {ticker} ({name})...")
        articles = fetch_financial_news(ticker, company_name=name, max_articles=max_articles)
        print(f"  Found {len(articles)} articles")
        all_articles[ticker] = articles
        time.sleep(pause)
    return all_articles


def save_news(all_articles: dict, output_dir: str = "data/raw/news"):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    for ticker, articles in all_articles.items():
        path = os.path.join(output_dir, f"{ticker}_news_{timestamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(articles, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(articles)} articles for {ticker} to {path}")


if __name__ == "__main__":
    watchlist = {
        "TSLA": "Tesla", "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Google",
        "AMZN": "Amazon", "NVDA": "Nvidia", "META": "Meta", "NFLX": "Netflix",
        "AMD": "AMD", "INTC": "Intel",
    }

    all_articles = fetch_news_for_watchlist(watchlist, max_articles=10, pause=1.0)
    save_news(all_articles)