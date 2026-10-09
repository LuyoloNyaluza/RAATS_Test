"""
Dynamic trading loop using the three arrays produced by discovery.py.

Input arrays:

1. top_50_performing
   - Complete top-50 performance universe.

2. top_10
   - First 10 tickers from the top-50.
   - News articles are already attached and scored.

3. waiting_list
   - Positions 11-30 from the top-50.
   - News is fetched only when a ticker is promoted
     as a replacement.

Trading process:

    discovery.py
        |
        v
    top_50_performing
        |
        +----> top_10 --------> analyse
        |
        +----> waiting_list --> replacement discovery
                                      |
                                      v
                              3 yfinance articles
                              2 Google articles
                                      |
                                      v
                                sentiment scoring
                                      |
                                      v
                                  analyse
                                      |
                                      v
                              INVEST / HOLD / other

The loop continues until:
    final_invest == max_active_positions

or:

    waiting_list is exhausted.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

import pandas as pd

from src.agents.trading_loop import (
    build_graph,
    run_daily_cycle,
)

from src.data.discovery import (
    get_yfinance_news,
    get_google_news_headlines,
    score_top_10_news,
)

from src.risk.risk_manager import RiskManager
from src.simulation.orchestrator import compute_performance_metrics
from src.utils.logger import log_session_summary
from src.utils.logger import (
    log_cycle,
    log_error,
    log_sentiment_analysis,
)


# ==========================================
# HELPERS
# ==========================================

def _format_price(
    price: Optional[float],
) -> str:
    """Safely format an execution price."""

    return (
        f"{price:8.2f}"
        if price is not None
        else "     n/a"
    )


def _classify_result(
    result: Dict[str, Any],
) -> str:
    """
    Classify one trading result.

    This classification is used by the dynamic
    replacement logic and session summary.
    """

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

    if (
        result.get("stability_status")
        == "Unstable"
    ):
        return "unstable"

    if (
        result.get("llm_signal")
        == "HOLD"
    ):
        return "hold"

    if (
        result.get("llm_signal")
        == "INVEST"
    ):
        return "invest_blocked"

    return "blocked"


def _extract_ticker(
    item: Any,
) -> Optional[str]:
    """
    Extract a ticker from:

    - DataFrame row dictionary
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

        return str(
            ticker
        ).upper().strip()

    return None


def _array_to_tickers(
    data: Any,
) -> List[str]:
    """
    Convert an input DataFrame/list/tuple
    into a list of ticker symbols.
    """

    tickers = []

    if data is None:
        return tickers

    if isinstance(
        data,
        pd.DataFrame,
    ):

        if "Ticker" not in data.columns:
            raise ValueError(
                "Expected DataFrame column 'Ticker'."
            )

        values = data[
            "Ticker"
        ].tolist()

    elif isinstance(
        data,
        (list, tuple),
    ):

        values = data

    else:

        raise TypeError(
            "Ticker array must be a DataFrame, "
            "list or tuple."
        )

    for item in values:

        ticker = _extract_ticker(
            item
        )

        if (
            ticker
            and ticker not in tickers
        ):
            tickers.append(
                ticker
            )

    return tickers


