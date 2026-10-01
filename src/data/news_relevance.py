import re
from typing import Any, Dict, List, Optional, Tuple


def _normalise_text(text: Any) -> str:
    """Normalise text for matching."""

    if not text:
        return ""

    text = str(text).lower()
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _contains_ticker(
    text: str,
    ticker: str,
) -> bool:
    """Check for an exact ticker-symbol match."""

    if not ticker:
        return False

    return bool(
        re.search(
            rf"\b{re.escape(ticker.lower())}\b",
            text,
        )
    )


def _contains_company_name(
    text: str,
    company_name: Optional[str],
) -> bool:
    """Check whether the company name appears in the text."""

    if not company_name:
        return False

    company_name = _normalise_text(
        company_name
    )

    if not company_name:
        return False

    return company_name in text


def validate_article_relevance(
    article: Dict[str, Any],
    ticker: str,
    company_name: Optional[str] = None,
) -> str:
    """
    Determine whether an article is relevant to a ticker.

    Returns:
        relevant
        irrelevant
        ambiguous
    """

    title = _normalise_text(
        article.get("title")
        or article.get("headline")
        or ""
    )

    summary = _normalise_text(
        article.get("summary")
        or article.get("description")
        or ""
    )

    if not title and not summary:
        return "irrelevant"

    # Strong evidence:
    # Company name or ticker appears in the title.
    if _contains_company_name(
        title,
        company_name,
    ):
        return "relevant"

    if _contains_ticker(
        title,
        ticker,
    ):
        return "relevant"

    # Company name in summary is also useful evidence.
    if _contains_company_name(
        summary,
        company_name,
    ):
        return "relevant"

    # Ticker only appearing in the summary is weaker.
    if _contains_ticker(
        summary,
        ticker,
    ):
        return "ambiguous"

    return "irrelevant"


def filter_relevant_articles(
    articles: List[Dict[str, Any]],
    ticker: str,
    company_name: Optional[str] = None,
) -> Tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    """
    Filter articles for one ticker.

    Returns:
        relevant_articles
        relevance_results
    """

    relevant_articles = []
    relevance_results = []

    for article in articles:

        relevance = validate_article_relevance(
            article=article,
            ticker=ticker,
            company_name=company_name,
        )

        title = (
            article.get("title")
            or article.get("headline")
            or ""
        )

        result = {
            "ticker": ticker,
            "title": title,
            "relevance": relevance,
        }

        relevance_results.append(
            result
        )

        if relevance == "relevant":
            relevant_articles.append(
                article
            )

    return (
        relevant_articles,
        relevance_results,
    )