"""
src/data/mt5_bridge.py

Connects the discovery/trading output (Yahoo Finance symbols) to MetaTrader 5.

Why this is needed
------------------
discovery.py produces Yahoo symbols:   AAPL, GC=F, CL=F, EURUSD=X ...
MT5 uses the BROKER's symbols:         AAPL.US, XAUUSD, XTIUSD, EURUSD ...
and those names differ between brokers.  mt5_fetch.py only knows how to query
a symbol once you already have the right MT5 name, so this module:

  1. resolves  yahoo ticker -> MT5 symbol (tries several candidates and checks
     the broker actually has it),
  2. calls mt5_fetch for tick / symbol info on each resolved symbol,
  3. returns one dict per ticker, ready to attach to the final INVEST list.

MT5 only runs on Windows with the terminal installed and logged in.  If the
package or terminal is missing, every function degrades to "unavailable"
instead of raising, so the trading loop keeps working.
"""

import json
import os
from typing import Any, Dict, List, Optional

from src.data.mt5_fetch import get_latest_tick, get_symbol_info

# MetaTrader5 ships no type stubs, so Pylance cannot see its functions.
# Declaring the name as Any silences those false warnings; it is also None
# when the package is not installed (checked in initialize_mt5()).
mt5: Any
try:
    import MetaTrader5 as _mt5_module
    mt5 = _mt5_module
except ImportError:
    mt5 = None


# Yahoo -> candidate MT5 names (first one the broker has wins).
# Brokers differ: edit this, or override with the RAATS_MT5_SYMBOL_MAP env var
# (JSON, e.g. '{"CL=F": "USOIL"}').
STATIC_MAP: Dict[str, List[str]] = {
    # currencies
    "EURUSD=X": ["EURUSD"],
    "GBPUSD=X": ["GBPUSD"],
    "USDJPY=X": ["USDJPY"],
    "AUDUSD=X": ["AUDUSD"],
    "USDCAD=X": ["USDCAD"],
    # commodities
    "GC=F": ["XAUUSD", "GOLD"],
    "SI=F": ["XAGUSD", "SILVER"],
    "CL=F": ["XTIUSD", "USOIL", "WTI", "UKOIL"],
    "NG=F": ["XNGUSD", "NATGAS"],
    "HG=F": ["COPPER", "XCUUSD"],
}

# Equity suffixes brokers commonly use for US stocks.
EQUITY_SUFFIXES = ["", ".US", ".NAS", ".NYSE", "#", ".O", ".N"]

_cache: Dict[str, Optional[str]] = {}


def _load_overrides() -> Dict[str, List[str]]:
    raw = os.environ.get("RAATS_MT5_SYMBOL_MAP")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {
            k: ([v] if isinstance(v, str) else list(v)) for k, v in data.items()
        }
    except (json.JSONDecodeError, AttributeError):
        print("  WARNING: RAATS_MT5_SYMBOL_MAP is not valid JSON; ignored.")
        return {}


def candidates_for(ticker: str) -> List[str]:
    ticker = ticker.upper().strip()
    overrides = _load_overrides()
    if ticker in overrides:
        return overrides[ticker]
    if ticker in STATIC_MAP:
        return STATIC_MAP[ticker]
    return [ticker + s for s in EQUITY_SUFFIXES]   # plain equity


# ------------------------------------------------------------------
# CONNECTION
# ------------------------------------------------------------------

def initialize_mt5() -> bool:
    """Start MT5 once per session. Returns False instead of raising."""
    if mt5 is None:
        print("  MT5: package not installed - skipping MT5 step.")
        return False
    if not mt5.initialize():
        print(f"  MT5: initialize() failed: {mt5.last_error()}")
        return False
    return True


def shutdown_mt5() -> None:
    if mt5 is not None:
        mt5.shutdown()


# ------------------------------------------------------------------
# SYMBOL RESOLUTION
# ------------------------------------------------------------------

def resolve_mt5_symbol(ticker: str) -> Optional[str]:
    """Return the broker's name for `ticker`, or None if it is not offered."""
    if ticker in _cache:
        return _cache[ticker]

    found = None
    for name in candidates_for(ticker):
        # symbol_select adds it to Market Watch; needed before ticks work.
        if mt5.symbol_select(name, True) and mt5.symbol_info(name) is not None:
            found = name
            break

    _cache[ticker] = found
    return found


# ------------------------------------------------------------------
# PUBLIC: ENRICH THE FINAL LIST
# ------------------------------------------------------------------

def enrich_final_invest(final_invest: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    For each ticker in the final INVEST list, return:

        {
          "mt5_symbol": "XAUUSD" | None,
          "tradable":   bool,         # broker offers it AND trading enabled
          "bid", "ask", "spread_points", "tick_time",
          "contract_size", "volume_min", "volume_step", "digits"
        }

    Tickers MT5 does not offer get {"mt5_symbol": None, "tradable": False}.
    Returns {} if MT5 is unavailable.
    """
    if not final_invest or not initialize_mt5():
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    try:
        for ticker in final_invest:
            symbol = resolve_mt5_symbol(ticker)
            if symbol is None:
                out[ticker] = {"mt5_symbol": None, "tradable": False}
                continue

            info = get_symbol_info(symbol) or {}
            tick = get_latest_tick(symbol) or {}

            # SYMBOL_TRADE_MODE_DISABLED == 0
            trade_enabled = info.get("trade_mode", 0) != 0
            bid, ask = tick.get("bid"), tick.get("ask")
            point = info.get("point") or 0

            out[ticker] = {
                "mt5_symbol": symbol,
                "tradable": bool(trade_enabled and bid and ask),
                "bid": bid,
                "ask": ask,
                "spread_points": (
                    round((ask - bid) / point) if (bid and ask and point) else None
                ),
                "tick_time": tick.get("time"),
                "contract_size": info.get("trade_contract_size"),
                "volume_min": info.get("volume_min"),
                "volume_step": info.get("volume_step"),
                "digits": info.get("digits"),
            }
    finally:
        shutdown_mt5()

    return out