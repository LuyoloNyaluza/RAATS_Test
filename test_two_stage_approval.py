"""
Tests for the two-stage Discord approval rules of RAATS (paper mode, no MT5 terminal needed).

    python test_two_stage_approval.py        (run from the project root, so `src` imports)

  1. Batch approval is not trade approval: a pool candidate is not opened before ITS OWN approval.
  2. No timer before approval: the entry timer starts only after APPROVE.
  3. A rejected / timed-out / errored trade is never executed; the next candidate is taken.
  4. Hard guard: _submit refuses an order without an individual APPROVE.
  5. Each candidate gets its own proposal (margin, lots, entry, SL, TP, risk-to-reward).
  6. The failed initial balance gate sets the ONE global block for both modules.
"""
import os
import sys
import tempfile
import threading
import time
from types import SimpleNamespace as NS
from typing import Any, cast

sys.path.insert(0, os.getcwd())
os.environ["RAATS_MEMORY_DIR"] = os.path.join(tempfile.mkdtemp(), "summaries")

from src.risk.risk_manager import RiskManager
import src.agents.live_agents as LA
from src.data.ticker_memory import TickerMemory

TIMER_CALLS = []


def fake_timer(simulate=True):
    TIMER_CALLS.append(time.time())
    return NS(seconds=0.0, simulated=True)


LA.wait_for_entry = fake_timer
LA.APPROVAL_JOIN_SEC = 0.05


class TradeNotif:
    """send_trade_approval_request + wait_for_approval, answers set per ticker (default APPROVE)."""

    def __init__(self):
        self.answers, self.proposals, self.msgs = {}, [], []
        self.gate = {}                      # ticker -> threading.Event; the answer waits for it

    def send_alert(self, m):
        self.msgs.append(m)
        return True

    def send_trade_approval_request(self, proposal):
        self.proposals.append(dict(proposal))
        return NS(request_id=proposal["ticker"])

    def wait_for_approval(self, request_id):
        ev = self.gate.get(request_id)
        if ev is not None:
            ev.wait(10)
        return self.answers.get(request_id, "APPROVE")


closes_up = [90 + i * 0.4 for i in range(30)]


def mdata(_t):
    return {"close": 100.0, "atr": 2.0, "closes": closes_up}


def stack(tickers, notifier=None, memory=None):
    mgr = NS(risk_manager=RiskManager(), final_invest=list(tickers), closed_positions_today=[],
             daily_results=[], news_by_ticker={}, enable_mt5=False, portfolio_value=1000.0,
             starting_balance=1000.0, hold_history=[])
    n = notifier or TradeNotif()
    pool = LA.FinalInvestPool()
    events = []
    memory = memory or TickerMemory(path=os.path.join(tempfile.mkdtemp(), "events.jsonl"),
                                    enabled=True)            # never the project's real file
    main = LA.MainAgent(mgr, pool, notifier=n, event_sink=events.append,
                        market_data_fn=mdata, use_mt5=False, memory=memory)
    main._macro_block = lambda *a, **k: None   # takes the ticker now; no calendar in tests
    for i, t in enumerate(tickers):
        pool.put(LA.Candidate(t, confidence=0.9 - i * 0.1, batch=1, ready=True, approved=True))
    return mgr, pool, main, n, events


def need(pool, ticker):
    """The pool's candidate for `ticker`; the test fails clearly if it is not there."""
    cand = pool.get(ticker)
    assert cand is not None, f"{ticker} is not in the pool"
    return cand


def wait_for(cond, secs=5.0):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


# ---- 1 + 2: batch approval is not trade approval; the timer starts only after APPROVE
TIMER_CALLS.clear()
mgr, pool, main, n, ev = stack(["AAA"])
n.gate["AAA"] = threading.Event()                        # the human has not answered yet
assert main.fill_slots(limit=1) == 0 and not main.open, "opened on batch approval alone"
assert need(pool, "AAA").approval == "PENDING" and len(n.proposals) == 1
assert not TIMER_CALLS, "the entry timer started before the trade was approved"
n.gate["AAA"].set()                                       # the human approves
assert wait_for(lambda: need(pool, "AAA").approval == "APPROVE")
assert main.fill_slots(limit=1) == 1 and "AAA" in main.open
assert len(TIMER_CALLS) == 1, "the timer must start exactly once, after approval"
main.release_authority()
print("1-2. batch approval does not open a trade; the timer starts only after the trade approval")

