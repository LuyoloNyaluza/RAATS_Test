# Week 4 Setup - Natural Language Processing for Financial Text

## Overview
This week focuses on applying spaCy and rule-based techniques to extract financial entities and perform sentiment analysis on news headlines.

## Prerequisites
- Completed Week 3 setup (vector stores, RAG basics)
- Python virtual environment activated
- Required packages installed (spaCy, VADER, TextBlob, matplotlib, seaborn)
- Ollama with llama3 model running (for any LLM components)

## Daily Activities with Runnable Code Snippets

### Monday 24 Aug – spaCy Fundamentals

**Goal:** Test basic spaCy pipeline (tokenization, POS tagging, NER) on sample headlines.

```python
# File: test_spacy_basics.py
import spacy

# Load English model
nlp = spacy.load("en_core_web_sm")

# Sample financial headlines
headlines = [
    "Apple Inc. (AAPL) shares rise after strong iPhone sales",
    "Federal Reserve hints at possible interest rate cuts",
    "Crude oil prices drop 3% on oversupply concerns",
    "Tesla delivers record vehicles in Q3, stock up 5%"
]

print("spaCy Basic Pipeline Test:")
print("=" * 50)
for i, headline in enumerate(headlines, 1):
    doc = nlp(headline)
    
    print(f"\n{i}. Headline: {headline}")
    print("   Tokens:", [token.text for token in doc[:5]], "..." if len(doc) > 5 else "")
    print("   POS Tags:", [(token.text, token.pos_) for token in doc[:5]])
    print("   Entities:", [(ent.text, ent.label_) for ent in doc.ents])
```

**To run:**
```bash
python test_spacy_basics.py
```

**Expected Output:** You'll see tokenization, POS tags, and named entities for each headline.

---

### Tuesday 25 Aug – Financial NLP Resources & Ticker Patterns

**Goal:** Experiment with spaCy's Matcher to catch ticker patterns ($AAPL, AAPL, NASDAQ:AAPL).

```python
# File: test_ticker_matcher.py
import spacy
from spacy.matcher import Matcher

nlp = spacy.load("en_core_web_sm")
matcher = Matcher(nlp.vocab)

# Define ticker patterns
ticker_patterns = [
    [{"TEXT": {"REGEX": r"\$[A-Z]{1,5}"}}],           # $AAPL
    [{"TEXT": {"REGEX": r"[A-Z]{1,5}"}}, {"IS_PUNCT": True}, {"TEXT": {"REGEX": r"[A-Z]{1,5}"}}],  # NASDAQ:AAPL
    [{"TEXT": {"REGEX": r"[A-Z]{1,5}"}}, {"LOWER": "inc"}],  # AAPL Inc
    [{"TEXT": {"REGEX": r"[A-Z]{1,5}"}}, {"LOWER": "corp"}], # AAPL Corp
]

matcher.add("TICKER", ticker_patterns)

# Test sentences
test_texts = [
    "Apple Inc. (AAPL) shares rose today",
    "Investors bought NASDAQ:AAPL after earnings",
    "MSFT stock is up 2%",
    "The Fed meeting affected GOOGL and AMZN"
]

print("Ticker Matcher Test:")
print("=" * 40)
for text in test_texts:
    doc = nlp(text)
    matches = matcher(doc)
    print(f"\nText: {text}")
    if matches:
        for match_id, start, end in matches:
            span = doc[start:end]
            print(f"  Found ticker: '{span.text}' (start={start}, end={end})")
    else:
        print("  No ticker patterns found")
```

**To run:**
```bash
python test_ticker_matcher.py
```

**Note:** Install regex support if needed: `pip install regex` (spacy uses it internally).

---

### Wednesday 26 Aug – Sentiment Analysis with VADER and TextBlob

**Goal:** Compare VADER and TextBlob on sample headlines.

