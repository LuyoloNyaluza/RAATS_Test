# Week 10 Reflection – Luyolo Nyaluza
## What went well
- Successfully installed and explored zipline-reloaded for backtesting.
- Defined key performance metrics (Sharpe, max drawdown, win rate) in src/evaluation/metrics.py.
- Backtested baseline strategies (buy & hold, SMA crossover) using zipline.
- Backtested the LLM‑guided strategy using the simulation from Week8 (src/simulation/orchestrator.py).
- Compared performance of all three strategies and generated a report.

## Challenges / Blockers
- Simulating LLM signals for historical days requires running the agent for each day, which is computationally heavy for longer windows.
- Ensuring the backtest uses the same data and indicators as the agent (we used the same cached CSVs, which is good).
- The equity curve from the LLM‑guided simulation only reflects realized P&L (closed trades); unrealized P&L on open positions at the end of the window is not captured. This is a known limitation noted in the orchestrator.

## Goals for Week 11
- Write the final project report.
- Build a slide deck for presentation.
- Record a 5‑minute demo video of the agentic system.