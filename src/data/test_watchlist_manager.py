# File: src/data/test_watchlist_manager.py
"""
Test script for the watchlist manager module.
"""

import sys
import os

# Add the project root to path so we can import src modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.data.watchlist_manager import (
    fetch_universe_news,
    score_universe_sentiment,
    aggregate_ticker_sentiment,
    generate_trading_lists,
    update_trading_lists,
    get_top_tickers_by_sentiment
)