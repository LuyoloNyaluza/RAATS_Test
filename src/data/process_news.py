"""Ingest fetched financial-news JSON into the persistent FAISS and Chroma stores.

The live RAG chain reads the FAISS store at data/vector_stores/faiss_news.
News files are written by fetch_news.py as JSON, so this module deliberately
uses that format and retains article metadata for ticker-aware retrieval.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_chroma import Chroma

LOGGER = logging.getLogger("raats.process_news")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NEWS_DIR = PROJECT_ROOT / "data" / "raw" / "news"
DEFAULT_FAISS_DIR = PROJECT_ROOT / "data" / "vector_stores" / "faiss_news"
DEFAULT_CHROMA_DIR = PROJECT_ROOT / "data" / "vector_stores" / "chroma_news"
EMBEDDING_MODEL = "nomic-embed-text"


def _resolve_path(path: str | Path) -> Path:
    """Resolve relative data paths from the repository root, not the shell CWD."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _normalise_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _article_to_document(article: dict[str, Any], file_path: Path) -> Document | None:
    ticker = _normalise_text(article.get("ticker") or file_path.name.split("_news_")[0]).upper()
    title = _normalise_text(article.get("title") or article.get("headline"))
    description = _normalise_text(article.get("description") or article.get("summary"))
    content = _normalise_text(article.get("content"))
    url = _normalise_text(article.get("url") or article.get("link"))

    body_parts = [part for part in (title, description, content) if part]
    text = _normalise_text(". ".join(dict.fromkeys(body_parts)))
    if len(text) < 10:
        return None

    source_value = article.get("source")
    if isinstance(source_value, dict):
        source = _normalise_text(source_value.get("name"))
    else:
        source = _normalise_text(source_value)

    published_at = _normalise_text(
        article.get("publishedAt") or article.get("published_at") or article.get("published")
    )

    # Prefer the canonical article URL. Fall back to stable article fields so
    # repeated fetches do not create duplicate vectors.
    identity = url or "|".join((ticker, title, published_at))
    if not identity.strip("|"):
        identity = f"{ticker}|{text}"
    article_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    metadata = {
        "article_id": article_id,
        "content_hash": content_hash,
        "ticker": ticker,
        "title": title,
        "source": source,
        "published_at": published_at,
        "url": url,
        "source_file": file_path.name,
    }
    metadata = {key: value for key, value in metadata.items() if value != ""}
    return Document(page_content=text, metadata=metadata)


def load_news_documents(data_dir: str | Path = DEFAULT_NEWS_DIR) -> list[Document]:
    """Load timestamped raw-news JSON files and convert valid articles to Documents.

    Scored outputs (for example AAPL_news_scored.json) are intentionally
    excluded because they are derived data, not independent news articles.
    """
    news_dir = _resolve_path(data_dir)
    if not news_dir.exists():
        LOGGER.warning("News directory does not exist: %s", news_dir)
        return []

    files = sorted(
        path for path in news_dir.glob("*_news_*.json")
        if not path.name.endswith("_news_scored.json")
    )
    documents: dict[str, Document] = {}

    for file_path in files:
        try:
            with file_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Skipping unreadable news file %s: %s", file_path, exc)
            continue

        if isinstance(payload, dict):
            articles = payload.get("articles", [])
            if not isinstance(articles, list):
                articles = [payload]
        elif isinstance(payload, list):
            articles = payload
        else:
            LOGGER.warning("Skipping unsupported JSON structure in %s", file_path)
            continue

        for article in articles:
            if not isinstance(article, dict):
                continue
            document = _article_to_document(article, file_path)
            if document is not None:
                documents[document.metadata["article_id"]] = document

    return list(documents.values())


