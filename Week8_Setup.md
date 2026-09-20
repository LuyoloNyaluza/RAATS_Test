# Week 8 Setup - Integration: End‑to‑End Paper Trading
**Goal:** Integrate all components into a single paper‑trading simulation, run historical simulation over a week of data, and generate performance report.

## Prerequisites
- Completed Week 7 setup (risk management, latency measurement, logging)
- Python virtual environment activated (`source venv/Scripts/activate` or `source RAATS_Test.venv/Scripts/activate`)
- Required packages installed: yfinance, pandas-ta, matplotlib, seaborn (install as needed)
- Ollama with llama3 model running
- Basic understanding of pandas and Jupyter notebooks

## Daily Activities with Runnable Code Snippets

### Monday 21 Sep – Simulation orchestrator design
1. Ensure you are in the RAATS_Test project root:
   ```bash
   cd /c/Users/Zamuxolo/RAATS_Test
   ```
2. Activate virtual environment (if not already):
   ```bash
   source venv/Scripts/activate
   ```
3. Create a simulation orchestrator that loops over historical dates, runs the agent graph for each day, and tracks portfolio.
   ```python
   # File: src/simulation/orchestrator.py
   import pandas as pd
   import os
   from datetime import datetime, timedelta
   from src.agent.trading_loop import run_daily_cycle  # we'll adapt to accept date
   from src.utils.logger import log_cycle

   def simulate_historical(ticker: str = "AAPL", start_date: str = None, end_date: str = None):
       # Load processed indicators data (from Week5)
       data_path = f"data/processed/indicators/{ticker}_indicators.csv"
       df = pd.read_csv(data_path, index_col=0, parse_dates=True)
       if start_date:
           df = df[df.index >= pd.Timestamp(start_date)]
       if end_date:
           df = df[df.index <= pd.Timestamp(end_date)]
       # For each day, run the agent (we'll simplify: use the same agent but with fixed data for that day)
       # In a more advanced version, we would adjust the collector to fetch data for that specific day.
       portfolio_value = 10000.0
       for date, row in df.iterrows():
           # We'll create a mock state for the day (in reality, we'd update the collector to use this day's data)
           # For now, we'll just run the existing trading loop and note the date.
           # We'll adapt the trading loop to accept a date later.
           print(f"Simulating {date.date()}")
           # TODO: run agent for this day
       return None
   ```
4. Create the file and commit:
   ```bash
   mkdir -p src/simulation
   cat > src/simulation/orchestrator.py << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   git add src/simulation/orchestrator.py
   git commit -m "Add simulation orchestrator stub"
   git push origin dev
   ```

### Tuesday 22 Sep – Enhance collector to accept a specific date
1. Modify src/agent/collector.py to accept an optional date parameter and load data for that date.
2. We'll adjust the collector to read from the processed indicators CSV and filter by date.
   ```python
   # Update src/agent/collector.py
   def collect_market_data(ticker: str = "AAPL", date: str = None) -> dict:
       data_path = f"data/processed/indicators/{ticker}_indicators.csv"
       df = pd.read_csv(data_path, index_col=0, parse_dates=True)
       if date:
           target_date = pd.Timestamp(date)
           # Find the closest date (or exact match)
           df = df[df.index == target_date]
           if df.empty:
               # If no data for that exact date, fallback to latest
               df = df.iloc[[-1]]
       else:
           df = df.iloc[[-1]]  # latest
       latest = df.iloc[0]
       return {
           "close": float(latest["Close"]),
           "sma_10": float(latest["SMA_10"]),
           "rsi": float(latest["RSI_14"]),
           "timestamp": latest.name.isoformat()
       }
   ```
3. Update the file and commit:
   ```bash
   cat > src/agent/collector.py << 'EOF'
   [updated content]
   EOF
   ```
   ```bash
   git add src/agent/collector.py
   git commit -m "Update collector to accept date"
   git push origin dev
   ```

### Wednesday 23 Sep – Update trading loop to use date-specific collector
1. Update src/agent/trading_loop.py to accept a date and pass it to the collector.
2. We'll change the collector_node to accept a date from the orchestrator.
   ```python
   # In src/agent/trading_loop.py, adjust collector_node to take date from state or args.
   # We'll change the design: the orchestrator will pass the date to the trading loop function.
   ```
3. Instead, let's create a new function in trading_loop that runs for a given date.
   ```python
   # File: src/agent/trading_loop.py (add function)
   def run_daily_cycle_for_date(date_str: str):
       # We'll create a state and override the collector to use the given date.
       # For simplicity, we'll create a new collector function that uses the date.
       from .collector import collect_market_data, collect_sentiment
       market_data = collect_market_data(date=date_str)
       sentiment = collect_sentiment()  # sentiment still generic; we could make date-specific later
       # Then run the analyst and executor as before.
       # We'll reuse the existing functions but we need to adjust the state.
       # Let's create a minimal graph run for this date.
       # We'll copy the logic from run_daily_cycle but inject the market_data and sentiment.
       # For brevity, we'll just call the existing functions and then run analyst and executor.
       # Note: This is a simplification; in a real system we would rebuild the graph with the date.
       state = {
           "market_data": market_data,
           "sentiment": sentiment,
           "llm_analysis": "",
           "signal": "",
           "executed_price": 0.0,
           "timestamp": market_data["timestamp"]
       }
       state = analyze_market(state)
       state = execute_trade(state)
       return state
   ```
