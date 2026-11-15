"""Market closed reported only by order_send: the candidate must stay in final INVEST."""
import os, sys, tempfile, time
from types import SimpleNamespace as NS
sys.path.insert(0, os.getcwd())
os.environ["RAATS_MEMORY_DIR"] = os.path.join(tempfile.mkdtemp(), "summaries")
from src.risk.risk_manager import RiskManager
import src.agents.live_agents as LA
from src.data.ticker_memory import TickerMemory
from src.data import mt5_orders as _MO

LA.wait_for_entry = lambda simulate=True: NS(seconds=0.0, simulated=True)
class N:
    def __init__(s): s.msgs = []
    def send_alert(s, m): s.msgs.append(m); return True
    def send_trade_approval_request(s, p): return NS(request_id=p["ticker"])
    def wait_for_approval(s, r): return "APPROVE"
closes = [90 + i * 0.4 for i in range(30)]
def stack(tickers):
    mgr = NS(risk_manager=RiskManager(), final_invest=list(tickers), closed_positions_today=[], daily_results=[],
             news_by_ticker={}, enable_mt5=False, portfolio_value=1000.0, starting_balance=1000.0, hold_history=[])
    pool, ev = LA.FinalInvestPool(), []
    mem = TickerMemory(path=os.path.join(tempfile.mkdtemp(), "e.jsonl"), enabled=True)
    main = LA.MainAgent(mgr, pool, notifier=N(), event_sink=ev.append,
                        market_data_fn=lambda t: {"close": 100.0, "atr": 2.0, "closes": closes}, use_mt5=False, memory=mem)
    main._macro_block = lambda *a, **k: None
    for i, t in enumerate(tickers):
        pool.put(LA.Candidate(t, confidence=0.9 - i * 0.1, batch=1, ready=True, approved=True))
    return pool, main, ev

snap = {"symbol": "AAA.US", "bid": 99.9, "ask": 100.1, "digits": 2, "point": 0.01, "stops_level": 0, "contract_size": 1.0,
        "volume_min": 0.01, "volume_max": 1000.0, "volume_step": 0.01, "filling_mode": 2, "trade_mode": 4}
names = ("resolve","available","snapshot","account_balance","account_free_margin","calc_margin","check_order","place_market_order")
saved = {k: getattr(_MO, k) for k in names}

def run(order_result):
    pool, main, ev = stack(["AAA"])
    main.use_mt5 = True
    _MO.resolve = lambda t: "AAA.US"; _MO.available = lambda: True; _MO.snapshot = lambda s: dict(snap)
    _MO.account_balance = lambda: 1000.0; _MO.account_free_margin = lambda: 1000.0; _MO.calc_margin = lambda *a, **k: 10.0
    _MO.check_order = lambda *a, **k: {"checked": True, "ok": True, "retcode": 0, "comment": "Done", "not_trading_now": False, "reason": ""}  # blind broker
    _MO.place_market_order = lambda *a, **k: order_result
    cand = pool.get("AAA"); status, ctx = main._prepare(cand); assert status == "ok", status
    cand.approval = "APPROVE"
    out = main._submit(cand, ctx)
    inpool = pool.get("AAA") is not None
    main.release_authority(); return out, inpool, ev

try:
    out, inpool, ev = run({"ok": False, "ticket": None, "price": None, "retcode": 10018, "message": "retcode=10018 Market closed"})
    assert out == "defer" and inpool, (out, inpool)
    assert any(e.get("type") == "market_not_open" and e.get("at") == "order_send" for e in ev)
    print("closed at order_send -> defer, candidate stays in the pool")
    out, inpool, ev = run({"ok": False, "ticket": None, "price": None, "retcode": 10019, "message": "retcode=10019 No money"})
    assert out == "drop" and not inpool, (out, inpool)
    print("other failure (no money) -> still dropped, as before")
    out, inpool, ev = run({"ok": False, "ticket": None, "price": None, "message": "MT5 not connected"})   # old-style result, no retcode key
    assert out == "drop" and not inpool
    print("failure without a retcode -> still dropped, no crash")
finally:
    for k, v in saved.items(): setattr(_MO, k, v)
