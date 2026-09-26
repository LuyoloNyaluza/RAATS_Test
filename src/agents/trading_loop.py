"""
src/agents/trading_loop.py

FIX (this version): an already-open position was NOT being monitored on
Unstable days. The graph previously routed stability -> END on any
Unstable verdict, skipping executor_node entirely - which meant
update_stepping_stop() and check_exit() never ran for a position held
through a volatile period, exactly when stop-loss enforcement matters
most. Confirmed on real data: a LONG opened 2026-09-02 went unmonitored
on both 2026-09-03 and 2026-09-04 (both Unstable), with no code path to
catch a stop-loss breach on either day.

Root cause was purely a routing gap, not a bug in execute_trade() itself
- it already checks "is this ticker already in risk_manager.positions"
BEFORE looking at signal, so monitoring an open position never actually
needed the analyst to have run. The fix routes Unstable-but-holding
tickers directly to executor (skipping analyst, saving an LLM call too),
while Unstable-and-flat tickers still correctly defer to observation
with no new entry considered.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from src.utils.timer import node_timer
from src.utils.logger import log_cycle


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
    latencies: Dict[str, float]
    analyst_model: Optional[str]
    simulate_date: Optional[str]


_STABILITY_FILTER = MarketStabilityFilter()


@node_timer("collector")
def collector_node(state: AgentState) -> AgentState:
    ticker = state.get("ticker", "AAPL")
    as_of = state.get("simulate_date")
    state["market_data"] = collect_market_data(ticker, as_of=as_of)
    state["sentiment"] = collect_sentiment(ticker, as_of=as_of)
    state["timestamp"] = state["market_data"]["timestamp"]
    return state


@node_timer("stability")
def stability_node(state: AgentState) -> AgentState:
    ticker = state.get("ticker", "AAPL")
    as_of = state.get("simulate_date")
    try:
        df = collect_ohlcv_frame(ticker, as_of=as_of)
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
    """Stable -> analyst (full cycle, may open a new position).
    Unstable -> executor DIRECTLY if a position is already open on this
                ticker (monitor/exit only, no new entry considered, no
                LLM call spent); otherwise -> observe (defer, do nothing).
    """
    if state.get("stability_status") == "Stable":
        return "analyst"

    risk_manager = state.get("risk_manager")
    ticker = state.get("ticker")
    if risk_manager is not None and ticker in getattr(risk_manager, "positions", {}):
        return "executor"
    return "observe"


@node_timer("analyst")
def analyst_node(state: AgentState) -> AgentState:
    model_name = state.get("analyst_model")
    result = analyze_market(dict(state), model_name=model_name)
    state.update(result)  # type: ignore[typeddict-item]
    return state


@node_timer("executor")
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
        {"analyst": "analyst", "executor": "executor", "observe": END},
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
    analyst_model: Optional[str] = None,
    simulate_date: Optional[str] = None,
    verbose: bool = True,
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
        "latencies": {},
        "analyst_model": analyst_model,
        "simulate_date": simulate_date,
    }
    final_state = app.invoke(initial_state)
    signal = str(final_state.get("llm_signal") or final_state.get("signal") or "")
    log_cycle(
        ticker=ticker,
        signal=signal,
        executed_price=final_state.get("executed_price"),
        latencies=final_state.get("latencies", {}),
        pnl=final_state.get("closed_trade", {}).get("pnl", 0.0),
    )

    if verbose:
        print("=== Daily Cycle Result ===")
        print(f"Ticker:      {final_state.get('ticker')}"
              + (f"  (as of {simulate_date})" if simulate_date else ""))
        print(f"Stability:   {final_state.get('stability_status')}")
        if final_state.get("stability_status") != "Stable":
            print(f"Deferred:    {final_state.get('risk_reason')}")
            # NOTE: no longer an early return here - if a position was
            # actually open and monitored via the executor-direct route,
            # its result (closed_trade, updated stop, etc.) still needs
            # to print below rather than being cut off at this point.
        if final_state.get("analyst_model") is not None:
            print(f"LLM signal:  {final_state.get('llm_signal')} "
                  f"(confidence: {final_state.get('confidence')}, model: {final_state.get('analyst_model')})")
        print(f"Executed:    {final_state.get('executed')}  "
              f"@ {final_state.get('executed_price')}")
        if final_state.get("executed") and final_state.get("stop_loss") is not None:
            print(f"Direction:   {final_state.get('direction')}  size={final_state.get('position_size'):.4f}")
            print(f"SL / TP:     {final_state.get('stop_loss'):.2f} / {final_state.get('take_profit'):.2f}")
        print(f"Risk note:   {final_state.get('risk_reason')}")
        print(f"Latencies:   {final_state.get('latencies')}")
    return final_state


def run_watchlist(
    tickers: List[str],
    portfolio_value: float = 10_000,
    top_five: Optional[List[str]] = None,
    analyst_model: Optional[str] = None,
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
                analyst_model=analyst_model,
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


def run_watchlist_concurrent(
    tickers: List[str],
    portfolio_value: float = 10_000,
    analyst_model: Optional[str] = None,
    max_workers: int = 5,
) -> List[Dict[str, Any]]:
    app = build_graph()
    results = []

    def _run_one(ticker: str):
        rm = RiskManager()
        return run_daily_cycle(
            ticker, app=app, risk_manager=rm,
            portfolio_value=portfolio_value, analyst_model=analyst_model,
        )

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                print(f"  ERROR processing {ticker}: {exc}")
                results.append({
                    "ticker": ticker, "signal": "ERROR", "confidence": 0.0,
                    "executed": False, "executed_price": None,
                    "risk_reason": str(exc), "stability_status": "n/a",
                })
    elapsed = time.perf_counter() - start

    print(f"\n\n{'=' * 50}\nCONCURRENT WATCHLIST SUMMARY ({elapsed:.1f}s wall-clock, "
          f"max_workers={max_workers})\n{'=' * 50}")
    for r in results:
        print(f"{r.get('ticker', '?'):6s} | {str(r.get('stability_status')):9s} | "
              f"signal: {str(r.get('llm_signal') or r.get('signal')):5s} | "
              f"executed: {str(r.get('executed')):5s} | {r.get('risk_reason')}")

    return results


if __name__ == "__main__":
    watchlist = ["TSLA", "AAPL", "MSFT", "GOOGL", "AMZN",
                 "NVDA", "META", "NFLX", "AMD", "INTC"]
    run_watchlist(watchlist)