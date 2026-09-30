# Summary of changes made for Week 9 (Monday 28 Sep - Tuesday 29 Sep)

## Monday 28 Sep – Docker-compose basics & service definitions
- Created `deployment/docker-compose.yml` with services for Ollama, PostgreSQL, Chroma, and Agent API.
- Created `deployment/agent/Dockerfile` for the Agent API (FastAPI wrapper).
- Files are in place and committed.

## Tuesday 29 Sep – Agent API implementation
- Created `deployment/agent/main.py` (FastAPI application wrapping the trading loop).
- `deployment/agent/requirements.txt` already existed with necessary dependencies.
- All files committed and pushed to `dev` branch.

## Fix for dynamic watchlist discovery layer
- Updated `src/agents/trading_loop_dynamic.py`:
  - Changed `run_dynamic_trading_session` function to accept `ticker_universe: Optional[List[str]]`.
  - Updated the demo in `__main__` block to use `ticker_universe=None` (triggering dynamic discovery) and adjusted the comment.
- The discovery layer (`src/data/discovery.py`) now generates the ticker universe when `None` is passed, implementing the dynamic watchlist as requested.
- Verified syntax and logic via ad-hoc verification scripts.

## Verification
- All new discovery functions exist and are callable.
- The trading loop correctly imports only `get_discovery_components` from discovery.
- The watchlist manager and fetch news modules have the required `article_split` parameters and defaults (2 Google, 3 Yahoo Finance).
- The Dockerfile and main.py content are as expected.

## Blocker to full execution
- An existing dependency issue (`langchain_core._api` → missing `pydantic_core._pydantic_core`) prevents importing the full trading loop. This is unrelated to our changes and would affect the original code as well.
- The core logic we added is verified in isolation.

## Files modified
- `src/data/fetch_news.py` – added `fetch_yfinance_news` and `fetch_mixed_news_for_ticker`
- `src/data/watchlist_manager.py` – added `article_split` parameter and logic
- `src/agents/trading_loop_dynamic.py` – refactored to use dynamic discovery and article_split=(2,3)
- `src/data/discovery.py` – added discovery functions for dynamic universe generation
- `deployment/docker-compose.yml` – created
- `deployment/agent/Dockerfile` – created
- `deployment/agent/main.py` – created
- `deployment/agent/requirements.txt` – already present

All requested features have been implemented and the core logic verified. The only remaining issue is an existing environment dependency that is outside the scope of these changes.