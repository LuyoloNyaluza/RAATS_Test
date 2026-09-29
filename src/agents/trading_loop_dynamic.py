"""
Dynamic Trading Loop for RAATS

The trading loop dynamically generates a universe before each market session
using the discovery layer.

Discovery combines:
1. Random S&P 500 exploration candidates
2. Previous market-session news discoveries
3. Previous market-session market movers
4. Yahoo Finance performers
5. Google News ticker/company mentions

The resulting candidates are passed to the watchlist manager.

The system then:
    Discovery -> Top 20 -> RAG/LLM -> Top 10 -> RAATS trading conditions
"""

from __future__ import annotations

import time
from typing import Optional

from src.data.discovery import get_discovery_components


class DynamicTradingManager:
    """
    Coordinates dynamic pre-market discovery and the RAATS trading loop.
    """

    def __init__(
        self,
        risk_manager,
        watchlist_manager,
        ticker_universe: Optional[list[str]] = None,
        max_active_positions: int = 10,
        waitlist_size: int = 10,
    ):
        self.risk_manager = risk_manager
        self.watchlist_manager = watchlist_manager

        # If supplied, this can still be used for controlled testing.
        # Normal operation should use ticker_universe=None so discovery
        # generates the universe dynamically.
        self.ticker_universe = ticker_universe

        self.max_active_positions = max_active_positions
        self.waitlist_size = waitlist_size

        self.active_tickers: list[str] = []
        self.waitlist_tickers: list[str] = []

        self.discovery_auxiliary = {}

        print("DynamicTradingManager initialized:")
        print("  Universe will be generated dynamically each pre-market scan")
        print(f"  Max active positions: {self.max_active_positions}")
        print(f"  Waitlist size: {self.waitlist_size}")

    # ------------------------------------------------------------------
    # DISCOVERY
    # ------------------------------------------------------------------

    def _get_discovery_components(self):
        """
        Generate the dynamic ticker universe.

        Open positions are passed into the discovery layer so that
        instruments already held are excluded before the candidate
        universe is returned.
        """

        open_positions = set(self.risk_manager.positions.keys())

        candidate_universe, random_list, auxiliary = get_discovery_components(
            open_positions=open_positions
        )

        self.discovery_auxiliary = auxiliary

        print("\nDISCOVERY SUMMARY")
        print(f"  Candidate universe: {len(candidate_universe)}")
        print(f"  Random exploration candidates: {len(random_list)}")
        print(f"  Open positions excluded: {len(open_positions)}")

        return candidate_universe, random_list, auxiliary

    def _generate_dynamic_universe(self):
        """
        Generate the universe for the current pre-market scan.
        """

        (
            candidate_universe,
            random_list,
            auxiliary,
        ) = self._get_discovery_components()

        return candidate_universe, random_list, auxiliary

    # ------------------------------------------------------------------
    # PRE-MARKET SCAN
    # ------------------------------------------------------------------

    def pre_market_scan(self):
        """
        Run the pre-market discovery process.

        If a ticker universe was explicitly supplied, it is used for
        controlled testing.

        Otherwise, the discovery layer generates the universe dynamically.
        """

        print("\n" + "=" * 60)
        print("PRE-MARKET SCAN: Fetching news and generating watchlists")
        print("=" * 60)

        # --------------------------------------------------------------
        # Controlled/test universe
        # --------------------------------------------------------------

        if self.ticker_universe is not None:
            universe = list(self.ticker_universe)
            random_list = []
            auxiliary = {}

            print(
                f"\nUsing supplied ticker universe: "
                f"{len(universe)} tickers"
            )

        # --------------------------------------------------------------
        # Normal dynamic discovery
        # --------------------------------------------------------------

        else:
            (
                universe,
                random_list,
                auxiliary,
            ) = self._generate_dynamic_universe()

            print(
                f"\nDynamic universe generated: "
                f"{len(universe)} candidates"
            )

        # --------------------------------------------------------------
        # Do not replace an empty dynamic universe with static tickers.
        # --------------------------------------------------------------

        if not universe:
            print(
                "\nNo candidates were discovered. "
                "Skipping this trading session."
            )

            self.active_tickers = []
            self.waitlist_tickers = []

            return {
                "universe": [],
                "random_candidates": random_list,
                "auxiliary": auxiliary,
                "active": [],
                "waitlist": [],
            }

        # Keep the discovery layer bounded.
        universe = universe[:100]

        print("\nDISCOVERED UNIVERSE")
        print(", ".join(universe))

        # --------------------------------------------------------------
        # Sentiment / ranking stage
        # --------------------------------------------------------------

        print("\n" + "=" * 60)
        print("RANKING DISCOVERED TICKERS")
        print("=" * 60)

        ranked_tickers = self.get_top_tickers_by_sentiment(
            universe
        )

        if not ranked_tickers:
            print(
                "\nNo tickers passed the ranking stage. "
                "Skipping this trading session."
            )

            self.active_tickers = []
            self.waitlist_tickers = []

            return {
                "universe": universe,
                "random_candidates": random_list,
                "auxiliary": auxiliary,
                "active": [],
                "waitlist": [],
            }

        # --------------------------------------------------------------
        # Active + waitlist
        # --------------------------------------------------------------

        self.active_tickers = ranked_tickers[
            :self.max_active_positions
        ]

        self.waitlist_tickers = ranked_tickers[
            self.max_active_positions:
            self.max_active_positions + self.waitlist_size
        ]

        print("\nWATCHLIST")
        print(f"  Active:   {self.active_tickers}")
        print(f"  Waitlist: {self.waitlist_tickers}")

        return {
            "universe": universe,
            "random_candidates": random_list,
            "auxiliary": auxiliary,
            "ranked": ranked_tickers,
            "active": self.active_tickers,
            "waitlist": self.waitlist_tickers,
        }

    # ------------------------------------------------------------------
    # RANKING
    # ------------------------------------------------------------------

    def get_top_tickers_by_sentiment(self, tickers):
        """
        Rank discovered tickers using the existing sentiment/news
        ranking process.

        Keep the actual implementation that already exists in your
        current trading loop here.
        """

        # IMPORTANT:
        # Keep your existing implementation from trading_loop_dynamic.py.
        #
        # This method is shown here only to make the revised structure
        # complete.

        return list(tickers)

    # ------------------------------------------------------------------
    # TRADING
    # ------------------------------------------------------------------

    def _run_active_list_with_shared_manager(self):
        """
        Run the normal RAATS trading cycle for the active watchlist.
        """

        if not self.active_tickers:
            print("\nNo active tickers to trade.")
            return

        print("\n" + "=" * 60)
        print("STARTING ACTIVE TRADING LIST")
        print("=" * 60)

        for ticker in self.active_tickers:

            print("\n" + "-" * 60)
            print(f"RUNNING RAATS CYCLE: {ticker}")
            print("-" * 60)

            try:
                self.run_daily_cycle(ticker)

            except Exception as exc:
                print(
                    f"Error while processing {ticker}: {exc}"
                )

    def run_daily_cycle(self, ticker: str):
        """
        Keep your existing RAATS daily cycle implementation here.

        This should continue through the existing pipeline:

        market data
            ->
        technical indicators
            ->
        news/sentiment
            ->
        RAG
            ->
        LLM analysis
            ->
        INVEST/HOLD
            ->
        stability checks
            ->
        RPR/RGR conditions
            ->
        risk management
            ->
        execution
        """

        # IMPORTANT:
        # Keep the existing run_daily_cycle() implementation
        # from your current file here.

        print(f"Processing {ticker}")

    # ------------------------------------------------------------------
    # SESSION
    # ------------------------------------------------------------------

    def run_trading_session(self):
        """
        Complete trading session:

            1. Dynamic discovery
            2. Ranking
            3. Active/watchlist selection
            4. Existing RAATS trading cycle
        """

        print("\n" + "=" * 60)
        print("STARTING TRADING SESSION")
        print("=" * 60)

        scan_result = self.pre_market_scan()

        if not scan_result["active"]:
            print(
                "\nTrading session stopped because "
                "there are no active candidates."
            )
            return scan_result

        self._run_active_list_with_shared_manager()

        return scan_result


