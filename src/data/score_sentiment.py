import json
import re
import logging
import os
from typing import Dict, Any, List, Optional

try:
    import ollama
except ImportError:
    ollama = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("raats.data.score_sentiment")


DEFAULT_SENTIMENT_MODEL = os.environ.get(
    "RAATS_SENTIMENT_MODEL",
    "phi3:mini-128k",
)


SENTIMENT_INSTRUCTIONS = """You are an objective financial news analyst.

### Evaluation Rules:
1. **Ticker Relevance**: Assess the article in relation to the specific ticker. Do not assign sentiment based on news about another company unless a clear and meaningful connection exists.

2. **Evidence Evaluation**: Base sentiment on the information actually reported in the current headline and summary. Do not assume financial impact, market reaction, or future outcomes that the article does not establish.

3. **Positive Sentiment**: Use positive when the reported development provides a reasonably clear benefit to the company, such as improved earnings, revenue growth, increased demand, successful products, or favourable business developments.

4. **Negative Sentiment**: Use negative when the reported development presents a reasonably clear disadvantage, such as declining earnings, revenue losses, regulatory penalties, dilution, major customer losses, or operational problems.

5. **Routine News**: Scheduled events, routine appointments, ordinary filings, routine financing, and announcements without demonstrated financial benefits or disadvantages should generally be neutral.

6. **Read Direction Carefully**: Check negations, comparisons and expectations against the actual reported outcome. For example, losses narrowing or revenue declining less than expected may indicate improvement, but assess the overall evidence rather than relying on wording alone. Guidance and outlook should also be considered alongside historical results.

7. **Mixed and Unclear News**: Use neutral when positive and negative developments roughly balance, or when the article is informational, speculative, ambiguous, or unrelated to the ticker.

8. **Avoid False Signals**: Do not interpret analyst opinions, routine announcements, partnerships without demonstrated benefits, or general industry news as automatically positive or negative.

9. **Related News Context**: Any related earlier coverage is background information only. Base the classification primarily on the current article. Do not allow unrelated historical headlines to determine its sentiment.

10. **Confidence Assessment**: Confidence should reflect the relevance, clarity, and strength of the evidence. Use lower confidence when the article is ambiguous, incomplete, indirect, or based on speculation.

11. **Strict Constraints**: Answer with exactly one of: positive, negative, neutral. Do not provide trading advice.

Respond ONLY in valid JSON, no extra text.
Keep "reasoning" to ONE short sentence, under 20 words:

{{
  "sentiment": "positive | negative | neutral",
  "confidence": <0-1 float>,
  "reasoning": "<one short sentence, max 20 words>"
}}
"""

SENTIMENT_ARTICLE = """
Ticker: {ticker}
Source: {source}
Headline: {headline}
Summary: {summary}
{related_block}
JSON:"""

SENTIMENT_PROMPT = SENTIMENT_INSTRUCTIONS + SENTIMENT_ARTICLE


_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.S | re.I)


def _strip_think(text: str) -> str:
    """Reasoning models (e.g. Qwen-Open-Finance-R) write <think>...</think> before the answer; the
    thinking can contain braces and break the JSON search below."""
    return _THINK.sub("", text or "").strip()


def _safe_parse_json(raw_text: str) -> Dict[str, Any]:
    text = _strip_think(raw_text)

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


_LABELS = ("positive", "negative", "neutral")


def _validate_answer(result: Dict[str, Any]):
    """(sentiment, confidence, valid). An answer is usable only if it names exactly one of the
    three labels and gives a confidence above 0 and at most 1. A copied template
    ("positive | negative | neutral"), an unknown word or a missing confidence is NOT turned into
    a neutral vote."""
    raw = str(result.get("sentiment", "")).strip().lower().strip(" .!\"'")
    label = raw if raw in _LABELS else None
    confidence = result.get("confidence")
    if confidence is None:
        return "neutral", 0.0, False
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        return "neutral", 0.0, False
    if label is None or not (0.0 < conf <= 1.0):
        return "neutral", 0.0, False
    return label, conf, True


def _related_block_for(
    ticker: str,
    article: Dict[str, Any],
    as_of: Optional[str],
):
    """
    Related earlier coverage from src/rag/news_memory.py.
    Returns (prompt_block, number_of_items). Never raises: if the memory is
    missing, empty or broken, scoring proceeds exactly as before.
    """
    try:
        from src.rag.news_memory import (
            format_related_block,
            retrieve_related,
        )

        items = retrieve_related(article, as_of=as_of, k=2)
        return format_related_block(ticker, items), len(items)
    except Exception as exc:
        logger.warning("news memory unavailable: %s", exc)
        return "", 0


def score_article(
    ticker: str,
    article: Dict[str, Any],
    model_name: str = DEFAULT_SENTIMENT_MODEL,
    use_memory: bool = False,
    as_of: Optional[str] = None,
) -> Dict[str, Any]:
    """Score one discovered news article.

    use_memory=True adds up to two related headlines (same batch or earlier
    days, any ticker) to the prompt as background. Default False keeps the
    old behaviour for every other caller.
    """

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

    related_block, related_count = ("", 0)

    if use_memory:
        related_block, related_count = _related_block_for(
            ticker,
            article,
            as_of,
        )

    prompt = SENTIMENT_PROMPT.format(
        ticker=ticker,
        source=source,
        headline=article.get("title", ""),
        summary=article.get("description", ""),
        related_block=related_block,
    )

    result: Dict[str, Any] = {}
    valid = False
    sentiment, confidence = "neutral", 0.0

    for attempt in (1, 2):                    # one retry: a small model sometimes returns junk
        try:
            response = ollama.generate(
                model=model_name,
                prompt=prompt,
                options={
                    "temperature": 0.1,
                    "num_predict": 150,
                },
            )
            result = _safe_parse_json(response.get("response", ""))
        except Exception as exc:
            logger.error(
                "Sentiment scoring failed for %s: %s",
                ticker,
                article.get("title", "")[:80],
            )
            result = {"reasoning": f"error: {exc}"}
            break                              # a failing call is not retried

        sentiment, confidence, valid = _validate_answer(result)
        if valid:
            break

    scored_article = dict(article)
    scored_article["sentiment"] = sentiment
    scored_article["confidence"] = confidence
    scored_article["valid"] = valid
    scored_article["reasoning"] = str(result.get("reasoning", ""))

    if use_memory:
        scored_article["related_count"] = related_count

    return scored_article


def score_articles(
    ticker: str,
    articles: List[Dict[str, Any]],
    model_name: str = DEFAULT_SENTIMENT_MODEL,
    use_memory: bool = False,
    as_of: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Score all discovered articles for one ticker."""

    scored = []

    for article in articles:
        scored_article = score_article(
            ticker,
            article,
            model_name=model_name,
            use_memory=use_memory,
            as_of=as_of,
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

    # Answers the model failed to give properly (valid == False) are not votes.
    invalid = sum(1 for a in scored_articles if a.get("valid") is False)
    scored_articles = [a for a in scored_articles if a.get("valid") is not False]

    if not scored_articles:
        return {
            "overall": "neutral",
            "score": 0.0,
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "total": 0,
            "invalid": invalid,
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
        "invalid": invalid,
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