# ---- 5: the proposal carries the figures the human decides on
p = n.proposals[0]
for key in ("ticker", "balance", "free_margin", "required_margin", "lots", "entry", "stop_loss",
            "take_profit", "risk_amount", "risk_reward"):
    assert key in p, f"proposal lacks {key}"
assert p["stop_loss"] < p["entry"] < p["take_profit"] or p["take_profit"] < p["entry"] < p["stop_loss"]
print("5. the proposal holds margin, lots, entry, SL, TP, risk amount and risk-to-reward")

# ---- 3: rejected / timeout / error: not executed, the next candidate is taken
for answer in ("REJECT", "TIMEOUT", "ERROR: boom"):
    TIMER_CALLS.clear()
    mgr, pool, main, n, ev = stack(["AAA", "BBB"])
    n.answers["AAA"] = answer
    opened = 0
    for _ in range(6):
        opened += main.fill_slots(limit=1)
        if "BBB" in main.open:
            break
    assert "AAA" not in main.open, f"{answer}: a not-approved trade was executed"
    assert "BBB" in main.open, f"{answer}: the next eligible candidate was not taken"
    assert len(n.proposals) == 2, "every candidate needs its own proposal and approval"
    assert len(TIMER_CALLS) == 1, "the timer must run only for the approved candidate"
    main.release_authority()
print("3. REJECT / TIMEOUT / ERROR are never executed; the next candidate gets its own approval")

# ---- 4: hard guard in _submit
mgr, pool, main, n, ev = stack(["AAA"])
cand = need(pool, "AAA")
status, ctx = main._prepare(cand)
assert status == "ok" and ctx is not None
cand.approval = ""                                       # no individual approval
assert main._submit(cand, ctx) == "drop" and not main.open
assert any(e.get("type") == "execution_refused" for e in ev)
main.release_authority()
print("4. _submit refuses to execute without an individual approval")

# ---- 6: a failed initial balance gate is ONE global block
from src.agents import trading_loop_dynamic as TLD
TLD.GLOBAL_STATE.reset()
LA.discard_pool_state = lambda *a, **k: None            # never touch the real state file
ledger = LA.BatchLedger(tempfile.mkdtemp())
mgr, pool, main, n, ev = stack(["AAA"])
ledger.status(1, LA.BATCH_PROCESSING)
LA._apply_global_block(ledger, main, {"reason": "BLOCKED_INSUFFICIENT_BALANCE", "balance": 0.74,
                                      "min_balance": 20.0, "tickers": ["AAA"],
                                      "by_batch": {1: ["AAA"]}})
assert TLD.GLOBAL_STATE.is_blocked() and TLD.GLOBAL_STATE.reason == TLD.BLOCKED_INSUFFICIENT_BALANCE
latest = ledger.latest()
assert latest is not None and latest["status"] == LA.INSUFFICIENT_FUNDS
assert main.should_stop()
TLD.GLOBAL_STATE.reset()
main.release_authority()
print("6. insufficient balance -> GLOBAL_STATE blocked, ledger INSUFFICIENT_FUNDS, main agent stopped")

# ---- 7: ticker memory
# 7a. a human REJECT is remembered: the same ticker is not proposed again
mgr, pool, main, n, ev = stack(["AAA", "BBB"])
n.answers["AAA"] = "REJECT"
for _ in range(6):
    main.fill_slots(limit=1)
    if "BBB" in main.open:
        break
assert main.memory.check("AAA"), "a rejected trade must be remembered"
assert main.memory.check("BBB") is None
pool.put(LA.Candidate("AAA", confidence=0.9, batch=2, ready=True, approved=True))
before = len(n.proposals)
main.fill_slots(limit=1)
assert len(n.proposals) == before, "a remembered rejection must not be proposed again"
assert any(e.get("type") == "candidate_skipped_memory" and e.get("ticker") == "AAA" for e in ev)
main.release_authority()
print("7a. a rejected trade is remembered and not proposed again")