```python
# File: test_sentiment_comparison.py
from textblob import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Initialize analyzers
vader = SentimentIntensityAnalyzer()

# Sample financial headlines
headlines = [
    "Apple shares surge after record iPhone sales",
    "Stock market crashes amid recession fears",
    "Tesla reports quarterly loss, stock down 8%",
    "Federal Reserve keeps interest rates unchanged",
    "Amazon beats earnings expectations"
]

print("Sentiment Analysis Comparison (VADER vs TextBlob):")
print("=" * 60)
for headline in headlines:
    # VADER
    vader_scores = vader.polarity_scores(headline)
    vader_compound = vader_scores['compound']
    vader_label = "POSITIVE" if vader_compound >= 0.05 else "NEGATIVE" if vader_compound <= -0.05 else "NEUTRAL"
    
    # TextBlob
    blob = TextBlob(headline)
    tb_polarity = blob.sentiment.polarity
    tb_label = "POSITIVE" if tb_polarity > 0 else "NEGATIVE" if tb_polarity < 0 else "NEUTRAL"
    
    print(f"\nHeadline: {headline}")
    print(f"  VADER:   compound={vader_compound:+.3f} ({vader_label})")
    print(f"  TextBlob: polarity={tb_polarity:+.3f} ({tb_label})")
```

**To run:**
```bash
pip install textblob vaderSentiment
python test_sentiment_comparison.py
```

**First-time setup for TextBlob:** You may need to run `python -m textblob.download_corpora` after installing.

---

### Thursday 27 Aug – Building a Financial NLP Pipeline

**Goal:** Create a reusable function that extracts entities, sentiment, and cleans text.

```python
# File: financial_nlp_pipeline.py
import spacy
from textblob import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import re

# Initialize components
nlp = spacy.load("en_core_web_sm")
vader = SentimentIntensityAnalyzer()

def financial_nlp_pipeline(text):
    """
    Process financial text to extract entities, sentiment, and clean text.
    
    Returns:
        dict: {
            'original': str,
            'cleaned': str,
            'entities': list of (text, label),
            'vader': {'compound': float, 'label': str},
            'textblob': {'polarity': float, 'label': str}
        }
    """
    # Clean text: lowercase, remove extra whitespace/punctuation (keep letters/digits/spaces)
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower())
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # spaCy processing
    doc = nlp(text)  # Use original for entity recognition
    entities = [(ent.text, ent.label_) for ent in doc.ents]
    
    # VADER sentiment
    vader_scores = vader.polarity_scores(text)
    vader_label = "POSITIVE" if vader_scores['compound'] >= 0.05 else \
                  "NEGATIVE" if vader_scores['compound'] <= -0.05 else "NEUTRAL"
    
    # TextBlob sentiment
    blob = TextBlob(text)
    tb_polarity = blob.sentiment.polarity
    tb_label = "POSITIVE" if tb_polarity > 0 else "NEGATIVE" if tb_polarity < 0 else "NEUTRAL"
    
    return {
        'original': text,
        'cleaned': cleaned,
        'entities': entities,
        'vader': {'compound': vader_scores['compound'], 'label': vader_label},
        'textblob': {'polarity': tb_polarity, 'label': tb_label}
    }

# Example usage with sample headlines
if __name__ == "__main__":
    sample_headlines = [
        "Apple Inc. (AAPL) shares rise 5% after strong iPhone sales",
        "Oil prices drop 4% as OPEC increases production",
        "Federal Reserve signals potential rate cuts in 2024"
    ]
    
    print("Financial NLP Pipeline Results:")
    print("=" * 50)
    for headline in sample_headlines:
        result = financial_nlp_pipeline(headline)
        print(f"\nOriginal: {result['original']}")
        print(f"Cleaned:  {result['cleaned']}")
        print(f"Entities: {result['entities']}")
        print(f"VADER:    {result['vader']}")
        print(f"TextBlob: {result['textblob']}")
```

**To run:**
```bash
python financial_nlp_pipeline.py
```

**To apply to Week 1 news data:**
```python
# After verifying the function works above, process your news data:
import pandas as pd
import os
from financial_nlp_pipeline import financial_nlp_pipeline

# Load your Week 1 news data (adjust path as needed)
news_df = pd.read_csv("data/raw/news/combined_headlines.csv")  # Example path
# Or if you have the processed news from Week 3:
news_df = pd.read_csv("data/processed/combined_news.csv")

# Apply pipeline
results = []
for _, row in news_df.iterrows():
    # Assuming column 'text' contains the headline/summary
    result = financial_nlp_pipeline(row['text'])
    result['original_index'] = row.name
    results.append(result)

# Convert to DataFrame and save
results_df = pd.DataFrame(results)
results_df.to_csv("data/processed/news_enriched_week4.csv", index=False)
print(f"Enriched data saved with {len(results_df)} records")
```

---

### Friday 28 Aug – Morning: Visualization and Insights

**Goal:** Generate simple visualizations of sentiment and entity distributions.