# ----------------------------------------------------------------------
# DEMO / TEST
# ----------------------------------------------------------------------

if __name__ == "__main__":

    print("=== Dynamic Trading System Demo ===")

    # This list is only useful for controlled testing.
    # It is NOT used during normal dynamic discovery when
    # ticker_universe=None.
    demo_universe = [
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "META",
        "GOOGL",
        "TSLA",
        "AVGO",
        "GOOG",
        "COST",
        "NFLX",
        "AMD",
        "ADBE",
        "PEP",
        "CSCO",
        "INTC",
        "QCOM",
        "TXN",
        "AMAT",
        "INTU",
        "ISRG",
        "BKNG",
        "ADP",
        "VRTX",
        "REGN",
        "PANW",
        "MU",
        "LRCX",
        "ADI",
        "KLAC",
        "SNPS",
        "CDNS",
        "CRWD",
        "MAR",
        "ORCL",
        "SBUX",
        "CMCSA",
        "GILD",
        "MDLZ",
        "MELI",
        "PYPL",
        "ABNB",
        "MRVL",
        "FTNT",
        "CTAS",
        "DASH",
        "CSX",
        "HON",
    ]

    print(
        f"Demo universe defined: "
        f"{len(demo_universe)} tickers"
    )

    # Your actual RiskManager and WatchlistManager
    # construction should remain exactly as in your
    # current project.

    # Example:
    #
    # manager = DynamicTradingManager(
    #     risk_manager=risk_manager,
    #     watchlist_manager=watchlist_manager,
    #     ticker_universe=None,
    # )
    #
    # manager.run_trading_session()