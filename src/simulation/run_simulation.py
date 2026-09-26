
import argparse

from src.simulation.orchestrator import simulate_historical


def run_week_simulation(
    ticker: str = "AAPL",
    start_date: str = "2026-09-01",
    end_date: str = "2026-09-07",
    portfolio_value: float = 10_000.0,
    verbose: bool = True,
) -> dict:
    """Run a historical simulation over [start_date, end_date] and print
    a short performance report.

    Args:
        ticker: e.g. "AAPL"
        start_date, end_date: "YYYY-MM-DD", inclusive.
        portfolio_value: starting capital.
        verbose: print each day's cycle result (noisy for long ranges).

    Returns:
        The full result dict from simulate_historical() - daily_results,
        performance_metrics, closed_trades, portfolio_summary, etc.
    """
    result = simulate_historical(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        portfolio_value=portfolio_value,
        verbose=verbose,
    )

    metrics = result["performance_metrics"]

    print(f"\n{'=' * 50}\nPERFORMANCE REPORT: {ticker} "
          f"({result['start_date']} to {result['end_date']})\n{'=' * 50}")
    print(f"Trading days simulated : {result['trading_days']}")
    print(f"Closed trades          : {metrics['n_trades']}")
    print(f"Win rate               : {metrics.get('win_rate_pct', 'n/a')}%")
    print(f"Total return           : {metrics['total_return_pct']}%")
    print(f"Sharpe ratio           : {metrics['sharpe']}")
    print(f"Max drawdown           : {metrics['max_drawdown_pct']}%")
    print(f"Final equity           : {metrics.get('final_equity', 'n/a')}")

    errors = [d for d in result["daily_results"] if "error" in d]
    if errors:
        print(f"\n{len(errors)} day(s) with errors:")
        for e in errors:
            print(f"  {e['date']} -> {e['error']}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a RAATS historical simulation.")
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--start", default="2026-09-01", help="YYYY-MM-DD")
    parser.add_argument("--end", default="2026-09-07", help="YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--quiet", action="store_true", help="Suppress per-day cycle output")
    args = parser.parse_args()

    run_week_simulation(
        ticker=args.ticker,
        start_date=args.start,
        end_date=args.end,
        portfolio_value=args.capital,
        verbose=not args.quiet,
    )
