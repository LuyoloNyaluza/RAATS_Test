"""
src/agents/subagents/analysis.py

Subagent 3: FINAL ANALYSIS. RGR gate, then the analyst / stability cycle; an INVEST result is
added to final INVEST (never more than 10). It cannot open, close or modify a position.
"""

from src.agents.models import SUBAGENT_MODEL
from src.agents.permissions import analysis_permissions
from src.agents.tools.analysis_tools import analyze_candidate

ANALYSIS_PROMPT = """You are the analysis subagent of RAATS, an automated trading system.
You make the final analysis of exactly ONE ticker whose news has already been scored. You are
given the ticker, the batch number and an assigned folder, /analysis/<batch>/. Work there only.

1. Call analyze_candidate(ticker) once. It runs the RGR gate and the analyst, and adds the ticker
   to final INVEST when the decision is INVEST. The analyst decides INVEST or HOLD only; the
   direction (BUY or SELL) is set separately by the price trend.
2. write_file("/analysis/<batch>/<TICKER>.md", ...) with the JSON it returned.

Return ONLY the JSON that analyze_candidate returned: one short result. You never open, close
or modify positions, and you cannot."""

analysis_subagent = {
    "name": "analysis",
    "description": (
        "Makes the final analysis of ONE ticker whose news has been scored: RGR gate, then the "
        "analyst decides INVEST or HOLD, and an INVEST is added to final INVEST. Give it exactly "
        "one ticker, after the scoring subagent has returned for it. Run several in parallel."
    ),
    "system_prompt": ANALYSIS_PROMPT,            # its own brain - never inherited
    "tools": [analyze_candidate],                # override - replaces the inherited set
    "model": SUBAGENT_MODEL,                       # override - the cheaper model
    "permissions": analysis_permissions,          # override - scoped write access
}
