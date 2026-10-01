"""
Dynamic trading loop using the three arrays produced by discovery.py.

Input arrays:

1. top_50_performing
   - Complete top-50 performance universe.

2. top_10
   - First 10 tickers from the top-50.
   - News articles are attached to these tickers.

3. waiting_list
   - Positions 11-30 from the top-50.
   - No news fetching is performed for these tickers.

The trading loop uses:
    top_50_performing -> complete trading universe
    top_10           -> initial active list
    waiting_list     -> replacement/waiting list
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

import pandas as pd

from src.agents.trading_loop import (
    build_graph,
    run_daily_cycle,
)
from src.risk.risk_manager import RiskManager
from src.simulation.orchestrator import compute_performance_metrics
from src.utils.logger import log_session_summary


# ==========================================
# HELPERS
# ==========================================

def _format_price(price: Optional[float]) -> str:
    """Safely format an execution price."""

    return (
        f"{price:8.2f}"
        if price is not None
        else "     n/a"
    )


def _classify_result(
    result: Dict[str, Any]
) -> str:
    """Classify one ticker's trading result."""

    if (
        result.get("signal") == "ERROR"
        or result.get("stability_status") == "n/a"
    ):
        return "error"

    if result.get("closed_trade"):
        return "closed"

    if result.get("executed"):
        return "executed"

    reason = str(
        result.get("risk_reason") or ""
    )

    if reason.startswith(
        "Position already open"
    ):
        return "monitoring"

    if result.get(
        "stability_status"
    ) == "Unstable":
        return "unstable"

    if result.get(
        "llm_signal"
    ) == "HOLD":
        return "hold"

    return "blocked"


# ==========================================
# ARRAY CONVERSION
# ==========================================

def _extract_ticker(
    item: Any
) -> Optional[str]:
    """
    Extract a ticker from either:

    - DataFrame row
    - dictionary
    - string
    """

    if isinstance(item, str):
        return item.upper().strip()

    if isinstance(item, dict):

        ticker = item.get("Ticker")

        if ticker is None:
            ticker = item.get("ticker")

        if ticker is None:
            return None

        return str(ticker).upper().strip()

    return None


def _array_to_tickers(
    data: Any
) -> List[str]:
    """
    Convert an input array/DataFrame into a simple
    list of ticker symbols.
    """

    tickers = []

    if data is None:
        return tickers

    if isinstance(data, pd.DataFrame):

        if "Ticker" not in data.columns:
            raise ValueError(
                "Expected DataFrame column 'Ticker'."
            )

        values = data["Ticker"].tolist()

    elif isinstance(data, (list, tuple)):

        values = data

    else:

        raise TypeError(
            "Ticker array must be a DataFrame, "
            "list or tuple."
        )

    for item in values:

        ticker = _extract_ticker(item)

        if ticker and ticker not in tickers:
            tickers.append(ticker)

    return tickers


def _build_performance_scores(
    top_50_performing: Any
) -> Dict[str, float]:
    """
    Build scores from the previous-session return.

    These scores replace the old sentiment-ranking
    dependency because discovery.py has already
    ranked the universe.
    """

    scores = {}

    if isinstance(
        top_50_performing,
        pd.DataFrame
    ):

        if (
            "Ticker" not in top_50_performing.columns
            or
            "Previous_Day_Return_Pct"
            not in top_50_performing.columns
        ):
            return scores

        for row in top_50_performing.itertuples(
            index=False
        ):

            ticker = str(
                row.Ticker
            ).upper().strip()

            value = getattr(
                row,
                "Previous_Day_Return_Pct"
            )

            if value is None:
                continue

            try:
                scores[ticker] = float(value)
            except (
                TypeError,
                ValueError
            ):
                continue

    elif isinstance(
        top_50_performing,
        (list, tuple)
    ):

        for item in top_50_performing:

            if not isinstance(item, dict):
                continue

            ticker = _extract_ticker(item)

            value = item.get(
                "Previous_Day_Return_Pct"
            )

            if ticker is None:
                continue

            if value is None:
                continue

            try:
                scores[ticker] = float(value)
            except (
                TypeError,
                ValueError
            ):
                continue

    return scores


def _build_news_by_ticker(
    top_10: Any
) -> Dict[str, Dict[str, Any]]:
    """Index news fields attached to top-10 ticker records."""

    if isinstance(top_10, pd.DataFrame):
        records = top_10.to_dict("records")
    elif isinstance(top_10, (list, tuple)):
        records = top_10
    else:
        return {}

    news_by_ticker: Dict[str, Dict[str, Any]] = {}
    for item in records:
        if not isinstance(item, dict):
            continue

        ticker = _extract_ticker(item)
        if ticker:
            news_by_ticker[ticker] = {
                "yfinance_news": item.get("yfinance_news", []),
                "google_news": item.get("google_news", []),
                "sentiment_summary": item.get("sentiment_summary", {}),
            }

    return news_by_ticker


