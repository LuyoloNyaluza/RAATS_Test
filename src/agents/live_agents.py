"""
src/agents/live_agents.py

RAATS live agent - the ENTRY POINT (python -m src.agents.live_agents, or run_live()).

THE WHOLE PROCESS IS A BATCH
----------------------------
A batch is one run of the existing trading_loop_dynamic process, split into three sequential
THREAD-BASED subagents that hand their result to the next one through queues. That pipeline
(BatchPipeline, the queue dataclasses, BatchRunner and the discovery cursor) is the section
"THREADED BATCH PIPELINE" at the end of trading_loop_dynamic.py; everything above it in that
file is the original loop, unchanged.

    Subagent 1  discovery        first half of discovery.main()
    Subagent 2  news + scoring   second half of discovery.main()
    Subagent 3  analysis         DynamicTradingManager.run_trading_session() - RGR, run_daily_cycle,
                                 replacements, reserve, order plan, balance guard and the DISCORD
                                 APPROVAL of the batch

This module is the other side of that conversation (LiveSink): the main agent, the only holder of
the MT5 write authority, the persisted batch history and the Discord alerts.

  Batch 1   the first run of the day: top gainers 1-40 + commodities / currencies ranks 1-5
  Batch 2   discovery continues where batch 1 stopped: gainers 41-80 + ranks 6-10
  Batch 3+  the next unused gainers (the cursor is read from the persisted batch history)

At the end of a batch the result is sent for approval on Discord (inside Subagent 3). A batch with
no approved ticker says so on Discord. Approved tickers are handed to the MAIN AGENT, which opens
them one by one (balance check -> entry timer -> open) and monitors / adapts SL and TP. Batches
2, 3, ... run in the background; they pause only when 10 positions are open AND final INVEST holds
10. Blocked (insufficient funds) and rejected batches are never recovered: the next batch is
fresh, with the next batch number.
"""

import copy
import json
import math
import os
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from src.data import mt5_orders
from src.data.mt5_sizing import to_mt5_lots
from src.data.ticker_memory import (TickerMemory, TRADE_REJECTED, BATCH_REJECTED, CLOSED, SEEN,
                                    NOT_TRADABLE)
from src.utils.async_timer import wait_for_entry


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


MAX_POSITIONS = _env_int("RAATS_MAX_POSITIONS", 10)
MAX_FINAL_INVEST = 10                         # hard cap on the final INVEST list
POOL_TARGET = min(_env_int("RAATS_POOL_TARGET", 10), MAX_FINAL_INVEST)
BATCH_POOL_SIZE = _env_int("RAATS_BATCH_POOL", 50)
RESERVE_BELOW = 5                             # reserve supplement when fewer approved than this
MONITOR_SEC = _env_float("RAATS_MONITOR_SEC", 30.0)
CANDIDATE_TTL_MIN = _env_float("RAATS_CANDIDATE_TTL_MIN", 0.0)   # 0 = candidates are kept
EXHAUSTED_RETRY_SEC = _env_float("RAATS_EXHAUSTED_RETRY_SEC", 600.0)
TP_HEADROOM_RR = _env_float("RAATS_TP_HEADROOM_RR", 1.0)
# Ladder constants for adaptive management (matching test expectations)
STOP_R = 1.0
TP_R = 3.0
LADDER_START_R = 2.0
LADDER_STEP_R = 0.5
LOCK_GAP_R = 0.5
CEILING_GAP_R = 1.5
MAX_SPREAD_FRAC = _env_float("RAATS_MAX_SPREAD_FRAC_OF_RISK", 0.5)
# Small accounts: below this balance a trade sized under the broker's minimum lot is opened at
# the minimum lot (if the margin fits). The minimum lot can risk more than RAATS sized, so this
# is an explicit choice; set to 0 to restore "never round up".
SMALL_ACCOUNT_BALANCE = _env_float("RAATS_SMALL_ACCOUNT_BALANCE", 200.0)
# Small-account exception: when RAATS sized below the broker's minimum lot, trade the minimum lot
# anyway. This caps how many times larger than RAATS's own size that minimum lot may be
# (= how far past the 1% risk budget it goes). 0 = no cap (the previous behaviour).
MAX_MIN_LOT_OVERSIZE = _env_float("RAATS_MAX_MIN_LOT_OVERSIZE", 0.0)
# Share of the free margin that is never used (0 = use all of it; a stop-out needs headroom).
MARGIN_RESERVE_PCT = min(max(_env_float("RAATS_MARGIN_RESERVE_PCT", 0.0), 0.0), 0.9)
# A candidate that cannot be paid for yet is retried after this many seconds.
DEFER_RETRY_SEC = _env_float("RAATS_DEFER_RETRY_SEC", 60.0)
# Live does not run below this MT5 balance (this amount or more passes).
MIN_ACCOUNT_BALANCE = _env_float("RAATS_MIN_BALANCE", 20.0)
BALANCE_READ_RETRIES = int(_env_float("RAATS_BALANCE_READ_RETRIES", 3))      # MT5 balance reads
BALANCE_RETRY_SEC = _env_float("RAATS_BALANCE_RETRY_SEC", 2.0)
# After a restart, final INVEST candidates analysed longer ago than this are discarded, not
# restored: market conditions and the balance change, so old analysis is not reused.
# (0 = never restore a final INVEST list.) Blocked candidates are never restored at all.
RESTORE_MAX_AGE_MIN = _env_float("RAATS_RESTORE_MAX_AGE_MIN", 30.0)
# Second (per-trade) Discord approval -------------------------------------------------------
# How long fill_slots waits for the human before it goes back to monitoring positions (the
# request stays open; the next pass picks the answer up). 0.2 s is enough for an instant reply.
APPROVAL_JOIN_SEC = _env_float("RAATS_APPROVAL_JOIN_SEC", 0.2)
# A rejected trade: "skip" = do not execute it and take the next candidate (default);
# "retry" = keep it in final INVEST and propose it again after TRADE_REJECT_RETRY_SEC.
TRADE_REJECT_POLICY = os.environ.get("RAATS_TRADE_REJECT_POLICY", "skip").strip().lower()
TRADE_REJECT_RETRY_SEC = _env_float("RAATS_TRADE_REJECT_RETRY_SEC", 3600.0)
# After the approval the proposal is recalculated; it is sent for approval AGAIN when the entry
# moved by more than this many risk units, the size changed by more than 2 %, or the required
# margin rose by more than 10 %. At most MAX_REPROPOSALS times for one candidate.
REPROPOSE_DRIFT_R = _env_float("RAATS_REPROPOSE_DRIFT_R", 0.25)
MAX_REPROPOSALS = int(_env_float("RAATS_MAX_REPROPOSALS", 3))
STOP_FILE = os.environ.get("RAATS_STOP_FILE", "data/STOP")
STATE_FILE = os.environ.get("RAATS_STATE_FILE", "data/state/live_discovery.json")

# Ranks 6-10 (discovery.py uses ranks 1-5 of each).


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _log_error(ticker: str, error: Any, stage: str, context: Optional[dict] = None) -> None:
    try:
        from src.utils.logger import log_error
        log_error(ticker=ticker, date=datetime.now().strftime("%Y-%m-%d"),
                  error=str(error), stage=stage, context=context or {})
    except Exception:
        pass


# ======================================================================
# shared state
# ======================================================================
@dataclass
class Candidate:
    ticker: str
    result: Dict[str, Any] = field(default_factory=dict)
    news: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    direction: Optional[str] = None
    source: str = "subagent"
    batch: int = 0
    ready: bool = False        # its batch is complete (handed to the main agent)
    approved: bool = False     # approved for opening (Discord workflow, or not required)
    created: float = field(default_factory=time.time)
    retry_at: float = 0.0      # not affordable yet: do not try again before this time
    # the SECOND approval (one trade): "" none yet | "PENDING" | "APPROVE" | "REJECT" | "TIMEOUT" | ...
    approval: str = ""
    proposal: Dict[str, Any] = field(default_factory=dict)        # margin, lots, entry, SL, TP, RR
    approval_rounds: int = 0
    approval_thread: Any = field(default=None, repr=False, compare=False)


