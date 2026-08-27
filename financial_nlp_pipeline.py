# File: financial_nlp_pipeline.py
#
# Goal: reusable function that extracts entities (including tickers),
# sentiment, and cleaned text from a financial headline.
#

import re
import spacy
from textblob import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
 
from test_ticker_matcher import extract_tickers
from company_ticker_resolver import resolve_company_tickers
 
# Initialize components
nlp = spacy.load("en_core_web_sm")
vader = SentimentIntensityAnalyzer()
 
 
def financial_nlp_pipeline(text):
    """
    Process financial text to extract entities (incl. tickers), sentiment,
    and clean text.
 
    Returns:
        dict: {
            'original': str,
            'cleaned': str,
            'entities': list of (text, label)   # spaCy NER, e.g. ORG/GPE
            'tickers': list of (text, confidence)  # 'high' or 'low'
            'vader': {'compound': float, 'label': str},
            'textblob': {'polarity': float, 'label': str}
        }
    """
    # Clean text: lowercase, remove extra whitespace/punctuation (keep letters/digits/spaces)
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower())
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
 
    # spaCy processing (use original, unlowercased text for NER + ticker matching -
    # both rely on capitalization)
    doc = nlp(text)
    entities = [(ent.text, ent.label_) for ent in doc.ents]
    tickers = extract_tickers(doc)
 
    # Merge in tickers resolved from company names (e.g. "Apple" -> AAPL)
    # for headlines that never spell out a ticker string at all. Dedupe
    # against anything extract_tickers() already found from the raw text.
    already_found = {t for t, _ in tickers}
    for ticker, confidence in resolve_company_tickers(entities):
        if ticker not in already_found:
            tickers.append((ticker, confidence))
            already_found.add(ticker)
 
    # VADER sentiment
    vader_scores = vader.polarity_scores(text)
    vader_label = "POSITIVE" if vader_scores['compound'] >= 0.05 else \
                  "NEGATIVE" if vader_scores['compound'] <= -0.05 else "NEUTRAL"
 
    # TextBlob sentiment
    blob = TextBlob(text)
    tb_polarity = blob.sentiment.polarity  # type: ignore[reportAttributeAccessIssue]
    tb_label = "POSITIVE" if tb_polarity > 0 else "NEGATIVE" if tb_polarity < 0 else "NEUTRAL"
 
    return {
        'original': text,
        'cleaned': cleaned,
        'entities': entities,
        'tickers': tickers,
        'vader': {'compound': vader_scores['compound'], 'label': vader_label},
        'textblob': {'polarity': tb_polarity, 'label': tb_label}
    }
 
 
# Example usage with sample headlines
if __name__ == "__main__":
    sample_headlines = [
        "Apple Inc. (AAPL) shares rise 5% after strong iPhone sales",
        "Oil prices drop 4% as OPEC increases production",
        "Federal Reserve signals potential rate cuts in 2024",
        "MSFT stock is up 2% after Azure growth acceleration",
    ]
 
    print("Financial NLP Pipeline Results:")
    print("=" * 50)
    for headline in sample_headlines:
        result = financial_nlp_pipeline(headline)
        print(f"\nOriginal: {result['original']}")
        print(f"Cleaned:  {result['cleaned']}")
        print(f"Entities: {result['entities']}")
        print(f"Tickers:  {result['tickers']}")
        print(f"VADER:    {result['vader']}")
        print(f"TextBlob: {result['textblob']}")