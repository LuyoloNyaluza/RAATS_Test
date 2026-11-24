"""RAATS dashboard server. Localhost only; it reads the bot's session files and starts/stops the agent."""
from __future__ import annotations

import asyncio
import json
import math
import os
import threading
import time
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from . import events, graphs
from .agent_runner import RUNNER
from .excel_export import build_workbook

STATIC = Path(__file__).parent / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
NO_DATA = "No data available for selected date. Please choose a different date."

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def localhost_only(request: Request, call_next):
    """The page can start a trading agent, so refuse other hosts (DNS rebinding) and cross-site POSTs."""
    host = request.headers.get("host", "").rsplit(":", 1)[0]
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"error": "forbidden host"}, status_code=403)
    origin = request.headers.get("origin")
    if request.method == "POST" and origin and origin.split("://", 1)[-1].rsplit(":", 1)[0] not in ALLOWED_HOSTS:
        return JSONResponse({"error": "forbidden origin"}, status_code=403)
    return await call_next(request)


def _day(text: Optional[str]) -> Date:
    try:
        return Date.fromisoformat(text) if text else Date.today()
    except ValueError:
        return Date.today()


# ---------------------------------------------------------------- MT5 cache
# Every MT5 call runs in ONE background thread; the web endpoints only read the cache. Before, each
# request called MT5 itself (the whole deal history every 10 s, positions every 2 s, from many
# threads at once), so one slow call stacked up the others and the page hung and went "offline".
MT5_ON = os.environ.get("RAATS_DASH_MT5", "1") != "0"
INCLUDE_FLOATING = os.environ.get("RAATS_DASH_INCLUDE_FLOATING", "1") != "0"
STALE_SEC = 20.0


class _Mt5Cache:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.d: Dict[str, Any] = {}          # name -> (time, value)
        self.started = False

    def get(self, name: str, max_age: float = STALE_SEC) -> Any:
        with self.lock:
            at, val = self.d.get(name, (0.0, None))
        return val if time.time() - at <= max_age else None

    def _put(self, name: str, val: Any) -> None:
        if val is not None:                  # keep the last good value on a failed read
            with self.lock:
                self.d[name] = (time.time(), val)

    def _loop(self) -> None:
        from src.data import mt5_orders
        last_realized = last_total = 0.0
        while True:
            try:
                if mt5_orders.live_enabled():
                    self._put("positions", mt5_orders.positions_detail())
                    self._put("account", mt5_orders.account_snapshot())
                    if time.time() - last_realized > 10:
                        last_realized = time.time()
                        self._put("realized", mt5_orders.realized_pnl_today())
                    if time.time() - last_total > 60:
                        last_total = time.time()
                        self._put("total", mt5_orders.overall_profit())
            except Exception:
                pass
            time.sleep(2.0)

    def start(self) -> None:
        if self.started or not MT5_ON:
            return
        self.started = True
        threading.Thread(target=self._loop, name="raats-dash-mt5", daemon=True).start()


MT5 = _Mt5Cache()


@app.on_event("startup")
def _startup() -> None:
    MT5.start()


