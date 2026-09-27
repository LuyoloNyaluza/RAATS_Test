# File: src/agents/trading_loop_dynamic.py
"""
Enhanced trading loop with dynamic watchlist management.

FIXES in this version, against the original:

1. CRASH FIXED: `result.get("executed_price", 0.0)` looked safe but
   wasn't - stability_node explicitly sets executed_price=None (the key
   EXISTS with value None), so .get()'s default was never used, and
   f"{None:8.2f}" crashed. Now formatted with an explicit None check.

2. SUMMARY NOW REFLECTS REAL TRADES: the original created
   self.risk_manager but never used it - run_watchlist_concurrent gives
   each thread its OWN throwaway RiskManager (by design, for thread
   safety), so self.risk_manager.portfolio_summary() always reported
   zero trades even when positions genuinely opened. Switched to
   run_watchlist (sequential), which already correctly shares ONE
   RiskManager across all tickers - the tradeoff is losing concurrent
   Ollama calls in exchange for a summary that's actually true.

3. REAL PERFORMANCE METRICS: reuses
   src.simulation.orchestrator.compute_performance_metrics (the same
   Sharpe/drawdown/return calculation run_simulation.py's report uses),
   rather than only ever printing a raw portfolio_summary() dict.

4. THREE-WAY CATEGORIZATION: results are now split into EXECUTED
   (a trade opened), HOLD (the LLM said no - a real signal, not a
   block), and UNSTABLE (the stability filter deferred it) - the
   original only distinguished EXECUTED vs SKIPPED, conflating "LLM
   said no" with "market was too volatile to even ask."

5. JSONL LOGGING: pre-market scan results and the end-of-session
   summary are now written to the weekly JSONL log (via log_scan /
   log_session_summary), not just printed to a terminal that scrolls
   away.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from src.data.watchlist_manager import (
    get_top_tickers_by_sentiment,
    update_trading_lists
)
from src.agents.trading_loop import (
    AgentState,
    build_graph
)
from src.risk.risk_manager import RiskManager
from src.simulation.orchestrator import compute_performance_metrics
from src.utils.logger import log_session_summary


def _format_price(price: Optional[float]) -> str:
    """Safe price formatting - the original f'{price:8.2f}' crashed
    whenever price was None (which is the NORMAL value for any
    Unstable/HOLD/rejected ticker, not an edge case)."""
    return f"{price:8.2f}" if price is not None else "     n/a"


class DynamicTradingManager:
    """
    Manages dynamic watchlist based on news sentiment and position tracking.
    - Read news before market opens
    - Hold top-N array (ranked by sentiment)
    - Open trades for the top active_list
    - As trades close, fill from waiting list
    - Keep waiting list filled from initial ranking
    """

    def __init__(
        self,
        ticker_universe: List[str],
        max_active_positions: int = 10,
        waitlist_size: int = 10,
        max_articles_per_ticker: int = 5,
        total_article_cap: Optional[int] = 30,
        sentiment_model: str = "mistral",
        news_fetch_pause: float = 0.5,
        portfolio_value: float = 10_000,
        analyst_model: Optional[str] = None
    ):
        self.ticker_universe = ticker_universe
        self.max_active_positions = max_active_positions
        self.waitlist_size = waitlist_size
        self.max_articles_per_ticker = max_articles_per_ticker
        self.total_article_cap = total_article_cap
        self.sentiment_model = sentiment_model
        self.news_fetch_pause = news_fetch_pause
        self.portfolio_value = portfolio_value
        self.analyst_model = analyst_model

        self.active_list: List[str] = []
        self.waitlist: List[str] = []
        self._initial_active: List[str] = []
        self._initial_waitlist: List[str] = []
        self.all_sentiment_scores: Dict[str, float] = {}

        # ONE RiskManager for the whole session - see fix #2 in the
        # module docstring for why this is now the single source of
        # truth for the final summary, instead of being unused.
        self.risk_manager = RiskManager()
        self.closed_positions_today: List[str] = []
        self.daily_results: List[Dict[str, Any]] = []

        self.shared_app = build_graph()

        print(f"DynamicTradingManager initialized:")
        print(f"  Universe: {len(ticker_universe)} tickers")
        print(f"  Max active positions: {max_active_positions}")
        print(f"  Waitlist size: {waitlist_size}")
        if total_article_cap is not None:
            print(f"  Total article budget: {total_article_cap} across the whole universe")

    def pre_market_scan(self) -> Tuple[List[str], List[str], Dict[str, float]]:
        """Fetch news, score sentiment, generate active/waitlist arrays."""
        print("\n" + "="*60)
        print("PRE-MARKET SCAN: Fetching news and generating watchlists")
        print("="*60)

        active_list, waitlist, sentiment_scores = get_top_tickers_by_sentiment(
            tickers=self.ticker_universe,
            top_n=self.max_active_positions,
            waitlist_n=self.waitlist_size,
            max_articles_per_ticker=self.max_articles_per_ticker,
            total_article_cap=self.total_article_cap,
            model_name=self.sentiment_model,
            pause=self.news_fetch_pause
        )

        self.active_list = active_list
        self.waitlist = waitlist
        self.all_sentiment_scores = sentiment_scores

        print(f"\nPRE-MARKET RESULTS:")
        print(f"  Active list ({len(self.active_list)}): {self.active_list}")
        print(f"  Waiting list ({len(self.waitlist)}): {self.waitlist}")

        return self.active_list, self.waitlist, self.all_sentiment_scores

    def update_lists_after_trades(self, newly_closed_positions: List[str]) -> None:
        """Update trading lists when positions close during the day."""
        if not newly_closed_positions:
            return

        print(f"\n{len(newly_closed_positions)} positions closed: {newly_closed_positions}")
        self.closed_positions_today.extend(newly_closed_positions)

        updated_active, updated_waitlist = update_trading_lists(
            closed_positions=newly_closed_positions,
            current_active=self.active_list,
            current_waitlist=self.waitlist,
            all_tickers=self.ticker_universe,
            sentiment_scores=self.all_sentiment_scores,
            top_n=self.max_active_positions,
            waitlist_n=self.waitlist_size
        )

        self.active_list = updated_active
        self.waitlist = updated_waitlist

        print(f"UPDATED LISTS:")
        print(f"  Active list ({len(self.active_list)}): {self.active_list}")
        print(f"  Waiting list ({len(self.waitlist)}): {self.waitlist}")

    def get_trading_tickers(self) -> List[str]:
        return self.active_list.copy()

    def run_trading_session(self, simulate_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Run a complete trading session with dynamic watchlist management."""
        print(f"\n{'='*60}")
        print(f"STARTING TRADING SESSION")
        if simulate_date:
            print(f"Simulated date: {simulate_date}")
        print(f"{'='*60}")

        self.pre_market_scan()

        if self.active_list:
            print(f"\nRunning sequential trading for {len(self.active_list)} active "
                  f"positions (one shared portfolio, so the final summary is accurate)...")
            results, self.risk_manager = self._run_active_list_with_shared_manager()

            self.daily_results.extend(results)

            newly_closed = [
                ticker for r in results
                if r.get("closed_trade")
                and isinstance((ticker := r.get("ticker")), str)
                and ticker not in self.closed_positions_today
            ]

            if newly_closed:
                self.update_lists_after_trades(newly_closed)
        else:
            print("WARNING: No active positions to trade!")
            results = []

        self._print_session_summary()

        return self.daily_results

    def _run_active_list_with_shared_manager(self) -> Tuple[List[Dict[str, Any]], RiskManager]:
        """Run the active list sequentially against THIS session's
        self.risk_manager directly (bypassing run_watchlist's internal
        manager), so positions genuinely persist in the object this
        class reports on afterward.
        """
        from src.agents.trading_loop import run_daily_cycle

        results = []
        for ticker in self.active_list:
            try:
                result = run_daily_cycle(
                    ticker,
                    app=self.shared_app,
                    risk_manager=self.risk_manager,
                    portfolio_value=self.portfolio_value,
                    analyst_model=self.analyst_model,
                    verbose=True,
                )
                results.append(result)
            except Exception as exc:
                print(f"  ERROR processing {ticker}: {exc}")
                results.append({
                    "ticker": ticker, "signal": "ERROR", "confidence": 0.0,
                    "executed": False, "executed_price": None,
                    "risk_reason": str(exc), "stability_status": "n/a",
                })
        return results, self.risk_manager

    def _categorize_results(self) -> Dict[str, List[str]]:
        """Split today's results into EXECUTED / HOLD / UNSTABLE, so the
        report can show "these were on hold" distinctly from "these were
        blocked by the stability filter" - the original conflated both
        into a single SKIPPED bucket.
        """
        executed, hold, unstable = [], [], []
        for r in self.daily_results:
            ticker = r.get("ticker", "UNKNOWN")
            if r.get("executed"):
                executed.append(ticker)
            elif r.get("stability_status") == "Unstable":
                unstable.append(ticker)
            else:
                hold.append(ticker)
        return {"executed": executed, "hold": hold, "unstable": unstable}

    def _print_session_summary(self) -> None:
        """Print (and log) a summary of the trading session, using the
        SAME performance-metrics calculation run_simulation.py's report
        uses, computed from this session's real, shared RiskManager.
        """
        print(f"\n{'='*60}")
        print(f"TRADING SESSION SUMMARY")
        print(f"{'='*60}")

        print(f"Pre-market scan completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Final active list ({len(self.active_list)}): {self.active_list}")
        print(f"Final waiting list ({len(self.waitlist)}): {self.waitlist}")
        print(f"Closed positions today ({len(self.closed_positions_today)}): {self.closed_positions_today}")

        categories = self._categorize_results()
        print(f"\nExecuted ({len(categories['executed'])}): {categories['executed']}")
        print(f"On HOLD  ({len(categories['hold'])}): {categories['hold']}")
        print(f"Unstable ({len(categories['unstable'])}): {categories['unstable']}")

        if self.daily_results:
            print(f"\n{'Ticker':<8} | {'Status':<10} | {'Signal':<8} | {'Price':>10}")
            for result in self.daily_results:
                ticker = result.get("ticker", "UNKNOWN")
                if result.get("executed"):
                    status = "EXECUTED"
                elif result.get("stability_status") == "Unstable":
                    status = "UNSTABLE"
                else:
                    status = "HOLD"
                signal = result.get("llm_signal", result.get("signal", "N/A")) or "N/A"
                price = _format_price(result.get("executed_price"))
                print(f"  {ticker:<6} | {status:<10} | {signal:<8} | {price}")

        # Real metrics, from the shared RiskManager's actual closed
        # trades - same function run_simulation.py's report uses.
        metrics = compute_performance_metrics(
            self.risk_manager.closed_trades, self.portfolio_value
        )
        print(f"\nPortfolio: {self.risk_manager.portfolio_summary()}")
        print(f"Performance metrics: {metrics}")

        log_session_summary(
            active_list=self.active_list,
            waitlist=self.waitlist,
            hold_list=categories["hold"],
            metrics=metrics,
        )

    def get_waitlist_opportunities(self, count: int = 5) -> List[Tuple[str, float]]:
        excluded = set(self.active_list) | set(self.closed_positions_today)
        available = [
            (ticker, score)
            for ticker, score in self.all_sentiment_scores.items()
            if ticker not in excluded
        ]
        available.sort(key=lambda x: x[1], reverse=True)
        return available[:count]


