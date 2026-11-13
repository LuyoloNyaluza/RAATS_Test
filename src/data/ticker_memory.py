"""
src/data/ticker_memory.py

Short-term ticker memory for RAATS: what happened to a ticker in the last days, so the Main Agent
does not propose again what you just rejected or what just lost money.

WHAT IT IS (phase 1)
--------------------
An append-only event log (data/memory/ticker_events.jsonl) plus two ADVISORY rules:

  1. A trade you REJECTED on Discord is not proposed again for RAATS_MEMORY_REJECT_DAYS
     trading days (default 2).
  2. A position that CLOSED AT A LOSS is not reopened for RAATS_MEMORY_LOSS_COOLDOWN_DAYS
     trading days (default 2).

  3. A ticker the BROKER does not offer (not found on MT5 at trade time) is not proposed again
     for RAATS_MEMORY_UNTRADABLE_DAYS calendar days (default 30). Discovery already skips tickers
     missing from the broker's symbol list (broker_symbols.py); this is the second guardrail for
     whatever still slips through. The record carries the broker SERVER, so it only applies to
     the broker it was noted for: switching to another broker lifts it. Recorded only when the terminal was reachable, so an MT5
     outage is never remembered as "not offered".

Also recorded, not acted on (so the history exists when it is needed later):
  * "seen"            a trade for the ticker was actually PROPOSED to you (it passed the balance
                      gate). Tickers blocked for insufficient funds never ran and leave no trace.
  * "batch_rejected"  the ticker was in a batch you rejected (a batch is all-or-nothing, so this
                      says nothing about the ticker itself and never blocks it)

WHAT IT IS NOT
--------------
* It never approves, skips analysis, or overrides the balance gate, the macro block, the risk
  checks or the human approval. A candidate you already approved is never blocked by it.
* A timeout or an error on Discord is NOT a rejection and is never recorded as one.
* Analysis is always re-run on fresh data; memory only decides whether to PROPOSE a ticker.
* It does not learn win rates or scores; a small account makes too few trades for that.

LOOK-AHEAD SAFETY
-----------------
check()/times_seen() accept as_of: only events up to that moment are used, so a historical
simulation never sees the future. Live use passes nothing (= now).

FAILURE SAFETY
--------------
Memory must never break trading: every file error is swallowed and logged, and a failing check()
returns None (= no objection).

Settings (environment)
----------------------
RAATS_TICKER_MEMORY               1 = on (default), 0 = off
RAATS_TICKER_MEMORY_FILE          default data/memory/ticker_events.jsonl
RAATS_MEMORY_REJECT_DAYS          trading days a rejected trade blocks the ticker      (2)
RAATS_MEMORY_LOSS_COOLDOWN_DAYS   trading days after a losing close                    (2)
RAATS_MEMORY_UNTRADABLE_DAYS      calendar days a ticker the broker does not offer is skipped (30)
RAATS_MEMORY_KEEP_DAYS            events older than this many calendar days are ignored (14)
"""

import json
import logging
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger("raats.data.ticker_memory")

DEFAULT_FILE = "data/memory/ticker_events.jsonl"

TRADE_REJECTED = "trade_rejected"
BATCH_REJECTED = "batch_rejected"
CLOSED = "closed"
SEEN = "seen"
NOT_TRADABLE = "not_tradable"


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _enabled_from_env() -> bool:
    return os.environ.get("RAATS_TICKER_MEMORY", "1").strip().lower() not in ("0", "false", "no", "off")


