"""
Discovery layer for dynamic ticker universe generation.
Implements:
1. 35 deterministic random S&P 500 candidates each day.
2. Google News RSS discovers ticker/company mentions from previous market day.
3. yfinance identifies previous-session market movers from S&P 500 universe.
4. Yahoo Finance news filtered by publication timestamp.
5. Excludes open positions from discovery to avoid churning existing holdings.
"""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote
import random
import re
import time
import xml.etree.ElementTree as ET
import pandas as pd
import requests
import yfinance as yf

# ============================================================================
# CONFIGURATION
# ============================================================================
BASE_RANDOM_COUNT = 35
NEWS_DISCOVERY_COUNT = 10
MARKET_MOVER_COUNT = 10
MAX_BASE_CANDIDATES = 50
TOP_20_COUNT = 20
MARKET_MOVE_THRESHOLD = 0.03  # 3%
MIN_VOLUME_RATIO = 1.20
MAX_NEWS_ITEMS_PER_TICKER = 5
GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?"
    "q={query}&hl=en-US&gl=US&ceid=US:en"
)
REQUEST_TIMEOUT = 15

# Previous-market-day news search themes (not ticker lists)
NEWS_QUERIES = [
    "US stocks market",
    "S&P 500 stocks",
    "Nasdaq stocks",
    "NYSE stocks",
    "stock market earnings",
    "stock market technology",
    "stocks healthcare",
    "stocks semiconductor",
]

# ============================================================================
# 1. TRADING DATE
# ============================================================================
def get_previous_trading_day(target_date=None):
    """Return the most recent weekday before target_date (handles weekends)."""
    if target_date is None:
        target = datetime.now().date()
    elif isinstance(target_date, datetime):
        target = target_date.date()
    else:
        target = target_date
    d = target - timedelta(days=1)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d -= timedelta(days=1)
    return d

def get_previous_trading_day_str(target_date=None):
    return get_previous_trading_day(target_date).strftime("%Y-%m-%d")

# ============================================================================
# 2. LIVE S&P 500 UNIVERSE
# ============================================================================
def get_sp500_universe():
    """Fetch current S&P 500 constituents from Wikipedia."""
    print("Fetching current S&P 500 component universe...")
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        tables = pd.read_html(url)
        if not tables:
            raise RuntimeError("No tables returned from Wikipedia.")
        df = tables[0]
        symbols = (
            df["Symbol"]
            .astype(str)
            .str.strip()
            .str.replace(".", "-", regex=False)
            .tolist()
        )
        symbols = sorted(set(symbols))
        print(f"S&P 500 universe loaded: {len(symbols)} symbols")
        return symbols
    except Exception as exc:
        raise RuntimeError(f"Unable to obtain current S&P 500 universe: {exc}") from exc

# ============================================================================
# 3. DAILY RANDOM EXPLORATION
# ============================================================================
def get_random_base(sp500_symbols, target_date=None, exclude_positions=None):
    """
    Select a deterministic random sample from S&P 500, excluding open positions.
    Same trading day -> same sample. Next trading day -> different sample.
    """
    if target_date is None:
        target_date = datetime.now().date()
    seed = int(target_date.strftime("%Y%m%d"))
    rng = random.Random(seed)
    
    # Filter out excluded positions
    available_symbols = [s for s in sp500_symbols if exclude_positions is None or s not in exclude_positions]
    if not available_symbols:
        return []
    
    count = min(BASE_RANDOM_COUNT, len(available_symbols))
    sample = rng.sample(available_symbols, count)
    print(f"Random exploration sample: {len(sample)} (excluded {len(exclude_positions or [])} positions)")
    return sample

