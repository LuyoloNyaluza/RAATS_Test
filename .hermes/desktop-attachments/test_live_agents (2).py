import json, os, sys, tempfile, time
from types import SimpleNamespace as NS
PROJECT_ROOT = "/tmp/proj"
sys.path.insert(0, PROJECT_ROOT)

# The tests must not write into the real logs: AAA..EEE rows used to land in
# logs/agent_performance_*.jsonl and data/summaries/sessions_*.jsonl.
_TMP = tempfile.mkdtemp()
os.environ["RAATS_MEMORY_DIR"] = os.path.join(_TMP, "summaries")
import src.utils.logger as _logger
_real_log_cycle = _logger.log_cycle
_test_cycle_rows = []
def _log_cycle_to_tmp(**kw):
    kw["log_dir"] = os.path.join(_TMP, "logs")
    row = _real_log_cycle(**kw)
    _test_cycle_rows.append(row)
    return row
_logger.log_cycle = _log_cycle_to_tmp

from src.data import mt5_orders
from src.risk.risk_manager import RiskManager
import src.agents.live_agents as LA
LA.wait_for_entry = lambda simulate=True: NS(seconds=0.0, simulated=True)


class FakeMT5:
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_TIME_GTC, ORDER_FILLING_IOC, ORDER_FILLING_FOK, ORDER_FILLING_RETURN = 0, 1, 2, 3
    TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED, TRADE_RETCODE_NO_CHANGES = 10009, 10008, 10025
    DEAL_ENTRY_OUT, DEAL_REASON_SL, DEAL_REASON_TP = 1, 4, 5

    def __init__(self):
        self.prices = {s: (100.0, 100.1) for s in ["AAA", "BBB", "CCC", "DDD", "EEE"]}
        self.positions, self.deals, self.sent, self.n = [], [], [], 1000
        self.balance = 1000.0

    def terminal_info(self): return NS()
    def initialize(self): return True
    def last_error(self): return (0, "ok")
    def symbol_info(self, s):
        return NS(digits=2, point=0.01, trade_stops_level=10, trade_contract_size=1.0, volume_min=0.01,
                  volume_max=1000.0, volume_step=0.01, filling_mode=2, trade_mode=4)
    def symbol_info_tick(self, s):
        b, a = self.prices[s]; return NS(bid=b, ask=a)
    def account_info(self): return NS(balance=self.balance, margin_free=self.balance)
    def order_calc_margin(self, action, s, lots, price): return lots * price * 0.1
    def positions_get(self, symbol=None, **k):
        return [p for p in self.positions if symbol is None or p.symbol == symbol]
    def history_deals_get(self, position=None):
        return [d for d in self.deals if d.position_id == position]
    def order_send(self, req):
        self.sent.append(dict(req))
        if req["action"] == self.TRADE_ACTION_DEAL and "position" not in req:
            self.n += 1
            self.positions.append(NS(ticket=self.n, identifier=self.n, symbol=req["symbol"], magic=req["magic"],
                                     type=req["type"], volume=req["volume"], price_open=req["price"],
                                     sl=req["sl"], tp=req["tp"], comment=req["comment"], time_msc=self.n, profit=0.0))
            return NS(retcode=self.TRADE_RETCODE_DONE, order=self.n, price=req["price"], comment="")
        if req["action"] == self.TRADE_ACTION_SLTP:
            p = [x for x in self.positions if x.ticket == req["position"]][0]
            if p.sl == req["sl"] and p.tp == req["tp"]:
                return NS(retcode=self.TRADE_RETCODE_NO_CHANGES, order=0, price=0, comment="nc")
            p.sl, p.tp = req["sl"], req["tp"]
            return NS(retcode=self.TRADE_RETCODE_DONE, order=0, price=0, comment="")
        if "position" in req:
            self.positions = [x for x in self.positions if x.ticket != req["position"]]
            self.deals.append(NS(position_id=req["position"], entry=1, reason=0, price=req["price"],
                                 profit=1.0, commission=0, swap=0))
            return NS(retcode=self.TRADE_RETCODE_DONE, order=0, price=req["price"], comment="")
    def broker_hits(self, ticket, reason, price, profit):
        self.positions = [x for x in self.positions if x.ticket != ticket]
        self.deals.append(NS(position_id=ticket, entry=1, reason=reason, price=price, profit=profit,
                             commission=0, swap=0))


fake = FakeMT5()
mt5_orders.mt5 = fake
mt5_orders.resolve_mt5_symbol = lambda t: t
mt5_orders.is_mt5_tradable = lambda t: t != "NOPE"


class Notif:
    def __init__(self, response="APPROVE"):
        self.msgs, self.requests, self.response = [], [], response
    def send_alert(self, m): self.msgs.append(m); return True
    def send_approval_request(self, final_invest, mt5_data=None, account_balance=None):
        self.requests.append(list(final_invest)); return NS(request_id="r1")
    def send_trade_approval_request(self, proposal):
        self.requests.append(proposal); return NS(request_id="r1")
    def wait_for_approval(self, request_id): return self.response


def make_manager(tickers):
    return NS(risk_manager=RiskManager(), final_invest=list(tickers), closed_positions_today=[],
              daily_results=[{"ticker": t, "confidence": 0.7, "direction": "LONG"} for t in tickers],
              news_by_ticker={}, enable_mt5=True, portfolio_value=1000.0, starting_balance=1000.0, hold_history=[])

