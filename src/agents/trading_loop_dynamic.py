# File: src/agents/trading_loop_dynamic.py
"""
Enhanced trading loop with dynamic watchlist management using a discovery layer.
Integrates the discovery layer (src/data/discovery.py) to generate a dynamic
ticker universe each day based on:
  1. 35 deterministic random S&P 500 candidates
  2. Google News RSS discovers ticker/company mentions from previous market day
  3. yfinance identifies previous-session market movers from S&P 500 universe
  4. Excludes open positions to avoid churning existing holdings
Then uses the existing watchlist manager to fetch news, score sentiment, and
generate active/waitlist arrays.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import pandas as pd

from src.data.watchlist_manager import (
    get_top_tickers_by_sentiment,
    update_trading_lists
)
from src.data.discovery import (
    get_sp500_universe,
    get_random_base,
    discover_tickers_from_news,
    discover_market_movers,
    build_candidate_base,
    build_company_map,
    fetch_previous_session_data,
    get_previous_trading_day
)
from src.agents.trading_loop import (
    AgentState,
    build_graph
)
from src.risk.risk_manager import RiskManager
from src.simulation.orchestrator import compute_performance_metrics
from src.utils.logger import log_session_summary, log_daily_watchlist


def _format_price(price: Optional[float]) -> str:
    """Safe price formatting - the original f'{price:8.2f}' crashed
    whenever price was None (which is the NORMAL value for any
    Unstable/HOLD/rejected ticker, not an edge case)."""
    return f"{price:8.2f}" if price is not None else "     n/a"


class DynamicTradingManager:
    """
    Manages dynamic watchlist based on news sentiment and position tracking.
    - Read news before market opens (via discovery layer + watchlist manager)
    - Hold top-N array (ranked by sentiment)
    - Open trades for the top active_list
    - As trades close, fill from waiting list
    - Keep waiting list filled from initial ranking
    """

    def __init__(
        self,
        ticker_universe: Optional[List[str]] = None,  # If None, will be generated dynamically
        max_active_positions: int = 10,
        waitlist_size: int = 10,
        max_articles_per_ticker: int = 5,
        total_article_cap: Optional[int] = 30,
        sentiment_model: str = "mistral",
        news_fetch_pause: float = 0.5,
        portfolio_value: float = 10_000,
        analyst_model: Optional[str] = None
    ):
        # If a fixed universe is provided, use it; otherwise generate dynamically each pre-market scan
        self.fixed_ticker_universe = ticker_universe
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

        # Placeholders for discovery logging
        self._last_universe: List[str] = []
        self._last_random_list: List[str] = []
        self._last_date: Optional[str] = None

        print(f"DynamicTradingManager initialized:")
        if self.fixed_ticker_universe is not None:
            print(f"  Using fixed universe: {len(self.fixed_ticker_universe)} tickers")
        else:
            print(f"  Universe will be generated dynamically each pre-market scan")
        print(f"  Max active positions: {max_active_positions}")
        print(f"  Waitlist size: {waitlist_size}")
        if total_article_cap is not None:
            print(f"  Total article budget: {total_article_cap} across the whole universe")

    def _get_discovery_components(self) -> dict:
        """Get all discovery components for logging and universe generation."""
        # Get current open positions to exclude from discovery
        open_positions = set(self.risk_manager.positions.keys())
        
        # Get previous trading day for data cutoff
        previous_day = get_previous_trading_day()
        
        # ------------------------------------------------------------------
        # 1. S&P 500 universe (excluding open positions)
        # ------------------------------------------------------------------
        all_sp500_symbols = get_sp500_universe()
        sp500_symbols = [s for s in all_sp500_symbols if s not in open_positions]
        print(f"Filtered S&P 500 universe (excluding open positions): {len(sp500_symbols)} symbols")
        
        # Need company names for Google News discovery
        sp500_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        sp500_df = pd.read_html(sp500_url)[0]
        ticker_to_company, company_to_ticker = build_company_map(sp500_df)
        # Remove open positions from company mapping lookup if needed
        for pos in open_positions:
            company_to_ticker = {k: v for k, v in company_to_ticker.items() if v != pos}
        
        # ------------------------------------------------------------------
        # 2. Random exploration (from filtered pool)
        # ------------------------------------------------------------------
        random_candidates = get_random_base(
            sp500_symbols, 
            target_date=None,  # uses today
            exclude_positions=open_positions
        )
        print(f"Random exploration sample: {len(random_candidates)} (excluded {len(open_positions)} positions)")
        
        # ------------------------------------------------------------------
        # 3. Download market data for entire filtered S&P 500
        # ------------------------------------------------------------------
        raw_sp500_data = fetch_previous_session_data(sp500_symbols, target_date=None)
        print(f"Downloaded market data for {len(sp500_symbols)} symbols")
        
        # ------------------------------------------------------------------
        # 4. Google News discovery
        # ------------------------------------------------------------------
        google_news = discover_tickers_from_news(
            sp500_symbols,
            ticker_to_company,
            company_to_ticker,
            target_date=None,
            exclude_positions=open_positions,
        )
        news_candidates = list(google_news.keys())[:10]  # NEWS_DISCOVERY_COUNT
        print(f"Google News discovered {len(google_news)} S&P 500 candidates.")
        
        # ------------------------------------------------------------------
        # 5. Previous-session market movers
        # ------------------------------------------------------------------
        market_movers = discover_market_movers(
            sp500_symbols, 
            raw_sp500_data, 
            target_date=None, 
            exclude_positions=open_positions
        )
        mover_candidates = list(market_movers.keys())  # MARKET_MOVER_COUNT
        print(f"Dynamic market movers discovered: {len(market_movers)}")
        
        # ------------------------------------------------------------------
        # 6. Build unique 50 candidates (guaranteed no open positions)
        # ------------------------------------------------------------------
        candidates = build_candidate_base(random_candidates, news_candidates, mover_candidates)
        # Absolute safety check against open positions
        candidates = [c for c in candidates if c not in open_positions]
        print(f"Final candidate base (excl. positions): {len(candidates)} symbols")
        
        return {
            'candidates': candidates,
            'random_list': random_candidates,
            'news_candidates': news_candidates,
            'mover_candidates': mover_candidates,
            'sp500_filtered': sp500_symbols,
            'previous_day': previous_day,
            'open_positions': open_positions
        }

    def _generate_dynamic_universe(self) -> List[str]:
        """Generate the ticker universe for today using the discovery layer.
        Excludes currently open positions to avoid churning.
        Returns a list of ticker symbols (aiming for ~50).
        """
        print("\n" + "="*60)
        print("GENERATING DYNAMIC TICKER UNIVERSE VIA DISCOVERY LAYER")
        print("="*60)
        
        components = self._get_discovery_components()
        self._last_universe = components['candidates']
        self._last_random_list = components['random_list']
        return self._last_universe

    def pre_market_scan(self) -> Tuple[List[str], List[str], Dict[str, float]]:
        """
        Fetch news, score sentiment, generate active/waitlist arrays.
        Uses discovery layer to generate the ticker universe, then
        delegates to the existing watchlist manager for news fetching,
        sentiment scoring, and list generation.
        """
        print("\n" + "="*60)
        print("PRE-MARKET SCAN: Fetching news and generating watchlists")
        print("="*60)

        # Determine ticker universe
        if self.fixed_ticker_universe is not None:
            tickers = self.fixed_ticker_universe
            # For static case, we still want to log something sensible for random list
            self._last_universe = tickers[:50]  # cap at 50 for logging consistency
            self._last_random_list = []  # no random exploration in static mode
            print(f"Using fixed ticker universe of {len(tickers)} symbols")
        else:
            tickers = self._generate_dynamic_universe()
            if not tickers:
                print("WARNING: Dynamic universe generation returned empty list. Falling back to default watchlist.")
                # Fallback to a small default list to avoid crashing
                tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
                self._last_universe = tickers[:50]
                self._last_random_list = []

        # Limit universe size to reasonable bounds (e.g., 50-100) as per original spec
        max_universe = 100
        if len(tickers) > max_universe:
            print(f"Universe size {len(tickers)} exceeds max {max_universe}. Truncating.")
            tickers = tickers[:max_universe]
            # Also truncate the stored universe for logging
            self._last_universe = tickers[:50]
        print(f"Final ticker universe size: {len(tickers)}")
        
        # Store date for logging
        today_str = datetime.now().strftime("%Y-%m-%d")
        self._last_date = today_str

        # Delegate to existing watchlist manager for news fetching, sentiment scoring, and list generation
        active_list, waitlist, sentiment_scores = get_top_tickers_by_sentiment(
            tickers=tickers,
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

        # Log start-of-day watchlist snapshot
        log_daily_watchlist(
            date=today_str,
            top50=self._last_universe,
            random_list=self._last_random_list,
            top10_active=self.active_list,
            open_trades=[],  # no open trades yet at start of day
        )

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
            all_tickers=self.fixed_ticker_universe if self.fixed_ticker_universe is not None else self._last_universe,
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

        # Log end-of-day watchlist snapshot (open trades at close of day)
        if self._last_date:
            # The logger expects serializable dictionaries, while the risk
            # manager stores Position objects.
            open_trades_at_close = [
                vars(position) for position in self.risk_manager.positions.values()
            ]
            log_daily_watchlist(
                date=self._last_date,
                top50=self._last_universe,
                random_list=self._last_random_list,
                top10_active=self.active_list,
                open_trades=open_trades_at_close,
            )

        return self.daily_results

    def _run_active_list_with_shared_manager(self) -> Tuple[List[Dict[str, Any]], RiskManager]:
        """Run the active list sequentially against THIS session's
        self.risk_manager directly (bypassing run_watchlist's internal
        manager), so positions genuinely persist in the object this
        class reports on afterward."""
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
        into a single SKIPPED bucket."""
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
        uses, computed from this session's real, shared RiskManager."""
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