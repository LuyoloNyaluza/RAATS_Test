
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

# Override via environment variable for quick A/B testing without code
# changes: set RAATS_ANALYST_MODEL=mistral before running trading_loop.py.
DEFAULT_ANALYST_MODEL = os.environ.get("RAATS_ANALYST_MODEL", "llama3")

ANALYST_PROMPT = """You are a financial analyst. Given the following market data for {ticker}:
- Close price: {close}
- SMA 10: {sma_10}
- RSI: {rsi}
- Sentiment score: {sentiment}

Respond ONLY in valid JSON, no extra text:
{{
  "signal": "BUY | SELL | HOLD",
  "confidence": <0-1 float>,
  "justification": "<one or two concise sentences>"
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
    logger.warning("Could not parse analyst output as JSON: %s", text[:150])
    return {"signal": "HOLD", "confidence": 0.0, "justification": "Failed to parse LLM output."}


def ollama_analyze(prompt: str, model_name: Optional[str] = None) -> str:
    if ollama is None:
        raise ImportError("The 'ollama' package is required. Install with: pip install ollama")

    model_name = model_name or DEFAULT_ANALYST_MODEL

    response = ollama.generate(
        model=model_name,
        prompt=prompt,
        options={"temperature": 0.2},
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
    state["signal"] = result.get("signal", "HOLD")
    state["confidence"] = result.get("confidence", 0.0)
    state["analyst_model"] = model_name   # NEW: record which model produced this, for A/B comparison
    return state