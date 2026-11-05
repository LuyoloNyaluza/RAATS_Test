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

Batch 1 is complete when EITHER:

    A. final_invest == max_active_positions   (10 approved candidates), OR
    B. ALL THREE sources are exhausted at the same time:
         - the top 50 (including the one-time reserve added to it),
         - the waiting list, and
         - the top-10 active candidates.

When the top 50 and the waiting list run out with fewer than 5 tickers in
final_invest, the one-time reserve (10 trending + 10 world indices + 10 most active)
is added to the top 50; it feeds the waiting list and the top 10 the same way.
With fewer than 10 approved candidates (even 0) the hand-over to the main agent
goes ahead with what is available - it never waits for 10.
"""

import os
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
from src.data.rgr_screen import screen_candidate
from src.data.mt5_sizing import build_order_plan, format_order_plan
from src.utils.trade_text import trade_rows, format_rows
from src.data.reserve_tickers import build_reserve, normalize as _norm_ticker
from src.data.mt5_bridge import (
    enrich_final_invest, get_account_balance, notify_insufficient_balance,
    initialize_mt5, shutdown_mt5, is_mt5_tradable,
)
from src.data.macro_events import is_trade_blocked_by_macro, MacroEventChecker
from src.notifications.discord_notifier import DiscordNotifier
from src.agents.middleware.summarization_middleware import SummarizationMiddleware

# Trades are blocked below this MT5 balance (env RAATS_MIN_BALANCE overrides).
MIN_ACCOUNT_BALANCE = float(os.environ.get("RAATS_MIN_BALANCE", "20"))


# One-time reserve: used only when the top 50 and the waiting list are exhausted AND
# fewer than this many tickers reached the final INVEST list.
MIN_FINAL_INVEST_BEFORE_RESERVE = 5


def balance_status(balance: Optional[float]) -> Optional[Dict[str, Any]]:
    """None when the balance is fine (or unknown); otherwise the shortfall details."""
    if balance is None or balance > MIN_ACCOUNT_BALANCE:
        return None                     # strictly greater than the minimum (e.g. > $20)
    return {
        "balance": float(balance),
        "min_balance": MIN_ACCOUNT_BALANCE,
        "shortfall": max(MIN_ACCOUNT_BALANCE - float(balance), 0.01),
    }


def check_minimum_balance() -> Optional[Dict[str, Any]]:
    """Read the MT5 balance and return balance_status() of it.

    Independent of enable_mt5: the guard used to run only when enable_mt5 was True, so
    a $0.74 account was still allowed to trade. An unreadable balance does not block.
    """
    balance = get_account_balance()
    if balance is None:
        print("\u26a0\ufe0f  MT5 balance unavailable - minimum-balance guard NOT applied.")
        return None
    return balance_status(balance)


def report_blocked_session(
    balance_check: Dict[str, Any], tickers: Optional[List[str]] = None
) -> None:
    """Print the blocked-session summary, alert on Discord, and record the session."""
    shortfall = balance_check["shortfall"]
    print("\n" + "=" * 60)
    print("TRADING SESSION SUMMARY - BLOCKED")
    print("=" * 60)
    print(f"Account balance:   ${balance_check['balance']:,.2f}")
    print(f"Minimum required:  ${balance_check['min_balance']:,.2f}")
    print(f"Short by:          ${shortfall:,.2f}")
    print("Open trades:       0 (no trades were opened)")
    if tickers:
        print(f"Blocked tickers:   {', '.join(tickers)}")
    print(f"\nPlease deposit at least ${shortfall:,.2f} to resume trading.")

    # Discord alert + data/approvals/insufficient_funds_<week>.jsonl
    notify_insufficient_balance(
        balance_check["balance"], balance_check["min_balance"], tickers
    )
    try:
        SummarizationMiddleware(
            starting_balance=balance_check["balance"]
        ).record_blocked_session(
            balance=balance_check["balance"],
            min_balance=balance_check["min_balance"],
            shortfall=shortfall,
            tickers=tickers,
        )
    except Exception as exc:
        print(f"  WARNING: blocked-session record failed ({exc})")
from src.simulation.orchestrator import compute_performance_metrics
from src.utils.logger import (
    log_daily_watchlist,
    log_session_summary,
)
from src.utils.logger import (
    log_error,
)

import json
from pathlib import Path


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
        enable_rgr_gate: bool = True,
        rgr_threshold: float = 0.0,
        rgr_hold_days: int = 5,
        enable_mt5: bool = False,
    ):

        # ----------------------------------
        # RGR gate / MT5 configuration
        # ----------------------------------

        self.enable_rgr_gate = enable_rgr_gate
        self.rgr_threshold = rgr_threshold
        self.rgr_hold_days = rgr_hold_days
        self.enable_mt5 = enable_mt5

        self.rgr_results = {}      # ticker -> diagnostics
        self.rgr_rejected = []     # tickers refused entry to active list
        self.mt5_data = {}         # ticker -> MT5 info for final INVEST

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

        # Batch metadata is populated by the batch coordinator.
        self.batch_no: Optional[int] = None
        self.batch_id: Optional[str] = None

        # One-time reserve (30 extra tickers) state
        self.reserve_loaded = False
        self.session_blocked = False      # set when balance / approval stops the first session
        self.mt5_order_plan = {}
        self.reserve_info = {}

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

                # INVEST is a trade, not just a name: show BUY/SELL, entry, SL and TP.
                print(
                    format_rows(
                        trade_rows(
                            self.risk_manager,
                            [ticker],
                            getattr(self, "mt5_order_plan", None),
                        ),
                        indent="  ",
                    )
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
    # RGR GATE
    # ======================================

    def _passes_rgr_gate(self, ticker: str) -> bool:
        """
        One of the tests for joining the active list.

        Fails OPEN on data errors (insufficient history, download failure):
        a data outage must not empty the whole list, and the analyst and
        stability checks still apply afterwards.
        """

        if not self.enable_rgr_gate:
            return True

        try:
            diag = screen_candidate(
                ticker,
                as_of=self.simulate_date,
                hold_days=self.rgr_hold_days,
                threshold=self.rgr_threshold,
            )
        except Exception as exc:
            print(f"  RGR gate: {ticker} data error ({exc}) - allowed.")
            return True

        self.rgr_results[ticker] = diag

        if diag.get("passed") is None:
            print(
                f"  RGR gate: {ticker} skipped "
                f"({diag.get('error')}) - allowed."
            )
            return True

        verdict = "PASS" if diag["passed"] else "REJECT"
        print(
            f"  RGR gate: {ticker} {verdict} | "
            f"RGR={diag['rgr']:+.5f} "
            f"(RoR={diag['ror']:+.4f}, RPR={diag['rpr']:.4f}, "
            f"{diag['direction']}, threshold={self.rgr_threshold})"
        )

        if not diag["passed"]:
            self.rgr_rejected.append(ticker)

        return bool(diag["passed"])

    def _screen_initial_active_list(self) -> None:
        """
        Apply the RGR gate to the initial top-10. Failures are removed and
        backfilled from the waiting list (replacements are gated too).
        """

        if not self.enable_rgr_gate:
            return

        print("\n" + "=" * 60)
        print("RGR SCREEN: INITIAL ACTIVE LIST")
        print("=" * 60)

        failed = [
            t for t in list(self.active_list)
            if not self._passes_rgr_gate(t)
        ]

        for t in failed:
            self.active_list.remove(t)

        if failed:
            print(f"\nRGR removed {len(failed)}: {failed}")
            self._get_replacements(len(failed))

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

    # ----------------------------------
    # One-time reserve of 30 extra tickers
    # ----------------------------------
    def _known_tickers(self) -> set:
        """Every ticker this session has already seen, in any state."""
        known = set()

        def add(item: Any) -> None:
            if isinstance(item, dict):
                item = item.get("ticker")
            if item:
                known.add(_norm_ticker(item))

        for coll in (
            self.ticker_universe, self._initial_active, self._initial_waitlist,
            self.active_list, self.waitlist, self.final_invest,
            self.replacement_history, self.rgr_rejected, self.rgr_results.keys(),
            self.closed_positions_today, self.hold_history, self.daily_results,
        ):
            for item in coll:
                add(item)
        return known

    def _load_reserve(self) -> bool:
        """Add up to 30 reserve tickers (10 trending, 10 world indices, 10 most active).

        Runs once, only when the top 50 and the waiting list are exhausted and fewer
        than MIN_FINAL_INVEST_BEFORE_RESERVE tickers reached the final INVEST list.
        The new tickers join the top-50 universe and the waiting list; the caller
        then draws the next top-10 from the waiting list as usual (RGR gate and
        fresh news discovery included). Skipped in historical simulation, where
        today's Yahoo pages would be look-ahead.

        Returns True if at least one new ticker was added.
        """
        if self.reserve_loaded or self.simulate_date:
            return False
        if len(self.final_invest) >= MIN_FINAL_INVEST_BEFORE_RESERVE:
            return False

        self.reserve_loaded = True   # one attempt per session, success or not

        print("\n" + "=" * 60)
        print(
            f"RESERVE: top 50 and waiting list exhausted with only "
            f"{len(self.final_invest)} final INVEST (< {MIN_FINAL_INVEST_BEFORE_RESERVE})"
        )
        print("=" * 60)

        # With MT5 on, only keep tickers the broker can trade (indices especially),
        # so reserve slots are not spent on symbols that can never reach an order.
        accept = None
        mt5_open = False
        if self.enable_mt5:
            mt5_open = initialize_mt5()
            if mt5_open:
                accept = is_mt5_tradable
            else:
                print("  MT5 unavailable - reserve NOT filtered by tradability.")

        try:
            reserve = build_reserve(exclude=self._known_tickers(), accept=accept)
        except Exception as exc:
            print(f"  Reserve fetch failed: {exc}")
            return False
        finally:
            if mt5_open:
                shutdown_mt5()

        self.reserve_info = reserve
        new = reserve["tickers"]
        for name, tickers in reserve["by_source"].items():
            print(f"  {name:<14} via {reserve['methods'][name]:<14} {len(tickers):>2}: {tickers}")
            dup = reserve["duplicates_dropped"][name]
            if dup:
                print(f"  {'':<14} duplicates skipped: {dup}")
            nt = reserve["untradable_dropped"][name]
            if nt:
                print(f"  {'':<14} not tradable on MT5, skipped: {nt}")

        if not new:
            print("  No new reserve tickers available.")
            return False

        # top 50 -> 80; point past the end so the reserve is not added twice
        self.ticker_universe.extend(new)
        self._next_universe_index = len(self.ticker_universe)
        self.waitlist.extend(t for t in new if t not in self.waitlist)

        print(f"  Added {len(new)} reserve tickers to the universe and waiting list.")
        return True

    # ----------------------------------
    # Exhaustion: ALL THREE must be used up
    # ----------------------------------
    def _top50_exhausted(self) -> bool:
        """Every ticker of the top 50 (plus any reserve added to it) has been drawn."""
        return self._next_universe_index >= len(self.ticker_universe)

    def sources_exhausted(self) -> bool:
        """True only when the top 50, the waiting list AND the top-10 active list are all empty."""
        return (
            self._top50_exhausted()
            and not self.waitlist
            and not self.active_list
        )

    def _refill_active(self, vacancies: int) -> List[str]:
        """Draw candidates for the top 10 from the waiting list (itself fed by the top 50).

        When the top 50 and the waiting list are exhausted and fewer than 5 tickers are in
        final_invest, the one-time reserve is added to the top 50 and drawn from the same
        way. Returns [] only when every source is exhausted.
        """
        got = self._get_replacements(vacancies)
        if not got and not self.active_list and self._top50_exhausted() and not self.waitlist:
            print("Top 50 and waiting list exhausted.")
            if self._load_reserve():
                got = self._get_replacements(vacancies)
        return got

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
        drawn = 0

        while len(replacements) < number_needed:

            if not self.waitlist:
                # The waiting list is topped up from the top 50. Tickers rejected by the
                # gates below used to leave it short while the top 50 still had unused
                # tickers, which ended the session early.
                self._replenish_waitlist_from_universe(
                    number_needed - len(replacements)
                )
                if not self.waitlist:
                    break

            ticker = (
                self.waitlist.pop(0)
            )
            drawn += 1

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
            # RGR gate (before paying for news)
            # ----------------------------------

            if not self._passes_rgr_gate(ticker):
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
        self._replenish_waitlist_from_universe(drawn)
        return replacements
    # ======================================
    # TRADING SESSION
    # ======================================

    def run_trading_session(
        self,
        simulate_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Run the dynamic trading session with:
        - Macro event blocking (FOMC, CPI, NFP windows)
        - Discord approval for final INVEST list
        - MT5 balance check once, after Batch 1 is complete (blocks if balance <= $20)
        - End-of-day summarization middleware
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

        # ==================================
        # 1. MACRO EVENT CHECK - Block if high-impact event window
        # ==================================
        
        check_time = None
        if simulate_date:
            import pandas as pd
            check_time = pd.Timestamp(simulate_date)
        
        blocking_event = MacroEventChecker().is_event_window_active(
            check_time=check_time,
            min_impact="MEDIUM",
        )
        if blocking_event:
            msg = f"🚫 TRADING BLOCKED: {blocking_event.name} ({blocking_event.event_type}) window active"
            print(msg)
            self._send_alert(msg)
            self.session_blocked = True       # Batch 1 did not run: no live hand-over
            return self.daily_results

        # Balance at the START of the session, for the end-of-day summary only.
        # (Not a guard any more.) Also the balance at the START of the session for the end-of-day summary.
        # Skipped for historical simulations: the live account says nothing about them.
        self.starting_balance = None
        if not simulate_date:
            self.starting_balance = get_account_balance()
            if self.starting_balance is None:
                print("\u26a0\ufe0f  MT5 balance unavailable - minimum-balance guard NOT applied.")
            # Read only: discovery and analysis are never stopped by the balance.
            # The guard runs once, after every ticker has been tested (step 4).

        # ==================================
        # 2. PRE-MARKET SCAN & RGR SCREEN
        # ==================================

        self.pre_market_scan()
        self._log_watchlist_snapshot(include_open_trades=False)

        self._screen_initial_active_list()

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

                # Need enough candidates to
                # reach the target.
                vacancies = (
                    self.max_active_positions
                    - len(self.final_invest)
                )

                # waiting list (fed by the top 50), then the one-time reserve
                self._refill_active(
                    vacancies
                )

                if not self.active_list:
                    print(
                        "\nTop 50, waiting list and top 10 "
                        "are all exhausted."
                    )
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
                    self._refill_active(
                        vacancies
                    )
                )

                if not replacements and self.sources_exhausted():

                    print(
                        "\nTop 50, waiting list and top 10 "
                        "are all exhausted."
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

                # The top of the loop tries the one-time reserve, and
                # breaks if there is nothing left.
                continue

        # ==================================
        # 3. MT5 DATA FOR FINAL INVEST LIST
        #    (before approval, so the approver sees real symbols and spreads;
        #    it used to be sent as {} and every ticker showed as N/A)
        # ==================================

        if self.enable_mt5 and self.final_invest:
            self.mt5_data = enrich_final_invest(self.final_invest)
            # Adapter only: converts RAATS positions to MT5 lots/levels, changes no risk logic.
            self.mt5_order_plan = build_order_plan(
                self.risk_manager, self.mt5_data,
            )
            print("\n" + format_order_plan(self.mt5_order_plan))

        if self.final_invest:
            print("\nFINAL INVEST - TRADES")
            print(format_rows(trade_rows(
                self.risk_manager, self.final_invest, self.mt5_order_plan)))

        # ==================================
        # 4. MINIMUM-BALANCE GUARD
        #    (runs whether or not approval is required)
        # ==================================

        if self.final_invest and not simulate_date:
            balance_check = check_minimum_balance()
            if balance_check:
                return self._block_for_balance(balance_check)

        # ==================================
        # 5. DISCORD APPROVAL (if enabled)
        # ==================================

        require_approval = os.environ.get(
            "RAATS_REQUIRE_APPROVAL", ""
        ).lower() in ("1", "true", "yes")

        if self.final_invest and require_approval:
            response = self._request_human_approval()

            if response != "APPROVE":
                print(f"\u274c Session not approved ({response}).")
                self.session_blocked = True
                self._discard_unapproved_positions(response)
                return self.daily_results

            # Approval can take minutes: look at the balance again.
            balance_check = None if simulate_date else check_minimum_balance()
            if balance_check:
                return self._block_for_balance(
                    balance_check, "insufficient balance after approval"
                )

        # ==================================
        # 6. FINAL SUMMARY + SUMMARIZATION MIDDLEWARE
        # ==================================

        self._print_session_summary()

        enable_discord_summary = os.environ.get(
            "RAATS_DISCORD_SUMMARY", ""
        ).lower() in ("1", "true", "yes")
        middleware = SummarizationMiddleware(
            enable_discord=enable_discord_summary,
            starting_balance=getattr(self, "starting_balance", None),
        )
        session_results = {
            "manager": self,
            "results": self.daily_results,
        }
        middleware.process_session_end(session_results)

        return self.daily_results

    def _get_notifier(self) -> DiscordNotifier:
        """One Discord notifier per manager, created on first use."""
        if getattr(self, "_notifier_obj", None) is None:
            self._notifier_obj = DiscordNotifier()
        return self._notifier_obj

    def _send_alert(self, message: str) -> None:
        """Post an alert to Discord (it is printed if Discord is not configured)."""
        try:
            self._get_notifier().send_alert(message)
        except Exception as exc:
            print(f"  WARNING: alert not sent ({exc})")

    def _block_for_balance(
        self, balance_check: Dict[str, Any], reason: str = "insufficient balance"
    ) -> List[Dict[str, Any]]:
        """Stop the session because the account is below the minimum.

        Drops this session's paper positions (if any were opened), prints the blocked
        summary, alerts on Discord with the amount to deposit, and records the session.
        """
        tickers = list(self.final_invest)
        self.session_blocked = True
        if tickers:
            self._discard_unapproved_positions(reason)
        report_blocked_session(balance_check, tickers)
        return self.daily_results

    def _print_account_balance(self) -> None:
        """Account-balance section of the session summary."""
        print("\n" + "=" * 60)
        print("ACCOUNT BALANCE")
        print("=" * 60)
        if getattr(self, "simulate_date", None):
            print("Balance check:     skipped (historical simulation)")
            return
        balance = getattr(self, "starting_balance", None)
        if balance is None:
            print("Account balance:   unavailable (MT5 not connected) - guard not applied")
            return
        print(f"Account balance:   ${balance:,.2f}")
        print(f"Minimum required:  ${MIN_ACCOUNT_BALANCE:,.2f}")
        if balance < MIN_ACCOUNT_BALANCE:
            print(f"Status:            BELOW MINIMUM - short by ${MIN_ACCOUNT_BALANCE - balance:,.2f}")
        else:
            print("Status:            OK")

    def _request_human_approval(self) -> str:
        """Ask on Discord and wait. Returns APPROVE | REJECT | MODIFY | TIMEOUT.

      
        """
        notifier = self._get_notifier()
        balance = get_account_balance()
        request = notifier.send_approval_request(
            final_invest=list(self.final_invest),
            mt5_data=getattr(self, "mt5_data", None) or {},
            account_balance=balance,
        )
        return notifier.wait_for_approval(request.request_id)

    def _discard_unapproved_positions(self, reason: str) -> None:
        """Drop this session's paper positions when the session is not approved.

        The positions are opened inside the analysis rounds, BEFORE the human is
        asked, so a REJECT used to leave them open. Nothing has been sent to the
        broker (there is no order placement yet); when real orders are added they
        must be placed only after approval.
        """
        positions = getattr(self.risk_manager, "positions", {})
        removed = [t for t in list(self.final_invest) if positions.pop(t, None) is not None]
        print(f"  Discarded {len(removed)} unapproved paper position(s): {removed} ({reason})")
        try:
            log_error(
                ticker=",".join(removed) or "-",
                date=datetime.now().strftime("%Y-%m-%d"),
                error=f"session not approved: {reason}",
                stage="approval",
                context={"final_invest": list(self.final_invest), "discarded": removed},
            )
        except Exception as exc:
            print(f"  WARNING: approval log failed ({exc})")

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

    def _open_trades_snapshot(self):
        """Open positions from the session's one shared RiskManager."""
        trades = []
        for ticker, p in getattr(self.risk_manager, "positions", {}).items():
            trades.append({
                "ticker": ticker,
                "direction": "LONG" if getattr(p, "direction", 1) == 1 else "SHORT",
                "entry_price": getattr(p, "entry_price", None),
                "size": getattr(p, "size", None),
                "stop_loss": getattr(p, "stop_loss", None),
                "take_profit": getattr(p, "take_profit", None),
            })
        return trades

    def _log_watchlist_snapshot(self, include_open_trades: bool = False) -> None:
        """Write the day's candidate arrays to the weekly JSONL log.

        Called at start of day (arrays only) and end of day (arrays plus open
        trades). random_list stays empty: discovery.py has no random-exploration
        step, so there is nothing real to record there yet.
        """
        try:
            log_daily_watchlist(
                date=datetime.now().strftime("%Y-%m-%d"),
                top50=list(self.ticker_universe),
                random_list=[],
                top10_active=list(self._initial_active),
                open_trades=self._open_trades_snapshot() if include_open_trades else [],
            )
        except Exception as exc:  # logging must never break trading
            print(f"  WARNING: daily watchlist log failed: {exc}")

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
            f"\nRGR gate rejections "
            f"({len(self.rgr_rejected)}):"
        )

        print(
            self.rgr_rejected
        )

        if self.mt5_data:

            print("\nMT5 DATA (final INVEST):")

            for t, d in self.mt5_data.items():
                print(
                    f"  {t:<10} -> {str(d.get('mt5_symbol')):<10} "
                    f"tradable={d.get('tradable')} "
                    f"bid={d.get('bid')} ask={d.get('ask')} "
                    f"spread_pts={d.get('spread_points')}"
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

        self._print_account_balance()

        log_session_summary(
            active_list=self.active_list,
            waitlist=self.waitlist,
            hold_list=categories[
                "hold"
            ],
            metrics=metrics,
        )
        self._log_watchlist_snapshot(include_open_trades=True)

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
    enable_rgr_gate: bool = True,
    rgr_threshold: float = 0.0,
    enable_mt5: bool = False,
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
        enable_rgr_gate=enable_rgr_gate,
        rgr_threshold=rgr_threshold,
        enable_mt5=enable_mt5,
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

        "final_invest_orders":
            trade_rows(
                manager.risk_manager,
                manager.final_invest,
                getattr(manager, "mt5_order_plan", None),
            ),

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

        "rgr_results":
            manager.rgr_results,

        "rgr_rejected":
            manager.rgr_rejected,

        "mt5_data":
            manager.mt5_data,

        "mt5_order_plan":
            manager.mt5_order_plan,

        "reserve_tickers":
            manager.reserve_info.get("tickers", []),

        "performance_scores":
            manager.all_sentiment_scores,

        "waitlist_opportunities":
            manager.get_waitlist_opportunities(
                10
            ),
    }

    return session_results


