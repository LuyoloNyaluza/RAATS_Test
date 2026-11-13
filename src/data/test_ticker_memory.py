"""
Unit tests for ticker memory (no MT5, no network, no src package needed).

    python test_ticker_memory.py          (from the folder holding ticker_memory.py,
                                           or the project root: it also tries src/data)
"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "src", "data"))
import ticker_memory as TM


def mem(now, **kw):
    path = os.path.join(tempfile.mkdtemp(), "events.jsonl")
    return TM.TickerMemory(path=path, enabled=True, now_fn=lambda: now[0], **kw), path, now


# 2026-11-09 is a Monday
MON = datetime(2026, 11, 9, 10, 0)
TUE = datetime(2026, 11, 10, 10, 0)
WED = datetime(2026, 11, 11, 10, 0)
FRI = datetime(2026, 11, 13, 10, 0)
NEXT_MON = datetime(2026, 11, 16, 10, 0)

# --- 1. a rejected trade blocks the ticker for 2 trading days, then expires
now = [MON]
m, path, _ = mem(now)
assert m.check("NKE") is None, "nothing recorded yet"
m.record(TM.TRADE_REJECTED, "nke")                      # case-insensitive
assert "rejected" in (m.check("NKE") or "") , "same day: blocked"
now[0] = TUE
assert m.check("NKE"), "next trading day: still blocked"
now[0] = WED
assert m.check("NKE") is None, "after 2 trading days: free"
assert m.check("AAPL") is None, "other tickers are never affected"
print("1. rejected trade: blocked Mon+Tue, free Wed; other tickers unaffected")

# --- 2. the weekend does not count as trading days
now = [FRI]
m, path, _ = mem(now)
m.record(TM.TRADE_REJECTED, "NKE")
now[0] = NEXT_MON
assert m.check("NKE"), "Fri reject, Mon: only 1 trading day has passed -> blocked"
now[0] = datetime(2026, 11, 17, 10, 0)
assert m.check("NKE") is None, "Tue: 2 trading days -> free"
print("2. weekends are skipped when counting trading days")

# --- 3. a losing close cools the ticker down; a win or a flat close does not
now = [MON]
m, path, _ = mem(now)
m.record(TM.CLOSED, "TEM", pnl=-12.5, reason="stop_loss")
m.record(TM.CLOSED, "WIN", pnl=8.0, reason="take_profit")
m.record(TM.CLOSED, "FLAT", pnl=0.0, reason="closed_at_broker")
assert "loss" in (m.check("TEM") or "") and "stop_loss" in m.check("TEM")
assert m.check("WIN") is None and m.check("FLAT") is None
now[0] = WED
assert m.check("TEM") is None, "cooldown over"
print("3. loss -> cooldown; win / flat -> no cooldown")

# --- 4. events persist across restarts; a damaged line is skipped
now = [MON]
m, path, _ = mem(now)
m.record(TM.TRADE_REJECTED, "NKE")
with open(path, "a", encoding="utf-8") as f:
    f.write("{not json\n\n")
m2 = TM.TickerMemory(path=path, enabled=True, now_fn=lambda: now[0])
assert m2.check("NKE"), "a new instance reads the same file"
print("4. persistence across restarts; damaged lines ignored")

# --- 5. look-ahead safety: as_of never sees the future
now = [WED]
m, path, _ = mem(now)
m.record(TM.TRADE_REJECTED, "NKE", ts=TUE)
assert m.check("NKE", as_of="2026-11-09") is None, "as_of Monday must not see Tuesday's rejection"
assert m.check("NKE", as_of="2026-11-10"), "as_of Tuesday sees it"
print("5. as_of ignores events from the future (no look-ahead in simulations)")

# --- 6. old events expire (RAATS_MEMORY_KEEP_DAYS)
now = [datetime(2026, 12, 15, 10, 0)]
m, path, _ = mem(now, keep_days=14)
m.record(TM.CLOSED, "TEM", ts=datetime(2026, 11, 9, 10, 0), pnl=-5.0, reason="stop_loss")
assert m.check("TEM") is None
print("6. events older than keep_days are ignored")

# --- 7. batch rejections and sightings are recorded but never block
now = [MON]
m, path, _ = mem(now)
m.record(TM.BATCH_REJECTED, "NKE", batch=2)
m.record(TM.SEEN, "NKE", batch=1)
m.record(TM.SEEN, "NKE", batch=3)
assert m.check("NKE") is None, "a rejected BATCH says nothing about the ticker"
assert m.times_seen("NKE", 7) == 2
print("7. batch rejection / sightings recorded, never block; times_seen works")

# --- 8. disabled memory does nothing and writes nothing
path = os.path.join(tempfile.mkdtemp(), "events.jsonl")
off = TM.TickerMemory(path=path, enabled=False)
off.record(TM.TRADE_REJECTED, "NKE")
assert off.check("NKE") is None and not os.path.exists(path)
print("8. disabled: no checks, no file")

# --- 9. an unwritable location never raises
try:
    blocker = os.path.join(tempfile.mkdtemp(), "blocker")
    open(blocker, "w").close()
    broken = TM.TickerMemory(path=os.path.join(blocker, "sub", "events.jsonl"), enabled=True)
    broken.record(TM.TRADE_REJECTED, "NKE")          # parent is a FILE: mkdir fails
    assert broken.check("NKE")                       # still remembered in memory
except Exception as exc:
    raise AssertionError(f"memory must never raise: {exc}")
print("9. file errors never raise")

# --- 10. a ticker the broker does not offer is skipped for 30 days (7 when the record says so)
now = [MON]
m, path, _ = mem(now)
m.record(TM.NOT_TRADABLE, "ORKA", reason="symbol not found on MT5")
m.record(TM.NOT_TRADABLE, "HALT", reason="MT5 trading not fully enabled", days=7)
assert "not tradable" in (m.check("ORKA") or "") and "not found" in m.check("ORKA")
now[0] = datetime(2026, 11, 20, 10, 0)                      # 11 days later
assert m.check("ORKA"), "30-day block still active"
assert m.check("HALT") is None, "a restricted-mode record expires after its own 7 days"
now[0] = datetime(2026, 12, 10, 10, 0)                      # 31 days later
assert m.check("ORKA") is None, "after 30 days it may be proposed again"
print("10. not-tradable tickers are skipped for 30 days (a record can set its own days)")

# --- 11. a not-tradable note belongs to ONE broker: another broker lifts it
now = [MON]
path = os.path.join(tempfile.mkdtemp(), "events.jsonl")
server = ["FBS-Real"]
m = TM.TickerMemory(path=path, enabled=True, now_fn=lambda: now[0], server_fn=lambda: server[0])
m.record(TM.NOT_TRADABLE, "ORKA", reason="symbol not found on MT5", server="FBS-Real")
m.record(TM.NOT_TRADABLE, "OLD", reason="symbol not found on MT5")          # an old record without a server
assert m.check("ORKA") and m.check("OLD")
server[0] = "OtherBroker-Live"                                              # switched broker in MT5
assert m.check("ORKA") is None, "a record for FBS must not block the other broker"
assert m.check("OLD"), "a record without a server still applies"
server[0] = "FBS-Real"
assert m.check("ORKA"), "back on FBS: blocked again"
print("11. not-tradable records are per broker (switching broker lifts them)")

print("ALL TICKER MEMORY TESTS PASSED")