def _clean(o: Any) -> Any:
    """NaN / inf are not valid JSON: one bad number used to turn a whole response into a 500."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


# ---------------------------------------------------------------- account (balance / return)
def _account(day_closed_pnl: float) -> Dict[str, Any]:
    """Balance, return and profit from the MT5 cache.

    MT5's balance only changes when a position CLOSES, so Bal / Ret / Profit used to stand still while
    trades ran. By default they now include the floating P/L of open positions (Bal shows equity);
    RAATS_DASH_INCLUDE_FLOATING=0 restores the closed-only figures.
    Ret = (realised today + floating) / start-of-day balance."""
    val: Dict[str, Any] = {"balance": None, "start_balance": None, "return_pct": None,
                           "total_profit": None, "floating": None, "source": "log"}
    snap = MT5.get("account")
    if snap is None:
        return val
    bal, equity, floating = snap["balance"], snap["equity"], snap["floating"]
    realized = MT5.get("realized", 120.0)
    realized = day_closed_pnl if realized is None else realized
    start = bal - realized
    fl = floating if INCLUDE_FLOATING else 0.0
    total = MT5.get("total", 300.0)
    val.update(balance=round(equity if INCLUDE_FLOATING else bal, 2), start_balance=round(start, 2),
               return_pct=round((realized + fl) / start * 100, 2) if start else None,
               total_profit=round(total + fl, 2) if total is not None else None,
               floating=round(floating, 2), closed_balance=round(bal, 2), source="MT5")
    return val


# ---------------------------------------------------------------- data
def _panels(day: Date) -> Dict[str, Any]:
    evs = events.load_events(day - timedelta(days=events.STALE_OPEN_DAYS + 1), day)
    open_rows, closed_all = events.build_trades(evs)
    closed = [c for c in closed_all if str(c["time"]).startswith(day.isoformat())]
    blocked, banner = events.build_blocked(evs, day)
    return {"open": open_rows, "closed": closed, "waiting": events.build_waiting(evs, day),
            "blocked": blocked, "banner": banner}


def _open_rows(fallback):
    """Open positions as MT5 shows them (from the cache). Falls back to the log rows when MT5 cannot be read."""
    rows = MT5.get("positions")
    if rows is not None:
        return rows, "MT5"
    return fallback, "log"


@app.get("/api/positions")
def positions():
    rows, source = _open_rows(events.build_trades(events.load_events(
        Date.today() - timedelta(days=events.STALE_OPEN_DAYS + 1), Date.today()))[0])
    return _clean({"rows": rows, "source": source, "agent_running": RUNNER.running()})


@app.post("/api/position/close")
async def close_position(request: Request):
    """Ask the running agent to close one ticket. The agent owns the MT5 order authority, so this only
    writes a request file; the agent closes it on its next monitor pass."""
    try:
        ticket = int((await request.json()).get("ticket"))
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({"ok": False, "message": "Bad request."}, status_code=400)
    rows, source = _open_rows([])
    if source != "MT5" or ticket not in {r["ticket"] for r in rows}:
        return {"ok": False, "message": "That ticket is not an open RAATS position on MT5."}
    if not RUNNER.running():
        return {"ok": False, "message": "The agent is not running from this dashboard, so it cannot carry out "
                                        "the close. Start it here, or close the trade in MT5."}
    d = Path(os.environ.get("RAATS_CLOSE_REQUEST_DIR", "data/close_requests"))
    d = d if d.is_absolute() else events.ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{ticket}.json").write_text(json.dumps({"ticket": ticket, "requested": datetime.now().isoformat()}),
                                      encoding="utf-8")
    return {"ok": True, "message": f"Close requested for ticket {ticket}. The agent closes it on its next pass."}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def state(date: Optional[str] = None):
    day = _day(date)
    p = _panels(day)
    if day == Date.today():
        p["open"], _ = _open_rows(p["open"])
    pnl = sum(c["pnl"] for c in p["closed"] if c["pnl"] is not None)
    return _clean({**p, "agent": RUNNER.status(), "account": _account(pnl), "day": day.isoformat(),
                   "now": datetime.now().strftime("%b %d, %Y  %H:%M:%S")})


@app.get("/api/graph")
def graph(kind: str = "balance", date: Optional[str] = None):
    if kind not in graphs.KINDS:
        return JSONResponse({"ok": False, "message": "Unknown graph type."}, status_code=400)
    day = _day(date)
    span = graphs.WINDOW_DAYS[kind]
    evs = events.load_events(day - timedelta(days=span + 4), day)
    _, closed = events.build_trades(evs)
    start = _account(0.0).get("start_balance") if day == Date.today() else None
    png = graphs.render(kind, closed, day, start)
    if png is None:
        return {"ok": False, "message": NO_DATA}
    return Response(content=png, media_type="image/png")


@app.get("/api/excel")
def excel(date: Optional[str] = None):
    """One workbook with four sheets. Open and waiting are as of now; closed and blocked are for the date."""
    day = _day(date)
    now = datetime.now()
    data = _panels(day)
    if day == Date.today():
        data["open"], _ = _open_rows(data["open"])
    blob = build_workbook(data, now)
    name = f"RAATS_{day.isoformat()}_{now:%H%M%S}.xlsx"
    out = events.ROOT / "data" / "exports"
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(blob)                      # keep a copy next to the bot's data
    except OSError:
        pass
    return Response(content=blob, headers={"Content-Disposition": f'attachment; filename="{name}"'},
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------- agent + console
@app.post("/api/agent/start")
def agent_start():
    return RUNNER.start()


@app.post("/api/agent/stop")
def agent_stop():
    return RUNNER.stop()


@app.get("/api/console")
async def console(request: Request):
    try:
        last = int(request.headers.get("last-event-id", -1))
    except ValueError:
        last = -1

    async def gen():
        nonlocal last
        while not await request.is_disconnected():
            for i, text in RUNNER.lines_after(last):
                last = i
                yield f"id: {i}\ndata: {text.replace(chr(13), '')}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
