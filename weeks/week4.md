# Week 4: Natural Language Processing for Financial Text
**Goal:** Apply spaCy and rule-based techniques to extract financial entities (tickers, company names, monetary values) and perform sentiment analysis on news headlines.

## Monday 24 Aug – spaCy fundamentals
- Review spaCy 101: https://spacy.io/usage/spacy-101
- Load the English model: `python -m spacy download en_core_web_sm` (already done in week1)
- Write a script to test basic tokenization, POS tagging, and named entity recognition on a few sample headlines.
- Output: Notebook 05_spacy_intro.ipynb demonstrating spaCy pipeline.

## Tuesday 25 Aug – Financial NLP resources
- Skim the survey paper: arXiv:2006.05523 (Financial NLP) – focus on entity recognition and sentiment techniques.
- Identify common entity types: TICKER, COMPANY, MONEY, PERCENT, DATE.
- Experiment with spaCy's matcher or rule-based matcher to catch ticker patterns (e.g., $AAPL, AAPL, NASDAQ:AAPL).
- Output: Notebook 06_financial_entities.ipynb showing custom entity extraction.

## Wednesday 26 Aug – Sentiment analysis with VADER and TextBlob
- Compare VADER and TextBlob on a small labeled set (you can create a few manual labels).
- Write a function that returns sentiment score and label (positive/negative/neutral) using both libraries.
- Output: Notebook 07_sentiment_comparison.ipynb.

## Thursday 27 Aug – Building a financial text preprocessing pipeline
- Combine the steps: load raw news, clean HTML/tags, extract entities, compute sentiment.
- Store the enriched data in a structured format (e.g., CSV with columns: date, headline, source, tickers, companies, sentiment_vader, sentiment_textblob).
- Output: Script `src/data/enrich_news.py` that processes all raw news files and writes to `data/processed/enriched_news.csv`.

## Friday 28 Aug – Morning: Apply pipeline to week's news
- Run the enrichment script on the news collected during week 1 (or newly fetched).
- Examine the output: check which entities were extracted, sentiment distribution.
- Afternoon: Rest (no work).

## Saturday 29 Aug – Rest day
- No planned work.

## Sunday 30 Aug – Preparation for Week 5
- Review yfinance and pandas-ta documentation for technical indicators.
- Think about how to merge enriched news with price data for feature creation.
- Write a brief note in `journal/week4_prep_week5.md` about ideas for week 5.
- Commit any notes or scripts.

---
**End of Week 4 Deliverables:**
- Notebooks: 05_spacy_intro.ipynb, 06_financial_entities.ipynb, 07_sentiment_comparison.ipynb
- Script: src/data/enrich_news.py
- Data: data/processed/enriched_news.csv
- Logs: journal/week4_log.md, journal/week4_prep_week5.md