# ==========================================
# THREADED BATCH PIPELINE
# ==========================================
#
# Everything ABOVE this section is the original trading loop and is unchanged
# (DynamicTradingManager, run_dynamic_trading_session, every helper, every logger).
# This section only ADDS:
#
#   * the whole process as BATCHES: the first run is batch 1; batch 2 continues
#     discovery where batch 1 stopped (top gainers 41-80), and so forth
#   * the original flow split into three SEQUENTIAL THREAD-BASED SUBAGENTS that
#     pass their result to the next one through queues (dataclasses):
#
#         Subagent 1  discovery        first half of discovery.main()
#         Subagent 2  news + scoring   second half of discovery.main()
#         Subagent 3  analysis         DynamicTradingManager.run_trading_session()
#                                      (RGR, run_daily_cycle / LangGraph, replacements,
#                                       reserve, order plan, balance guard, DISCORD APPROVAL
#                                       of the batch, summary)
#
#   * BatchRunner: runs batch after batch in the background and hands every approved
#     batch to a "sink" (live_agents.py), which owns the MT5 position engine
#
# GOVERNING RULE
#   Discovery -> Scoring -> Analysis -> DISCORD BATCH APPROVAL -> FinalInvestPool -> Main Agent
#   -> balance gate -> margin / lot size / SL / TP proposal -> DISCORD TRADE APPROVAL ->
#   async timer -> revalidation -> MT5 order
#   * EVERY batch goes through Discord, whatever RAATS_REQUIRE_APPROVAL says: suitable
#     candidates are never approved automatically, and only approved ones are handed over
#   * the minimum-balance gate is NOT decided here: the Main Agent does it on the first approved
#     batch and, when it fails, sets GLOBAL_STATE (BLOCKED_INSUFFICIENT_BALANCE); this module
#     then stops at once
#   * a batch needs no minimum size: even one approved candidate enters the pool
#
# The functions of discovery.py and of this file are called in the same order with the
# same arguments; the only addition to the manager is its batch number (`batch_no`).
#
# BEGIN THREADED BATCH PIPELINE
import contextlib
import inspect
import queue
import threading
import time
from dataclasses import dataclass, field

