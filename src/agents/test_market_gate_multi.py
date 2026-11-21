"""One batch with tickers from many markets: at a given moment only the markets that are open go on
to approval and to the live agents; the others stay in shared final INVEST. Uses the REAL
market_hours rules at fixed moments (nothing is faked except the clock).
Run from the project root:  python -m src.agents.test_market_gate_multi"""
import os, sys, tempfile
from datetime import datetime, timezone
from types import SimpleNamespace as NS
sys.path.insert(0, os.getcwd())
os.environ["RAATS_MEMORY_DIR"] = os.path.join(tempfile.mkdtemp(), "summaries")
from src.utils import market_hours as MH
from src.risk.risk_manager import RiskManager
import src.agents.live_agents as LA
from src.data.ticker_memory import TickerMemory

REAL = MH.is_ticker_market_open                      # keep the real rule; only the clock is fixed
NOW: dict[str, datetime | None] = {"t": None}
LA.market_hours.is_ticker_market_open = lambda t, **k: REAL(t, now=NOW["t"])

BATCH = ["AAPL", "VOD.L", "7203.T", "NPN.JO", "BTC-USD", "EURUSD=X", "GC=F", "^GSPC", "SAP.DE", "0700.HK"]
CONF = {t: 0.9 - i * 0.01 for i, t in enumerate(BATCH)}


CUR = []


def make():
    while CUR:                                   # only one Main Agent may hold MT5 write authority
        CUR.pop().release_authority()
    closes = [90 + i * 0.4 for i in range(30)]
    mgr = NS(risk_manager=RiskManager(), final_invest=[], closed_positions_today=[], daily_results=[], news_by_ticker={},
             enable_mt5=False, portfolio_value=1000.0, starting_balance=1000.0, hold_history=[])
    pool = LA.FinalInvestPool()
    mem = TickerMemory(path=os.path.join(tempfile.mkdtemp(), "e.jsonl"), enabled=True)
    main = LA.MainAgent(mgr, pool, notifier=NS(send_alert=lambda m: True), event_sink=lambda e: None,
                        market_data_fn=lambda t: {"close": 100.0, "atr": 2.0, "closes": closes}, use_mt5=False, memory=mem)
    LA.SHARED_FINAL_INVEST_FILE = os.path.join(tempfile.mkdtemp(), "shared.json")
    sink = LA.LiveSink(main, LA.BatchLedger(tempfile.mkdtemp()), use_mt5=False)
    main.shared_candidates_fn, main.retain_shared_fn = sink.shared_candidates, sink.retain_candidate
    CUR.append(main)
    return main, pool, sink


def batch(no=1):
    return NS(final_invest=list(BATCH), risk_manager=RiskManager(), mt5_order_plan={}, mt5_data={}, batch_no=no,
              daily_results=[{"ticker": t, "confidence": CONF[t]} for t in BATCH])


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


# Moment A: Thu 19 Nov 2026 02:00 UTC
#    Tokyo 11:00 open | HK 10:00 open | JSE 04:00 closed | Berlin 03:00 closed | London 02:00 closed
#            New York Wed 21:00 closed | forex (Wed 21:00 ET) open | gold futures (Wed 21:00 ET) open | crypto open
NOW["t"] = utc(2026, 11, 19, 2, 0)
expected_a = {"7203.T", "0700.HK", "BTC-USD", "EURUSD=X", "GC=F", "^GSPC"}      # ^GSPC: hours unknown -> broker decides
main, pool, sink = make()
sent = set(sink.prepare_batch(batch()))
assert sent == expected_a, f"A prepare_batch: {sorted(sent)}"
assert {x["ticker"] for x in sink.shared_candidates()} == set(BATCH), "closed ones must stay retained in shared"
accepted = set(main.adopt_batch(batch(), 1))
assert accepted == expected_a, f"A adopt_batch: {sorted(accepted)}"
print("Asia morning: only", sorted(expected_a), "go on; the rest stay in shared final INVEST")

# Moment B: Thu 19 Nov 2026 15:30 UTC = NY 10:30 | London 15:30 | Berlin 16:30 | JSE 17:30 closed | Tokyo 00:30 closed | HK 23:30 closed
NOW["t"] = utc(2026, 11, 19, 15, 30)
expected_b = {"AAPL", "VOD.L", "SAP.DE", "BTC-USD", "EURUSD=X", "GC=F", "^GSPC"}
main, pool, sink = make()
sent = set(sink.prepare_batch(batch()))
assert sent == expected_b, f"B prepare_batch: {sorted(sent)}"
accepted = set(main.adopt_batch(batch(), 1))
assert accepted == expected_b, f"B adopt_batch: {sorted(accepted)}"
print("US/Europe session: only", sorted(expected_b), "go on")

# Moment C: Sat 21 Nov 2026 12:00 UTC -> only crypto (and the unknown-hours index) are left
NOW["t"] = utc(2026, 11, 21, 12, 0)
expected_c = {"BTC-USD", "^GSPC"}
main, pool, sink = make()
assert set(sink.prepare_batch(batch())) == expected_c
assert set(main.adopt_batch(batch(), 1)) == expected_c
print("Saturday: only", sorted(expected_c), "go on")

# A retained closed ticker is admitted when its market opens (same sink, later moment)
NOW["t"] = utc(2026, 11, 19, 15, 30)                     # US open
main, pool, sink = make()
NOW["t"] = utc(2026, 11, 21, 12, 0)                      # Saturday: AAPL closed -> retained
assert "AAPL" not in sink.prepare_batch(batch())
assert "AAPL" in {x["ticker"] for x in sink.shared_candidates()}
NOW["t"] = utc(2026, 11, 23, 15, 0)                      # Monday 10:00 ET: AAPL open
later = sink.prepare_batch(NS(final_invest=[], daily_results=[], mt5_order_plan={}, mt5_data={}, batch_no=2))
assert "AAPL" in later and "VOD.L" in later and "7203.T" not in later, sorted(later)
print("retained tickers are admitted when their own market opens (Mon: US + London yes, Tokyo no)")
main.release_authority()
