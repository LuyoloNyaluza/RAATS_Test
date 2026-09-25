from typing import List, Optional

import pandas as pd

from src.agents.trading_loop import build_graph, run_daily_cycle
from src.risk.risk_manager import RiskManager


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

    print(f"\n{'=' * 50}\nSIMULATION SUMMARY: {ticker} "
          f"({df.index[0].date()} to {df.index[-1].date()}, "
          f"{len(df)} trading days)\n{'=' * 50}")
    print(f"Portfolio: {summary}")
    print(f"Closed trades: {len(risk_manager.closed_trades)}")
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
        "closed_trades": risk_manager.closed_trades,
        "risk_manager": risk_manager,  # kept for further analysis (Sharpe/drawdown, next)
    }


if __name__ == "__main__":
    result = simulate_historical("AAPL", verbose=False)