# File: test_ticker_matcher.py

import spacy
from spacy.matcher import Matcher

nlp = spacy.load("en_core_web_sm")
matcher = Matcher(nlp.vocab)

# Common all-caps acronyms that are NOT tickers - used to suppress obvious
# false positives on the low-confidence "bare ticker" pattern only.
NON_TICKER_ACRONYMS = {
    "EU", "US", "USA", "UK", "CEO", "CFO", "CTO", "IPO", "GDP", "SEC",
    "FDA", "FED", "NYSE", "OPEC", "ETF", "AI", "IT", "PR", "HR",
}

# --- High-confidence patterns: ticker is unambiguous given the delimiter ---
ticker_patterns_high_conf = [
    [{"TEXT": "$"}, {"TEXT": {"REGEX": r"^[A-Z]{1,5}$"}}],                     # $AAPL
    [{"TEXT": "("}, {"TEXT": {"REGEX": r"^[A-Z]{1,5}$"}}, {"TEXT": ")"}],      # (AAPL)
    [{"IS_UPPER": True}, {"TEXT": ":"}, {"TEXT": {"REGEX": r"^[A-Z]{1,5}$"}}], # NASDAQ:AAPL
    [{"TEXT": {"REGEX": r"^[A-Z]{1,5}$"}}, {"LOWER": "inc"}],                 # AAPL Inc
    [{"TEXT": {"REGEX": r"^[A-Z]{1,5}$"}}, {"LOWER": "corp"}],                # AAPL Corp
]

# --- Low-confidence pattern: bare all-caps token, no delimiter/context ---
ticker_pattern_bare = [{"TEXT": {"REGEX": r"^[A-Z]{2,5}$"}}]

matcher.add("TICKER_HIGH_CONF", ticker_patterns_high_conf)
matcher.add("TICKER_BARE", [ticker_pattern_bare])


def extract_tickers(doc):
    """
    Run the ticker Matcher over a spaCy Doc and return clean results as
    (ticker_text, confidence) tuples, e.g. [("AAPL", "high"), ...].

    - High-confidence matches (delimiter-based) are returned with the
      surrounding punctuation/context stripped, e.g. "(AAPL)" -> "AAPL".
    - Bare matches are filtered against NON_TICKER_ACRONYMS and against
      any token already covered by a high-confidence match (so "(AAPL)"
      doesn't also get reported separately as a bare "AAPL"), then
      labeled "low" confidence - use with judgment, not as ground truth.
    """
    matches = matcher(doc)

    high_conf_results = []
    high_conf_token_idxs = set()
    bare_matches = []

    for match_id, start, end in matches:
        label = nlp.vocab.strings[match_id]
        span = doc[start:end]

        if label == "TICKER_HIGH_CONF":
            ticker_tok_idx = next(
                (t.i for t in span if t.text.isupper() and 1 <= len(t.text) <= 5 and t.text.isalpha()),
                None,
            )
            if ticker_tok_idx is None:
                continue
            high_conf_token_idxs.add(ticker_tok_idx)
            high_conf_results.append((doc[ticker_tok_idx].text, "high"))
        else:  # TICKER_BARE
            bare_matches.append((start, span.text))

    # Dedupe high-confidence results (multiple patterns can match the same token).
    seen = set()
    deduped_high = []
    for text, conf in high_conf_results:
        if text not in seen:
            seen.add(text)
            deduped_high.append((text, conf))

    low_conf_results = []
    seen_low = set()
    for start, text in bare_matches:
        if start in high_conf_token_idxs:
            continue  # already covered by a high-confidence match
        if text in NON_TICKER_ACRONYMS:
            continue
        if text in seen or text in seen_low:
            continue
        seen_low.add(text)
        low_conf_results.append((text, "low"))

    return deduped_high + low_conf_results


if __name__ == "__main__":
    test_texts = [
        "Apple Inc. (AAPL) shares rose today",
        "Investors bought NASDAQ:AAPL after earnings",
        "MSFT stock is up 2%",
        "The Fed meeting affected GOOGL and AMZN",
        "Investors bought $AAPL after strong earnings",
        "Tesla, Inc. (TSLA) delivers record vehicles in Q3",
        "Amazon.com, Inc. (AMZN) faces antitrust investigation in EU",
    ]

    print("Ticker Matcher Test:")
    print("=" * 40)
    for text in test_texts:
        doc = nlp(text)
        results = extract_tickers(doc)
        print(f"\nText: {text}")
        if results:
            for ticker, confidence in results:
                print(f"  Found ticker: '{ticker}' (confidence={confidence})")
        else:
            print("  No ticker patterns found")
