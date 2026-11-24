"""
src/data/mt5_orders.py

Order layer for MetaTrader 5: open a position with SL/TP, move SL/TP later, close it, and
read back what is open and how a position ended.

SAFETY
------
Orders are SENT to the broker by default. Set RAATS_LIVE_TRADING=0 and every call is a
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
import time
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
    """LIVE by default: orders are sent to the broker (your FBS DEMO account).

    Set RAATS_LIVE_TRADING=0 (or false/no/off) to go back to a dry run."""
    return os.environ.get("RAATS_LIVE_TRADING", "1").strip().lower() not in ("0", "false", "no", "off")


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


def realized_pnl_today() -> Optional[float]:
    """Net P&L of today's buy/sell deals from the broker (profit + commission + swap + fee).

    Deposits and withdrawals are excluded. 'Today' = the PC's calendar day, compared with the deal
    times as the broker stamps them; if the broker's clock is in another time zone than the PC,
    set RAATS_BROKER_TZ_SHIFT_HOURS (broker time minus PC time, in hours). None = unavailable.
    """
    if mt5 is None:
        return None
    from datetime import datetime, timedelta, timezone
    shift = float(os.environ.get("RAATS_BROKER_TZ_SHIFT_HOURS", "0") or 0)
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with session() as ok:
        if not ok:
            return None
        deals = mt5.history_deals_get(start - timedelta(days=1), now + timedelta(days=1))
        if deals is None:
            return None
        total = 0.0
        for d in deals:
            if d.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                continue
            when = datetime.fromtimestamp(d.time, tz=timezone.utc).replace(tzinfo=None) - timedelta(hours=shift)
            if when >= start:
                total += d.profit + d.commission + d.swap + float(getattr(d, "fee", 0.0) or 0.0)
        return total


def account_snapshot() -> Optional[Dict[str, float]]:
    """Balance, equity and floating P/L in ONE read. Balance only moves when a position closes;
    equity = balance + floating P/L moves with every tick."""
    with session() as ok:
        if not ok or mt5 is None:
            return None
        info = mt5.account_info()
        if info is None:
            return None
        return {"balance": float(info.balance), "equity": float(info.equity),
                "floating": float(info.profit)}


def overall_profit() -> Optional[float]:
    """Net P/L of every buy/sell deal in the account history (profit + commission + swap + fee),
    the figure of the MT5 History tab. Deposits, withdrawals and credit are excluded."""
    if mt5 is None:
        return None
    from datetime import datetime, timedelta
    with session() as ok:
        if not ok:
            return None
        deals = mt5.history_deals_get(datetime(2000, 1, 1), datetime.now() + timedelta(days=2))
        if deals is None:
            return None
        skip = {mt5.DEAL_TYPE_BALANCE, mt5.DEAL_TYPE_CREDIT}
        return round(sum(d.profit + d.commission + d.swap + float(getattr(d, "fee", 0.0) or 0.0)
                         for d in deals if d.type not in skip), 2)


def positions_detail() -> Optional[list]:
    """RAATS positions open at the broker, as the dashboard table shows them: swap, commission,
    P/L and % change included. Floating P/L = profit + swap (+ commission when the broker books
    it on the open deal). None when MT5 cannot be read."""
    if mt5 is None or not live_enabled():
        return None
    from datetime import datetime, timedelta, timezone
    with session() as ok:
        if not ok:
            return None
        raw = mt5.positions_get()
        if raw is None:
            return None
        mine = [p for p in raw if p.magic == MAGIC]
        # Commission lives on the entry deal, not on the position object.
        comm: Dict[int, float] = {}
        if mine:
            try:
                start = datetime.now() - timedelta(days=30)
                for d in mt5.history_deals_get(start, datetime.now() + timedelta(days=2)) or []:
                    if d.entry == mt5.DEAL_ENTRY_IN:
                        comm[d.position_id] = comm.get(d.position_id, 0.0) + d.commission + float(getattr(d, "fee", 0.0) or 0.0)
            except Exception:
                pass
        rows = []
        for p in mine:
            c = comm.get(p.identifier if hasattr(p, "identifier") else p.ticket)
            if c is None:
                c = float(getattr(p, "commission", 0.0) or 0.0)
            swap = float(p.swap or 0.0)
            pnl = float(p.profit or 0.0) + swap + c
            entry, cur = float(p.price_open), float(p.price_current)
            sign = 1 if p.type == 0 else -1
            pct = sign * (cur - entry) / entry * 100 if entry else None
            opened = datetime.fromtimestamp(p.time, tz=timezone.utc).astimezone().replace(tzinfo=None)
            rows.append({
                "ticket": int(p.ticket), "symbol": p.symbol, "side": "LONG" if p.type == 0 else "SHORT",
                "volume": float(p.volume), "entry": entry, "current": cur,
                "sl": float(p.sl) or None, "tp": float(p.tp) or None,
                "swap": round(swap, 2), "commission": round(c, 2), "profit": round(float(p.profit or 0.0), 2),
                "pnl": round(pnl, 2), "pct": round(pct, 2) if pct is not None else None,
                "opened": opened.isoformat(timespec="seconds"),
            })
        rows.sort(key=lambda r: r["opened"], reverse=True)
        return rows


def account_free_margin() -> Optional[float]:
    with session() as ok:
        if not ok or mt5 is None:
            return None
        info = mt5.account_info()
        return float(info.margin_free) if info is not None else None


def account_margin_used() -> Optional[float]:
    """Margin currently used by open positions (None if MT5 cannot be read)."""
    with session() as ok:
        if not ok or mt5 is None:
            return None
        info = mt5.account_info()
        return float(info.margin) if info is not None else None


def calc_margin(direction: str, symbol: str, lots: float, price: float) -> Optional[float]:
    with session() as ok:
        if not ok or mt5 is None:
            return None
        action = mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL
        value = mt5.order_calc_margin(action, symbol, lots, price)
        return float(value) if value is not None else None


def calc_profit(direction: str, symbol: str, lots: float, open_price: float,
                close_price: float) -> Optional[float]:
    """Profit (negative = loss) in ACCOUNT currency if a position opened at open_price is closed
    at close_price, from MT5's own calculation (contract size, tick value and currency
    conversion included). None when MT5 cannot answer."""
    with session() as ok:
        if not ok or mt5 is None:
            return None
        action = mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL
        value = mt5.order_calc_profit(action, symbol, lots, open_price, close_price)
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


def _fail(message: str, retcode: Optional[int] = None) -> Dict[str, Any]:
    return {"ok": False, "dry_run": False, "ticket": None, "price": None, "message": message,
            "retcode": retcode}


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


# order_check / order_send return codes that mean "the broker will not take an order on this
# symbol RIGHT NOW" (as opposed to a problem with the order itself).
_NOT_TRADING_NOW = {
    10018: "market closed",
    10017: "trading is disabled for this symbol",
    10021: "no quotes",
}
NOT_TRADING_NOW = _NOT_TRADING_NOW          # public name for callers that read a result's retcode

# Some brokers' order_check() answers "OK" on a closed market and only order_send() says 10018.
# When that happens the symbol is remembered as closed for a while, and check_order() reports it
# as not trading, so every screen built on check_order keeps the candidate waiting instead of
# proposing it again straight away.
CLOSED_COOLDOWN_SEC = float(os.environ.get("RAATS_CLOSED_MARKET_COOLDOWN_SEC", "900"))
_CLOSED_UNTIL: Dict[str, float] = {}


def mark_closed(symbol: str, seconds: Optional[float] = None) -> None:
    with _LOCK:
        _CLOSED_UNTIL[symbol] = time.time() + (CLOSED_COOLDOWN_SEC if seconds is None else seconds)


def recently_closed(symbol: str) -> bool:
    with _LOCK:
        until = _CLOSED_UNTIL.get(symbol, 0.0)
        if until and until <= time.time():
            _CLOSED_UNTIL.pop(symbol, None)
            return False
        return bool(until)


def check_order(symbol: str, direction: str, lots: float, sl: Optional[float] = None,
                tp: Optional[float] = None) -> Dict[str, Any]:
    """Ask the broker whether this market order WOULD be accepted right now (order_check).

    Nothing is placed and no authority token is needed, so it works in a dry run too: a dry run
    used to "open" positions on a closed market because it never asked the broker anything.

    Returns {checked, ok, retcode, comment, not_trading_now, reason}.
      checked=False  MT5 could not answer (not connected, no tick): callers must NOT block on it.
      not_trading_now=True  market closed / trading disabled / no quotes (reason says which).
    Other rejections (invalid stops, no money, ...) leave not_trading_now False: they are the
    order's own problem and are handled where the order is built.
    """
    out: Dict[str, Any] = {"checked": False, "ok": False, "retcode": None, "comment": "",
                           "not_trading_now": False, "reason": ""}
    if recently_closed(symbol):
        out.update(checked=True, retcode=10018, not_trading_now=True,
                   comment="broker refused an order on this symbol a moment ago",
                   reason="market closed")
        return out
    with session() as ok:
        if not ok or mt5 is None:
            out["comment"] = "MT5 not connected"
            return out
        snap = snapshot(symbol)
        if snap is None:
            out["comment"] = "no tick / symbol info"
            return out
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
            "comment": "RAATS check",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _filling(snap),
        }
        try:
            result = mt5.order_check(request)
        except Exception as exc:
            out["comment"] = f"order_check failed: {exc}"
            return out
        if result is None:
            out["comment"] = f"order_check returned None: {mt5.last_error()}"
            return out
        code = int(result.retcode)
        out.update(checked=True, retcode=code, comment=str(getattr(result, "comment", "") or ""),
                   ok=code in (0, getattr(mt5, "TRADE_RETCODE_DONE", 10009)))
        reason = _NOT_TRADING_NOW.get(code)
        if reason:
            out.update(not_trading_now=True, reason=reason)
        return out


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
        # Pre-trade check: the broker validates volume, stops, margin and trading conditions
        # WITHOUT placing anything. A rejected check never reaches order_send.
        check = mt5.order_check(request)
        if check is None:
            return _fail(f"order_check returned None: {mt5.last_error()}")
        if check.retcode not in (0, mt5.TRADE_RETCODE_DONE):
            if int(check.retcode) in _NOT_TRADING_NOW:
                mark_closed(symbol)
            return _fail(f"order_check rejected: retcode={check.retcode} "
                         f"{getattr(check, 'comment', '')}", retcode=int(check.retcode))
        result = mt5.order_send(request)
        if not _ok(result):
            code = int(result.retcode) if result is not None and getattr(result, "retcode", None) is not None else None
            if code in _NOT_TRADING_NOW:
                mark_closed(symbol)
            detail = f"retcode={getattr(result, 'retcode', None)} {getattr(result, 'comment', '')}" \
                if result is not None else f"order_send returned None: {mt5.last_error()}"
            return _fail(detail, retcode=code)
        ticket = _find_position_ticket(symbol, result.order) or result.order
        filled = float(getattr(result, "volume", 0) or lots)
        note = "filled" if abs(filled - float(lots)) < 1e-9 else \
            f"filled {filled:g} of {float(lots):g} lots"          # partial fill is reported
        return {"ok": True, "dry_run": False, "ticket": ticket, "volume": filled,
                "price": float(result.price or price), "message": note}


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
        code = int(last.reason)
        by_code = {
            getattr(mt5, "DEAL_REASON_SL", -1): "stop_loss",
            getattr(mt5, "DEAL_REASON_TP", -2): "take_profit",
            getattr(mt5, "DEAL_REASON_SO", -3): "stop_out",            # broker margin stop-out
            getattr(mt5, "DEAL_REASON_CLIENT", -4): "manual_close",    # desktop terminal
            getattr(mt5, "DEAL_REASON_MOBILE", -5): "manual_close",    # mobile terminal
            getattr(mt5, "DEAL_REASON_WEB", -6): "manual_close",       # web terminal
            getattr(mt5, "DEAL_REASON_EXPERT", -7): "expert_close",    # an EA / script (RAATS or other)
        }
        reason = by_code.get(code, "external_close")
        return {"price": float(last.price), "reason": reason,
                "profit": float(sum(d.profit + d.commission + d.swap for d in out)),
                "detail": {"deal_reason_code": code, "deal_comment": str(getattr(last, "comment", "") or ""),
                           "deal_ticket": int(last.ticket), "deal_time": int(last.time)}}


def intraday_atr(symbol: str, timeframe: str = "M5", period: int = 14, bars: int = 60) -> Optional[float]:
    """Wilder-style ATR(period) from the last CLOSED bars of an MT5 intraday timeframe.

    Returns None when MT5 cannot supply enough bars (caller falls back to the daily ATR).
    The still-forming bar is excluded so the value does not jitter while it builds.
    """
    if mt5 is None or not symbol:
        return None
    tf = getattr(mt5, "TIMEFRAME_" + timeframe.upper(), None)
    if tf is None:
        return None
    with session() as ok:
        if not ok:
            return None
        rates = mt5.copy_rates_from_pos(symbol, tf, 1, bars)      # start_pos=1 skips the forming bar
        if rates is None or len(rates) < period + 1:
            return None
        highs = [float(r["high"]) for r in rates]
        lows = [float(r["low"]) for r in rates]
        closes = [float(r["close"]) for r in rates]
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
           for i in range(1, len(rates))]
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr if atr > 0 else None