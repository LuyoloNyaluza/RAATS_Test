"""
src/agents/subagents/discovery.py

Subagent 1: DISCOVERY. Defined like `genre_researcher` in the anatomy picture.

  name          the handle the main agent calls:  task("discovery", ...)
  description   how the main agent decides to delegate (it reads this)
  system_prompt its own brain - not inherited
  tools         OVERRIDE: replaces the inherited set (it finds tickers, it never trades)
  model         OVERRIDE: the cheaper model
  permissions   OVERRIDE: may write only under /batches/*/candidates/**
"""

from src.agents.models import SUBAGENT_MODEL
from src.agents.permissions import discovery_permissions
from src.agents.tools.discovery_tools import check_tradable, load_candidate_pool, load_reserve_pool

DISCOVERY_PROMPT = """You are the discovery subagent of RAATS, an automated trading system.
You find tickers that have not been seen before. You never trade and you never invent tickers.

You are given the batch number and an assigned folder, /candidates/<batch>/. Work there only.

How you work:
- When asked to load the next candidate pool, call load_candidate_pool once.
- When asked to load the reserve, call load_reserve_pool once. It refuses unless the rule allows it.
- When asked whether a ticker can be traded, call check_tradable.
- Then save the tool's JSON with write_file("/candidates/<batch>/pool.md", ...).

Return ONLY the JSON that the tool returned: short, no commentary. The detail stays in your folder."""

discovery_subagent = {
    "name": "discovery",
    "description": (
        "Finds NEW tickers that have not been seen before: loads the candidate pool for the next "
        "batch (equities after the ones already used, currencies and commodities ranks 6-10) and, "
        "when fewer than 5 candidates are approved and the pool is used up, the reserve "
        "(10 trending, 10 most active, 10 world indices). Use it once at the start of a batch."
    ),
    "system_prompt": DISCOVERY_PROMPT,           # its own brain - never inherited
    "tools": [load_candidate_pool, load_reserve_pool, check_tradable],   # override - replaces the inherited set
    "model": SUBAGENT_MODEL,                       # override - the cheaper model
    "permissions": discovery_permissions,           # override - scoped write access
}