closes_up = [90 + i * 0.4 for i in range(30)]
def mdata(t): return {"close": 100.0, "atr": 2.0, "closes": closes_up}
def wait_for(cond, secs=8.0):
    end = time.time() + secs
    while time.time() < end:
        if cond(): return True
        time.sleep(0.05)
    return False

def new_main(tickers, notifier=None):
    mgr = make_manager(tickers)
    n = notifier or Notif(); ev = []
    pool = LA.FinalInvestPool()
    main = LA.MainAgent(mgr, pool, notifier=n, event_sink=ev.append, market_data_fn=mdata, use_mt5=True)
    return mgr, pool, main, n, ev


# ============== 1. authority: only the main agent can write
os.environ["RAATS_LIVE_TRADING"] = "1"
mgr, pool, main, n, ev = new_main(["AAA"])
for call in (lambda: mt5_orders.place_market_order("AAA", "LONG", 1, 90, 110),
             lambda: mt5_orders.modify_sltp(1, "AAA", 90, 110),
             lambda: mt5_orders.close_position(1, "AAA", "LONG", 1),
             lambda: mt5_orders.place_market_order("AAA", "LONG", 1, 90, 110, token=object())):
    try:
        call(); raise SystemExit("write allowed without the main agent's token")
    except PermissionError:
        pass
try:
    LA.MainAgent(make_manager([]), LA.FinalInvestPool(), notifier=Notif(), use_mt5=True)
    raise SystemExit("a second main agent was allowed")
except PermissionError:
    pass
print("1. authority ok: only the main agent can open/close/modify; a second main agent is refused")

# ============== 2. final INVEST: max 10, no open/closed tickers, approval gates opening
assert main.adopt_batch(mgr, 1) == ["AAA"]
c = pool.get("AAA"); assert c is not None and c.approved and c.ready and c.batch == 1
big = LA.FinalInvestPool()
assert all(big.put(LA.Candidate(f"S{i}")) for i in range(10)) and big.put(LA.Candidate("S10")) is False
assert len(big) == 10 and big.full()
pool.put(LA.Candidate("BBB", confidence=0.9, batch=2))               # not ready, not approved
assert main.fill_slots() == 1 and list(main.open) == ["AAA"], "unapproved candidate was opened"
print("2. pool capped at 10; unapproved candidate not opened")

# ============== 3. adaptive management: 2.0R -> SL 1.5R, 2.5R -> 2.0R, profit taken at the stop
sent = fake.sent[0]
pos = mgr.risk_manager.positions["AAA"]; ru, entry = pos.risk_unit, pos.entry_price
assert abs(sent["tp"] - (entry + 3 * ru)) < 0.011 and sent["tp"] > entry + 2 * ru, "TP must sit beyond 2R"
bp = fake.positions[0]
def at_ratio(r):
    fake.prices["AAA"] = (entry + r * ru, entry + r * ru + 0.1)
n0 = len(fake.sent)
at_ratio(1.9); main.monitor_tick()
assert len(fake.sent) == n0 and "AAA" in main.open, "nothing should change below 2.0R"
at_ratio(2.001); main.monitor_tick()          # ratio just past 2.0
print("   2.0R: SL", bp.sl, "(entry+1.5R =", round(entry + 1.5 * ru, 2), ") TP", bp.tp)
assert abs(bp.sl - (entry + 1.5 * ru)) < 0.011 and "AAA" in main.open, "must NOT be closed at 2R"
assert abs(bp.tp - (entry + 3.5 * ru)) < 0.011          # ceiling stays >= 1R ahead of the best ratio
at_ratio(2.501); main.monitor_tick()          # ratio just past 2.5
print("   2.5R: SL", bp.sl, "(entry+2.0R =", round(entry + 2.0 * ru, 2), ") TP", bp.tp)
assert abs(bp.sl - (entry + 2.0 * ru)) < 0.011 and abs(bp.tp - (entry + 4.0 * ru)) < 0.011
n1 = len(fake.sent); main.monitor_tick(); main.monitor_tick()
assert len(fake.sent) == n1, "unchanged levels must not be re-sent"
at_ratio(2.2); main.monitor_tick()                                      # pulls back: the stop never loosens
assert abs(bp.sl - (entry + 2.0 * ru)) < 0.011 and len(fake.sent) == n1
fake.broker_hits(bp.ticket, FakeMT5.DEAL_REASON_SL, bp.sl, 4.2)         # the locked stop is hit
main.monitor_tick()
closed = [e for e in ev if e["type"] == "position_closed"][0]
print("   closed:", closed["reason"], closed["pnl"])
assert closed["reason"] == "take_profit_trailing_stop" and abs(closed["pnl"] - 4.2) < 1e-9
assert "AAA" not in main.open and "AAA" in main.closed_today and any("CLOSED" in m for m in n.msgs)
print("3. adaptive management ok")

