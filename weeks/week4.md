# Week 4: Natural Language Processing for Financial Text
**Goal:** Apply spaCy and rule-based techniques to extract financial entities (tickers, company names, monetary values) and perform sentiment analysis on news headlines.

## Monday 24 Aug – spaCy fundamentals
- Review spaCy 101: https://spacy.io/usage/spacy-101
- Load the English model (should already be installed from week1): `python -m spacy download en_core_web_sm`
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

## Thursday 27 Aug – Building a financial NLP pipeline
- Combine the previous steps into a reusable function that takes a headline and returns:
  - List of entities (with types)
  - Sentiment scores from VADER and TextBlob
  - Cleaned text (lowercased, no punctuation)
- Apply this pipeline to the news data collected in week1 (data/raw/news/).
- Store the enriched data as CSV: data/processed/news_enriched_week4.csv.
- Output: Notebook 08_nlp_pipeline.ipynb.

## Friday 28 Aug – Morning: Visualization and insights
- Generate some simple visualizations: distribution of sentiment, top entities mentioned, etc.
- Use matplotlib or seaborn (install if needed: `pip install matplotlib seaborn`).
- Afternoon: Rest (no work) – enjoy the break.

## Saturday 29 Aug – Rest day
- No planned work.

## Sunday 30 Aug – Preparation for Week 5
- Review the plan for week5: technical indicators and market data collection.
- Check that yfinance and pandas-ta are installed (they are in requirements).
- Optionally, run a quick test to download one month of data for AAPL and compute a few indicators.
- Write a quick note in journal/week4_prep_week5.md about what you'll do Monday.
- Commit any notes or small scripts.

---
**End of Week 4 Deliverables:**
- Notebooks: 05_spacy_intro.ipynb, 06_financial_entities.ipynb, 07_sentiment_comparison.ipynb, 08_nlp_pipeline.ipynb
- Data: data/processed/news_enriched_week4.csv
- Visualizations: optional plots in notebooks or a separate folder.
- Logs: journal/week4_log.md, journal/week4_prep_week5.md