# Week 6: Agentic AI & LangGraph
**Goal:** Design agent graph: Data Collector → Analyst (LLM) → Executor (mock trade), implement paper‑trading loop, and produce a runnable LangGraph agent (no real broker).

## Monday 7 Sep – LangGraph basics & environment setup
1. Ensure virtual environment is activated:
   ```bash
   source venv/Scripts/activate
   ```
2. Install langgraph and any needed dependencies:
   ```bash
   pip install langgraph
   ```
3. Verify installation:
   ```bash
   python -c "import langgraph; print(langgraph.__version__)"
   ```
4. Create a notebook to explore LangGraph concepts:
   ```bash
   jupyter notebook notebooks/13_langgraph_intro.ipynb
   ```
   In the notebook, run:
   ```python
   # 13_langgraph_intro.ipynb
   from langgraph.graph import StateGraph, END
   from typing import TypedDict, Annotated
   import operator

   # Define state
   class AgentState(TypedDict):
       data: dict
       analysis: str
       decision: str

   # Define nodes
   def collector(state: AgentState):
       # Simulate data collection
       state["data"] = {"price": 100, "sentiment": 0.5}
       return state

   def analyst(state: AgentState):
       # Simple LLM placeholder (we'll replace with Ollama later)
       state["analysis"] = f"Price is {state['data']['price']} with sentiment {state['data']['sentiment']}"
       return state

   def executor(state: AgentState):
       state["decision"] = "BUY" if state["data"]["sentiment"] > 0.3 else "HOLD"
       return state

   # Build graph
   workflow = StateGraph(AgentState)
   workflow.add_node("collector", collector)
   workflow.add_node("analyst", analyst)
   workflow.add_node("executor", executor)
   workflow.set_entry_point("collector")
   workflow.add_edge("collector", "analyst")
   workflow.add_edge("analyst", "executor")
   workflow.add_edge("executor", END)

   app = workflow.compile()
   result = app.invoke({"data": {}, "analysis": "", "decision": ""})
   print(result)
   ```
5. Save, commit, and push:
   ```bash
   git add notebooks/13_langgraph_intro.ipynb
   git commit -m "Add LangGraph intro notebook"
   git push origin dev
   ```

## Tuesday 8 Sep – Designing the agent graph for RAATS
1. Outline the three core nodes:
   - **Data Collector**: Fetches latest price and sentiment data.
   - **Analyst (LLM)**: Uses Ollama with llama3 to analyze data and generate trading signal.
   - **Executor (Mock Trade)**: Simulates order execution based on signal.
2. Define the state structure:
   ```python
   # File: src/agent/state.py
   from typing import TypedDict, Dict, Any

   class AgentState(TypedDict):
       market_data: Dict[str, Any]   # price, volume, etc.
       sentiment: float              # -1 to 1
       llm_analysis: str             # raw LLM output
       signal: str                   # BUY, SELL, HOLD
       executed_price: float         # price at which trade simulated
       timestamp: str
   ```
3. Create the file and commit:
   ```bash
   mkdir -p src/agent
   ```
   Then write the state.py file (use VS Code or cat).
   ```bash
   cat > src/agent/state.py << 'EOF'
   from typing import TypedDict, Dict, Any

   class AgentState(TypedDict):
       market_data: Dict[str, Any]
       sentiment: float
       llm_analysis: str
       signal: str
       executed_price: float
       timestamp: str
   EOF
   ```
   ```bash
   git add src/agent/state.py
   git commit -m "Add agent state definition"
   git push origin dev
   ```

## Wednesday 9 Sep – Data Collector node
1. Create a node that fetches latest OHLCV and sentiment data (reuse Week5 pipeline).
   ```python
   # File: src/agent/collector.py
   import pandas as pd
   import os
   from datetime import datetime, timedelta

   def collect_market_data(ticker: str = "AAPL") -> dict:
       # Load latest processed data (from Week5)
       data_path = f"data/processed/indicators/{ticker}_indicators.csv"
       if not os.path.exists(data_path):
           # Fallback: download latest week
           import yfinance as yf
           end = datetime.now()
           start = end - timedelta(days=7)
           df = yf.download(ticker, start=start, end=end)
           # Compute indicators using pandas-ta (simplified)
           import pandas_ta as ta
           df.ta.sma(length=10, append=True)
           df.ta.rsi(length=14, append=True)
           df.to_csv(data_path)
       df = pd.read_csv(data_path, index_col=0, parse_dates=True)
       latest = df.iloc[-1]
       return {
           "close": float(latest["Close"]),
           "sma_10": float(latest["SMA_10"]),
           "rsi": float(latest["RSI_14"]),
           "timestamp": latest.name.isoformat()
       }

   def collect_sentiment() -> float:
       # Placeholder: in later weeks we'll fetch from news/RSS
       # For now, simulate sentiment based on RSI
       data = collect_market_data()
       rsi = data["rsi"]
       # Normalize RSI to -1..1 (rough)
       sentiment = (rsi - 50) / 50  # RSI 0-100 -> -1..1
       return max(-1.0, min(1.0, sentiment))
   ```
2. Create the file and commit:
   ```bash
   mkdir -p src/agent
   cat > src/agent/collector.py << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   git add src/agent/collector.py
   git commit -m "Add data collector node"
   git push origin dev
   ```

