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
from datetime import datetime
from pathlib import Path
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
    # indices (CFD names vary a lot by broker; first one the broker has wins).
    # Put YOUR broker's names first, or use RAATS_MT5_SYMBOL_MAP.
    "^GSPC": ["US500", "SPX500", "SP500", "USA500"],
    "^DJI": ["US30", "DJ30", "WS30", "USA30"],
    "^IXIC": ["USTEC", "NAS100", "US100", "NDX100"],
    "^RUT": ["US2000", "RUSSELL2000"],
    "^FTSE": ["UK100", "FTSE100"],
    "^GDAXI": ["GER40", "DE40", "DAX40", "GER30"],
    "^FCHI": ["FRA40", "FR40", "CAC40"],
    "^STOXX50E": ["EU50", "STOXX50", "ESTX50"],
    "^IBEX": ["ESP35", "SPA35", "ES35"],
    "^AEX": ["NETH25", "NL25"],
    "^N225": ["JP225", "JPN225", "NIKKEI225"],
    "^HSI": ["HK50", "HSI50", "HKG50"],
    "^AXJO": ["AUS200", "AU200"],
    "^BSESN": ["INDIA50"],
    "^NSEI": ["INDIA50", "NIFTY50"],
    "^KS11": ["KOR200"],
    "^TWII": ["TW50"],
}

# Equity suffixes brokers commonly use for US stocks.
EQUITY_SUFFIXES = ["", ".US", ".NAS", ".NYSE", "#", ".O", ".N"]

_cache: Dict[str, Optional[str]] = {}

# MT5 SYMBOL_TRADE_MODE_*: 0 disabled, 1 long only, 2 short only, 3 close only, 4 full.
TRADE_MODE_FULL = 4


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
    if ticker.startswith("^"):
        return []          # an index with no mapping: never guess a stock name like "^FOO.US"
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


def get_account_balance() -> Optional[float]:
    """
    Fetch current MT5 account balance.
    Returns None if MT5 unavailable.
    """
    if not initialize_mt5():
        return None
    
    try:
        account_info = mt5.account_info()
        if account_info is None:
            print(f"MT5: account_info() failed: {mt5.last_error()}")
            return None
        
        balance = account_info.balance
        print(f"MT5 Account Balance: ${balance:.2f}")
        return float(balance)
    except Exception as e:
        print(f"MT5 balance fetch error: {e}")
        return None
    finally:
        shutdown_mt5()


def notify_insufficient_balance(
    balance: float,
    min_balance: float = 20.0,
    final_invest: Optional[List[str]] = None,
) -> None:
    """Alert on Discord and write the weekly insufficient-funds log entry."""
    shortfall = min_balance - balance
    tickers = list(final_invest or [])
    msg = (
        "ACCOUNT BALANCE INSUFFICIENT - no trades were opened.\n"
        f"Balance: ${balance:,.2f} | Minimum required: ${min_balance:,.2f} | "
        f"Short by: ${shortfall:,.2f}\n"
        f"Please deposit at least ${shortfall:,.2f}."
    )
    if tickers:
        msg += f"\nBlocked tickers: {', '.join(tickers)}"

    try:
        from src.notifications.discord_notifier import DiscordNotifier
        DiscordNotifier().send_alert(msg)
    except Exception as exc:          # alerting must never block the log below
        print(f"  Discord alert not sent: {exc}")

    log_path = _get_insufficient_funds_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "balance": balance,
            "min_required": min_balance,
            "shortfall": shortfall,
            "action": "trades_blocked",
            "final_invest": list(final_invest or []),
        }) + "\n")

    print(msg)


def check_balance_and_notify(min_balance: float = 20.0) -> bool:
    """
    Check MT5 balance; alert + log if below threshold.
    Returns True if balance >= min_balance, False otherwise (including when
    the balance cannot be read).
    """
    balance = get_account_balance()

    if balance is None:
        print("Could not fetch MT5 balance")
        return False

    if balance < min_balance:
        notify_insufficient_balance(balance, min_balance)
        return False

    return True


def _get_insufficient_funds_log_path() -> Path:
    """Generate weekly log path for insufficient funds: insufficient_funds_YYYY-MM-DD_to_YYYY-MM-DD.jsonl"""
    from datetime import datetime, timedelta
    now = datetime.now()
    # Start of week (Monday)
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=6)
    start_str = week_start.strftime("%Y-%m-%d")
    end_str = week_end.strftime("%Y-%m-%d")
    # Use same directory as approvals: data/approvals/
    return Path("./data/approvals") / f"insufficient_funds_{start_str}_to_{end_str}.jsonl"


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


def is_mt5_tradable(ticker: str) -> bool:
    """True if the broker offers `ticker` with full (long + short) trading enabled.

    Needs an initialised MT5 session (initialize_mt5()). Used to drop reserve
    tickers the broker cannot trade, before they take a slot in the top 10.
    """
    symbol = resolve_mt5_symbol(ticker)
    if symbol is None:
        return False
    info = get_symbol_info(symbol) or {}
    return info.get("trade_mode", 0) == getattr(
        mt5, "SYMBOL_TRADE_MODE_FULL", TRADE_MODE_FULL
    )


# ------------------------------------------------------------------
# PUBLIC: ENRICH THE FINAL LIST
# ------------------------------------------------------------------

def enrich_final_invest(final_invest: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    For each ticker in the final INVEST list, return:

        {
          "mt5_symbol": "XAUUSD" | None,
          "tradable":   bool,         # broker offers it AND trading enabled
          "bid", "ask", "spread_points", "spread_pct", "tick_time",
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

            # RAATS opens both LONG and SHORT, so only FULL trading counts.
            # The old test "!= 0" also accepted close-only symbols.
            trade_enabled = info.get("trade_mode", 0) == getattr(
                mt5, "SYMBOL_TRADE_MODE_FULL", TRADE_MODE_FULL
            )
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
                "spread_pct": (
                    round((ask - bid) / ((ask + bid) / 2) * 100, 4)
                    if (bid and ask) else None
                ),
                "tick_time": tick.get("time"),
                "contract_size": info.get("trade_contract_size"),
                "volume_min": info.get("volume_min"),
                "volume_step": info.get("volume_step"),
                "digits": info.get("digits"),
                "trade_mode": info.get("trade_mode"),
            }
    finally:
        shutdown_mt5()

    return out