# ---- batch statuses (the values live_agents.py records; a test keeps both in step) ----
BATCH_PROCESSING = "BATCH_PROCESSING"          # the batch is being processed
READY = "READY"                                # eligible candidates are ready for handover
WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"  # Discord approval is required
INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"      # MT5 balance below the minimum: batch blocked
BALANCE_UNAVAILABLE = "BALANCE_UNAVAILABLE"    # MT5 balance could not be verified
REJECTED = "REJECTED"                          # the Discord approval was not given
HANDED_OVER = "HANDED_OVER"                    # approved candidates were handed to the main agent
BATCH_COMPLETED = "BATCH_COMPLETED"            # the batch finished its lifecycle
ABANDONED = "ABANDONED"                        # blocked by a macro event or failed

BLOCKED_INSUFFICIENT_BALANCE = "BLOCKED_INSUFFICIENT_BALANCE"   # the Main Agent's balance gate failed


class GlobalState:
    """ONE state shared by both modules. When the Main Agent's initial balance gate fails it calls
    block(); the batch runner (and any approval still to be sent) then stops immediately."""

    def __init__(self) -> None:
        self.blocked = threading.Event()
        self.reason: Optional[str] = None
        self.detail: Dict[str, Any] = {}

    def block(self, reason: str, **detail: Any) -> None:
        self.reason, self.detail = reason, dict(detail)
        self.blocked.set()

    def is_blocked(self) -> bool:
        return self.blocked.is_set()

    def reset(self) -> None:
        self.blocked.clear()
        self.reason, self.detail = None, {}