# ============================================================================
# 4. GOOGLE NEWS RSS
# ============================================================================
def fetch_google_news(query):
    """Retrieve Google News RSS results for a query."""
    url = GOOGLE_NEWS_RSS.format(query=quote(query))
    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                )
            },
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"Google News request failed ({query}): {exc}")
        return []
    
    try:
        root = ET.fromstring(response.content)
    except Exception as exc:
        print(f"Failed to parse Google News RSS ({query}): {exc}")
        return []
    
    articles = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub_date = item.findtext("pubDate") or ""
        description = item.findtext("description") or ""
        source_node = item.find("source")
        source = source_node.text if source_node is not None else ""
        published_dt = None
        if pub_date:
            try:
                published_dt = parsedate_to_datetime(pub_date)
            except Exception:
                pass
        articles.append({
            "title": title,
            "link": link,
            "published": published_dt,
            "source": source,
            "description": description,
        })
    return articles

# ============================================================================
# 5. COMPANY / TICKER DISCOVERY
# ============================================================================
def build_company_map(sp500_df):
    """
    Create mappings:
        ticker -> company name
        normalized company name -> ticker
    This lets Google News articles mentioning company names contribute candidates
    even when the ticker symbol itself is not present.
    """
    ticker_to_company = {}
    company_to_ticker = {}
    for _, row in sp500_df.iterrows():
        symbol = str(row["Symbol"]).strip().replace(".", "-")
        company = str(row["Security"]).strip()
        ticker_to_company[symbol] = company
        normalized = re.sub(r"[^a-z0-9 ]", "", company.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if len(normalized) >= 4:
            company_to_ticker[normalized] = symbol
    return ticker_to_company, company_to_ticker

def discover_tickers_from_news(
    sp500_symbols,
    ticker_to_company,
    company_to_ticker,
    target_date,
    exclude_positions=None,
):
    """
    Search Google News and identify S&P 500 companies mentioned in the
    previous-market-day information window.
    Returns: dict of discovered ticker -> list of evidence articles
    """
    print("Scanning Google News for candidate discovery...")
    previous_day = get_previous_trading_day(target_date)
    start_dt = datetime.combine(
        previous_day, datetime.min.time(), tzinfo=timezone.utc
    )
    end_dt = start_dt + timedelta(days=1)
    
    discovered = {}
    valid_symbols = set(sp500_symbols)
    
    for query in NEWS_QUERIES:
        try:
            articles = fetch_google_news(query)
        except Exception as exc:
            print(f"Google News query failed ({query}): {exc}")
            continue
        
        for article in articles:
            published = article["published"]
            if published is None:
                continue
            # Convert naive timestamps to UTC if needed
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            # Information cutoff: only previous-market-day articles
            if not (start_dt <= published < end_dt):
                continue
            
            title = article["title"].lower()
            
            # Direct ticker detection (avoid short/common tickers as words)
            for symbol in valid_symbols:
                if exclude_positions and symbol in exclude_positions:
                    continue
                if len(symbol) < 3:
                    continue
                pattern = rf"\b{re.escape(symbol.lower())}\b"
                if re.search(pattern, title):
                    discovered.setdefault(symbol, []).append(article)
            
            # Company-name detection
            for company_name, symbol in company_to_ticker.items():
                if exclude_positions and symbol in exclude_positions:
                    continue
                if company_name in title:
                    discovered.setdefault(symbol, []).append(article)
    
    # Remove duplicates while preserving evidence (by title+link)
    for symbol in list(discovered.keys()):
        unique = {}
        for article in discovered[symbol]:
            key = (article["title"], article["link"])
            unique[key] = article
        discovered[symbol] = list(unique.values())[:MAX_NEWS_ITEMS_PER_TICKER]
    
    print(f"Google News discovered {len(discovered)} S&P 500 candidates.")
    return discovered

# ============================================================================
# 6. BULK PREVIOUS-SESSION MARKET DATA
# ============================================================================
def fetch_previous_session_data(tickers, target_date=None):
    """
    Download historical daily data to calculate:
        previous-session return, volume ratio, volatility
    Data is downloaded in one yfinance batch.
    """
    if not tickers:
        return pd.DataFrame()
    previous_day = get_previous_trading_day(target_date)
    # Need several sessions before previous_day for volume average and volatility
    start_date = previous_day - timedelta(days=15)
    # yfinance end is exclusive, therefore add one day
    end_date = previous_day + timedelta(days=1)
    print(f"Downloading market data through {previous_day}...")
    try:
        data = yf.download(
            tickers=tickers,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
        return data
    except Exception as exc:
        print(f"yfinance download failed: {exc}")
        return pd.DataFrame()

# ============================================================================
# 7. EXTRACT ONE TICKER'S PREVIOUS SESSION
# ============================================================================
def get_ticker_history_from_bulk(raw_data, symbol, ticker_count):
    """Safely extract one ticker from yfinance's multi-ticker DataFrame."""
    if ticker_count == 1:
        df = raw_data.copy()
    else:
        if not isinstance(raw_data.columns, pd.MultiIndex):
            return None
        if symbol not in raw_data.columns.get_level_values(0):
            return None
        df = raw_data[symbol].copy()
    if df.empty:
        return None
    df = df.dropna(subset=["Close", "Volume"])
    return df

def calculate_previous_session_metrics(df, previous_day):
    """
    Calculate metrics using the explicitly requested previous completed market session.
    """
    if df is None or df.empty:
        return None
    
    # Normalize index to date for comparison
    if hasattr(df.index, "tz") and df.index.tz is not None:
        index_dates = df.index.tz_convert("America/New_York").date
    else:
        index_dates = df.index.date
    
    target_rows = df[
        pd.Series(index_dates, index=df.index) == previous_day
    ]
    if target_rows.empty:
        return None
    
    target = target_rows.iloc[-1]
    close = float(target["Close"])
    volume = float(target["Volume"])
    
    # Data before the target session
    prior_rows = df.loc[df.index < target_rows.index[0]]
    if len(prior_rows) >= 1:
        previous_close = float(prior_rows.iloc[-1]["Close"])
        daily_return = (close - previous_close) / previous_close
    else:
        previous_close = None
        daily_return = 0.0
    
    # Volume baseline including the target session
    volume_window = df.loc[df.index <= target_rows.index[0]]["Volume"].tail(5)
    avg_volume = float(volume_window.mean())
    volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0
    
    returns = df["Close"].pct_change().dropna().tail(10)
    volatility = float(returns.std()) if len(returns) > 1 else 0.0
    
    return {
        "previous_close": previous_close,
        "latest_close": close,
        "daily_return": daily_return,
        "volume": volume,
        "volume_ratio": volume_ratio,
        "volatility": volatility,
    }

# ============================================================================
# 8. DYNAMIC MARKET-MOVER DISCOVERY
# ============================================================================
def discover_market_movers(sp500_symbols, raw_data, target_date=None, exclude_positions=None):
    """
    Identify previous-market-day movers dynamically. No hardcoded mover list.
    """
    previous_day = get_previous_trading_day(target_date)
    movers = {}
    ticker_count = len(sp500_symbols)
    print("Scanning previous-market-day performance for movers...")
    
    for symbol in sp500_symbols:
        if exclude_positions and symbol in exclude_positions:
            continue
        try:
            df = get_ticker_history_from_bulk(raw_data, symbol, ticker_count)
            metrics = calculate_previous_session_metrics(df, previous_day)
            if metrics is None:
                continue
            daily_return = metrics["daily_return"]
            volume_ratio = metrics["volume_ratio"]
            # A mover can qualify through price movement OR unusual volume
            if abs(daily_return) >= MARKET_MOVE_THRESHOLD or volume_ratio >= MIN_VOLUME_RATIO:
                movers[symbol] = metrics
        except Exception as exc:
            print(f"Could not evaluate mover {symbol}: {exc}")
    
    # Rank by absolute price movement first, then volume ratio
    ranked = sorted(
        movers.items(),
        key=lambda x: (abs(x[1]["daily_return"]), x[1]["volume_ratio"]),
        reverse=True,
    )
    selected = dict(ranked[:MARKET_MOVER_COUNT])
    print(f"Dynamic market movers discovered: {len(selected)}")
    return selected

# ============================================================================
# 9. BUILD 50-CANDIDATE BASE
# ============================================================================
def build_candidate_base(random_candidates, news_candidates, market_movers):
    """
    Combine all discovery sources while preserving source priority and removing duplicates.
    """
    candidates = []
    def add(symbol):
        if symbol not in candidates:
            candidates.append(symbol)
    
    # Exploration first
    for symbol in random_candidates:
        add(symbol)
    # Information-driven discovery
    for symbol in news_candidates:
        add(symbol)
    # Market-driven discovery
    for symbol in market_movers:
        add(symbol)
    
    candidates = candidates[:MAX_BASE_CANDIDATES]
    print(f"Final candidate base: {len(candidates)} symbols")
    return candidates

# ============================================================================
# 10. YAHOO FINANCE NEWS
# ============================================================================
def get_yahoo_news_for_ticker(symbol, target_date):
    """
    Fetch Yahoo Finance news and retain only articles published during
    the previous completed market day.
    Uses yfinance Ticker.get_news() API.
    """
    previous_day = get_previous_trading_day(target_date)
    start_dt = datetime.combine(
        previous_day, datetime.min.time(), tzinfo=timezone.utc
    )
    end_dt = start_dt + timedelta(days=1)
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.get_news(count=MAX_NEWS_ITEMS_PER_TICKER, tab="news") or []
    except Exception as exc:
        print(f"Yahoo news failed for {symbol}: {exc}")
        return []
    
    filtered = []
    for item in news:
        content = item.get("content", item)
        title = content.get("title") or item.get("title") or ""
        published_raw = (
            content.get("pubDate")
            or content.get("providerPublishTime")
            or item.get("pubDate")
            or item.get("providerPublishTime")
        )
        published = None
        try:
            if isinstance(published_raw, (int, float)):
                published = datetime.fromtimestamp(published_raw, tz=timezone.utc)
            elif isinstance(published_raw, str):
                published = datetime.fromisoformat(
                    published_raw.replace("Z", "+00:00")
                )
        except Exception:
            published = None
        if published is None:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if not (start_dt <= published < end_dt):
            continue
        filtered.append({
            "title": title,
            "published": published.isoformat(),
            "url": (
                content.get("canonicalUrl", {}).get("url")
                if isinstance(content.get("canonicalUrl"), dict)
                else content.get("link")
            ),
        })
    return filtered

# ============================================================================
# 11. FINAL QUANTITATIVE EVALUATION
# ============================================================================
def evaluate_candidates(target_date=None, exclude_positions=None):
    """
    Complete dynamic discovery + quantitative pre-filter.
    Returns Top 20 candidates for the existing LLM/RAG stage.
    """
    if target_date is None:
        target_date = datetime.now().date()
    previous_day = get_previous_trading_day(target_date)
    print("=" * 70)
    print("RAATS PRE-MARKET CANDIDATE DISCOVERY")
    print("=" * 70)
    print(f"Current target date: {target_date}")
    print(f"Previous completed market day: {previous_day}")
    
    # ------------------------------------------------------------------
    # S&P universe (excluding open positions)
    # ------------------------------------------------------------------
    all_sp500_symbols = get_sp500_universe()
    if exclude_positions:
        sp500_symbols = [s for s in all_sp500_symbols if s not in exclude_positions]
    else:
        sp500_symbols = all_sp500_symbols
    print(f"Filtered S&P universe (excluding open positions): {len(sp500_symbols)} symbols")
    
    # Need company names for Google News discovery
    sp500_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    sp500_df = pd.read_html(sp500_url)[0]
    ticker_to_company, company_to_ticker = build_company_map(sp500_df)
    # Remove open positions from company mapping lookup if needed
    if exclude_positions:
        for pos in exclude_positions:
            company_to_ticker = {
                k: v for k, v in company_to_ticker.items() if v != pos
            }
    
    # ------------------------------------------------------------------
    # Random exploration (from filtered pool)
    # ------------------------------------------------------------------
    random_candidates = get_random_base(
        sp500_symbols, target_date, exclude_positions=exclude_positions
    )
    
    # ------------------------------------------------------------------
    # Download market data for entire filtered S&P 500
    # ------------------------------------------------------------------
    raw_sp500_data = fetch_previous_session_data(sp500_symbols, target_date)
    
    # ------------------------------------------------------------------
    # Google News discovery
    # ------------------------------------------------------------------
    google_news = discover_tickers_from_news(
        sp500_symbols,
        ticker_to_company,
        company_to_ticker,
        target_date,
        exclude_positions=exclude_positions,
    )
    news_candidates = list(google_news.keys())[:NEWS_DISCOVERY_COUNT]
    
    # ------------------------------------------------------------------
    # Previous-session market movers
    # ------------------------------------------------------------------
    market_movers = discover_market_movers(
        sp500_symbols, raw_sp500_data, target_date, exclude_positions=exclude_positions
    )
    mover_candidates = list(market_movers.keys())
    
    # ------------------------------------------------------------------
    # Build unique 50 (guaranteed no open positions)
    # ------------------------------------------------------------------
    candidates = build_candidate_base(random_candidates, news_candidates, mover_candidates)
    # Absolute safety check
    if exclude_positions:
        candidates = [c for c in candidates if c not in exclude_positions]
    print(f"Final candidate base (excl. positions): {len(candidates)} symbols")
    
    # ------------------------------------------------------------------
    # Download exact candidate data (smaller set)
    # ------------------------------------------------------------------
    raw_candidate_data = fetch_previous_session_data(candidates, target_date)
    metrics = []
    ticker_count = len(candidates)
    
    for symbol in candidates:
        try:
            df = get_ticker_history_from_bulk(raw_candidate_data, symbol, ticker_count)
            market = calculate_previous_session_metrics(df, previous_day)
            if market is None:
                continue
            
            # Yahoo Finance news
            yahoo_news = get_yahoo_news_for_ticker(symbol, target_date)
            google_articles = google_news.get(symbol, [])
            article_count = len(yahoo_news) + len(google_articles)
            
            # Candidate scoring (quantitative pre-filter)
            return_score = abs(market["daily_return"]) * 40
            volume_score = min(market["volume_ratio"], 5.0) * 10
            news_score = min(article_count, 5) * 5
            quant_score = return_score + volume_score + news_score
            
            metrics.append({
                "ticker": symbol,
                "previous_close": (
                    round(market["previous_close"], 2)
                    if market["previous_close"] is not None
                    else None
                ),
                "latest_close": round(market["latest_close"], 2),
                "daily_return_pct": round(market["daily_return"] * 100, 2),
                "volume": int(market["volume"]),
                "volume_ratio": round(market["volume_ratio"], 2),
                "volatility_pct": round(market["volatility"] * 100, 4),
                "google_news_count": len(google_articles),
                "yahoo_news_count": len(yahoo_news),
                "article_count": article_count,
                "quant_score": round(quant_score, 2),
                "google_headlines": [
                    a["title"] for a in google_articles[:2]
                ],
                "yahoo_headlines": [
                    a["title"] for a in yahoo_news[:3]
                ],
            })
        except Exception as exc:
            print(f"Error evaluating {symbol}: {exc}")
    
    if not metrics:
        print("No candidates survived quantitative evaluation.")
        return pd.DataFrame()
    
    df_metrics = pd.DataFrame(metrics)
    top_20 = (
        df_metrics.sort_values(by="quant_score", ascending=False)
        .head(TOP_20_COUNT)
        .reset_index(drop=True)
    )
    return top_20

# ============================================================================
# 12. ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    top_20_pool = evaluate_candidates()
    if not top_20_pool.empty:
        print("\n")
        print("=" * 70)
        print("TOP 20 QUANTITATIVE SURVIVORS")
        print("=" * 70)
        display_columns = [
            "ticker",
            "daily_return_pct",
            "volume_ratio",
            "google_news_count",
            "yahoo_news_count",
            "article_count",
            "quant_score",
        ]
        print(top_20_pool[display_columns].to_string(index=False))
        print("\n")
        print("=" * 70)
        print("NEWS EVIDENCE")
        print("=" * 70)
        for _, row in top_20_pool.iterrows():
            print(f"\n{row['ticker']} (score={row['quant_score']})")
            for headline in row["google_headlines"]:
                print(f"  Google: {headline}")
            for headline in row["yahoo_headlines"]:
                print(f"  Yahoo: {headline}")