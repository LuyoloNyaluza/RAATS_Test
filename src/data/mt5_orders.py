"""
src/data/mt5_orders.py

Order layer for MetaTrader 5: open a position with SL/TP, move SL/TP later, close it, and
read back what is open and how a position ended.

SAFETY
------
Orders are only SENT to the broker when RAATS_LIVE_TRADING=1. Otherwise every call is a
dry run: it reads live MT5 prices when MT5 is available, keeps the "position" in memory
and reports what it would have done. Test on a DEMO account first.

All positions carry a magic number (RAATS_MT5_MAGIC, default 77010) so RAATS only ever
touches its own positions.

CONNECTION
----------
Everything here goes through one lock and re-connects when needed, without calling
mt5.shutdown(). (mt5_bridge.get_account_balance() shuts MT5 down after each call; use
account_balance() below inside the background agents so they never cut each other off.)
"""

import contextlib
import itertools
import os
import threading
from typing import Any, Dict, Optional

try:
    from src.data.mt5_bridge import mt5, resolve_mt5_symbol, is_mt5_tradable
except Exception:                       # MT5 / bridge not available (tests, non-Windows)
    mt5 = None
    resolve_mt5_symbol = None
    is_mt5_tradable = None

MAGIC = int(os.environ.get("RAATS_MT5_MAGIC", "77010"))
DEVIATION = int(os.environ.get("RAATS_MT5_DEVIATION", "20"))

_LOCK = threading.RLock()
_AUTHORITY: Any = None
_DRY: Dict[str, Dict[str, Any]] = {}
_DRY_IDS = itertools.count(1)


# ------------------------------------------------------------------ write authority
# Only ONE holder (the main agent) may open, close or modify positions. The subagents never
# receive the token, so a bug or a race in them cannot place an order or change a stop.
def grant_authority(token: Any) -> None:
    global _AUTHORITY
    with _LOCK:
        if _AUTHORITY is not None and _AUTHORITY is not token:
            raise PermissionError("another main agent already holds MT5 write authority")
        _AUTHORITY = token


def release_authority(token: Any) -> None:
    global _AUTHORITY
    with _LOCK:
        if _AUTHORITY is token:
            _AUTHORITY = None


def _require(token: Any) -> None:
    if _AUTHORITY is None or token is not _AUTHORITY:
        raise PermissionError("only the main agent may open, close or modify MT5 positions")


def live_enabled() -> bool:
    return os.environ.get("RAATS_LIVE_TRADING", "").strip().lower() in ("1", "true", "yes")


# ------------------------------------------------------------------ connection
def _ensure() -> bool:
    if mt5 is None:
        return False
    try:
        if mt5.terminal_info() is not None:
            return True
    except Exception:
        pass
    try:
        return bool(mt5.initialize())
    except Exception:
        return False


@contextlib.contextmanager
def session():
    """Hold the MT5 lock with a connected terminal. Yields True/False (connected)."""
    with _LOCK:
        yield _ensure()


def available() -> bool:
    with session() as ok:
        return ok


# ------------------------------------------------------------------ symbols / prices
def resolve(ticker: str) -> Optional[str]:
    with session() as ok:
        if not ok or resolve_mt5_symbol is None:
            return None
        return resolve_mt5_symbol(ticker)


def tradable(ticker: str) -> bool:
    """Broker offers it with full long+short trading (for the discovery filter)."""
    with session() as ok:
        if not ok or is_mt5_tradable is None:
            return False
        return bool(is_mt5_tradable(ticker))


def snapshot(symbol: str) -> Optional[Dict[str, Any]]:
    with session() as ok:
        if not ok or mt5 is None:
            return None
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None or tick is None:
            return None
        return {
            "symbol": symbol,
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "digits": int(getattr(info, "digits", 5)),
            "point": float(getattr(info, "point", 0.00001)),
            "stops_level": int(getattr(info, "trade_stops_level", 0) or 0),
            "contract_size": float(getattr(info, "trade_contract_size", 1.0) or 1.0),
            "volume_min": float(getattr(info, "volume_min", 0.01) or 0.01),
            "volume_max": float(getattr(info, "volume_max", 100.0) or 100.0),
            "volume_step": float(getattr(info, "volume_step", 0.01) or 0.01),
            "filling_mode": int(getattr(info, "filling_mode", 0) or 0),
            "trade_mode": int(getattr(info, "trade_mode", 4)),
        }


def exit_price(snap: Dict[str, Any], direction: str) -> float:
    """Price a position would be closed at: bid for LONG, ask for SHORT."""
    return snap["bid"] if direction == "LONG" else snap["ask"]


