
import json
import os
import time
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import feedparser


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


def fetch_news_for_watchlist(tickers_with_names: dict, max_articles: int = 10, pause: float = 1.0):
    """Fetch news for multiple tickers."""
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