GLOBAL_STATE = GlobalState()


def _batch_env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# After a FAILED batch wait this long before the next one.
PAUSE_AFTER_BLOCK_SEC = _batch_env_float("RAATS_BLOCKED_BATCH_PAUSE_SEC", 900.0)
# After a REJECTED batch the loop simply continues with the next batch (0 = at once).
REJECTED_BATCH_PAUSE_SEC = _batch_env_float("RAATS_REJECTED_BATCH_PAUSE_SEC", 0.0)
# Macro event window: try a fresh batch again after this long.
BATCH_MACRO_RETRY_SEC = _batch_env_float("RAATS_MACRO_RETRY_SEC", 600.0)
RUNNER_POLL_SEC = _batch_env_float("RAATS_RUNNER_POLL_SEC", 2.0)
# Retry interval when balance is unreadable
BATCH_BALANCE_RETRY_SEC = _batch_env_float("RAATS_BATCH_BALANCE_RETRY_SEC", 5.0)

# Commodity / currency ranks 6-10, used by batch 2 (batch 1 uses the lists of discovery.py).
EXTRA_COMMODITY_TICKERS = ["PL=F", "PA=F", "BZ=F", "ZC=F", "ZW=F"]
EXTRA_CURRENCY_TICKERS = ["NZDUSD=X", "USDCHF=X", "EURGBP=X", "EURJPY=X", "GBPJPY=X"]