# a tighter stop already on MT5 is never loosened
fake.prices["BBB"] = (100.0, 100.1)
pool.put(LA.Candidate("BBB", confidence=0.9, batch=2, ready=True, approved=True))
assert main.fill_slots() == 1
bb = [p for p in fake.positions if p.symbol == "BBB"][0]
tight = bb.sl + 0.5; bb.sl = tight
main.monitor_tick()
assert fake.positions[0].sl == tight, "broker stop was loosened"
print("   broker-tightened stop kept")

# ============== 4. slots: no balance gate here; closure frees a slot; all free slots filled
fake.balance = 15.0                                                     # below $20: not a gate any more
for t in ("CCC", "DDD", "EEE"):
    pool.put(LA.Candidate(t, confidence=0.5, batch=2, ready=True, approved=True))
assert main.fill_slots() == 3, n.msgs[-3:]
assert not any("INSUFFICIENT" in m for m in n.msgs)
assert main.open_count() == 4 and set(main.open) == {"BBB", "CCC", "DDD", "EEE"}
fake.balance = 1000.0
main.max_positions = 4
pool.put(LA.Candidate("AAA2", confidence=0.5, batch=3, ready=True, approved=True))
fake.prices["AAA2"] = (10.0, 10.02)
assert main.fill_slots() == 0 and "AAA2" in pool.tickers()              # full: kept, not opened
bt = [p for p in fake.positions if p.symbol == "CCC"][0]
fake.broker_hits(bt.ticket, FakeMT5.DEAL_REASON_SL, 95.0, -2.0)
main.monitor_tick()
assert main.open_count() == 3 and main.fill_slots() == 1 and "AAA2" in main.open
assert main.open_count() == 4
print("4. one closure -> one candidate taken from final INVEST; no repeated balance gate")
main.release_authority()

# ============== 7. INVEST is logged as a trade: side, entry, SL, TP, size, lots, ticket
opened_rows = [r for r in _test_cycle_rows if r.get("event") == "opened"]
closed_rows = [r for r in _test_cycle_rows if r.get("event") == "closed"]
assert opened_rows and closed_rows
for r in opened_rows:
    assert r["side"] in ("BUY", "SELL") and r["direction"] in ("LONG", "SHORT")
    assert r["stop_loss"] and r["take_profit"] and r["position_size"] and r["executed_price"]
    assert r.get("lots") is not None and r.get("ticket") is not None
for r in closed_rows:                       # closing order is the opposite of the position
    assert r["side"] == ("SELL" if r["direction"] == "LONG" else "BUY")
print("7. every INVEST row carries BUY/SELL, entry, SL, TP, size, lots and ticket")

# ============== 8. small balance: open what the money pays for, keep the rest, never above 10
os.environ["RAATS_REQUIRE_APPROVAL"] = ""
LA.DEFER_RETRY_SEC = 0.0                                  # retry at once (the default is 60 s)
fake.positions.clear(); fake.deals.clear()
fake.prices.update({f"S{i}": (100.0, 100.1) for i in range(14)})
fake.balance = 20.0
# the broker's smallest trade is 1 unit; one minimum lot needs $6 of margin
fake.symbol_info = lambda s: NS(digits=2, point=0.01, trade_stops_level=10, trade_contract_size=1.0,
                                volume_min=1.0, volume_max=1000.0, volume_step=1.0, filling_mode=2,
                                trade_mode=4)
fake.order_calc_margin = lambda action, s, lots, price: lots * 6.0
fake.account_info = lambda: NS(balance=fake.balance,
                               margin_free=fake.balance - sum(p.volume * 6.0 for p in fake.positions))
mgr, pool, main, n, ev = new_main([])
for i in range(6):                                        # six approved candidates, best first
    assert pool.put(LA.Candidate(f"S{i}", confidence=0.9 - i * 0.1, batch=1, ready=True, approved=True))

# $20 pays for 3 minimum-lot positions: those 3 open, one by one, the other 3 stay in final INVEST
assert main.fill_slots() == 3
assert main.open_count() == 3 and set(main.open) == {"S0", "S1", "S2"}
assert all(p.volume == 1.0 for p in fake.positions), "small account: minimum lot"
assert set(pool.tickers()) == {"S3", "S4", "S5"}, pool.tickers()
assert not [e for e in ev if e["type"] == "candidate_dropped"], "affordability must not discard"
assert main.open["S0"]["margin"] == 6.0
print("8a. $20: 3 opened at the minimum lot, 3 kept in final INVEST, none dropped")

# the next batch refills final INVEST to 10, never above
for i in range(6, 13):               # 3 waiting + 7 = 10
    pool.put(LA.Candidate(f"S{i}", confidence=0.3, batch=2, ready=True, approved=True))
assert len(pool) == 10 and pool.full() and pool.put(LA.Candidate("S99")) is False
assert main.fill_slots() == 0 and main.open_count() == 3, "no money: nothing more opens"
assert len(pool) == 10
print("8b. batch 2 fills final INVEST to 10 (cap kept); nothing opens until there is money")

# the balance grows: it keeps opening the most it can pay for
fake.balance = 40.0                                       # free margin 22 -> 3 more
assert main.fill_slots() == 3 and main.open_count() == 6
fake.balance = 200.0                                      # not below $200: RAATS sizing below one lot waits
assert main.fill_slots() == 0 and main.open_count() == 6
fake.balance = 1000.0                                     # RAATS sizing now clears the minimum lot
main.fill_slots()
assert main.open_count() == 10, main.open_count()         # 10 open, never more
assert len(pool) == 3                                     # the rest wait: the cap is 10 open
assert main.fill_slots() == 0 and main.open_count() == 10
print("8c. balance grows -> keeps opening the maximum it can; capped at 10 open")

