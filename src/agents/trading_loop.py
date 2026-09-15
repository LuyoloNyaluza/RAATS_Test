"""
src/agents/trading_loop.py

Graph: collector -> stability -> [analyst -> executor] -> END
"""

from typing import TypedDict, Dict, Any, List, Optional

from langgraph.graph import StateGraph, END

from src.agents.collector import (
    collect_market_data,
    collect_sentiment,
    collect_ohlcv_frame,
)
from src.agents.analyst import analyze_market
from src.agents.executor import execute_trade
from src.risk.risk_manager import RiskManager
from src.risk.stability_filter import MarketStabilityFilter


class AgentState(TypedDict, total=False):
    ticker: str
    market_data: Dict[str, Any]
    sentiment: float
    llm_analysis: str
    llm_signal: str
    signal: str
    confidence: float
    executed: bool
    executed_price: Optional[float]
    position_size: float
    direction: str
    stop_loss: Optional[float]
    take_profit: Optional[float]
    risk_unit: float
    risk_reason: Optional[str]
    timestamp: str
    portfolio_value: float
    is_top_five: bool
    risk_manager: Any
    stability_status: str
    stability_detail: Dict[str, Any]


_STABILITY_FILTER = MarketStabilityFilter()


def collector_node(state: AgentState) -> AgentState:
    ticker = state.get("ticker", "AAPL")
    state["market_data"] = collect_market_data(ticker)
    state["sentiment"] = collect_sentiment(ticker)
    state["timestamp"] = state["market_data"]["timestamp"]
    return state


def stability_node(state: AgentState) -> AgentState:
    ticker = state.get("ticker", "AAPL")
    try:
        df = collect_ohlcv_frame(ticker)
        result = _STABILITY_FILTER.assess(df)
        state["stability_status"] = result.status
        state["stability_detail"] = result.indicators
        if not result.stable:
            state["risk_reason"] = f"Observation state - market Unstable ({', '.join(result.failed)})"
            state["signal"] = "HOLD"
            state["executed"] = False
            state["executed_price"] = None
    except Exception as exc:
        state["stability_status"] = "Unstable"
        state["stability_detail"] = {"error": str(exc)}
        state["risk_reason"] = f"Stability assessment failed: {exc}"
        state["signal"] = "HOLD"
        state["executed"] = False
        state["executed_price"] = None
    return state


def route_on_stability(state: AgentState) -> str:
    return "analyst" if state.get("stability_status") == "Stable" else "observe"


def analyst_node(state: AgentState) -> AgentState:
    result = analyze_market(dict(state))
    state.update(result)  # type: ignore[typeddict-item]
    return state


def executor_node(state: AgentState) -> AgentState:
    result = execute_trade(dict(state))
    state.update(result)  # type: ignore[typeddict-item]
    return state


def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("collector", collector_node)
    workflow.add_node("stability", stability_node)
    workflow.add_node("analyst", analyst_node)
    workflow.add_node("executor", executor_node)

    workflow.set_entry_point("collector")
    workflow.add_edge("collector", "stability")
    workflow.add_conditional_edges(
        "stability",
        route_on_stability,
        {"analyst": "analyst", "observe": END},
    )
    workflow.add_edge("analyst", "executor")
    workflow.add_edge("executor", END)
    return workflow.compile()


def run_daily_cycle(
    ticker: str = "AAPL",
    app=None,
    risk_manager: Optional[RiskManager] = None,
    portfolio_value: float = 10_000,
    is_top_five: bool = False,
):
    app = app or build_graph()
    initial_state: AgentState = {
        "ticker": ticker,
        "market_data": {},
        "sentiment": 0.0,
        "llm_analysis": "",
        "signal": "",
        "confidence": 0.0,
        "executed": False,
        "executed_price": None,
        "timestamp": "",
        "portfolio_value": portfolio_value,
        "is_top_five": is_top_five,
        "risk_manager": risk_manager,
        "stability_status": "",
    }
    final_state = app.invoke(initial_state)

    print("=== Daily Cycle Result ===")
    print(f"Ticker:      {final_state.get('ticker')}")
    print(f"Stability:   {final_state.get('stability_status')}")
    if final_state.get("stability_status") != "Stable":
        print(f"Deferred:    {final_state.get('risk_reason')}")
        return final_state

    print(f"LLM signal:  {final_state.get('llm_signal')} "
          f"(confidence: {final_state.get('confidence')})")
    print(f"Executed:    {final_state.get('executed')}  "
          f"@ {final_state.get('executed_price')}")
    if final_state.get("executed") and final_state.get("stop_loss") is not None:
        print(f"Direction:   {final_state.get('direction')}  size={final_state.get('position_size'):.4f}")
        print(f"SL / TP:     {final_state.get('stop_loss'):.2f} / {final_state.get('take_profit'):.2f}")
    print(f"Risk note:   {final_state.get('risk_reason')}")
    return final_state


def run_watchlist(
    tickers: List[str],
    portfolio_value: float = 10_000,
    top_five: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    app = build_graph()
    risk_manager = RiskManager()
    top_five = top_five or []
    results = []

    for ticker in tickers:
        print(f"\n{'=' * 50}\nProcessing {ticker}...\n{'=' * 50}")
        try:
            final_state = run_daily_cycle(
                ticker, app=app, risk_manager=risk_manager,
                portfolio_value=portfolio_value, is_top_five=ticker in top_five,
            )
            results.append(final_state)
        except Exception as exc:
            print(f"  ERROR processing {ticker}: {exc}")
            results.append({
                "ticker": ticker, "signal": "ERROR", "confidence": 0.0,
                "executed": False, "executed_price": None,
                "risk_reason": str(exc), "stability_status": "n/a",
            })

    print(f"\n\n{'=' * 50}\nWATCHLIST SUMMARY\n{'=' * 50}")
    for r in results:
        print(f"{r.get('ticker', '?'):6s} | {str(r.get('stability_status')):9s} | "
              f"signal: {str(r.get('llm_signal') or r.get('signal')):5s} | "
              f"executed: {str(r.get('executed')):5s} | {r.get('risk_reason')}")

    print("\nPortfolio:", risk_manager.portfolio_summary())
    return results


if __name__ == "__main__":
    watchlist = ["TSLA", "AAPL", "MSFT", "GOOGL", "AMZN",
                 "NVDA", "META", "NFLX", "AMD", "INTC"]
    run_watchlist(watchlist)