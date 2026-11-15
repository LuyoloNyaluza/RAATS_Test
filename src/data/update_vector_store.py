"""Fetch raw financial news and incrementally update the RAG vector stores.

Sentiment interpretation belongs to the RAG layer. This updater only fetches
and indexes source articles; it does not run the legacy article sentiment
scorer or treat its derived JSON files as source news.
"""
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("raats.update_vector_store")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def run_news_fetch() -> bool:
    """Fetch the current watchlist news into data/raw/news/*.json."""
    print("Step 1: Fetching latest financial news...")
    script_path = SRC_DIR / "data" / "fetch_news.py"
    if not script_path.exists():
        logger.error("News fetch script not found: %s", script_path)
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print("Fetcher output:", result.stderr)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("News fetching failed: %s", exc)
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr)
        return False


def process_and_store_news() -> bool:
    """Convert raw JSON articles to Documents and incrementally update stores."""
    print("\nStep 2: Processing JSON news and updating vector stores...")
    script_path = SRC_DIR / "data" / "process_news.py"
    if not script_path.exists():
        logger.error("News processing script not found: %s", script_path)
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print("Indexer output:", result.stderr)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("Vector-store update failed: %s", exc)
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr)
        return False


def main() -> None:
    """Run the fetch-and-index pipeline."""
    print("Starting financial-news RAG ingestion...")
    print("=" * 50)

    if not run_news_fetch():
        raise SystemExit("News fetch failed; vector stores were not updated.")

    if not process_and_store_news():
        raise SystemExit("News indexing failed; inspect the output above.")

    print("\n" + "=" * 50)
    print("News ingestion completed successfully.")
    print("FAISS: data/vector_stores/faiss_news/")
    print("Chroma: data/vector_stores/chroma_news/")


if __name__ == "__main__":
    main()
