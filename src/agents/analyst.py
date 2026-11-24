
"""
src/agents/analyst.py

LLM signal is INVEST / HOLD, not BUY / SELL / HOLD.

The LLM determines whether a genuine opportunity exists.
Trade direction is determined separately from price trend data by the RiskManager.
"""

import json
import re
import logging
import os
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Optional, Any, List, Tuple

try:
    import ollama
except ImportError:
    ollama = None


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("raats.agent.analyst")


DEFAULT_ANALYST_MODEL = os.environ.get(
    "RAATS_ANALYST_MODEL",
    "llama3",
)

NEWS_LOOKBACK_DAYS = 7

VALID_NEWS_TONES = {
    "positive",
    "negative",
    "mixed",
    "none",
}


ANALYST_PROMPT = """You are an objective financial analyst evaluating whether a stock presents a genuine trading opportunity.

Given the following market data for {ticker}:

- Analysis reference date: {as_of_date}
- Close price: {close}
- SMA 10: {sma_10}
- RSI: {rsi}
- Sentiment score: {sentiment}

Eligible recent news:
{news_context}

Number of date-eligible news articles supplied by Python: {eligible_news_count}

Historical Context & Prior Signals:
{history_block}

### Evaluation Rules

1. OPPORTUNITY ASSESSMENT

Your task is to determine whether sufficient evidence exists to justify further evaluation by the RiskManager.

- INVEST means a genuine opportunity exists and should be evaluated further.
- HOLD means evidence is insufficient, weak, conflicting, or does not justify further evaluation.
- Default to HOLD when uncertain.

INVEST does not guarantee trade execution.

2. MANDATORY NEWS EVIDENCE

INVEST requires at least ONE strong, relevant, recent and financially meaningful news development.

The supplied eligible news has already been filtered by Python to the seven calendar days ending on the analysis reference date.

Relevant developments may include:
- Material revenue or earnings growth or deterioration.
- Earnings surprises or significant changes in financial guidance.
- Major contracts, customer wins or losses.
- Significant changes in demand or business outlook.
- Important regulatory approvals, penalties or restrictions.
- Material dilution or financing developments.
- Significant operational disruptions or product failures.

A competitor's news may qualify only when there is a clear, specific and material impact on the ticker being analysed.

3. NEWS THAT DOES NOT QUALIFY

Do not count:
- Routine company announcements without material impact.
- Event reminders, webcasts and scheduled presentations.
- Executive appointments without demonstrated significance.
- Analyst opinions without new supporting facts.
- Rumours, speculation or unsupported claims.
- Unrelated company or industry news.
- Duplicate coverage of the same development.
- News without sufficient information to establish its relevance or significance.

Count distinct meaningful developments, not the number of articles repeating the same story.

If no meaningful development is identified, relevant_news_count MUST be 0 and the signal MUST be HOLD.

4. NEWS TONE

Classify the overall tone of the relevant developments:

- positive: predominantly favourable developments.
- negative: predominantly unfavourable developments.
- mixed: meaningful positive and negative developments.
- none: no qualifying relevant developments.

If relevant_news_count is 0, news_tone MUST be "none".

5. MARKET INDICATORS

Assess Close price, SMA 10 and RSI as supporting context.

- Price above SMA 10 can indicate positive short-term behaviour.
- Price below SMA 10 can indicate negative short-term behaviour.
- RSI below 30 can indicate oversold conditions.
- RSI above 70 can indicate overbought conditions.

Indicators must NEVER independently justify INVEST.

An oversold condition does not automatically invalidate a genuine opportunity. An overbought condition does not automatically justify one.

6. SENTIMENT

Consider sentiment alongside the actual news and market data.

Positive or negative sentiment alone is not sufficient evidence for INVEST.

7. EVIDENCE QUALITY

Weigh relevance, financial significance, credibility and consistency.

If evidence is weak, unclear, conflicting, duplicated or speculative, choose HOLD.

Do not exaggerate the market impact of a headline.

8. HISTORICAL CONTEXT

Use historical context to identify previous false starts and avoid chasing outdated setups.

Historical signals and older news are background information only. They cannot satisfy the mandatory current-news requirement.

9. STRICT CONSTRAINTS

- Return only INVEST or HOLD.
- Never return BUY or SELL.
- Do not select trade direction.
- Do not calculate position size.
- Do not determine stop-loss or take-profit.
- The RiskManager handles trade direction and risk separately.

10. CONFIDENCE

Confidence must reflect the strength and consistency of the evidence.

- INVEST: use 0.60 to 0.90 only when mandatory news evidence is strong.
- HOLD with no relevant news: normally 0.80 to 0.95.
- HOLD with weak or conflicting evidence: normally 0.50 to 0.70.

Do not use high confidence to disguise uncertainty.

11. OUTPUT FORMAT

Return ONLY valid JSON. No Markdown or additional text.

The justification must be one short sentence under 20 words.

Use exactly these five fields:

{{
  "relevant_news_count": 0,
  "news_tone": "none",
  "signal": "HOLD",
  "confidence": 0.90,
  "justification": "No relevant recent financial development supports further evaluation."
}}
"""


