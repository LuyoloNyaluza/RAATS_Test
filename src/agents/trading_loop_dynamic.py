# File: src/agents/trading_loop_dynamic.py
"""
Enhanced trading loop with dynamic watchlist management.
Implements the requested logic: read news before market opens, hold top 20 array,
open trades for first 10, manage waiting list based on closed trades.
"""

import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from src.data.watchlist_manager import (
    get_top_tickers_by_sentiment,
    update_trading_lists
)
from src.agents.trading_loop import (
    run_watchlist_concurrent,
    AgentState,
    build_graph
)
from src.risk.risk_manager import RiskManager


class DynamicTradingManager:
    """
    Manages dynamic watchlist based on news sentiment and position tracking.
    Implements the specific logic requested:
    - Read news before market opens
    - Hold top 20 array (ranked by sentiment)
    - Open trades for first 10
    - As trades close, fill from waiting list
    - Keep waiting list filled from initial ranking
    """
    
    def __init__(
        self,
        ticker_universe: List[str],
        max_active_positions: int = 10,
        waitlist_size: int = 10,
        max_articles_per_ticker: int = 5,
        sentiment_model: str = "mistral",
        news_fetch_pause: float = 0.5,
        portfolio_value: float = 10_000,
        analyst_model: Optional[str] = None
    ):
        self.ticker_universe = ticker_universe
        self.max_active_positions = max_active_positions
        self.waitlist_size = waitlist_size
        self.max_articles_per_ticker = max_articles_per_ticker
        self.sentiment_model = sentiment_model
        self.news_fetch_pause = news_fetch_pause
        self.portfolio_value = portfolio_value
        self.analyst_model = analyst_model
        
        # Initialize trading lists
        self.active_list: List[str] = []
        self.waitlist: List[str] = []
        self.all_sentiment_scores: Dict[str, float] = {}
        
        # Track positions and performance
        self.risk_manager = RiskManager()
        self.closed_positions_today: List[str] = []
        self.daily_results: List[Dict[str, Any]] = []
        
        # Initialize shared app for efficiency
        self.shared_app = build_graph()
        
        print(f"DynamicTradingManager initialized:")
        print(f"  Universe: {len(ticker_universe)} tickers")
        print(f"  Max active positions: {max_active_positions}")
        print(f"  Waitlist size: {waitlist_size}")
    
    def pre_market_scan(self) -> Tuple[List[str], List[str], Dict[str, float]]:
        """
        Perform pre-market news scan and generate trading lists.
        This implements: "read news before market opens, hold top 20 array"
        """
        print("\n" + "="*60)
        print("PRE-MARKET SCAN: Fetching news and generating watchlists")
        print("="*60)
        
        # Generate trading lists using sentiment analysis
        active_list, waitlist, sentiment_scores = get_top_tickers_by_sentiment(
            tickers=self.ticker_universe,
            top_n=self.max_active_positions,
            waitlist_n=self.waitlist_size,
            max_articles_per_ticker=self.max_articles_per_ticker,
            model_name=self.sentiment_model,
            pause=self.news_fetch_pause
        )
        
        # Store results
        self.active_list = active_list
        self.waitlist = waitlist
        self.all_sentiment_scores = sentiment_scores
        
        print(f"\nPRE-MARKET RESULTS:")
        print(f"  Active list ({len(self.active_list)}): {self.active_list}")
        print(f"  Waiting list ({len(self.waitlist)}): {self.waitlist}")
        
        return self.active_list, self.waitlist, self.all_sentiment_scores
    
    def update_lists_after_trades(self, newly_closed_positions: List[str]) -> None:
        """
        Update trading lists when positions close during the day.
        Implements: "Depending on number of trades closed, push remaining 
        on waiting list to open trades. Fill up the waiting list"
        """
        if not newly_closed_positions:
            return
            
        print(f"\n{len(newly_closed_positions)} positions closed: {newly_closed_positions}")
        self.closed_positions_today.extend(newly_closed_positions)
        
        # Update lists using the watchlist manager logic
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
        """Get current list of tickers to trade (active list)."""
        return self.active_list.copy()
    
    def run_trading_session(self, simulate_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Run a complete trading session with dynamic watchlist management.
        """
        print(f"\n{'='*60}")
        print(f"STARTING TRADING SESSION")
        if simulate_date:
            print(f"Simulated date: {simulate_date}")
        print(f"{'='*60}")
        
        # Step 1: Pre-market scan to get initial lists
        self.pre_market_scan()
        
        # Step 2: Run trading for active list
        if self.active_list:
            print(f"\nRunning concurrent trading for {len(self.active_list)} active positions...")
            results = run_watchlist_concurrent(
                tickers=self.active_list,
                portfolio_value=self.portfolio_value,
                analyst_model=self.analyst_model,
                max_workers=5  # Concurrent processing
            )
            
            # Store results
            self.daily_results.extend(results)
            
            # Extract newly closed positions from results
            newly_closed = []
            for result in results:
                if result.get("executed") and result.get("closed_trade"):
                    ticker = result.get("ticker")
                    if ticker and ticker not in self.closed_positions_today:
                        newly_closed.append(ticker)
            
            # Step 3: Update lists based on closed positions
            if newly_closed:
                self.update_lists_after_trades(newly_closed)
                
                # If we have waitlist and closed positions, we might want to trade more
                # For now, we'll note that new opportunities exist but wait for next cycle
                # In a real intraday system, you might immediately trade from waitlist
        else:
            print("WARNING: No active positions to trade!")
            results = []
        
        # Step 4: Session summary
        self._print_session_summary()
        
        return self.daily_results
    
    def _print_session_summary(self) -> None:
        """Print summary of the trading session."""
        print(f"\n{'='*60}")
        print(f"TRADING SESSION SUMMARY")
        print(f"{'='*60}")
        
        print(f"Pre-market scan completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Initial active list: {getattr(self, '_initial_active', 'N/A')}")
        print(f"Initial waitlist: {getattr(self, '_initial_waitlist', 'N/A')}")
        
        print(f"\nFinal active list ({len(self.active_list)}): {self.active_list}")
        print(f"Final waiting list ({len(self.waitlist)}): {self.waitlist}")
        print(f"Closed positions today ({len(self.closed_positions_today)}): {self.closed_positions_today}")
        
        if self.daily_results:
            executed_trades = [r for r in self.daily_results if r.get("executed")]
            print(f"\nTrades executed: {len(executed_trades)}/{len(self.daily_results)}")
            
            # Show performance by ticker
            for result in self.daily_results:
                ticker = result.get("ticker", "UNKNOWN")
                executed = result.get("executed", False)
                signal = result.get("llm_signal", result.get("signal", "N/A"))
                price = result.get("executed_price", 0.0)
                status = "EXECUTED" if executed else "SKIPPED"
                print(f"  {ticker:6} | {status:8} | Signal: {signal:5} | Price: {price:8.2f}")
        
        # Portfolio summary
        print(f"\n{self.risk_manager.portfolio_summary()}")
    
    def get_waitlist_opportunities(self, count: int = 5) -> List[Tuple[str, float]]:
        """
        Get top waiting list opportunities based on sentiment scores.
        Useful for monitoring or prepping for next cycle.
        """
        # Combine active and waitlist, excluding already traded/today closed
        excluded = set(self.active_list) | set(self.closed_positions_today)
        available = [
            (ticker, score) 
            for ticker, score in self.all_sentiment_scores.items() 
            if ticker not in excluded
        ]
        
        # Sort by score descending
        available.sort(key=lambda x: x[1], reverse=True)
        return available[:count]


def run_dynamic_trading_session(
    ticker_universe: List[str],
    simulate_date: Optional[str] = None,
    max_active_positions: int = 10,
    waitlist_size: int = 10,
    max_articles_per_ticker: int = 5,
    sentiment_model: str = "mistral",
    news_fetch_pause: float = 0.5,
    portfolio_value: float = 10_000,
    analyst_model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to run a complete dynamic trading session.
    
    Returns:
        Dictionary with session results and statistics
    """
    print("Initializing Dynamic Trading Manager...")
    
    manager = DynamicTradingManager(
        ticker_universe=ticker_universe,
        max_active_positions=max_active_positions,
        waitlist_size=waitlist_size,
        max_articles_per_ticker=max_articles_per_ticker,
        sentiment_model=sentiment_model,
        news_fetch_pause=news_fetch_pause,
        portfolio_value=portfolio_value,
        analyst_model=analyst_model
    )
    
    # Store initial lists for summary
    manager._initial_active = manager.active_list.copy()
    manager._initial_waitlist = manager.waitlist.copy()
    
    # Run the trading session
    results = manager.run_trading_session(simulate_date=simulate_date)
    
    # Prepare return value
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
    # Example usage
    print("=== Dynamic Trading System Demo ===")
    
    # Example ticker universe (you would expand this to 50-100 tickers)
    demo_universe = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
        "META", "NVDA", "NFLX", "AMD", "INTC",
        "CSCO", "ADBE", "CRM", "ORCL", "IBM",
        "QCOM", "TXN", "HON", "UNH", "JNJ",
        "PG", "JPM", "BAC", "WFC", "C",
        "V", "MA", "DIS", "NKE", "SBUX",
        "MCD", "WMT", "TGT", "COST", "HD",
        "LOW", "PG", "CL", "KMB", "GE",
        "CAT", "MMM", "BA", "F", "GM",
        "XOM", "CVX", "COP", "EOG", "SLB"
    ]
    
    try:
        # Run a trading session
        session = run_dynamic_trading_session(
            ticker_universe=demo_universe[:15],  # Limit for demo speed
            max_active_positions=5,              # Smaller for demo
            waitlist_size=5,
            max_articles_per_ticker=3,
            news_fetch_pause=2.0,                # Longer pause to be nice to APIs
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