class FinalInvestPool:
    """The final INVEST list: filled by the subagents, drained ONLY by the main agent.

    Never holds more than 10 tickers, never a ticker that is already open or was closed today
    (`reject` is set by the main agent, which owns that knowledge).
    """

    def __init__(self, target: int = POOL_TARGET, reject: Optional[Callable[[str], bool]] = None):
        self.capacity = max(1, min(int(target), MAX_FINAL_INVEST))
        self.target = self.capacity
        self.reject = reject
        self._items: "OrderedDict[str, Candidate]" = OrderedDict()
        self._lock = threading.RLock()

    def put(self, cand: Candidate, front: bool = False) -> bool:
        """Add a candidate. False if refused (list full, or ticker already open / closed today)."""
        with self._lock:
            if self.reject is not None and self.reject(cand.ticker):
                return False
            if cand.ticker not in self._items and len(self._items) >= self.capacity:
                return False
            self._items[cand.ticker] = cand
            if front:
                self._items.move_to_end(cand.ticker, last=False)
            return True

    def take(self, accept: Optional[Callable[[Candidate], bool]] = None) -> Optional[Candidate]:
        """Highest-confidence candidate that `accept` allows (and remove it)."""
        with self._lock:
            ranked = sorted(self._items.values(), key=lambda c: -(c.confidence or 0.0))
            for cand in ranked:
                if accept is None or accept(cand):
                    del self._items[cand.ticker]
                    return cand
        return None

    def peek(self, accept: Optional[Callable[[Candidate], bool]] = None) -> Optional[Candidate]:
        """Like take() but the candidate STAYS in final INVEST (it leaves only when it is opened,
        rejected or dropped), so the list never holds more than 10 while a trade is approved."""
        with self._lock:
            ranked = sorted(self._items.values(), key=lambda c: -(c.confidence or 0.0))
            for cand in ranked:
                if accept is None or accept(cand):
                    return cand
        return None

    def reset_retry(self) -> None:
        """A position closed (margin freed): every waiting candidate may be tried at once."""
        with self._lock:
            for c in self._items.values():
                c.retry_at = 0.0

    def snapshot(self) -> List[Dict[str, Any]]:
        """What is needed to put the list back after a restart (not the analysis payload)."""
        with self._lock:
            return [{"ticker": c.ticker, "confidence": c.confidence, "direction": c.direction,
                     "source": c.source, "batch": c.batch, "ready": c.ready,
                     "approved": c.approved, "created": c.created} for c in self._items.values()]

    def restore(self, items: Optional[List[Dict[str, Any]]], max_age_sec: float = 0.0) -> int:
        """Put a saved list back. Candidates older than `max_age_sec` are discarded (their
        analysis is stale); 0 restores nothing."""
        restored = 0
        now = time.time()
        for it in items or []:
            try:
                created = float(it.get("created") or 0.0)
                if max_age_sec <= 0 or not created or now - created > max_age_sec:
                    continue                                   # stale: discard
                cand = Candidate(
                    ticker=str(it["ticker"]), confidence=float(it.get("confidence") or 0.0),
                    direction=it.get("direction"), source=str(it.get("source") or "restored"),
                    batch=int(it.get("batch") or 0), ready=bool(it.get("ready")),
                    approved=bool(it.get("approved")), created=created)
            except (KeyError, TypeError, ValueError):
                continue
            if self.put(cand):               # refused when already open / closed today / full
                restored += 1
        return restored

    def mark_ready(self, batch: int) -> List[str]:
        """Hand a completed batch over: returns the tickers of that batch not yet ready."""
        with self._lock:
            out = []
            for c in self._items.values():
                if c.batch == batch and not c.ready:
                    c.ready = True
                    out.append(c.ticker)
            return out

    def approve(self, tickers) -> None:
        with self._lock:
            for t in tickers:
                if t in self._items:
                    self._items[t].approved = True

    def drop(self, tickers) -> None:
        with self._lock:
            for t in tickers:
                self._items.pop(t, None)

    def remove(self, ticker: str) -> None:
        self.drop([ticker])

    def tickers(self) -> List[str]:
        with self._lock:
            return list(self._items)

    def get(self, ticker: str) -> Optional[Candidate]:
        with self._lock:
            return self._items.get(ticker)

    def free(self) -> int:
        with self._lock:
            return self.capacity - len(self._items)

    def full(self) -> bool:
        return self.free() <= 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


# ======================================================================
# BATCH STATUSES, THE BATCH LEDGER AND THE STARTUP DECISION
# ======================================================================
BATCH_PROCESSING = "BATCH_PROCESSING"          # the batch is being processed
READY = "READY"                                # eligible candidates are ready for handover
WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"  # Discord approval is required
INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"      # MT5 balance below the minimum: batch blocked
BALANCE_UNAVAILABLE = "BALANCE_UNAVAILABLE"    # MT5 balance could not be verified
REJECTED = "REJECTED"                          # the approval request was rejected
HANDED_OVER = "HANDED_OVER"                    # approved candidates were handed to the main agent
BATCH_COMPLETED = "BATCH_COMPLETED"            # the batch finished its lifecycle
ABANDONED = "ABANDONED"                        # a restart found it unfinished and unrecoverable

ACTIVE_STATUSES = {BATCH_PROCESSING, READY, WAITING_FOR_APPROVAL, BALANCE_UNAVAILABLE}
FINISHED_STATUSES = {HANDED_OVER, BATCH_COMPLETED}
DEAD_STATUSES = {INSUFFICIENT_FUNDS, REJECTED, ABANDONED}      # never recovered, never recycled


class BatchLedger:
    """Persistent batch history in the monthly session file (data/summaries/sessions_YYYY-MM.jsonl,
    the file the end-of-day summary already uses). Every batch has a number and a unique id and
    a status; the status of a batch is read from its own `batch_status` records (by batch number
    and time), never from the last physical line of the file."""

    def __init__(self, directory: Optional[str] = None):
        self.directory = Path(directory or os.environ.get("RAATS_MEMORY_DIR", "data/summaries"))
        self._lock = threading.Lock()
        self._seq = 0

    def path(self, when: Optional[datetime] = None) -> Path:
        when = when or datetime.now()
        pattern = os.environ.get("RAATS_SESSION_FILE_PATTERN", "sessions_{year}-{month}.jsonl")
        return self.directory / pattern.format(year=f"{when.year:04d}", month=f"{when.month:02d}")

    @staticmethod
    def batch_id(batch_no: int, when: Optional[datetime] = None) -> str:
        when = when or datetime.now()
        return f"batch{int(batch_no)}_{when.year:04d}_{when.month:02d}_{when.day:02d}"

    def append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Add one event line (batch statuses, approvals, positions opened / closed, ...)."""
        with self._lock:
            self._seq += 1
            record = {"time": _now(), "seq": self._seq, **record}
            try:
                path = self.path()
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, default=str) + "\n")
            except OSError as exc:
                print(f"[ledger] could not write {self.path()}: {exc}")
        return record

    def status(self, batch_no: int, status: str, **info: Any) -> Dict[str, Any]:
        return self.append({"type": "batch_status", "batch_no": int(batch_no),
                            "batch_id": self.batch_id(batch_no), "status": status, **info})

    def batches(self) -> Dict[int, Dict[str, Any]]:
        """{batch_no: {batch_no, batch_id, status, history}} from TODAY's records: the batch
        counter restarts at 1 every day (ids look like batch1_2026_11_08)."""
        out: Dict[int, Dict[str, Any]] = {}
        today = datetime.now().strftime("%Y-%m-%d")
        path = self.path()
        if not path.exists():
            return out
        rows: List[Tuple[str, int, Dict[str, Any]]] = []
        try:
            with open(path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if (isinstance(rec, dict) and rec.get("type") == "batch_status"
                            and "batch_no" in rec and str(rec.get("time", "")).startswith(today)):
                        rows.append((str(rec.get("time", "")), i, rec))
        except OSError:
            return out
        for _t, _i, rec in sorted(rows, key=lambda r: (r[0], r[1])):    # by time, then file order
            n = int(rec["batch_no"])
            b = out.setdefault(n, {"batch_no": n, "batch_id": rec.get("batch_id"), "history": []})
            b["status"] = rec.get("status")
            b["history"].append(rec.get("status"))
            b["initial"] = bool(b.get("initial") or rec.get("initial"))   # made by the 3-thread pipeline
        return out

    def latest(self) -> Optional[Dict[str, Any]]:
        batches = self.batches()
        return batches[max(batches)] if batches else None

    def _today_universes(self) -> List[List[str]]:
        """The universe (tickers) of each of today's batches, from their persisted records."""
        out: Dict[int, List[str]] = {}
        path = self.path()
        today = datetime.now().strftime("%Y-%m-%d")
        if not path.exists():
            return []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if (isinstance(rec, dict) and rec.get("type") == "batch_status"
                            and rec.get("universe") and str(rec.get("time", "")).startswith(today)):
                        out[int(rec["batch_no"])] = [str(t).upper() for t in rec["universe"]]
        except OSError:
            return []
        return [out[n] for n in sorted(out)]

    def used_today(self) -> List[str]:
        """Every ticker today's batches already used: the discovery cursor. The next batch starts
        with the first gainer NOT in this list (batch 2 = 41-80, and so on)."""
        used: List[str] = []
        for universe in self._today_universes():
            used.extend(t for t in universe if t not in used)
        return used

    def day_index(self) -> int:
        """How many batches discovered tickers today (0 = the first one of the day)."""
        return len(self._today_universes())

    def next_batch_no(self) -> int:
        latest = self.latest()
        return (latest["batch_no"] + 1) if latest else 1


def decide_startup(ledger: BatchLedger) -> Dict[str, Any]:
    """The next batch number and what happened to the previous one (cases A-E).

    A  no previous batch                    -> batch 1
    B  previous batch still processing      -> its threads died with the process: ABANDONED, next number
    C  previous batch finished              -> not regenerated; the next number
    D  previous batch blocked (funds)       -> its tickers are never retrieved; fresh next number
    E  previous batch rejected              -> never asked again; fresh next number
    """
    latest = ledger.latest()
    batch_no = ledger.next_batch_no()
    if latest is None:
        return {"case": "A", "batch_no": batch_no, "abandon": None}
    status = latest["status"]
    if status in ACTIVE_STATUSES:
        return {"case": "B", "batch_no": batch_no, "abandon": latest["batch_no"]}
    if status in FINISHED_STATUSES:
        return {"case": "C", "batch_no": batch_no, "abandon": None}
    return {"case": "D" if status == INSUFFICIENT_FUNDS else "E", "batch_no": batch_no,
            "abandon": None}


