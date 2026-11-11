import os
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import pandas as pd
import requests
import yfinance as yf

_REAL_YF = yf   # the genuine module: trading_loop swaps `yf` for a gainers-only window

from src.data.score_sentiment import (
    score_articles,
    summarize_ticker_sentiment,
    save_scored_news,
)
from src.data.macro_events import is_trade_blocked_by_macro, MacroEventChecker


# ==========================================
# CONFIGURATION
# ==========================================

TOP_50_COUNT = 50
TOP_40_EQUITIES_COUNT = 40
COMMODITIES_COUNT = 5
CURRENCIES_COUNT = 5

TOP_10_COUNT = 10
WAITING_LIST_COUNT = 20

DOWNLOAD_RETRIES = 3

SENTIMENT_MODEL = os.environ.get(
    "RAATS_SENTIMENT_MODEL",
    "qwen2.5:3b",
)

# Progressive Yahoo screener retrieval.
EQUITY_FETCH_PAGE_SIZE = 250   # Yahoo's maximum: one call returns the whole list when it can
EQUITY_FETCH_MAX = 250
SCREENER_RETRIES = 3

# ------------------------------------------
# Yahoo Finance commodity instruments
# ------------------------------------------

COMMODITY_TICKERS = [
    "GC=F",
    "SI=F",
    "CL=F",
    "NG=F",
    "HG=F",
]

# ------------------------------------------
# Yahoo Finance currency instruments
# ------------------------------------------

