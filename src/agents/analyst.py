"""
src/agents/analyst.py

LLM signal is now INVEST / HOLD, not BUY / SELL / HOLD.

Rationale: gradient (not the LLM) determines trade direction (see
src/risk/risk_manager.py's resolve_direction). Asking the LLM to guess a
side (BUY/SELL) was misleading - that guess was being silently discarded
whenever it disagreed with the gradient, which is confusing to read in logs
and doesn't reflect what the LLM's output is actually used for. INVEST/HOLD
matches its real role: confirm there's a genuine opportunity worth trading
(informed by market data + sentiment), and let deterministic Python
(gradient + risk_manager) handle direction, sizing, and execution.
"""

import json
import logging
import os
from typing import Dict, Optional

try:
    import ollama
except ImportError:
    ollama = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("raats.agent.analyst")

DEFAULT_ANALYST_MODEL = os.environ.get("RAATS_ANALYST_MODEL", "llama3")

ANALYST_PROMPT = """You are a financial analyst. Given the following market data for {ticker}:
- Close price: {close}
- SMA 10: {sma_10}
- RSI: {rsi}
- Sentiment score: {sentiment}

Decide only whether this is a genuine trading OPPORTUNITY worth acting on
right now, or whether conditions do not justify a trade. Do NOT pick a
direction - that is determined separately from price trend data.

Respond ONLY in valid JSON, no extra text. Keep "justification" to ONE
short sentence, under 20 words:
{{
  "signal": "INVEST | HOLD",
  "confidence": <0-1 float>,
  "justification": "<one short sentence, max 20 words>"
}}"""


def _safe_parse_json(raw_text: str) -> Dict:
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
    logger.warning("Could not parse analyst output as JSON (%d chars): %s", len(text), text)
    return {"signal": "HOLD", "confidence": 0.0, "justification": "Failed to parse LLM output."}


def _normalize_signal(raw_signal: str) -> str:
    """Map legacy/unexpected model output onto INVEST/HOLD, so a model that
    ignores the prompt and still says BUY/SELL doesn't silently become an
    unrecognized value downstream.
    """
    s = (raw_signal or "").strip().upper()
    if s in ("INVEST", "BUY", "SELL"):
        return "INVEST"
    return "HOLD"


def ollama_analyze(prompt: str, model_name: Optional[str] = None) -> str:
    if ollama is None:
        raise ImportError("The 'ollama' package is required. Install with: pip install ollama")

    model_name = model_name or DEFAULT_ANALYST_MODEL

    response = ollama.generate(
        model=model_name,
        prompt=prompt,
        options={"temperature": 0.2, "num_predict": 200},
    )
    return response.get("response", "")


def analyze_market(state: dict, model_name: Optional[str] = None) -> dict:
    market_data = state["market_data"]
    sentiment = state["sentiment"]
    ticker = state.get("ticker", "UNKNOWN")
    model_name = model_name or DEFAULT_ANALYST_MODEL

    prompt = ANALYST_PROMPT.format(
        ticker=ticker,
        close=market_data["close"],
        sma_10=market_data["sma_10"],
        rsi=market_data["rsi"],
        sentiment=sentiment,
    )

    try:
        raw_analysis = ollama_analyze(prompt, model_name=model_name)
        result = _safe_parse_json(raw_analysis)
    except Exception as exc:
        logger.error("Analyst node failed for %s: %s", ticker, exc)
        result = {
            "signal": "HOLD",
            "confidence": 0.0,
            "justification": f"Error during analysis: {exc}",
        }

    state["llm_analysis"] = result.get("justification", "")
    state["signal"] = _normalize_signal(result.get("signal", "HOLD"))
    state["confidence"] = result.get("confidence", 0.0)
    state["analyst_model"] = model_name
    return state
