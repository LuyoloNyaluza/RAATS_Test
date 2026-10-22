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

import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypedDict, Dict, Any, List, Optional, Mapping

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
from src.utils.logger import log_cycle, log_sentiment_analysis, log_error
from src.data.score_sentiment import summarize_ticker_sentiment
from src.data.news_relevance import (
    filter_relevant_articles,
)


class AgentState(TypedDict, total=False):
    ticker: str
    market_data: Dict[str, Any]
    discovery_news: Dict[str, Any]
    scored_news: List[Any]
    sentiment_summary: Dict[str, Any]
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
    news_relevance: List[Dict[str, Any]]
    news_articles_retrieved: int
    news_articles_relevant: int
    treat_as_closed: bool


_STABILITY_FILTER = MarketStabilityFilter()


def _article_key(article: Mapping[str, Any]) -> tuple:
    """Identity for an article that survives copying (title + url)."""
    return (
        str(article.get("title", "")).strip().lower(),
        str(article.get("link") or article.get("url") or "").strip(),
    )


def _compact_articles(articles: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Only the audit fields - not full article bodies - go into the JSONL log."""
    keep = ("title", "url", "link", "discovery_source", "sentiment", "confidence", "reasoning")
    return [{k: a[k] for k in keep if k in a} for a in (articles or []) if isinstance(a, Mapping)]


def _compact_cycle_result(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Small, JSON-safe view of the cycle. The full state holds the RiskManager
    object, 30 closes and every article body; logging that duplicated all of it
    into every sentiment_analysis line."""
    keep = (
        "ticker", "stability_status", "llm_signal", "signal", "confidence",
        "executed", "executed_price", "direction", "position_size", "stop_loss",
        "take_profit", "risk_reason", "latencies", "analyst_model", "simulate_date",
        "news_articles_retrieved", "news_articles_relevant", "closed_trade",
    )
    return {k: state.get(k) for k in keep if k in state}


@node_timer("collector")
def collector_node(state: AgentState) -> AgentState:
    ticker = state.get("ticker")
    if ticker is None:
        raise ValueError("AgentState must include a ticker")
    as_of = state.get("simulate_date")

    state["market_data"] = collect_market_data(
        ticker,
        as_of=as_of,
    )

    discovery_news = state.get("discovery_news") or {
        "yfinance_news": [],
        "google_news": [],
    }

    # Validate news relevance.
    company_name = discovery_news.get("company_name")
    all_articles = []
    for source in ("yfinance_news", "google_news"):
        all_articles.extend(discovery_news.get(source, []))

    try:
        relevant_articles, relevance_results = filter_relevant_articles(
            articles=all_articles,
            ticker=ticker,
            company_name=company_name,
        )
    except Exception as exc:
        # Relevance filtering is an enhancement: if it fails, fall back to all
        # articles rather than killing the cycle, and leave a durable record.
        print(f"  WARNING: relevance filter failed for {ticker}: {exc}")
        try:
            log_error(
                ticker=ticker,
                date=str(as_of or datetime.now().date()),
                error=str(exc),
                stage="relevance_filter",
            )
        except Exception:
            pass
        relevant_articles, relevance_results = list(all_articles), []

    # Rebuild news using only relevant articles. Matching is by object identity
    # OR by (title, url): matching by id() alone silently returned ZERO articles
    # for every ticker whenever the filter returned copies instead of the
    # original dict objects.
    relevant_ids = {id(a) for a in relevant_articles}
    relevant_keys = {_article_key(a) for a in relevant_articles}
    filtered_news = {"yfinance_news": [], "google_news": [], "sentiment_summary": {}}
    for source in ("yfinance_news", "google_news"):
        filtered_news[source] = [
            a for a in discovery_news.get(source, [])
            if id(a) in relevant_ids or _article_key(a) in relevant_keys
        ]

    # Last-resort safety net: the filter kept articles but none matched.
    if relevant_articles and not (filtered_news["yfinance_news"] or filtered_news["google_news"]):
        for a in relevant_articles:
            tag = "yfinance_news" if a.get("discovery_source") == "yfinance" else "google_news"
            filtered_news[tag].append(a)

    filtered_scored = filtered_news["yfinance_news"] + filtered_news["google_news"]

    # The summary must describe the articles sentiment actually uses. It used to be
    # carried over from BEFORE filtering, so irrelevant articles still counted.
    if any(a.get("sentiment") for a in filtered_scored):
        filtered_news["sentiment_summary"] = summarize_ticker_sentiment(filtered_scored)
    else:
        filtered_news["sentiment_summary"] = discovery_news.get("sentiment_summary", {})

    # Keep diagnostics in state.
    state["news_relevance"] = relevance_results
    state["news_articles_retrieved"] = len(all_articles)
    state["news_articles_relevant"] = len(filtered_scored)

    # Sentiment receives filtered news only.
    state["sentiment"] = collect_sentiment(
        ticker,
        as_of=as_of,
        discovery_news=filtered_news,
    )

    # Audit trail = exactly what sentiment used. sentiment_summary was previously
    # a no-op self-assignment, so it was always {} and logged counts were always 0.
    state["scored_news"] = filtered_scored
    state["sentiment_summary"] = filtered_news["sentiment_summary"]

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

def build_daily_cycle_terminal_output(
    result: Mapping[str, Any],
) -> str:
    """
    Build the Daily Cycle Result text used for terminal output
    and persistent sentiment-analysis logging.
    """

    ticker = result.get(
        "ticker",
        "UNKNOWN",
    )

    stability = result.get(
        "stability_status",
        "n/a",
    )

    llm_signal = result.get(
        "llm_signal",
        result.get(
            "signal",
            "N/A",
        ),
    )

    confidence = result.get(
        "confidence",
        0.0,
    )

    model = result.get(
        "model",
        result.get(
            "analyst_model",
            "unknown",
        ),
    )

    executed = result.get(
        "executed",
        False,
    )

    executed_price = result.get(
        "executed_price"
    )

    risk_note = result.get(
        "risk_reason",
        "",
    )

    latencies = result.get("latencies") or result.get("latencies_ms") or {}

    return (
        "=== Daily Cycle Result ===\n"
        "\n"
        f"Ticker:      {ticker}\n"
        "\n"
        f"Stability:   {stability}\n"
        "\n"
        f"LLM signal:  {llm_signal} "
        f"(confidence: {confidence}, model: {model})\n"
        "\n"
        f"Executed:    {executed} @ {executed_price}\n"
        "\n"
        f"Risk note:   {risk_note}\n"
        "\n"
        f"Latencies:   {latencies}"
    )

def run_daily_cycle(
    ticker,
    app=None,
    risk_manager=None,
    portfolio_value: float = 10000,
    analyst_model=None,
    simulate_date=None,
    verbose=False,
    discovery_news=None,
    treat_as_closed=False,
    is_top_five=False,
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
        "discovery_news": discovery_news or {
        "yfinance_news": [],
        "google_news": [],
         "sentiment_summary": {},
         "treat_as_closed": treat_as_closed
},
    }
    # treat_as_closed was previously only inside the fallback discovery_news dict:
    # dropped whenever real news was passed, and never a top-level state key.
    initial_state["treat_as_closed"] = treat_as_closed
    _dn = dict(initial_state.get("discovery_news") or {})
    _dn.setdefault("treat_as_closed", treat_as_closed)
    initial_state["discovery_news"] = _dn
    final_state = app.invoke(initial_state)
    terminal_output = build_daily_cycle_terminal_output(final_state)
    if verbose:
        print(terminal_output)
    signal = str(final_state.get("llm_signal") or final_state.get("signal") or "")
    try:
        log_cycle(
            ticker=ticker,
            signal=signal,
            executed_price=final_state.get("executed_price"),
            latencies=final_state.get("latencies", {}),
            pnl=final_state.get("closed_trade", {}).get("pnl", 0.0),
        )
    except Exception as exc:  # logging must never break the trading cycle
        print(f"  WARNING: cycle log failed for {ticker}: {exc}")
    try:
        _summary = final_state.get("sentiment_summary") or {}
        log_sentiment_analysis(
            ticker=ticker,
            sentiment=_summary.get("overall"),
            sentiment_score=_summary.get("score"),
            positive=_summary.get("positive", 0),
            negative=_summary.get("negative", 0),
            neutral=_summary.get("neutral", 0),
            articles=_compact_articles(final_state.get("scored_news")),
            daily_cycle_result=_compact_cycle_result(final_state),
            terminal_output=terminal_output,
            model=os.environ.get("RAATS_SENTIMENT_MODEL"),
        )
    except Exception as exc:  # logging must never break the trading cycle
        print(f"  WARNING: sentiment log failed for {ticker}: {exc}")

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
            print(
                f"  ERROR processing "
                f"{ticker}: {exc}"
            )

            log_error(
                ticker=ticker,
                date=datetime.now().strftime("%Y-%m-%d"),
                error=str(exc),
                stage="daily_cycle",
                context={
                    "portfolio_value": portfolio_value,
                    "active_list": tickers,
                    "round": None,
                },
            )

            results.append({
                "ticker": ticker,
                "signal": "ERROR",
                "confidence": 0.0,
                "executed": False,
                "executed_price": None,
                "risk_reason": str(exc),
                "stability_status": "n/a",
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