import os
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import pandas as pd
import requests
import yfinance as yf

from src.data.score_sentiment import (
    score_articles,
    summarize_ticker_sentiment,
    save_scored_news,
)


# ==========================================
# CONFIGURATION
# ==========================================

TOP_50_COUNT = 50
TOP_40_EQUITIES_COUNT = 40
COMMODITIES_COUNT = 5
CURRENCIES_COUNT = 5

TOP_10_COUNT = 10
WAITING_LIST_COUNT = 20

SENTIMENT_MODEL = os.environ.get(
    "RAATS_SENTIMENT_MODEL",
    "qwen2.5:3b",
)

# ------------------------------------------
# Yahoo Finance commodity instruments
# ------------------------------------------

COMMODITY_TICKERS = [
    "GC=F",   # Gold
    "SI=F",   # Silver
    "CL=F",   # Crude Oil
    "NG=F",   # Natural Gas
    "HG=F",   # Copper
]

# ------------------------------------------
# Yahoo Finance currency instruments
# ------------------------------------------

CURRENCY_TICKERS = [
    "EURUSD=X",  # Euro / US Dollar
    "GBPUSD=X",  # British Pound / US Dollar
    "USDJPY=X",  # US Dollar / Japanese Yen
    "AUDUSD=X",  # Australian Dollar / US Dollar
    "USDCAD=X",  # US Dollar / Canadian Dollar
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

def get_tickers_from_gainers_feed():
    """
    Get the top 40 equity gainers from Yahoo Finance.

    Only normal US equity symbols are retained here.

    Commodities and currencies are added separately so that
    the final universe always contains:

        40 equities
        5 commodities
        5 currencies
    """

    print(
        "Extracting top 40 equity gainers "
        "from Yahoo Finance..."
    )

    try:

        result = yf.screen(
            "day_gainers",
            count=40,
        )

        quotes = result.get("quotes", [])

        if not quotes:
            raise ValueError(
                "Yahoo day_gainers returned no quotes."
            )

        tickers = []

        for item in quotes:

            symbol = item.get("symbol")

            if not symbol:
                continue

            symbol = str(symbol).upper().strip()

            # Normal US equity symbols only
            if not symbol.isalpha():
                continue

            if len(symbol) > 5:
                continue

            if symbol not in tickers:
                tickers.append(symbol)

            if len(tickers) >= TOP_40_EQUITIES_COUNT:
                break

        if len(tickers) < TOP_40_EQUITIES_COUNT:
            print(
                f"Yahoo returned only {len(tickers)} "
                f"usable equity gainers."
            )

        print(
            f"Discovered {len(tickers)} "
            f"Yahoo equity gainers."
        )

        return tickers

    except Exception as e:

        print(
            f"Yahoo gainers screener failed: {e}"
        )

        # Emergency equity fallback only
        fallback = [
            "AAPL",
            "NVDA",
            "MSFT",
            "AMZN",
            "META",
            "GOOGL",
            "TSLA",
            "NFLX",
            "AMD",
            "INTC",
            "AVGO",
            "MU",
            "QCOM",
            "AMAT",
            "MRVL",
            "ORCL",
            "CRM",
            "ADBE",
            "PLTR",
            "CRWD",
            "JPM",
            "BAC",
            "WMT",
            "COST",
            "HD",
            "LOW",
            "DIS",
            "V",
            "MA",
            "PYPL",
            "UBER",
            "ABNB",
            "SHOP",
            "SNOW",
            "PANW",
            "NET",
            "DDOG",
            "MDB",
            "COIN",
            "SOFI",
        ]

        fallback = fallback[:TOP_40_EQUITIES_COUNT]

        print(
            f"Using emergency equity fallback: "
            f"{len(fallback)} tickers."
        )

        return fallback


# ==========================================
# STEP 2: BUILD 40 + 5 + 5 UNIVERSE
# ==========================================

def build_market_universe(equity_tickers):
    """
    Build the complete 50-instrument discovery universe.

    Structure:

        40 equities
        5 commodities
        5 currencies
    """

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

    print(
        "\n=== MARKET UNIVERSE ==="
    )

    print(
        f"Equities:    {len(equities)}"
    )

    print(
        f"Commodities: {len(commodities)}"
    )

    print(
        f"Currencies:  {len(currencies)}"
    )

    print(
        f"Total:       {len(universe)}"
    )

    return universe


# ==========================================
# STEP 3: PREVIOUS SESSION PERFORMANCE
# ==========================================

def get_previous_session_returns(
    market_universe
):
    """
    Calculate previous fully completed market-session
    returns for the complete 40 + 5 + 5 universe.

    The final structure remains:

        40 equities
        5 commodities
        5 currencies

    Equities are sorted by previous-session return.

    Commodities are sorted within the commodity group.

    Currencies are sorted within the currency group.
    """

    tickers = [
        item["Ticker"]
        for item in market_universe
    ]

    print(
        f"\nVerifying previous-session performance "
        f"for {len(tickers)} instruments..."
    )

    data = yf.download(
        tickers=tickers,
        period="7d",
        interval="1d",
        progress=False,
        auto_adjust=False,
        group_by="column",
        threads=True,
    )

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
            "No valid previous-session performance "
            "was available."
        )

    performance = pd.DataFrame(
        performance_records
    )

    # ------------------------------------------
    # Keep the 40 + 5 + 5 structure
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

    # ------------------------------------------
    # ARRAY 1:
    # Overall top 50
    # ------------------------------------------

    top_50_performing = (
        df_top_50
        .head(TOP_50_COUNT)
        .copy()
    )

    # ------------------------------------------
    # ARRAY 2:
    # Top 10 receive news
    # ------------------------------------------

    top_10_to_fetch_articles = (
        top_50_performing
        .head(TOP_10_COUNT)
        .copy()
    )

    # ------------------------------------------
    # ARRAY 3:
    # Waiting list
    #
    # Positions 11 -> 30
    # ------------------------------------------

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
# STEP 5: yfinance NEWS
# ==========================================

