"""
src/data/mt5_sizing.py

Adapter between RAATS's paper positions and what MT5 can actually place.

Nothing in risk_manager / executor / stability_filter is changed. This module only READS
the positions they open (units, entry, stop, target) plus the MT5 data that
mt5_bridge.enrich_final_invest already collected, and turns them into an order plan:

  * units  -> lots   (units / contract_size, rounded DOWN to volume_step)
  * flags trades whose lot size falls below the broker's volume_min (not placeable;
    never rounded UP, because that would silently take more risk than RAATS sized)
  * stop / target re-anchored to the broker's own bid/ask (Yahoo and CFD prices differ)
  * optional margin check against free margin (needs MT5 connected)

Call build_order_plan(risk_manager, mt5_data) after enrich_final_invest().
"""

import math
from typing import Any, Dict, Optional


def _decimals(step: float) -> int:
    text = f"{step:.10f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def to_mt5_lots(
    units: float,
    contract_size: Optional[float],
    volume_min: Optional[float],
    volume_step: Optional[float],
) -> Dict[str, Any]:
    """Convert RAATS units (shares / index units) to MT5 lots.

    Rounds DOWN to volume_step. feasible is False when the result is below volume_min.
    """
    if not units or units <= 0:
        return {"feasible": False, "lots": 0.0, "raw_lots": 0.0, "reason": "no position size"}
    if not contract_size or not volume_min or not volume_step:
        return {"feasible": False, "lots": 0.0, "raw_lots": None,
                "reason": "missing MT5 contract data (contract_size/volume_min/volume_step)"}

    raw = units / contract_size
    lots = math.floor(raw / volume_step + 1e-9) * volume_step
    lots = round(lots, _decimals(volume_step))

    if lots < volume_min:
        return {
            "feasible": False, "lots": 0.0, "raw_lots": raw,
            "min_lot_units": volume_min * contract_size,
            "oversize_factor": round((volume_min * contract_size) / units, 2),
            "reason": (f"below broker minimum: sized {raw:.6f} lots, minimum {volume_min} "
                       f"(smallest trade is {volume_min * contract_size / units:.1f}x "
                       f"the size RAATS wanted)"),
        }
    return {"feasible": True, "lots": lots, "raw_lots": raw, "reason": "ok"}


def broker_levels(position: Any, bid: float, ask: float, digits: Optional[int]) -> Dict[str, float]:
    """Re-anchor the paper stop/target to the broker's price, keeping the same distances."""
    d = position.direction
    entry = ask if d == 1 else bid
    sl_dist = (position.entry_price - position.stop_loss) * d
    tp_dist = (position.take_profit - position.entry_price) * d
    nd = digits if digits is not None else 5
    return {
        "entry": round(entry, nd),
        "stop_loss": round(entry - d * sl_dist, nd),
        "take_profit": round(entry + d * tp_dist, nd),
        "sl_distance": round(sl_dist, nd),
        "tp_distance": round(tp_dist, nd),
    }


def _margin_check(plan: Dict[str, Dict[str, Any]]) -> None:
    """Add required margin per order and a free-margin verdict. Needs MT5; silent if absent."""
    try:
        from src.data.mt5_bridge import mt5, initialize_mt5, shutdown_mt5
    except Exception:
        return
    if mt5 is None or not initialize_mt5():
        return
    try:
        acct = mt5.account_info()
        free = float(acct.margin_free) if acct else None
        running = 0.0
        for ticker, row in plan.items():
            if not row.get("feasible"):
                continue
            action = mt5.ORDER_TYPE_BUY if row["direction"] == "LONG" else mt5.ORDER_TYPE_SELL
            margin = mt5.order_calc_margin(action, row["mt5_symbol"], row["lots"], row["levels"]["entry"])
            if margin is None:
                row["margin_required"] = None
                continue
            running += margin
            row["margin_required"] = round(float(margin), 2)
            if free is not None and running > free:
                row["feasible"] = False
                row["reason"] = (f"insufficient free margin: need ${running:,.2f} "
                                 f"cumulative, free ${free:,.2f}")
        for row in plan.values():
            row["free_margin"] = free
    finally:
        shutdown_mt5()


def build_order_plan(
    risk_manager: Any,
    mt5_data: Dict[str, Dict[str, Any]],
    check_margin: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """One entry per ticker in mt5_data: what MT5 could place, or why it cannot."""
    plan: Dict[str, Dict[str, Any]] = {}

    for ticker, d in (mt5_data or {}).items():
        pos = risk_manager.positions.get(ticker)
        if not d.get("tradable") or not d.get("mt5_symbol"):
            plan[ticker] = {"feasible": False, "reason": "not tradable on MT5"}
            continue
        if pos is None:
            plan[ticker] = {"feasible": False,
                            "reason": "no RAATS position opened (risk manager did not approve)"}
            continue

        sized = to_mt5_lots(pos.size, d.get("contract_size"), d.get("volume_min"), d.get("volume_step"))
        row: Dict[str, Any] = {
            "mt5_symbol": d["mt5_symbol"],
            "direction": "LONG" if pos.direction == 1 else "SHORT",
            "units": pos.size,
            **sized,
        }
        if d.get("bid") and d.get("ask"):
            row["levels"] = broker_levels(pos, d["bid"], d["ask"], d.get("digits"))
        else:
            row["feasible"] = False
            row["reason"] = "no live bid/ask"
        plan[ticker] = row

    if check_margin and any(r.get("feasible") for r in plan.values()):
        _margin_check(plan)
    return plan


def format_order_plan(plan: Dict[str, Dict[str, Any]]) -> str:
    lines = ["MT5 ORDER PLAN"]
    for t, r in plan.items():
        if r.get("feasible"):
            lv = r["levels"]
            m = f" margin ${r['margin_required']:,.2f}" if r.get("margin_required") is not None else ""
            lines.append(f"  {t} -> {r['mt5_symbol']} {r['direction']} {r['lots']} lots @ {lv['entry']} "
                         f"SL {lv['stop_loss']} TP {lv['take_profit']}{m}")
        else:
            lines.append(f"  {t}: NOT PLACEABLE - {r['reason']}")
    return "\n".join(lines)