def update_vector_stores(
    documents: list[Document],
    faiss_dir: str | Path = DEFAULT_FAISS_DIR,
    chroma_dir: str | Path = DEFAULT_CHROMA_DIR,
    embedding_model: str = EMBEDDING_MODEL,
) -> dict[str, int]:
    """Add previously unseen articles to FAISS and Chroma without rebuilding them."""
    if not documents:
        return {"loaded": 0, "faiss_added": 0, "faiss_total": 0,
                "chroma_added": 0, "chroma_total": 0}

    faiss_path = _resolve_path(faiss_dir)
    chroma_path = _resolve_path(chroma_dir)
    faiss_path.mkdir(parents=True, exist_ok=True)
    chroma_path.mkdir(parents=True, exist_ok=True)

    embeddings = OllamaEmbeddings(model=embedding_model)

    # FAISS does not provide native upsert. Use article_id metadata to append
    # only unseen articles, preserving the existing index.
    index_file = faiss_path / "index.faiss"
    metadata_file = faiss_path / "index.pkl"
    if index_file.exists() and metadata_file.exists():
        faiss_store = FAISS.load_local(
            str(faiss_path),
            embeddings,
            allow_dangerous_deserialization=True,
        )
        existing_docs = list(faiss_store.docstore._dict.values())
        known_ids = {
            doc.metadata.get("article_id")
            for doc in existing_docs
            if doc.metadata.get("article_id")
        }
        known_content = {
            hashlib.sha256(doc.page_content.encode("utf-8")).hexdigest()
            for doc in existing_docs
        }
        faiss_new = [
            doc for doc in documents
            if doc.metadata["article_id"] not in known_ids
            and doc.metadata["content_hash"] not in known_content
        ]
    else:
        faiss_store = None
        faiss_new = documents

    if faiss_new:
        if faiss_store is None:
            faiss_store = FAISS.from_documents(faiss_new, embeddings)
        else:
            faiss_store.add_documents(faiss_new)
        faiss_store.save_local(str(faiss_path))

    faiss_total = faiss_store.index.ntotal if faiss_store is not None else 0

    # Keep the existing default LangChain collection name for compatibility
    # with the Chroma store created by the previous process_news.py.
    chroma_store = Chroma(
        embedding_function=embeddings,
        persist_directory=str(chroma_path),
    )
    existing_chroma = chroma_store.get(include=["metadatas", "documents"])
    existing_chroma_ids = set(existing_chroma.get("ids", []))
    existing_chroma_content = {
        hashlib.sha256(text.encode("utf-8")).hexdigest()
        for text in existing_chroma.get("documents", [])
        if text
    }
    chroma_new = [
        doc for doc in documents
        if doc.metadata["article_id"] not in existing_chroma_ids
        and doc.metadata["content_hash"] not in existing_chroma_content
    ]
    if chroma_new:
        chroma_store.add_documents(
            chroma_new,
            ids=[doc.metadata["article_id"] for doc in chroma_new],
        )

    chroma_total = chroma_store._collection.count()
    return {
        "loaded": len(documents),
        "faiss_added": len(faiss_new),
        "faiss_total": faiss_total,
        "chroma_added": len(chroma_new),
        "chroma_total": chroma_total,
    }


def load_and_clean_news(data_dir: str | Path = DEFAULT_NEWS_DIR):
    """Backward-compatible entry point returning the normalised article documents."""
    return load_news_documents(data_dir)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    news_documents = load_news_documents()
    print(f"Loaded {len(news_documents)} unique news articles from JSON")
    if not news_documents:
        raise SystemExit(
            "No valid news articles found. Fetch news first; existing vector stores were not changed."
        )

    stats = update_vector_stores(news_documents)
    print("Vector store update completed:")
    print(f"  Articles loaded: {stats['loaded']}")
    print(f"  New FAISS vectors: {stats['faiss_added']}")
    print(f"  Total FAISS vectors: {stats['faiss_total']}")
    print(f"  New Chroma documents: {stats['chroma_added']}")
    print(f"  Total Chroma documents: {stats['chroma_total']}")
