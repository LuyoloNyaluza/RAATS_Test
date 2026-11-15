"""
src/rag/news_memory.py

Short-term news memory for RAATS (FAISS + nomic-embed-text).

What it is for
--------------
1. Stage 4 (sentiment scorer): when scoring one headline, show the model a
   couple of RELATED headlines from the same batch / earlier days, so an
   article such as "Buyout Talks Pause" can be read next to the article that
   says the talks were abandoned (which may sit in another ticker's batch).
2. Stage 6 (analyst): give the analyst the last few days of coverage for the
   ticker, labelled as history (not live news).

Design rules (all deliberate)
-----------------------------
* NEW index: data/vector_stores/faiss_news_history. It never touches the
  static test corpus at data/vector_stores/faiss_news.
* Stores article TEXT only (title + description when there is one). Past
  sentiment labels are never stored or retrieved.
* De-duplicated on (ticker, url), falling back to the normalised title when
  there is no url. Retrieval also collapses duplicate stories.
* Never raises into the trading flow: every public function returns an empty
  result and logs a warning if the index, Ollama or FAISS misbehaves.
* Look-ahead guard: retrieval only returns articles dated on or before
  `as_of` (scorer) or strictly before it (analyst history).
* Heavy imports (langchain, FAISS) are lazy, so importing this module is free.

Switches (environment)
----------------------
RAATS_NEWS_MEMORY=0            disable everything (all functions become no-ops)
RAATS_NEWS_MEMORY_PATH         index folder
RAATS_EMBED_MODEL              embedding model (default nomic-embed-text)
RAATS_NEWS_MEMORY_MAX_DIST     optional L2 distance cut-off for related items
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger("raats.rag.news_memory")

VECTORSTORE_PATH = os.environ.get(
    "RAATS_NEWS_MEMORY_PATH",
    "data/vector_stores/faiss_news_history",
)
EMBED_MODEL = os.environ.get("RAATS_EMBED_MODEL", "nomic-embed-text")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

_embeddings = None
_store = None
_store_loaded = False


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------

def enabled() -> bool:
    return os.environ.get("RAATS_NEWS_MEMORY", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _to_date(value: Any) -> str:
    """Normalise a date-like value to 'YYYY-MM-DD' (today if unusable)."""
    if value is None:
        return _today()
    text = str(value).strip()
    if _DATE_RE.match(text):
        return text[:10]
    return _today()


def _url(article: Dict[str, Any]) -> str:
    return str(article.get("link") or article.get("url") or "").strip()


def _norm_title(title: Any) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", str(title or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _dedupe_key(ticker: str, article: Dict[str, Any]) -> Tuple[str, str]:
    url = _url(article)
    return ticker, url if url else "title:" + _norm_title(article.get("title"))


def _article_text(article: Dict[str, Any]) -> str:
    """Title plus description when one exists (discovery articles often
    carry only a title; that is fine, it is just a weaker embedding)."""
    title = str(article.get("title") or "").strip()
    description = str(
        article.get("description") or article.get("summary") or ""
    ).strip()
    if description and description.lower() != title.lower():
        return f"{title}. {description[:300]}"
    return title


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ----------------------------------------------------------------------
# Store plumbing
# ----------------------------------------------------------------------

def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        from langchain_ollama import OllamaEmbeddings

        _embeddings = OllamaEmbeddings(model=EMBED_MODEL)
    return _embeddings


def reset_cache() -> None:
    """Forget the in-memory handle (tests, or after deleting the folder)."""
    global _store, _store_loaded
    _store = None
    _store_loaded = False


def _load():
    """Return the FAISS store, or None if there is no index yet."""
    global _store, _store_loaded
    if _store_loaded:
        return _store
    if not os.path.isdir(VECTORSTORE_PATH):
        _store_loaded = True
        _store = None
        return None
    try:
        from langchain_community.vectorstores import FAISS

        _store = FAISS.load_local(
            VECTORSTORE_PATH,
            _get_embeddings(),
            allow_dangerous_deserialization=True,
        )
    except Exception as exc:  # corrupt index, missing libs, Ollama down
        logger.warning("news_memory: could not load index (%s)", exc)
        _store = None
    _store_loaded = True
    return _store


def _entries(store) -> List[Dict[str, Any]]:
    """All stored metadata dicts (plus text), without any embedding call."""
    if store is None:
        return []
    try:
        docs = list(store.docstore._dict.values())
    except Exception as exc:
        logger.warning("news_memory: cannot read docstore (%s)", exc)
        return []
    out = []
    for doc in docs:
        meta = dict(getattr(doc, "metadata", {}) or {})
        meta["text"] = getattr(doc, "page_content", "")
        out.append(meta)
    return out


# ----------------------------------------------------------------------
# Ingest
# ----------------------------------------------------------------------

def ingest_many(
    items: Iterable[Tuple[str, Sequence[Dict[str, Any]]]],
    date: Optional[str] = None,
) -> int:
    """
    Add articles for several tickers in ONE embedding call and ONE save.
    `items` is [(ticker, [article, ...]), ...]. Returns how many were added.

    Call this for the whole batch BEFORE scoring, so every article can see
    the others. Already-stored (ticker, url) pairs are skipped.
    """
    if not enabled():
        return 0
    try:
        day = _to_date(date)
        store = _load()
        seen: Set[Tuple[str, str]] = {
            (m.get("ticker", ""), m.get("key", "")) for m in _entries(store)
        }

        texts: List[str] = []
        metas: List[Dict[str, Any]] = []

        for ticker, articles in items:
            ticker = str(ticker or "").upper().strip()
            if not ticker:
                continue
            for article in articles or []:
                if not isinstance(article, dict) or not article.get("title"):
                    continue
                key = _dedupe_key(ticker, article)
                if key in seen:
                    continue
                seen.add(key)
                texts.append(_article_text(article))
                metas.append(
                    {
                        "ticker": ticker,
                        "date": day,
                        "url": _url(article),
                        "key": key[1],
                        "title": str(article.get("title")).strip(),
                    }
                )

        if not texts:
            return 0

        global _store, _store_loaded
        if store is None:
            from langchain_community.vectorstores import FAISS

            store = FAISS.from_texts(texts, _get_embeddings(), metadatas=metas)
        else:
            store.add_texts(texts, metadatas=metas)

        os.makedirs(os.path.dirname(VECTORSTORE_PATH) or ".", exist_ok=True)
        store.save_local(VECTORSTORE_PATH)
        _store, _store_loaded = store, True

        logger.info("news_memory: indexed %d new article(s) for %s", len(texts), day)
        return len(texts)

    except Exception as exc:
        logger.warning("news_memory: ingest failed (%s)", exc)
        return 0


def ingest(ticker: str, articles: Sequence[Dict[str, Any]], date: Optional[str] = None) -> int:
    """Single-ticker convenience wrapper around ingest_many()."""
    return ingest_many([(ticker, articles)], date)


# ----------------------------------------------------------------------
# Retrieve: related headlines for the scorer
# ----------------------------------------------------------------------

def retrieve_related(
    article: Dict[str, Any],
    as_of: Optional[str] = None,
    k: int = 2,
    max_distance: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Up to `k` stored articles most similar to `article`, dated on or before
    `as_of`, never the article itself, never a repeat of the same story.
    No ticker filter on purpose: the point is cross-ticker context.

    Each result: {"date", "ticker", "title", "text", "url", "distance"}.
    """
    if not enabled() or not article.get("title"):
        return []
    try:
        store = _load()
        if store is None:
            return []

        if max_distance is None:
            raw = os.environ.get("RAATS_NEWS_MEMORY_MAX_DIST", "").strip()
            max_distance = float(raw) if raw else None

        limit = _to_date(as_of)
        own_url = _url(article)
        own_title = _norm_title(article.get("title"))

        def keep(meta: Dict[str, Any]) -> bool:
            return (
                str(meta.get("date", "")) <= limit
                and (not own_url or meta.get("url") != own_url)
                and _norm_title(meta.get("title")) != own_title
            )

        query = _article_text(article)
        fetch_k = max(50, k * 20)
        try:
            hits = store.similarity_search_with_score(
                query, k=k * 3, fetch_k=fetch_k, filter=keep
            )
        except Exception:
            # Older langchain_community: no callable filters. Filter by hand.
            hits = [
                (d, s)
                for d, s in store.similarity_search_with_score(query, k=fetch_k)
                if keep(d.metadata)
            ]

        results: List[Dict[str, Any]] = []
        seen_titles: Set[str] = set()
        for doc, score in hits:
            meta = doc.metadata
            norm = _norm_title(meta.get("title"))
            if norm in seen_titles:
                continue
            if max_distance is not None and float(score) > max_distance:
                continue
            seen_titles.add(norm)
            results.append(
                {
                    "date": meta.get("date", ""),
                    "ticker": meta.get("ticker", ""),
                    "title": meta.get("title", ""),
                    "text": doc.page_content,
                    "url": meta.get("url", ""),
                    "distance": float(score),
                }
            )
            if len(results) >= k:
                break
        return results

    except Exception as exc:
        logger.warning("news_memory: retrieve_related failed (%s)", exc)
        return []


