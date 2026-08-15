"""
notebooks/vector_store_chroma.py

Sets up a persistent Chroma collection, indexes a handful of sample
news/technical snippets, and runs a few semantic queries to sanity-check
retrieval quality.

This version uses a deterministic hashing-based embedding function to avoid
downloading external models, making it usable offline.

Run:
    python vector_store_chroma.py
"""

import logging
import hashlib
import random
from typing import List

try:
    import chromadb
except ImportError:
    chromadb = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vector_store_chroma")


class SimpleHashingEmbeddingFunction:
    """Deterministic embedding function based on a hash of the text.
    NOT suitable for real semantic search — only for demonstration of the Chroma API.
    """
    def __init__(self, dim: int = 384):
        self.dim = dim

    def __call__(self, input: List[str]) -> List[List[float]]:
        # Chroma passes a list of strings (or list of bytes, etc.)
        embeddings: List[List[float]] = []
        for text in input:
            if isinstance(text, bytes):
                text = text.decode('utf-8', errors='ignore')
            # Deterministic seed from MD5 hash
            hash_int = int(hashlib.md5(text.encode('utf-8')).hexdigest(), 16)
            random.seed(hash_int)
            embedding = [random.uniform(-1, 1) for _ in range(self.dim)]
            embeddings.append(embedding)
        return embeddings


class ChromaVectorStore:
    def __init__(self, persist_directory="./chroma_db", collection_name="raats_news"):
        if chromadb is None:
            raise ImportError(
                "The 'chromadb' package is not installed. Run: pip install chromadb"
            )
        self.client = chromadb.PersistentClient(path=persist_directory)
        # If a collection with the same name exists, delete it to avoid embedding function conflicts.
        existing = [c.name for c in self.client.list_collections()]
        if collection_name in existing:
            logger.info("Deleting existing collection '%s' to avoid embedding function conflict.", collection_name)
            self.client.delete_collection(name=collection_name)
        self.embedding_fn = SimpleHashingEmbeddingFunction()
        self.collection = self.client.create_collection(
            name=collection_name,
            embedding_function=self.embedding_fn,  # type: ignore[arg-type]
        )
        logger.info(
            "Chroma collection '%s' ready at %s (count=%d)",
            collection_name,
            persist_directory,
            self.collection.count(),
        )

    def add_news(self, doc_id, text, ticker, date, source="unknown"):
        if chromadb is None:
            raise ImportError("chromadb is not available")
        self.collection.add(
            ids=[doc_id],
            documents=[text],
            metadatas=[{"ticker": ticker, "date": date, "source": source, "type": "news"}],
        )

    def add_technical_note(self, doc_id, text, ticker, indicator):
        if chromadb is None:
            raise ImportError("chromadb is not available")
        self.collection.add(
            ids=[doc_id],
            documents=[text],
            metadatas=[{"ticker": ticker, "type": "technical", "indicator": indicator}],
        )

    def query(self, query_text, ticker=None, n_results=5):
        if chromadb is None:
            raise ImportError("chromadb is not available")
        where = {"ticker": ticker} if ticker else None
        return self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where,
        )


SAMPLE_NEWS = [
    {
        "doc_id": "news_001",
        "text": "Apple reported record iPhone sales in Q4, beating analyst expectations "
                "and signaling strong consumer demand heading into the holiday season.",
        "ticker": "AAPL",
        "date": "2026-01-15",
        "source": "sample_wire",
    },
    {
        "doc_id": "news_002",
        "text": "Tesla shares dropped after the company missed delivery targets for the "
                "third consecutive quarter amid rising competition in the EV market.",
        "ticker": "TSLA",
        "date": "2026-01-10",
        "source": "sample_wire",
    },
    {
        "doc_id": "news_003",
        "text": "Analysts upgraded Apple stock citing services revenue growth and "
                "expanding margins in the wearables segment.",
        "ticker": "AAPL",
        "date": "2026-01-20",
        "source": "sample_wire",
    },
]

SAMPLE_TECHNICAL = [
    {
        "doc_id": "tech_001",
        "text": "AAPL RSI(14) crossed above 55, ADX rising above 25 indicating a "
                "strengthening uptrend with increasing directional momentum.",
        "ticker": "AAPL",
        "indicator": "RSI+ADX",
    },
]


def main():
    if chromadb is None:
        print("The 'chromadb' package is not installed. Run: pip install chromadb")
        return

    store = ChromaVectorStore(persist_directory="./chroma_db_demo")

    for item in SAMPLE_NEWS:
        store.add_news(**item)
    for item in SAMPLE_TECHNICAL:
        store.add_technical_note(**item)

    print(f"\nCollection size after indexing: {store.collection.count()}")

    print("\n--- Query: 'strong sales, positive outlook' (ticker=AAPL) ---")
    results = store.query("strong sales, positive outlook", ticker="AAPL", n_results=2)
    if results and results.get("documents"):
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            print(f"[{meta.get('date', meta.get('type'))}] {doc[:100]}...")
    else:
        print("No results returned.")

    print("\n--- Query: 'missed targets, competition' (ticker=TSLA) ---")
    results = store.query("missed targets, competition", ticker="TSLA", n_results=2)
    if results and results.get("documents"):
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            print(f"[{meta.get('date', meta.get('type'))}] {doc[:100]}...")
    else:
        print("No results returned.")

    print("\n--- Query: 'uptrend momentum indicators' (no ticker filter) ---")
    results = store.query("uptrend momentum indicators", n_results=3)
    if results and results.get("documents"):
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            print(f"[{meta.get('ticker')}] {doc[:100]}...")
    else:
        print("No results returned.")

    print("\nDone. Persisted collection is available at ./chroma_db_demo for reuse.")


if __name__ == "__main__":
    main()