# 7b. TIMEOUT / ERROR is NOT a rejection
for answer in ("TIMEOUT", "ERROR: boom"):
    mgr, pool, main, n, ev = stack(["AAA", "BBB"])
    n.answers["AAA"] = answer
    for _ in range(6):
        main.fill_slots(limit=1)
        if "BBB" in main.open:
            break
    assert main.memory.check("AAA") is None, f"{answer} must not be remembered as a rejection"
    main.release_authority()
print("7b. timeouts and errors are never recorded as rejections")

# 7c. a candidate you already approved is never blocked by the memory
mgr, pool, main, n, ev = stack(["AAA"])
main.memory.record("trade_rejected", "AAA")             # remembered from an earlier rejection ...
cand = need(pool, "AAA")
status, ctx = main._prepare(cand)                       # ... but THIS proposal was approved by you
assert status == "ok" and ctx is not None
cand.proposal = dict(ctx["proposal"])
cand.approval = "APPROVE"
main._advance(cand)                                     # executes; the memory must not veto it
assert "AAA" in main.open, "an approved candidate must be executed, not vetoed"
assert not any(e.get("type") == "candidate_skipped_memory" for e in ev), "human APPROVE wins"
main.release_authority()
print("7c. an approved candidate is never vetoed by the memory")

# 7d. a losing close is remembered (the position is opened through the real flow first)
mgr, pool, main, n, ev = stack(["AAA"])
assert main.fill_slots(limit=1) == 1 and "AAA" in main.open
main._finish(main.open["AAA"], 95.0, "stop_loss", -12.0)
assert "loss" in (main.memory.check("AAA") or ""), "a losing close must start a cooldown"
main.release_authority()
print("7d. a losing close starts a cooldown")

# 7e. tickers that never ran (balance gate blocked them) leave NO trace in the memory
mgr, pool, main, n, ev = stack(["AAA"])
pool.remove("AAA")
batch_mgr = NS(final_invest=["ZZZ"], daily_results=[], news_by_ticker={}, risk_manager=main.rm)
assert main.adopt_batch(batch_mgr, 1) == ["ZZZ"]
assert main.memory.times_seen("ZZZ") == 0, "handover alone must not record anything"
real_gate = main._initial_balance_gate
main._initial_balance_gate = lambda: False             # the balance gate blocks
assert main.fill_slots(limit=1) == 0
assert main.memory.times_seen("ZZZ") == 0 and main.memory.check("ZZZ") is None, \
    "a ticker blocked for insufficient funds must leave no memory"
main._initial_balance_gate = real_gate                 # funds are fine: it runs and is proposed
main.fill_slots(limit=1)
assert main.memory.times_seen("ZZZ") == 1, "recorded once, when the proposal is made"
main.release_authority()
print("7e. blocked-for-funds tickers leave no memory; 'seen' is recorded when a trade is proposed")

# ---- 8: the trading loop reads the ticker memory BEFORE scoring (batch pipeline)
import pandas as pd
df = pd.DataFrame({"Ticker": ["AAA", "BBB", "CCC", "DDD"], "Return": [9.0, 8.0, 7.0, 6.0]})
pipe = TLD.BatchPipeline(1, skip_fn=lambda t: "you rejected this trade" if t == "BBB" else None)
kept = pipe._apply_memory_filter(df)
assert list(kept["Ticker"]) == ["AAA", "CCC", "DDD"] and list(kept.index) == [0, 1, 2], \
    "BBB must be removed and the next-best instruments move up"
