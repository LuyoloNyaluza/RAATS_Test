"""
src/utils/trade_text.py

One place that turns "this ticker is INVEST" into the trade it stands for:
BUY or SELL, entry, stop loss, take profit and size. The loop print-out, the Discord
approval request, the end-of-day summary and the logs all use it, so they cannot drift apart.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional


def side(direction: Any) -> str:
    """LONG / +1 -> BUY, SHORT / -1 -> SELL."""
    return "BUY" if direction in ("LONG", 1, "BUY") else "SELL"


def _num(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{v:,.5f}" if abs(v) < 10 else f"{v:,.2f}"


def trade_rows(
    risk_manager: Any,
    tickers: Iterable[str],
    order_plan: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """One row per ticker: side, entry, SL, TP, units and (when MT5 sized it) lots.

    Reads the RiskManager position; the MT5 order plan, when present, adds lots, the MT5
    symbol and the broker-anchored levels (those are the ones that will really be sent).
    """
    rows: List[Dict[str, Any]] = []
    positions = getattr(risk_manager, "positions", {}) or {}
    for t in tickers:
        pos = positions.get(t)
        plan = (order_plan or {}).get(t) or {}
        row: Dict[str, Any] = {"ticker": t, "side": None, "entry": None, "stop_loss": None,
                               "take_profit": None, "units": None, "lots": None,
                               "mt5_symbol": plan.get("mt5_symbol"), "placeable": None,
                               "note": None}
        if pos is not None:
            row.update(side=side(pos.direction), entry=pos.entry_price, stop_loss=pos.stop_loss,
                       take_profit=pos.take_profit, units=pos.size)
        else:
            row["note"] = "no position opened (risk manager did not approve)"
        if plan:
            row["placeable"] = bool(plan.get("feasible"))
            row["waits"] = bool(plan.get("waits"))
            levels = plan.get("levels") or {}
            if plan.get("feasible") and levels:
                row.update(entry=levels.get("entry"), stop_loss=levels.get("stop_loss"),
                           take_profit=levels.get("take_profit"), lots=plan.get("lots"))
            elif not plan.get("feasible"):
                row["note"] = plan.get("reason")
            if plan.get("direction") and row["side"] is None:
                row["side"] = side(plan["direction"])
        rows.append(row)
    return rows


def format_row(row: Mapping[str, Any]) -> str:
    if row.get("side") is None:
        return f"{row['ticker']}: no trade - {row.get('note') or 'no position'}"
    size = (f"{row['lots']} lots" if row.get("lots") is not None
            else f"{_num(row.get('units'))} units")
    sym = f" ({row['mt5_symbol']})" if row.get("mt5_symbol") else ""
    line = (f"{row['ticker']}{sym} {row['side']} {size} @ {_num(row.get('entry'))} | "
            f"SL {_num(row.get('stop_loss'))} | TP {_num(row.get('take_profit'))}")
    if row.get("waits"):
        line += f"  [WAITS IN FINAL INVEST: {row.get('note')}]"
    elif row.get("placeable") is False:
        line += f"  [NOT PLACEABLE: {row.get('note')}]"
    return line


def format_rows(rows: Iterable[Mapping[str, Any]], indent: str = "  ") -> str:
    return "\n".join(indent + format_row(r) for r in rows)
