
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("raats.update_vector_store")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def run_news_fetch():
    """Step 1: Run the news fetching script (real headlines via Google News RSS)."""
    print("Step 1: Fetching latest financial news...")
    script_path = SRC_DIR / "data" / "fetch_news.py"

    if not script_path.exists():
        print(f"  Skipping: {script_path} not found.")
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, check=True,
            encoding="utf-8", errors="replace",
        )
        print(result.stdout)
        if result.stderr:
            print("Warnings:", result.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching news: {e}")
        print(e.stdout)
        print(e.stderr)
        return False
    return True


def run_sentiment_scoring(news_dir: Optional[Path] = None, model_name: str = "mistral"):
    """Step 1.5: Score sentiment on freshly fetched news using local Ollama."""
    print("\nStep 1.5: Scoring news sentiment locally via Ollama...")

    from data.score_sentiment import score_articles, summarize_ticker_sentiment

    news_dir = news_dir or (PROJECT_ROOT / "data" / "raw" / "news")
    if not news_dir.exists():
        print(f"  No news directory found at {news_dir} — skipping sentiment scoring.")
        return False

    news_files = sorted(news_dir.glob("*_news_*.json"))
    if not news_files:
        print(f"  No news files found in {news_dir} — skipping sentiment scoring.")
        return False

    latest_by_ticker = {}
    for f in news_files:
        ticker = f.name.split("_news_")[0]
        latest_by_ticker[ticker] = f

    all_summaries = {}
    for ticker, filepath in latest_by_ticker.items():
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                articles = json.load(fh)
        except Exception as exc:
            print(f"  Could not read {filepath}: {exc}")
            continue

        if not articles:
            print(f"  {ticker}: no articles to score, skipping.")
            continue

        try:
            scored = score_articles(ticker, articles, model_name=model_name)
        except Exception as exc:
            print(f"  Sentiment scoring failed for {ticker}: {exc}")
            print("  (Is Ollama running? Try: ollama serve)")
            return False

        scored_path = news_dir / f"{ticker}_news_scored.json"
        with open(scored_path, "w", encoding="utf-8") as fh:
            json.dump(scored, fh, indent=2, ensure_ascii=False)

        summary = summarize_ticker_sentiment(scored)
        all_summaries[ticker] = summary
        print(f"  {ticker}: {summary['total']} articles scored -> "
              f"{summary['positive']} positive, {summary['negative']} negative, "
              f"{summary['neutral']} neutral (overall: {summary['overall']})")

    summary_path = news_dir / f"sentiment_summary_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(all_summaries, fh, indent=2)
    print(f"  Saved sentiment summary to {summary_path}")

    return True


def process_and_store_news():
    """Step 2: Process news and update vector stores."""
    print("\nStep 2: Processing news and updating vector stores...")
    script_path = SRC_DIR / "data" / "process_news.py"

    if not script_path.exists():
        print(f"  Skipping: {script_path} not found.")
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, check=True,
            encoding="utf-8", errors="replace",
        )
        print(result.stdout)
        if result.stderr:
            print("Warnings:", result.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error processing news: {e}")
        print(e.stdout)
        print(e.stderr)
        return False
    return True


def main():
    """Main update pipeline."""
    print("Starting vector store update process...")
    print("=" * 50)

    success = True
    success = run_news_fetch() and success
    success = run_sentiment_scoring() and success
    success = process_and_store_news() and success

    if success:
        print("\n" + "=" * 50)
        print("Vector store update completed successfully!")
        print("Updated stores available in:")
        print("- data/vector_stores/faiss_news/")
        print("- data/vector_stores/chroma_news/")
        print("Scored sentiment available in:")
        print("- data/raw/news/{ticker}_news_scored.json")
    else:
        print("\n" + "=" * 50)
        print("Vector store update failed. Check logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()