def report_insufficient_funds(balance: Optional[float], tickers: List[str],
                              alert: Callable[[str], Any] = print) -> None:
    """The insufficient-funds report: console, ONE Discord message ("ACCOUNT BALANCE
    INSUFFICIENT", blocked tickers named) + the weekly log, and the end-of-day blocked record.

    balance None = the MT5 balance could not be read (terminal not accessible): the same message
    is sent, with the balance shown as unavailable. Nothing else goes to Discord."""
    known = balance is not None
    shortfall = max(MIN_ACCOUNT_BALANCE - balance, 0.01) if known else MIN_ACCOUNT_BALANCE
    print("\n" + "=" * 60)
    print("LIVE NOT STARTED - INSUFFICIENT FUNDS")
    print("=" * 60)
    print(f"Account balance:   {f'${balance:,.2f}' if known else 'unavailable (MT5 not accessible)'}")
    print(f"Minimum required:  ${MIN_ACCOUNT_BALANCE:,.2f}")
    if known:
        print(f"Short by:          ${shortfall:,.2f}")
    print(f"Blocked tickers:   {', '.join(tickers) if tickers else 'none'}")
    try:        # the Discord message (blocked tickers named) + data/approvals/insufficient_funds_<week>.jsonl
        from src.data.mt5_bridge import notify_insufficient_balance
        notify_insufficient_balance(balance, MIN_ACCOUNT_BALANCE, list(tickers))
    except Exception as exc:
        print(f"  Discord / insufficient-funds log failed: {exc}")
    try:        # end-of-day record, as the first session did
        from src.agents.middleware.summarization_middleware import SummarizationMiddleware
        SummarizationMiddleware(starting_balance=balance).record_blocked_session(
            balance=balance, min_balance=MIN_ACCOUNT_BALANCE,
            shortfall=shortfall if known else None, tickers=list(tickers))
    except Exception as exc:
        print(f"  WARNING: blocked-session record failed ({exc})")


