"""Per-ticker market gate: closed markets are never accepted by the live agents and are
retained in shared final INVEST until they open."""
import os, sys, tempfile
from datetime import datetime, timezone
from types import SimpleNamespace as NS
sys.path.insert(0, os.getcwd())
os.environ["RAATS_MEMORY_DIR"] = os.path.join(tempfile.mkdtemp(), "summaries")
from src.utils import market_hours as MH
from src.risk.risk_manager import RiskManager
import src.agents.live_agents as LA
from src.data.ticker_memory import TickerMemory

u = lambda *a: datetime(*a, tzinfo=timezone.utc)
thu_us_open, sat = u(2026, 11, 19, 15, 0), u(2026, 11, 21, 15, 0)
assert MH.market_open_for("AAPL", thu_us_open) is True
assert MH.market_open_for("AAPL", sat) is False
assert MH.market_open_for("7203.T", thu_us_open) is False
assert MH.market_open_for("BTC-USD", sat) is True
assert MH.market_open_for("^GSPC", sat) is None and MH.is_ticker_market_open("^GSPC", sat) is True
print("market_hours per ticker ok")

closed = {"BBB"}
LA.market_hours.is_ticker_market_open = lambda t, **k: t.upper() not in closed

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

# 1. handover: the closed ticker is not accepted by the pool
bm = NS(final_invest=["AAA", "BBB"], risk_manager=RiskManager(), daily_results=[{"ticker": "AAA", "confidence": .9}, {"ticker": "BBB", "confidence": .8}],
        news_by_ticker={}, mt5_order_plan={}, mt5_data={}, batch_no=1)
assert main.adopt_batch(bm, 1) == ["AAA"] and pool.tickers() == ["AAA"]
print("adopt_batch refuses a closed market")

# 2. prepare_batch: only open tickers go to approval; the closed one stays shared
bm2 = NS(final_invest=["AAA", "BBB"], daily_results=bm.daily_results, mt5_order_plan={}, mt5_data={}, batch_no=1)
assert sink.prepare_batch(bm2) == ["AAA"]
assert sorted(x["ticker"] for x in sink.shared_candidates()) == ["AAA", "BBB"]
print("prepare_batch keeps only open markets for approval, closed stays retained")

# 3. a pooled candidate whose market closes goes back to shared, not stuck in the pool
pool.put(LA.Candidate("BBB", confidence=.8, ready=True, approved=True))
cand = pool.get("BBB")
assert cand is not None
assert main._return_to_shared(cand, "market closed") == "defer"
assert pool.get("BBB") is None and "BBB" in [x["ticker"] for x in sink.shared_candidates()]
print("closed pooled candidate returns to shared final INVEST")

# 4. once the market opens it is admitted
closed.clear()
assert sorted(sink.prepare_batch(NS(final_invest=[], daily_results=[], mt5_order_plan={}, mt5_data={}, batch_no=2))) == ["AAA", "BBB"]
print("opens later -> admitted")
main.release_authority()