def clamp_levels(direction: str, sl: Optional[float], tp: Optional[float],
                 snap: Dict[str, Any]) -> tuple:
    """Push SL/TP outside the broker's minimum stop distance and round to its digits."""
    dist = max(snap.get("stops_level", 0), 0) * snap.get("point", 0.0)
    nd = snap.get("digits", 5)
    bid, ask = snap["bid"], snap["ask"]
    if direction == "LONG":
        if sl is not None:
            sl = min(sl, bid - dist)
        if tp is not None:
            tp = max(tp, ask + dist)
    else:
        if sl is not None:
            sl = max(sl, ask + dist)
        if tp is not None:
            tp = min(tp, bid - dist)
    return (round(sl, nd) if sl is not None else None,
            round(tp, nd) if tp is not None else None)


# ------------------------------------------------------------------ account
def account_balance() -> Optional[float]:
    with session() as ok:
        if not ok or mt5 is None:
            return None
        info = mt5.account_info()
        return float(info.balance) if info is not None else None


def account_free_margin() -> Optional[float]:
    with session() as ok:
        if not ok or mt5 is None:
            return None
        info = mt5.account_info()
        return float(info.margin_free) if info is not None else None


def calc_margin(direction: str, symbol: str, lots: float, price: float) -> Optional[float]:
    with session() as ok:
        if not ok or mt5 is None:
            return None
        action = mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL
        value = mt5.order_calc_margin(action, symbol, lots, price)
        return float(value) if value is not None else None


# ------------------------------------------------------------------ orders
def _filling(snap: Dict[str, Any]) -> int:
    if mt5 is None:
        return 0
    mode = snap.get("filling_mode", 0)
    if mode & 2:
        return mt5.ORDER_FILLING_IOC
    if mode & 1:
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


def _ok(result: Any) -> bool:
    if result is None or mt5 is None:
        return False
    return result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)


def _fail(message: str) -> Dict[str, Any]:
    return {"ok": False, "dry_run": False, "ticket": None, "price": None, "message": message}


def _find_position_ticket(symbol: str, order_ticket: int) -> Optional[int]:
    if mt5 is None:
        return None
    positions = [p for p in (mt5.positions_get(symbol=symbol) or []) if p.magic == MAGIC]
    for p in positions:
        if p.ticket == order_ticket or getattr(p, "identifier", None) == order_ticket:
            return p.ticket
    if positions:
        return max(positions, key=lambda p: getattr(p, "time_msc", 0)).ticket
    return None


def place_market_order(symbol: str, direction: str, lots: float, sl: Optional[float],
                       tp: Optional[float], comment: str = "RAATS",
                       ref_price: Optional[float] = None, token: Any = None) -> Dict[str, Any]:
    """Open a market position. Returns {ok, dry_run, ticket, price, message}.

    Requires the main agent's authority token.
    """
    _require(token)
    if not live_enabled():
        price = ref_price
        if price is None:
            snap = snapshot(symbol)
            price = (snap["ask"] if direction == "LONG" else snap["bid"]) if snap else None
        ticket = f"DRY-{next(_DRY_IDS)}"
        with _LOCK:
            _DRY[ticket] = {"ticket": ticket, "symbol": symbol, "direction": direction,
                            "volume": lots, "price_open": price, "sl": sl, "tp": tp,
                            "comment": comment}
        return {"ok": True, "dry_run": True, "ticket": ticket, "price": price,
                "message": "dry run - no order sent"}

    with session() as ok:
        if not ok:
            return _fail("MT5 not connected")
        if mt5 is None:
            return _fail("MT5 package is unavailable")
        snap = snapshot(symbol)
        if snap is None:
            return _fail("no tick / symbol info")
        price = snap["ask"] if direction == "LONG" else snap["bid"]
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lots),
            "type": mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": float(sl) if sl else 0.0,
            "tp": float(tp) if tp else 0.0,
            "deviation": DEVIATION,
            "magic": MAGIC,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _filling(snap),
        }
        result = mt5.order_send(request)
        if not _ok(result):
            detail = f"retcode={getattr(result, 'retcode', None)} {getattr(result, 'comment', '')}" \
                if result is not None else f"order_send returned None: {mt5.last_error()}"
            return _fail(detail)
        ticket = _find_position_ticket(symbol, result.order) or result.order
        return {"ok": True, "dry_run": False, "ticket": ticket,
                "price": float(result.price or price), "message": "filled"}


