## Summary

Implemented dynamic watchlist management for RAATS trading system per user request:
- Created `src/data/watchlist_manager.py` with functions to:
  * Fetch news for 50-100 tickers pre-market
  * Score sentiment via Ollama
  * Generate active list (top 10) and waitlist (next 10)
  * Update lists as positions close, maintaining exactly 10 open trades
- Created `src/agents/trading_loop_dynamic.py` that orchestrates the workflow
- Added test files: `src/data/test_watchlist_manager.py` and `src/data/test_watchlist_manager_simple.py`
- Updated documentation: enhanced Week8_Setup.md, verified Week9-12_Setup.md contain runnable snippets
- Removed unused import (`load_and_clean_news`) from watchlist_manager.py

Verification (ad-hoc) confirmed:
- File exists and contains all required function definitions
- The previously unused import has been removed
- No syntax errors in the modified file

All changes committed to git branch `dev`.