## Thursday 10 Sep – Analyst node (LLM with Ollama)
1. Ensure Ollama is running with llama3 model.
2. Create analyst node that prompts the LLM with market data and sentiment.
   ```python
   # File: src/agent/analyst.py
   import subprocess
   import json
   from typing import Dict

   def ollama_analyze(prompt: str) -> str:
       result = subprocess.run(
           ["ollama", "run", "llama3", prompt],
           capture_output=True, text=True, check=True
       )
       return result.stdout.strip()

   def analyze_market(state: dict) -> dict:
       market_data = state["market_data"]
       sentiment = state["sentiment"]
       prompt = f"""
       You are a financial analyst. Given the following market data for AAPL:
       - Close price: {market_data['close']}
       - SMA 10: {market_data['sma_10']}
       - RSI: {market_data['rsi']}
       - Sentiment score: {sentiment}
       Provide a concise trading signal (BUY, SELL, HOLD) and a brief justification.
       """
       analysis = ollama_analyze(prompt)
       # Extract signal (simple)
       signal = "HOLD"
       if "BUY" in analysis.upper():
           signal = "BUY"
       elif "SELL" in analysis.upper():
           signal = "SELL"
       state["llm_analysis"] = analysis
       state["signal"] = signal
       return state
   ```
3. Create the file and commit:
   ```bash
   cat > src/agent/analyst.py << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   git add src/agent/analyst.py
   git commit -m "Add analyst node with Ollama"
   git push origin dev
   ```

## Friday 11 Sep – Executor node and paper‑trading loop
1. Create executor node that simulates trade execution.
   ```python
   # File: src/agent/executor.py
   def execute_trade(state: dict) -> dict:
       signal = state["signal"]
       market_data = state["market_data"]
       price = market_data["close"]
       # Simulate execution at close price (slippage zero for simplicity)
       executed_price = price
       state["executed_price"] = executed_price
       # In a real system, we would update position, PnL, etc.
       return state
   ```
2. Create a simple paper‑trading loop that runs the graph daily.
   ```python
   # File: src/agent/trading_loop.py
   from langgraph.graph import StateGraph, END
   from .state import AgentState
   from .collector import collect_market_data, collect_sentiment
   from .analyst import analyze_market
   from .executor import execute_trade
   from typing import TypedDict, Dict, Any

   # Re‑define state for clarity (could import)
   class AgentState(TypedDict):
       market_data: Dict[str, Any]
       sentiment: float
       llm_analysis: str
       signal: str
       executed_price: float
       timestamp: str

   def collector_node(state: AgentState) -> AgentState:
       state["market_data"] = collect_market_data()
       state["sentiment"] = collect_sentiment()
       state["timestamp"] = state["market_data"]["timestamp"]
       return state

   def build_graph():
       workflow = StateGraph(AgentState)
       workflow.add_node("collector", collector_node)
       workflow.add_node("analyst", analyze_market)
       workflow.add_node("executor", execute_trade)
       workflow.set_entry_point("collector")
       workflow.add_edge("collector", "analyst")
       workflow.add_edge("analyst", "executor")
       workflow.add_edge("executor", END)
       return workflow.compile()

   def run_daily_cycle():
       app = build_graph()
       initial_state: AgentState = {
           "market_data": {},
           "sentiment": 0.0,
           "llm_analysis": "",
           "signal": "",
           "executed_price": 0.0,
           "timestamp": ""
       }
       final_state = app.invoke(initial_state)
       print("=== Daily Cycle Result ===")
       print(f"Signal: {final_state['signal']}")
       print(f"Executed Price: {final_state['executed_price']}")
       print(f"LLM Analysis: {final_state['llm_analysis'][:200]}...")
       return final_state

   if __name__ == "__main__":
       run_daily_cycle()
   ```
3. Create the files and commit:
   ```bash
   cat > src/agent/executor.py << 'EOF'
   def execute_trade(state: dict) -> dict:
       signal = state["signal"]
       market_data = state["market_data"]
       price = market_data["close"]
       executed_price = price
       state["executed_price"] = executed_price
       return state
   EOF
   ```
   ```bash
   cat > src/agent/trading_loop.py << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   git add src/agent/executor.py src/agent/trading_loop.py
   git commit -m "Add executor node and trading loop"
   git push origin dev
   ```

## Saturday 12 Sep – Rest day
- No planned project work.

## Sunday 13 Sep – Testing, refinement, and preparation for Week 7
1. Run the trading loop to see end‑to‑end execution.
   ```bash
   source venv/Scripts/activate
   python -m src.agent.trading_loop
   ```
2. If any errors, debug and fix.
3. Create a reflection note in journal/week6_reflection.md:
   ```markdown
   # Week 6 Reflection – Luyolo Nyaluza
   ## What went well
   - Successfully set up LangGraph environment.
   - Defined agent state and three core nodes.
   - Integrated Ollama LLM for analysis.
   - Created a basic paper‑trading loop.
   ## Challenges / Blockers
   - Initial latency of Ollama calls (expected).
   - Parsing LLM output for signal extraction (simple keyword match works but brittle).
   ## Goals for Week 7
   - Add risk‑check module (position sizing, stop‑loss).
   - Measure execution latency and aim for <200 ms.
   - Log latency and results for analysis.
   ```
4. Commit the reflection:
   ```bash
   mkdir -p journal
   git add journal/week6_reflection.md
   git commit -m "Add week 6 reflection"
   git push origin dev
   ```

---\n**End of Week 6 Deliverables:**\n- Notebook: notebooks/13_langgraph_intro.ipynb\n- Module: src/agent/state.py, src/agent/collector.py, src/agent/analyst.py, src/agent/executor.py, src/agent/trading_loop.py\n- Data: continues using data/processed/indicators/\n- Logs: journal/week6_reflection.md\n