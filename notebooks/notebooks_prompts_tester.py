"""
notebooks/prompts_tester.py

Runs Templates A, B, and C (see Claude_Suggestions_Week2.md Section 1)
against a few sample market snapshots and prints the raw + parsed output
so you can compare quality and consistency.

Run:
    python prompts_tester.py
"""

import json
import logging
import time

try:
    import ollama
except ImportError:
    ollama = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("prompts_tester")


TEMPLATE_A = """You are a trading signal generator. Given the market data below, respond with
ONLY one word: BUY, SELL, or HOLD.

Ticker: {ticker}
Price: {price}
24h Change: {change_pct}%
RSI(14): {rsi}
Volume vs 20d avg: {volume_ratio}x

Signal:"""

TEMPLATE_B = """You are a trading strategist choosing between candidate strategies based on
current market conditions.

Market snapshot:
- Ticker: {ticker}
- Price: {price}
- Trend (20/50 SMA): {trend}
- RSI(14): {rsi}
- ADX(14): {adx}
- Recent volatility (ATR%): {atr_pct}

Candidate strategies: mean_reversion, momentum, breakout

Respond ONLY in valid JSON:
{{
  "selected_strategy": "<name>",
  "signal": "BUY | SELL | HOLD",
  "confidence": <0-1 float>,
  "reasoning": "<1-2 sentences>"
}}"""

TEMPLATE_C = """You are a trading analyst. Combine the technical snapshot with the retrieved
news context to produce a signal.

Technical snapshot:
{technical_summary}

Retrieved news context:
{retrieved_context}

Respond ONLY in valid JSON:
{{
  "signal": "BUY | SELL | HOLD",
  "confidence": <0-1 float>,
  "technical_reasoning": "<short>",
  "sentiment_reasoning": "<short>"
}}"""


SAMPLE_SNAPSHOTS = [
    {
        "ticker": "AAPL",
        "price": 187.32,
        "change_pct": 1.2,
        "rsi": 58.4,
        "volume_ratio": 1.1,
        "trend": "uptrend",
        "adx": 27.1,
        "atr_pct": 1.8,
    },
    {
        "ticker": "TSLA",
        "price": 214.10,
        "change_pct": -3.4,
        "rsi": 32.7,
        "volume_ratio": 2.3,
        "trend": "downtrend",
        "adx": 41.2,
        "atr_pct": 3.9,
    },
]


def run_template(model_name: str, template: str, data: dict) -> str:
    prompt = template.format(**data)
    start = time.time()
    response = ollama.generate(model=model_name, prompt=prompt, options={"temperature": 0.2})
    elapsed = time.time() - start
    logger.info("Model=%s | %.2fs", model_name, elapsed)
    return response.get("response", "")


def main(model_name: str = "mistral"):
    if ollama is None:
        print("The 'ollama' package is not installed. Run: pip install ollama")
        return

    for snapshot in SAMPLE_SNAPSHOTS:
        print(f"\n{'=' * 60}\nTicker: {snapshot['ticker']}\n{'=' * 60}")

        print("\n--- Template A (direct signal) ---")
        print(run_template(model_name, TEMPLATE_A, snapshot).strip())

        print("\n--- Template B (strategy selection) ---")
        print(run_template(model_name, TEMPLATE_B, snapshot).strip())

        print("\n--- Template C (sentiment-aware, no real context yet) ---")
        c_data = {
            "technical_summary": f"{snapshot['ticker']} price {snapshot['price']}, "
                                  f"trend {snapshot['trend']}, RSI {snapshot['rsi']}",
            "retrieved_context": "No news retrieval wired up yet (Week 3 task).",
        }
        print(run_template(model_name, TEMPLATE_C, c_data).strip())


if __name__ == "__main__":
    main()