class MainAgent:
    """Opens positions, manages SL/TP on MT5, closes, reports and owns the open count.

    Only this object holds the MT5 write token (mt5_orders.grant_authority), so no other
    component can open, close or modify a position. Everything it does to positions runs under
    one lock from one loop, so two threads can never open the same ticker or push the count
    past 10.
    """

    def __init__(
        self,
        manager: Any,
        pool: FinalInvestPool,
        notifier: Any = None,
        event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
        market_data_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
        max_positions: int = MAX_POSITIONS,
        monitor_sec: float = MONITOR_SEC,
        use_mt5: Optional[bool] = None,
        memory: Optional[TickerMemory] = None,
    ):
        self.manager = manager
        # short-term ticker memory (advisory): what you rejected / what just lost money
        self.memory = memory if memory is not None else TickerMemory()
        self.rm = manager.risk_manager
        self.pool = pool
        self.notifier = notifier
        self._sink = event_sink
        self._market_data_fn = market_data_fn
        self.max_positions = max_positions
        self.monitor_sec = monitor_sec
        self.live = mt5_orders.live_enabled()
        self.use_mt5 = bool(getattr(manager, "enable_mt5", False)) if use_mt5 is None else use_mt5
        self.open: Dict[str, Dict[str, Any]] = {}
        self.closed_today = set(getattr(manager, "closed_positions_today", []))
        self.events: List[Dict[str, Any]] = []
        self._alert_times: Dict[str, float] = {}
        self._macro = None
        self._middleware = None
        self._stop = threading.Event()
        self._token = object()
        self._lock = threading.RLock()
        self.on_state_change: Callable[[], None] = lambda: None
        self.blocked = False                             # insufficient funds: live does not run
        self.balance_gate_passed = False                 # the initial balance check (first approved batch)
        self._gate_unavailable = False
        self._active: Optional[str] = None               # the candidate whose trade approval is open
        self.on_blocked: Callable[[Dict[str, Any]], None] = lambda info: None
        self.expect_first_open = False                   # the first batch was handed over, being opened
        self.first_open_done = threading.Event()         # ... and is opened as far as it can be
        mt5_orders.grant_authority(self._token)
        pool.reject = self._pool_rejects
        manager.open_live_positions = MappingProxyType(self.open)    # read-only for everyone else

    def _pool_rejects(self, ticker: str) -> bool:
        return ticker in self.open or ticker in self.closed_today or ticker in self.rm.positions

    def open_count(self) -> int:
        """The authoritative number of open positions."""
        return len(self.open)

    def release_authority(self) -> None:
        mt5_orders.release_authority(self._token)

    # ---------------------------------------------------------- reporting
    def _alert(self, message: str, key: Optional[str] = None, cooldown: float = 1800.0) -> None:
        if key is not None:
            last = self._alert_times.get(key, 0.0)
            if time.time() - last < cooldown:
                return
            self._alert_times[key] = time.time()
        print(f"\n[main] {message}")
        try:
            self._get_notifier().send_alert(message)
        except Exception as exc:
            print(f"  (Discord not sent: {exc})")

    def _get_notifier(self) -> Any:
        if self.notifier is None:
            from src.notifications.discord_notifier import DiscordNotifier
            self.notifier = DiscordNotifier()
        return self.notifier

    def _start_balance(self) -> Optional[float]:
        """Balance for the summary object, read without shutting MT5 down under other threads."""
        value = getattr(self.manager, "starting_balance", None)
        if value is None and self.use_mt5:
            value = mt5_orders.account_balance()
        return value

    def _event(self, record: Dict[str, Any]) -> None:
        record = {"time": _now(), **record}
        self.events.append(record)
        try:
            if self._sink is not None:
                self._sink(record)
                return
            if self._middleware is None:
                from src.agents.middleware.summarization_middleware import SummarizationMiddleware
                self._middleware = SummarizationMiddleware(
                    enable_discord=False, starting_balance=self._start_balance())
            self._middleware._save_jsonl(record)
        except Exception as exc:
            print(f"  (event not saved: {exc})")

    def _log_cycle(self, rec: Dict[str, Any], pnl: float = 0.0, price: Optional[float] = None,
                   event: str = "opened", reason: Optional[str] = None, side: Optional[str] = None) -> None:
        """One weekly-log row per open / close, so INVEST is logged as a trade:
        BUY/SELL, price, SL, TP, size, lots, ticket and MT5 symbol."""
        try:
            from src.utils.logger import log_cycle
            if side is None:
                side = "BUY" if rec["direction"] == "LONG" else "SELL"
            log_cycle(
                ticker=rec["ticker"], signal="INVEST",
                executed_price=price if price is not None else rec["entry"],
                latencies={}, pnl=pnl, direction=rec["direction"],
                stop_loss=rec["sl"], take_profit=rec["tp"], position_size=rec["units"],
                event=event, executed=True, risk_reason=reason,
                ticket=rec.get("ticket"), lots=rec.get("lots"), mt5_symbol=rec.get("mt5_symbol"),
                side=side,
            )
        except Exception as exc:
            print(f"  (cycle log failed: {exc})")

    # ---------------------------------------------------------- data helpers
    def _market_data(self, ticker: str) -> Dict[str, Any]:
        if self._market_data_fn is not None:
            return self._market_data_fn(ticker)
        from src.agents.collector import collect_market_data
        return collect_market_data(ticker)

    def _macro_checker(self) -> Any:
        """The calendar checker, created once. On first use the calendar is verified and a
        missing / expired calendar is reported (it would otherwise switch the block OFF silently)."""
        if self._macro is None:
            from src.data.macro_events import MacroEventChecker
            self._macro = MacroEventChecker()
            st = self._macro.status()
            print(f"[macro] calendar: {st['count']} events, {st['upcoming']} upcoming, "
                  f"next: {st.get('next')}; {st['unconfirmed_upcoming']} upcoming date(s) unconfirmed")
            if not st["ok"]:
                self._alert(f"Macro calendar problem: {st['reason']}. Entries are NOT protected "
                            f"from macro events until it is fixed.", key="macro_calendar",
                            cooldown=6 * 3600)
        return self._macro

    def _macro_block(self, ticker: Optional[str] = None) -> Optional[Any]:
        """The active macro-event window that applies to `ticker`, else None.

        Windows run `window_minutes` BEFORE and AFTER each event. Global events (Fed, ECB, US CPI
        / NFP) block every ticker; the rest (BoE, BoC, China data) block only assets that trade
        in the currencies they move. A failing check is reported, never silent."""
        try:
            from src.data.macro_events import asset_currencies
            cur = asset_currencies(ticker) if ticker else None
            return self._macro_checker().is_event_window_active(min_impact="MEDIUM", currencies=cur)
        except Exception as exc:
            self._alert(f"Macro-event check FAILED ({exc}). Entries are NOT protected from macro "
                        f"events until it works.", key="macro_error", cooldown=3600)
            return None

    def _portfolio_value(self) -> float:
        if self.use_mt5:
            # the REAL MT5 balance, never the simulated 10,000 (a balance of 0 is 0)
            return float(mt5_orders.account_balance() or 0.0)
        return float(getattr(self.manager, "portfolio_value", 10_000))

    def _price_for_exit(self, rec: Dict[str, Any]) -> Optional[float]:
        if rec.get("mt5_symbol"):
            snap = mt5_orders.snapshot(rec["mt5_symbol"])
            if snap:
                return mt5_orders.exit_price(snap, rec["direction"])
        try:
            import yfinance as yf
            return float(yf.Ticker(rec["ticker"]).fast_info["last_price"])
        except Exception:
            return None

    # ---------------------------------------------------------- hand-over from Subagent 3
    def adopt_batch(self, batch_manager: Any, batch: int) -> List[str]:
        """Take the approved final INVEST tickers of a finished batch into the opening queue.

        The batch's analysis rounds opened PAPER positions in the batch's OWN RiskManager (a
        sandbox, separate from the live one, so a ticker already open at the broker is never
        touched by a later batch). Each ticker is opened for real, at the broker's price, by
        this agent only. Returns the tickers that fitted in final INVEST (never more than 10).
        """
        by_ticker = {r.get("ticker"): r for r in getattr(batch_manager, "daily_results", [])}
        entries = []
        for ticker in list(batch_manager.final_invest):
            result = by_ticker.get(ticker, {})
            entries.append((float(result.get("confidence") or 0.0), ticker, result))
        accepted: List[str] = []
        for confidence, ticker, result in sorted(entries, key=lambda e: e[0]):   # best ends first
            if getattr(batch_manager, "risk_manager", None) is self.rm:
                self.rm.positions.pop(ticker, None)
            kept = self.pool.put(Candidate(
                ticker=ticker, result=result,
                news=getattr(batch_manager, "news_by_ticker", {}).get(ticker, {}),
                confidence=confidence, direction=result.get("direction"),
                source=f"batch{batch}", batch=batch, ready=True, approved=True,
            ), front=True)
            if kept:
                accepted.append(ticker)    # NOT recorded in the memory yet: it has not run
        return accepted

    def sync_summary(self, batch_manager: Any) -> None:
        """Keep the end-of-day summary object in step with the latest batch."""
        for name in ("active_list", "waitlist", "hold_history", "replacement_history",
                     "rgr_rejected", "rgr_results", "mt5_data", "mt5_order_plan",
                     "news_by_ticker", "daily_results"):
            if hasattr(batch_manager, name):
                setattr(self.manager, name, getattr(batch_manager, name))
        self.manager.final_invest = [c for c in self.pool.tickers()]

    def _maybe_release_batches(self, opened: int) -> None:
        """After one opening pass that opened nothing, the first batch is as open as it can be."""
        if self.expect_first_open and not opened:
            self.expect_first_open = False
            print("[main] the first batch is opened as far as the balance allows; batches 2, 3, ... start")
            self.first_open_done.set()

    def _mt5_view(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        if not self.use_mt5:
            return out
        for t in tickers:
            sym = mt5_orders.resolve(t)
            snap = mt5_orders.snapshot(sym) if sym else None
            out[t] = {
                "mt5_symbol": sym, "tradable": bool(snap and snap["trade_mode"] == 4),
                "bid": snap["bid"] if snap else None, "ask": snap["ask"] if snap else None,
                "spread_pct": round((snap["ask"] - snap["bid"]) / ((snap["ask"] + snap["bid"]) / 2) * 100, 4)
                if snap and snap["ask"] and snap["bid"] else None,
            }
        return out

    def recover_open_positions(self) -> int:
        """After a restart: take over RAATS positions still open on MT5 (matched by magic)."""
        if not (self.use_mt5 and self.live):
            return 0
        broker = mt5_orders.list_positions() or {}
        recovered = 0
        for ticket, p in broker.items():
            comment = p.get("comment") or ""
            if not comment.startswith("RAATS "):
                continue
            ticker = comment.split(" ", 1)[1].strip()
            if ticker in self.open or ticker in self.rm.positions:
                continue
            try:
                md = self._market_data(ticker)
                m, m_norm = self.rm.resolve_gradient(md["closes"], md["atr"])
                snap = mt5_orders.snapshot(p["symbol"])
                units = p["volume"] * (snap["contract_size"] if snap else 1.0)
                d = 1 if p["direction"] == "LONG" else -1
                pos = self.rm.open_position(ticker, d, p["price_open"], units, md["atr"], m, m_norm)
                if p.get("sl"):
                    pos.stop_loss = p["sl"]
                if p.get("tp"):
                    pos.take_profit = p["tp"]
                self.open[ticker] = {
                    "ticker": ticker, "mt5_symbol": p["symbol"], "ticket": ticket,
                    "direction": p["direction"], "lots": p["volume"], "units": units,
                    "entry": p["price_open"], "sl": pos.stop_loss, "tp": pos.take_profit,
                    "opened": _now(), "recovered": True,
                }
                recovered += 1
            except Exception as exc:
                print(f"  could not recover {ticker}: {exc}")
        if recovered:
            self._alert(f"Recovered {recovered} open position(s) from MT5 after restart.")
        return recovered

    # ---------------------------------------------------------- take-profit ceiling
    def _tp_rr(self, max_rr: float) -> float:
        """Take profit is a CEILING that rides ahead of the best ratio seen.

        Profit is taken when the trailing stop is hit, not at a fixed 2R, so the ceiling
        starts beyond the trailing trigger and only ever moves outward, in step increments.
        """
        # Use the ladder ceiling: max_rr + CEILING_GAP_R
        return max_rr + CEILING_GAP_R

    def _tp_price(self, entry: float, d: int, risk_unit: float, max_rr: float) -> float:
        return entry + d * self._tp_rr(max_rr) * risk_unit

    # ---------------------------------------------------------- opening
    # ---------------------------------------------------------- the two-stage trade flow
    #
    #   Stage 1 (trading loop): the Discord BATCH approval admits candidates to FinalInvestPool.
    #   Stage 2 (here), for the first approved batch and then for EACH candidate:
    #       1  initial balance check (once): below the minimum -> BLOCKED, both modules stop
    #       2  calculate margin, lot size, entry, SL, TP, risk amount and risk-to-reward
    #       3  send them to Discord for a second, INDIVIDUAL approval
    #       4  only after APPROVE: start the asynchronous entry timer
    #       5  revalidate balance / free margin / price; recalculate, and ask again when the
    #          proposal changed materially
    #       6  submit the order to MT5, confirm and record it, take the next candidate
    #   Batch approval is not trade approval: nothing is sent to MT5 without the second one.
    def _forget(self, ticker: str) -> None:
        self.pool.remove(ticker)
        if self._active == ticker:
            self._active = None

    def _drop(self, ticker: str, reason: str) -> str:
        self._forget(ticker)
        self._event({"type": "candidate_dropped", "ticker": ticker, "reason": reason})
        self._alert(f"Not opened: {ticker} - {reason}")
        return "drop"

    def _skip_by_memory(self, cand: Candidate, reason: str) -> str:
        """The ticker memory objects (you rejected it / it just lost): not proposed now."""
        t = cand.ticker
        self._forget(t)
        self._event({"type": "candidate_skipped_memory", "ticker": t, "reason": reason})
        self._alert(f"Skipped by ticker memory: {t} - {reason}", key=f"memory:{t}", cooldown=6 * 3600)
        return "drop"

    def _defer(self, cand: Candidate, reason: str) -> str:
        """Cannot be paid for right now: it STAYS in final INVEST, the next candidate is tried, and
        this one is proposed again (new numbers, new approval) later."""
        cand.retry_at = time.time() + DEFER_RETRY_SEC
        cand.approval, cand.proposal = "", {}
        if self._active == cand.ticker:
            self._active = None
        self._event({"type": "candidate_deferred", "ticker": cand.ticker, "reason": reason})
        self._alert(f"Kept in final INVEST, not opened yet: {cand.ticker} - {reason}",
                    key=f"defer:{cand.ticker}", cooldown=1800)
        return "defer"

    def _free_margin(self) -> Optional[float]:
        """Free margin that may still be used for NEW positions (None if MT5 cannot be read).

        In a dry run nothing is reserved at the broker, so the margin of the positions opened
        by this agent is subtracted here; otherwise a dry run would 'afford' 10 positions.
        """
        free = mt5_orders.account_free_margin()
        if free is None:
            return None
        if not self.live:
            free -= sum(float(r.get("margin") or 0.0) for r in self.open.values())
        return max(0.0, free * (1.0 - MARGIN_RESERVE_PCT))

    # -- step 1: the initial balance gate (first approved batch only)
    def _initial_balance_gate(self) -> bool:
        """True: trading may go on. False: not now (balance unreadable) or BLOCKED for good.

        MT5 balance is the only source of truth (paper equity never substitutes for it). Below
        the minimum: the blocked tickers are reported on Discord, the shared global state is set
        (BLOCKED_INSUFFICIENT_BALANCE) and BOTH this agent and the trading loop stop. An approval
        never bypasses this check.
        """
        if self.balance_gate_passed or not self.use_mt5:
            return True
        approved = [c for c in (self.pool.get(t) for t in self.pool.tickers()) if c and c.approved]
        if not approved:
            return False                      # nothing has arrived yet
        balance = None
        for attempt in range(max(1, BALANCE_READ_RETRIES)):      # a short MT5 hiccup is not a block
            balance = mt5_orders.account_balance()
            if balance is not None:
                break
            if attempt + 1 < BALANCE_READ_RETRIES:
                time.sleep(BALANCE_RETRY_SEC)
        if balance is not None and balance >= MIN_ACCOUNT_BALANCE:
            self.balance_gate_passed = True
            self._gate_unavailable = False
            print(f"[main] balance ${balance:,.2f} >= ${MIN_ACCOUNT_BALANCE:,.2f}: trading may start")
            return True
        # below the minimum, OR the balance cannot be read (MT5 not accessible): an unverified
        # balance is never sufficient. Same message either way; on the first run it stops BOTH
        # this agent and the trading loop (batch discovery).
        if balance is None:
            self._event({"type": "balance_unavailable"})
        by_batch: Dict[int, List[str]] = {}
        for c in approved:
            by_batch.setdefault(c.batch, []).append(c.ticker)
        tickers = [c.ticker for c in approved]
        self.blocked = True
        self.pool.drop(tickers)               # blocked, never recovered or recycled
        report_insufficient_funds(balance, tickers, alert=self._alert)    # ONE Discord message
        info = {"reason": "BLOCKED_INSUFFICIENT_BALANCE", "balance": balance,
                "min_balance": MIN_ACCOUNT_BALANCE, "tickers": tickers, "by_batch": by_batch}
        self._event({"type": "live_blocked", **info})
        self.on_blocked(info)                 # ledger + the shared global state -> the loop stops
        self._stop.set()                      # the Main Agent stops
        return False

    # -- step 2: the proposal
    def _prepare(self, cand: Candidate) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Market data, direction, size, margin and levels at the CURRENT price. Returns
        ("ok", ctx) with the proposal, or ("drop" | "defer" | "halt", None)."""
        t = cand.ticker
        try:
            md = self._market_data(t)
            atr, closes = md["atr"], md["closes"]
            m, m_norm = self.rm.resolve_gradient(closes, atr)
        except Exception as exc:
            return self._drop(t, f"market data unavailable ({exc})"), None

        symbol, snap = None, None
        if self.use_mt5:
            symbol = mt5_orders.resolve(t)
            if not symbol:
                # Guardrail: a ticker the broker does not offer goes into the ticker memory, so it
                # is not discovered, analysed or proposed again. Only when the terminal ANSWERED:
                # an MT5 outage must never be remembered as "not offered".
                if mt5_orders.available():
                    self.memory.record(NOT_TRADABLE, t, reason="symbol not found on MT5",
                                       server=self.memory.current_server())
                    return self._drop(t, "not offered by the broker (noted in the ticker memory)"), None
                return self._drop(t, "not available on MT5 (terminal not reachable)"), None
            snap = mt5_orders.snapshot(symbol)
            if snap is None:
                return self._drop(t, "not available on MT5 (or no price)"), None
            if snap["trade_mode"] != 4:
                self.memory.record(NOT_TRADABLE, t, reason="MT5 trading not fully enabled", days=7,
                                   server=self.memory.current_server())
                return self._drop(t, "MT5 trading is not fully enabled for this symbol"), None

        price = (snap["bid"] + snap["ask"]) / 2 if snap else md["close"]
        # MT5 mode: the real balance, never a made-up number. `_portfolio_value()` turns an unreadable
        # balance into 0.0 (typed float), which the risk manager would REJECT and so drop a good
        # candidate on a momentary MT5 hiccup; here an unreadable balance defers instead.
        balance: Optional[float] = (mt5_orders.account_balance() if self.use_mt5
                                    else self._portfolio_value())
        if balance is None:                    # MT5 mode and the balance cannot be read
            return self._defer(cand, "the MT5 balance cannot be read; no proposal made"), None
        approved, units, d, reason = self.rm.validate_trade(
            ticker=t, signal="INVEST", current_price=price,
            portfolio_value=balance, atr=atr, m_norm=m_norm, is_top_five=False,
        )
        if not approved:
            return self._drop(t, f"risk manager: {reason}"), None
        direction = "LONG" if d == 1 else "SHORT"

        lots, traded_units, oversize = None, units, None
        if snap:
            sized = to_mt5_lots(units, snap["contract_size"], snap["volume_min"], snap["volume_step"])
            if sized["feasible"]:
                lots = min(sized["lots"], snap["volume_max"])
            elif "min_lot_units" in sized:
                # RAATS sized it below the broker's minimum lot
                if balance is not None and balance < SMALL_ACCOUNT_BALANCE:
                    oversize = sized.get("oversize_factor")
                    if MAX_MIN_LOT_OVERSIZE > 0 and oversize and oversize > MAX_MIN_LOT_OVERSIZE:
                        return self._drop(
                            t, f"the minimum lot is {oversize:.1f}x the size RAATS wanted "
                               f"(cap {MAX_MIN_LOT_OVERSIZE:g}x); skipped"), None
                    lots = snap["volume_min"]          # small account: the smallest trade there is
                else:
                    return self._defer(cand, sized["reason"]), None   # wait for the balance to grow
            else:
                return self._drop(t, sized["reason"]), None
            traded_units = lots * snap["contract_size"]

        risk_unit, _gf = self.rm.compute_risk_unit(atr, m_norm)
        ref = md["close"]
        if snap:
            ref = snap["ask"] if direction == "LONG" else snap["bid"]
        sl, tp = self.rm.compute_initial_levels(ref, d, risk_unit)
        # Initial TP uses rrr (3R), ceiling only applies during monitoring in _manage
        required_margin, free_margin = None, balance
        if snap:
            sl, tp = mt5_orders.clamp_levels(direction, sl, tp, snap)
            free_margin = self._free_margin()
            if symbol is not None and lots is not None:
                required_margin = mt5_orders.calc_margin(direction, symbol, lots, ref)
            if (required_margin is not None and free_margin is not None
                    and required_margin > free_margin):
                return self._defer(
                    cand, f"not enough free margin yet (need ${required_margin:,.2f}, "
                          f"free ${free_margin:,.2f})"), None
        else:
            required_margin = traded_units * ref                 # paper: no leverage

        if snap and symbol is not None and lots is not None:
            # Would the broker take this order RIGHT NOW? (order_check places nothing, so this is
            # the same test in a dry run as live.) A closed market is not proposed to you: you
            # would approve a trade that cannot be filled. It stays in the pool and is proposed
            # again when the market opens; the same check re-runs after the entry timer.
            chk = mt5_orders.check_order(symbol, direction, lots, sl, tp)
            if chk.get("not_trading_now"):
                self._event({"type": "market_not_open", "ticker": t, "symbol": symbol,
                             "reason": chk["reason"], "retcode": chk.get("retcode")})
                return self._defer(
                    cand, f"{symbol}: {chk['reason']} (broker: {chk.get('comment') or 'n/a'}); "
                          f"it is proposed again when the market opens"), None

        risk_per_unit = abs(ref - sl)
        risk_amount = risk_per_unit * traded_units
        reward_amount = abs(tp - ref) * traded_units
        rr = (abs(tp - ref) / risk_per_unit) if risk_per_unit else None
        proposal = {
            "ticker": t, "mt5_symbol": symbol, "side": "BUY" if d == 1 else "SELL",
            "direction": direction, "batch": cand.batch, "confidence": cand.confidence,
            "balance": balance, "free_margin": free_margin, "required_margin": required_margin,
            "oversize": oversize,
            "paper": not self.use_mt5, "dry_run": bool(self.use_mt5 and not self.live),
            "lots": lots, "units": traded_units, "entry": ref, "stop_loss": sl, "take_profit": tp,
            "risk_amount": risk_amount, "reward_amount": reward_amount,
            "risk_reward": f"1:{rr:.1f}" if rr else "n/a", "time": _now(),
        }
        ctx = {"md": md, "atr": atr, "m": m, "m_norm": m_norm, "symbol": symbol, "snap": snap,
               "direction": direction, "d": d, "lots": lots, "units": traded_units,
               "risk_unit": risk_unit, "ref": ref, "sl": sl, "tp": tp,
               "required_margin": required_margin, "proposal": proposal}
        return "ok", ctx

    # -- step 3: the second Discord approval (asynchronous, so monitoring never stops)
    def _approval_worker(self, cand: Candidate, proposal: Dict[str, Any]) -> None:
        try:
            notifier = self._get_notifier()
            request = notifier.send_trade_approval_request(proposal)
            response = str(notifier.wait_for_approval(request.request_id))
        except Exception as exc:                   # no answer is never an approval
            response = f"ERROR: {exc}"
        cand.approval = response                   # set LAST: it is what the main loop watches

    def _request_trade_approval(self, cand: Candidate, ctx: Dict[str, Any]) -> str:
        t = cand.ticker
        cand.proposal = ctx["proposal"]
        cand.approval = "PENDING"
        cand.approval_rounds += 1
        if cand.approval_rounds == 1:      # it ran: it passed the balance gate and is proposed to you.
            self.memory.record(SEEN, t, batch=cand.batch)   # (tickers blocked for funds never get here)
        self._active = t
        self._event({"type": "trade_approval_requested", "ticker": t, "round": cand.approval_rounds,
                     "proposal": cand.proposal})
        cand.approval_thread = threading.Thread(
            target=self._approval_worker, args=(cand, cand.proposal),
            name=f"raats-trade-approval-{t}", daemon=True)
        cand.approval_thread.start()
        cand.approval_thread.join(timeout=APPROVAL_JOIN_SEC)
        if cand.approval == "PENDING":
            return "pending"                       # the human has not answered: keep monitoring
        return self._advance(cand)                 # answered at once: carry on in this pass

    def _trade_not_approved(self, cand: Candidate, decision: str) -> str:
        t = cand.ticker
        self._event({"type": "trade_rejected", "ticker": t, "decision": decision,
                     "proposal": cand.proposal})
        self._alert(f"Trade not approved ({decision}): {t} will not be opened.")
        if decision == "REJECT" and TRADE_REJECT_POLICY != "retry":
            # a human decision; TIMEOUT / ERROR never count. With the "retry" policy you have
            # asked to be asked again later, so the memory must not veto that.
            self.memory.record(TRADE_REJECTED, t, batch=cand.batch,
                               entry=(cand.proposal or {}).get("entry"))
        if TRADE_REJECT_POLICY == "retry":
            cand.approval, cand.proposal = "", {}
            cand.retry_at = time.time() + TRADE_REJECT_RETRY_SEC
            if self._active == t:
                self._active = None
            return "defer"
        self._forget(t)                            # not executed: the next eligible candidate
        return "rejected"

    @staticmethod
    def _materially_changed(old: Dict[str, Any], new: Dict[str, Any], risk_unit: float) -> bool:
        """Did the proposal change enough while waiting that the human must see it again?"""
        if old.get("side") != new.get("side"):
            return True
        for key in ("lots", "units"):
            if old.get(key) and new.get(key) is not None \
                    and abs(new[key] - old[key]) > 0.02 * abs(old[key]):
                return True
        if risk_unit and abs(new["entry"] - old["entry"]) > REPROPOSE_DRIFT_R * risk_unit:
            return True
        o, n = old.get("required_margin"), new.get("required_margin")
        return bool(o and n is not None and n > o * 1.10)

    # -- steps 4-6: timer, revalidation, order
    def _execute_approved(self, cand: Candidate) -> str:
        t = cand.ticker
        approved_proposal = dict(cand.proposal)
        # 4. ONLY NOW does the asynchronous entry timer start (15-30 s, a real wait when live)
        delay = wait_for_entry(simulate=False)          # always a real 15-30 s wait before the order
        print(f"  {t}: approved; entry delay {delay.seconds:.1f}s "
              f"({'simulated' if delay.simulated else 'waited'})")
        # 5. revalidate trading conditions, balance, free margin and price. The wait can be long:
        #    a stop request, a macro window or a balance below the minimum must not be carried
        #    through on the strength of an approval given earlier.
        if self._stop.is_set() or self.should_stop():
            return "halt"
        event = self._macro_block(t)
        if event:
            self._alert(f"{t}: approved, but the {event.name} [{event.region}] window opened "
                        f"during the entry delay; waiting.", key=f"macro:{event.event_type}",
                        cooldown=900)
            return "halt"
        if self.use_mt5:
            balance_now = mt5_orders.account_balance()
            if balance_now is None:
                return self._defer(cand, "the MT5 balance cannot be verified; not executed")
            if balance_now < MIN_ACCOUNT_BALANCE:
                return self._defer(
                    cand, f"balance ${balance_now:,.2f} is below the ${MIN_ACCOUNT_BALANCE:,.2f} "
                          f"minimum; not executed")
        status, ctx = self._prepare(cand)
        if status != "ok" or ctx is None:
            return status                          # dropped / deferred / halted: nothing is sent
        if self._materially_changed(approved_proposal, ctx["proposal"], ctx["risk_unit"]):
            if cand.approval_rounds >= MAX_REPROPOSALS:
                return self._drop(t, "the proposal kept changing; not executed")
            self._event({"type": "trade_reproposed", "ticker": t, "old": approved_proposal,
                         "new": ctx["proposal"]})
            self._alert(f"{t}: the proposal changed while waiting (entry "
                        f"{approved_proposal['entry']} -> {ctx['proposal']['entry']}); "
                        f"sending it for approval again.")
            return self._request_trade_approval(cand, ctx)
        return self._submit(cand, ctx)

    def _submit(self, cand: Candidate, ctx: Dict[str, Any]) -> str:
        """6. submit the approved order to MT5 (or record the paper trade), confirm, record."""
        t = cand.ticker
        # Hard guard: the ONLY way to an MT5 order is an individual APPROVE. Batch approval
        # (entry to FinalInvestPool) never authorises execution.
        if cand.approval != "APPROVE":
            self._event({"type": "execution_refused", "ticker": t, "approval": cand.approval})
            return self._drop(t, f"no trade approval ({cand.approval or 'none'}); not executed")
        symbol, snap, lots = ctx["symbol"], ctx["snap"], ctx["lots"]
        direction, d, ref = ctx["direction"], ctx["d"], ctx["ref"]
        sl, tp, traded_units = ctx["sl"], ctx["tp"], ctx["units"]
        margin_needed = ctx["required_margin"]
        atr, m, m_norm = ctx["atr"], ctx["m"], ctx["m_norm"]

        ticket, fill = f"PAPER-{t}", ref
        if snap:
            if symbol is None:
                return self._drop(t, "MT5 symbol is unavailable")
            if lots is None:
                return self._drop(t, "MT5 lot size is unavailable")
            res = mt5_orders.place_market_order(symbol, direction, lots, sl, tp,
                                                comment=f"RAATS {t}", ref_price=ref,
                                                token=self._token)
            if not res["ok"]:
                return self._drop(t, f"order failed: {res['message']}")
            ticket, fill = res["ticket"], res["price"] or ref

        pos = self.rm.open_position(ticker=t, direction=d, entry_price=fill, size=traded_units,
                                    atr=atr, m=m, m_norm=m_norm)
        new_sl = pos.stop_loss
        new_tp = pos.take_profit  # Use RiskManager's TP (rrr-based)
        if snap:
            new_sl, new_tp = mt5_orders.clamp_levels(direction, new_sl, new_tp, snap)
            pos.stop_loss, pos.take_profit = new_sl, new_tp
            if symbol is not None and (new_sl, new_tp) != (sl, tp):  # fill price differed from the quote
                mt5_orders.modify_sltp(ticket, symbol, new_sl, new_tp, token=self._token)

        rec = {"ticker": t, "mt5_symbol": symbol, "ticket": ticket, "direction": direction,
               "lots": lots, "units": traded_units, "entry": fill, "sl": new_sl, "tp": new_tp,
               "opened": _now(), "confidence": cand.confidence, "source": cand.source,
               "batch": cand.batch, "dry_run": bool(self.use_mt5 and not self.live),
               "margin": margin_needed, "approval_rounds": cand.approval_rounds}
        self.open[t] = rec
        self._forget(t)
        if t in self.manager.final_invest:
            self.manager.final_invest.remove(t)

        mode = "LIVE" if (self.live and self.use_mt5) else ("DRY RUN" if self.use_mt5 else "PAPER")
        self._alert(
            f"[{mode}] OPENED {direction} {t}"
            + (f" ({symbol}, {lots} lots)" if symbol else "")
            + f" @ {fill} | SL {new_sl} | TP {new_tp} | confidence {cand.confidence:.2f}"
            f" | open {len(self.open)}/{self.max_positions}")
        self._event({"type": "position_opened", **rec})
        self._log_cycle(rec, event="opened")
        self.on_state_change()                       # final INVEST changed: keep the saved copy
        return "opened"

    # -- the state machine: one step for one candidate
    def _advance(self, cand: Candidate) -> str:
        """'opened' | 'drop' | 'defer' | 'halt' | 'pending' (waiting for the human) | 'rejected'"""
        t = cand.ticker
        if t in self.open or t in self.rm.positions:
            self._forget(t)
            return "drop"
        if len(self.open) >= self.max_positions:
            return "halt"
        event = self._macro_block(t)
        if event:
            self._alert(f"Opening paused: {event.name} [{event.region}] window active "
                        f"(entries blocked {event.window_minutes} min before and after).",
                        key=f"macro:{event.event_type}", cooldown=900)
            if getattr(event, "global_risk", True):
                return "halt"                       # moves every market: nothing opens
            cand.retry_at = time.time() + 60        # moves only its currencies: try the next ticker
            return "defer"
        if cand.approval == "PENDING":
            thread = cand.approval_thread
            if thread is not None and thread.is_alive():
                return "pending"
            if cand.approval == "PENDING":         # the worker ended without an answer
                cand.approval = "ERROR: no answer"
        if cand.approval == "":
            why = self.memory.check(t)             # advisory: only decides whether to PROPOSE
            if why:
                return self._skip_by_memory(cand, why)
            status, ctx = self._prepare(cand)      # steps 2 + 3
            if status != "ok" or ctx is None:
                return status
            return self._request_trade_approval(cand, ctx)
        if cand.approval == "APPROVE":
            return self._execute_approved(cand)    # steps 4 - 6
        return self._trade_not_approved(cand, cand.approval)

    def _try_open(self, cand: Candidate) -> str:
        with self._lock:
            return self._advance(cand)

    def _next_candidate(self, deferred: set) -> Optional[Candidate]:
        """One trade is proposed at a time: the candidate whose approval is open comes first."""
        if self._active:
            active = self.pool.get(self._active)
            if active is not None:
                return active
            self._active = None
        now = time.time()
        return self.pool.peek(
            lambda c: c.approved and c.ticker not in self.closed_today
            and c.ticker not in deferred and c.retry_at <= now)

    def fill_slots(self, limit: Optional[int] = None) -> int:
        """Take APPROVED candidates from final INVEST, one at a time, through the two-stage flow
        (balance gate -> proposal -> Discord trade approval -> timer -> revalidation -> MT5), as
        many as the account can pay for and never more than 10.

        A candidate that cannot be paid for yet stays in final INVEST (deferred, not dropped); a
        rejected trade is not executed and the next candidate is taken; a trade waiting for the
        human is left pending so position monitoring goes on. `limit` caps how many are opened.
        """
        if not self._initial_balance_gate():
            return 0
        opened = 0
        ttl = CANDIDATE_TTL_MIN * 60
        deferred: set = set()                    # tried and not affordable during THIS call
        for stale in [t for t in self.pool.tickers() if t in self.closed_today]:
            self.pool.remove(stale)
        while len(self.open) < self.max_positions and not self._stop.is_set():
            if limit is not None and opened >= limit:
                break
            cand = self._next_candidate(deferred)
            if cand is None:
                break
            if ttl > 0 and not cand.approval and time.time() - cand.created > ttl:
                self._event({"type": "candidate_expired", "ticker": cand.ticker})
                self._forget(cand.ticker)
                continue
            outcome = self._try_open(cand)
            if outcome == "opened":
                opened += 1
            elif outcome == "defer":
                deferred.add(cand.ticker)        # kept in final INVEST; try the next candidate
            elif outcome in ("halt", "pending"):
                break
        return opened

    # ---------------------------------------------------------- adaptive position management
    def _apply_levels(self, rec: Dict[str, Any], sl: float, tp: float, note: str) -> bool:
        if rec.get("mt5_symbol"):
            res = mt5_orders.modify_sltp(rec["ticket"], rec["mt5_symbol"], sl, tp, token=self._token)
            if not res["ok"]:
                self._alert(f"{rec['ticker']}: could not update SL/TP on MT5 ({res['message']})",
                            key=f"modfail:{rec['ticker']}", cooldown=600)
                return False
        old_sl, old_tp = rec["sl"], rec["tp"]
        rec["sl"], rec["tp"] = sl, tp
        self._alert(f"{rec['ticker']} {rec['direction']}: SL {old_sl} -> {sl}"
                    + (f", TP {old_tp} -> {tp}" if tp != old_tp else "") + f" ({note})")
        self._event({"type": "levels_updated", "ticker": rec["ticker"], "ticket": rec["ticket"],
                     "old_sl": old_sl, "new_sl": sl, "old_tp": old_tp, "new_tp": tp, "note": note})
        return True

    def _close_now(self, rec: Dict[str, Any], price: float, reason: str) -> None:
        res: Dict[str, Any] = {"ok": True, "price": price}
        if rec.get("mt5_symbol"):
            res = mt5_orders.close_position(rec["ticket"], rec["mt5_symbol"], rec["direction"],
                                            rec["lots"], ref_price=price, token=self._token)
        if res["ok"]:
            info = (mt5_orders.closed_deal_info(rec["ticket"]) or {}) if rec.get("mt5_symbol") else {}
            self._finish(rec, info.get("price") or res.get("price") or price, reason, info.get("profit"))
        else:
            self._alert(f"{rec['ticker']}: exit signal ({reason}) but close failed: {res['message']}",
                        key=f"closefail:{rec['ticker']}", cooldown=300)

    def _manage(self, rec: Dict[str, Any], bpos: Optional[Dict[str, Any]]) -> None:
        """One pass of adaptive management for one open position.

        Ladder logic (matching test expectations):
        - Ratio >= 2.0R: SL moves to entry + 1.5R
        - Ratio >= 2.5R: SL moves to entry + 2.0R
        - Every further 0.5R: SL moves up by 0.5R (step)
        - TP ceiling: always 1.5R above the current step
        - Stops only tighten, ceilings only rise
        """
        t = rec["ticker"]
        pos = self.rm.positions.get(t)
        if pos is None:
            self.open.pop(t, None)
            return
        d, direction = pos.direction, rec["direction"]

        # 1. the actual MT5 position and the current price
        snap = mt5_orders.snapshot(rec["mt5_symbol"]) if rec.get("mt5_symbol") else None
        price = mt5_orders.exit_price(snap, direction) if snap else self._price_for_exit(rec)
        if price is None:
            return
        actual_sl = bpos["sl"] if bpos else rec["sl"]
        actual_tp = bpos["tp"] if bpos else rec["tp"]
        if actual_sl and ((d == 1 and actual_sl > pos.stop_loss) or (d == -1 and actual_sl < pos.stop_loss)):
            pos.stop_loss = actual_sl            # a tighter stop already at the broker is never loosened

        # 2. profit ratio and trading conditions
        ratio = pos.current_rr(price)
        spread_ok = True
        if snap and pos.risk_unit:
            spread_ok = (snap["ask"] - snap["bid"]) <= MAX_SPREAD_FRAC * pos.risk_unit

        # 3. new levels: the stepping stop and the TP ceiling
        # Ladder: at 2.0R -> SL at 1.5R, at 2.5R -> SL at 2.0R, etc.
        if ratio >= LADDER_START_R:
            step = math.floor(ratio / LADDER_STEP_R + 1e-9) * LADDER_STEP_R
            # Lock gap: stop sits LOCK_GAP_R behind the step
            locked_rr = step - LOCK_GAP_R
            # Ceiling: CEILING_GAP_R ahead of the step
            ceiling_rr = step + CEILING_GAP_R
            
            new_sl = pos.entry_price + d * locked_rr * pos.risk_unit
            new_tp = pos.entry_price + d * ceiling_rr * pos.risk_unit
            
            # Only tighten stop, only raise ceiling
            if d == 1:
                if new_sl > pos.stop_loss:
                    pos.stop_loss = new_sl
                if new_tp > pos.take_profit:
                    pos.take_profit = new_tp
                pos.locked_rr = locked_rr
            else:
                if new_sl < pos.stop_loss:
                    pos.stop_loss = new_sl
                if new_tp < pos.take_profit:
                    pos.take_profit = new_tp
                pos.locked_rr = locked_rr

        # the stop may already be reached: that is the exit (profit taken at the stop)
        reason = self.rm.check_exit(t, price)
        if reason:
            self._close_now(rec, price, reason)
            return

        # 4. compare with the levels that are really on MT5
        tol = snap["point"] / 2 if snap else 1e-9
        sl, tp = pos.stop_loss, pos.take_profit
        if snap:
            sl, tp = mt5_orders.clamp_levels(direction, sl, tp, snap)

        # 5. validity: the stop only tightens, the ceiling only moves outward
        if actual_sl is not None and ((d == 1 and sl < actual_sl) or (d == -1 and sl > actual_sl)):
            sl = actual_sl
        if actual_tp is not None and ((d == 1 and tp < actual_tp) or (d == -1 and tp > actual_tp)):
            tp = actual_tp
        differs = (actual_sl is None or abs(sl - actual_sl) > tol
                   or actual_tp is None or abs(tp - actual_tp) > tol)
        if differs and spread_ok:
            locked = f", stop locked at {pos.locked_rr:.1f}R" if pos.locked_rr is not None else ""
            self._apply_levels(rec, sl, tp, f"ratio {ratio:.2f}R{locked}")
    
    def _finish(self, rec: Dict[str, Any], exit_px: Optional[float], reason: str,
                broker_profit: Optional[float] = None) -> None:
        """7. Record the closing result and notify Discord; the slot is refilled by the loop."""
        t = rec["ticker"]
        pos = self.rm.positions.get(t)
        if pos is not None and pos.locked_rr is not None and reason in ("stop_loss", "closed_at_broker"):
            reason = "take_profit_trailing_stop"        # the locked stop was hit: profit taken
        if exit_px is None:
            exit_px = rec["entry"]
        pnl = broker_profit
        if pos is not None:
            closed = self.rm.close_position(t, exit_px, reason=reason)
            if pnl is None:
                pnl = closed["pnl"]
        self.open.pop(t, None)
        self.pool.reset_retry()                     # margin freed: waiting candidates retry now
        self.closed_today.add(t)
        if t not in self.manager.closed_positions_today:
            self.manager.closed_positions_today.append(t)
        pnl = 0.0 if pnl is None else pnl
        self.memory.record(CLOSED, t, pnl=round(pnl, 2), reason=reason)
        icon = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"
        self._alert(f"[{icon}] CLOSED {rec['direction']} {t} @ {exit_px} ({reason}) | "
                    f"entry {rec['entry']} | PnL {pnl:+.2f} | open {len(self.open)}/{self.max_positions}")
        self._event({"type": "position_closed", "ticker": t, "ticket": rec["ticket"],
                     "direction": rec["direction"], "entry": rec["entry"], "exit": exit_px,
                     "reason": reason, "pnl": pnl, "final_sl": rec["sl"], "final_tp": rec["tp"]})
        side = "SELL" if rec["direction"] == "LONG" else "BUY"
        self._log_cycle(rec, pnl=pnl, price=exit_px, event="closed", reason=reason, side=side)

    def monitor_tick(self) -> None:
        with self._lock:
            broker = mt5_orders.list_positions() if self.use_mt5 else None
            for t, rec in list(self.open.items()):
                bpos = broker.get(rec["ticket"]) if broker is not None else None
                if self.use_mt5 and broker is not None and bpos is None:
                    # closed at the broker: stop loss / take profit hit, or closed by hand
                    info = mt5_orders.closed_deal_info(rec["ticket"]) or {}
                    self._finish(rec, info.get("price"), info.get("reason", "closed_at_broker"),
                                 info.get("profit"))
                    continue
                self._manage(rec, bpos)

    # ---------------------------------------------------------- loop
    def stop(self) -> None:
        self._stop.set()

    def should_stop(self) -> bool:
        return self._stop.is_set() or os.path.exists(STOP_FILE)

    def run(self) -> None:
        print(f"\n[main] live phase started: max {self.max_positions} positions, "
              f"monitor every {self.monitor_sec:.0f}s, "
              f"{'LIVE ORDERS' if (self.live and self.use_mt5) else 'dry run / paper'}; "
              f"create '{STOP_FILE}' to stop")
        while not self.should_stop():
            opened = 0
            try:
                self.monitor_tick()
                # one new position per pass: the entry delay is 15-30 s, and the open
                # positions are looked at again before the next one is opened
                opened = self.fill_slots(limit=1)
                self._maybe_release_batches(opened)
            except Exception as exc:
                _log_error("-", exc, "main_agent")
                print(f"[main] error: {exc}")
            if not opened:
                self._stop.wait(self.monitor_sec)

    def shutdown(self) -> None:
        """End-of-run summary. Positions stay open on MT5 with their current SL/TP."""
        if self.blocked:                  # insufficient funds: the blocked record is already written
            self.release_authority()
            return
        self._alert(f"Live phase stopped. Open positions kept on MT5: {sorted(self.open)}")
        self.release_authority()
        try:
            if self._middleware is None:
                from src.agents.middleware.summarization_middleware import SummarizationMiddleware
                self._middleware = SummarizationMiddleware(
                    enable_discord=_env_flag("RAATS_DISCORD_SUMMARY"),
                    starting_balance=self._start_balance())
            self._middleware.process_session_end(
                {"manager": self.manager, "results": self.manager.daily_results})
        except Exception as exc:
            print(f"[main] final summary failed: {exc}")


# ======================================================================
# entry point
# ======================================================================
# ======================================================================
# THE FINAL INVEST LIST ON DISK (fresh candidates only)
# ======================================================================
def save_pool_state(pool: FinalInvestPool, path: str = STATE_FILE) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"date": datetime.now().strftime("%Y-%m-%d"), "pool": pool.snapshot()}, f)
        os.replace(tmp, path)
    except OSError as exc:
        _log_error("-", exc, "save_pool_state")


def load_pool_state(pool: FinalInvestPool, path: str = STATE_FILE) -> int:
    """Put back today's final INVEST candidates that are still FRESH (analysis younger than
    RAATS_RESTORE_MAX_AGE_MIN). Older analysis is discarded, never reused."""
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return 0
    if st.get("date") != datetime.now().strftime("%Y-%m-%d"):
        return 0
    saved = st.get("pool", []) or []
    restored = pool.restore(saved, max_age_sec=RESTORE_MAX_AGE_MIN * 60.0)
    if saved:
        print(f"[live] final INVEST: {restored} restored, {len(saved) - restored} discarded (stale)")
    return restored


def discard_pool_state(path: str = STATE_FILE) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        _log_error("-", exc, "discard_pool_state")


# ======================================================================
# THE SINK: what trading_loop_dynamic.BatchRunner needs from live
# ======================================================================
class LiveSink:
    """The consumer of the batches: the main agent (the only trader), the persisted batch history
    and the Discord alerts. trading_loop_dynamic.BatchRunner calls these methods; it never
    touches MT5."""

    def __init__(self, main: "MainAgent", ledger: BatchLedger, use_mt5: bool):
        self.main, self.ledger, self.use_mt5 = main, ledger, use_mt5
        self.min_balance = MIN_ACCOUNT_BALANCE
        self.paused = False

    # -- state of the position engine
    def should_stop(self) -> bool:
        return self.main.should_stop()

    def open_count(self) -> int:
        return self.main.open_count()

    def has_room(self) -> bool:
        """Batches pause only when 10 positions are open AND final INVEST holds 10."""
        pool, main = self.main.pool, self.main
        if pool.full() and main.open_count() >= main.max_positions:
            if not self.paused:
                self.paused = True
                print("\n[batches] paused: open positions 10 and final INVEST 10")
                main._event({"type": "batches_paused"})
            return False
        if self.paused:
            self.paused = False
            print("\n[batches] resumed")
            main._event({"type": "batches_resumed"})
        return pool.free() > 0

    def first_batch_pending(self) -> bool:
        return self.main.expect_first_open

    # -- balance (the MT5 balance is the only source of truth)
    def read_balance(self) -> Optional[float]:
        return mt5_orders.account_balance()

    def report_insufficient(self, balance: float, tickers: List[str]) -> None:
        report_insufficient_funds(balance, tickers, alert=self.main._alert)

    def live_cannot_run(self) -> None:
        self.main.blocked = True
        discard_pool_state()
        self.main.stop()

    # -- the persisted batch history
    def next_batch_no(self) -> int:
        return self.ledger.next_batch_no()

    def used_today(self) -> List[str]:
        return self.ledger.used_today()

    def day_index(self) -> int:
        return self.ledger.day_index()

    def status(self, batch_no: int, status: str, **info: Any) -> None:
        print(f"[batches] batch {batch_no}: {status}")
        self.ledger.status(batch_no, status, **info)
        if status == REJECTED and str(info.get("response", "")).upper() in ("REJECT", "MODIFY"):
            for t in info.get("tickers") or []:          # information only: a batch is all-or-nothing
                self.main.memory.record(BATCH_REJECTED, t, batch=batch_no)

    def alert(self, message: str, key: Optional[str] = None, cooldown: float = 1800.0) -> None:
        self.main._alert(message, key=key, cooldown=cooldown)

    def memory_check(self, ticker: str) -> Optional[str]:
        """Ticker memory for the batch pipeline: asked BEFORE a ticker is scored or analysed."""
        return self.main.memory.check(ticker)

    def final_outcome(self, outcomes: List[Tuple[int, str]]) -> None:
        """The batch runner calls this once when the discovery sources are exhausted and it ends.
        Report what every batch of this run did; the position engine keeps running."""
        lines = [f"batch {n}: {outcome}" for n, outcome in outcomes]
        handed = sum(1 for _, o in outcomes if o == "handed")
        message = (
            "DISCOVERY SOURCES EXHAUSTED\n\n"
            "No more new broker-supported tickers were available, so no further batches will run "
            "this session. Open positions keep being monitored.\n\n"
            f"Batches this run: {len(outcomes)} ({handed} approved and handed over)\n"
            + "\n".join(lines)
        )
        print(f"\n[batches] {message}")
        try:
            self.main._event({"type": "batches_finished", "outcomes": [list(o) for o in outcomes]})
        except Exception:
            pass
        self.alert(message, key="final_outcome", cooldown=3600.0)

    # -- the hand-over to the main agent
    def handover(self, manager: Any, batch_no: int, tickers: List[str], first_batch: bool) -> List[str]:
        accepted = self.main.adopt_batch(manager, batch_no)
        self.main.sync_summary(manager)
        self.main.on_state_change()
        if first_batch and accepted:
            self.main.expect_first_open = True     # open it first, then batches 2, 3, ... start
        return accepted


# ======================================================================
# THE ENTRY POINT
# ======================================================================
def _keep_mt5_connected() -> None:
    """The batches run beside the main agent and call mt5_bridge helpers that shut MT5 down after
    every read (get_account_balance, enrich_final_invest). Once live trading runs, that would cut
    the terminal out from under an order. Initialising again is harmless; shutting down is not."""
    try:
        from src.data import mt5_bridge
        mt5_bridge.shutdown_mt5 = lambda: None
    except Exception:
        pass


def _apply_global_block(ledger: BatchLedger, main: "MainAgent", info: Dict[str, Any]) -> None:
    """The initial balance gate failed: ONE global block for both modules. The trading loop's
    GLOBAL_STATE is set (its batch runner stops discovering and any approval still to be sent is
    cancelled), every batch involved is recorded INSUFFICIENT_FUNDS and no candidate is kept for
    a later run."""
    try:
        from src.agents.trading_loop_dynamic import GLOBAL_STATE, BLOCKED_INSUFFICIENT_BALANCE
        GLOBAL_STATE.block(BLOCKED_INSUFFICIENT_BALANCE,
                           **{k: v for k, v in info.items() if k != "reason"})
    except Exception as exc:
        _log_error("-", exc, "global_block")
    for batch_no, tickers in (info.get("by_batch") or {}).items():
        ledger.status(batch_no, INSUFFICIENT_FUNDS, tickers=tickers, balance=info.get("balance"))
    discard_pool_state()
    main.stop()


def _prepare_live(manager: Any, notifier: Any, ledger: BatchLedger, use_mt5: bool,
                  handed: bool = False) -> Tuple["MainAgent", FinalInvestPool, Any]:
    """The main agent + the background batch runner around one manager (not started yet).

    handed  the manager already holds a finished, approved and balance-checked batch (the way
            trading_loop_dynamic's own main block ends): it is recorded as the next batch and
            handed to the main agent before batches 2, 3, ... start.
    """
    pool = FinalInvestPool()
    def _append_event(record: Dict[str, Any]) -> None:
        ledger.append(record)

    main = MainAgent(manager, pool, notifier=notifier, event_sink=_append_event, use_mt5=use_mt5)
    manager.starting_balance = main._start_balance()
    main.on_state_change = lambda: save_pool_state(pool)
    main.on_blocked = lambda info: _apply_global_block(ledger, main, info)
    main.recover_open_positions()
    restored = load_pool_state(pool)
    recovered = main.open_count()
    if handed:
        n = ledger.next_batch_no()
        tickers = list(manager.final_invest)
        ledger.status(n, BATCH_PROCESSING, initial=True,
                      universe=[str(t).upper() for t in getattr(manager, "ticker_universe", [])])
        ledger.status(n, READY, tickers=tickers)
        accepted = main.adopt_batch(manager, n)
        ledger.status(n, HANDED_OVER, tickers=accepted, approved=tickers)
        ledger.status(n, BATCH_COMPLETED, tickers=accepted)
        main.on_state_change()
        main.expect_first_open = bool(accepted)
        print(f"[live] batch {n} handed to the main agent: {accepted}")
    if use_mt5:
        _keep_mt5_connected()
    from src.agents.trading_loop_dynamic import BatchRunner      # the batch runner
    from src.agents.deep_batch import DeepBatchPipeline          # Deep Agents: main agent + 3 subagents
    runner = BatchRunner(LiveSink(main, ledger, use_mt5), use_mt5,
                         first_batch=not (recovered or restored),
                         pipeline_cls=DeepBatchPipeline)         # RAATS_DEEP_AGENTS=0 -> plain threads
    return main, pool, runner


def _serve(main: "MainAgent", runner: Any) -> None:
    runner.start()
    try:
        main.run()
    except KeyboardInterrupt:
        print("\n[live] interrupted.")
    finally:
        runner.stop()
        main.stop()
        runner.join(timeout=10)
        main.shutdown()


def run_live_phase(manager: Any, notifier: Any = None) -> None:
    """Compatibility for trading_loop_dynamic's own main block: the loop has produced, approved and
    balance-checked a batch; it is handed to the main agent and batches 2, 3, ... follow in the
    background. (run_live() does all of this itself, with the three thread-based subagents.)"""
    if getattr(manager, "session_blocked", False):
        print("[live] the batch was blocked (balance / approval / macro event) - live phase not started.")
        return
    if not hasattr(manager, "simulate_date"):
        manager.simulate_date = None
    use_mt5 = bool(getattr(manager, "enable_mt5", False))
    main, _pool, runner = _prepare_live(manager, notifier, BatchLedger(), use_mt5, handed=True)
    _serve(main, runner)


def run_live(notifier: Any = None) -> None:
    """RAATS entry point.

    1. Read the persisted batch history (cases A-E) and take the next batch number. A blocked or
       rejected batch is never recovered.
    2. Start the main agent: it takes over positions still open on MT5 and keeps managing them.
    3. Run batches (three thread-based subagents each) in the background: the first batch is
       approved on Discord, passed to the main agent and opened one by one; batches 2, 3, ...
       continue where the previous discovery stopped.
    """
    from src.agents.trading_loop_dynamic import mt5_enabled
    use_mt5 = mt5_enabled()                 # auto: on when the MT5 terminal answers
    ledger = BatchLedger()
    plan = decide_startup(ledger)
    print(f"[live] startup case {plan['case']}: next batch {plan['batch_no']} "
          f"(id {ledger.batch_id(plan['batch_no'])})")
    if plan["abandon"] is not None:
        ledger.status(plan["abandon"], ABANDONED, reason="restart: its threads did not survive")

    from src.agents.trading_loop_dynamic import (
        DynamicTradingManager, _live_portfolio_value, GLOBAL_STATE)
    GLOBAL_STATE.reset()                 # a fresh run starts unblocked; the gate decides again
    # the live manager: its RiskManager is the one the main agent trades with
    manager = DynamicTradingManager(
        top_50_performing=[], top_10=[], waiting_list=[],
        portfolio_value=_live_portfolio_value(), enable_mt5=use_mt5)
    manager.simulate_date = None
    setattr(manager, "batch_no", plan["batch_no"])
    main, _pool, runner = _prepare_live(manager, notifier, ledger, use_mt5)
    _serve(main, runner)


if __name__ == "__main__":
    run_live()