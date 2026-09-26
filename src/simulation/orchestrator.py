"""
src/simulation/orchestrator.py

Historical paper-trading simulation (Week 8 goal). Beyond the earlier
stub, this actually runs the agent for each historical date, and now
also computes performance metrics (cumulative return, Sharpe, max
drawdown) from the resulting closed-trade history.

Two things the stub didn't have:

1. A SINGLE RiskManager persists across the whole simulation, not a
   fresh one per day - otherwise every "day" would start from zero
   capital with no memory of yesterday's open positions, which isn't a
   simulation of anything real.
2. Every day's cycle only sees data up to and including that day
   (via simulate_date -> as_of, threaded through collector.py's
   look-ahead-bias guard) - so day 10's stability/gradient checks can't
   see day 15's price action.

METRICS LIMITATION - stated explicitly, not hidden: the equity curve
used for Sharpe/drawdown reflects REALIZED P&L only (from closed
trades), not mark-to-market unrealized P&L on positions still open at
the end of the simulation window. A simulation that ends mid-trade will
understate true performance/risk until those positions are closed. This
is a reasonable simplification for an initial Week 8 pass, but should be
named as a limitation in the write-up, not presented as a complete P&L
accounting.
"""

from typing import List, Optional

import numpy as np
import pandas as pd

from src.agents.trading_loop import build_graph, run_daily_cycle
from src.risk.risk_manager import RiskManager


def compute_performance_metrics(closed_trades: List[dict], starting_capital: float) -> dict:
    """Cumulative return, Sharpe ratio, and max drawdown from a sequence
    of closed trades (each a dict with at least a 'pnl' key), in the
    order they closed.

    Sharpe assumes a 0% risk-free rate and annualizes using 252 trading
    days/year - a standard simplification, but an explicit assumption
    worth naming in the write-up rather than leaving implicit.
    """
    if not closed_trades:
        return {
            "total_return_pct": 0.0,
            "sharpe": None,
            "max_drawdown_pct": 0.0,
            "n_trades": 0,
            "note": "No closed trades in this simulation window.",
        }

    equity = [starting_capital]
    for trade in closed_trades:
        equity.append(equity[-1] + trade["pnl"])
    equity = np.array(equity)

    returns = np.diff(equity) / equity[:-1]
    total_return_pct = float((equity[-1] / equity[0] - 1) * 100)

    sharpe = None
    if len(returns) > 1 and returns.std() > 0:
        sharpe = float(returns.mean() / returns.std() * np.sqrt(252))

    running_max = np.maximum.accumulate(equity)
    drawdowns = (equity - running_max) / running_max
    max_drawdown_pct = float(drawdowns.min() * 100)

    wins = [t for t in closed_trades if t["pnl"] > 0]

    return {
        "total_return_pct": round(total_return_pct, 2),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "n_trades": len(closed_trades),
        "win_rate_pct": round(len(wins) / len(closed_trades) * 100, 1),
        "final_equity": round(float(equity[-1]), 2),
    }


def simulate_historical(
    ticker: str = "AAPL",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    portfolio_value: float = 10_000.0,
    analyst_model: Optional[str] = None,
    verbose: bool = False,
) -> dict:
    """Run the full agent pipeline once per historical trading day.

    Args:
        ticker: e.g. "AAPL"
        start_date, end_date: "YYYY-MM-DD", inclusive. None = use the full
                               cached history's range.
        portfolio_value: starting capital for the simulation.
        analyst_model: override the Ollama model (None = analyst.py's default).
        verbose: print each day's cycle result (noisy for long ranges;
                 off by default for simulation).

    Returns:
        dict with the day-by-day results list and a final portfolio summary.
    """
    data_path = f"data/processed/indicators/{ticker}_indicators.csv"
    df = pd.read_csv(data_path, index_col=0, parse_dates=True)

    if start_date:
        df = df[df.index >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df.index <= pd.Timestamp(end_date)]

    if df.empty:
        raise ValueError(
            f"No rows for {ticker} in range {start_date} to {end_date} - "
            f"check the dates against the cached CSV's actual date range."
        )

    # ONE RiskManager for the whole simulation - positions and daily_pnl
    # persist across days, exactly like a real deployment would.
    risk_manager = RiskManager()
    app = build_graph()

    daily_results = []

    # Iterate over df.index (dates) directly, not df.iterrows() - we only
    # need the date string per day; collect_market_data re-reads and
    # truncates the CSV itself via as_of, so the row data here is unused.
    # (This also sidesteps the Hashable/Timestamp typing issue iterrows()
    # produces, since DatetimeIndex values are properly typed.)
    for ts in df.index:
        date_str = ts.strftime("%Y-%m-%d")

        # Reset the daily-loss circuit breaker at the start of each
        # simulated day, matching real-world daily reset behaviour.
        risk_manager.reset_daily()

        if verbose:
            print(f"\n--- Simulating {ticker} as of {date_str} ---")

        try:
            result = run_daily_cycle(
                ticker,
                app=app,
                risk_manager=risk_manager,
                portfolio_value=portfolio_value,
                analyst_model=analyst_model,
                simulate_date=date_str,
                verbose=verbose,
            )
            daily_results.append({"date": date_str, "result": result})
        except Exception as exc:
            daily_results.append({"date": date_str, "error": str(exc)})
            if verbose:
                print(f"  ERROR on {date_str}: {exc}")

    summary = risk_manager.portfolio_summary()
    metrics = compute_performance_metrics(risk_manager.closed_trades, portfolio_value)

    print(f"\n{'=' * 50}\nSIMULATION SUMMARY: {ticker} "
          f"({df.index[0].date()} to {df.index[-1].date()}, "
          f"{len(df)} trading days)\n{'=' * 50}")
    print(f"Portfolio: {summary}")
    print(f"Performance metrics: {metrics}")
    errors = [d for d in daily_results if "error" in d]
    if errors:
        print(f"Days with errors: {len(errors)} (see daily_results for detail)")

    return {
        "ticker": ticker,
        "start_date": df.index[0].strftime("%Y-%m-%d"),
        "end_date": df.index[-1].strftime("%Y-%m-%d"),
        "trading_days": len(df),
        "daily_results": daily_results,
        "portfolio_summary": summary,
        "performance_metrics": metrics,
        "closed_trades": risk_manager.closed_trades,
        "risk_manager": risk_manager,
    }

if __name__ == "__main__":
    result = simulate_historical("AAPL", verbose=False)

    errors = [d for d in result["daily_results"] if "error" in d]
    if errors:
        print(f"\n{len(errors)} days with errors:")
        for e in errors:
            print(e["date"], "->", e["error"])