```python
# File: visualize_nlp_results.py
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter

# Load enriched data from Thursday's pipeline
df = pd.read_csv("data/processed/news_enriched_week4.csv")

# Set style
plt.style.use('seaborn-v0_8')
sns.set_palette("husl")

# 1. Sentiment distribution (VADER)
plt.figure(figsize=(10, 5))
plt.subplot(1, 2, 1)
vader_counts = df['vader.label'].value_counts()
sns.barplot(x=vader_counts.index, y=vader_counts.values)
plt.title('VADER Sentiment Distribution')
plt.ylabel('Count')

plt.subplot(1, 2, 2)
tb_counts = df['textblob.label'].value_counts()
sns.barplot(x=tb_counts.index, y=tb_counts.values)
plt.title('TextBlob Sentiment Distribution')
plt.ylabel('Count')
plt.tight_layout()
plt.savefig('sentiment_distribution.png')
plt.show()

# 2. Top entities mentioned
all_entities = []
for entities_str in df['entities']:
    # Assuming entities are stored as string representation of list of tuples
    # You may need to adjust parsing based on how you saved it
    try:
        entities_list = eval(entities_str) if isinstance(entities_str, str) else entities_str
        all_entities.extend([ent[0] for ent in entities_list])  # Extract entity text
    except:
        pass  # Skip if parsing fails

entity_counts = Counter(all_entities)
top_10 = entity_counts.most_common(10)

plt.figure(figsize=(10, 6))
entities, counts = zip(*top_10) if top_10 else ([], [])
sns.barplot(x=list(counts), y=list(entities))
plt.title('Top 10 Financial Entities Mentioned')
plt.xlabel('Frequency')
plt.tight_layout()
plt.savefig('top_entities.png')
plt.show()

print("Visualizations saved as sentiment_distribution.png and top_entities.png")
```

**To run:**
```bash
pip install matplotlib seaborn
python visualize_nlp_results.py
```

**Note:** Adjust the data loading and entity parsing based on how you saved your enriched data from Thursday's activity.

---

### Sunday 30 Aug – Preparation for Week 5

**Goal:** Review Week 5 plan and test yfinance/pandas-ta setup.

```python
# File: test_week5_prep.py
import yfinance as yf
import pandas_ta as ta

# Test data download for AAPL
print("Testing yfinance and pandas-ta setup:")
print("=" * 40)
try:
    # Download 1 month of AAPL data
    data = yf.download("AAPL", period="1mo")
    print(f"Downloaded {len(data)} rows of AAPL data")
    print(data.head())
    
    # Calculate a few technical indicators
    data.ta.rsi(append=True)
    data.ta.macd(append=True)
    data.ta.bbands(append=True)
    
    print("\nTechnical indicators calculated:")
    print("Columns:", [col for col in data.columns if col not in ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']])
    print(data.tail())
    
except Exception as e:
    print(f"Error: {e}")
    print("Make sure yfinance and pandas-ta are installed:")
    print("pip install yfinance pandas-ta")

# Optional: Save sample data for Week 5
if 'data' in locals():
    os.makedirs("data/raw/market", exist_ok=True)
    data.to_csv("data/raw/market/AAPL_1mo_sample.csv")
    print("\nSample data saved to data/raw/market/AAPL_1mo_sample.csv")
```

**To run:**
```bash
pip install yfinance pandas-ta
python test_week5_prep.py
```

---

## How to Use This Setup File

1. **Navigate to the RAATS_Test project root:**
   ```bash
   cd /c/Users/Zamuxolo/RAATS_Test
   ```

2. **Ensure your virtual environment is activated** (if using one):
   ```bash
   source venv/Scripts/activate  # or source RAATS_Test.venv/Scripts/activate
   ```

3. **Install required packages** for each day's activities as indicated in the code comments.

4. **Create and run the Python scripts** as shown in each section.

5. **Commit your work** regularly:
   ```bash
   git add .
   git commit -m "Week 4 NLP setup and experiments"
   git push origin dev
   ```

## Notes
- All code snippets are designed to be copy-paste executable.
- Adjust file paths based on your actual data locations (especially for Week 1 news data).
- The spaCy model (`en_core_web_sm`) should already be installed from Week 3 activities.
- For best results, run activities in the order presented to build upon previous steps.

---
*Created as part of Weekly Setup Instructions. Includes runnable code snippets for direct execution as requested.*