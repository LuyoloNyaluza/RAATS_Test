"""
Discovery layer for dynamic ticker universe generation.

Implements:
1. 35 deterministic random S&P 500 candidates each day.
2. Google News RSS discovers company/ticker mentions from the previous
   completed market session.
3. yfinance identifies previous-session market movers.
4. Yahoo Finance news can be filtered by publication timestamp.
5. Excludes open positions from discovery to avoid churning existing holdings.
6. Generates a final candidate universe of up to 50 tickers.
"""

from datetime import datetime, timedelta
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

MARKET_MOVE_THRESHOLD = 0.03
MIN_VOLUME_RATIO = 1.20

REQUEST_TIMEOUT = 15

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?"
    "q={query}&hl=en-US&gl=US&ceid=US:en"
)

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

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/153.0.0.0 "
        "Safari/537.36"
    )
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_previous_trading_day() -> datetime:
    """
    Return the previous weekday.

    This currently skips weekends. Exchange holiday handling can be added
    later if an exchange calendar is introduced.
    """

    today = datetime.now().date()

    day = today - timedelta(days=1)

    while day.weekday() >= 5:
        day -= timedelta(days=1)

    return datetime.combine(day, datetime.min.time())


def _get_day_before(day: datetime) -> datetime:
    """Return the previous weekday before the supplied day."""

    previous = day.date() - timedelta(days=1)

    while previous.weekday() >= 5:
        previous -= timedelta(days=1)

    return datetime.combine(previous, datetime.min.time())