def run_dynamic_trading_session(
    ticker_universe: List[str],
    simulate_date: Optional[str] = None,
    max_active_positions: int = 10,
    waitlist_size: int = 10,
    max_articles_per_ticker: int = 5,
    total_article_cap: Optional[int] = 30,
    sentiment_model: str = "mistral",
    news_fetch_pause: float = 0.5,
    portfolio_value: float = 10_000,
    analyst_model: Optional[str] = None
) -> Dict[str, Any]:
    """Convenience function to run a complete dynamic trading session."""
    print("Initializing Dynamic Trading Manager...")

    manager = DynamicTradingManager(
        ticker_universe=ticker_universe,
        max_active_positions=max_active_positions,
        waitlist_size=waitlist_size,
        max_articles_per_ticker=max_articles_per_ticker,
        total_article_cap=total_article_cap,
        sentiment_model=sentiment_model,
        news_fetch_pause=news_fetch_pause,
        portfolio_value=portfolio_value,
        analyst_model=analyst_model
    )

    manager._initial_active = manager.active_list.copy()
    manager._initial_waitlist = manager.waitlist.copy()

    results = manager.run_trading_session(simulate_date=simulate_date)

    session_results = {
        "manager": manager,
        "results": results,
        "active_list": manager.active_list,
        "waitlist": manager.waitlist,
        "closed_positions": manager.closed_positions_today,
        "sentiment_scores": manager.all_sentiment_scores,
        "waitlist_opportunities": manager.get_waitlist_opportunities(10)
    }

    return session_results


