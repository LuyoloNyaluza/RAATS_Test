"""

log_cycle() writes one JSON object per line to a weekly-rotated
JSONL file. Each file covers one Monday-to-Sunday week and is
named with that week's date range.

Example:
logs/agent_performance_2026-09-14_to_2026-09-20.jsonl
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


def _weekly_log_path(
    dt: datetime,
    log_dir: str = LOG_DIR,
) -> str:
    """Return the current week's JSONL log file path."""
    start, end = _week_bounds(dt)

    return os.path.join(
        log_dir,
        f"agent_performance_{start}_to_{end}.jsonl",
    )


def log_cycle(
    ticker: str,
    signal: str,
    executed_price: Optional[float],
    latencies: dict,
    pnl: float = 0.0,
    log_dir: str = LOG_DIR,
) -> dict:
    """Append one trading-cycle entry to the current week's JSONL file.

    Args:
        signal: The signal that was acted on, such as BUY, SELL, or HOLD.
        ticker: The instrument ticker associated with the cycle.
        executed_price: Fill price if a trade executed, otherwise None.
        latencies: Dictionary containing node execution times in milliseconds.
        pnl: Realized PnL for this cycle. Defaults to 0.0.
        log_dir: Override the log directory, useful for testing.

    Returns:
        The entry written to the JSONL file.
    """

    now = datetime.now(LOCAL_TZ)

    entry = {
        "timestamp": now.isoformat(),
        "signal": signal,
        "ticker": ticker,
        "executed_price": executed_price,
        "latencies_ms": latencies,
        "pnl": pnl,
    }

    os.makedirs(log_dir, exist_ok=True)

    path = _weekly_log_path(now, log_dir)

    # JSONL format:
    # Each trading cycle is written as one complete JSON object
    # on its own line.
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    return entry


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