4. Update the file and commit:
   ```bash
   cat > src/agent/trading_loop.py << 'EOF'
   [content with new function]
   EOF
   ```
   ```bash
   git add src/agent/trading_loop.py
   git commit -m "Add date-specific trading cycle"
   git push origin dev
   ```

### Thursday 24 Sep – Run historical simulation and collect metrics
1. Write a simulation script that loops over a week of dates, runs the agent for each day, logs results, and computes performance metrics.
   ```python
   # File: src/simulation/run_simulation.py
   import pandas as pd
   from src.agent.trading_loop import run_daily_cycle_for_date
   from src.utils.logger import log_cycle
   import json

   def run_week_simulation(ticker: str = "AAPL", start_date: str = "2026-09-01", end_date: str = "2026-09-07"):
       df = pd.read_csv(f"data/processed/indicators/{ticker}_indicators.csv", index_col=0, parse_dates=True)
       mask = (df.index >= pd.Timestamp(start_date)) & (df.index <= pd.Timestamp(end_date))
       df_week = df.loc[mask]
       portfolio_value = 10000.0
       # We'll track simple metrics: cumulative returns, etc.
       returns = []
       for date, row in df_week.iterrows():
           date_str = date.strftime("%Y-%m-%d")
           print(f"Running simulation for {date_str}")
           state = run_daily_cycle_for_date(date_str)
           # For simplicity, we'll assume the strategy returns are based on the signal and price change.
           # We'll compute a simple daily return: if BUY, then return is (next_day_close - today_close)/today_close, etc.
           # We'll need next day's price; we'll approximate by using the row's close and the next row's close.
           # We'll do this after the loop.
           # Log the cycle
           log_cycle(
               signal=state["signal"],
               executed_price=state["executed_price"],
               latencies={}  # we don't have latencies in this simplified version
           )
       # After loop, compute metrics (placeholder)
       print("Simulation complete. Compute metrics...")
   ```
2. Create the file and commit:
   ```bash
   cat > src/simulation/run_simulation.py << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   git add src/simulation/run_simulation.py
   git commit -m "Add simulation runner"
   git push origin dev
   ```

### Friday 25 Sep – Morning: Run simulation and generate report
1. Source venv and run the simulation script.
2. Generate a simple performance report (e.g., total return, Sharpe approximation, max drawdown).
3. Afternoon: Rest (no work).

### Saturday 26 Sep – Rest day
- No planned project work.

### Sunday 27 Sep – Preparation for Week 9
1. Review Week 9 plan: System Scalability & Resource Utilization.
2. Sketch how to dockerize the components (Ollama, PostgreSQL, Vector DB, Agent API) and add health checks.
3. Write a brief note in journal/week8_prep_week9.md.
4. Commit reflection for Week 8.
   ```markdown
   # Week 8 Reflection – Luyolo Nyaluza
   ## What went well
   - Successfully designed simulation orchestrator.
   - Enhanced collector to accept specific dates.
   - Created date-specific trading cycle.
   - Built simulation runner that loops over historical dates.
   ## Challenges / Blockers
   - Simplifications in latency and sentiment modeling.
   - Need for more realistic performance metrics.
   ## Goals for Week 9
   - Dockerize Ollama and other services.
   - Set up docker-compose for the agent API, vector store, and database.
   - Add health checks and monitoring.
   ```
5. Commit reflection and prep note.
   ```bash
   mkdir -p journal
   cat > journal/week8_reflection.md << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   cat > journal/week8_prep_week9.md << 'EOF'
   # Week 9 Preparation Notes
   ## Topic: System Scalability & Resource Utilization
   
   ## High-level architecture ideas:
   - Use Docker-compose to orchestrate Ollama (LLM), PostgreSQL (metadata), Chroma/FAISS (vector store), and a FastAPI agent service.
   - Each service in its own container with health checks.
   - Use Prometheus to scrape metrics (e.g., latency, request counts) and Grafana for visualization.
   
   ## Components to dockerize:
   1. Ollama service (already has Docker support).
   2. PostgreSQL for storing agent states, trade logs, etc.
   3. Chroma or FAISS vector store (we'll use Chroma for simplicity).
   4. Agent API: a FastAPI wrapper that exposes the trading loop as an endpoint.
   5. Optional: a simple frontend or CLI to trigger simulations.
   
   ## Next steps:
   - Write Dockerfiles for each service.
   - Create docker-compose.yml.
   - Add healthchecks and monitoring setup.
   EOF
   ```
   ```bash
   git add journal/week8_reflection.md journal/week8_prep_week9.md
   git commit -m "Add week 8 reflection and week 9 prep"
   git push origin dev
   ```

---\n**End of Week 8 Deliverables:**\n- Module: src/simulation/orchestrator.py, src/simulation/run_simulation.py\n- Updated: src/agent/collector.py, src/agent/trading_loop.py\n- Logs: logs/agent_performance.jsonl (continued)\n- Reflection: journal/week8_reflection.md\n- Preparation: journal/week8_prep_week9.md\n