# ----------------------------------------------------------------------
# Retrieve: recent history for one ticker (analyst)
# ----------------------------------------------------------------------

def recent_for_ticker(
    ticker: str,
    as_of: Optional[str] = None,
    days: int = 5,
    k: int = 4,
) -> List[Dict[str, Any]]:
    """
    Earlier coverage of `ticker`: dated within the last `days` days and
    STRICTLY BEFORE `as_of` (today's articles are already in the live
    news_context). Newest first. No embedding call, so no latency cost.
    """
    if not enabled():
        return []
    try:
        ticker = str(ticker or "").upper().strip()
        end = _to_date(as_of)
        start = (
            datetime.strptime(end, "%Y-%m-%d") - timedelta(days=days)
        ).strftime("%Y-%m-%d")

        rows = [
            m
            for m in _entries(_load())
            if m.get("ticker") == ticker and start <= str(m.get("date", "")) < end
        ]
        rows.sort(key=lambda m: str(m.get("date", "")), reverse=True)

        out, seen = [], set()
        for m in rows:
            norm = _norm_title(m.get("title"))
            if norm in seen:
                continue
            seen.add(norm)
            out.append(
                {
                    "date": m.get("date", ""),
                    "ticker": ticker,
                    "title": m.get("title", ""),
                    "text": m.get("text", ""),
                    "url": m.get("url", ""),
                }
            )
            if len(out) >= k:
                break
        return out

    except Exception as exc:
        logger.warning("news_memory: recent_for_ticker failed (%s)", exc)
        return []


# ----------------------------------------------------------------------
# Prompt blocks (empty string when there is nothing to add)
# ----------------------------------------------------------------------

def format_related_block(ticker: str, items: Sequence[Dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = [
        f"Related earlier coverage (background only; it may concern OTHER "
        f"companies. Score ONLY the headline above, for {ticker}):"
    ]
    for it in items:
        lines.append(
            f"- [{it.get('date', '')} | {it.get('ticker', '')}] "
            f"{_clip(it.get('text') or it.get('title', ''), 200)}"
        )
    return "\n" + "\n".join(lines) + "\n"


def format_history_block(ticker: str, items: Sequence[Dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = [
        f"Earlier coverage of {ticker} from previous days (historical context, "
        f"NOT live news; do not treat it as a new development):"
    ]
    for it in items:
        lines.append(f"- [{it.get('date', '')}] {_clip(it.get('title', ''), 160)}")
    return "\n" + "\n".join(lines) + "\n"
