
import os
import pandas as pd
from financial_nlp_pipeline import financial_nlp_pipeline

# Adjust path to wherever your Week 1 / Week 3 combined news data actually lives.
NEWS_PATH = "data/processed/combined_news.csv"
OUTPUT_PATH = "data/processed/news_enriched_week4.csv"

if __name__ == "__main__":
    if not os.path.exists(NEWS_PATH):
        raise FileNotFoundError(
            f"Couldn't find {NEWS_PATH} - update NEWS_PATH to point at your "
            f"actual Week 1/3 news CSV before running this."
        )

    news_df = pd.read_csv(NEWS_PATH)

    if "text" not in news_df.columns:
        raise KeyError(
            f"Expected a 'text' column in {NEWS_PATH}, got: {list(news_df.columns)}. "
            f"Update the column name below if your headline/summary column is named differently."
        )

    results = []
    for idx, row in news_df.iterrows():
        result = financial_nlp_pipeline(row["text"])
        result["original_index"] = idx
        results.append(result)

    # Flatten nested dict fields (vader, textblob) into dot-notation columns
    # so Friday's script can read df['vader.label'] / df['textblob.label']
    # directly, without needing to parse a stringified dict back out.
    results_df = pd.json_normalize(results)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    results_df.to_csv(OUTPUT_PATH, index=False)
    print(f"Enriched data saved with {len(results_df)} records -> {OUTPUT_PATH}")
    print(f"Columns: {list(results_df.columns)}")