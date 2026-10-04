"""
src/utils/logger.py

Weekly JSONL logging for RAATS.

Three weekly JSONL files are used:

1. agent_performance_YYYY-MM-DD_to_YYYY-MM-DD.jsonl
   Contains:
       - cycle
       - scan
       - session_summary
       - daily_watchlist

2. sentiment_analysis_YYYY-MM-DD_to_YYYY-MM-DD.jsonl
   Contains:
       - sentiment analysis
       - individual article sentiment
       - Daily Cycle Result
       - terminal-style analysis output

3. analysis_errors_YYYY-MM-DD_to_YYYY-MM-DD.jsonl
   Contains:
       - errors raised during discovery
       - errors during sentiment analysis
       - errors during daily-cycle processing
       - errors during replacement discovery

All files are rotated weekly from Monday to Sunday.

NOTE ON HISTORICAL SIMULATION:
The weekly file is selected using the wall-clock time
when the code actually runs, not the historical date being
simulated.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo


LOG_DIR = "logs"

LOCAL_TZ = ZoneInfo(
    "Africa/Johannesburg"
)


# ============================================================
# WEEKLY FILE HELPERS
# ============================================================

def _week_bounds(
    dt: datetime,
) -> tuple[str, str]:
    """
    Return the Monday and Sunday dates for the ISO week.
    """

    monday = (
        dt.date()
        - timedelta(days=dt.weekday())
    )

    sunday = (
        monday
        + timedelta(days=6)
    )

    return (
        monday.isoformat(),
        sunday.isoformat(),
    )


def _weekly_log_path(
    dt: datetime,
    prefix: str,
    log_dir: str = LOG_DIR,
) -> str:
    """
    Build a weekly JSONL path.

    Example:

        agent_performance_2026-09-28_to_2026-10-04.jsonl
        sentiment_analysis_2026-09-28_to_2026-10-04.jsonl
        analysis_errors_2026-09-28_to_2026-10-04.jsonl
    """

    start, end = _week_bounds(dt)

    return os.path.join(
        log_dir,
        f"{prefix}_{start}_to_{end}.jsonl",
    )


def _write_jsonl_entry(
    entry: dict,
    prefix: str,
    log_dir: str = LOG_DIR,
) -> dict:
    """
    Append one JSON object as one JSONL line.
    """

    now = datetime.now(
        LOCAL_TZ
    )

    os.makedirs(
        log_dir,
        exist_ok=True,
    )

    path = _weekly_log_path(
        now,
        prefix,
        log_dir,
    )

    with open(
        path,
        "a",
        encoding="utf-8",
    ) as f:

        f.write(
            json.dumps(
                entry,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
        )

        f.write("\n")

    return entry


# ============================================================
# AGENT PERFORMANCE LOG
# ============================================================

def log_cycle(
    ticker: str,
    signal: str,
    executed_price: Optional[float],
    latencies: dict,
    pnl: float = 0.0,
    log_dir: str = LOG_DIR,
) -> dict:
    """
    Append one trading-cycle entry to:

        agent_performance_YYYY-MM-DD_to_YYYY-MM-DD.jsonl
    """

    entry = {
        "timestamp": datetime.now(
            LOCAL_TZ
        ).isoformat(),

        "type": "cycle",

        "ticker": ticker,

        "signal": signal,

        "executed_price": executed_price,

        "latencies_ms": latencies,

        "pnl": pnl,
    }

    return _write_jsonl_entry(
        entry,
        "agent_performance",
        log_dir,
    )


# ============================================================
# SENTIMENT ANALYSIS LOG
# ============================================================

def log_sentiment_analysis(
    ticker: str,
    sentiment: Optional[str],
    sentiment_score: Optional[float],
    positive: int,
    negative: int,
    neutral: int,
    articles: Optional[list] = None,
    daily_cycle_result: Optional[dict] = None,
    terminal_output: Optional[str] = None,
    model: Optional[str] = None,
    log_dir: str = LOG_DIR,
) -> dict:
    """
    Append one sentiment-analysis record to:

        sentiment_analysis_YYYY-MM-DD_to_YYYY-MM-DD.jsonl

    The record contains both the sentiment analysis and the
    Daily Cycle Result associated with that analysis.
    """

    entry = {
        "timestamp": datetime.now(
            LOCAL_TZ
        ).isoformat(),

        "type": "sentiment_analysis",

        "ticker": ticker,

        "model": model,

        "sentiment": sentiment,

        "sentiment_score": (
            round(
                float(sentiment_score),
                4,
            )
            if sentiment_score is not None
            else None
        ),

        "positive": positive,

        "negative": negative,

        "neutral": neutral,

        "n_articles": len(
            articles or []
        ),

        "articles": articles or [],

        "daily_cycle_result": (
            daily_cycle_result or {}
        ),

        "terminal_output": terminal_output,
    }

    return _write_jsonl_entry(
        entry,
        "sentiment_analysis",
        log_dir,
    )


# ============================================================
# ANALYSIS ERROR LOG
# ============================================================

def log_error(
    ticker: str,
    date: str,
    error: str,
    stage: str = "unknown",
    context: Optional[dict] = None,
    log_dir: str = LOG_DIR,
) -> dict:
    """
    Append one analysis error to:

        analysis_errors_YYYY-MM-DD_to_YYYY-MM-DD.jsonl

    Examples of stage:

        discovery
        sentiment_analysis
        daily_cycle
        collector
        stability
        analyst
        executor
        replacement_discovery
    """

    entry = {
        "timestamp": datetime.now(
            LOCAL_TZ
        ).isoformat(),

        "type": "error",

        "ticker": ticker,

        "date": date,

        "stage": stage,

        "error": str(error),

        "context": context or {},
    }

    return _write_jsonl_entry(
        entry,
        "analysis_errors",
        log_dir,
    )


# ============================================================
# PRE-MARKET SCAN LOG
# ============================================================

def log_scan(
    ticker: str,
    sentiment_score: float,
    n_articles: int,
    list_assignment: str,
    log_dir: str = LOG_DIR,
) -> dict:
    """
    Append one pre-market scan result to:

        agent_performance_YYYY-MM-DD_to_YYYY-MM-DD.jsonl
    """

    entry = {
        "timestamp": datetime.now(
            LOCAL_TZ
        ).isoformat(),

        "type": "scan",

        "ticker": ticker,

        "sentiment_score": round(
            sentiment_score,
            4,
        ),

        "n_articles": n_articles,

        "list_assignment": list_assignment,
    }

    return _write_jsonl_entry(
        entry,
        "agent_performance",
        log_dir,
    )


# ============================================================
# SESSION SUMMARY
# ============================================================

def log_session_summary(
    active_list: list,
    waitlist: list,
    hold_list: list,
    metrics: dict,
    log_dir: str = LOG_DIR,
) -> dict:
    """
    Append one end-of-session summary to:

        agent_performance_YYYY-MM-DD_to_YYYY-MM-DD.jsonl
    """

    entry = {
        "timestamp": datetime.now(
            LOCAL_TZ
        ).isoformat(),

        "type": "session_summary",

        "active_list": active_list,

        "waitlist": waitlist,

        "hold_list": hold_list,

        "metrics": metrics,
    }

    return _write_jsonl_entry(
        entry,
        "agent_performance",
        log_dir,
    )


# ============================================================
# DAILY WATCHLIST
# ============================================================

def log_daily_watchlist(
    *,
    date: str,
    top50: list[str],
    random_list: list[str],
    top10_active: list[str],
    open_trades: list[dict],
    log_dir: str = LOG_DIR,
) -> dict:
    """
    Append a daily watchlist snapshot to:

        agent_performance_YYYY-MM-DD_to_YYYY-MM-DD.jsonl
    """

    entry = {
        "timestamp": datetime.now(
            LOCAL_TZ
        ).isoformat(),

        "type": "daily_watchlist",

        "date": date,

        "top50_tickers": top50,

        "random_list": random_list,

        "top10_active": top10_active,

        "open_trades": open_trades,
    }

    return _write_jsonl_entry(
        entry,
        "agent_performance",
        log_dir,
    )


# ============================================================
# TRADE EVENT
# ============================================================

def log_trade_event(
    event_type: str,
    trade_id: str,
    symbol: str,
    price: float,
    quantity: float,
    pnl: Optional[float] = None,
    reason: str = "",
) -> str:
    """
    Build a standardized human-readable trade log line.

    Does NOT write to disk itself.
    """

    timestamp = datetime.now(
        LOCAL_TZ
    ).isoformat()

    log_entry = (
        f"{timestamp} | {event_type} | "
        f"TradeID:{trade_id} | {symbol} | "
        f"Price:{price:.2f} | "
        f"Qty:{quantity:.4f}"
    )

    if pnl is not None:
        log_entry += (
            f" | PnL:{pnl:.2f}"
        )

    if reason:
        log_entry += (
            f" | Reason:{reason}"
        )

    return log_entry