# ==========================================
# DYNAMIC TRADING MANAGER
# ==========================================

class DynamicTradingManager:

    """
    Manages the three discovery arrays.

    top_50_performing:
        Complete trading universe.

    top_10:
        Initial active trading list.

    waiting_list:
        Positions 11-30 used as replacements.
    """

    def __init__(
        self,
        top_50_performing: Any,
        top_10: Any,
        waiting_list: Any,
        portfolio_value: float = 10_000,
        analyst_model: Optional[str] = None,
    ):

        # ----------------------------------
        # Store original arrays
        # ----------------------------------
        self.news_by_ticker = _build_news_by_ticker(
    top_10
)
        self.top_50_performing = (
            top_50_performing
        )

        self.top_10 = top_10

        self.initial_waiting_list = (
            waiting_list
        )

        # ----------------------------------
        # Convert to ticker lists
        # ----------------------------------

        self.ticker_universe = (
            _array_to_tickers(
                top_50_performing
            )
        )

        self.active_list = (
            _array_to_tickers(
                top_10
            )
        )

        self.waitlist = (
            _array_to_tickers(
                waiting_list
            )
        )

        # ----------------------------------
        # Configuration
        # ----------------------------------

        self.max_active_positions = len(
            self.active_list
        )

        self.waitlist_size = len(
            self.waitlist
        )

        self.portfolio_value = (
            portfolio_value
        )

        self.analyst_model = (
            analyst_model
        )

        # ----------------------------------
        # Performance ranking
        # ----------------------------------

        self.all_sentiment_scores = (
            _build_performance_scores(
                top_50_performing
            )
        )

        # ----------------------------------
        # Session state
        # ----------------------------------

        self.closed_positions_today = []

        self.daily_results = []

        self._initial_active = (
            self.active_list.copy()
        )

        self._initial_waitlist = (
            self.waitlist.copy()
        )

        # ----------------------------------
        # Shared trading graph
        # ----------------------------------

        self.shared_app = build_graph()

        # ONE RiskManager for the entire
        # session.
        self.risk_manager = RiskManager()

        # ----------------------------------
        # Diagnostics
        # ----------------------------------

        print(
            "\nDynamicTradingManager initialized:"
        )

        print(
            f"  Top-50 universe: "
            f"{len(self.ticker_universe)} tickers"
        )

        print(
            f"  Active top-10: "
            f"{len(self.active_list)} tickers"
        )

        print(
            f"  Waiting list: "
            f"{len(self.waitlist)} tickers"
        )

    # ======================================
    # PRE-MARKET ARRAYS
    # ======================================

    def pre_market_scan(
        self
    ) -> Tuple[
        List[str],
        List[str],
        Dict[str, float]
    ]:
        """
        Use discovery.py output directly.

        No additional news fetching or
        sentiment ranking occurs here.
        """

        print(
            "\n"
            + "=" * 60
        )

        print(
            "PRE-MARKET DISCOVERY ARRAYS"
        )

        print(
            "=" * 60
        )

        print(
            f"Top-50 universe "
            f"({len(self.ticker_universe)}):"
        )

        print(
            self.ticker_universe
        )

        print(
            f"\nActive top-10 "
            f"({len(self.active_list)}):"
        )

        print(
            self.active_list
        )

        print(
            f"\nWaiting list "
            f"({len(self.waitlist)}):"
        )

        print(
            self.waitlist
        )

        return (
            self.active_list,
            self.waitlist,
            self.all_sentiment_scores,
        )

    # ======================================
    # UPDATE AFTER CLOSED TRADES
    # ======================================

    def update_lists_after_trades(
        self,
        newly_closed_positions: List[str]
    ) -> None:
        """
        Fill an empty active slot from the
        waiting list.

        Waiting-list order is preserved.
        """

        if not newly_closed_positions:
            return

        print(
            f"\n"
            f"{len(newly_closed_positions)} "
            f"positions closed: "
            f"{newly_closed_positions}"
        )

        self.closed_positions_today.extend(
            newly_closed_positions
        )

        # Remove closed tickers from active list.
        for ticker in newly_closed_positions:

            if ticker in self.active_list:
                self.active_list.remove(
                    ticker
                )

        # ----------------------------------
        # Fill active positions from waitlist
        # ----------------------------------

        while (
            len(self.active_list)
            < self.max_active_positions
            and self.waitlist
        ):

            next_ticker = (
                self.waitlist.pop(0)
            )

            if (
                next_ticker
                not in self.active_list
                and
                next_ticker
                not in self.closed_positions_today
            ):

                self.active_list.append(
                    next_ticker
                )

                print(
                    f"  Promoted from waiting "
                    f"list: {next_ticker}"
                )

        print(
            "\nUPDATED LISTS:"
        )

        print(
            f"  Active list "
            f"({len(self.active_list)}): "
            f"{self.active_list}"
        )

        print(
            f"  Waiting list "
            f"({len(self.waitlist)}): "
            f"{self.waitlist}"
        )

    # ======================================
    # ACTIVE TICKERS
    # ======================================

    def get_trading_tickers(
        self
    ) -> List[str]:

        return self.active_list.copy()

    # ======================================
    # TRADING SESSION
    # ======================================

    def run_trading_session(
        self,
        simulate_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Run one complete trading session.
        """

        print(
            "\n"
            + "=" * 60
        )

        print(
            "STARTING DYNAMIC TRADING SESSION"
        )

        if simulate_date:
            print(
                f"Simulated date: "
                f"{simulate_date}"
            )

        print(
            "=" * 60
        )

        self.pre_market_scan()

        if self.active_list:

            print(
                f"\nRunning trading for "
                f"{len(self.active_list)} "
                f"active tickers..."
            )

            if simulate_date:

                print(
                    f"NOTE: simulate_date="
                    f"{simulate_date}"
                )

            results, self.risk_manager = (
                self._run_active_list_with_shared_manager(
                    simulate_date
                )
            )

            self.daily_results.extend(
                results
            )

            newly_closed = [
                ticker
                for result in results
                if result.get(
                    "closed_trade"
                )
                and isinstance(
                    (
                        ticker :=
                        result.get("ticker")
                    ),
                    str
                )
                and ticker
                not in self.closed_positions_today
            ]

            if newly_closed:

                self.update_lists_after_trades(
                    newly_closed
                )

        else:

            print(
                "WARNING: "
                "No active positions to trade!"
            )

            results = []

        self._print_session_summary()

        return self.daily_results

    # ======================================
    # RUN ACTIVE LIST
    # ======================================

    def _run_active_list_with_shared_manager(
        self,
        simulate_date: Optional[str] = None
    ) -> Tuple[
        List[Dict[str, Any]],
        RiskManager
    ]:
        """
        Run each active ticker sequentially
        using one shared RiskManager.
        """

        results = []

        for ticker in self.active_list:
            try:
                news_by_ticker = getattr(self, "news_by_ticker", {})
                news = news_by_ticker.get(
    ticker,
    {
        "yfinance_news": [],
        "google_news": [],
        "sentiment_summary": {},
    },
)
                result = run_daily_cycle(
                    ticker,
                    app=self.shared_app,
                    risk_manager=self.risk_manager,
                    portfolio_value=self.portfolio_value,
                    analyst_model=self.analyst_model,
                    simulate_date=simulate_date,
                    verbose=True,
                    discovery_news=news,
                )

                results.append(
                    result
                )

            except Exception as exc:

                print(
                    f"  ERROR processing "
                    f"{ticker}: {exc}"
                )

                results.append({
                    "ticker": ticker,
                    "signal": "ERROR",
                    "confidence": 0.0,
                    "executed": False,
                    "executed_price": None,
                    "risk_reason": str(exc),
                    "stability_status": "n/a",
                })

        return (
            results,
            self.risk_manager
        )

    # ======================================
    # CATEGORIZE RESULTS
    # ======================================

    def _categorize_results(
        self
    ) -> Dict[str, List[str]]:

        categories = {
            "executed": [],
            "closed": [],
            "monitoring": [],
            "hold": [],
            "blocked": [],
            "unstable": [],
            "error": [],
        }

        for result in self.daily_results:

            category = _classify_result(
                result
            )

            categories[
                category
            ].append(
                result.get(
                    "ticker",
                    "UNKNOWN"
                )
            )

        return categories

    # ======================================
    # SESSION SUMMARY
    # ======================================

    def _print_session_summary(
        self
    ) -> None:

        print(
            "\n"
            + "=" * 60
        )

        print(
            "TRADING SESSION SUMMARY"
        )

        print(
            "=" * 60
        )

        print(
            "Pre-market discovery completed at: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        print(
            f"Top-50 universe "
            f"({len(self.ticker_universe)}): "
            f"{self.ticker_universe}"
        )

        print(
            f"Final active list "
            f"({len(self.active_list)}): "
            f"{self.active_list}"
        )

        print(
            f"Final waiting list "
            f"({len(self.waitlist)}): "
            f"{self.waitlist}"
        )

        print(
            f"Closed positions today "
            f"({len(self.closed_positions_today)}): "
            f"{self.closed_positions_today}"
        )

        categories = (
            self._categorize_results()
        )

        labels = [
            (
                "executed",
                "Executed (new position)"
            ),
            (
                "closed",
                "Closed"
            ),
            (
                "monitoring",
                "Already open, monitored"
            ),
            (
                "hold",
                "On HOLD (LLM said no)"
            ),
            (
                "blocked",
                "INVEST but blocked"
            ),
            (
                "unstable",
                "Deferred, market unstable"
            ),
            (
                "error",
                "Errors"
            ),
        ]

        print()

        for key, label in labels:

            if (
                categories[key]
                or key
                in (
                    "executed",
                    "hold",
                    "unstable"
                )
            ):

                print(
                    f"{label:<34} "
                    f"({len(categories[key])}): "
                    f"{categories[key]}"
                )

        if self.daily_results:

            print(
                f"\n"
                f"{'Ticker':<7} | "
                f"{'Outcome':<10} | "
                f"{'Signal':<7} | "
                f"{'Conf':>4} | "
                f"{'Price':>9} | Reason"
            )

            for result in self.daily_results:

                ticker = result.get(
                    "ticker",
                    "UNKNOWN"
                )

                outcome = (
                    _classify_result(
                        result
                    ).upper()
                )

                signal = (
                    result.get(
                        "llm_signal"
                    )
                    or "-"
                )

                conf = result.get(
                    "confidence"
                )

                conf_str = (
                    f"{conf:.1f}"
                    if isinstance(
                        conf,
                        (int, float)
                    )
                    and signal != "-"
                    else "  -"
                )

                price = _format_price(
                    result.get(
                        "executed_price"
                    )
                )

                reason = str(
                    result.get(
                        "risk_reason"
                    )
                    or ""
                )[:70]

                print(
                    f"{ticker:<7} | "
                    f"{outcome:<10} | "
                    f"{signal:<7} | "
                    f"{conf_str:>4} | "
                    f"{price:>9} | "
                    f"{reason}"
                )

        metrics = (
            compute_performance_metrics(
                self.risk_manager.closed_trades,
                self.portfolio_value
            )
        )

        print(
            f"\nPortfolio: "
            f"{self.risk_manager.portfolio_summary()}"
        )

        print(
            f"Performance metrics: "
            f"{metrics}"
        )

        log_session_summary(
            active_list=self.active_list,
            waitlist=self.waitlist,
            hold_list=categories["hold"],
            metrics=metrics,
        )

    # ======================================
    # WAITLIST OPPORTUNITIES
    # ======================================

    def get_waitlist_opportunities(
        self,
        count: int = 5
    ) -> List[Tuple[str, float]]:

        excluded = (
            set(self.active_list)
            |
            set(self.closed_positions_today)
        )

        available = [
            (
                ticker,
                score
            )
            for ticker, score
            in self.all_sentiment_scores.items()
            if ticker not in excluded
        ]

        available.sort(
            key=lambda x: x[1],
            reverse=True
        )

        return available[:count]
def _replace_holds_until_all_invest(self):
    """
    Remove HOLD candidates from the active list and replace them
    from the waiting list until all active candidates are INVEST.
    """

    hold_history = []
    replacement_round = 0

    while True:
        replacement_round += 1

        print(
            f"\n========== ACTIVE LIST ROUND {replacement_round} =========="
        )

        results = []

        # Analyse current active list
        for ticker in list(self.active_list):

            print(f"\nAnalyzing {ticker}...")

            news = self.news_by_ticker.get(
                ticker,
                {
                    "yfinance_news": [],
                    "google_news": [],
                    "sentiment_summary": {},
                },
            )

            result = run_daily_cycle(
                ticker,
                app=self.shared_app,
                risk_manager=self.risk_manager,
                portfolio_value=self.portfolio_value,
                analyst_model=self.analyst_model,
                simulate_date=self.simulate_date,
                verbose=True,
                discovery_news=news,
                treat_as_closed=True,
            )

            results.append(
                {
                    "ticker": ticker,
                    "result": result,
                }
            )

        # Find HOLD candidates
        holds = []

        for item in results:
            ticker = item["ticker"]
            result = item["result"]

            if self._classify_result(result) == "HOLD":
                holds.append(ticker)

        # No HOLDs means active list is complete
        if not holds:
            print("\nAll active candidates are INVEST.")
            break

        print(
            f"\nHOLD candidates: {len(holds)}"
        )

        # Keep record for final summary
        for ticker in holds:
            hold_history.append(
                {
                    "ticker": ticker,
                    "round": replacement_round,
                }
            )

        # Remove HOLDs
        self.active_list = [
            ticker
            for ticker in self.active_list
            if ticker not in holds
        ]

        # Replace each HOLD from waiting list
        replacements = []

        for _ in holds:

            if not self.waitlist:
                print(
                    "\nWaiting list exhausted. "
                    "Cannot replace remaining HOLD candidates."
                )
                break

            replacement = self.waitlist.pop(0)

            self.active_list.append(replacement)
            replacements.append(replacement)

        if not replacements:
            break

        print(
            f"\nReplacing HOLDs with: {replacements}"
        )

        # Fresh article retrieval + scoring
        for ticker in replacements:

            print(
                f"\nFetching fresh articles for {ticker}..."
            )

            news = self._fetch_and_score_articles(
                ticker
            )

            self.news_by_ticker[ticker] = news

            print(
                f"{ticker}: "
                f"{len(news.get('yfinance_news', []))} "
                f"Yahoo/yfinance articles, "
                f"{len(news.get('google_news', []))} "
                f"Google articles"
            )

    return hold_history

# ==========================================
# PUBLIC ENTRY POINT
# ==========================================

def run_dynamic_trading_session(
    top_50_performing: Any,
    top_10: Any,
    waiting_list: Any,
    simulate_date: Optional[str] = None,
    portfolio_value: float = 10_000,
    analyst_model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the dynamic trading session using the
    three arrays generated by discovery.py.

    Parameters
    ----------
    top_50_performing:
        Complete top-50 performance array.

    top_10:
        Top-10 array. News can be attached to
        each ticker.

    waiting_list:
        Positions 11-30.

    simulate_date:
        Optional historical simulation date.

    portfolio_value:
        Starting portfolio value.

    analyst_model:
        Optional LLM analyst model.
    """

    print(
        "Initializing Dynamic Trading Manager..."
    )

    manager = DynamicTradingManager(
        top_50_performing=top_50_performing,
        top_10=top_10,
        waiting_list=waiting_list,
        portfolio_value=portfolio_value,
        analyst_model=analyst_model,
    )

    results = manager.run_trading_session(
        simulate_date=simulate_date
    )

    session_results = {
        "manager": manager,
        "results": results,

        # Original discovery arrays
        "top_50_performing":
            manager.top_50_performing,

        "top_10":
            manager.top_10,

        "initial_waiting_list":
            manager.initial_waiting_list,

        # Current trading state
        "active_list":
            manager.active_list,

        "waitlist":
            manager.waitlist,

        "closed_positions":
            manager.closed_positions_today,

        "performance_scores":
            manager.all_sentiment_scores,

        "waitlist_opportunities":
            manager.get_waitlist_opportunities(10),
    }

    return session_results


# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":

    print(
        "\n=== RAATS DYNAMIC TRADING SYSTEM ==="
    )

    try:

        # ----------------------------------
        # STEP 1: RUN DISCOVERY
        # ----------------------------------

        from src.data import discovery

        (
            top_50_performing,
            top_10,
            waiting_list,
        ) = discovery.main()

        print(
            "\nDiscovery completed."
        )

        print(
            f"Top-50 array: "
            f"{len(top_50_performing)}"
        )

        print(
            f"Top-10 array: "
            f"{len(top_10)}"
        )

        print(
            f"Waiting-list array: "
            f"{len(waiting_list)}"
        )

        # ----------------------------------
        # STEP 2: PASS ALL THREE ARRAYS
        # ----------------------------------

        session = run_dynamic_trading_session(
            top_50_performing=top_50_performing,
            top_10=top_10,
            waiting_list=waiting_list,
            portfolio_value=10_000,
        )

        # ----------------------------------
        # STEP 3: FINAL OUTPUT
        # ----------------------------------

        print(
            "\n=== SESSION COMPLETE ==="
        )

        print(
            f"Active list: "
            f"{session['active_list']}"
        )

        print(
            f"Waiting list: "
            f"{session['waitlist']}"
        )

        print(
            f"Closed positions: "
            f"{session['closed_positions']}"
        )

    except Exception as e:

        print(
            f"\nERROR: {e}"
        )

        raise