# ---- what travels through the queues ----
@dataclass
class DiscoveryBatch:
    """Subagent 1 -> Subagent 2."""
    batch_no: int
    blocked: bool = False            # macro event window: discovery.main() returns empty arrays
    exhausted: bool = False          # no unused gainers left for this batch
    universe: List[str] = field(default_factory=list)   # every ticker this batch discovered
    top_50: Any = None
    top_10: Any = None
    waiting: Any = None
    target_date: Any = None


@dataclass
class ScoredBatch:
    """Subagent 2 -> Subagent 3."""
    discovery: DiscoveryBatch
    scored_top_10: Any = None


@dataclass
class BatchResult:
    """Subagent 3 -> the coordinator."""
    batch_no: int
    manager: Any = None
    session: Dict[str, Any] = field(default_factory=dict)
    exhausted: bool = False


@dataclass
class StageFailure:
    """An exception travelling down the queues so the coordinator can report it."""
    stage: str
    error: BaseException


# ---- batch 2 continues where batch 1 stopped ----
def _usable_symbol(symbol: Any) -> bool:
    """The test get_tickers_from_gainers_feed() applies to a gainer."""
    sym = str(symbol or "").upper().strip()
    return sym.isalpha() and len(sym) <= 5


class GainersWindow:
    """Stands in for discovery's `yf` while a later batch discovers: day_gainers WITHOUT the
    tickers earlier batches used, so the original get_tickers_from_gainers_feed() simply takes
    the next ones. Everything else on `yf` is passed through unchanged."""

    def __init__(self, real_yf: Any, used: List[str], need: int):
        self._real = real_yf
        self.used = {str(u).upper().strip() for u in used}
        self.need = need
        self._quotes: Optional[List[Dict[str, Any]]] = None
        self.usable = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def screen(self, query: str, **_ignored: Any) -> Dict[str, Any]:
        if self._quotes is None:                       # one request per batch (Yahoo allows 250)
            result = self._real.screen(query, count=250)
            quotes = [q for q in (result.get("quotes") or [])
                      if str(q.get("symbol", "")).upper().strip() not in self.used]
            self._quotes = quotes
            self.usable = sum(1 for q in quotes if _usable_symbol(q.get("symbol")))
        return {"quotes": self._quotes}


@contextlib.contextmanager
def discovery_window(d: Any, day_index: int, used: List[str]):
    """Point discovery.py at the next slice of the market for the duration of one discovery.

        first batch of the day   nothing is touched: discovery runs exactly as written
        second batch             next 40 gainers + commodities / currencies ranks 6-10
        later batches            next 50 gainers (the commodity / currency lists are used up)

    Only module attributes of discovery are swapped, and restored afterwards; no function of
    discovery.py is changed.
    """
    if day_index == 0 and not used:
        yield None
        return
    keys = ("yf", "COMMODITY_TICKERS", "CURRENCY_TICKERS", "TOP_40_EQUITIES_COUNT")
    saved = {k: getattr(d, k) for k in keys}
    window = GainersWindow(saved["yf"], used, 40 if day_index == 1 else 50)
    d.yf = window
    d.TOP_40_EQUITIES_COUNT = window.need
    d.COMMODITY_TICKERS = list(EXTRA_COMMODITY_TICKERS) if day_index == 1 else []
    d.CURRENCY_TICKERS = list(EXTRA_CURRENCY_TICKERS) if day_index == 1 else []
    try:
        yield window
    finally:
        for k, v in saved.items():
            setattr(d, k, v)


@contextlib.contextmanager
def _batch_flow_rules():
    """The corrected workflow, applied to the batch pipeline only (restored afterwards):

    * RAATS_REQUIRE_APPROVAL is forced on: every batch goes to Discord, never automatically
    * check_minimum_balance is switched off inside the batch: the balance gate belongs to the
      Main Agent (it runs after the approval, on the first approved batch)

    Neither function of this file is edited; a module setting and an environment variable are
    set for the duration of one batch.
    """
    global check_minimum_balance
    saved_check = check_minimum_balance
    saved_env = os.environ.get("RAATS_REQUIRE_APPROVAL")
    check_minimum_balance = lambda: None
    os.environ["RAATS_REQUIRE_APPROVAL"] = "1"
    try:
        yield
    finally:
        check_minimum_balance = saved_check
        if saved_env is None:
            os.environ.pop("RAATS_REQUIRE_APPROVAL", None)
        else:
            os.environ["RAATS_REQUIRE_APPROVAL"] = saved_env


