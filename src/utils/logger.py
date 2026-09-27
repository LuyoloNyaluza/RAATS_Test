"""
src/utils/logger.py

Four entry types now write to the same weekly-rotated JSONL file:
  type="cycle"           - log_cycle(), one per trading cycle (existing)
  type="error"           - log_error(), a day/cycle that raised an exception
  type="scan"            - log_scan(), one per ticker in a pre-market scan
  type="session_summary" - log_session_summary(), one per trading session

Previously, pre-market scan results (sentiment scores, active/waitlist
assignment) and session-level summaries only existed as console print
statements - gone the moment the terminal scrolled past them. They now
have a durable, structured record alongside the existing cycle log.

NOTE ON HISTORICAL SIMULATION: the weekly file is chosen by the wall-
clock time the code actually RUNS, not by any historical date being
simulated - see log_cycle()'s original note; this applies to all entry
types here.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo


LOG_DIR = "logs"
LOCAL_TZ = ZoneInfo("Africa/Johannesburg")


def _week_bounds(dt: datetime) -> tuple[str, str]:
    """Return (monday, sunday) as YYYY-MM-DD strings for dt's ISO week."""
    monday = dt.date() - timedelta(days=dt.weekday())  # Mon=0..Sun=6
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def _weekly_log_path(dt: datetime, log_dir: str = LOG_DIR) -> str:
    """Return the current week's JSONL log file path."""
    start, end = _week_bounds(dt)
    return os.path.join(log_dir, f"agent_performance_{start}_to_{end}.jsonl")


def _write_entry(entry: dict, log_dir: str = LOG_DIR) -> dict:
    """Shared append-one-line-of-JSON helper used by every log_* function."""
    now = datetime.now(LOCAL_TZ)
    os.makedirs(log_dir, exist_ok=True)
    path = _weekly_log_path(now, log_dir)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    return entry


def log_cycle(
    ticker: str,
    signal: str,
    executed_price: Optional[float],
    latencies: dict,
    pnl: float = 0.0,
    log_dir: str = LOG_DIR,
) -> dict:
    """Append one trading-cycle entry to the current week's JSONL file."""
    entry = {
        "timestamp": datetime.now(LOCAL_TZ).isoformat(),
        "type": "cycle",
        "signal": signal,
        "ticker": ticker,
        "executed_price": executed_price,
        "latencies_ms": latencies,
        "pnl": pnl,
    }
    return _write_entry(entry, log_dir)


def log_error(
    ticker: str,
    date: str,
    error: str,
    log_dir: str = LOG_DIR,
) -> dict:
    """Append an error entry - so a failed cycle/day has a durable record
    instead of only existing in a console printout or an in-memory result
    that's lost when the process exits.
    """
    entry = {
        "timestamp": datetime.now(LOCAL_TZ).isoformat(),
        "type": "error",
        "ticker": ticker,
        "date": date,
        "error": error,
    }
    return _write_entry(entry, log_dir)


def log_scan(
    ticker: str,
    sentiment_score: float,
    n_articles: int,
    list_assignment: str,
    log_dir: str = LOG_DIR,
) -> dict:
    """Append one pre-market scan result for a single ticker.

    Args:
        ticker: the instrument scanned.
        sentiment_score: aggregated sentiment score (-1..1).
        n_articles: number of articles that contributed to the score.
        list_assignment: "active", "waitlist", or "excluded".
    """
    entry = {
        "timestamp": datetime.now(LOCAL_TZ).isoformat(),
        "type": "scan",
        "ticker": ticker,
        "sentiment_score": round(sentiment_score, 4),
        "n_articles": n_articles,
        "list_assignment": list_assignment,
    }
    return _write_entry(entry, log_dir)


def log_session_summary(
    active_list: list,
    waitlist: list,
    hold_list: list,
    metrics: dict,
    log_dir: str = LOG_DIR,
) -> dict:
    """Append one end-of-session summary entry.

    Args:
        active_list: tickers that were traded this session.
        waitlist: tickers held in reserve, not traded.
        hold_list: tickers the LLM explicitly said HOLD for (distinct
                   from tickers blocked by the stability filter).
        metrics: the dict returned by
                 src.simulation.orchestrator.compute_performance_metrics.
    """
    entry = {
        "timestamp": datetime.now(LOCAL_TZ).isoformat(),
        "type": "session_summary",
        "active_list": active_list,
        "waitlist": waitlist,
        "hold_list": hold_list,
        "metrics": metrics,
    }
    return _write_entry(entry, log_dir)


def log_trade_event(
    event_type: str,
    trade_id: str,
    symbol: str,
    price: float,
    quantity: float,
    pnl: Optional[float] = None,
    reason: str = "",
) -> str:
    """Build a standardized, human-readable trade log line.

    Does NOT write to disk itself. Call print() or write it
    wherever you want it to show up.
    """
    timestamp = datetime.now(LOCAL_TZ).isoformat()
    log_entry = (
        f"{timestamp} | {event_type} | "
        f"TradeID:{trade_id} | {symbol} | "
        f"Price:{price:.2f} | Qty:{quantity:.4f}"
    )
    if pnl is not None:
        log_entry += f" | PnL:{pnl:.2f}"
    if reason:
        log_entry += f" | Reason:{reason}"
    return log_entry