if __name__ == "__main__":
    print("=== Dynamic Trading System Demo ===")

    # Deduplicated (the original list had PG and IBM listed twice)
    demo_universe = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
        "META", "NVDA", "NFLX", "AMD", "INTC",
        "CSCO", "ADBE", "CRM", "ORCL", "IBM",
        "QCOM", "TXN", "HON", "UNH", "JNJ",
        "PG", "JPM", "BAC", "WFC", "C",
        "V", "MA", "DIS", "NKE", "SBUX",
        "MCD", "WMT", "TGT", "COST", "HD",
        "LOW", "CL", "KMB", "GE",
        "CAT", "MMM", "BA", "F", "GM",
        "XOM", "CVX", "COP", "EOG", "SLB",
    ]
    print(f"Universe: {len(demo_universe)} tickers")

    try:
        session = run_dynamic_trading_session(
            ticker_universe=demo_universe,
            max_active_positions=10,
            waitlist_size=10,
            total_article_cap=30,
            news_fetch_pause=0.5,
            portfolio_value=10_000
        )

        print(f"\n=== SESSION COMPLETE ===")
        print(f"Active list: {session['active_list']}")
        print(f"Waiting list: {session['waitlist']}")
        print(f"Closed positions: {session['closed_positions']}")
        print(f"Top waitlist opportunities: {session['waitlist_opportunities']}")

    except Exception as e:
        print(f"Error running demo: {e}")
        print("Make sure:")
        print("1. Ollama is running (ollama serve)")
        print("2. Required models are installed (ollama pull mistral)")
        print("3. All required Python packages are installed")
        print("4. You have internet access for news fetching")

    print("\nDemo completed.")
