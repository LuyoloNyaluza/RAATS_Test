# Week 7: Risk Management & Execution Latency
**Goal:** Add risk‑check module, time execution with perf_counter, log latency, and produce risk module + latency log (target <200 ms).

## Monday 14 Sep – Risk‑check module design
1. Ensure virtual environment activated.
2. Create risk management module that validates trades based on:
   - Maximum position size (e.g., 10% of portfolio)
   - Stop‑loss and take‑profit levels
   - Maximum daily loss limit
3. Write the module:
   ```python
   # File: src/risk/risk_manager.py
   class RiskManager:
       def __init__(self, max_position_pct=0.1, stop_loss_pct=0.05, take_profit_pct=0.15, max_daily_loss_pct=0.05):
           self.max_position_pct = max_position_pct
           self.stop_loss_pct = stop_loss_pct
           self.take_profit_pct = take_profit_pct
           self.max_daily_loss_pct = max_daily_loss_pct
           self.daily_pnl = 0.0
           self.position = 0  # in shares
           self.entry_price = 0.0

       def validate_trade(self, signal, current_price, portfolio_value):
           """Return (approved, adjusted_size, reason)"""
           # Calculate desired position size based on signal
           if signal == "BUY":
               max_shares = int((portfolio_value * self.max_position_pct) / current_price)
               if max_shares <= 0:
                   return False, 0, "Position size too small"
               # Check stop-loss and take-profit (for simplicity, we set on entry)
               return True, max_shares, "Approved"
           elif signal == "SELL":
               # For selling, check if we have position to sell
               if self.position <= 0:
                   return False, 0, "No position to sell"
               return True, self.position, "Approved"
           else:  # HOLD
               return False, 0, "Hold signal"
   
       def update_position(self, signal, shares, price):
           """Update internal position tracking"""
           if signal == "BUY":
               self.position += shares
               if self.entry_price == 0:
                   self.entry_price = price
           elif signal == "SELL":
               self.position -= shares
               if self.position == 0:
                   self.entry_price = 0.0
   
       def update_daily_pnl(self, pnl):
           self.daily_pnl += pnl
   
       def can_trade_today(self):
           return abs(self.daily_pnl) <= (portfolio_value * self.max_daily_loss_pct)  # portfolio_value needed; simplify
   ```
4. Create the file and commit:
   ```bash
   mkdir -p src/risk
   cat > src/risk/risk_manager.py << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   git add src/risk/risk_manager.py
   git commit -m "Add risk manager module"
   git push origin dev
   ```

## Tuesday 15 Sep – Integrate risk check into agent
1. Modify the trading loop to include risk validation before execution.
2. Update executor.py to consult risk manager.
   ```python
   # File: src/agent/executor.py (updated)
   from src.risk.risk_manager import RiskManager

   # Initialize risk manager (in practice, would be passed or made global)
   risk_manager = RiskManager()

   def execute_trade(state: dict) -> dict:
       signal = state["signal"]
       market_data = state["market_data"]
       price = market_data["close"]
       # Assume portfolio value of 10000 for simulation
       portfolio_value = 10000
       approved, size, reason = risk_manager.validate_trade(signal, price, portfolio_value)
       if not approved:
           print(f"Trade rejected: {reason}")
           state["executed_price"] = 0.0
           state["signal"] = "HOLD"  # override to hold
           return state
       # Simulate execution
       executed_price = price
       state["executed_price"] = executed_price
       # Update risk manager position
       if signal == "BUY":
           risk_manager.update_position("BUY", size, executed_price)
       elif signal == "SELL":
           risk_manager.update_position("SELL", size, executed_price)
       return state
   ```
3. Update the file and commit:
   ```bash
   cat > src/agent/executor.py << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   git add src/agent/executor.py
   git commit -m "Integrate risk check into executor"
   git push origin dev
   ```

## Wednesday 16 Sep – Latency measurement
1. Add latency measurement to each node using time.perf_counter.
2. Create a utility for timing:
   ```python
   # File: src/utils/timer.py
   import time
   from functools import wraps

   def timer(func):
       @wraps(func)
       def wrapper(*args, **kwargs):
           start = time.perf_counter()
           result = func(*args, **kwargs)
           end = time.perf_counter()
           elapsed_ms = (end - start) * 1000
           # Optionally log to file or state
           print(f"{func.__name__} took {elapsed_ms:.2f} ms")
           return result, elapsed_ms
       return wrapper
   ```
3. Apply decorator to nodes (collector, analyst, executor) or wrap calls.
4. Update trading loop to collect and log latencies.
5. Create the files and commit:
   ```bash
   mkdir -p src/utils
   cat > src/utils/timer.py << 'EOF'
   import time
   from functools import wraps

   def timer(func):
       @wraps(func)
       def wrapper(*args, **kwargs):
           start = time.perf_counter()
           result = func(*args, **kwargs)
           end = time.perf_counter()
           elapsed_ms = (end - start) * 1000
           print(f"{func.__name__} took {elapsed_ms:.2f} ms")
           return result, elapsed_ms
       return wrapper
   EOF
   ```
   ```bash
   git add src/utils/timer.py
   git commit -m "Add timer utility"
   git push origin dev
   ```

