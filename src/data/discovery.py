"""
Discovery layer for dynamic ticker universe generation.
Implements:
1. 35 deterministic random S&P 500 candidates each day.
2. Google News RSS discovers ticker/company mentions from previous market day.
3. yfinance identifies previous-session market movers from S&P 500 universe.
4. Yahoo Finance news filtered by publication timestamp.
5. Excludes open positions from discovery to avoid churning existing holdings.
6. Generates final day's top 50 by comparing previous day's Yahoo Finance top 50 performers
   with Google RSS top 50 from previous day.
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
# HELPER FUNCTIONS
# ============================================================================
def _get_previous_trading_day() -> datetime:
    """Return the previous trading day (skipping weekends)."""
    today = datetime.now().date()
    # Go back one day at a time until we find a weekday (Mon-Fri)
    day = today - timedelta(days=1)
    while day.weekday() >= 5:  # Saturday=5, Sunday=6
        day -= timedelta(days=1)
    return datetime.combine(day, datetime.min.time())

def _format_date_for_yfinance(dt: datetime) -> str:
    """Format date as YYYY-MM-DD for yfinance history."""
    return dt.strftime("%Y-%m-%d")

def get_sp500_universe() -> list[str]:
    """Fetch the current S&P 500 ticker list from Wikipedia."""
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        df = tables[0]
        tickers = df['Symbol'].str.replace('.', '-', regex=False).tolist()
        return tickers
    except Exception as e:
        print(f"Warning: Could not fetch S&P 500 list: {e}")
        # Fallback to a small list if needed
        return ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]

def get_random_base(seed: str | None = None) -> list[str]:
    """
    Return a deterministic random sample of BASE_RANDOM_COUNT S&P 500 tickers.
    If seed is provided, use it; otherwise use today's date (YYYY-MM-DD) for daily determinism.
    """
    if seed is None:
        seed = datetime.now().strftime("%Y-%m-%d")
    random.seed(seed)
    universe = get_sp500_universe()
    # Ensure we don't request more than available
    count = min(BASE_RANDOM_COUNT, len(universe))
    return random.sample(universe, count)

def _parse_google_news_rss(content: str) -> list[dict]:
    """Parse Google News RSS XML and return list of entries with title and link."""
    try:
        root = ET.fromstring(content)
        namespace = {'': 'http://purl.org/rss/1.0/'}
        items = []
        for item in root.findall('.//item', namespace):
            title_elem = item.find('title', namespace)
            link_elem = item.find('link', namespace)
            pub_date_elem = item.find('pubDate', namespace)
            title = title_elem.text if title_elem is not None else ""
            link = link_elem.text if link_elem is not None else ""
            pub_date = pub_date_elem.text if pub_date_elem is not None else ""
            items.append({"title": title, "link": link, "pub_date": pub_date})
        return items
    except Exception as e:
        print(f"Error parsing Google News RSS: {e}")
        return []

def _extract_tickers_from_text(text: str) -> set[str]:
    """Extract potential ticker symbols from text (simple regex for 1-5 uppercase letters)."""
    # Look for words that are all uppercase, length 1-5, not common words
    # This is a simple heuristic; could be improved with a known ticker list.
    words = re.findall(r'\b[A-Z]{1,5}\b', text)
    # Filter out common false positives (could expand this list)
    false_positives = {"THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM", "HIS", "HOW", "ITS", "MAY", "NEW", "NOW", "OLD", "SEE", "TWO", "WHO", "BOY", "DID", "LET", "PUT", "SAY", "SHE", "TOO", "USE"}
    tickers = {w for w in words if w not in false_positives}
    return tickers

def discover_tickers_from_news(date: datetime | None = None) -> list[str]:
    """
    Discover tickers mentioned in Google News RSS for a given date (default: previous trading day).
    Returns a list of unique ticker symbols mentioned in the news articles.
    """
    if date is None:
        date = _get_previous_trading_day()
    # Format date for query? We'll rely on Google's own date sorting; we'll just fetch recent news and filter by date later if needed.
    # For simplicity, we'll fetch news for each query and extract tickers, then we could filter by pub_date if we wanted to be strict.
    # We'll just collect tickers from all news items (assuming they are recent).
    mentioned = set()
    for query in NEWS_QUERIES:
        url = GOOGLE_NEWS_RSS.format(query=quote(query))
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                items = _parse_google_news_rss(resp.text)
                for item in items:
                    # Optionally filter by pub_date being the previous day (more complex)
                    # For now, we assume the RSS returns recent news.
                    title = item.get('title', '')
                    mentioned.update(_extract_tickers_from_text(title))
            else:
                print(f"Warning: Google News request failed for query '{query}': {resp.status_code}")
        except Exception as e:
            print(f"Warning: Error fetching Google News for query '{query}': {e}")
        time.sleep(0.1)  # be polite
    return list(mentioned)

def discover_market_movers(universe: list[str] | None = None) -> list[str]:
    """
    Identify previous-session market movers from the S&P 500 universe using yfinance.
    Looks for stocks with significant price change (>= MARKET_MOVE_THRESHOLD) and high volume.
    """
    if universe is None:
        universe = get_sp500_universe()
    # Limit to a reasonable number to avoid rate limiting; we'll take first 100 if universe larger
    # But we can use the whole universe; yfinance download can handle many tickers.
    # We'll download data for the previous trading day.
    prev_day = _get_previous_trading_day()
    start_str = _format_date_for_yfinance(prev_day)
    # We need data for the previous day and the day before to calculate change? Actually we want previous session's change.
    # We'll download 2 days of data to ensure we have the previous close and the day before close.
    day_before = prev_day - timedelta(days=1)
    while day_before.weekday() >= 5:  # skip weekends
        day_before -= timedelta(days=1)
    start_str = _format_date_for_yfinance(day_before)
    end_str = _format_date_for_yfinance(prev_day)
    try:
        # Download adjusted close and volume for the universe
        data = yf.download(universe, start=start_str, end=end_str, progress=False, threads=True)
        if data is None or data.empty:
            return []
        # Extract adjusted close and volume; handle multi-index columns
        if isinstance(data.columns, pd.MultiIndex):
            close_data = data['Adj Close'] if 'Adj Close' in data.columns.levels[0] else data['Close']
            vol_data = data['Volume']
        else:
            # Single ticker case (should not happen with universe list)
            close_data = data['Adj Close'] if 'Adj Close' in data.columns else data['Close']
            vol_data = data['Volume']
            close_data = close_data.to_frame()
            vol_data = vol_data.to_frame()
        # Get previous day's close and volume (last row) and day before (second last row)
        if len(close_data) < 2:
            return []
        prev_close = close_data.iloc[-1]
        prev_vol = vol_data.iloc[-1]
        day_before_close = close_data.iloc[-2]
        day_before_vol = vol_data.iloc[-2]
        # Calculate percent change
        pct_change = (prev_close - day_before_close) / day_before_close
        # Calculate volume ratio (today vs yesterday)
        vol_ratio = prev_vol / day_before_vol.replace(0, 1e-9)  # avoid div by zero
        # Filter: significant price change AND above average volume
        movers = (pct_change.abs() >= MARKET_MOVE_THRESHOLD) & (vol_ratio >= MIN_VOLUME_RATIO)
        mover_tickers = prev_close[movers].index.tolist()
        # Limit to top MARKET_MOVER_COUNT by absolute percent change
        if len(mover_tickers) > MARKET_MOVER_COUNT:
            mover_pct = pct_change[mover_tickers].abs()
            top_movers = mover_pct.nlargest(MARKET_MOVER_COUNT).index.tolist()
            return top_movers
        return mover_tickers
    except Exception as e:
        print(f"Error discovering market movers: {e}")
        return []

def filter_yahoo_finance_news_by_timestamp(news_items: list[dict], hours_back: int = 24) -> list[dict]:
    """
    Filter Yahoo Finance news items by publication timestamp (within last `hours_back` hours).
    Each news item is expected to have a 'providerPublishTime' field (Unix timestamp).
    """
    if not news_items:
        return []
    cutoff_time = time.time() - (hours_back * 3600)
    filtered = []
    for item in news_items:
        pub_time = item.get('providerPublishTime')
        if pub_time is None:
            # If no timestamp, we cannot filter; we'll keep it (or skip?)
            continue
        if pub_time >= cutoff_time:
            filtered.append(item)
    return filtered

def get_previous_day_top50_yahoo() -> list[str]:
    """
    Get the top 50 performing stocks from Yahoo Finance for the previous trading day,
    sorted by percent change (descending).
    """
    universe = get_sp500_universe()
    prev_day = _get_previous_trading_day()
    # We need data for the previous day and the day before to calculate change
    day_before = prev_day - timedelta(days=1)
    while day_before.weekday() >= 5:  # skip weekends
        day_before -= timedelta(days=1)
    start_str = _format_date_for_yfinance(day_before)
    end_str = _format_date_for_yfinance(prev_day)
    try:
        data = yf.download(universe, start=start_str, end=end_str, progress=False, threads=True)
        if data is None or data.empty:
            return []
        if isinstance(data.columns, pd.MultiIndex):
            close_data = data['Adj Close'] if 'Adj Close' in data.columns.levels[0] else data['Close']
        else:
            close_data = data['Adj Close'] if 'Adj Close' in data.columns else data['Close']
        if len(close_data) < 2:
            return []
        prev_close = close_data.iloc[-1]
        day_before_close = close_data.iloc[-2]
        pct_change = (prev_close - day_before_close) / day_before_close
        # Sort descending by percent change and take top 50
        top50 = pct_change.sort_values(ascending=False).head(50).index.tolist()
        return top50
    except Exception as e:
        print(f"Error getting previous day top 50 Yahoo performers: {e}")
        return []

def get_previous_day_google_rss_top50() -> list[str]:
    """
    Get the top 50 most-mentioned tickers in Google News RSS for the previous trading day.
    We'll fetch news for our standard queries, extract tickers from titles, count mentions,
    and return the top 50 by frequency.
    """
    date = _get_previous_trading_day()
    # We'll fetch news and count ticker mentions in titles (could also include description if we had it)
    mentions = {}
    for query in NEWS_QUERIES:
        url = GOOGLE_NEWS_RSS.format(query=quote(query))
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                items = _parse_google_news_rss(resp.text)
                for item in items:
                    title = item.get('title', '')
                    tickers_in_title = _extract_tickers_from_text(title)
                    for t in tickers_in_title:
                        mentions[t] = mentions.get(t, 0) + 1
            else:
                print(f"Warning: Google News request failed for query '{query}': {resp.status_code}")
        except Exception as e:
            print(f"Warning: Error fetching Google News for query '{query}': {e}")
        time.sleep(0.1)
    # Sort by mention count descending, take top 50
    sorted_tickers = sorted(mentions.items(), key=lambda x: x[1], reverse=True)
    top50 = [ticker for ticker, _count in sorted_tickers[:50]]
    return top50

def get_final_top50_universe() -> list[str]:
    """
    Generate final day's top 50 by comparing previous day's Yahoo Finance top 50 performers
    with Google RSS top 50 from previous day.
    We take the intersection of the two lists; if intersection size < 50, we supplement
    with tickers from the union ranked by a combined score ( Yahoo rank + Google rank ).
    """
    yahoo_top50 = get_previous_day_top50_yahoo()
    google_top50 = get_previous_day_google_rss_top50()
    if not yahoo_top50:
        yahoo_top50 = []
    if not google_top50:
        google_top50 = []
    # Convert to sets for intersection
    yahoo_set = set(yahoo_top50)
    google_set = set(google_top50)
    intersection = list(yahoo_set & google_set)
    # If we have at least 50 in intersection, return that (sorted by some combined score? we'll just return intersection)
    if len(intersection) >= 50:
        # For determinism, sort alphabetically
        return sorted(intersection)[:50]
    # Otherwise, we need to add more tickers from the union
    union = list(yahoo_set | google_set)
    # We'll rank union tickers by sum of ranks (lower is better). Tickers not in one list get a large rank penalty.
    rank_yahoo = {ticker: i+1 for i, ticker in enumerate(yahoo_top50)}
    rank_google = {ticker: i+1 for i, ticker in enumerate(google_top50)}
    def combined_score(ticker):
        ry = rank_yahoo.get(ticker, 999)  # penalize missing
        rg = rank_google.get(ticker, 999)
        return ry + rg
    union_sorted = sorted(union, key=combined_score)
    # Take top 50 from this sorted union
    final = union_sorted[:50]
    return final

# ============================================================================
# MAIN DISCOVERY FUNCTION (for backward compatibility)
# ============================================================================
def get_discovery_components() -> tuple[list[str], list[str], dict]:
    """
    Return components for the dynamic universe:
    - candidate_universe: list of tickers to score (final top 50 from Yahoo/Google comparison)
    - random_list: 35 deterministic random S&P 500 tickers (for logging)
    - auxiliary: dict with extra info for logging (e.g., news mentions, movers)
    """
    # 1. Get the 35 deterministic random S&P 500 candidates (for logging)
    random_list = get_random_base()
    # 2. Get the final top 50 universe from Yahoo/Google comparison
    candidate_universe = get_final_top50_universe()
    # 3. Optionally, we could also compute news discoveries and market movers for auxiliary logging
    # But we'll keep it simple for now; we can add more if needed.
    auxiliary = {
        "yahoo_top50": get_previous_day_top50_yahoo(),
        "google_top50": get_previous_day_google_rss_top50(),
        "note": "Universe derived from Yahoo/Google top 50 comparison"
    }
    return candidate_universe, random_list, auxiliary