# ---- the three sequential thread-based subagents ----
class BatchPipeline:
    """One batch = the original flow on three SEQUENTIAL THREADS.

        python -m src.agents.trading_loop_dynamic   =   discovery.main()  ->  run_dynamic_trading_session()

    Nothing in discovery.py or in the code above is changed or re-implemented: the same
    functions are called in the same order with the same arguments, on three threads that pass
    their result to the next one through a queue (q12, q23, q_out).
    """

    NAMES = ("raats-subagent-1-discovery", "raats-subagent-2-news", "raats-subagent-3-analysis")

    def __init__(self, batch_no: int, status_cb: Any = None,
                 used: Optional[List[str]] = None, day_index: int = 0):
        self.batch_no = int(batch_no)
        self.status_cb = status_cb or (lambda batch_no, status, **info: None)
        self.used = list(used or [])
        self.day_index = int(day_index)
        self.q12: "queue.Queue[Any]" = queue.Queue(maxsize=1)     # subagent 1 -> 2
        self.q23: "queue.Queue[Any]" = queue.Queue(maxsize=1)     # subagent 2 -> 3
        self.q_out: "queue.Queue[Any]" = queue.Queue(maxsize=1)   # subagent 3 -> coordinator
        self.threads: List[threading.Thread] = []

    def run(self) -> BatchResult:
        """Start the three threads, wait for the result, join them."""
        for name, target in zip(self.NAMES, (self._subagent1, self._subagent2, self._subagent3)):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self.threads.append(thread)
        while True:
            try:
                result = self.q_out.get(timeout=1.0)
                break
            except queue.Empty:
                if not any(t.is_alive() for t in self.threads):
                    try:                                   # the last result may have arrived just now
                        result = self.q_out.get_nowait()
                        break
                    except queue.Empty:
                        raise RuntimeError("the batch pipeline threads ended without a result")
        for thread in self.threads:
            thread.join(timeout=5)
        if isinstance(result, StageFailure):
            try:
                log_error(
                    ticker="-", date=datetime.now().strftime("%Y-%m-%d"),
                    error=str(result.error), stage=f"batch_pipeline_{result.stage}",
                    context={"batch_no": self.batch_no},
                )
            except Exception:
                pass
            raise result.error
        return result

    # ------------------------------------------------------------------ Subagent 1
    def _subagent1(self) -> None:
        """First half of discovery.main()."""
        try:
            from src.data import discovery as d
            with discovery_window(d, self.day_index, self.used) as window:
                if window is not None:
                    window.screen("day_gainers")             # one request, kept for the call below
                    if window.usable < window.need:
                        print(f"Yahoo has only {window.usable} unused gainers left "
                              f"(batch needs {window.need}): discovery sources exhausted.")
                        self.q12.put(DiscoveryBatch(self.batch_no, exhausted=True))
                        return
                equity_tickers = d.get_tickers_from_gainers_feed()
                if not equity_tickers:
                    raise ValueError("No equity gainers discovered.")
                market_universe = d.build_market_universe(equity_tickers)
                if len(market_universe) != d.TOP_50_COUNT:
                    raise ValueError(f"Expected {d.TOP_50_COUNT} instruments, "
                                     f"but built {len(market_universe)}.")
            universe = [str(u["Ticker"]).upper() for u in market_universe]
            df_top_50, target_date = d.get_previous_session_returns(market_universe)
            df_top_50 = d.apply_mt5_filter(df_top_50)
            if d.is_trade_blocked_by_macro(min_impact="MEDIUM"):
                print("\U0001F6AB MACRO EVENT WINDOW ACTIVE - Discovery blocked")
                print("   Set RAATS_MACRO_API_KEY for live calendar or update macro_calendar.json")
                self.q12.put(DiscoveryBatch(
                    self.batch_no, blocked=True, top_50=pd.DataFrame(), top_10=[],
                    waiting=pd.DataFrame(), target_date=target_date))
                return
            top_50_performing, top_10_to_fetch_articles, waiting_list = d.build_ticker_arrays(df_top_50)
            print(f"\nDiscovered performance universe: {len(df_top_50)} instruments")
            print(f"Top 50 array: {len(top_50_performing)} instruments")
            print(f"Top 10 article array: {len(top_10_to_fetch_articles)} instruments")
            print(f"Waiting list array: {len(waiting_list)} instruments")
            # the cursor: the next batch starts after these tickers
            self.status_cb(self.batch_no, BATCH_PROCESSING, initial=True, universe=universe)
            self.q12.put(DiscoveryBatch(
                self.batch_no, universe=universe, top_50=top_50_performing,
                top_10=top_10_to_fetch_articles, waiting=waiting_list, target_date=target_date))
        except BaseException as exc:                       # noqa: BLE001 - relayed to the coordinator
            self.q12.put(StageFailure("discovery", exc))

    # ------------------------------------------------------------------ Subagent 2
    def _subagent2(self) -> None:
        """Second half of discovery.main(): the news and the sentiment scoring."""
        item = self.q12.get()
        if isinstance(item, StageFailure):
            self.q23.put(item)
            return
        if item.exhausted:                                 # nothing to score: pass the news step
            self.q23.put(ScoredBatch(item))
            return
        try:
            if item.blocked:                               # discovery.main() returned before the news
                self.q23.put(ScoredBatch(item, scored_top_10=item.top_10))
                return
            from src.data import discovery as d
            scored_top_10 = d.render_top_50_and_news(item.top_50, item.top_10, item.target_date)
            d.render_waiting_list(item.waiting)
            self.q23.put(ScoredBatch(item, scored_top_10=scored_top_10))
        except BaseException as exc:                       # noqa: BLE001
            self.q23.put(StageFailure("news", exc))

    # ------------------------------------------------------------------ Subagent 3
    def _subagent3(self) -> None:
        """run_dynamic_trading_session(), step by step: same arguments, same defaults. The Discord
        approval of the batch happens inside run_trading_session(), as always."""
        item = self.q23.get()
        try:
            if isinstance(item, StageFailure):
                self.q_out.put(item)
                return
            if item.discovery.exhausted:
                self.q_out.put(BatchResult(self.batch_no, exhausted=True))
                return
            found = item.discovery
            print("\nDiscovery completed.")
            print(f"Top-50 array: {len(found.top_50)}")
            print(f"Top-10 array: {len(item.scored_top_10)}")
            print(f"Waiting-list array: {len(found.waiting)}")

            defaults = {n: p.default for n, p in
                        inspect.signature(run_dynamic_trading_session).parameters.items()
                        if p.default is not inspect.Parameter.empty}
            print("Initializing Dynamic Trading Manager...")
            manager = DynamicTradingManager(
                top_50_performing=found.top_50,
                top_10=item.scored_top_10,
                waiting_list=found.waiting,
                portfolio_value=_live_portfolio_value(),
                analyst_model=defaults.get("analyst_model"),
                enable_rgr_gate=defaults.get("enable_rgr_gate", True),
                rgr_threshold=defaults.get("rgr_threshold", 0.0),
                enable_mt5=os.environ.get("RAATS_USE_MT5", "").lower() in ("1", "true", "yes"),
            )
            manager.batch_no = self.batch_no                              # the only addition
            manager.batch_id = f"{datetime.now():%Y-%m}-B{self.batch_no:03d}"

            original_request = manager._request_human_approval            # report the wait, change nothing
            def request_with_status() -> str:
                if GLOBAL_STATE.is_blocked():              # the Main Agent has stopped everything
                    return "CANCELLED"
                self.status_cb(self.batch_no, WAITING_FOR_APPROVAL, tickers=list(manager.final_invest))
                return original_request()
            manager._request_human_approval = request_with_status

            with _batch_flow_rules():
                results = manager.run_trading_session(simulate_date=defaults.get("simulate_date"))
            self.q_out.put(BatchResult(self.batch_no, manager=manager,
                                       session=_batch_session_results(manager, results, self.batch_no)))
        except BaseException as exc:                       # noqa: BLE001
            self.q_out.put(StageFailure("analysis", exc))