def trading_days_elapsed(start: date, end: date) -> int:
    """Weekdays after `start` up to and including `end` (0 on the same day, 1 the next weekday).

    Holidays are not known here; a market holiday counts as a trading day, which only makes the
    cooldown end slightly early."""
    if end <= start:
        return 0
    days, cur = 0, start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def _to_datetime(value: Union[None, str, date, datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 23, 59, 59)
    try:
        text = str(value).replace("Z", "")
        parsed = datetime.fromisoformat(text)
        if len(text) <= 10:                       # a bare date means the whole day
            parsed = parsed.replace(hour=23, minute=59, second=59)
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


class TickerMemory:
    """Append-only ticker event log with the cooldown rules described above."""

    def __init__(
        self,
        path: Optional[str] = None,
        enabled: Optional[bool] = None,
        reject_days: Optional[int] = None,
        loss_days: Optional[int] = None,
        keep_days: Optional[int] = None,
        untradable_days: Optional[int] = None,
        now_fn: Callable[[], datetime] = datetime.now,
        server_fn: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.enabled = _enabled_from_env() if enabled is None else enabled
        self.path = Path(path or os.environ.get("RAATS_TICKER_MEMORY_FILE", DEFAULT_FILE))
        self.reject_days = reject_days if reject_days is not None else _env_int("RAATS_MEMORY_REJECT_DAYS", 2)
        self.loss_days = loss_days if loss_days is not None else _env_int("RAATS_MEMORY_LOSS_COOLDOWN_DAYS", 2)
        self.keep_days = keep_days if keep_days is not None else _env_int("RAATS_MEMORY_KEEP_DAYS", 14)
        self.untradable_days = (untradable_days if untradable_days is not None
                                else _env_int("RAATS_MEMORY_UNTRADABLE_DAYS", 30))
        self._now = now_fn
        self._server_fn = server_fn
        self._lock = threading.RLock()
        self._events: List[Dict[str, Any]] = []
        if self.enabled:
            self._load()

    def current_server(self) -> Optional[str]:
        """The broker server in use (None when unknown); used to scope not_tradable records."""
        try:
            if self._server_fn is not None:
                return self._server_fn()
            try:
                from src.data.broker_symbols import current_server
            except ImportError:
                from broker_symbols import current_server          # type: ignore
            return current_server()
        except Exception:
            return None

    # ------------------------------------------------------------------ storage
    def _load(self) -> None:
        try:
            if not self.path.exists():
                return
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue                  # a damaged line never stops the rest
                    if isinstance(ev, dict) and ev.get("ticker") and ev.get("kind") and ev.get("ts"):
                        self._events.append(ev)
        except OSError as exc:
            logger.warning("ticker memory could not be read (%s): %s", self.path, exc)

    def record(self, kind: str, ticker: str, ts: Optional[datetime] = None, **info: Any) -> None:
        """Append one event. Never raises."""
        if not self.enabled or not ticker:
            return
        try:
            moment = (ts or self._now()).replace(tzinfo=None)
            ev: Dict[str, Any] = {"ts": moment.isoformat(timespec="seconds"),
                                  "ticker": str(ticker).upper().strip(), "kind": kind}
            ev.update({k: v for k, v in info.items() if v is not None})
            with self._lock:
                self._events.append(ev)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev, default=str) + "\n")
        except Exception as exc:                  # memory must never break trading
            logger.warning("ticker memory could not record %s %s: %s", kind, ticker, exc)

    def _recent(self, ticker: str, as_of: Optional[datetime]) -> List[Dict[str, Any]]:
        cutoff = as_of or self._now().replace(tzinfo=None)
        oldest = cutoff - timedelta(days=max(self.keep_days, self.untradable_days))
        t = str(ticker).upper().strip()
        out = []
        with self._lock:
            for ev in self._events:
                if ev.get("ticker") != t:
                    continue
                when = _to_datetime(ev.get("ts"))
                if when is None or when > cutoff or when < oldest:   # nothing from the future
                    continue
                out.append(ev)
        return out

    # ------------------------------------------------------------------ rules
    def check(self, ticker: str, as_of: Union[None, str, date, datetime] = None) -> Optional[str]:
        """Why this ticker should NOT be proposed now, or None. Advisory; never raises."""
        if not self.enabled:
            return None
        try:
            moment = _to_datetime(as_of) if as_of is not None else self._now().replace(tzinfo=None)
            today = moment.date() if moment else self._now().date()
            for ev in reversed(self._recent(ticker, moment)):          # newest first
                when = _to_datetime(ev["ts"])
                if when is None:
                    continue
                elapsed = trading_days_elapsed(when.date(), today)
                kind = ev.get("kind")
                if kind == NOT_TRADABLE:
                    ev_server, here = ev.get("server"), self.current_server()
                    if ev_server and here and ev_server != here:
                        continue                  # noted for another broker: does not apply here
                    days = ev.get("days")
                    limit = days if isinstance(days, (int, float)) else self.untradable_days
                    if (today - when.date()).days < limit:
                        why = ev.get("reason") or "not offered by the broker"
                        return (f"not tradable on the broker ({why}), noted {when:%Y-%m-%d}; "
                                f"not proposed for {int(limit)} days")
                    continue
                if kind == TRADE_REJECTED and elapsed < self.reject_days:
                    return (f"you rejected this trade on {when:%Y-%m-%d} "
                            f"(not proposed again for {self.reject_days} trading days)")
                if kind == CLOSED and elapsed < self.loss_days:
                    pnl = ev.get("pnl")
                    if isinstance(pnl, (int, float)) and pnl < 0:
                        why = ev.get("reason") or "loss"
                        return (f"closed at a loss on {when:%Y-%m-%d} ({why}, {pnl:+.2f}); "
                                f"cooldown {self.loss_days} trading days")
            return None
        except Exception as exc:
            logger.warning("ticker memory check failed for %s: %s", ticker, exc)
            return None

    def times_seen(self, ticker: str, days: int = 7,
                   as_of: Union[None, str, date, datetime] = None) -> int:
        """How many times the ticker entered FinalInvestPool in the last `days` calendar days."""
        if not self.enabled:
            return 0
        try:
            moment = (_to_datetime(as_of) if as_of is not None else None)
            if moment is None:
                moment = self._now().replace(tzinfo=None)
            floor = moment - timedelta(days=days)
            return sum(1 for ev in self._recent(ticker, moment)
                       if ev.get("kind") == SEEN and (_to_datetime(ev["ts"]) or floor) >= floor)
        except Exception:
            return 0

    def snapshot(self, ticker: str, as_of: Union[None, str, date, datetime] = None) -> Dict[str, Any]:
        """Everything remembered about a ticker (for later use as analyst context)."""
        moment = _to_datetime(as_of) if as_of is not None else None
        return {
            "ticker": str(ticker).upper().strip(),
            "blocked_reason": self.check(ticker, as_of),
            "seen_7d": self.times_seen(ticker, 7, as_of),
            "events": self._recent(ticker, moment),
        }