def modify_sltp(ticket: Any, symbol: str, sl: Optional[float], tp: Optional[float],
                token: Any = None) -> Dict[str, Any]:
    """Move SL/TP of an open position. Requires the main agent's authority token."""
    _require(token)
    if not live_enabled() or str(ticket).startswith("DRY-"):
        with _LOCK:
            pos = _DRY.get(str(ticket))
            if pos is None:
                return _fail("unknown dry position")
            pos["sl"], pos["tp"] = sl, tp
        return {"ok": True, "dry_run": True, "message": "dry run - SL/TP not sent"}

    with session() as ok:
        if not ok:
            return _fail("MT5 not connected")
        if mt5 is None:
            return _fail("MT5 package is unavailable")
        request = {"action": mt5.TRADE_ACTION_SLTP, "position": int(ticket), "symbol": symbol,
                   "sl": float(sl) if sl else 0.0, "tp": float(tp) if tp else 0.0, "magic": MAGIC}
        result = mt5.order_send(request)
        no_change = getattr(mt5, "TRADE_RETCODE_NO_CHANGES", 10025)
        if result is not None and result.retcode == no_change:
            return {"ok": True, "dry_run": False, "message": "no change"}
        if not _ok(result):
            detail = f"retcode={getattr(result, 'retcode', None)} {getattr(result, 'comment', '')}" \
                if result is not None else f"order_send returned None: {mt5.last_error()}"
            return _fail(detail)
        return {"ok": True, "dry_run": False, "message": "modified"}


def close_position(ticket: Any, symbol: str, direction: str, lots: float,
                   ref_price: Optional[float] = None, token: Any = None) -> Dict[str, Any]:
    """Close a position at market. Requires the main agent's authority token."""
    _require(token)
    if not live_enabled() or str(ticket).startswith("DRY-"):
        with _LOCK:
            _DRY.pop(str(ticket), None)
        return {"ok": True, "dry_run": True, "price": ref_price, "message": "dry run - not sent"}

    with session() as ok:
        if not ok:
            return _fail("MT5 not connected")
        if mt5 is None:
            return _fail("MT5 not available")
        snap = snapshot(symbol)
        if snap is None:
            return _fail("no tick / symbol info")
        price = snap["bid"] if direction == "LONG" else snap["ask"]
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "position": int(ticket),
            "volume": float(lots),
            "type": mt5.ORDER_TYPE_SELL if direction == "LONG" else mt5.ORDER_TYPE_BUY,
            "price": price, "deviation": DEVIATION, "magic": MAGIC,
            "comment": "RAATS close", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _filling(snap),
        }
        result = mt5.order_send(request)
        if not _ok(result):
            detail = f"retcode={getattr(result, 'retcode', None)} {getattr(result, 'comment', '')}" \
                if result is not None else f"order_send returned None: {mt5.last_error()}"
            return _fail(detail)
        return {"ok": True, "dry_run": False, "price": float(result.price or price),
                "message": "closed"}


# ------------------------------------------------------------------ read back
def list_positions() -> Optional[Dict[Any, Dict[str, Any]]]:
    """RAATS positions open at the broker, keyed by ticket.

    Returns None (NOT an empty dict) when MT5 cannot be read, so a connection problem is
    never mistaken for "everything was closed".
    """
    if not live_enabled():
        with _LOCK:
            return {k: dict(v) for k, v in _DRY.items()}
    if mt5 is None:
        return None
    with session() as ok:
        if not ok:
            return None
        raw = mt5.positions_get()
        if raw is None:
            return None
        out = {}
        for p in raw:
            if p.magic != MAGIC:
                continue
            out[p.ticket] = {
                "ticket": p.ticket, "symbol": p.symbol,
                "direction": "LONG" if p.type == 0 else "SHORT",
                "volume": p.volume, "price_open": p.price_open,
                "sl": p.sl or None, "tp": p.tp or None, "profit": p.profit,
                "comment": getattr(p, "comment", ""),
            }
        return out


def closed_deal_info(ticket: Any) -> Optional[Dict[str, Any]]:
    """How a position ended: exit price, profit and why (stop_loss / take_profit / manual)."""
    if not live_enabled() or str(ticket).startswith("DRY-"):
        return None
    with session() as ok:
        if not ok or mt5 is None:
            return None
        deals = mt5.history_deals_get(position=int(ticket)) or []
        out = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        if not out:
            return None
        last = out[-1]
        if last.reason == getattr(mt5, "DEAL_REASON_SL", -1):
            reason = "stop_loss"
        elif last.reason == getattr(mt5, "DEAL_REASON_TP", -2):
            reason = "take_profit"
        else:
            reason = "closed_at_broker"
        return {"price": float(last.price), "reason": reason,
                "profit": float(sum(d.profit + d.commission + d.swap for d in out))}
