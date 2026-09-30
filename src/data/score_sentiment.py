import json
import logging
import os
from typing import Dict, Any, List

try:
    import ollama
except ImportError:
    ollama = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("raats.data.score_sentiment")


DEFAULT_SENTIMENT_MODEL = os.environ.get(
    "RAATS_SENTIMENT_MODEL",
    "mistral",
)


SENTIMENT_PROMPT = """Rate the financial sentiment of this news article for the given stock ticker.

Respond ONLY in valid JSON, no extra text.

Ticker: {ticker}
Source: {source}
Headline: {headline}
Summary: {summary}

Consider whether the article is positive, negative, or neutral for the specific ticker.

{{
  "sentiment": "positive | negative | neutral",
  "confidence": <0-1 float>,
  "reasoning": "<one short sentence>"
}}"""


def _safe_parse_json(raw_text: str) -> Dict[str, Any]:
    text = raw_text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning(
        "Could not parse sentiment output: %s",
        text[:150],
    )

    return {
        "sentiment": "neutral",
        "confidence": 0.0,
        "reasoning": "parse failed",
    }


def _normalise_sentiment(value: str) -> str:
    value = str(value or "").strip().lower()

    if value in {"positive", "negative", "neutral"}:
        return value

    return "neutral"


def score_article(
    ticker: str,
    article: Dict[str, Any],
    model_name: str = DEFAULT_SENTIMENT_MODEL,
) -> Dict[str, Any]:
    """Score one discovered news article."""

    if ollama is None:
        raise ImportError(
            "The 'ollama' package is required. "
            "Install with: pip install ollama"
        )

    source = article.get(
        "discovery_source",
        article.get("source", {}).get(
            "name",
            "Unknown",
        ),
    )

    prompt = SENTIMENT_PROMPT.format(
        ticker=ticker,
        source=source,
        headline=article.get("title", ""),
        summary=article.get("description", ""),
    )

    try:
        response = ollama.generate(
            model=model_name,
            prompt=prompt,
            options={
                "temperature": 0.1,
                "num_predict": 150,
            },
        )

        result = _safe_parse_json(
            response.get("response", "")
        )

    except Exception as exc:
        logger.error(
            "Sentiment scoring failed for %s: %s",
            ticker,
            article.get("title", "")[:80],
        )

        result = {
            "sentiment": "neutral",
            "confidence": 0.0,
            "reasoning": f"error: {exc}",
        }

    scored_article = dict(article)

    scored_article["sentiment"] = _normalise_sentiment(
        result.get("sentiment", "neutral")
    )

    try:
        scored_article["confidence"] = float(
            result.get("confidence", 0.0)
        )
    except (TypeError, ValueError):
        scored_article["confidence"] = 0.0

    scored_article["reasoning"] = str(
        result.get("reasoning", "")
    )

    return scored_article


def score_articles(
    ticker: str,
    articles: List[Dict[str, Any]],
    model_name: str = DEFAULT_SENTIMENT_MODEL,
) -> List[Dict[str, Any]]:
    """Score all discovered articles for one ticker."""

    scored = []

    for article in articles:
        scored_article = score_article(
            ticker,
            article,
            model_name=model_name,
        )

        scored.append(scored_article)

        logger.info(
            "%s | %s | %.2f | %s",
            ticker,
            scored_article["sentiment"],
            scored_article["confidence"],
            article.get("title", "")[:80],
        )

    return scored


def summarize_ticker_sentiment(
    scored_articles: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Create a ticker-level sentiment summary."""

    if not scored_articles:
        return {
            "overall": "neutral",
            "score": 0.0,
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "total": 0,
        }

    counts = {
        "positive": 0,
        "negative": 0,
        "neutral": 0,
    }

    weighted_total = 0.0
    total_confidence = 0.0

    values = {
        "positive": 1.0,
        "negative": -1.0,
        "neutral": 0.0,
    }

    for article in scored_articles:
        sentiment = _normalise_sentiment(
            article.get("sentiment", "neutral")
        )

        counts[sentiment] += 1

        try:
            confidence = float(
                article.get("confidence", 0.0)
            )
        except (TypeError, ValueError):
            confidence = 0.0

        confidence = max(
            0.0,
            min(1.0, confidence),
        )

        weighted_total += (
            values[sentiment] * confidence
        )

        total_confidence += confidence

    if total_confidence > 0:
        score = weighted_total / total_confidence
    else:
        score = 0.0

    if counts["positive"] > counts["negative"]:
        overall = "positive"
    elif counts["negative"] > counts["positive"]:
        overall = "negative"
    else:
        overall = "neutral"

    return {
        "overall": overall,
        "score": round(score, 4),
        **counts,
        "total": len(scored_articles),
    }


def save_scored_news(
    ticker: str,
    scored_articles: List[Dict[str, Any]],
    output_dir: str = "data/raw/news",
) -> str:
    """Save scored discovery news for auditing."""

    os.makedirs(output_dir, exist_ok=True)

    path = os.path.join(
        output_dir,
        f"{ticker}_news_scored.json",
    )

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            scored_articles,
            f,
            indent=2,
            ensure_ascii=False,
        )

    logger.info(
        "%s: saved %d scored articles to %s",
        ticker,
        len(scored_articles),
        path,
    )

    return path


def score_and_save_ticker_news(
    ticker: str,
    articles: List[Dict[str, Any]],
    model_name: str = DEFAULT_SENTIMENT_MODEL,
    output_dir: str = "data/raw/news",
) -> Dict[str, Any]:
    """
    Score discovered articles, save them, and return
    both the scored articles and ticker summary.
    """

    scored = score_articles(
        ticker,
        articles,
        model_name=model_name,
    )

    summary = summarize_ticker_sentiment(
        scored
    )

    path = save_scored_news(
        ticker,
        scored,
        output_dir=output_dir,
    )

    return {
        "articles": scored,
        "summary": summary,
        "path": path,
    }