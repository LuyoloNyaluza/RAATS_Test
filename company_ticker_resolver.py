# File: company_ticker_resolver.py
#
# Solves a different problem than test_ticker_matcher.py:
#   test_ticker_matcher.py -> finds ticker STRINGS already written in text
#                              (AAPL, $AAPL, (AAPL), NASDAQ:AAPL...)
#   company_ticker_resolver.py -> maps COMPANY NAMES (already extracted by
#                              spaCy's NER as ORG entities) to their ticker,
#                              for headlines that never spell out the ticker
#                              at all (e.g. "Apple shares rise..." with no
#                              "AAPL" anywhere in the text).
#
# This is a lookup problem, not a pattern-matching problem - regex can't
# know that the word "Apple" refers to a company with ticker AAPL, so this
# intentionally does NOT extend test_ticker_matcher.py's patterns.
#
# NOTE: COMPANY_TICKER_MAP below is a small starter dict covering the
# companies that actually showed up in the Week 4 sample dataset - it is
# NOT a comprehensive company/ticker database. For real coverage at scale,
# replace this dict with a lookup against a real listings file (e.g. NASDAQ/
# NYSE symbol directory, or a yfinance/other API call) rather than hand-
# maintaining entries.

COMPANY_TICKER_MAP = {
    "apple": "AAPL",
    "apple inc": "AAPL",
    "apple inc.": "AAPL",
    "microsoft": "MSFT",
    "microsoft corporation": "MSFT",
    "tesla": "TSLA",
    "tesla inc": "TSLA",
    "tesla, inc.": "TSLA",
    "amazon": "AMZN",
    "amazon.com": "AMZN",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "alphabet inc": "GOOGL",
    "meta": "META",
    "meta platforms": "META",
    "nvidia": "NVDA",
    "nvidia corp": "NVDA",
    "netflix": "NFLX",
}

# Entities that will legitimately show up as ORG but are NOT publicly
# traded companies - no ticker exists, so we deliberately do not guess.
NOT_A_COMPANY = {
    "fed", "federal reserve", "opec", "eu", "european union",
    "imf", "world bank", "sec", "fda", "nato",
}


def resolve_company_tickers(entities):
    """
    Take a list of (text, label) tuples from spaCy NER (e.g. doc.ents) and
    return resolved tickers for any ORG entity found in COMPANY_TICKER_MAP.

    Returns: list of (ticker, confidence) tuples, e.g. [("AAPL", "name_match")]
    - confidence is always "name_match": this came from a company-name
      lookup, not from a ticker string actually present in the text, so
      treat it as a distinct provenance from test_ticker_matcher.py's
      "high"/"low" - it means "we're confident this IS the company,
      not necessarily that this headline is 'about' the stock in a
      trading sense."
    - ORG entities not found in the map (including known non-companies
      like "Fed" or "OPEC") are silently skipped, not guessed at.
    """
    results = []
    seen = set()

    for text, label in entities:
        if label != "ORG":
            continue

        key = text.lower().strip()
        if key in NOT_A_COMPANY:
            continue

        ticker = COMPANY_TICKER_MAP.get(key)
        if ticker and ticker not in seen:
            seen.add(ticker)
            results.append((ticker, "name_match"))

    return results


if __name__ == "__main__":
    # Quick check against the same shape of entities your pipeline produces
    test_cases = [
        [("Apple", "ORG"), ("iPhone", "ORG")],
        [("OPEC", "ORG")],
        [("Federal Reserve", "ORG")],
        [("Google", "ORG"), ("AI", "GPE")],
        [("Tesla, Inc.", "ORG")],
    ]

    print("Company -> Ticker Resolution Test:")
    print("=" * 40)
    for entities in test_cases:
        print(f"\nEntities: {entities}")
        print(f"Resolved: {resolve_company_tickers(entities)}")
