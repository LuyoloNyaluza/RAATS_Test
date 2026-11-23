"""Matplotlib charts for the dashboard, drawn in the dashboard's dark style.

Each function takes closed-trade rows (see events.build_trades) and returns PNG bytes, or None when
there is nothing to draw (the page then shows "No data available for selected date").
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.dates import date2num  # noqa: E402

BG, PANEL, GRID, INK, MUTED = "#111A24", "#111A24", "#223246", "#E6EDF3", "#9AA7B5"
GREEN, RED, BLUE = "#3FB950", "#FF6B66", "#4C9AFF"
# Market sessions in UTC hours [start, end). Edit here; overlaps are not counted twice (first match wins).
SESSIONS = [("Asia", 0, 7), ("Europe", 7, 13), ("US", 13, 21)]

KINDS = ("balance", "daily", "drawdown", "hist", "session", "hour")
WINDOW_DAYS = {"balance": 1, "drawdown": 1, "hist": 1, "daily": 14, "session": 30, "hour": 30}


def _fig(w: float = 6.4, h: float = 4.2):
    fig, ax = plt.subplots(figsize=(w, h), dpi=110)
    fig.patch.set_facecolor(BG)
    _style(ax)
    return fig, ax


def _style(ax) -> None:
    ax.set_facecolor(PANEL)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.title.set_color(INK)


def _png(fig) -> bytes:
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def _dt(text: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


def _utc_hour(text: Any) -> Optional[int]:
    d = _dt(text)
    return d.astimezone(timezone.utc).hour if d else None      # naive timestamps are the PC's local time


def _session_of(hour: int) -> str:
    for name, a, b in SESSIONS:
        if a <= hour < b:
            return name
    return "Off-hours"


def _of_day(rows: List[Dict[str, Any]], day: date) -> List[Dict[str, Any]]:
    return sorted((r for r in rows if str(r.get("time", "")).startswith(day.isoformat()) and r.get("pnl") is not None),
                  key=lambda r: r["time"])


def balance_curve(rows, day: date, start_balance: Optional[float]) -> Optional[bytes]:
    day_rows = _of_day(rows, day)
    if not day_rows:
        return None
    base = start_balance if start_balance is not None else 0.0
    xs: List[datetime] = []
    start = _dt(day_rows[0].get("opened") or day_rows[0]["time"])
    if start is not None:
        xs.append(start)
    ys, total = [base], base
    for r in day_rows:
        timestamp = _dt(r["time"])
        if timestamp is None:
            continue
        xs.append(timestamp)
        total += r["pnl"]
        ys.append(total)
    if len(xs) < 2:
        return None
    xnums = date2num(xs)
    fig, ax = _fig()
    ax.step(xnums, ys, where="post", color=GREEN, linewidth=2)
    ax.fill_between(xnums, ys, base, step="post", color=GREEN, alpha=0.15)
    ax.axhline(base, color=MUTED, linewidth=0.8, linestyle="--")
    ax.set_title(f"{'Balance' if start_balance is not None else 'Day P/L'} - {day:%d %b %Y}")
    ax.set_ylabel("$")
    fig.autofmt_xdate()
    return _png(fig)


def drawdown(rows, day: date, start_balance: Optional[float]) -> Optional[bytes]:
    day_rows = _of_day(rows, day)
    if not day_rows:
        return None
    base = start_balance if start_balance else None
    total, peak, xs, ys = 0.0, 0.0, [], []
    for r in day_rows:
        total += r["pnl"]
        peak = max(peak, total)
        dd = total - peak
        xs.append(_dt(r["time"]))
        ys.append(dd / (base + peak) * 100 if base else dd)
    fig, ax = _fig()
    ax.fill_between(xs, ys, 0, step="post", color=RED, alpha=0.25)
    ax.step(xs, ys, where="post", color=RED, linewidth=2)
    ax.set_title(f"Drawdown from the day's peak - {day:%d %b %Y}")
    ax.set_ylabel("%" if base else "$")
    fig.autofmt_xdate()
    return _png(fig)


def daily_pnl(rows, day: date, start_balance: Optional[float] = None) -> Optional[bytes]:
    days = [day - timedelta(days=i) for i in range(WINDOW_DAYS["daily"] - 1, -1, -1)]
    pnl = {d: 0.0 for d in days}
    cnt = {d: 0 for d in days}
    for r in rows:
        d = _dt(r.get("time"))
        if d and d.date() in pnl and r.get("pnl") is not None:
            pnl[d.date()] += r["pnl"]
            cnt[d.date()] += 1
    if not any(cnt.values()):
        return None
    fig, ax = _fig()
    labels = [f"{d:%d %b}" for d in days]
    vals = [pnl[d] for d in days]
    ax.bar(labels, vals, color=[GREEN if v >= 0 else RED for v in vals])
    for i, d in enumerate(days):
        if cnt[d]:
            ax.annotate(f"n={cnt[d]}", (i, vals[i]), ha="center", va="bottom" if vals[i] >= 0 else "top",
                        color=MUTED, fontsize=8)
    ax.set_title("Daily P/L (last 14 days, n = trades)")
    ax.set_ylabel("$")
    plt.setp(ax.get_xticklabels(), rotation=60, ha="right")
    return _png(fig)


def r_histogram(rows, day: date, start_balance: Optional[float] = None) -> Optional[bytes]:
    rs = [r["r"] for r in _of_day(rows, day) if r.get("r") is not None]
    if not rs:
        return None
    lo, hi = min(-1.5, min(rs)), max(3.5, max(rs))
    edges = [lo + 0.5 * i for i in range(int((hi - lo) / 0.5) + 2)]
    counts = [0] * (len(edges) - 1)
    for v in rs:
        counts[min(int((v - lo) / 0.5), len(counts) - 1)] += 1
    fig, ax = _fig()
    ax.bar([e + 0.25 for e in edges[:-1]], counts, width=0.45,
           color=[GREEN if e + 0.25 >= 0 else RED for e in edges[:-1]])
    ax.set_title(f"Trade results in R - {day:%d %b %Y}")
    ax.set_xlabel("R (multiple of the initial risk)")
    ax.set_ylabel("Trades")
    return _png(fig)


def _by_window(rows, day: date, days: int):
    start = day - timedelta(days=days - 1)
    picked = []
    for r in rows:
        timestamp = _dt(r.get("time"))
        if r.get("r") is not None and timestamp is not None and start <= timestamp.date() <= day:
            picked.append(r)
    return picked


def by_session(rows, day: date, start_balance: Optional[float] = None) -> Optional[bytes]:
    picked = _by_window(rows, day, WINDOW_DAYS["session"])
    groups: Dict[str, List[float]] = {}
    for r in picked:
        h = _utc_hour(r.get("opened") or r["time"])
        if h is not None:
            groups.setdefault(_session_of(h), []).append(r["r"])
    if not groups:
        return None
    names = [n for n in [s[0] for s in SESSIONS] + ["Off-hours"] if n in groups]
    avg = [sum(groups[n]) / len(groups[n]) for n in names]
    win = [100 * sum(v > 0 for v in groups[n]) / len(groups[n]) for n in names]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 4.0), dpi=110)
    fig.patch.set_facecolor(BG)
    for ax in (a1, a2):
        _style(ax)
    labels = [f"{n}\n(n={len(groups[n])})" for n in names]
    a1.bar(labels, avg, color=[GREEN if v >= 0 else RED for v in avg])
    a1.set_title("Average R")
    a2.bar(labels, win, color=[GREEN if v >= 50 else RED for v in win])
    a2.set_ylim(0, 100)
    a2.set_title("Win rate (%)")
    fig.suptitle("By session (UTC, last 30 days)", color=INK, fontsize=10)
    return _png(fig)


def by_hour(rows, day: date, start_balance: Optional[float] = None) -> Optional[bytes]:
    picked = _by_window(rows, day, WINDOW_DAYS["hour"])
    hours: Dict[int, List[float]] = {}
    for r in picked:
        h = _utc_hour(r.get("opened") or r["time"])
        if h is not None:
            hours.setdefault(h, []).append(r["r"])
    if not hours:
        return None
    xs = sorted(hours)
    avg = [sum(hours[h]) / len(hours[h]) for h in xs]
    fig, ax = _fig(7.0, 4.0)
    ax.bar([f"{h:02d}" for h in xs], avg, color=[GREEN if v >= 0 else RED for v in avg])
    for i, h in enumerate(xs):
        ax.annotate(f"n={len(hours[h])}", (i, avg[i]), ha="center", va="bottom" if avg[i] >= 0 else "top",
                    color=MUTED, fontsize=8)
    ax.set_title("Average R by UTC hour (last 30 days, n = trades)")
    ax.set_xlabel("UTC hour")
    ax.set_ylabel("Average R")
    return _png(fig)


RENDER = {"balance": balance_curve, "drawdown": drawdown, "daily": daily_pnl,
          "hist": r_histogram, "session": by_session, "hour": by_hour}


def render(kind: str, rows, day: date, start_balance: Optional[float] = None) -> Optional[bytes]:
    return RENDER[kind](rows, day, start_balance)