def _format_date_for_yfinance(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


# ============================================================================
# S&P 500 UNIVERSE
# ============================================================================

def get_sp500_universe() -> list[str]:
    """
    Fetch the current S&P 500 ticker list from Wikipedia.

    Uses requests first so that a browser-like User-Agent is supplied.
    """

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

    try:
        response = requests.get(
            url,
            headers=HTTP_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        tables = pd.read_html(response.text)

        if not tables:
            raise ValueError("No tables found on S&P 500 page")

        df = tables[0]

        if "Symbol" not in df.columns:
            raise ValueError("S&P 500 table does not contain Symbol column")

        tickers = (
            df["Symbol"]
            .astype(str)
            .str.replace(".", "-", regex=False)
            .str.upper()
            .tolist()
        )

        tickers = list(dict.fromkeys(tickers))

        print(f"S&P 500 universe loaded: {len(tickers)} tickers")

        return tickers

    except Exception as e:
        print(f"Warning: Could not fetch S&P 500 list: {e}")

        # Do not silently pretend this is a dynamic S&P 500 universe.
        return []


# ============================================================================
# COMPANY / TICKER MAPPING
# ============================================================================

def get_sp500_company_map() -> dict[str, str]:
    """
    Return mapping:

        ticker -> company name

    Example:

        AAPL -> Apple Inc.
    """

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

    try:
        response = requests.get(
            url,
            headers=HTTP_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        tables = pd.read_html(response.text)

        if not tables:
            return {}

        df = tables[0]

        required = {"Symbol", "Security"}

        if not required.issubset(df.columns):
            return {}

        company_map = {}

        for _, row in df.iterrows():

            ticker = str(row["Symbol"]).replace(".", "-").upper()
            company = str(row["Security"])

            company_map[ticker] = company

        return company_map

    except Exception as e:
        print(f"Warning: Could not build S&P 500 company map: {e}")
        return {}


# ============================================================================
# RANDOM EXPLORATION
# ============================================================================

def get_random_base(seed: str | None = None) -> list[str]:
    """
    Return 35 deterministic random S&P 500 tickers.

    The same date produces the same exploratory sample.
    """

    if seed is None:
        seed = datetime.now().strftime("%Y-%m-%d")

    universe = get_sp500_universe()

    if not universe:
        return []

    rng = random.Random(seed)

    count = min(BASE_RANDOM_COUNT, len(universe))

    return rng.sample(universe, count)


# ============================================================================
# GOOGLE NEWS RSS
# ============================================================================

def _parse_google_news_rss(content: str) -> list[dict]:
    """Parse Google News RSS XML."""

    try:
        root = ET.fromstring(content)

        items = []

        for item in root.findall(".//item"):

            title_elem = item.find("title")
            link_elem = item.find("link")
            pub_date_elem = item.find("pubDate")
            description_elem = item.find("description")

            title = (
                title_elem.text
                if title_elem is not None and title_elem.text
                else ""
            )

            link = (
                link_elem.text
                if link_elem is not None and link_elem.text
                else ""
            )

            pub_date = (
                pub_date_elem.text
                if pub_date_elem is not None and pub_date_elem.text
                else ""
            )

            description = (
                description_elem.text
                if description_elem is not None and description_elem.text
                else ""
            )

            items.append(
                {
                    "title": title,
                    "link": link,
                    "pub_date": pub_date,
                    "description": description,
                }
            )

        return items

    except Exception as e:
        print(f"Error parsing Google News RSS: {e}")
        return []


def _normalise_company_name(name: str) -> str:
    """Normalise company names for simple text matching."""

    name = name.lower()

    name = re.sub(
        r"\b(inc|corp|corporation|company|co|ltd|plc|class [a-z])\b",
        " ",
        name,
    )

    name = re.sub(r"[^a-z0-9 ]+", " ", name)

    name = re.sub(r"\s+", " ", name).strip()

    return name


def _find_tickers_in_article(
    title: str,
    description: str,
    company_map: dict[str, str],
) -> set[str]:
    """
    Identify S&P 500 tickers from article text.

    Uses both explicit ticker-style matches and company-name matching.
    """

    text = f"{title} {description}"

    text_upper = text.upper()

    discovered = set()

    # Explicit uppercase ticker candidates.
    words = re.findall(r"\b[A-Z]{1,5}\b", text_upper)

    for ticker in words:

        if ticker in company_map:
            discovered.add(ticker)

    # Company-name matching.
    text_normalised = _normalise_company_name(text)

    for ticker, company in company_map.items():

        company_normalised = _normalise_company_name(company)

        if not company_normalised:
            continue

        if company_normalised in text_normalised:
            discovered.add(ticker)

    return discovered


def get_google_news_discoveries(
    date: datetime | None = None,
) -> tuple[list[str], dict[str, int]]:
    """
    Discover S&P 500 tickers mentioned in Google News.

    Returns:

        tickers
        mention_counts
    """

    if date is None:
        date = _get_previous_trading_day()

    company_map = get_sp500_company_map()

    if not company_map:
        return [], {}

    mentions: dict[str, int] = {}

    target_date = date.date()

    for query in NEWS_QUERIES:

        url = GOOGLE_NEWS_RSS.format(
            query=quote(query)
        )

        try:
            response = requests.get(
                url,
                headers=HTTP_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            items = _parse_google_news_rss(response.text)

            for item in items:

                pub_date = item.get("pub_date", "")

                # Try to enforce the previous-session date.
                if pub_date:
                    try:
                        parsed_date = parsedate_to_datetime(pub_date)

                        if parsed_date.date() != target_date:
                            continue

                    except Exception:
                        # If Google gives an unexpected date format,
                        # retain the article rather than crashing discovery.
                        pass

                title = item.get("title", "")
                description = item.get("description", "")

                tickers = _find_tickers_in_article(
                    title,
                    description,
                    company_map,
                )

                for ticker in tickers:
                    mentions[ticker] = mentions.get(ticker, 0) + 1

        except Exception as e:
            print(
                f"Warning: Google News request failed "
                f"for '{query}': {e}"
            )

        time.sleep(0.1)

    ranked = sorted(
        mentions.items(),
        key=lambda item: (-item[1], item[0]),
    )

    top_tickers = [
        ticker
        for ticker, _count in ranked[:NEWS_DISCOVERY_COUNT]
    ]

    return top_tickers, mentions


# ============================================================================
# MARKET MOVERS
# ============================================================================

def discover_market_movers(
    universe: list[str] | None = None,
) -> list[str]:
    """
    Identify previous-session S&P 500 market movers.

    Requires:
        - absolute price movement >= 3%
        - volume ratio >= 1.20
    """

    if universe is None:
        universe = get_sp500_universe()

    if not universe:
        return []

    prev_day = _get_previous_trading_day()
    day_before = _get_day_before(prev_day)

    start_str = _format_date_for_yfinance(day_before)

    # yfinance end date is exclusive, so add one day.
    end_str = _format_date_for_yfinance(
        prev_day + timedelta(days=1)
    )

    try:

        data = yf.download(
            universe,
            start=start_str,
            end=end_str,
            progress=False,
            threads=True,
            auto_adjust=False,
        )

        if data is None or data.empty:
            return []

        if isinstance(data.columns, pd.MultiIndex):

            close_data = (
                data["Adj Close"]
                if "Adj Close" in data.columns.get_level_values(0)
                else data["Close"]
            )

            volume_data = data["Volume"]

        else:

            close_data = (
                data["Adj Close"]
                if "Adj Close" in data.columns
                else data["Close"]
            )

            volume_data = data["Volume"]

            if isinstance(close_data, pd.Series):
                close_data = close_data.to_frame()

            if isinstance(volume_data, pd.Series):
                volume_data = volume_data.to_frame()

        if len(close_data) < 2:
            return []

        previous_close = close_data.iloc[-1]
        day_before_close = close_data.iloc[-2]

        previous_volume = volume_data.iloc[-1]
        day_before_volume = volume_data.iloc[-2]

        pct_change = (
            (previous_close - day_before_close)
            / day_before_close
        )

        volume_ratio = (
            previous_volume
            / day_before_volume.replace(0, 1e-9)
        )

        qualifies = (
            pct_change.abs() >= MARKET_MOVE_THRESHOLD
        ) & (
            volume_ratio >= MIN_VOLUME_RATIO
        )

        movers = pct_change[qualifies].abs()

        movers = movers.sort_values(
            ascending=False
        )

        return movers.head(
            MARKET_MOVER_COUNT
        ).index.tolist()

    except Exception as e:

        print(
            f"Error discovering market movers: {e}"
        )

        return []


# ============================================================================
# PREVIOUS-DAY YAHOO PERFORMERS
# ============================================================================

def get_previous_day_top50_yahoo(
    universe: list[str] | None = None,
) -> list[str]:
    """
    Get up to 50 S&P 500 stocks with the largest positive
    previous-session percentage movement.
    """

    if universe is None:
        universe = get_sp500_universe()

    if not universe:
        return []

    prev_day = _get_previous_trading_day()
    day_before = _get_day_before(prev_day)

    start_str = _format_date_for_yfinance(day_before)

    end_str = _format_date_for_yfinance(
        prev_day + timedelta(days=1)
    )

    try:

        data = yf.download(
            universe,
            start=start_str,
            end=end_str,
            progress=False,
            threads=True,
            auto_adjust=False,
        )

        if data is None or data.empty:
            return []

        if isinstance(data.columns, pd.MultiIndex):

            close_data = (
                data["Adj Close"]
                if "Adj Close" in data.columns.get_level_values(0)
                else data["Close"]
            )

        else:

            close_data = (
                data["Adj Close"]
                if "Adj Close" in data.columns
                else data["Close"]
            )

            if isinstance(close_data, pd.Series):
                close_data = close_data.to_frame()

        if len(close_data) < 2:
            return []

        previous_close = close_data.iloc[-1]
        day_before_close = close_data.iloc[-2]

        pct_change = (
            (previous_close - day_before_close)
            / day_before_close
        )

        return (
            pct_change
            .dropna()
            .sort_values(ascending=False)
            .head(50)
            .index
            .tolist()
        )

    except Exception as e:

        print(
            f"Error getting previous-day Yahoo performers: {e}"
        )

        return []


# ============================================================================
# FINAL CANDIDATE UNIVERSE
# ============================================================================

def get_final_top50_universe() -> tuple[list[str], dict]:
    """
    Build the final dynamic candidate universe.

    Sources:
        1. Random S&P 500 exploration
        2. Google News discoveries
        3. Previous-session market movers
        4. Previous-session Yahoo performers

    The final universe is capped at 50.
    """

    sp500 = get_sp500_universe()

    if not sp500:
        print(
            "ERROR: S&P 500 universe unavailable. "
            "Dynamic discovery cannot continue."
        )

        return [], {
            "random": [],
            "google_news": [],
            "market_movers": [],
            "yahoo_top50": [],
        }

    print(
        f"Discovery source universe: "
        f"{len(sp500)} S&P 500 tickers"
    )

    # ------------------------------------------------------------
    # 1. Random exploration
    # ------------------------------------------------------------

    rng = random.Random(
        datetime.now().strftime("%Y-%m-%d")
    )

    random_count = min(
        BASE_RANDOM_COUNT,
        len(sp500),
    )

    random_list = rng.sample(
        sp500,
        random_count,
    )

    # ------------------------------------------------------------
    # 2. Google News
    # ------------------------------------------------------------

    google_top, google_mentions = (
        get_google_news_discoveries()
    )

    # ------------------------------------------------------------
    # 3. Previous-session market movers
    # ------------------------------------------------------------

    market_movers = discover_market_movers(
        sp500
    )

    # ------------------------------------------------------------
    # 4. Previous-session Yahoo performers
    # ------------------------------------------------------------

    yahoo_top50 = get_previous_day_top50_yahoo(
        sp500
    )

    # ------------------------------------------------------------
    # Combine while preserving source priority
    # ------------------------------------------------------------

    final = []

    def add_ticker(ticker: str) -> None:

        if ticker in sp500 and ticker not in final:

            final.append(ticker)

    # News and market information get priority.
    for ticker in google_top:
        add_ticker(ticker)

    for ticker in market_movers:
        add_ticker(ticker)

    for ticker in yahoo_top50:
        add_ticker(ticker)

    # Random exploration guarantees that the system
    # still has exploratory candidates.
    for ticker in random_list:
        add_ticker(ticker)

    final = final[:MAX_BASE_CANDIDATES]

    print(
        f"Dynamic candidate universe generated: "
        f"{len(final)} tickers"
    )

    print(
        f"  Google News discoveries: {len(google_top)}"
    )

    print(
        f"  Market movers: {len(market_movers)}"
    )

    print(
        f"  Yahoo performers: {len(yahoo_top50)}"
    )

    print(
        f"  Random exploration: {len(random_list)}"
    )

    return final, {
        "random": random_list,
        "google_news": google_top,
        "google_mentions": google_mentions,
        "market_movers": market_movers,
        "yahoo_top50": yahoo_top50,
    }


# ============================================================================
# DISCOVERY API USED BY trading_loop_dynamic.py
# ============================================================================

def get_discovery_components(
    open_positions: set[str] | None = None,
) -> tuple[list[str], list[str], dict]:
    """
    Return:

        candidate_universe
        random_list
        auxiliary

    This is the interface used by trading_loop_dynamic.py.
    """

    if open_positions is None:
        open_positions = set()

    candidate_universe, auxiliary = (
        get_final_top50_universe()
    )

    # Prevent existing positions from being rediscovered.
    filtered_universe = [
        ticker
        for ticker in candidate_universe
        if ticker not in open_positions
    ]

    random_list = [
        ticker
        for ticker in auxiliary["random"]
        if ticker not in open_positions
    ]

    print(
        f"Discovery universe: "
        f"{len(candidate_universe)} candidates "
        f"-> {len(filtered_universe)} "
        f"after excluding open positions"
    )

    return (
        filtered_universe,
        random_list,
        auxiliary,
    )


# ============================================================================
# TEST
# ============================================================================

if __name__ == "__main__":

    print("=" * 60)
    print("DYNAMIC DISCOVERY TEST")
    print("=" * 60)

    candidates, random_list, auxiliary = (
        get_discovery_components()
    )

    print()
    print(f"Final candidates ({len(candidates)}):")
    print(candidates)

    print()
    print(f"Random exploration ({len(random_list)}):")
    print(random_list)

    print()
    print("Discovery complete.")