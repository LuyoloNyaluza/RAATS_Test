"""
notebooks/model_comparison.py

Benchmarks a set of local Ollama models on the Template B (strategy
selection) prompt: latency, JSON validity, and basic consistency across
repeated runs on the same input.

Run:
    python model_comparison.py
"""

import json
import logging
import time
from statistics import mean, stdev

try:
    import ollama
except ImportError:
    ollama = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("model_comparison")

MODELS_TO_TEST = ["mistral", "llama3", "phi3"]  # edit based on what you've pulled

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

SAMPLE = {
    "ticker": "AAPL",
    "price": 187.32,
    "trend": "uptrend",
    "rsi": 58.4,
    "adx": 27.1,
    "atr_pct": 1.8,
}


def try_parse_json(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def benchmark_model(model_name: str, runs: int = 3):
    prompt = TEMPLATE_B.format(**SAMPLE)
    latencies = []
    signals = []
    valid_json_count = 0

    for i in range(runs):
        start = time.time()
        try:
            response = ollama.generate(model=model_name, prompt=prompt, options={"temperature": 0.2})
        except Exception as exc:
            logger.error("Model %s failed on run %d: %s", model_name, i + 1, exc)
            continue
        elapsed = time.time() - start
        latencies.append(elapsed)

        raw = response.get("response", "")
        parsed = try_parse_json(raw)
        if parsed:
            valid_json_count += 1
            signals.append(parsed.get("signal", "UNKNOWN"))
        else:
            signals.append("PARSE_FAILED")

    if not latencies:
        return {"model": model_name, "status": "failed", "error": "all runs failed"}

    consistency = len(set(signals)) == 1

    return {
        "model": model_name,
        "status": "ok",
        "avg_latency_sec": round(mean(latencies), 2),
        "latency_stdev": round(stdev(latencies), 2) if len(latencies) > 1 else 0.0,
        "valid_json_rate": f"{valid_json_count}/{runs}",
        "signals_seen": signals,
        "consistent_signal": consistency,
    }


def main():
    if ollama is None:
        print("The 'ollama' package is not installed. Run: pip install ollama")
        return

    results = []
    for model_name in MODELS_TO_TEST:
        print(f"\nBenchmarking {model_name}...")
        result = benchmark_model(model_name)
        results.append(result)
        print(json.dumps(result, indent=2))

    print(f"\n{'=' * 60}\nSUMMARY\n{'=' * 60}")
    for r in results:
        if r["status"] == "ok":
            print(
                f"{r['model']:10s} | avg latency: {r['avg_latency_sec']}s | "
                f"valid JSON: {r['valid_json_rate']} | consistent: {r['consistent_signal']}"
            )
        else:
            print(f"{r['model']:10s} | FAILED: {r.get('error')}")


if __name__ == "__main__":
    main()
