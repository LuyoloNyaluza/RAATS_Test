# File: src/agents/trading_loop.py
from typing import TypedDict, Dict, Any, List

from langgraph.graph import StateGraph, END

from src.agents.collector import collect_market_data, collect_sentiment
from src.agents.analyst import analyze_market
from src.agents.executor import execute_trade


class AgentState(TypedDict):
    ticker: str
    market_data: Dict[str, Any]
    sentiment: float
    llm_analysis: str
    signal: str
    confidence: float
    executed_price: float
    timestamp: str


def collector_node(state: AgentState) -> AgentState:
    ticker = state.get("ticker", "AAPL")
    state["market_data"] = collect_market_data(ticker)
    state["sentiment"] = collect_sentiment(ticker)
    state["timestamp"] = state["market_data"]["timestamp"]
    return state


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
    workflow.add_node("analyst", analyst_node)
    workflow.add_node("executor", executor_node)
    workflow.set_entry_point("collector")
    workflow.add_edge("collector", "analyst")
    workflow.add_edge("analyst", "executor")
    workflow.add_edge("executor", END)
    return workflow.compile()


def run_daily_cycle(ticker: str = "AAPL", app=None):
    """Run the full collector -> analyst -> executor cycle for one ticker.

    Args:
        app: an already-compiled graph (from build_graph()). Pass this in
             when calling repeatedly across tickers so the graph is only
             built once rather than once per ticker.
    """
    app = app or build_graph()
    initial_state: AgentState = {
        "ticker": ticker,
        "market_data": {},
        "sentiment": 0.0,
        "llm_analysis": "",
        "signal": "",
        "confidence": 0.0,
        "executed_price": 0.0,
        "timestamp": "",
    }
    final_state = app.invoke(initial_state)
    print("=== Daily Cycle Result ===")
    print(f"Ticker: {final_state['ticker']}")
    print(f"Signal: {final_state['signal']} (confidence: {final_state['confidence']})")
    print(f"Executed Price: {final_state['executed_price']}")
    print(f"LLM Analysis: {final_state['llm_analysis'][:200]}...")
    return final_state


def run_watchlist(tickers: List[str]) -> List[Dict[str, Any]]:
    """Run the daily cycle across a list of tickers.

    Builds the graph once and reuses it across all tickers. A failure on
    one ticker (missing data, Ollama down, etc.) is caught and recorded
    rather than aborting the rest of the watchlist.
    """
    app = build_graph()
    results = []

    for ticker in tickers:
        print(f"\n{'=' * 50}\nProcessing {ticker}...\n{'=' * 50}")
        try:
            final_state = run_daily_cycle(ticker, app=app)
            results.append(final_state)
        except Exception as exc:
            print(f"  ERROR processing {ticker}: {exc}")
            results.append({
                "ticker": ticker,
                "signal": "ERROR",
                "confidence": 0.0,
                "executed_price": None,
                "llm_analysis": str(exc),
                "market_data": {},
                "sentiment": 0.0,
                "timestamp": "",
            })

    print(f"\n\n{'=' * 50}\nWATCHLIST SUMMARY\n{'=' * 50}")
    for r in results:
        print(f"{r['ticker']:6s} | signal: {r['signal']:5s} | "
              f"confidence: {r['confidence']:.2f} | price: {r['executed_price']}")

    return results


if __name__ == "__main__":
    watchlist = ["TSLA", "AAPL", "MSFT", "GOOGL", "AMZN",
                 "NVDA", "META", "NFLX", "AMD", "INTC"]
    run_watchlist(watchlist)