_THINK = re.compile(
    r"<think>.*?(?:</think>|$)",
    re.S | re.I,
)


def _strip_think(text: str) -> str:
    """Remove reasoning blocks before attempting JSON parsing."""
    return _THINK.sub("", text or "").strip()


def _safe_parse_json(raw_text: str) -> Dict:

    text = _strip_think(raw_text)

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result

    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(text[start:end + 1])
            if isinstance(result, dict):
                return result

        except json.JSONDecodeError:
            pass

    logger.warning(
        "Could not parse analyst output as JSON (%d chars): %s",
        len(text),
        text,
    )

    return {
        "relevant_news_count": 0,
        "news_tone": "none",
        "signal": "HOLD",
        "confidence": 0.0,
        "justification": "Failed to parse LLM output.",
    }


def _normalize_signal(raw_signal: str) -> str:
    """Accept only the analyst's two permitted signals."""

    signal = str(raw_signal or "").strip().upper()

    if signal == "INVEST":
        return "INVEST"

    if signal == "HOLD":
        return "HOLD"

    logger.warning(
        "Invalid analyst signal '%s'. Defaulting to HOLD.",
        signal,
    )

    return "HOLD"


def _parse_news_date(value: Any) -> Optional[date]:
    """Parse common Yahoo Finance and Google News publication dates."""

    if value is None or value == "":
        return None

    # Unix timestamps, including Yahoo providerPublishTime.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(
                value,
                tz=timezone.utc,
            ).date()
        except (ValueError, OSError, OverflowError):
            return None

    value = str(value).strip()

    if not value:
        return None

    # ISO date or datetime.
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).date()
    except ValueError:
        pass

    # RFC publication dates commonly used by Google News.
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.date()
    except (TypeError, ValueError, OverflowError):
        pass

    return None


def _get_publication_date(item: Dict[str, Any]) -> Optional[date]:
    """Extract publication date from supported news fields."""

    for key in (
        "publishedAt",
        "published",
        "published_at",
        "providerPublishTime",
    ):
        published_date = _parse_news_date(item.get(key))

        if published_date:
            return published_date

    return None


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

    if not title:
        return ""

    source_data = item.get("source")

    if isinstance(source_data, dict):
        publisher = (
            item.get("publisher")
            or source_data.get("name")
        )
    else:
        publisher = (
            item.get("publisher")
            or source_data
        )

    published = (
        item.get("publishedAt")
        or item.get("published")
        or item.get("published_at")
        or item.get("providerPublishTime")
        or ""
    )

    description = (
        item.get("description")
        or item.get("summary")
        or item.get("content")
        or ""
    )

    line = f"- [{source}] {title}"

    if publisher:
        line += f" | Source: {publisher}"

    if published:
        line += f" | Date: {published}"

    if description:
        description = str(description).strip()[:250]
        line += f" | Summary: {description}"

    return line


def _build_news_context(
    discovery_news: Optional[
        Dict[str, List[Dict[str, Any]]]
    ],
    as_of_date: str,
) -> Tuple[str, int]:
    """
    Filter current news to the seven calendar days ending on as_of_date.

    Articles without a valid publication date are excluded.
    Duplicate headlines are removed.
    Returns the formatted context and the number of eligible articles.
    """

    try:
        reference_date = date.fromisoformat(
            str(as_of_date)[:10]
        )
    except (TypeError, ValueError):
        logger.warning(
            "Invalid analysis reference date '%s'. Using today's date.",
            as_of_date,
        )
        reference_date = date.today()

    start_date = date.fromordinal(
        reference_date.toordinal() - (NEWS_LOOKBACK_DAYS - 1)
    )

    if not discovery_news:
        return "No eligible recent news available.", 0

    lines = []
    seen_headlines = set()

    sources = (
        ("yfinance_news", "Yahoo Finance"),
        ("google_news", "Google News"),
    )

    for key, source_name in sources:

        for item in discovery_news.get(key, []):

            if not isinstance(item, dict):
                continue

            published_date = _get_publication_date(item)

            # Unknown dates and dates outside the window are excluded.
            if published_date is None:
                continue

            if not start_date <= published_date <= reference_date:
                continue

            title = (
                item.get("title")
                or item.get("headline")
                or ""
            )

            normalized_title = re.sub(
                r"\s+",
                " ",
                str(title).strip().lower(),
            )

            if not normalized_title:
                continue

            if normalized_title in seen_headlines:
                continue

            seen_headlines.add(normalized_title)

            line = _format_news_item(
                item,
                source_name,
            )

            if line:
                lines.append(line)

    if not lines:
        return "No eligible recent news available.", 0

    return "\n".join(lines[:10]), len(lines)