assert "BBB" in pipe.memory_skipped and len(df) == 4, "the input table is not modified"
# no memory -> untouched; a failing memory -> untouched; everything blocked -> not applied
assert TLD.BatchPipeline(1)._apply_memory_filter(df) is df
def boom(t): raise RuntimeError("memory down")
assert len(TLD.BatchPipeline(1, skip_fn=boom)._apply_memory_filter(df)) == 4
assert len(TLD.BatchPipeline(1, skip_fn=lambda t: "x")._apply_memory_filter(df)) == 4
# the sink hands the Main Agent's memory to the pipeline, and the base sink has none
mgr, pool, main, n, ev = stack(["AAA"])
main.memory.record("trade_rejected", "BBB")
fake_sink: Any = NS(main=main)                       # only .main is used by memory_check
assert LA.LiveSink.memory_check(fake_sink, "BBB") and LA.LiveSink.memory_check(fake_sink, "AAA") is None
assert TLD.BatchSink.memory_check(cast(Any, NS()), "BBB") is None
main.release_authority()
print("8. the trading loop skips remembered tickers before news and scoring (fail-safe)")

# ---- 9: a ticker not found on MT5 is reported to the ticker memory (guardrail)
from src.data import mt5_orders as _MO
mgr, pool, main, n, ev = stack(["ORKA"])
main.use_mt5 = True                                   # MT5 mode with a stubbed terminal
saved = (_MO.resolve, _MO.available)
orka = need(pool, "ORKA")        # fetched ONCE: a drop removes the candidate from the pool
try:
    _MO.resolve = lambda t: None                      # the broker does not list it ...
    _MO.available = lambda: False                     # ... but the terminal is NOT reachable
    status, ctx = main._prepare(orka)
    assert status == "drop" and main.memory.check("ORKA") is None, \
        "an MT5 outage must never be remembered as 'not offered'"
    _MO.available = lambda: True                      # the terminal answered: it is really not offered
    status, ctx = main._prepare(orka)
    assert status == "drop" and "not tradable" in (main.memory.check("ORKA") or "")
finally:
    _MO.resolve, _MO.available = saved
main.use_mt5 = False
main.release_authority()
print("9. a ticker the broker does not offer goes into the ticker memory (not on an MT5 outage)")

# ---- 10: a closed market is never proposed to you (dry run included)
mgr, pool, main, n, ev = stack(["AAA"])
main.use_mt5 = True
snap = {"symbol": "AAA.US", "bid": 99.9, "ask": 100.1, "digits": 2, "point": 0.01, "stops_level": 0,
        "contract_size": 1.0, "volume_min": 0.01, "volume_max": 1000.0, "volume_step": 0.01,
        "filling_mode": 2, "trade_mode": 4}
names = ("resolve", "available", "snapshot", "account_balance", "account_free_margin",
         "calc_margin", "check_order")
saved_mo = {k: getattr(_MO, k) for k in names}
try:
    _MO.resolve = lambda t: "AAA.US"
    _MO.available = lambda: True
    _MO.snapshot = lambda s_: dict(snap)
    _MO.account_balance = lambda: 1000.0
    _MO.account_free_margin = lambda: 1000.0
    _MO.calc_margin = lambda *a, **k: 10.0
    _MO.check_order = lambda *a, **k: {"checked": True, "ok": False, "retcode": 10018,
                                       "comment": "Market closed", "not_trading_now": True,
                                       "reason": "market closed"}
    aaa = need(pool, "AAA")
    status, ctx = main._prepare(aaa)
    assert status == "defer" and ctx is None, "a closed market must not reach the approval"
    assert any(e.get("type") == "market_not_open" for e in ev)
    assert not n.proposals, "nothing is sent to Discord while the market is closed"
    # the broker cannot answer (checked False): never block on that
    _MO.check_order = lambda *a, **k: {"checked": False, "ok": False, "retcode": None,
                                       "comment": "MT5 not connected", "not_trading_now": False,
                                       "reason": ""}
    status, ctx = main._prepare(aaa)
    assert status == "ok" and ctx is not None, "an unanswered check must not block"
    # the market is open: normal proposal
    _MO.check_order = lambda *a, **k: {"checked": True, "ok": True, "retcode": 0,
                                       "comment": "Done", "not_trading_now": False, "reason": ""}
    status, ctx = main._prepare(aaa)
    assert status == "ok" and ctx is not None
finally:
    for k, v in saved_mo.items():
        setattr(_MO, k, v)
main.use_mt5 = False
main.release_authority()
print("10. a closed market is deferred (not proposed); an unanswered check never blocks")

print("ALL TWO-STAGE APPROVAL TESTS PASSED")
