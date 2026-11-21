
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
from datetime import date
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
    "gemma3:4b",
)


ANALYST_PROMPT = """You are an objective financial analyst evaluating whether a stock presents a genuine trading opportunity.

Given the following market data for {ticker}:

- Analysis reference date: {as_of_date}
- Close price: {close}
- SMA 10: {sma_10}
- RSI: {rsi}
- Sentiment score: {sentiment}

Recent discovered news:
{news_context}

Historical Context & Prior Signals:
{history_block}

### Evaluation Rules:

1. **Opportunity Assessment**:
   Decide whether the available evidence identifies a genuine opportunity worth further evaluation by the trading system.

   INVEST means there is sufficient evidence of a meaningful opportunity for the RiskManager to evaluate. It does not mean that a trade must be executed.

   HOLD means the available evidence is insufficient, weak, conflicting, or does not justify further trade evaluation.

2. **Fundamental and News Evidence**:
   Consider meaningful developments such as:
   - Revenue growth, improved earnings, and positive earnings surprises.
   - Increased guidance, improving forecasts, and stronger business outlook.
   - Major contracts, increased demand, successful products, and regulatory approvals.
   - Declining earnings, reduced guidance, customer losses, dilution, regulatory penalties, and operational problems.

   Give greater weight to specific, financially meaningful developments than routine announcements or unsupported opinions.

3. **Market Indicators**:
   Assess Close price, SMA 10, and RSI together with the available evidence.

   - Price above SMA 10 can indicate positive short-term price behaviour.
   - Price below SMA 10 can indicate negative short-term price behaviour.
   - RSI below 30 can indicate oversold conditions.
   - RSI above 70 can indicate overbought conditions.

   These indicators provide context, not automatic INVEST or HOLD decisions. An oversold condition does not automatically invalidate a genuine opportunity, and an overbought condition does not automatically justify one.

4. **Sentiment Evaluation**:
   Consider sentiment alongside the actual news and market data. Do not treat a positive or negative sentiment score as sufficient evidence on its own.

5. **Evidence Quality**:
   Objectively weigh relevant evidence. If news is unrelated, weak, duplicated, stale, speculative, or unclear, do not treat it as strong evidence. Avoid overstating the market impact of headlines.

6. **News Recency**:
   Compare publication dates against the analysis reference date. Give greater weight to recent, relevant developments. Older news is historical context, not evidence of a current opportunity unless supported by new developments.

7. **Historical Context Utilization**:
   Cross-reference historical context to identify previous false starts and avoid blindly chasing outdated setups. Historical signals must not override genuinely improved current conditions.

8. **Strict Constraints**:
   - Do NOT pick a trade direction.
   - Do NOT say BUY or SELL.
   - Trade direction is determined separately by the RiskManager using price trend data.
   - INVEST only identifies an opportunity for further evaluation.

9. **Confidence Assessment**:
   Confidence should reflect the strength, relevance, and consistency of the available evidence. Do not express high confidence when evidence is incomplete or conflicting.

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

    # Use the simulation date when available.
    # Otherwise, use the current system date.
    as_of_date = (
        state.get("simulate_date")
        or date.today().isoformat()
    )

    discovery_news = state.get(
        "discovery_news",
        {},
    )

    news_context = _build_news_context(
        discovery_news
    )

    # Earlier days' coverage of this ticker, kept separate from live news.
    # Use the same reference date as the analyst prompt.
    history_block = ""

    try:
        from src.rag.news_memory import (
            format_history_block,
            recent_for_ticker,
        )

        history_block = format_history_block(
            ticker,
            recent_for_ticker(
                ticker,
                as_of=as_of_date,
            ),
        )

    except Exception as exc:
        logger.warning(
            "News history unavailable for %s: %s",
            ticker,
            exc,
        )

    prompt = ANALYST_PROMPT.format(
        as_of_date=as_of_date,
        ticker=ticker,
        close=market_data["close"],
        sma_10=market_data["sma_10"],
        rsi=market_data["rsi"],
        sentiment=sentiment,
        news_context=news_context,
        history_block=history_block,
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
