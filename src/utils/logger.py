"""Logging utilities for the trading agent."""

import json
import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

CYCLE_LOG_FILE = "logs/agent_performance.jsonl"


def log_cycle(
    signal: str,
    executed_price: Optional[float],
    latencies: dict,
    pnl: float = 0.0,
    log_file: str = CYCLE_LOG_FILE,
) -> dict:
    """Log the results of a single trading cycle to a JSONL file."""
    entry = {
        "timestamp": datetime.now(ZoneInfo("Africa/Johannesburg")).isoformat(),
        "signal": signal,
        "executed_price": executed_price,
        "latencies_ms": latencies,
        "pnl": pnl,
    }

    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

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
    """Log a trade event (entry or exit) with details."""
    timestamp = datetime.now(ZoneInfo("Africa/Johannesburg")).isoformat()
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