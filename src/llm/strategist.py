"""
src/llm/strategist.py (REVISED)

Fixes applied vs. the original stub:
- __init__ was previously written as init() — fixed
- Not actually connected to Ollama — now uses the `ollama` python client
- No error handling / logging — added throughout
- No structured output — now parses JSON with a safe fallback
- No RAG support — optional retriever can be injected
- No batch mode — added generate_signals_batch()

Usage:
    strategist = LLMStrategist(model_name="mistral")
    signal = strategist.generate_signal(ticker="AAPL", market_data={...})
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

try:
    import ollama
except ImportError:  # pragma: no cover
    ollama = None

logger = logging.getLogger("raats.llm.strategist")
logging.basicConfig(level=logging.INFO)


TEMPLATE_STRATEGY_SELECTION = """You are a trading strategist choosing between candidate strategies based on
current market conditions.

Market snapshot:
- Ticker: {ticker}
- Price: {price}
- Trend (20/50 SMA): {trend}
- RSI(14): {rsi}
- ADX(14): {adx}
- Recent volatility (ATR%): {atr_pct}

Candidate strategies: {strategy_list}

Respond ONLY in valid JSON with exactly these keys, no extra text:
{{
  "selected_strategy": "<name>",
  "signal": "BUY | SELL | HOLD",
  "confidence": <0-1 float>,
  "reasoning": "<1-2 sentences>"
}}"""

TEMPLATE_RAG_AUGMENTED = """You are a trading analyst. Combine the technical snapshot with the retrieved
news context to produce a signal.

Technical snapshot:
{technical_summary}

Retrieved news context:
{retrieved_context}

Respond ONLY in valid JSON, no extra text:
{{
  "signal": "BUY | SELL | HOLD",
  "confidence": <0-1 float>,
  "technical_reasoning": "<short>",
  "sentiment_reasoning": "<short>"
}}"""


@dataclass
class StrategistConfig:
    model_name: str = "mistral"
    temperature: float = 0.2
    default_strategies: List[str] = field(
        default_factory=lambda: ["mean_reversion", "momentum", "breakout"]
    )


class LLMStrategist:
    """LLM-driven strategy selector / signal generator."""

    def __init__(
        self,
        model_name: str = "mistral",
        temperature: float = 0.2,
        retriever: Optional[Any] = None,
        use_rag: bool = False,
    ):
        """
        Args:
            model_name: Ollama model tag (e.g. "mistral", "llama3").
            temperature: Sampling temperature; lower = more deterministic.
            retriever: Optional object exposing `.query(text, ticker=None, n_results=3)`
                       returning a dict with a "documents" key (e.g. ChromaVectorStore).
            use_rag: If True, `generate_signal` will pull context from `retriever`.
        """
        if ollama is None:
            raise ImportError(
                "The 'ollama' package is required. Install with: pip install ollama"
            )

        self.config = StrategistConfig(model_name=model_name, temperature=temperature)
        self.retriever = retriever
        self.ollama = ollama
        self.use_rag = use_rag and retriever is not None

        if use_rag and retriever is None:
            logger.warning("use_rag=True but no retriever provided; falling back to non-RAG mode.")

        logger.info(
            "LLMStrategist initialized (model=%s, rag=%s)", self.config.model_name, self.use_rag
        )

    def _call_llm(self, prompt: str) -> str:
        if self.ollama is None:
            # This should never happen due to the check in __init__, but added for type safety
            raise ImportError("The 'ollama' package is required but not available.")
        try:
            response = self.ollama.generate(
                model=self.config.model_name,
                prompt=prompt,
                options={"temperature": self.config.temperature},
            )
            return response.get("response", "")
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            raise

    @staticmethod
    def _safe_parse_json(raw_text: str) -> Dict[str, Any]:
        """Attempt to extract and parse a JSON object from raw LLM output."""
        text = raw_text.strip()
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fall back to extracting the first {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                logger.warning("Failed to parse extracted JSON block: %s", exc)

        logger.warning("Could not parse LLM output as JSON. Raw output: %s", text[:200])
        return {
            "signal": "HOLD",
            "confidence": 0.0,
            "reasoning": "Failed to parse LLM output; defaulting to HOLD.",
            "raw_output": text,
        }

    def generate_signal(self, ticker: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a trading signal for a single ticker.

        market_data expected keys: price, trend, rsi, adx, atr_pct
        """
        try:
            prompt = TEMPLATE_STRATEGY_SELECTION.format(
                ticker=ticker,
                price=market_data.get("price", "N/A"),
                trend=market_data.get("trend", "N/A"),
                rsi=market_data.get("rsi", "N/A"),
                adx=market_data.get("adx", "N/A"),
                atr_pct=market_data.get("atr_pct", "N/A"),
                strategy_list=", ".join(self.config.default_strategies),
            )
            raw = self._call_llm(prompt)
            result = self._safe_parse_json(raw)
            result["ticker"] = ticker
            logger.info("Signal generated for %s: %s", ticker, result.get("signal"))
            return result
        except Exception as exc:
            logger.error("generate_signal failed for %s: %s", ticker, exc)
            return {
                "ticker": ticker,
                "signal": "HOLD",
                "confidence": 0.0,
                "reasoning": f"Error during generation: {exc}",
            }

    def generate_signal_with_rag(self, ticker: str, technical_summary: str) -> Dict[str, Any]:
        """Generate a signal using retrieved news/context alongside technicals."""
        if not self.use_rag:
            logger.warning("generate_signal_with_rag called but RAG is not enabled.")
            return {"ticker": ticker, "signal": "HOLD", "confidence": 0.0,
                     "reasoning": "RAG not enabled."}

        # At this point, use_rag is True, so retriever must be not None
        assert self.retriever is not None, "Retriever is not set when use_rag is True"
        try:
            retrieved = self.retriever.query(technical_summary, ticker=ticker, n_results=3)
            docs = retrieved.get("documents", [[]])[0] if retrieved else []
            context = "\\n---\\n".join(docs) if docs else "No relevant context found."

            prompt = TEMPLATE_RAG_AUGMENTED.format(
                technical_summary=technical_summary,
                retrieved_context=context,
            )
            raw = self._call_llm(prompt)
            result = self._safe_parse_json(raw)
            result["ticker"] = ticker
            return result
        except Exception as exc:
            logger.error("generate_signal_with_rag failed for %s: %s", ticker, exc)
            return {"ticker": ticker, "signal": "HOLD", "confidence": 0.0,
                     "reasoning": f"Error during RAG generation: {exc}"}

    def generate_signals_batch(
        self, tickers_data: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Generate signals for multiple tickers.

        Args:
            tickers_data: dict of {ticker: market_data_dict}
        """
        results = []
        for ticker, market_data in tickers_data.items():
            results.append(self.generate_signal(ticker, market_data))
        return results


if __name__ == "__main__":
    # Quick manual smoke test
    strategist = LLMStrategist(model_name="mistral")
    sample_data = {
        "price": 187.32,
        "trend": "uptrend",
        "rsi": 58.4,
        "adx": 27.1,
        "atr_pct": 1.8,
    }
    signal = strategist.generate_signal("AAPL", sample_data)
    print(json.dumps(signal, indent=2))