def _build_performance_scores(
    top_50_performing: Any,
) -> Dict[str, float]:
    """
    Build previous-session performance
    scores from discovery.py.
    """

    scores = {}

    if isinstance(
        top_50_performing,
        pd.DataFrame,
    ):

        required = {
            "Ticker",
            "Previous_Day_Return_Pct",
        }

        if not required.issubset(
            top_50_performing.columns
        ):
            return scores

        for row in (
            top_50_performing.itertuples(
                index=False
            )
        ):

            ticker = str(
                row.Ticker
            ).upper().strip()

            value = getattr(
                row,
                "Previous_Day_Return_Pct",
            )

            if value is None:
                continue

            try:
                scores[ticker] = float(
                    value
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

    elif isinstance(
        top_50_performing,
        (list, tuple),
    ):

        for item in top_50_performing:

            if not isinstance(
                item,
                dict,
            ):
                continue

            ticker = _extract_ticker(
                item
            )

            value = item.get(
                "Previous_Day_Return_Pct"
            )

            if (
                ticker is None
                or value is None
            ):
                continue

            try:
                scores[ticker] = float(
                    value
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

    return scores


def _build_news_by_ticker(
    top_10: Any,
) -> Dict[str, Dict[str, Any]]:
    """
    Index the already discovered and scored
    Top-10 news.
    """

    if isinstance(
        top_10,
        pd.DataFrame,
    ):

        records = top_10.to_dict(
            "records"
        )

    elif isinstance(
        top_10,
        (list, tuple),
    ):

        records = top_10

    else:

        return {}

    news_by_ticker = {}

    for item in records:

        if not isinstance(
            item,
            dict,
        ):
            continue

        ticker = _extract_ticker(
            item
        )

        if ticker:

            news_by_ticker[ticker] = {
                "yfinance_news":
                    item.get(
                        "yfinance_news",
                        [],
                    ),

                "google_news":
                    item.get(
                        "google_news",
                        [],
                    ),

                "sentiment_summary":
                    item.get(
                        "sentiment_summary",
                        {},
                    ),
            }

    return news_by_ticker


# ==========================================
# DYNAMIC TRADING MANAGER
# ==========================================

class DynamicTradingManager:

    """
    Manages:

        top_50_performing
        top_10
        waiting_list

    The top-10 are analysed first.

    HOLD candidates are removed.

    Replacement candidates are taken from
    the waiting list and receive fresh news
    discovery before analysis.
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
        # Original discovery arrays
        # ----------------------------------

        self.top_50_performing = (
            top_50_performing
        )

        self.top_10 = top_10

        self.initial_waiting_list = (
            waiting_list
        )

        # ----------------------------------
        # Existing Top-10 news
        # ----------------------------------

        self.news_by_ticker = (
            _build_news_by_ticker(
                top_10
            )
        )

        # ----------------------------------
        # Convert arrays to ticker lists
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
        # Pointer to next ticker in universe for replenishing waiting list
        # ----------------------------------
        self._next_universe_index = len(self.active_list) + len(self.waitlist)

        # ----------------------------------
        # Target number of final INVEST
        # ----------------------------------

        self.max_active_positions = len(
            self.active_list
        )

        # ----------------------------------
        # Configuration
        # ----------------------------------

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
        # Previous-session performance
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

        self.final_invest = []

        self.hold_history = []

        self.replacement_history = []

        # Store simulation date
        self.simulate_date = None

        # ----------------------------------
        # Initial copies
        # ----------------------------------

        self._initial_active = (
            self.active_list.copy()
        )

        self._initial_waitlist = (
            self.waitlist.copy()
        )

        # ----------------------------------
        # Shared graph
        # ----------------------------------

        self.shared_app = build_graph()

        # ----------------------------------
        # One RiskManager for session
        # ----------------------------------

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
            f"  Initial active list: "
            f"{len(self.active_list)} tickers"
        )

        print(
            f"  Waiting list: "
            f"{len(self.waitlist)} tickers"
        )

        print(
            f"  Target final INVEST: "
            f"{self.max_active_positions}"
        )

    # ======================================
    # PRE-MARKET SCAN
    # ======================================

    def pre_market_scan(
        self,
    ) -> Tuple[
        List[str],
        List[str],
        Dict[str, float],
    ]:

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
            f"\nInitial active top-10 "
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
    # FRESH NEWS DISCOVERY
    # ======================================

    def _fetch_and_score_articles(
        self,
        ticker: str,
        simulate_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Discover and score fresh news for a
        replacement ticker.

        Uses the SAME discovery.py functions
        as the initial Top-10 process:

            3 yfinance articles
            2 Google News articles

        The articles are then passed through
        score_top_10_news().
        """

        ticker = (
            str(ticker)
            .upper()
            .strip()
        )

        print(
            f"\n"
            f"  Discovering fresh news for "
            f"{ticker}..."
        )

        # ----------------------------------
        # yfinance
        # ----------------------------------

        print(
            f"    Fetching 3 yfinance articles..."
        )

        yfinance_news = (
            get_yfinance_news(
                ticker,
                max_results=3,
            )
        )

        # ----------------------------------
        # Google News
        # ----------------------------------

        print(
            f"    Fetching 2 Google News articles..."
        )

        google_news = (
            get_google_news_headlines(
                ticker,
                max_results=2,
            )
        )

        print(
            f"    Retrieved: "
            f"{len(yfinance_news)} yfinance + "
            f"{len(google_news)} Google"
        )

        # ----------------------------------
        # Build same record structure used
        # by discovery.py
        # ----------------------------------

        performance = (
            self.all_sentiment_scores.get(
                ticker,
                0.0,
            )
        )

        record = {
            "Ticker": ticker,

            "Previous_Day_Return_Pct":
                float(performance),

            "yfinance_news":
                yfinance_news,

            "google_news":
                google_news,
        }

        # ----------------------------------
        # Score through discovery.py
        # ----------------------------------

        print(
            f"    Scoring discovered news..."
        )

        scored_records = (
            score_top_10_news(
                [record]
            )
        )

        # ----------------------------------
        # No scored record
        # ----------------------------------

        if not scored_records:

            return {
                "yfinance_news":
                    yfinance_news,

                "google_news":
                    google_news,

                "sentiment_summary": {
                    "overall": "neutral",
                    "score": 0.0,
                    "positive": 0,
                    "negative": 0,
                    "neutral": 0,
                    "total": 0,
                },
            }

        scored = (
            scored_records[0]
        )

        news = {
            "yfinance_news":
                scored.get(
                    "yfinance_news",
                    [],
                ),

            "google_news":
                scored.get(
                    "google_news",
                    [],
                ),

            "sentiment_summary":
                scored.get(
                    "sentiment_summary",
                    {},
                ),
        }

        # ----------------------------------
        # Store fresh news
        # ----------------------------------

        self.news_by_ticker[
            ticker
        ] = news

        summary = news[
            "sentiment_summary"
        ]

        print(
            f"    Sentiment: "
            f"{summary.get('overall', 'neutral')}"
        )

        print(
            f"    Score: "
            f"{summary.get('score', 0.0):+.4f}"
        )

        return news

    # ======================================
    # RUN ONE ACTIVE LIST
    # ======================================

    def _run_active_list_with_shared_manager(
        self,
        simulate_date: Optional[str] = None,
    ) -> Tuple[
        List[Dict[str, Any]],
        RiskManager,
    ]:
        """
        Analyse the current active list.

        Each ticker is analysed once during
        the current round.

        Previously resolved INVEST candidates
        are not placed back into active_list,
        so they are not analysed again.
        """

        results = []

        current_active = (
            self.active_list.copy()
        )

        for ticker in current_active:

            # ----------------------------------
            # Skip already resolved INVEST
            # ----------------------------------

            if ticker in self.final_invest:

                print(
                    f"\nSkipping {ticker}: "
                    f"already resolved INVEST."
                )

                continue

            print(
                "\n"
                + "-" * 60
            )

            print(
                f"Analyzing {ticker}..."
            )

            print(
                "-" * 60
            )

            try:

                news = (
                    self.news_by_ticker.get(
                        ticker,
                        {
                            "yfinance_news": [],
                            "google_news": [],
                            "sentiment_summary": {},
                        },
                    )
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
                    "ticker":
                        ticker,

                    "signal":
                        "ERROR",

                    "llm_signal":
                        "ERROR",

                    "confidence":
                        0.0,

                    "executed":
                        False,

                    "executed_price":
                        None,

                    "risk_reason":
                        str(exc),

                    "stability_status":
                        "n/a",
                })

        return (
            results,
            self.risk_manager,
        )

    # ======================================
    # PROCESS ROUND RESULTS
    # ======================================

    def _process_round_results(
        self,
        results: List[Dict[str, Any]],
        replacement_round: int,
    ) -> List[str]:
        """
        Process the results from one analysis
        round.

        INVEST candidates are permanently moved
        into final_invest.

        HOLD and unresolved candidates are
        removed from active_list and can be
        replaced.
        """

        replacements_needed = []

        for result in results:

            ticker = result.get(
                "ticker"
            )

            if not ticker:
                continue

            llm_signal = (
                result.get(
                    "llm_signal"
                )
                or result.get(
                    "signal"
                )
                or ""
            )

            llm_signal = str(
                llm_signal
            ).upper().strip()

            # ----------------------------------
            # INVEST
            # ----------------------------------

            if llm_signal == "INVEST":

                if ticker not in (
                    self.final_invest
                ):

                    self.final_invest.append(
                        ticker
                    )

                if ticker in (
                    self.active_list
                ):

                    self.active_list.remove(
                        ticker
                    )

                print(
                    f"\n{ticker}: INVEST"
                )

                print(
                    f"  Added to final INVEST "
                    f"({len(self.final_invest)}/"
                    f"{self.max_active_positions})"
                )

                continue

            # ----------------------------------
            # HOLD
            # ----------------------------------

            if llm_signal == "HOLD":

                self.hold_history.append({
                    "ticker":
                        ticker,

                    "round":
                        replacement_round,
                })

                print(
                    f"\n{ticker}: HOLD"
                )

                print(
                    f"  Removing from active list."
                )

                if ticker in (
                    self.active_list
                ):

                    self.active_list.remove(
                        ticker
                    )

                replacements_needed.append(
                    ticker
                )

                continue

            # ----------------------------------
            # Unresolved result
            # ----------------------------------

            print(
                f"\n{ticker}: "
                f"{llm_signal or 'NO SIGNAL'}"
            )

            category = (
                _classify_result(
                    result
                )
            )

            print(
                f"  Result category: "
                f"{category}"
            )

            if ticker in (
                self.active_list
            ):

                self.active_list.remove(
                    ticker
                )

            replacements_needed.append(
                ticker
            )

        return replacements_needed

    # ======================================
    # GET REPLACEMENTS
    # ======================================

    # ----------------------------------
    # Helper to replenish waiting list from universe
    # ----------------------------------
    def _replenish_waitlist_from_universe(self, count: int) -> None:
        """Add up to `count` new tickers from ticker_universe to waiting list,
        skipping those already in active list, final_invest, waiting list,
        or closed positions.
        """
        added = 0
        while added < count and self._next_universe_index < len(self.ticker_universe):
            ticker = self.ticker_universe[self._next_universe_index]
            self._next_universe_index += 1
            if (
                ticker not in self.active_list
                and ticker not in self.final_invest
                and ticker not in self.waitlist
                and ticker not in self.closed_positions_today
            ):
                self.waitlist.append(ticker)
                added += 1

    def _get_replacements(
        self,
        number_needed: int,
    ) -> List[str]:
        """
        Pull replacement candidates from the
        waiting list.

        Fresh news is discovered and scored
        BEFORE the candidate is added to the
        active list.
        """

        replacements = []

        while (
            len(replacements)
            < number_needed
            and self.waitlist
        ):

            ticker = (
                self.waitlist.pop(0)
            )

            # ----------------------------------
            # Safety checks
            # ----------------------------------

            if ticker in self.final_invest:
                continue

            if ticker in self.active_list:
                continue

            if ticker in (
                self.closed_positions_today
            ):
                continue

            # ----------------------------------
            # Fresh discovery
            # ----------------------------------

            print(
                "\n"
                + "=" * 60
            )

            print(
                f"DISCOVERING REPLACEMENT: "
                f"{ticker}"
            )

            print(
                "=" * 60
            )

            try:
                news = (
                    self._fetch_and_score_articles(
                        ticker,
                        self.simulate_date,
                    )
                )
            except Exception as exc:
                log_error(
                    ticker=ticker,
                    date=(
                        self.simulate_date
                        if self.simulate_date
                        else datetime.now().strftime(
                            "%Y-%m-%d"
                        )
                    ),
                    error=str(exc),
                    stage="replacement_discovery",
                    context={
                        "round": getattr(
                            self,
                            "current_round",
                            None,
                        ),
                        "final_invest": self.final_invest,
                        "waiting_list": self.waitlist,
                    },
                )
                continue

            self.news_by_ticker[
                ticker
            ] = news

            # ----------------------------------
            # Add only after fresh discovery
            # ----------------------------------

            self.active_list.append(
                ticker
            )

            replacements.append(
                ticker
            )

            self.replacement_history.append(
                ticker
            )

            print(
                f"\nReplacement added: "
                f"{ticker}"
            )

        # ----------------------------------
        # Replenish waiting list from universe for each replacement used
        # ----------------------------------
        self._replenish_waitlist_from_universe(len(replacements))
        return replacements
    # ======================================
    # TRADING SESSION
    # ======================================

    def run_trading_session(
        self,
        simulate_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Run the dynamic trading session.

        Round 1:

            Analyse initial Top-10.

        Subsequent rounds:

            HOLD/unresolved candidates are removed.

            Waiting-list replacements receive fresh
            news discovery and sentiment scoring.

            Only the replacements are analysed.

        Final INVEST candidates are never
        analysed again.
        """

        self.simulate_date = (
            simulate_date
        )

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

        replacement_round = 0

        # ==================================
        # MAIN RESOLUTION LOOP
        # ==================================

        while (
            len(self.final_invest)
            < self.max_active_positions
        ):

            # ----------------------------------
            # No candidates left
            # ----------------------------------

            if not self.active_list:

                print(
                    "\nNo unresolved active "
                    "candidates remain."
                )

                if not self.waitlist:

                    print(
                        "Waiting list exhausted."
                    )

                    break

                # Need enough candidates to
                # reach the target.
                vacancies = (
                    self.max_active_positions
                    - len(self.final_invest)
                )

                self._get_replacements(
                    vacancies
                )

                if not self.active_list:
                    break

            # ----------------------------------
            # Determine round
            # ----------------------------------

            replacement_round += 1

            print(
                "\n"
                + "=" * 60
            )

            print(
                f"TRADING ROUND "
                f"{replacement_round}"
            )

            print(
                "=" * 60
            )

            print(
                f"Final INVEST: "
                f"{len(self.final_invest)}/"
                f"{self.max_active_positions}"
            )

            print(
                f"Candidates to analyse: "
                f"{len(self.active_list)}"
            )

            print(
                f"Waiting candidates: "
                f"{len(self.waitlist)}"
            )

            print(
                f"Active list: "
                f"{self.active_list}"
            )

            # ----------------------------------
            # Analyse current active candidates
            # ----------------------------------

            results, self.risk_manager = (
                self._run_active_list_with_shared_manager(
                    simulate_date
                )
            )

            self.daily_results.extend(
                results
            )

            # ----------------------------------
            # Process results
            # ----------------------------------

            self._process_round_results(
                results,
                replacement_round,
            )

            # ----------------------------------
            # Target reached
            # ----------------------------------

            if (
                len(self.final_invest)
                >= self.max_active_positions
            ):

                print(
                    "\nTarget final INVEST "
                    "count reached."
                )

                break

            # ----------------------------------
            # Calculate vacancies
            # ----------------------------------

            vacancies = (
                self.max_active_positions
                - len(self.final_invest)
                - len(self.active_list)
            )

            # ----------------------------------
            # Fill vacancies
            # ----------------------------------

            if vacancies > 0:

                print(
                    f"\nVacancies to fill: "
                    f"{vacancies}"
                )

                replacements = (
                    self._get_replacements(
                        vacancies
                    )
                )

                if not replacements:

                    print(
                        "\nNo more replacement "
                        "candidates available."
                    )

                    break

                print(
                    f"\nNew replacement "
                    f"candidates: "
                    f"{replacements}"
                )

            # ----------------------------------
            # Safety condition
            # ----------------------------------

            if (
                not self.active_list
                and not self.waitlist
            ):

                print(
                    "\nActive and waiting lists "
                    "are exhausted."
                )

                break

        # ==================================
        # FINAL SUMMARY
        # ==================================

        self._print_session_summary()

        return self.daily_results

    # ======================================
    # SESSION SUMMARY
    # ======================================

    def _categorize_results(
        self,
    ) -> Dict[str, List[str]]:

        categories = {
            "executed": [],
            "closed": [],
            "monitoring": [],
            "hold": [],
            "invest_blocked": [],
            "blocked": [],
            "unstable": [],
            "error": [],
        }

        for result in (
            self.daily_results
        ):

            category = (
                _classify_result(
                    result
                )
            )

            ticker = result.get(
                "ticker",
                "UNKNOWN",
            )

            categories[
                category
            ].append(
                ticker
            )

        return categories

    def _print_session_summary(
        self,
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
            "Discovery completed at: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        print(
            f"\nFinal INVEST "
            f"({len(self.final_invest)}/"
            f"{self.max_active_positions}):"
        )

        print(
            self.final_invest
        )

        print(
            f"\nRemaining active "
            f"({len(self.active_list)}):"
        )

        print(
            self.active_list
        )

        print(
            f"\nRemaining waiting list "
            f"({len(self.waitlist)}):"
        )

        print(
            self.waitlist
        )

        print(
            f"\nHOLD history "
            f"({len(self.hold_history)}):"
        )

        print(
            self.hold_history
        )

        print(
            f"\nReplacement history "
            f"({len(self.replacement_history)}):"
        )

        print(
            self.replacement_history
        )

        print(
            f"\nClosed positions today "
            f"({len(self.closed_positions_today)}):"
        )

        print(
            self.closed_positions_today
        )

        # ==================================
        # Current open trades
        # ==================================

        open_positions = (
            self.risk_manager.positions
        )

        open_trades = len(
            open_positions
        )

        print(
            f"\nOpen trades: "
            f"{open_trades}"
        )

        if open_positions:

            print(
                "Open trade tickers:"
            )

            print(
                list(
                    open_positions.keys()
                )
            )

        # ==================================
        # Categories
        # ==================================

        categories = (
            self._categorize_results()
        )

        print(
            "\nRESULT CATEGORIES"
        )

        print(
            f"  Executed: "
            f"{len(categories['executed'])} "
            f"{categories['executed']}"
        )

        print(
            f"  HOLD: "
            f"{len(categories['hold'])} "
            f"{categories['hold']}"
        )

        print(
            f"  INVEST but blocked: "
            f"{len(categories['invest_blocked'])} "
            f"{categories['invest_blocked']}"
        )

        print(
            f"  Unstable: "
            f"{len(categories['unstable'])} "
            f"{categories['unstable']}"
        )

        print(
            f"  Errors: "
            f"{len(categories['error'])} "
            f"{categories['error']}"
        )

        # ==================================
        # Detailed result table
        # ==================================

        if self.daily_results:

            print(
                "\n"
                + "-" * 95
            )

            print(
                f"{'Ticker':<8} | "
                f"{'Outcome':<16} | "
                f"{'Signal':<8} | "
                f"{'Conf':>5} | "
                f"{'Price':>9} | "
                f"Reason"
            )

            print(
                "-" * 95
            )

            for result in (
                self.daily_results
            ):

                ticker = result.get(
                    "ticker",
                    "UNKNOWN",
                )

                outcome = (
                    _classify_result(
                        result
                    )
                ).upper()

                signal = (
                    result.get(
                        "llm_signal"
                    )
                    or result.get(
                        "signal"
                    )
                    or "-"
                )

                confidence = result.get(
                    "confidence"
                )

                if isinstance(
                    confidence,
                    (int, float),
                ):

                    conf_str = (
                        f"{confidence:.2f}"
                    )

                else:

                    conf_str = "-"

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
                )[:55]

                print(
                    f"{ticker:<8} | "
                    f"{outcome:<16} | "
                    f"{signal:<8} | "
                    f"{conf_str:>5} | "
                    f"{price:>9} | "
                    f"{reason}"
                )

        # ==================================
        # Performance metrics
        # ==================================

        metrics = (
            compute_performance_metrics(
                self.risk_manager.closed_trades,
                self.portfolio_value,
            )
        )

        # Add current open-trade count
        # without changing the existing
        # compute_performance_metrics()
        # function.

        metrics = dict(
            metrics
        )

        metrics[
            "open_trades"
        ] = open_trades

        metrics[
            "closed_trades"
        ] = len(
            self.risk_manager.closed_trades
        )

        metrics[
            "final_invest"
        ] = len(
            self.final_invest
        )

        print(
            "\n"
            + "=" * 60
        )

        print(
            "PORTFOLIO"
        )

        print(
            "=" * 60
        )

        print(
            self.risk_manager.portfolio_summary()
        )

        print(
            "\nPerformance metrics:"
        )

        print(
            metrics
        )

        # ==================================
        # Logger
        # ==================================

        log_session_summary(
            active_list=self.active_list,
            waitlist=self.waitlist,
            hold_list=categories[
                "hold"
            ],
            metrics=metrics,
        )

    # ======================================
    # WAITLIST OPPORTUNITIES
    # ======================================

    def get_waitlist_opportunities(
        self,
        count: int = 5,
    ) -> List[
        Tuple[str, float]
    ]:

        excluded = (
            set(
                self.active_list
            )
            |
            set(
                self.final_invest
            )
            |
            set(
                self.closed_positions_today
            )
        )

        available = [
            (
                ticker,
                score,
            )

            for ticker, score
            in self.all_sentiment_scores.items()

            if ticker not in excluded
        ]

        available.sort(
            key=lambda x: x[1],
            reverse=True,
        )

        return available[
            :count
        ]


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
    Run the dynamic trading session using
    the three arrays generated by discovery.py.
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

    results = (
        manager.run_trading_session(
            simulate_date=simulate_date
        )
    )

    session_results = {

        "manager":
            manager,

        "results":
            results,

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

        "final_invest":
            manager.final_invest,

        "hold_history":
            manager.hold_history,

        "replacement_history":
            manager.replacement_history,

        "closed_positions":
            manager.closed_positions_today,

        "open_trades":
            len(
                manager.risk_manager.positions
            ),

        "performance_scores":
            manager.all_sentiment_scores,

        "waitlist_opportunities":
            manager.get_waitlist_opportunities(
                10
            ),
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
        # STEP 2: RUN DYNAMIC TRADING
        # ----------------------------------

        session = (
            run_dynamic_trading_session(
                top_50_performing=
                    top_50_performing,

                top_10=
                    top_10,

                waiting_list=
                    waiting_list,

                portfolio_value=
                    10_000,
            )
        )

        # ----------------------------------
        # STEP 3: FINAL OUTPUT
        # ----------------------------------

        print(
            "\n"
            + "=" * 60
        )

        print(
            "SESSION COMPLETE"
        )

        print(
            "=" * 60
        )

        print(
            f"Final INVEST "
            f"({len(session['final_invest'])}): "
            f"{session['final_invest']}"
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

        print(
            f"Open trades: "
            f"{session['open_trades']}"
        )

    except Exception as e:

        print(
            f"\nERROR: {e}"
        )

        raise