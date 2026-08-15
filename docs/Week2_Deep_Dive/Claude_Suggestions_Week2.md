# Claude Suggestions — RAATS Week 2: LLM Foundations & RAG Prototyping

This document covers all five Week 2 focus areas: prompt engineering, model
comparison, vector store experimentation, RAG prototyping, and documentation.
Revised, integration-ready code for `strategist.py` and `paper_trader.py` is
included in Section 6.

---

## Section 1 — Prompt Engineering for Trading Signals

Three prompt templates to test against Ollama, from lightweight to
comprehensive.

### Template A — Direct Signal Generation (fast & lightweight)

```
You are a trading signal generator. Given the market data below, respond with
ONLY one word: BUY, SELL, or HOLD.

Ticker: {ticker}
Price: {price}
24h Change: {change_pct}%
RSI(14): {rsi}
Volume vs 20d avg: {volume_ratio}x

Signal:
```

### Template B — Strategy Selection (recommended for Week 2)

```
You are a trading strategist choosing between candidate strategies based on
current market conditions.

Market snapshot:
- Ticker: {ticker}
- Price: {price}
- Trend (20/50 SMA): {trend}
- RSI(14): {rsi}
- ADX(14): {adx}
- Recent volatility (ATR%): {atr_pct}

Candidate strategies: {strategy_list}

Respond in JSON with exactly these keys:
{{
  "selected_strategy": "<name>",
  "signal": "BUY | SELL | HOLD",
  "confidence": <0-1 float>,
  "reasoning": "<1-2 sentences>"
}}
```

### Template C — Sentiment-Aware Analysis (for RAG, future use)

```
You are a trading analyst. Combine the technical snapshot with the retrieved
news context to produce a signal.

Technical snapshot:
{technical_summary}

Retrieved news context:
{retrieved_context}

Respond in JSON:
{{
  "signal": "BUY | SELL | HOLD",
  "confidence": <0-1 float>,
  "technical_reasoning": "<short>",
  "sentiment_reasoning": "<short>"
}}
```

### Best Practices

| Practice | Why it matters |
|---|---|
| Force structured (JSON) output | Makes parsing deterministic downstream |
| Keep numeric context concise | Long prompts slow local models and add noise |
| Always include a "reasoning" field | Lets you audit *why* a signal was produced |
| Pin a temperature (e.g. 0.2) | Reduces signal flip-flopping on identical input |
| Version your prompts | Compare template performance over time |

See `notebooks_prompts_tester.py` for a script that runs all three templates
against sample data and logs the outputs.

---

## Section 2 — Model Comparison

| Model | Size | Approx. Latency (local CPU) | Notes |
|---|---|---|---|
| mistral | 7B | ~2s | Best speed/quality tradeoff, good default |
| llama3 | 8B | ~4s | Best reasoning quality of the small models |
| llama2 | 7B | ~3s | Older, generally weaker instruction following |
| phi3 | 3.8B | ~1s | Fastest, weaker on multi-step financial reasoning |
| mixtral | 8x7B | ~10s+ | Best quality but heavy; only if you have GPU headroom |

**Recommendation:** Start with `mistral` for iteration speed, benchmark
`llama3` for final quality comparison before locking in a default.

### Evaluation Rubric

Score each model 1-5 on:
1. **JSON validity** — did it return parseable structured output?
2. **Signal consistency** — same input, same signal across 3 runs?
3. **Reasoning quality** — is the explanation grounded in the given data?
4. **Latency** — acceptable for your target decision interval?
5. **Instruction following** — did it stick to the requested format?

See `notebooks_model_comparison.py` for an automated benchmarking harness.

---

## Section 3 — Vector Store Experimentation

### Why Chroma (recommended for RAATS)

- Simple Python API, minimal setup
- Built-in persistence to disk (`persist_directory`)
- Native metadata filtering (e.g. filter by ticker or date range)
- Good enough performance at the scale of a single-user research project

### Minimal Chroma Wrapper