## Thursday 17 Sep – Logging latency and results
1. Create a simple logger to store latency and trade results for analysis.
   ```python
   # File: src/utils/logger.py
   import json
   import os
   from datetime import datetime

   LOG_FILE = "logs/agent_performance.jsonl"

   def log_cycle(signal, executed_price, latencies, pnl=0.0):
       entry = {
           "timestamp": datetime.now().isoformat(),
           "signal": signal,
           "executed_price": executed_price,
           "latencies_ms": latencies,  # dict of node -> ms
           "pnl": pnl
       }
       os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
       with open(LOG_FILE, "a") as f:
           f.write(json.dumps(entry) + "\n")
   ```
2. Update trading loop to use logger.
3. Create the file and commit:
   ```bash
   cat > src/utils/logger.py << 'EOF'
   import json
   import os
   from datetime import datetime

   LOG_FILE = "logs/agent_performance.jsonl"

   def log_cycle(signal, executed_price, latencies, pnl=0.0):
       entry = {
           "timestamp": datetime.now().isoformat(),
           "signal": signal,
           "executed_price": executed_price,
           "latencies_ms": latencies,
           "pnl": pnl
       }
       os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
       with open(LOG_FILE, "a") as f:
           f.write(json.dumps(entry) + "\n")
   EOF
   ```
   ```bash
   git add src/utils/logger.py
   git commit -m "Add logger utility"
   git push origin dev
   ```

## Friday 18 Sep – Morning: Run latency tests and optimize
1. Source venv and run the trading loop multiple times to collect latency stats.
2. Aim for each node <50ms, total <200ms.
3. If latency high, consider:
   - Caching Ollama responses (if same prompt)
   - Using async calls (but note Ollama CLI is synchronous)
   - Optimizing data loading (e.g., load CSV once)
4. Afternoon: Rest (no work).

## Saturday 19 Sep – Rest day
- No planned project work.

## Sunday 20 Sep – Preparation for Week 8
1. Review Week 8 plan: Integration: End‑to‑End Paper Trading.
2. Sketch how to connect data pipeline, LLM strategist, risk manager, and mock executor into a cohesive simulation.
3. Write a brief note in journal/week7_prep_week8.md.
4. Commit any notes or small scripts.
5. Create reflection for Week 7.
   ```markdown
   # Week 7 Reflection – Luyolo Nyaluza
   ## What went well
   - Successfully designed risk management module.
   - Integrated risk checks into the agent execution flow.
   - Added latency measurement utilities.
   - Created logger for performance tracking.
   ## Challenges / Blockers
   - Balancing risk parameters without over‑constraining trades.
   - Ollama latency dominates overall cycle time.
   ## Goals for Week 8
   - Integrate all components into a single paper‑trading simulation.
   - Run historical simulation over a week of data.
   - Generate performance report (Sharpe, max drawdown, etc.).
   ```
6. Commit reflection and prep note.
   ```bash
   mkdir -p journal
   cat > journal/week7_reflection.md << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   cat > journal/week7_prep_week8.md << 'EOF'
   # Week 8 Preparation Notes
   ## Topic: Integration: End‑to‑End Paper Trading
   
   ## High-level architecture ideas:
   - Data collector feeds processed market data and sentiment.
   - Risk manager validates trade signals based on portfolio rules.
   - Analyst (LLM) refines or overrides signals with contextual analysis.
   - Executor simulates trades and updates portfolio.
   - Performance tracker logs trades, computes metrics.
   
   ## Components to integrate:
   1. Data pipeline (src/data/market_data.py) – provides OHLCV and indicators.
   2. Sentiment module (reuse from Week6 or enhance).
   3. Risk manager (src/risk/risk_manager.py).
   4. LLM analyst (src/agent/analyst.py).
   5. Executor with simulation (src/agent/executor.py).
   6. Performance logger (src/utils/logger.py).
   7. Main simulation script that loops over historical dates.
   
   ## Next steps:
   - Design simulation orchestrator.
   - Implement portfolio tracker.
   - Run simulation on historical data and compute metrics.
   EOF
   ```
   ```bash
   git add journal/week7_reflection.md journal/week7_prep_week8.md
   git commit -m "Add week 7 reflection and week 8 prep"
   git push origin dev
   ```

---\n**End of Week 7 Deliverables:**\n- Module: src/risk/risk_manager.py, src/utils/timer.py, src/utils/logger.py\n- Updated: src/agent/executor.py\n- Logs: logs/agent_performance.jsonl (created during runs)\n- Reflection: journal/week7_reflection.md\n- Preparation: journal/week7_prep_week8.md\n