def ollama_analyze(
    prompt: str,
    model_name: Optional[str] = None,
) -> str:

    if ollama is None:
        raise ImportError(
            "The 'ollama' package is required. "
            "Install with: pip install ollama"
        )

    model_name = model_name or DEFAULT_ANALYST_MODEL

    response = ollama.generate(
        model=model_name,
        prompt=prompt,
        options={
            "temperature": 0.2,
            "num_predict": 300,
        },
    )

    return response.get("response", "")


def _validate_analyst_result(
    result: Dict[str, Any],
    eligible_news_count: int,
) -> Dict[str, Any]:
    """
    Validate analyst output and enforce the mandatory news condition.
    """

    # Validate relevant_news_count.
    raw_count = result.get("relevant_news_count", 0)

    if (
        isinstance(raw_count, bool)
        or not isinstance(raw_count, int)
        or raw_count < 0
        or raw_count > eligible_news_count
    ):
        logger.warning(
            "Invalid relevant_news_count '%s'. Defaulting to zero.",
            raw_count,
        )
        relevant_news_count = 0
    else:
        relevant_news_count = raw_count

    # Validate news tone.
    news_tone = str(
        result.get("news_tone", "none")
    ).strip().lower()

    if news_tone not in VALID_NEWS_TONES:
        logger.warning(
            "Invalid analyst news_tone '%s'. Defaulting to none.",
            news_tone,
        )
        news_tone = "none"

    # Validate signal.
    signal = _normalize_signal(
        result.get("signal", "HOLD")
    )

    # Validate confidence.
    try:
        confidence = float(
            result.get("confidence", 0.0)
        )

        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence outside 0-1 range.")

    except (TypeError, ValueError):
        logger.warning(
            "Invalid analyst confidence. Defaulting to 0."
        )
        confidence = 0.0

    justification = str(
        result.get("justification", "")
    ).strip()

    # Enforce consistency between count and tone.
    if relevant_news_count == 0:
        news_tone = "none"

    elif news_tone == "none":
        logger.warning(
            "Analyst reported relevant news but returned tone 'none'. "
            "Forcing HOLD."
        )
        signal = "HOLD"

    # Mandatory news condition: no relevant news means no INVEST.
    if relevant_news_count == 0 and signal == "INVEST":
        logger.warning(
            "Analyst contract violation: INVEST returned without "
            "relevant news. Forcing HOLD."
        )
        signal = "HOLD"

    return {
        "relevant_news_count": relevant_news_count,
        "news_tone": news_tone,
        "signal": signal,
        "confidence": confidence,
        "justification": justification,
    }


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

    # Use simulation date when available.
    # Otherwise, use the current system date.
    as_of_date = str(
        state.get("simulate_date")
        or date.today().isoformat()
    )[:10]

    discovery_news = state.get(
        "discovery_news",
        {},
    )

    # Python enforces the seven-day news window before the LLM sees news.
    news_context, eligible_news_count = _build_news_context(
        discovery_news,
        as_of_date,
    )

    state["eligible_news_count"] = eligible_news_count

    # Historical news is kept separate from eligible current news.
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
        eligible_news_count=eligible_news_count,
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
            "relevant_news_count": 0,
            "news_tone": "none",
            "signal": "HOLD",
            "confidence": 0.0,
            "justification": (
                f"Error during analysis: {exc}"
            ),
        }

    # Validate the complete response and enforce the news requirement.
    result = _validate_analyst_result(
        result,
        eligible_news_count,
    )

    state["llm_analysis"] = result["justification"]

    state["signal"] = result["signal"]

    state["confidence"] = result["confidence"]

    state["relevant_news_count"] = result["relevant_news_count"]

    state["news_tone"] = result["news_tone"]

    state["analyst_model"] = model_name

    return state