```python
import chromadb
from chromadb.utils import embedding_functions

class ChromaVectorStore:
    def __init__(self, persist_directory="./chroma_db", collection_name="raats_news"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_fn,
        )

    def add_news(self, doc_id, text, ticker, date, source="unknown"):
        self.collection.add(
            ids=[doc_id],
            documents=[text],
            metadatas=[{"ticker": ticker, "date": date, "source": source}],
        )

    def add_technical_note(self, doc_id, text, ticker, indicator):
        self.collection.add(
            ids=[doc_id],
            documents=[text],
            metadatas=[{"ticker": ticker, "type": "technical", "indicator": indicator}],
        )

    def query(self, query_text, ticker=None, n_results=5):
        where = {"ticker": ticker} if ticker else None
        return self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where,
        )
```

### FAISS Alternative

FAISS is faster at large scale but has no built-in metadata filtering or
persistence layer out of the box — you'd manage an index file plus a separate
mapping of ids to metadata yourself. For Week 2's scope, Chroma's simplicity
wins; revisit FAISS only if you hit performance limits later.

See `notebooks_vector_store_chroma.py` for a runnable setup + query demo.

---

## Section 4 — RAG Prototyping

### Architecture

```
News/Docs ──► Embed ──► Chroma (vector store)
                              │
Market Data ──► Technical summary ──┐
                                     ▼
                         Retrieve top-k relevant context
                                     │
                                     ▼
                     Prompt (Template C) ──► Ollama ──► Signal (JSON)
```

### RAGTradingAgent (prototype)

```python
class RAGTradingAgent:
    def __init__(self, vector_store, llm_client, model_name="mistral"):
        self.vector_store = vector_store
        self.llm_client = llm_client
        self.model_name = model_name

    def _build_context(self, ticker, query, n_results=3):
        results = self.vector_store.query(query, ticker=ticker, n_results=n_results)
        docs = results.get("documents", [[]])[0]
        return "\n---\n".join(docs) if docs else "No relevant context found."

    def generate_signal(self, ticker, technical_summary):
        context = self._build_context(ticker, technical_summary)
        prompt = TEMPLATE_C.format(
            technical_summary=technical_summary,
            retrieved_context=context,
        )
        response = self.llm_client.generate(model=self.model_name, prompt=prompt)
        return response
```

This is a prototype only — Week 3 is where real news ingestion, embedding
pipelines, and error handling get built out fully.

---

## Section 5 — Documentation & Learning Capture

### Week 2 Learning Template

```markdown
# Week 2 Learning Capture — [Date]

## Prompt Engineering
- Template that worked best: ___
- Surprising failures: ___

## Model Comparison
- Chosen default model: ___
- Latency observed: ___
- Quality notes: ___

## Vector Store
- Setup issues encountered: ___
- Query quality observations: ___

## RAG Prototype
- What worked: ___
- What's needed for Week 3: ___

## Overall Reflection
- Biggest blocker this week: ___
- Plan for next week: ___
```

---

## Section 6 — Revised Code Examples

### 6.1 `src/llm/strategist.py` (Revised)

See `src_llm_strategist_REVISED.py` in this package. Highlights:
- Fixed `__init__` (was `init`)
- Structured JSON parsing with fallback handling
- Optional RAG-augmented mode (`use_rag=True`)
- Batch signal generation across multiple tickers
- Logging via the standard `logging` module

### 6.2 `src/execution/paper_trader.py` (Revised)

See `src_execution_paper_trader_REVISED.py` in this package. Highlights:
- Full position lifecycle: open → monitor → close
- Stop-loss / take-profit checking each tick
- Trade history with realized P&L
- Portfolio summary reporting method

---

## Next Steps

1. Copy the revised code from Section 6 into your actual project files
2. Run the prompt tests using `notebooks_prompts_tester.py`
3. Benchmark models with `notebooks_model_comparison.py`
4. Set up Chroma and index a few sample news items
5. Fill in the Week 2 Learning Capture template
6. Prepare for Week 3, where strategist + paper trader get fully integrated