def _batch_session_results(manager: Any, results: Any, batch_no: int) -> Dict[str, Any]:
    """The same dictionary run_dynamic_trading_session() returns, plus the batch number."""
    return {
        "manager": manager,
        "results": results,
        "top_50_performing": manager.top_50_performing,
        "top_10": manager.top_10,
        "initial_waiting_list": manager.initial_waiting_list,
        "active_list": manager.active_list,
        "waitlist": manager.waitlist,
        "final_invest": manager.final_invest,
        "final_invest_orders": trade_rows(
            manager.risk_manager, manager.final_invest, getattr(manager, "mt5_order_plan", None)),
        "hold_history": manager.hold_history,
        "replacement_history": manager.replacement_history,
        "closed_positions": manager.closed_positions_today,
        "open_trades": len(manager.risk_manager.positions),
        "rgr_results": manager.rgr_results,
        "rgr_rejected": manager.rgr_rejected,
        "mt5_data": manager.mt5_data,
        "mt5_order_plan": manager.mt5_order_plan,
        "reserve_tickers": manager.reserve_info.get("tickers", []),
        "performance_scores": manager.all_sentiment_scores,
        "waitlist_opportunities": manager.get_waitlist_opportunities(10),
        "batch_no": batch_no,
    }


def classify_blocked_batch(manager: Any) -> Tuple[str, Dict[str, Any]]:
    """Why did the batch not pass? (run_trading_session() only sets `session_blocked`)."""
    response = getattr(manager, "approval_response", None)
    if response is not None and response != "APPROVE":
        return REJECTED, {"response": response}
    # Check if blocked - differentiate between macro event and insufficient funds
    # Check both session_blocked (from Manager) and blocked (from GlobalState)
    if getattr(manager, "session_blocked", False) or getattr(manager, "blocked", False):
        # Check starting balance to determine the reason
        balance = getattr(manager, "starting_balance", None)
        if balance is not None and balance <= 20:
            return INSUFFICIENT_FUNDS, {"reason": "insufficient_balance"}
        # If no balance info but session_blocked is True, check if it's a macro event
        # (macro events block without balance issues)
        return ABANDONED, {"reason": "macro_event_window"}
    return ABANDONED, {"reason": "macro_event_window"}


def print_batch_complete(session: Dict[str, Any]) -> None:
    """STEP 3 of the original main block, with the batch number."""
    print("\n" + "=" * 60)
    print("SESSION COMPLETE")
    print("=" * 60)
    print(f"Batch: {session.get('batch_no')}")
    print(f"Final INVEST ({len(session['final_invest'])}): {session['final_invest']}")
    if session.get("final_invest_orders"):
        print(format_rows(session["final_invest_orders"]))
    print(f"Active list: {session['active_list']}")
    print(f"Waiting list: {session['waitlist']}")
    print(f"Closed positions: {session['closed_positions']}")
    print(f"Open trades: {session['open_trades']}")


# ---- the background runner ----
class BatchSink:
    """What the BatchRunner needs from whoever consumes the batches (live_agents.py provides it:
    FinalInvestPool and the Main Agent, the persisted batch history and the Discord alerts)."""

    def should_stop(self) -> bool: raise NotImplementedError
    def has_room(self) -> bool: raise NotImplementedError          # FinalInvestPool has capacity
    def open_count(self) -> int: raise NotImplementedError
    def next_batch_no(self) -> int: raise NotImplementedError
    def used_today(self) -> List[str]: raise NotImplementedError   # the discovery cursor
    def day_index(self) -> int: raise NotImplementedError
    def status(self, batch_no: int, status: str, **info: Any) -> None: raise NotImplementedError
    def alert(self, message: str, key: Optional[str] = None, cooldown: float = 1800.0) -> None:
        raise NotImplementedError
    def handover(self, manager: Any, batch_no: int, tickers: List[str],
                 first_batch: bool) -> List[str]: raise NotImplementedError   # only APPROVED tickers
    def first_batch_pending(self) -> bool: raise NotImplementedError
    def final_outcome(self, outcomes: List[Tuple[int, str]]) -> None: raise NotImplementedError