def get_yfinance_news(
    ticker,
    max_results=3
):
    try:

        search = yf.Search(
            ticker,
            max_results=max_results
        )

        raw_news = search.news

        if not raw_news:
            return []

        articles = []

        for item in raw_news[:max_results]:

            title = item.get(
                "title",
                "No Title"
            )

            link = item.get(
                "link",
                ""
            )

            if not title:
                continue

            articles.append({
                "title": title,
                "link": link,
            })

        return articles

    except Exception as e:

        print(
            f"    [Diagnostic] "
            f"yfinance news error for "
            f"{ticker}: {e}"
        )

        return []


# ==========================================
# STEP 6: GOOGLE NEWS
# ==========================================

def get_google_news_headlines(
    ticker,
    max_results=2
):

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
            timeout=10
        )

        response.raise_for_status()

        root = ET.fromstring(
            response.content
        )

        items = root.findall(
            ".//item"
        )

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
                    1
                )[0]

            headlines.append({
                "title": title,
                "link": link,
            })

        return headlines

    except Exception as e:

        print(
            f"    [Diagnostic] "
            f"Google News error for "
            f"{ticker}: {e}"
        )

        return []


# ==========================================
# STEP 7: SCORE DISCOVERED NEWS
# ==========================================

def score_top_10_news(top_10_records):
    """
    Score ONLY the articles that were already
    fetched during discovery.

    No additional news is fetched here.
    """

    print("\n" + "=" * 60)
    print("SCORING DISCOVERED NEWS")
    print("=" * 60)

    scored_top_10 = []

    for item in top_10_records:

        ticker = item["Ticker"]

        yfinance_news = item.get(
            "yfinance_news",
            []
        )

        google_news = item.get(
            "google_news",
            []
        )

        articles = []

        # --------------------------------------
        # Add yfinance articles
        # --------------------------------------

        for article in yfinance_news:

            article_copy = dict(article)

            article_copy["discovery_source"] = (
                "yfinance"
            )

            articles.append(
                article_copy
            )

        # --------------------------------------
        # Add Google articles
        # --------------------------------------

        for article in google_news:

            article_copy = dict(article)

            article_copy["discovery_source"] = (
                "google"
            )

            articles.append(
                article_copy
            )

        print(
            f"\n{ticker}: "
            f"{len(yfinance_news)} yfinance + "
            f"{len(google_news)} Google = "
            f"{len(articles)} articles"
        )

        # --------------------------------------
        # No articles
        # --------------------------------------

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

            scored_top_10.append(
                updated
            )

            print(
                "  No articles available for scoring."
            )

            continue

        # --------------------------------------
        # Score exact discovered articles
        # --------------------------------------

        scored_articles = score_articles(
            ticker,
            articles,
            model_name=SENTIMENT_MODEL,
        )

        # --------------------------------------
        # Calculate ticker sentiment
        # --------------------------------------

        summary = summarize_ticker_sentiment(
            scored_articles
        )

        # --------------------------------------
        # Save scored news
        # --------------------------------------

        save_scored_news(
            ticker,
            scored_articles
        )

        # --------------------------------------
        # Separate sources again
        # --------------------------------------

        scored_yfinance_news = []
        scored_google_news = []

        for article in scored_articles:

            source = article.get(
                "discovery_source"
            )

            if source == "yfinance":

                scored_yfinance_news.append(
                    article
                )

            if source == "google":

                scored_google_news.append(
                    article
                )

        # --------------------------------------
        # Create final Top 10 record
        # --------------------------------------

        updated = dict(item)

        updated["yfinance_news"] = (
            scored_yfinance_news
        )

        updated["google_news"] = (
            scored_google_news
        )

        updated["sentiment_summary"] = summary

        scored_top_10.append(
            updated
        )

        # --------------------------------------
        # Print scoring result
        # --------------------------------------

        print(
            f"  Sentiment: "
            f"{summary['overall']}"
        )

        print(
            f"  Score: "
            f"{summary['score']:+.4f}"
        )

        print(
            f"  Positive: "
            f"{summary['positive']}"
        )

        print(
            f"  Negative: "
            f"{summary['negative']}"
        )

        print(
            f"  Neutral: "
            f"{summary['neutral']}"
        )

        # --------------------------------------
        # Print individual scores
        # --------------------------------------

        for article in scored_articles:

            source = article.get(
                "discovery_source",
                "unknown"
            )

            sentiment = article.get(
                "sentiment",
                "neutral"
            )

            confidence = article.get(
                "confidence",
                0.0
            )

            title = article.get(
                "title",
                "No Title"
            )

            print(
                f"    [{source}] "
                f"{sentiment} "
                f"({confidence:.2f}) | "
                f"{title}"
            )

    print(
        "\nNews scoring completed."
    )

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
    target_date
):
    """
    Print Top 50 and fetch news for Top 10.

    The returned Top 10 contains the exact
    discovered articles and their sentiment scores.
    """

    print(
        f"\n=== TOP 50 MARKET UNIVERSE FOR "
        f"PREVIOUS MARKET DAY "
        f"({target_date.upper()}) ==="
    )

    # ------------------------------------------
    # Print ALL 50
    # ------------------------------------------

    for rank, row in enumerate(
        top_50_performing.itertuples(
            index=False
        ),
        start=1
    ):

        ticker = row.Ticker

        performance = (
            row.Previous_Day_Return_Pct
        )

        asset_type = (
            row.Asset_Type
        )

        print(
            f"#{rank} | "
            f"{ticker} | "
            f"{asset_type} | "
            f"Return: "
            f"{format_return(performance)}"
        )

    # ------------------------------------------
    # Build Top 10 records
    # ------------------------------------------

    top_10_records = []

    print(
        "\n=== TOP 10 NEWS FETCH TARGETS ==="
    )

    for rank, row in enumerate(
        top_10_to_fetch_articles.itertuples(
            index=False
        ),
        start=1
    ):

        ticker = row.Ticker

        performance = (
            row.Previous_Day_Return_Pct
        )

        asset_type = (
            row.Asset_Type
        )

        print(
            f"\n#{rank} | "
            f"{ticker} | "
            f"{asset_type} | "
            f"Return: "
            f"{format_return(performance)}"
        )

        # --------------------------------------
        # yfinance
        # --------------------------------------

        print(
            "\n  [yfinance News Content]"
        )

        yf_articles = get_yfinance_news(
            ticker,
            max_results=3
        )

        if yf_articles:

            for article in yf_articles:

                print(
                    f"\n    - "
                    f"{article['title']}\n"
                    f"      URL: "
                    f"{article['link']}"
                )

        else:

            print(
                "    - No yfinance news "
                "coverage available."
            )

        # --------------------------------------
        # Google News
        # --------------------------------------

        print(
            "\n  [Google News Feed]"
        )

        google_articles = (
            get_google_news_headlines(
                ticker,
                max_results=2
            )
        )

        if google_articles:

            for article in google_articles:

                print(
                    f"\n    - "
                    f"{article['title']}\n"
                    f"      URL: "
                    f"{article['link']}"
                )

        else:

            print(
                "    - No Google News "
                "coverage available."
            )

        # --------------------------------------
        # Store EXACT discovered articles
        # --------------------------------------

        top_10_records.append({
            "Ticker": ticker,
            "Asset_Type": asset_type,
            "Previous_Day_Return_Pct": (
                float(performance)
            ),
            "yfinance_news": yf_articles,
            "google_news": google_articles,
        })

    # ------------------------------------------
    # SCORE BEFORE TRADING
    # ------------------------------------------

    scored_top_10 = score_top_10_news(
        top_10_records
    )

    return scored_top_10


