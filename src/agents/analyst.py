"""
src/agents/analyst.py

LLM signal is INVEST / HOLD, not BUY / SELL / HOLD.

The LLM determines whether a genuine opportunity exists.

Trade direction is determined separately from price trend data by the
RiskManager.
"""

import json
import logging
import os
from typing import Dict, Optional, Any, List

try:
    import ollama
except ImportError:
    ollama = None


logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(
    "raats.agent.analyst"
)


DEFAULT_ANALYST_MODEL = os.environ.get(
    "RAATS_ANALYST_MODEL",
    "llama3",
)


ANALYST_PROMPT = """You are a financial analyst.

Given the following market data for {ticker}:

- Close price: {close}
- SMA 10: {sma_10}
- RSI: {rsi}
- Sentiment score: {sentiment}

Recent discovered news:

{news_context}

Decide only whether this is a genuine trading OPPORTUNITY worth acting on
right now, or whether conditions do not justify a trade.

Use the market data, sentiment, and relevant news as supporting evidence.

Do NOT pick a direction.
Do NOT say BUY or SELL.

Trade direction is determined separately from price trend data.

If the news is unrelated, weak, duplicated, or unclear, do not treat it
as strong evidence for an opportunity.

Respond ONLY in valid JSON, no extra text.

Keep "justification" to ONE short sentence, under 20 words:

{{
  "signal": "INVEST | HOLD",
  "confidence": <0-1 float>,
  "justification": "<one short sentence, max 20 words>"
}}"""


def _safe_parse_json(
    raw_text: str,
) -> Dict:

    text = raw_text.strip()

    try:
        return json.loads(text)

    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if (
        start != -1
        and end != -1
        and end > start
    ):
        try:
            return json.loads(
                text[start:end + 1]
            )

        except json.JSONDecodeError:
            pass

    logger.warning(
        "Could not parse analyst output as JSON "
        "(%d chars): %s",
        len(text),
        text,
    )

    return {
        "signal": "HOLD",
        "confidence": 0.0,
        "justification": (
            "Failed to parse LLM output."
        ),
    }


def _normalize_signal(
    raw_signal: str,
) -> str:

    s = (
        raw_signal or ""
    ).strip().upper()

    if s in (
        "INVEST",
        "BUY",
        "SELL",
    ):
        return "INVEST"

    return "HOLD"


def _format_news_item(
    item: Dict[str, Any],
    source: str,
) -> str:

    if not isinstance(item, dict):
        return ""

    title = (
        item.get("title")
        or item.get("headline")
        or ""
    )

    publisher = (
        item.get("publisher")
        or item.get("source", {}).get("name")
        if isinstance(
            item.get("source"),
            dict,
        )
        else item.get("source")
    )

    published = (
        item.get("publishedAt")
        or item.get("published")
        or item.get("published_at")
        or ""
    )

    description = (
        item.get("description")
        or item.get("summary")
        or item.get("content")
        or ""
    )

    if not title:
        return ""

    line = (
        f"- [{source}] {title}"
    )

    if publisher:
        line += (
            f" | Source: {publisher}"
        )

    if published:
        line += (
            f" | Date: {published}"
        )

    if description:
        description = str(
            description
        ).strip()[:250]

        line += (
            f" | Summary: {description}"
        )

    return line


def _build_news_context(
    discovery_news: Optional[
        Dict[str, List[Dict[str, Any]]]
    ],
) -> str:

    if not discovery_news:
        return (
            "No discovered news available."
        )

    lines = []

    for item in discovery_news.get(
        "yfinance_news",
        [],
    ):

        line = _format_news_item(
            item,
            "Yahoo Finance",
        )

        if line:
            lines.append(line)

    for item in discovery_news.get(
        "google_news",
        [],
    ):

        line = _format_news_item(
            item,
            "Google News",
        )

        if line:
            lines.append(line)

    if not lines:
        return (
            "No usable discovered news available."
        )

    return "\n".join(
        lines[:10]
    )


def ollama_analyze(
    prompt: str,
    model_name: Optional[str] = None,
) -> str:

    if ollama is None:
        raise ImportError(
            "The 'ollama' package is required. "
            "Install with: pip install ollama"
        )

    model_name = (
        model_name
        or DEFAULT_ANALYST_MODEL
    )

    response = ollama.generate(
        model=model_name,
        prompt=prompt,
        options={
            "temperature": 0.2,
            "num_predict": 200,
        },
    )

    return response.get(
        "response",
        "",
    )


def analyze_market(
    state: dict,
    model_name: Optional[str] = None,
) -> dict:

    market_data = state["market_data"]

    sentiment = state["sentiment"]

    ticker = state.get(
        "ticker",
        "UNKNOWN",
    )

    model_name = (
        model_name
        or DEFAULT_ANALYST_MODEL
    )

    discovery_news = state.get(
        "discovery_news",
        {},
    )

    news_context = _build_news_context(
        discovery_news
    )

    prompt = ANALYST_PROMPT.format(
        ticker=ticker,
        close=market_data["close"],
        sma_10=market_data["sma_10"],
        rsi=market_data["rsi"],
        sentiment=sentiment,
        news_context=news_context,
    )

    try:

        raw_analysis = ollama_analyze(
            prompt,
            model_name=model_name,
        )

        result = _safe_parse_json(
            raw_analysis
        )

    except Exception as exc:

        logger.error(
            "Analyst node failed for %s: %s",
            ticker,
            exc,
        )

        result = {
            "signal": "HOLD",
            "confidence": 0.0,
            "justification": (
                f"Error during analysis: {exc}"
            ),
        }

    state["llm_analysis"] = result.get(
        "justification",
        "",
    )

    state["signal"] = _normalize_signal(
        result.get(
            "signal",
            "HOLD",
        )
    )

    state["confidence"] = result.get(
        "confidence",
        0.0,
    )

    state["analyst_model"] = model_name

    return state