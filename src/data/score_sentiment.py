import json
import logging
from typing import Dict, Any, List

try:
    import ollama
except ImportError:
    ollama = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("raats.data.score_sentiment")


SENTIMENT_PROMPT = """Rate the financial sentiment of this news headline for the given
stock ticker. Respond ONLY in valid JSON, no extra text:

Ticker: {ticker}
Headline: {headline}
Summary: {summary}

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
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    logger.warning("Could not parse sentiment output: %s", text[:150])
    return {"sentiment": "neutral", "confidence": 0.0, "reasoning": "parse failed"}


def score_article(ticker: str, article: Dict[str, Any], model_name: str = "mistral") -> Dict[str, Any]:
    """Score a single article's sentiment using a local Ollama model."""
    if ollama is None:
        raise ImportError("The 'ollama' package is required. Install with: pip install ollama")

    prompt = SENTIMENT_PROMPT.format(
        ticker=ticker,
        headline=article.get("title", ""),
        summary=article.get("description", ""),
    )
    try:
        response = ollama.generate(model=model_name, prompt=prompt, options={"temperature": 0.1})
        result = _safe_parse_json(response.get("response", ""))
    except Exception as exc:
        logger.error("Sentiment scoring failed for '%s': %s", article.get("title", "")[:50], exc)
        result = {"sentiment": "neutral", "confidence": 0.0, "reasoning": f"error: {exc}"}

    return {**article, **result}


def score_articles(ticker: str, articles: List[Dict[str, Any]], model_name: str = "mistral") -> List[Dict[str, Any]]:
    """Score a list of articles for one ticker."""
    scored = []
    for article in articles:
        scored_article = score_article(ticker, article, model_name=model_name)
        scored.append(scored_article)
        logger.info(
            "%s | %s | %s",
            ticker, scored_article["sentiment"], article.get("title", "")[:60],
        )
    return scored


def summarize_ticker_sentiment(scored_articles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-article sentiment into a simple ticker-level summary."""
    if not scored_articles:
        return {"overall": "neutral", "positive": 0, "negative": 0, "neutral": 0, "total": 0}

    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for a in scored_articles:
        s = a.get("sentiment", "neutral")
        counts[s] = counts.get(s, 0) + 1

    total = len(scored_articles)
    if counts["positive"] > counts["negative"]:
        overall = "positive"
    elif counts["negative"] > counts["positive"]:
        overall = "negative"
    else:
        overall = "neutral"

    return {"overall": overall, **counts, "total": total}


if __name__ == "__main__":
    sample_articles = [
        {"title": "Apple shares surge on record iPhone sales", "description": "Strong quarterly results beat expectations."},
        {"title": "Apple faces regulatory scrutiny in EU", "description": "New antitrust investigation announced."},
    ]
    scored = score_articles("AAPL", sample_articles, model_name="mistral")
    print(json.dumps(scored, indent=2))
    print("\nSummary:", summarize_ticker_sentiment(scored))