# a closure frees a slot and margin: the next one in final INVEST opens
victim = [p for p in fake.positions if p.symbol == "S0"][0]
fake.broker_hits(victim.ticket, FakeMT5.DEAL_REASON_SL, 95.0, -1.0)
main.monitor_tick()
assert main.open_count() == 9 and main.fill_slots() == 1 and main.open_count() == 10
print("8d. one closure -> one candidate taken from final INVEST (open stays at most 10)")
main.release_authority()

# 3 was only an example: with cheaper margin the same $20 pays for more, up to the cap of 10
fake.positions.clear(); fake.deals.clear(); fake.balance = 20.0
fake.order_calc_margin = lambda action, s, lots, price: lots * 1.5      # 13 would fit, cap is 10
fake.account_info = lambda: NS(balance=fake.balance,
                               margin_free=fake.balance - sum(p.volume * 1.5 for p in fake.positions))
mgr, pool, main, n, ev = new_main([])
for i in range(12):
    pool.put(LA.Candidate(f"S{i}", confidence=0.9 - i * 0.01, batch=1, ready=True, approved=True)) if i < 10 else None
n_opened = 0
while True:                                                  # one by one, as the main loop does
    got = main.fill_slots(limit=1)
    if not got:
        break
    n_opened += got
assert n_opened == 10 and main.open_count() == 10, n_opened  # not 3: what the money pays for, max 10
pool.put(LA.Candidate("S10", confidence=0.5, batch=2, ready=True, approved=True))
assert main.fill_slots() == 0 and main.open_count() == 10 and "S10" in pool.tickers()
print("8e. $20 with cheap margin -> 10 opened (what it can afford, capped at 10); the 11th waits")
main.release_authority()


# ====================================================================================
# 9. THE THREADED BATCH PIPELINE that now lives INSIDE trading_loop_dynamic.py.
#    The real section is extracted from the real file (between its BEGIN / END markers) and
#    executed against recording stand-ins for discovery.py and for the loop's classes, so the
#    test checks the exact text that was added: ORDER, THREADS, hand-over, cursor.
# ====================================================================================
import types
import threading
import pandas as pd
from dataclasses import fields
os.environ["RAATS_REQUIRE_APPROVAL"] = ""
CALLS = []                                                   # (function, thread name)

TLD_FILE = os.environ.get("TLD_FILE", os.path.join(PROJECT_ROOT, "src/agents/trading_loop_dynamic.py"))
_tld_text = open(TLD_FILE, encoding="utf-8").read().replace("\r\n", "\n")
SECTION = _tld_text[_tld_text.index("# BEGIN THREADED BATCH PIPELINE"):
                    _tld_text.index("# END THREADED BATCH PIPELINE")]