# ==========================================
# STEP 10: PRINT WAITING LIST
# ==========================================

def render_waiting_list(
    waiting_list
):

    print(
        "\n\n=== WAITING LIST "
        "(POSITIONS 11-30) ==="
    )

    for rank, row in enumerate(
        waiting_list.itertuples(
            index=False
        ),
        start=11
    ):

        ticker = row.Ticker

        performance = (
            row.Previous_Day_Return_Pct
        )

        asset_type = (
            row.Asset_Type
        )

        print(
            f"#{rank} | "
            f"{ticker} | "
            f"{asset_type} | "
            f"Return: "
            f"{format_return(performance)}"
        )


# ==========================================
# MAIN
# ==========================================

def main():

    # ------------------------------------------
    # 1. Discover TOP 40 equity gainers
    # ------------------------------------------

    equity_tickers = (
        get_tickers_from_gainers_feed()
    )

    if not equity_tickers:

        raise ValueError(
            "No equity gainers discovered."
        )

    # ------------------------------------------
    # 2. Add 5 commodities + 5 currencies
    # ------------------------------------------

    market_universe = (
        build_market_universe(
            equity_tickers
        )
    )

    if len(market_universe) != TOP_50_COUNT:

        raise ValueError(
            f"Expected {TOP_50_COUNT} instruments, "
            f"but built {len(market_universe)}."
        )

    # ------------------------------------------
    # 3. Previous-session performance
    # ------------------------------------------

    df_top_50, target_date = (
        get_previous_session_returns(
            market_universe
        )
    )

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
    # 6. Print Top 50
    #    Fetch Top 10 news
    #    SCORE Top 10 news
    # ------------------------------------------

    scored_top_10 = (
        render_top_50_and_news(
            top_50_performing,
            top_10_to_fetch_articles,
            target_date
        )
    )

    # ------------------------------------------
    # 7. Print waiting list
    # ------------------------------------------

    render_waiting_list(
        waiting_list
    )

    # ------------------------------------------
    # 8. Return THREE arrays
    #
    # top_50_performing:
    #     DataFrame with:
    #       40 equities
    #       5 commodities
    #       5 currencies
    #
    # scored_top_10:
    #     List containing exact discovered
    #     yfinance + Google articles,
    #     already sentiment scored
    #
    # waiting_list:
    #     DataFrame containing positions 11-30
    # ------------------------------------------

    return (
        top_50_performing,
        scored_top_10,
        waiting_list,
    )


if __name__ == "__main__":
    main()