class BatchRunner(threading.Thread):
    """Runs batch after batch (each one = the three subagents) beside the position engine.

    * every batch is sent to Discord inside Subagent 3; only the APPROVED tickers are handed over
      (to FinalInvestPool), and a rejected batch adds nothing and the loop goes on
    * a batch starts while FinalInvestPool has capacity; it pauses when the pool is full
    * it stops at once when GLOBAL_STATE is blocked (the Main Agent's balance gate failed)
    * when the discovery sources are exhausted the final outcome is reported and it ends
    * it never trades and never checks the balance
    """

    def __init__(self, sink: Any, use_mt5: bool = True, first_batch: bool = True,
                 pipeline_cls: Any = None):
        super().__init__(name="raats-batch-runner", daemon=True)
        self.sink, self.use_mt5, self.first_batch = sink, use_mt5, first_batch
        self.pipeline_cls = pipeline_cls or BatchPipeline
        self.outcomes: List[Tuple[int, str]] = []
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _halted(self) -> bool:
        return (self._stop_event.is_set() or GLOBAL_STATE.is_blocked()
                or self.sink.should_stop())

    def _wait(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end and not self._halted():
            time.sleep(min(RUNNER_POLL_SEC, max(0.0, end - time.time())))

    def _balance_ok(self, batch_no: int) -> bool:
        """Check if MT5 balance is sufficient for a batch (before running discovery)."""
        balance_unavailable_logged = False
        while True:
            balance = self.sink.read_balance()
            if balance is None:
                if not balance_unavailable_logged:
                    self.sink.status(batch_no, BALANCE_UNAVAILABLE)
                    balance_unavailable_logged = True
                self._wait(BATCH_BALANCE_RETRY_SEC)
                if self._halted():
                    return False
                continue
            if balance < self.sink.min_balance:
                tickers = []  # no tickers yet, just the balance check
                self.sink.report_insufficient(balance, tickers)
                self.sink.live_cannot_run()
                self.sink.status(batch_no, INSUFFICIENT_FUNDS, tickers=tickers, balance=balance)
                return False
            return True

    def run_batch(self, batch_no: int) -> str:
        """One batch, from discovery to the hand-over of its approved candidates."""
        
        sink = self.sink
        sink.status(batch_no, BATCH_PROCESSING, initial=True)
        pipeline = self.pipeline_cls(batch_no, sink.status, used=sink.used_today(),
                                     day_index=sink.day_index())
        try:
            result = pipeline.run()
        except Exception as exc:
            sink.status(batch_no, ABANDONED, reason=f"error: {type(exc).__name__}: {exc}")
            sink.alert(f"Batch {batch_no} failed: {type(exc).__name__}: {exc}")
            return "error"

        if GLOBAL_STATE.is_blocked():                 # the Main Agent stopped everything meanwhile
            sink.status(batch_no, ABANDONED, reason=GLOBAL_STATE.reason or "blocked")
            return "stopped"

        if result.exhausted:
            sink.status(batch_no, BATCH_COMPLETED, tickers=[], note="discovery sources exhausted")
            return "exhausted"

        manager = result.manager
        print_batch_complete(result.session)
        tickers = list(manager.final_invest)

        if getattr(manager, "session_blocked", False):
            status, info = classify_blocked_batch(manager)
            sink.status(batch_no, status, tickers=tickers, **info)
            if status == REJECTED:
                sink.alert(f"Batch {batch_no} not approved ({info.get('response')}): "
                           "no candidate was added to final INVEST.")
                return "rejected"
            if status == INSUFFICIENT_FUNDS:
                return "insufficient_funds"
            return "macro"

        if not tickers:
            sink.status(batch_no, BATCH_COMPLETED, tickers=[], note="no tickers approved")
            sink.alert(f"Batch {batch_no} complete: No tickers approved for final INVEST.")
            return "empty"

        sink.status(batch_no, READY, tickers=tickers)
        accepted = sink.handover(manager, batch_no, tickers, self.first_batch)
        sink.status(batch_no, HANDED_OVER, tickers=accepted, approved=tickers,
                    not_fitted=[t for t in tickers if t not in accepted])
        sink.status(batch_no, BATCH_COMPLETED, tickers=accepted)
        print(f"[batches] batch {batch_no} approved and sent to FinalInvestPool: {accepted}")
        return "handed"

    def run(self) -> None:
        sink = self.sink
        while not self._halted():
            if not sink.has_room():
                self._wait(RUNNER_POLL_SEC)
                continue
            batch_no = sink.next_batch_no()
            outcome = self.run_batch(batch_no)
            self.outcomes.append((batch_no, outcome))
            if outcome == "stopped":
                break
            if outcome == "exhausted":
                sink.final_outcome(self.outcomes)        # sources exhausted: report and finish
                break
            if outcome == "handed" and self.first_batch:
                # the Main Agent works on the first batch before the next one starts
                while sink.first_batch_pending() and not self._halted():
                    self._wait(RUNNER_POLL_SEC)
                self.first_batch = False
            elif outcome == "rejected":
                self._wait(REJECTED_BATCH_PAUSE_SEC)     # rejected: add nothing, continue
            elif outcome == "macro":
                self._wait(BATCH_MACRO_RETRY_SEC)
            elif outcome == "error":
                self._wait(PAUSE_AFTER_BLOCK_SEC)
        if GLOBAL_STATE.is_blocked():
            print(f"[batches] trading loop stopped: {GLOBAL_STATE.reason}")
# END THREADED BATCH PIPELINE


# ==========================================
# MAIN
# ==========================================

def _live_portfolio_value(default: float = 10_000) -> float:
    """MT5 balance when MT5 is enabled and readable; otherwise the old 10,000 default.

    Read only - it never blocks. Without this, a $20 account was sized as if it had
    $10,000 (50% = $5,000 per trade) the moment real orders are placed.
    """
    if os.environ.get("RAATS_USE_MT5", "").strip().lower() not in ("1", "true", "yes"):
        return default
    balance = get_account_balance()
    return float(balance) if balance else default


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
                    _live_portfolio_value(),
                # RAATS_USE_MT5 used to switch only the discovery filter, so the MT5 symbol
                # lookup and the balance guard never ran from this entry point.
                enable_mt5=os.environ.get(
                    "RAATS_USE_MT5", ""
                ).strip().lower() in ("1", "true", "yes"),
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

        if session.get("final_invest_orders"):
            print(format_rows(session["final_invest_orders"]))

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

        # ----------------------------------
        # STEP 4: LIVE PHASE (optional)
        # Background discovery/scoring/analysis subagents + the main agent that
        # opens positions on MT5, moves SL/TP and reports. Orders are only sent
        # when RAATS_LIVE_TRADING=1; otherwise it is a dry run.
        # ----------------------------------
        if os.environ.get(
            "RAATS_LIVE_AGENTS", ""
        ).strip().lower() in ("1", "true", "yes"):
            from src.agents.live_agents import run_live_phase
            run_live_phase(session["manager"])

    except Exception as e:

        print(
            f"\nERROR: {e}"
        )

        raise