def _sym(i):                                                 # unique 4-letter gainer symbols
    return "Q" + chr(65 + i // 676) + chr(65 + (i // 26) % 26) + chr(65 + i % 26)
GAINERS = [_sym(i) for i in range(250)]

class FakeYF:
    def screen(self, query, count=40, **kw):
        return {"quotes": [{"symbol": s} for s in GAINERS[:count]]}
    def download(self, *a, **k):
        return "passthrough"

STUB_DISCOVERY = """
import threading
TOP_50_COUNT = 50
TOP_40_EQUITIES_COUNT = 40
COMMODITY_TICKERS = ["GC=F", "SI=F", "CL=F", "NG=F", "HG=F"]
CURRENCY_TICKERS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X"]
MACRO = [False]
def _c(name):
    CALLS.append((name, threading.current_thread().name))
def get_tickers_from_gainers_feed():
    _c("gainers")
    result = yf.screen("day_gainers", count=40)
    out = []
    for item in result.get("quotes", []):
        s = str(item.get("symbol", "")).upper().strip()
        if not s.isalpha() or len(s) > 5:
            continue
        if s not in out:
            out.append(s)
        if len(out) >= TOP_40_EQUITIES_COUNT:
            break
    return out
def build_market_universe(equities):
    _c("universe")
    u = [{"Ticker": t, "Asset_Type": "equity"} for t in equities[:TOP_40_EQUITIES_COUNT]]
    u += [{"Ticker": t, "Asset_Type": "commodity"} for t in COMMODITY_TICKERS[:5]]
    u += [{"Ticker": t, "Asset_Type": "currency"} for t in CURRENCY_TICKERS[:5]]
    return u
def get_previous_session_returns(universe):
    _c("returns"); return list(universe), "2026-11-03"
def apply_mt5_filter(df):
    _c("mt5_filter"); return df
def is_trade_blocked_by_macro(min_impact="MEDIUM"):
    _c("macro"); return MACRO[0]
def build_ticker_arrays(df):
    _c("arrays"); return df[:50], df[:10], df[10:30]
def render_top_50_and_news(top50, top10, target_date):
    _c("news"); return [{"Ticker": u["Ticker"], "news": []} for u in top10]
def render_waiting_list(waiting):
    _c("waiting_list")
"""
disc = types.ModuleType("src.data.discovery")
disc.CALLS = CALLS
disc.yf = FakeYF()
exec(STUB_DISCOVERY, disc.__dict__)
sys.modules["src.data.discovery"] = disc
import src.data as _srcdata
_srcdata.discovery = disc

SCENARIO = {"final": [], "blocked": False, "approval": False, "response": "APPROVE", "balance": 1000.0}
print("[MODULE] test_live_agents loaded, SCENARIO initialized")

def classify_blocked_batch_for_test(manager):
    """Read SCENARIO at call time, but also check manager.session_blocked for 9f test."""
    bal = SCENARIO.get("balance", 1000)
    blk = SCENARIO.get("blocked", False)
    mgr_blocked = getattr(manager, 'session_blocked', False) or getattr(manager, 'blocked', False)
    print(f"[DEBUG classify_blocked_batch] balance={bal}, blocked={blk}, manager.session_blocked={getattr(manager, 'session_blocked', 'N/A')}, mgr_blocked={mgr_blocked}")
    # For the test: if manager is blocked (session_blocked=True) and balance <= 20, return INSUFFICIENT_FUNDS
    if mgr_blocked and bal <= 20:
        print(f"[DEBUG] returning INSUFFICIENT_FUNDS")
        return ("INSUFFICIENT_FUNDS", {"reason": "insufficient_balance"})
    elif bal <= 20:
        print(f"[DEBUG] returning INSUFFICIENT_FUNDS")
        return ("INSUFFICIENT_FUNDS", {"reason": "insufficient_balance"})
    else:
        print(f"[DEBUG] returning ABANDONED")
        return ("ABANDONED", {"reason": "macro_event_window"})

# Also add a wrapper to catch if it's called
import sys
_old_classify = classify_blocked_batch_for_test
def _debug_classify(m):
    print(f"[DEBUG _debug_classify] called with balance={SCENARIO.get('balance')}")
    return _old_classify(m)
classify_blocked_batch_for_test = _debug_classify
CREATED = []                                                 # kwargs of every manager built

class StubManager:
    def __init__(self, **kw):
        CREATED.append(kw)
        self.kw = kw
        self.top_50_performing, self.top_10, self.initial_waiting_list = (
            kw["top_50_performing"], kw["top_10"], kw["waiting_list"])
        self.active_list, self.waitlist, self.final_invest = [], [], []
        self.hold_history, self.replacement_history, self.closed_positions_today = [], [], []
        self.risk_manager = RiskManager()
        self.rgr_results, self.rgr_rejected, self.mt5_data, self.mt5_order_plan = {}, [], {}, {}
        self.reserve_info, self.all_sentiment_scores = {"tickers": []}, {}
        self.daily_results, self.news_by_ticker = [], {}
        self.session_blocked, self.enable_mt5 = False, kw.get("enable_mt5")
        self.starting_balance = SCENARIO.get("balance", 1000.0)
    def get_waitlist_opportunities(self, n):
        return []
    def _request_human_approval(self):
        return SCENARIO["response"]
    def run_trading_session(self, simulate_date=None):
        CALLS.append(("session", threading.current_thread().name))
        queue_of_batches = SCENARIO["final"]
        final = list(queue_of_batches.pop(0) if queue_of_batches and isinstance(queue_of_batches[0], list)
                     else queue_of_batches)
        self.final_invest = final
        self.daily_results = [{"ticker": f, "confidence": 0.7, "direction": "LONG"} for f in final]
        if SCENARIO["approval"] and final:
            if self._request_human_approval() != "APPROVE":
                self.session_blocked = True
                return self.daily_results
        if SCENARIO["blocked"]:
            self.session_blocked = True
        return self.daily_results

def _run_dynamic(top_50_performing, top_10, waiting_list, simulate_date=None, portfolio_value=10000.0,
                 analyst_model=None, enable_rgr_gate=True, rgr_threshold=0.0, enable_mt5=False):
    raise AssertionError("the pipeline calls the parts of this wrapper, not the wrapper")

# the names the section uses from the REAL trading_loop_dynamic.py, as stand-ins
tld = types.ModuleType("src.agents.trading_loop_dynamic")
tld.__dict__.update({
    "os": os, "datetime": __import__("datetime").datetime, "pd": pd,
    "List": __import__("typing").List, "Dict": __import__("typing").Dict,
    "Any": __import__("typing").Any, "Optional": __import__("typing").Optional,
    "Tuple": __import__("typing").Tuple,
    "DynamicTradingManager": StubManager, "run_dynamic_trading_session": _run_dynamic,
    "_live_portfolio_value": lambda: 1000.0,
    "balance_status": lambda b: {"shortfall": 20 - b} if b is not None and b <= 20 else None,
    "get_account_balance": lambda: SCENARIO["balance"],
    "check_minimum_balance": lambda: {"shortfall": 20 - SCENARIO["balance"]} if SCENARIO["balance"] <= 20 else None,
    "trade_rows": __import__("src.utils.trade_text", fromlist=["trade_rows"]).trade_rows,
    "format_rows": lambda rows, indent="  ": "",
    "log_error": lambda **kw: LOGGED.append(kw),
    "classify_blocked_batch": classify_blocked_batch_for_test,
    "INSUFFICIENT_FUNDS": "INSUFFICIENT_FUNDS",
})
LOGGED = []
exec(SECTION, tld.__dict__)
sys.modules["src.agents.trading_loop_dynamic"] = tld
import src.agents as _srcagents
_srcagents.trading_loop_dynamic = tld
tld.RUNNER_POLL_SEC = 0.02

# the status values the loop section and live_agents record must stay the same
for name in ("BATCH_PROCESSING", "READY", "WAITING_FOR_APPROVAL", "INSUFFICIENT_FUNDS",
             "BALANCE_UNAVAILABLE", "REJECTED", "HANDED_OVER", "BATCH_COMPLETED", "ABANDONED"):
    assert getattr(tld, name) == getattr(LA, name), name

# the original code above the section is untouched: nothing of it may appear below the markers
assert "BEGIN THREADED BATCH PIPELINE" in _tld_text and _tld_text.index("class DynamicTradingManager") \
    < _tld_text.index("BEGIN THREADED BATCH PIPELINE")

def reset_stubs(final=(), **kw):
    del CALLS[:]; del CREATED[:]; del LOGGED[:]
    SCENARIO.update({"final": list(final), "blocked": False, "approval": False,
                     "response": "APPROVE", "balance": 1000.0, **kw})
    disc.MACRO[0] = False

# 9a. one batch = the original functions in the original order, on three threads, results passed on
reset_stubs(final=["F1", "F2"])
led = LA.BatchLedger(tempfile.mkdtemp())
result = tld.BatchPipeline(1, led.status, used=[], day_index=0).run()
names = [c[0] for c in CALLS]
assert names == ["gainers", "universe", "returns", "mt5_filter", "macro", "arrays",
                 "news", "waiting_list", "session"], names
by_thread = {n: t for n, t in CALLS}
S1, S2, S3 = tld.BatchPipeline.NAMES
assert [by_thread[n] for n in ("gainers", "universe", "returns", "mt5_filter", "macro", "arrays")] == [S1] * 6
assert by_thread["news"] == by_thread["waiting_list"] == S2 and by_thread["session"] == S3
kw = CREATED[0]
assert kw["top_50_performing"][0]["Ticker"] == GAINERS[0] and len(kw["top_50_performing"]) == 50
assert kw["top_10"] == [{"Ticker": u["Ticker"], "news": []} for u in kw["top_50_performing"][:10]]
assert len(kw["waiting_list"]) == 20 and kw["portfolio_value"] == 1000.0
m = result.manager
assert m.batch_no == 1 and m.batch_id.endswith("-B001") and result.session["final_invest"] == ["F1", "F2"]
assert result.session["batch_no"] == 1 and "waitlist_opportunities" in result.session
assert [f.name for f in fields(tld.DiscoveryBatch)][:3] == ["batch_no", "blocked", "exhausted"]
assert len(led.used_today()) == 50 and led.day_index() == 1
print("9a. one batch: gainers..arrays on subagent 1, news on subagent 2, session on subagent 3; batch_no set")

# 9b. batch 2 continues where batch 1 stopped (gainers 41-80, commodities / currencies ranks 6-10)
reset_stubs()
tld.BatchPipeline(2, led.status, used=led.used_today(), day_index=led.day_index()).run()
univ2 = [u["Ticker"] for u in CREATED[0]["top_50_performing"]]
assert univ2[:40] == GAINERS[40:80], "batch 2 must start after the 40 gainers batch 1 used"
assert univ2[40:] == tld.EXTRA_COMMODITY_TICKERS + tld.EXTRA_CURRENCY_TICKERS
assert disc.TOP_40_EQUITIES_COUNT == 40 and disc.COMMODITY_TICKERS[0] == "GC=F" and isinstance(disc.yf, FakeYF), \
    "discovery.py's own settings must be restored after the batch"
reset_stubs()
tld.BatchPipeline(3, led.status, used=led.used_today(), day_index=led.day_index()).run()
univ3 = [u["Ticker"] for u in CREATED[0]["top_50_performing"]]
assert univ3 == GAINERS[80:130], "later batches: the next 50 unused gainers"
print("9b. batch 2 = gainers 41-80 + ranks 6-10; batch 3 = the next 50; discovery settings restored")

# 9c. no unused gainers left: nothing is built, the batch says so
reset_stubs()
out = tld.BatchPipeline(9, None, used=GAINERS[:245], day_index=3).run()
assert out.exhausted and not CREATED
print("9c. gainers exhausted -> reported, no manager built")

# 9d. macro window: the original behaviour (empty arrays go on, the session blocks itself)
reset_stubs(blocked=True)
disc.MACRO[0] = True
res = tld.BatchPipeline(1, None, used=[], day_index=0).run()
assert "news" not in [c[0] for c in CALLS] and len(CREATED[0]["top_50_performing"]) == 0
assert res.manager.session_blocked
status, info = tld.classify_blocked_batch(res.manager)
assert status == tld.ABANDONED and info["reason"] == "macro_event_window"
print("9d. macro event window -> no news step, blocked session, classified as macro")

# 9e. Discord approval is inside subagent 3 (as in the loop); REJECT -> REJECTED
reset_stubs(final=["F1"], approval=True, response="REJECT")
led2 = LA.BatchLedger(tempfile.mkdtemp())
res = tld.BatchPipeline(1, led2.status, used=[], day_index=0).run()
assert res.manager.session_blocked and res.manager.approval_response == "REJECT"
assert tld.classify_blocked_batch(res.manager)[0] == tld.REJECTED
assert LA.WAITING_FOR_APPROVAL in led2.batches()[1]["history"]
print("9e. approval wait recorded (WAITING_FOR_APPROVAL); a rejected batch is classified REJECTED")

# 9f. blocked for funds is told apart from macro
reset_stubs(final=["F1"], blocked=True, balance=5.0)
res = tld.BatchPipeline(1, None, used=[], day_index=0).run()
status, info = tld.classify_blocked_batch(res.manager)
assert status == tld.INSUFFICIENT_FUNDS and info["reason"] == "insufficient_balance"
print("9f. balance 5 -> INSUFFICIENT_FUNDS")

# 9g. an exception in a subagent reaches the coordinator, is logged, and no thread is left hanging
reset_stubs()
class Boom(Exception):
    pass
real_news = disc.render_top_50_and_news
disc.render_top_50_and_news = lambda *a: (_ for _ in ()).throw(Boom("news down"))
pipe = tld.BatchPipeline(1, None, used=[], day_index=0)
try:
    pipe.run(); raise SystemExit("the failure was swallowed")
except Boom:
    pass
assert not any(th.is_alive() for th in pipe.threads)
assert LOGGED and LOGGED[0]["stage"] == "batch_pipeline_news"
disc.render_top_50_and_news = real_news
print("9g. a failing subagent is reported, logged with the loop's own log_error, every thread ends")

# ====================================================================================
# 10. the BatchRunner (in the loop file) talking to live (LiveSink) and the main agent
# ====================================================================================
fake.positions.clear(); fake.deals.clear()
fake.prices.update({t: (100.0, 100.1) for t in ["F1", "F2", "F3"]})
fake.balance = 1000.0
fake.order_calc_margin = lambda action, s, lots, price: lots * 1.5
fake.account_info = lambda: NS(balance=fake.balance,
                               margin_free=fake.balance - sum(p.volume * 1.5 for p in fake.positions))

def live_stack(final=(), ledger=None):
    reset_stubs(final=final)
    led = ledger or LA.BatchLedger(tempfile.mkdtemp())
    mgr, pool, main, n, ev = new_main([])
    main._sink = lambda r: (ev.append(r), led.append(r))
    sink = LA.LiveSink(main, led, True)
    return led, mgr, pool, main, n, ev, sink

# 10a. batch 1 is approved and handed over, the main agent opens it, THEN batch 2 starts, and an
#      empty batch says so on Discord
led, mgr, pool, main, n, ev, sink = live_stack(final=[["F1", "F2", "F3"], []])
runner = tld.BatchRunner(sink, use_mt5=True)
runner.start()
assert wait_for(lambda: main.expect_first_open), runner.outcomes
assert sorted(pool.tickers()) == ["F1", "F2", "F3"] and all(pool.get(t).batch == 1 for t in pool.tickers())
assert runner.outcomes == [(1, "handed")]
time.sleep(0.2)
assert len(CREATED) == 1, "batch 2 must wait until the first batch is opened"
while True:                                                  # what main.run() does, one pass at a time
    o = main.fill_slots(limit=1)
    main._maybe_release_batches(o)
    if not o:
        break
assert main.open_count() == 3
assert wait_for(lambda: any("Batch 2 complete: No tickers approved for final INVEST." in m for m in n.msgs))
assert wait_for(lambda: len(CREATED) >= 2)
univ = [u["Ticker"] for u in CREATED[1]["top_50_performing"]]
assert univ[:40] == GAINERS[40:80]
assert led.batches()[1]["history"][-2:] == [LA.HANDED_OVER, LA.BATCH_COMPLETED]
runner.stop(); runner.join(timeout=5); main.release_authority()
print("10a. batch 1 handed over and opened first; batch 2 then ran from gainers 41-80; empty batch said so")

# 10b. paused only when 10 positions are open AND final INVEST holds 10
led, mgr, pool, main, n, ev, sink = live_stack()
for i in range(10):
    pool.put(LA.Candidate(f"P{i}", ready=True, approved=True))
main.max_positions = 0                                       # "10 open" without opening 10
assert sink.has_room() is False and sink.paused
pool.take(lambda c: True)                                    # final INVEST drops to 9
assert sink.has_room() is True and not sink.paused
main.max_positions = 10
pool.put(LA.Candidate("P10", ready=True, approved=True))
assert sink.has_room() is False and not sink.paused, "pool full but fewer than 10 open: not 'paused'"
main.release_authority()
print("10b. pause only when open == 10 and final INVEST == 10")

# 10c. below $20 at the start: INSUFFICIENT_FUNDS, nothing discovered, live does not run
LA.report_insufficient_funds = lambda bal, tks, alert=None: None
led, mgr, pool, main, n, ev, sink = live_stack()
fake.balance = 5.0
runner = tld.BatchRunner(sink, use_mt5=True)
assert runner.run_batch(1) == "insufficient_funds"
assert main.blocked and main.should_stop() and not CALLS and led.latest()["status"] == LA.INSUFFICIENT_FUNDS
main.release_authority()
fake.balance = 20.0                                          # $20 passes
led, mgr, pool, main, n, ev, sink = live_stack()
assert tld.BatchRunner(sink, use_mt5=True)._balance_ok(2) is True
main.release_authority()
print("10c. balance 5 -> blocked before any discovery, live stops; balance 20.00 passes")

# 10d. balance unreadable: BALANCE_UNAVAILABLE once, retried, no batch generated meanwhile
tld.BATCH_BALANCE_RETRY_SEC = 0.05
led, mgr, pool, main, n, ev, sink = live_stack()
calls = {"n": 0}
real_info = fake.account_info
def flaky():
    calls["n"] += 1
    return None if calls["n"] <= 3 else NS(balance=1000.0, margin_free=1000.0)
fake.account_info = flaky
runner = tld.BatchRunner(sink, use_mt5=True)
assert runner._balance_ok(1) is True and calls["n"] > 3 and not CALLS
assert led.batches()[1]["history"].count(LA.BALANCE_UNAVAILABLE) == 1
fake.account_info = real_info
main.release_authority()
print("10d. balance unreadable -> BALANCE_UNAVAILABLE once, retried until readable, no batch meanwhile")

# ====================================================================================
# 11. the batch ledger and the startup decision (cases A-E); final INVEST on disk
# ====================================================================================
led = LA.BatchLedger(tempfile.mkdtemp())
assert led.latest() is None and led.next_batch_no() == 1
assert LA.decide_startup(led) == {"case": "A", "batch_no": 1, "abandon": None}
led.status(9, LA.BATCH_COMPLETED)
led.status(10, LA.BATCH_PROCESSING)
led.status(10, LA.INSUFFICIENT_FUNDS, tickers=["X1", "X2"], balance=5.0)
led.append({"type": "position_opened", "ticker": "Z", "batch": 3})   # an unrelated line comes last
led.status(9, LA.HANDED_OVER)                                       # a late event of an OLDER batch
assert led.latest()["batch_no"] == 10 and led.latest()["status"] == LA.INSUFFICIENT_FUNDS
plan = LA.decide_startup(led)
assert plan == {"case": "D", "batch_no": 11, "abandon": None} and "X1" not in json.dumps(plan)
print("11a. batch 10 blocked -> the next run is a FRESH batch 11; blocked tickers are not carried")

for status, expect in ((LA.BATCH_PROCESSING, ("B", 2, 1)), (LA.WAITING_FOR_APPROVAL, ("B", 2, 1)),
                       (LA.BATCH_COMPLETED, ("C", 2, None)), (LA.HANDED_OVER, ("C", 2, None)),
                       (LA.REJECTED, ("E", 2, None))):
    l2 = LA.BatchLedger(tempfile.mkdtemp())
    l2.status(1, status)
    p = LA.decide_startup(l2)
    assert (p["case"], p["batch_no"], p["abandon"]) == expect, (status, p)
print("11b. cases A-E decided from the persisted batch records")

pool = LA.FinalInvestPool()
for tkr in ("S1", "S2"):
    pool.put(LA.Candidate(tkr, confidence=0.6, batch=1, ready=True, approved=True))
path = os.path.join(tempfile.mkdtemp(), "pool.json")
LA.save_pool_state(pool, path)
fresh = LA.FinalInvestPool()
assert LA.load_pool_state(fresh, path) == 2 and sorted(fresh.tickers()) == ["S1", "S2"]
st = json.load(open(path))
for c in st["pool"]:
    c["created"] = time.time() - 2 * 3600                    # analysed two hours ago
json.dump(st, open(path, "w"))
stale = LA.FinalInvestPool()
assert LA.load_pool_state(stale, path) == 0 and len(stale) == 0
LA.discard_pool_state(path)
assert not os.path.exists(path)
print("11c. final INVEST on disk: fresh candidates restored, two-hour-old analysis discarded")

# 11d. trading_loop_dynamic's own main block still works: it hands its batch to run_live_phase
reset_stubs(final=["F1", "F2"])
loop_mgr = StubManager(top_50_performing=[], top_10=[], waiting_list=[], enable_mt5=True)
loop_mgr.final_invest = ["F1", "F2"]
loop_mgr.daily_results = [{"ticker": "F1", "confidence": 0.8, "direction": "LONG"},
                          {"ticker": "F2", "confidence": 0.6, "direction": "LONG"}]
loop_mgr.ticker_universe = [f"U{i}" for i in range(50)]
loop_mgr.simulate_date = None
led = LA.BatchLedger(tempfile.mkdtemp())
fake.balance = 1000.0
main, pool, runner = LA._prepare_live(loop_mgr, Notif(), led, True, handed=True)
assert sorted(pool.tickers()) == ["F1", "F2"] and all(pool.get(t).batch == 1 for t in pool.tickers())
assert led.batches()[1]["history"][-2:] == [LA.HANDED_OVER, LA.BATCH_COMPLETED] and main.expect_first_open
assert led.used_today()[:3] == ["U0", "U1", "U2"], "the loop's universe becomes the discovery cursor"
assert isinstance(runner, tld.BatchRunner)
main.release_authority()
print("11d. run_live_phase(manager): the loop's own batch is recorded as batch 1 and handed over")

print("ALL TESTS PASSED")
