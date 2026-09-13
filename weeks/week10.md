# Week 10: Evaluation Framework
**Goal:** Define metrics, backtesting libs (zipline, backtrader), write evaluation script across historical windows, compute Sharpe, max DD, compare baseline vs LLM‑guided, produce evaluation report (PDF/MD).

## Monday 5 Oct – Choose backtesting library & setup
1. Ensure virtual environment activated.
2. Decide on a backtesting library (e.g., backtrader for simplicity, zipline if preferred).
3. Install the library and any dependencies.
   ```bash
   pip install backtrader
   ```
   or
   ```bash
   pip install zipline-reloaded
   ```
4. Create a notebook to explore the library basics.
   ```bash
   jupyter notebook notebooks/14_backtest_intro.ipynb
   ```
   In the notebook, run a simple example (e.g., SMA crossover on AAPL data).
5. Save, commit, and push:
   ```bash
   git add notebooks/14_backtest_intro.ipynb
   git commit -m "Add backtesting intro notebook"
   git push origin dev
   ```

## Tuesday 6 Oct – Define evaluation metrics
1. List metrics to compute: cumulative return, annualized return, Sharpe ratio, max drawdown, win rate, profit factor, etc.
2. Write a utility function to compute these from a series of returns or equity curve.
   ```python
   # File: src/evaluation/metrics.py
   import numpy as np
   import pandas as pd

   def compute_sharpe(returns, risk_free=0.0, periods=252):
       """Annualized Sharpe ratio"""
       excess = returns - risk_free/periods
       return np.sqrt(periods) * excess.mean() / excess.std()

   def compute_max_drawdown(equity_curve):
       """Max drawdown from equity curve"""
       roll_max = equity_curve.expanding().max()
       drawdown = (equity_curve - roll_max) / roll_max
       return drawdown.min()

   def compute_win_rate(trades):
       """Win rate from list of trade profits"""
       wins = [t for t in trades if t > 0]
       return len(wins) / len(trades) if trades else 0

   # Add more as needed
   ```
3. Create the file and commit:
   ```bash
   mkdir -p src/evaluation
   cat > src/evaluation/metrics.py << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   git add src/evaluation/metrics.py
   git commit -m "Add metrics utility"
   git push origin dev
   ```

## Wednesday 7 Oct – Backtest baseline strategy (buy & hold, SMA crossover)
1. Using historical data (from Week5), backtest a buy‑and‑hold strategy and an SMA crossover strategy.
2. Create a notebook that loads data, runs the strategies, and computes metrics.
   ```python
   # File: notebooks/15_baseline_backtest.ipynb
   # Load AAPL indicators data
   # Compute buy‑and‑hold returns
   # Compute SMA crossover returns (using signals from Week5)
   # Use metrics.py to compute Sharpe, max DD, etc.
   ```
3. Save, commit, and push:
   ```bash
   git add notebooks/15_baseline_backtest.ipynb
   git commit -m "Add baseline backtest notebook"
   git push origin dev
   ```

## Thursday 8 Oct – Backtest LLM‑guided strategy
1. We need to simulate the LLM‑guided strategy over historical data. Since we don't have actual LLM signals for past days, we can either:
   - Use the agent we built (but it uses current data) – we can approximate by running the agent for each historical day (as we did in Week8 simulation) and collect the signals.
   - Or, we can generate signals using a proxy (e.g., based on RSI and sentiment) for simplicity.
2. We'll choose to reuse the simulation from Week8 (src/simulation/run_simulation.py) but enhance it to record daily signals and returns.
3. Update the simulation to output a list of daily returns (based on the signal and next day's price change).
4. Write a notebook that runs the enhanced simulation and computes metrics.
   ```python
   # File: notebooks/16_llm_guided_backtest.ipynb
   # Import the updated simulation runner
   # Run simulation over a historical window (e.g., last 3 months)
   # Compute metrics using metrics.py
   ```
5. Create the file and commit:
   ```bash
   git add notebooks/16_llm_guided_backtest.ipynb
   git commit -m "Add LLM‑guided backtest notebook"
   git push origin dev
   ```

## Friday 9 Oct – Morning: Compare strategies and generate report
1. Compute metrics for both baseline and LLM‑guided strategies.
2. Create a comparison table.
3. Write a brief report (markdown) summarizing findings.
   ```markdown
   # File: reports/evaluation_report.md
   # Include tables, charts (if any), and conclusion.
   ```
4. Generate any plots (equity curves) and save them.
5. Commit the report and plots.
6. Afternoon: Rest (no work).

## Saturday 10 Oct – Rest day
- No planned project work.

## Sunday 11 Oct – Preparation for Week 11 (Documentation & Presentation Prep)
1. Review Week 11 plan: Documentation & Presentation Prep.
2. Sketch how to write the project report, build slide deck, record demo video.
3. Write a brief note in journal/week10_prep_week11.md.
4. Commit any notes or small scripts.
5. Create reflection for Week 10.
   ```markdown
   # Week 10 Reflection – Luyolo Nyaluza
   ## What went well
   - Successfully installed and explored a backtesting library.
   - Defined key performance metrics (Sharpe, max drawdown, etc.).
   - Backtested baseline strategies (buy & hold, SMA crossover).
   - Backtested the LLM‑guided strategy using the simulation from Week8.
   - Compared performance and generated a report.
   ## Challenges / Blockers
   - Simulating LLM signals for historical days requires the agent to be run in a loop (computationally heavy).
   - Ensuring the backtest uses the same data and indicators as the agent.
   ## Goals for Week 11
   - Write the final project report.
   - Build a slide deck for presentation.
   - Record a 5‑minute demo video of the agentic system.
   ```
6. Commit reflection and prep note.
   ```bash
   mkdir -p journal
   cat > journal/week10_reflection.md << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   cat > journal/week10_prep_week11.md << 'EOF'
   # Week 11 Preparation Notes
   ## Topic: Documentation & Presentation Prep
   
   ## High-level architecture ideas:
   - Final report: include introduction, methodology, results, conclusion.
   - Slide deck: highlight key components, architecture, results.
   - Demo video: show the agent running, making decisions, and simulating trades.
   
   ## Components to develop:
   1. Report template (can use university guidelines).
   2. Slide outline.
   3. Video recording script.
   
   ## Next steps:
   - Start writing the report.
   - Design the slides.
   - Prepare the demo.
   EOF
   ```
   ```bash
   git add journal/week10_reflection.md journal/week10_prep_week11.md
   git commit -m "Add week 10 reflection and week 11 prep"
   git push origin dev
   ```

---\n**End of Week 10 Deliverables:**\n- Notebook: notebooks/14_backtest_intro.ipynb, notebooks/15_baseline_backtest.ipynb, notebooks/16_llm_guided_backtest.ipynb\n- Module: src/evaluation/metrics.py\n- Reports: reports/evaluation_report.md (and any plots)\n- Logs: journal/week10_reflection.md\n- Preparation: journal/week10_prep_week11.md\n