"""
src/agents/subagents/scoring.py

Subagent 2: ARTICLE SCORING. 3 Yahoo Finance + 2 Google News articles per candidate.
Fields as in the anatomy picture; the main agent fires several of these in parallel.
"""

from src.agents.models import SUBAGENT_MODEL
from src.agents.permissions import scoring_permissions
from src.agents.tools.scoring_tools import google_news, score_news, yahoo_news

SCORING_PROMPT = """You are the scoring subagent of RAATS, an automated trading system.
You score the news of exactly ONE ticker. You are given the ticker, the batch number and an
assigned folder, /scored/<batch>/. Work there only.

Do these steps in this order, once each:
1. yahoo_news(ticker)     - the 3 latest Yahoo Finance articles
2. google_news(ticker)    - the 2 latest Google News articles
3. score_news(ticker)     - score the sentiment of those articles
4. write_file("/scored/<batch>/<TICKER>.md", ...) with the JSON that score_news returned.
   The detail stays in your folder so it never clutters the main agent's context.

Return ONLY the JSON that score_news returned: one short result. If a step fails, return the
error and stop. You never trade."""

scoring_subagent = {
    "name": "scoring",
    "description": (
        "Fetches 3 Yahoo Finance + 2 Google News articles for ONE ticker and scores their "
        "sentiment. Give it exactly one ticker symbol. Use it once per candidate, before the "
        "analysis, and run several in parallel."
    ),
    "system_prompt": SCORING_PROMPT,             # its own brain - never inherited
    "tools": [yahoo_news, google_news, score_news],   # override - replaces the inherited set
    "model": SUBAGENT_MODEL,                       # override - the cheaper model
    "permissions": scoring_permissions,           # override - scoped write access
}