CURRENCY_TICKERS = [
    "EURUSD=X",
    "GBPUSD=X",
    "USDJPY=X",
    "AUDUSD=X",
    "USDCAD=X",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ==========================================
# STEP 1: DISCOVER TOP 40 EQUITY GAINERS
# ==========================================

# Tickers earlier batches already used.
EXCLUDE_TICKERS = set()

# Last-resort padding with large caps.
# Batch 1 can use this; later batches can disable it.
EMERGENCY_PADDING = True

EMERGENCY_EQUITY_FALLBACK = [
    "AAPL", "NVDA", "MSFT", "AMZN", "META", "GOOGL", "TSLA",
    "NFLX", "AMD", "INTC", "AVGO", "MU", "QCOM", "AMAT",
    "MRVL", "ORCL", "CRM", "ADBE", "PLTR", "CRWD", "JPM",
    "BAC", "WMT", "COST", "HD", "LOW", "DIS", "V", "MA",
    "PYPL", "UBER", "ABNB", "SHOP", "SNOW", "PANW", "NET",
    "DDOG", "MDB", "COIN", "SOFI", "NKE", "MCD", "SBUX",
    "KO", "MESO", "PEP", "TGT", "CVS", "MRK", "PFE",
    "JNJ", "ABBV", "BMY", "LLY", "GILD", "AMGN", "VRTX",
    "REGN", "BIIB", "AZN", "NVS", "RHHBY", "SNY", "BNTX",
    "MRNA", "PINS", "TWTR", "SNAP", "ZM", "DOCU", "FSLY",
    "ROKU", "SPOT", "SQ", "ETSY",
]


def _usable_equity(symbol):
    """Normal US equity symbol: letters only, 5 characters or fewer."""
    sym = str(symbol or "").upper().strip()
    return sym.isalpha() and len(sym) <= 5


def _broker_offers(symbol: str) -> bool:
    from src.data.broker_symbols import accepts

    return bool(accepts(symbol))


def _add_unique(
    target,
    candidates,
    need,
    exclude,
    skipped=None,
):
    """
    Append usable, unseen, broker-supported equities.

    Continues through candidates until:
      - the required number is reached, or
      - the candidate list is exhausted.
    """

    for raw in candidates:

        if len(target) >= need:
            break

        sym = str(raw or "").upper().strip()

        if not _usable_equity(sym):
            continue

        if sym in exclude or sym in target:
            continue

        if not _broker_offers(sym):

            if skipped is not None and sym not in skipped:
                skipped.append(sym)

            continue

        target.append(sym)

    return target


def _fetch_screener_page(
    screener,
    offset,
    page_size=EQUITY_FETCH_PAGE_SIZE,
):
    """
    Retrieve one Yahoo Finance screener page.

    Example:
      offset=0  -> positions 1-40
      offset=40 -> positions 41-80
      offset=80 -> positions 81-120

    Returns an empty list when the source is exhausted or fails.
    """

    for attempt in range(1, SCREENER_RETRIES + 1):

        try:

            client = yf if screener == "day_gainers" else _REAL_YF
            result = client.screen(
                screener,
                count=page_size,
                offset=offset,
            )

            quotes = (result or {}).get("quotes", []) or []

            return [
                quote.get("symbol")
                for quote in quotes
                if quote.get("symbol")
            ]

        except Exception as exc:

            print(
                f"  {screener}: page offset {offset} "
                f"attempt {attempt} failed: {exc}"
            )

            if attempt < SCREENER_RETRIES:
                time.sleep(2 * attempt)

    return []


def _collect_screener_equities(
    screener: str,
    need: int,
    target=None,
    exclude=None,
    skipped=None,
    seen_symbols=None,
):
    """
    Collect unique, broker-supported equities from a Yahoo screener.

    - Advances by the actual number of symbols returned.
    - Stops if Yahoo repeats a page.
    - Prevents duplicates across discovery sources when seen_symbols is shared.
    """
    exclude = set(exclude or [])
    skipped = skipped if skipped is not None else []
    seen_symbols = seen_symbols if seen_symbols is not None else set()

    accepted = target if target is not None else []
    seen_symbols.update(accepted)
    seen_pages = set()
    offset = 0
    checked = 0

    while len(accepted) < need and offset < EQUITY_FETCH_MAX:
        page = _fetch_screener_page(
            screener,
            offset=offset,
            page_size=EQUITY_FETCH_PAGE_SIZE,
        )

        if not page:
            print(f"  {screener}: no more results at offset {offset}")
            break

        # Normalize and remove duplicate symbols within this page.
        page_symbols = []
        page_seen = set()

        for symbol in page:
            symbol = str(symbol).strip().upper()

            if symbol and symbol not in page_seen:
                page_seen.add(symbol)
                page_symbols.append(symbol)

        if not page_symbols:
            break

        # Detect a repeated Yahoo response. Do not keep scanning the same page.
        page_signature = tuple(page_symbols)

        if page_signature in seen_pages:
            print(
                f"  {screener}: repeated page detected at offset {offset}; "
                "stopping pagination."
            )
            break

        seen_pages.add(page_signature)

        page_accepted = 0

        for symbol in page_symbols:
            checked += 1

            if symbol in exclude or symbol in seen_symbols:
                continue

            if not _usable_equity(symbol):
                continue

            # Do not silently accept a symbol if broker validation fails.
            if not _broker_offers(symbol):
                skipped.append(symbol)
                continue

            seen_symbols.add(symbol)
            accepted.append(symbol)
            page_accepted += 1

            if len(accepted) >= need:
                break

        print(
            f"  {screener}: offset {offset}, returned {len(page_symbols)}, "
            f"checked {checked}, accepted {page_accepted}, "
            f"total {len(accepted)}/{need}"
        )

        # Advance by the actual returned page length, not the requested size.
        offset += len(page_symbols)

    return accepted

def _fetch_day_gainers(
    target=None,
    need=TOP_40_EQUITIES_COUNT,
    exclude=None,
    skipped=None,
):
    """
    Progressively retrieve day gainers.

    If the first 40 contain fewer than 40 broker-approved
    equities, continue with 41-80, 81-120, etc.

    When target is supplied, accepted candidates are added
    immediately and retrieval stops when the target is full.
    """

    print("Extracting top equity gainers from Yahoo Finance...")

    if target is None:
        target = []

    if exclude is None:
        exclude = set()

    if skipped is None:
        skipped = []

    return _collect_screener_equities(
        screener="day_gainers",
        target=target,
        need=need,
        exclude=exclude,
        skipped=skipped,
    )


def _fetch_most_active(
    target=None,
    need=TOP_40_EQUITIES_COUNT,
    exclude=None,
    skipped=None,
):
    """
    Progressively retrieve most-active equities.

    First uses the existing most-active page parser.
    Then supplements it with Yahoo screener pages.

    Broker filtering is applied throughout.
    """

    if target is None:
        target = []

    if exclude is None:
        exclude = set()

    if skipped is None:
        skipped = []

    print("Reading Yahoo most-active stocks...")

    # ------------------------------------------
    # 1. Existing most-active page parser
    # ------------------------------------------

    try:

        from src.data.reserve_tickers import fetch_most_active

        page_symbols, method = fetch_most_active(
            count=EQUITY_FETCH_MAX
        )

        print(
            f"  most-active source: {method} "
            f"({len(page_symbols)} symbols)"
        )

        before = len(target)

        _add_unique(
            target,
            page_symbols,
            need,
            exclude,
            skipped=skipped,
        )

        print(
            f"  most-active page added "
            f"{len(target) - before} approved equities."
        )

    except Exception as exc:

        print(
            f"  most-active page fetch failed: {exc}"
        )

    # ------------------------------------------
    # 2. Yahoo most-active screener pages
    # ------------------------------------------

    if len(target) < need:

        _collect_screener_equities(
            screener="most_actives",
            target=target,
            need=need,
            exclude=exclude,
            skipped=skipped,
        )

    return target


def _fetch_reserve(exclude):
    """
    Retrieve additional candidates from reserve sources.

    Sources:
      - Yahoo trending
      - Yahoo most-active
      - Yahoo world indices

    Only plain equity symbols are accepted.
    """

    try:

        from src.data.reserve_tickers import build_reserve

        result = build_reserve(
            exclude=exclude,
            per_source=TOP_40_EQUITIES_COUNT,
            accept=_usable_equity,
            fill_to_total=False,
        )

        for name, picked in result["by_source"].items():

            print(
                f"  reserve {name}: {len(picked)} "
                f"via {result['methods'][name]}"
            )

        return result["tickers"]

    except Exception as exc:

        print(
            f"  reserve fetch failed: {exc}"
        )

        return []


def get_tickers_from_gainers_feed():
    """
    Get up to 40 distinct broker-supported equities.

    Source order (each source runs only while the list is short):

      1. Yahoo day gainers: the WHOLE ranked list is walked, skipping tickers the broker does
         not offer, until 40 are collected or the list is exhausted.
      2. Yahoo most-active: the same, once the gainers list is exhausted.
      3. Reserve sources (trending ...).
      4. Emergency fallback, when enabled (batch 1 only).

    Tickers in EXCLUDE_TICKERS (used by earlier batches) and duplicates are never returned.
    """

    print("\n" + "=" * 60)
    print("EQUITY DISCOVERY")
    print("=" * 60)

    need = TOP_40_EQUITIES_COUNT
    exclude = {str(t).upper().strip() for t in EXCLUDE_TICKERS}
    tickers = []
    skipped = []

    # 1. Day gainers: continue down the list until 40 approved or the list runs out
    _fetch_day_gainers(target=tickers, need=need, exclude=exclude, skipped=skipped)
    print(f"Day gainers gave {len(tickers)}/{need} broker-supported equities.")

    # 2. Most-active: only when the gainers list is exhausted
    if len(tickers) < need:
        print(f"\nGainers exhausted, short by {need - len(tickers)}: checking most-active.")
        before = len(tickers)
        _fetch_most_active(target=tickers, need=need, exclude=exclude, skipped=skipped)
        print(f"Most-active added: {len(tickers) - before}")

    # 3. Reserve top-up
    if len(tickers) < need:
        print(f"\nStill short by {need - len(tickers)}. Loading reserve candidates.")
        before = len(tickers)
        _add_unique(tickers, _fetch_reserve(exclude | set(tickers)), need, exclude, skipped=skipped)
        print(f"Reserve added: {len(tickers) - before}")

    # 4. Emergency padding
    if len(tickers) < need and EMERGENCY_PADDING:
        print("\nUsing emergency equity fallback.")
        before = len(tickers)
        _add_unique(tickers, EMERGENCY_EQUITY_FALLBACK, need, exclude, skipped=skipped)
        print(f"Emergency fallback added: {len(tickers) - before}")

    if skipped:
        shown = ", ".join(skipped[:15]) + (" ..." if len(skipped) > 15 else "")
        print(f"\nBroker filter: {len(skipped)} unsupported ticker(s) skipped: {shown}")

    if len(tickers) < need:
        print(f"\nWARNING: only {len(tickers)} of {need} broker-supported equities available.")
    else:
        print(f"\nSuccessfully collected {len(tickers)} broker-supported equities.")

    return tickers[:need]


# ==========================================
# STEP 2: BUILD 40 + 5 + 5 UNIVERSE
# ==========================================

def build_market_universe(equity_tickers):

    equities = equity_tickers[
        :TOP_40_EQUITIES_COUNT
    ]

    commodities = COMMODITY_TICKERS[
        :COMMODITIES_COUNT
    ]

    currencies = CURRENCY_TICKERS[
        :CURRENCIES_COUNT
    ]

    universe = []

    for ticker in equities:

        universe.append({
            "Ticker": ticker,
            "Asset_Type": "equity",
        })

    for ticker in commodities:

        universe.append({
            "Ticker": ticker,
            "Asset_Type": "commodity",
        })

    for ticker in currencies:

        universe.append({
            "Ticker": ticker,
            "Asset_Type": "currency",
        })

    print("\n=== MARKET UNIVERSE ===")

    print(f"Equities:    {len(equities)}")
    print(f"Commodities: {len(commodities)}")
    print(f"Currencies:  {len(currencies)}")
    print(f"Total:       {len(universe)}")

    return universe


# ==========================================
# STEP 3: PREVIOUS SESSION PERFORMANCE
# ==========================================

def get_previous_session_returns(market_universe):

    tickers = [
        item["Ticker"]
        for item in market_universe
    ]

    print(
        f"\nVerifying previous-session performance "
        f"for {len(tickers)} instruments..."
    )

    data = None

    for attempt in range(1, DOWNLOAD_RETRIES + 1):

        try:

            data = yf.download(
                tickers=tickers,
                period="1mo",
                interval="1d",
                progress=False,
                auto_adjust=False,
                group_by="column",
                threads=True,
            )

        except Exception as exc:

            print(
                f"  download attempt {attempt} failed: {exc}"
            )

            data = None

        if data is not None and not data.empty:
            break

        if attempt < DOWNLOAD_RETRIES:

            wait = 5 * attempt

            print(
                f"  no pricing data. Retrying in {wait}s..."
            )

            time.sleep(wait)

    if data is None or data.empty:

        raise ValueError(
            "No valid market pricing data returned."
        )

    # ------------------------------------------
    # Extract Adjusted Close / Close
    # ------------------------------------------

    if isinstance(data.columns, pd.MultiIndex):

        level_0 = data.columns.get_level_values(0)

        if "Adj Close" in level_0:
            close_prices = data["Adj Close"]

        elif "Close" in level_0:
            close_prices = data["Close"]

        else:
            raise ValueError(
                "Neither Adj Close nor Close was returned."
            )

    else:

        if "Adj Close" in data.columns:
            close_prices = data["Adj Close"]

        elif "Close" in data.columns:
            close_prices = data["Close"]

        else:
            raise ValueError(
                "Neither Adj Close nor Close was returned."
            )

        # A single ticker may return a Series.
        if isinstance(close_prices, pd.Series):
            close_prices = close_prices.to_frame(
                name=tickers[0]
            )

    if isinstance(close_prices, pd.Series):
        close_prices = close_prices.to_frame()

    close_prices = close_prices.dropna(
        how="all",
        axis=1,
    )

    if close_prices.empty:

        raise ValueError(
            "No valid closing prices available."
        )

    # ------------------------------------------
    # Calculate daily returns
    # ------------------------------------------

    daily_returns = (
        close_prices
        .pct_change(fill_method=None)
        .mul(100)
    )

    daily_returns = daily_returns.dropna(
        how="all"
    )

    if len(daily_returns) < 2:

        raise ValueError(
            "Insufficient data for return calculation."
        )

    # ------------------------------------------
    # Previous completed market session
    # ------------------------------------------

    previous_session_date = daily_returns.index[-2]

    previous_session_returns = daily_returns.iloc[-2]

    target_date = previous_session_date.strftime(
        "%A, %B %d, %Y"
    )

    # ------------------------------------------
    # Build performance records
    # ------------------------------------------

    performance_records = []

    for item in market_universe:

        ticker = item["Ticker"]
        asset_type = item["Asset_Type"]

        if ticker not in previous_session_returns.index:
            continue

        value = previous_session_returns[ticker]

        if pd.isna(value):
            continue

        performance_records.append({
            "Ticker": ticker,
            "Previous_Day_Return_Pct": float(value),
            "Asset_Type": asset_type,
        })

    if not performance_records:

        raise ValueError(
            "No valid previous-session performance was available."
        )

    performance = pd.DataFrame(
        performance_records
    )

    # ------------------------------------------
    # Keep the 40 + 5 + 5 structure where data
    # is available.
    # ------------------------------------------

    equities = (
        performance[
            performance["Asset_Type"] == "equity"
        ]
        .sort_values(
            "Previous_Day_Return_Pct",
            ascending=False,
        )
        .head(TOP_40_EQUITIES_COUNT)
    )

    commodities = (
        performance[
            performance["Asset_Type"] == "commodity"
        ]
        .sort_values(
            "Previous_Day_Return_Pct",
            ascending=False,
        )
        .head(COMMODITIES_COUNT)
    )

    currencies = (
        performance[
            performance["Asset_Type"] == "currency"
        ]
        .sort_values(
            "Previous_Day_Return_Pct",
            ascending=False,
        )
        .head(CURRENCIES_COUNT)
    )

    df_top_50 = pd.concat(
        [
            equities,
            commodities,
            currencies,
        ],
        ignore_index=True,
    )

    return df_top_50, target_date


# ==========================================
# STEP 4: CREATE THREE ARRAYS
# ==========================================

def build_ticker_arrays(df_top_50):

    top_50_performing = (
        df_top_50
        .head(TOP_50_COUNT)
        .copy()
    )

    top_10_to_fetch_articles = (
        top_50_performing
        .head(TOP_10_COUNT)
        .copy()
    )

    waiting_list = (
        top_50_performing
        .iloc[
            TOP_10_COUNT:
            TOP_10_COUNT + WAITING_LIST_COUNT
        ]
        .copy()
    )

    return (
        top_50_performing,
        top_10_to_fetch_articles,
        waiting_list,
    )


# ==========================================
# STEP 5: YAHOO FINANCE NEWS
# ==========================================

def get_yfinance_news(ticker, max_results=3):

    try:

        search = yf.Search(
            ticker,
            max_results=max_results,
        )

        raw_news = search.news

        if not raw_news:
            return []

        articles = []

        for item in raw_news[:max_results]:

            title = item.get(
                "title",
                "No Title",
            )

            link = item.get(
                "link",
                "",
            )

            if not title:
                continue

            articles.append({
                "title": title,
                "link": link,
            })

        return articles

    except Exception as exc:

        print(
            f"    [Diagnostic] yfinance news error "
            f"for {ticker}: {exc}"
        )

        return []


# ==========================================
# STEP 6: GOOGLE NEWS
# ==========================================

def get_google_news_headlines(ticker, max_results=2):

    query = quote_plus(
        f"{ticker} stock performance"
    )

    rss_url = (
        "https://news.google.com/rss/search?"
        f"q={query}"
        "&hl=en-US"
        "&gl=US"
        "&ceid=US:en"
    )

    try:

        response = requests.get(
            rss_url,
            headers=HEADERS,
            timeout=10,
        )

        response.raise_for_status()

        root = ET.fromstring(
            response.content
        )

        items = root.findall(".//item")

        headlines = []

        for item in items[:max_results]:

            title_elem = item.find("title")
            link_elem = item.find("link")

            title = (
                title_elem.text
                if title_elem is not None
                else "No Title"
            )

            link = (
                link_elem.text
                if link_elem is not None
                else ""
            )

            if title and " - " in title:

                title = title.rsplit(
                    " - ",
                    1,
                )[0]

            headlines.append({
                "title": title,
                "link": link,
            })

        return headlines

    except Exception as exc:

        print(
            f"    [Diagnostic] Google News error "
            f"for {ticker}: {exc}"
        )

        return []


# ==========================================
# STEP 7: SCORE DISCOVERED NEWS
# ==========================================

def score_top_10_news(top_10_records):

    print("\n" + "=" * 60)
    print("SCORING DISCOVERED NEWS")
    print("=" * 60)

    scored_top_10 = []

    for item in top_10_records:

        ticker = item["Ticker"]

        yfinance_news = item.get(
            "yfinance_news",
            [],
        )

        google_news = item.get(
            "google_news",
            [],
        )

        articles = []

        for article in yfinance_news:

            article_copy = dict(article)
            article_copy["discovery_source"] = "yfinance"

            articles.append(article_copy)

        for article in google_news:

            article_copy = dict(article)
            article_copy["discovery_source"] = "google"

            articles.append(article_copy)

        print(
            f"\n{ticker}: "
            f"{len(yfinance_news)} yfinance + "
            f"{len(google_news)} Google = "
            f"{len(articles)} articles"
        )

        if not articles:

            updated = dict(item)

            updated["sentiment_summary"] = {
                "overall": "neutral",
                "score": 0.0,
                "positive": 0,
                "negative": 0,
                "neutral": 0,
                "total": 0,
            }

            scored_top_10.append(updated)

            print(
                "  No articles available for scoring."
            )

            continue

        scored_articles = score_articles(
            ticker,
            articles,
            model_name=SENTIMENT_MODEL,
        )

        summary = summarize_ticker_sentiment(
            scored_articles
        )

        save_scored_news(
            ticker,
            scored_articles,
        )

        scored_yfinance_news = []
        scored_google_news = []

        for article in scored_articles:

            source = article.get(
                "discovery_source"
            )

            if source == "yfinance":
                scored_yfinance_news.append(article)

            elif source == "google":
                scored_google_news.append(article)

        updated = dict(item)

        updated["yfinance_news"] = scored_yfinance_news
        updated["google_news"] = scored_google_news
        updated["sentiment_summary"] = summary

        scored_top_10.append(updated)

        print(
            f"  Sentiment: {summary['overall']}"
        )

        print(
            f"  Score: {summary['score']:+.4f}"
        )

        print(
            f"  Positive: {summary['positive']}"
        )

        print(
            f"  Negative: {summary['negative']}"
        )

        print(
            f"  Neutral: {summary['neutral']}"
        )

        for article in scored_articles:

            source = article.get(
                "discovery_source",
                "unknown",
            )

            sentiment = article.get(
                "sentiment",
                "neutral",
            )

            confidence = article.get(
                "confidence",
                0.0,
            )

            title = article.get(
                "title",
                "No Title",
            )

            print(
                f"    [{source}] {sentiment} "
                f"({confidence:.2f}) | {title}"
            )

    print("\nNews scoring completed.")

    return scored_top_10


# ==========================================
# STEP 8: FORMAT RETURN
# ==========================================

def format_return(value):

    if pd.isna(value):
        return "N/A"

    return f"{value:+.2f}%"


# ==========================================
# STEP 9: FETCH + SCORE TOP 10 NEWS
# ==========================================

def render_top_50_and_news(
    top_50_performing,
    top_10_to_fetch_articles,
    target_date,
):

    print(
        f"\n=== TOP 50 MARKET UNIVERSE FOR "
        f"PREVIOUS MARKET DAY "
        f"({target_date.upper()}) ==="
    )

    for rank, row in enumerate(
        top_50_performing.itertuples(index=False),
        start=1,
    ):

        print(
            f"#{rank} | {row.Ticker} | "
            f"{row.Asset_Type} | Return: "
            f"{format_return(row.Previous_Day_Return_Pct)}"
        )

    top_10_records = []

    print("\n=== TOP 10 NEWS FETCH TARGETS ===")

    for rank, row in enumerate(
        top_10_to_fetch_articles.itertuples(index=False),
        start=1,
    ):

        ticker = row.Ticker
        performance = row.Previous_Day_Return_Pct
        asset_type = row.Asset_Type

        print(
            f"\n#{rank} | {ticker} | "
            f"{asset_type} | Return: "
            f"{format_return(performance)}"
        )

        print("\n  [yfinance News Content]")

        yf_articles = get_yfinance_news(
            ticker,
            max_results=3,
        )

        if yf_articles:

            for article in yf_articles:

                print(
                    f"\n    - {article['title']}\n"
                    f"      URL: {article['link']}"
                )

        else:

            print(
                "    - No yfinance news coverage available."
            )

        print("\n  [Google News Feed]")

        google_articles = get_google_news_headlines(
            ticker,
            max_results=2,
        )

        if google_articles:

            for article in google_articles:

                print(
                    f"\n    - {article['title']}\n"
                    f"      URL: {article['link']}"
                )

        else:

            print(
                "    - No Google News coverage available."
            )

        top_10_records.append({
            "Ticker": ticker,
            "Asset_Type": asset_type,
            "Previous_Day_Return_Pct": float(performance),
            "yfinance_news": yf_articles,
            "google_news": google_articles,
            "mt5_symbol": getattr(row, "MT5_Symbol", None),
            "mt5_spread_pct": getattr(row, "MT5_Spread_Pct", None),
        })

    scored_top_10 = score_top_10_news(
        top_10_records
    )

    return scored_top_10


# ==========================================
# STEP 10: PRINT WAITING LIST
# ==========================================

def render_waiting_list(waiting_list):

    print(
        "\n\n=== WAITING LIST (POSITIONS 11-30) ==="
    )

    for rank, row in enumerate(
        waiting_list.itertuples(index=False),
        start=11,
    ):

        print(
            f"#{rank} | {row.Ticker} | "
            f"{row.Asset_Type} | Return: "
            f"{format_return(row.Previous_Day_Return_Pct)}"
        )


# ==========================================
# STEP 11: OPTIONAL MT5 FILTER
# ==========================================

def apply_mt5_filter(df_top_50):
    """
    Apply the broker catalog and MT5 tradability filter.

    This retains the existing behaviour:
      - broker catalog check first
      - MT5 enrichment second
      - no quote means the instrument may be rejected
      - failures fail open

    This function is separate from the progressive equity
    retrieval above.
    """

    try:

        from src.agents.trading_loop_dynamic import mt5_enabled

        wanted = mt5_enabled()

    except Exception:

        wanted = (
            os.environ.get(
                "RAATS_USE_MT5",
                "",
            ).strip().lower()
            in ("1", "true", "yes", "on")
        )

    if not wanted:
        return df_top_50

    print("\n=== MT5 BROKER FILTER ===")

    try:

        from src.data.broker_symbols import get_catalog

        catalog = get_catalog()

    except Exception:

        catalog = None

    if catalog is not None:

        offered = [
            ticker
            for ticker in df_top_50["Ticker"]
            if catalog.has(ticker)
        ]

        missing = [
            ticker
            for ticker in df_top_50["Ticker"]
            if ticker not in set(offered)
        ]

        if missing and offered:

            print(
                f"  Not in the broker's symbol list "
                f"({catalog.server}): {missing}"
            )

            df_top_50 = (
                df_top_50[
                    df_top_50["Ticker"].isin(offered)
                ]
                .reset_index(drop=True)
                .copy()
            )

        elif missing:

            print(
                "  WARNING: broker symbol list matches nothing; "
                "NO list filter applied."
            )

    try:

        from src.data.mt5_bridge import enrich_final_invest

        try:

            from src.data import mt5_orders

            lock = mt5_orders.session()

        except Exception:

            lock = None

        if lock is not None:

            with lock:

                info = enrich_final_invest(
                    df_top_50["Ticker"].tolist()
                )

        else:

            info = enrich_final_invest(
                df_top_50["Ticker"].tolist()
            )

    except Exception as exc:

        print(
            f"  WARNING: MT5 filter failed ({exc}). "
            "NO broker filter applied."
        )

        return df_top_50

    if not info:

        print(
            "  WARNING: MT5 unavailable. "
            "NO broker filter applied."
        )

        return df_top_50

    # "tradable" from enrich_final_invest also demands a live bid AND ask. Outside the exchange's
    # hours a stock CFD has no quote, so the whole universe was dropped (39 of 40 on one run) for
    # a reason that has nothing to do with the instrument. Discovery therefore asks only "does the
    # broker offer it with FULL trading"; the live quote is checked when the order is planned.
    # RAATS_DISCOVERY_REQUIRE_QUOTE=1 restores the old strict test.
    require_quote = os.environ.get(
        "RAATS_DISCOVERY_REQUIRE_QUOTE", ""
    ).strip().lower() in ("1", "true", "yes", "on")

    def _tradable(details):
        if require_quote:
            return bool(details.get("tradable"))
        return bool(details.get("mt5_symbol")) and details.get("trade_mode") == 4

    tradable = {
        ticker
        for ticker, details in info.items()
        if _tradable(details)
    }

    if not tradable:

        print(
            "  WARNING: MT5 reported ZERO tradable instruments. "
            "NO broker filter applied."
        )

        return df_top_50

    dropped = [
        ticker
        for ticker in df_top_50["Ticker"]
        if ticker not in tradable
    ]

    print(
        f"  Tradable on broker: "
        f"{len(tradable)} / {len(df_top_50)}"
    )

    if dropped:
        print(f"  Dropped (not tradable): {dropped}")

    kept = (
        df_top_50[
            df_top_50["Ticker"].isin(tradable)
        ]
        .reset_index(drop=True)
        .copy()
    )

    kept["MT5_Symbol"] = kept["Ticker"].map(
        lambda ticker: info[ticker].get("mt5_symbol")
    )

    kept["MT5_Spread_Pct"] = kept["Ticker"].map(
        lambda ticker: info[ticker].get("spread_pct")
    )

    return kept


# ==========================================
# MAIN
# ==========================================

def main():

    # ------------------------------------------
    # 1. Discover TOP 40 broker-supported equities
    # ------------------------------------------

    equity_tickers = get_tickers_from_gainers_feed()

    if not equity_tickers:

        raise ValueError(
            "No equity gainers discovered."
        )

    # ------------------------------------------
    # 2. Add 5 commodities + 5 currencies
    # ------------------------------------------

    market_universe = build_market_universe(
        equity_tickers
    )

    if len(market_universe) != TOP_50_COUNT:

        raise ValueError(
            f"Expected {TOP_50_COUNT} instruments, "
            f"but built {len(market_universe)}."
        )

    # ------------------------------------------
    # 3. Previous-session performance
    # ------------------------------------------

    df_top_50, target_date = get_previous_session_returns(
        market_universe
    )

    # ------------------------------------------
    # 3b. Optional MT5 broker filter
    # ------------------------------------------

    df_top_50 = apply_mt5_filter(
        df_top_50
    )

    # ------------------------------------------
    # 3c. Macro event check
    # ------------------------------------------

    if is_trade_blocked_by_macro(
        min_impact="MEDIUM"
    ):

        print(
            "MACRO EVENT WINDOW ACTIVE - Discovery blocked"
        )

        print(
            "Set RAATS_MACRO_API_KEY for live calendar "
            "or update macro_calendar.json"
        )

        return pd.DataFrame(), [], pd.DataFrame()

    # ------------------------------------------
    # 4. Build THREE arrays
    # ------------------------------------------

    (
        top_50_performing,
        top_10_to_fetch_articles,
        waiting_list,
    ) = build_ticker_arrays(
        df_top_50
    )

    # ------------------------------------------
    # 5. Array sizes
    # ------------------------------------------

    print(
        f"\nDiscovered performance universe: "
        f"{len(df_top_50)} instruments"
    )

    print(
        f"Top 50 array: "
        f"{len(top_50_performing)} instruments"
    )

    print(
        f"Top 10 article array: "
        f"{len(top_10_to_fetch_articles)} instruments"
    )

    print(
        f"Waiting list array: "
        f"{len(waiting_list)} instruments"
    )

    # ------------------------------------------
    # 6. Print Top 50 and score Top 10 news
    # ------------------------------------------

    scored_top_10 = render_top_50_and_news(
        top_50_performing,
        top_10_to_fetch_articles,
        target_date,
    )

    # ------------------------------------------
    # 7. Print waiting list
    # ------------------------------------------

    render_waiting_list(
        waiting_list
    )

    # ------------------------------------------
    # 8. Return THREE arrays
    # ------------------------------------------

    return (
        top_50_performing,
        scored_top_10,
        waiting_list,
    )


if __name__ == "__main__":
    main()