from typing import TypedDict, Dict, Any

class AgentState(TypedDict):
    market_data: Dict[str, Any]   # price, volume, etc.
    sentiment: float              # -1 to 1
    llm_analysis: str             # raw LLM output
    signal: str                   # BUY, SELL, HOLD
    executed_price: float         # price at which trade simulated
    timestamp: str