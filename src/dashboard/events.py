"""Read the bot's monthly session files (data/summaries/sessions_YYYY-MM.jsonl) into dashboard rows.

Everything here is read-only: the dashboard never writes to the bot's files.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]          # repo root (the folder that holds src/ and data/)
BROKER_NAME = os.environ.get("RAATS_BROKER_NAME", "FBS")
STALE_OPEN_DAYS = int(os.environ.get("RAATS_DASH_STALE_OPEN_DAYS", "3"))


def _dir() -> Path:
    d = Path(os.environ.get("RAATS_MEMORY_DIR", "data/summaries"))
    return d if d.is_absolute() else ROOT / d


def _file_for(when: date) -> Path:
    pattern = os.environ.get("RAATS_SESSION_FILE_PATTERN", "sessions_{year}-{month}.jsonl")
    return _dir() / pattern.format(year=f"{when.year:04d}", month=f"{when.month:02d}")


def load_events(since: date, until: date) -> List[Dict[str, Any]]:
    """Events dated since..until (inclusive), oldest first. Bad lines are skipped."""
    files, cur = [], date(since.year, since.month, 1)
    while cur <= until:
        files.append(_file_for(cur))
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    out: List[Dict[str, Any]] = []
    for path in files:
        if not path.exists():
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                day = str(rec.get("time", ""))[:10]
                if since.isoformat() <= day <= until.isoformat():
                    out.append(rec)
    return out


def _dt(text: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_trades(events: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(open_now, closed) rows. A close is matched to its open by ticket."""
    opened: Dict[str, Dict[str, Any]] = {}
    closed: List[Dict[str, Any]] = []
    for r in events:
        kind = r.get("type")
        if kind == "position_opened":
            opened[str(r.get("ticket"))] = r
        elif kind == "position_closed":
            o = opened.pop(str(r.get("ticket")), None)
            direction = r.get("direction") or (o or {}).get("direction")
            entry, exit_, sl0 = _num(r.get("entry")), _num(r.get("exit")), _num((o or {}).get("sl") or r.get("final_sl"))
            sign = 1 if direction == "LONG" else -1
            risk = abs(entry - sl0) if entry is not None and sl0 is not None else None
            rr = sign * (exit_ - entry) / risk if entry is not None and exit_ is not None and risk else None
            closed.append({
                "ticker": r.get("ticker"), "side": direction, "entry": entry, "exit": exit_,
                "pnl": _num(r.get("pnl")), "r": rr, "reason": r.get("reason"),
                "time": r.get("time"), "opened": (o or {}).get("opened"),
                "max_rr_seen": r.get("max_rr_seen"),
            })
    cutoff = datetime.now() - timedelta(days=STALE_OPEN_DAYS)
    open_rows = []
    for o in opened.values():
        when = _dt(o.get("opened") or o.get("time"))
        if when is not None and when < cutoff:
            continue                       # opened long ago and never closed in the log: not shown as open
        open_rows.append({"ticket": o.get("ticket"), "symbol": o.get("ticker"), "side": o.get("direction"),
                          "volume": _num(o.get("lots")), "entry": _num(o.get("entry")), "current": None,
                          "sl": _num(o.get("sl")), "tp": _num(o.get("tp")), "swap": None, "commission": None,
                          "profit": None, "pnl": None, "pct": None, "opened": o.get("opened")})
    return open_rows, closed


def build_waiting(events: Iterable[Dict[str, Any]], day: date) -> List[Dict[str, Any]]:
    """Tickers that are waiting: market closed (deferred) or an approval request not answered yet."""
    waiting: Dict[str, Dict[str, Any]] = {}
    for r in events:
        if not str(r.get("time", "")).startswith(day.isoformat()):
            continue
        t, tk = r.get("type"), r.get("ticker")
        if t in ("market_not_open", "candidate_deferred") and tk:
            reason = "Waiting for market open" if t == "market_not_open" else "Deferred until the market opens"
            waiting[tk] = {"ticker": tk, "reason": reason, "since": str(r["time"])[11:16]}
        elif t == "trade_approval_requested" and tk:
            waiting[tk] = {"ticker": tk, "reason": "Awaiting Discord approval", "since": str(r["time"])[11:16]}
        elif t in ("position_opened", "candidate_dropped", "trade_rejected") and tk:
            waiting.pop(tk, None)
    return list(waiting.values())


def _blocked_reason(rec: Dict[str, Any]) -> Tuple[str, str]:
    """(label, kind). kind: rejected | failed | noreply | dailyloss | system"""
    kind = rec.get("type")
    if kind == "trade_rejected":
        decision = str(rec.get("decision", "")).strip()
        up = decision.upper()
        if up == "REJECT":
            return "Rejected in Discord approval", "rejected"
        if up.startswith("ERROR"):
            return "Approval failed", "failed"
        if any(k in up for k in ("TIMEOUT", "TIMED", "NO REPLY", "NO_REPLY", "EXPIRE")):
            return "No reply", "noreply"
        return decision.title() or "Rejected", "rejected"
    if kind == "candidate_dropped":
        reason = str(rec.get("reason", ""))
        low = reason.lower()
        if "daily loss limit reached" in low:
            return "Daily loss limit reached", "dailyloss"
        if "symbol not found" in low or "not tradable" in low or "symbol is unavailable" in low:
            return f"Not supported by {BROKER_NAME}", "system"
        return "Dropped: " + reason.replace("risk manager: ", "")[:60], "system"
    return "Blocked", "system"


def build_blocked(events: Iterable[Dict[str, Any]], day: date) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    rows: List[Dict[str, Any]] = []
    banner: Optional[str] = None
    for r in events:
        if not str(r.get("time", "")).startswith(day.isoformat()):
            continue
        t = r.get("type")
        if t in ("trade_rejected", "candidate_dropped") and r.get("ticker"):
            label, kind = _blocked_reason(r)
            rows.append({"ticker": r["ticker"], "reason": label, "kind": kind, "time": str(r["time"])[11:16]})
        elif t == "live_blocked":
            for tk in r.get("tickers") or []:
                rows.append({"ticker": tk, "reason": "Insufficient balance", "kind": "system",
                             "time": str(r["time"])[11:16]})
            banner = "Insufficient balance: the agent stopped opening trades"
        elif t == "daily_loss_limit_reached":
            banner = (f"Daily loss limit reached (net {r.get('net_pnl')}); no new positions today, "
                      f"open positions are kept")
    rows.reverse()
    return rows, banner
