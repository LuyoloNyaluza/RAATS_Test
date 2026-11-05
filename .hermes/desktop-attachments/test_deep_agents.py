"""
Tests for src/agents/{main_agent,models,permissions}.py, subagents/ and tools/.

deepagents / langchain are NOT needed: a stand-in package checks the arguments against the
documented create_deep_agent signature, and a scripted "model" follows MAIN_PROMPT step by step
using the real tools. So this proves the definitions, the permission rules, the tools and the
batch rules fit together - it does NOT test a real LLM. Run it from the project root.
"""
import json, os, re, sys, tempfile, time, types
from dataclasses import dataclass
from types import SimpleNamespace as NS
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- stand-in deepagents + langchain
CAPTURED = {}

@dataclass(frozen=True)
class FilesystemPermission:
    operations: List[str]
    paths: List[str]
    mode: str = "allow"

class TodoListMiddleware: pass

def create_deep_agent(model=None, tools=None, *, system_prompt=None, middleware=(), subagents=None,
                      skills=None, memory=None, permissions=None, backend=None, name=None, **kw):
    # the documented signature: model str | BaseChatModel, tools, system_prompt, subagents, permissions
    assert isinstance(model, str) and ":" in model, "model must be a provider:model string"
    assert all(callable(t) for t in (tools or []))
    assert isinstance(system_prompt, str) and system_prompt
    for sub in subagents or []:
        for key in ("name", "description", "system_prompt"):           # the three required fields
            assert sub.get(key), f"subagent {sub.get('name')} lacks {key}"
        assert all(callable(t) for t in sub.get("tools", []))
        assert all(isinstance(p, FilesystemPermission) for p in sub.get("permissions", []))
    assert all(isinstance(p, FilesystemPermission) for p in (permissions or []))
    CAPTURED.update(model=model, tools=tools, system_prompt=system_prompt, middleware=list(middleware),
                    subagents=subagents, permissions=permissions, name=name)
    return globals().get("ScriptedAgent", lambda *a: None)(tools, subagents, permissions)

for mod, attrs in (("deepagents", {"create_deep_agent": create_deep_agent,
                                   "FilesystemPermission": FilesystemPermission}),
                   ("langchain", {}), ("langchain.agents", {}),
                   ("langchain.agents.middleware", {"TodoListMiddleware": TodoListMiddleware})):
    m = types.ModuleType(mod); m.__dict__.update(attrs); sys.modules[mod] = m

# stand-in for the discovery.py news functions the scoring tools call
disc = types.ModuleType("src.data.discovery")
disc.get_yfinance_news = lambda t, max_results=3: [{"title": f"{t} yahoo {i}"} for i in range(max_results)]
disc.get_google_news_headlines = lambda t, max_results=2: [{"title": f"{t} google {i}"} for i in range(max_results)]
disc.score_top_10_news = lambda recs: [dict(recs[0], sentiment_summary={"overall": "positive", "score": 0.4,
                                       "positive": 3, "negative": 1, "neutral": 1, "total": 5})]
sys.modules["src.data.discovery"] = disc

from src.agents import live_agents as LA
from src.agents import main_agent as MA
from src.agents import permissions as P
from src.agents.subagents import SUBAGENTS, validate_subagents, describe_subagents
from src.agents.tools import runtime, main_tools, discovery_tools, scoring_tools, analysis_tools
from src.risk.risk_manager import RiskManager

assert P.FilesystemPermission is FilesystemPermission      # the real class is used when installed

# ---------------------------------------------------------------- permission rules (first match wins)
def _rx(pattern):
    return re.compile("^" + re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") + "$")

def allowed(rules, op, path):
    for r in rules or []:
        if op in r.operations and any(_rx(p).match(path) for p in r.paths):
            return r.mode == "allow"
    return True                                            # no rule matched: allowed

# ================= 1. subagents are plain dicts with the six fields of the anatomy picture
validate_subagents()
assert [s["name"] for s in SUBAGENTS] == ["discovery", "scoring", "analysis"]
for s in SUBAGENTS:
    for field in ("name", "description", "system_prompt", "tools", "model", "permissions"):
        assert s[field], (s["name"], field)
    assert isinstance(s, dict) and all(callable(t) for t in s["tools"])
assert {t.__name__ for t in SUBAGENTS[1]["tools"]} == {"yahoo_news", "google_news", "score_news"}
for bad in ({"name": "x", "description": "d", "system_prompt": "p", "tools": [lambda: 0], "model": "m",
             "permissions": [1]},):
    try:
        validate_subagents([dict(bad, tools=[type("open_position", (), {"__name__": "open_position",
                                                  "__call__": lambda self: 0})()])]); raise SystemExit("allowed")
    except PermissionError:
        pass
try:
    validate_subagents([{"name": "x", "description": "d"}]); raise SystemExit("incomplete subagent accepted")
except ValueError:
    pass
print("1. three subagents defined as dicts (name, description, system_prompt, tools, model, permissions); "
      "none may hold a trading tool")

# ================= 2. permissions: scoped write access like research_permissions / editor_permissions
sc, di, an, mn = (SUBAGENTS[1]["permissions"], SUBAGENTS[0]["permissions"], SUBAGENTS[2]["permissions"],
                  P.main_permissions)
assert allowed(sc, "write", "/scored/2/AAPL.md") and not allowed(sc, "write", "/candidates/2/pool.md")
assert not allowed(sc, "write", "/analysis/2/AAPL.md") and not allowed(sc, "write", "/reports/batch_2.md")
assert allowed(di, "write", "/candidates/2/pool.md") and not allowed(di, "write", "/scored/2/AAPL.md")
assert allowed(an, "write", "/analysis/2/AAPL.md") and not allowed(an, "write", "/scored/2/AAPL.md")
assert not allowed(mn, "write", "/scored/2/AAPL.md") and not allowed(mn, "write", "/analysis/2/x.md")
assert allowed(mn, "write", "/reports/batch_2.md") and allowed(mn, "read", "/scored/2/AAPL.md")
assert allowed(sc, "read", "/analysis/2/AAPL.md")          # reads are left open
print("2. each subagent writes only in its own zone; the main agent reads all zones, writes only /reports/")

# ================= 3. the main agent is created like the example: subagents=[...]
agent = MA.build_main_agent()
assert CAPTURED["subagents"] is SUBAGENTS and CAPTURED["permissions"] is P.main_permissions
assert [t.__name__ for t in CAPTURED["tools"]] == ["batch_status", "next_candidates", "complete_batch",
                                                  "positions_status", "notify_discord"]
assert any(isinstance(m, TodoListMiddleware) for m in CAPTURED["middleware"]), "planning (write_todos)"
assert "task tool" in CAPTURED["system_prompt"] and "in parallel" in CAPTURED["system_prompt"]
assert "Do NOT score or analyse" in CAPTURED["system_prompt"] and "write_todos" in CAPTURED["system_prompt"]
for t in CAPTURED["tools"]:                                # the main agent has no trading tool either
    assert t.__name__ not in ("open_position", "close_position", "modify_sltp", "place_market_order")
print("3. create_deep_agent(model, tools, system_prompt, subagents=SUBAGENTS, middleware=[Todo...], "
      "permissions) called; model =", CAPTURED["model"])
print(describe_subagents())

# ---------------------------------------------------------------- scripted model: follows MAIN_PROMPT
class ScriptedAgent:
    """Plays the model: does what MAIN_PROMPT says, calling the real tools, honouring permissions."""
    def __init__(self, tools, subagents, permissions):
        self.tools = {t.__name__: t for t in tools}
        self.sub_tools = {s["name"]: {t.__name__: t for t in s["tools"]} for s in subagents}
        self.sub_perms = {s["name"]: s["permissions"] for s in subagents}
        self.main_perms = permissions
        self.calls = 0
        self.denied = []

    def write(self, who, perms, path, text, files):
        if not allowed(perms, "write", path):
            self.denied.append((who, path)); return
        files[path] = {"content": text}

    def invoke(self, inputs, config=None):
        assert "recursion_limit" in (config or {}) and "Run the batch" in inputs["messages"][0]["content"]
        self.calls += 1
        files = {}
        st = json.loads(self.tools["batch_status"]())
        b = st["batch"]
        if not st["batch_active"]:
            out = self.sub_tools["discovery"]["load_candidate_pool"]()
            self.write("discovery", self.sub_perms["discovery"], f"/candidates/{b}/pool.md", out, files)
        for _ in range(60):
            got = json.loads(self.tools["next_candidates"](5))
            for t in got["tickers"]:                                   # "in parallel" in a real run
                self.sub_tools["scoring"]["yahoo_news"](t); self.sub_tools["scoring"]["google_news"](t)
                s = self.sub_tools["scoring"]["score_news"](t)
                self.write("scoring", self.sub_perms["scoring"], f"/scored/{b}/{t}.md", s, files)
            for t in got["tickers"]:
                a = self.sub_tools["analysis"]["analyze_candidate"](t)
                self.write("analysis", self.sub_perms["analysis"], f"/analysis/{b}/{t}.md", a, files)
                self.write("analysis", self.sub_perms["analysis"], f"/scored/{b}/{t}.md", a, files)  # not its zone
            if json.loads(self.tools["batch_status"]())["reserve_needed"]:
                self.sub_tools["discovery"]["load_reserve_pool"]()
            done = json.loads(self.tools["complete_batch"]())
            if done["complete"]:
                break
        self.write("main", self.main_perms, f"/reports/batch_{b}.md",
                   f"batch {b}: {done['final_invest']}", files)
        self.write("main", self.main_perms, f"/scored/{b}/x.md", "no", files)       # must be denied
        return {"messages": [], "files": files}


# ---------------------------------------------------------------- a bound runtime with the real classes
def fresh(equities, reserve, approve, open_count=0, state_path=None):
    seen = LA.SeenTickers([])
    disc_agent = LA.DiscoveryAgent(seen, equity_fetch=lambda: list(equities),
                                   reserve_fetch=lambda ex, acc: [r for r in reserve if r not in ex])
    disc_agent.pending["currency"].clear(); disc_agent.pending["commodity"].clear()
    pool = LA.FinalInvestPool()
    handed = []
    mgr = NS(risk_manager=RiskManager(), final_invest=[], closed_positions_today=[], daily_results=[],
             news_by_ticker={}, enable_mt5=False, portfolio_value=1000.0, starting_balance=1000.0,
             hold_history=[], all_sentiment_scores={})
    engine = LA.PositionEngine(mgr, pool, notifier=NS(send_alert=lambda m: True), use_mt5=False,
                               event_sink=lambda e: None)
    subs = LA.Subagents(pool, disc_agent, lambda t: {}, lambda t, n: (None, ""),
                        on_batch_complete=lambda b, ts: handed.append((b, ts)),
                        open_count_fn=lambda: open_count, state_path=state_path)
    def analyze(t, news):
        assert news["sentiment_summary"]["overall"] == "positive"          # came from the scoring tools
        return (LA.Candidate(t, confidence=0.6, direction="LONG"), "INVEST") if approve(t) else (None, "HOLD")
    runtime.bind(manager=mgr, pool=pool, seen=seen, discovery=disc_agent, subs=subs, engine=engine,
                 analyze_fn=analyze)
    return mgr, pool, subs, engine, handed

# ================= 4. a batch end to end through the tools: completes at 10 candidates
os.environ["RAATS_REPORT_DIR"] = tempfile.mkdtemp()
mgr, pool, subs, engine, handed = fresh([f"X{i:02d}" for i in range(40)], [], lambda t: True)
orch = MA.Orchestrator(MA.build_main_agent(), subs, engine, alert=print)
assert orch.step() == "ran"
print("4. batch", handed[0][0], "->", len(handed[0][1]), "candidates handed over; queue left", len(subs.batch_queue))
assert handed and handed[0][0] == 2 and len(handed[0][1]) == 10 and pool.full() and len(subs.batch_queue) > 0
assert all(pool.get(t).batch == 2 and pool.get(t).ready for t in handed[0][1])
ag = orch.agent
assert ("analysis", "/scored/2/X00.md") in ag.denied and ("main", "/scored/2/x.md") in ag.denied
saved = os.listdir(os.environ["RAATS_REPORT_DIR"])
assert saved == ["batch_2.md"], saved                         # report read out of result["files"]
engine.release_authority()

# ================= 5. fewer than 5 approved -> reserve through the discovery subagent; <10 is fine
mgr, pool, subs, engine, handed = fresh(["E1", "E2", "E3", "E4", "E5", "E6"],
                                        ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"],
                                        lambda t: t in ("E2", "E5") or (t.startswith("R") and int(t[1:]) <= 3))
orch = MA.Orchestrator(MA.build_main_agent(), subs, engine)
assert orch.step() == "ran"
print("5. reserve rule ->", sorted(handed[0][1]))
assert subs.reserve_used and sorted(handed[0][1]) == ["E2", "E5", "R1", "R2", "R3"]
engine.release_authority()

mgr, pool, subs, engine, handed = fresh(["E1", "E2", "E3", "E4", "E5", "E6", "E7"], ["R1"], lambda t: t != "E7")
MA.Orchestrator(MA.build_main_agent(), subs, engine).step()
assert not subs.reserve_used and len(handed[0][1]) == 6       # 5 or more approved: no reserve
print("   6 approved: reserve not used, handed over without waiting for 10")
engine.release_authority()

# ================= 6. pause / resume, and the fallback to the built-in pipeline
mgr, pool, subs, engine, handed = fresh([f"X{i:02d}" for i in range(40)], [], lambda t: True, open_count=10)
orch = MA.Orchestrator(MA.build_main_agent(), subs, engine)
orch.step()                                                    # fills final INVEST to 10
assert pool.full() and engine.open_count() == 0
engine.open["A"] = {}; 
for i in range(9): engine.open[f"B{i}"] = {}
calls = orch.agent.calls
assert orch.step() == "paused" and subs.paused and orch.agent.calls == calls   # 10 open + 10 final INVEST
q = list(subs.batch_queue)
del engine.open["A"]
pool.take(); assert orch.step() in ("ran", "waiting") and not subs.paused    # a place freed: resumed
assert list(subs.batch_queue) != q or len(pool) == 10
print("6. paused at open=10 & final INVEST=10 (agent not run, queue kept); resumed when a place freed")
engine.release_authority()

class Broken:
    def invoke(self, *a, **k): raise ConnectionError("ollama is down")
mgr, pool, subs, engine, handed = fresh(["E1", "E2"], [], lambda t: True)
alerts, started = [], []
orch = MA.Orchestrator(Broken(), subs, engine, alert=alerts.append, fallback=lambda: started.append(1), max_failures=2)
assert orch.step() == "failed" and not started
assert orch.step() == "failed" and started == [1] and orch.fell_back and alerts and "built-in pipeline" in alerts[0]
engine.release_authority()
class Idle:
    def invoke(self, *a, **k): return {"messages": []}
mgr, pool, subs, engine, handed = fresh(["E1", "E2"], [], lambda t: True)
orch = MA.Orchestrator(Idle(), subs, engine, fallback=lambda: started.append(2), max_failures=2)
orch.step(); orch.step()
assert orch.fell_back and started[-1] == 2
print("   an agent that fails or makes no progress twice -> alert + built-in pipeline takes over")
engine.release_authority()

# ================= 7. tools: rules enforced inside the tools, not left to the model
mgr, pool, subs, engine, handed = fresh(["E1", "E2", "E3"], ["R1"], lambda t: True)
assert "fetch the Yahoo" in scoring_tools.score_news("E1")                      # order matters
assert json.loads(analysis_tools.analyze_candidate("E1"))["error"] == "score the news first"
assert json.loads(discovery_tools.load_reserve_pool())["added"] == 0           # not needed yet
subs.begin_batch_now()
assert [t for t, _ in subs.take_for_processing(2)] == ["E1", "E2"] and subs.inflight() == 2
assert json.loads(main_tools.complete_batch())["complete"] is False            # candidates still left
for t in ("E1", "E2", "E3"):
    scoring_tools.yahoo_news(t); scoring_tools.google_news(t); scoring_tools.score_news(t)
for t in ("E1", "E2"):
    r = json.loads(analysis_tools.analyze_candidate(t)); assert r["decision"] == "INVEST" and r["side"] == "BUY"
subs.take_for_processing(1)
analysis_tools.analyze_candidate("E3")
assert json.loads(main_tools.positions_status())["open"] == 0
assert json.loads(main_tools.batch_status())["final_invest_count"] == 3
# a candidate handed out but never returned is given one more chance, then dropped
subs._manual["GHOST"] = (time.time() - 5000, "equity")
assert subs.sweep_stale(900) == ["GHOST"] and subs.batch_queue[0][0] == "GHOST"
subs.batch_queue.clear(); subs._manual["GHOST"] = (time.time() - 5000, "equity")
subs.sweep_stale(900); assert not subs.batch_queue and not subs._manual
print("7. tools enforce order, the reserve rule, the cap and the retry-once rule")
engine.release_authority()

# ================= 8. BUY/SELL decision + the SL/TP set initially go into agent_performance
import shutil
work = tempfile.mkdtemp(); os.chdir(work)
from src.data import mt5_orders
class FM:   # the smallest fake MT5 that the engine needs
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP, ORDER_TYPE_BUY, ORDER_TYPE_SELL = 1, 6, 0, 1
    ORDER_TIME_GTC, ORDER_FILLING_IOC, ORDER_FILLING_FOK, ORDER_FILLING_RETURN = 0, 1, 2, 3
    TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED, TRADE_RETCODE_NO_CHANGES, DEAL_ENTRY_OUT = 10009, 10008, 10025, 1
    def __init__(self): self.pos, self.sent, self.n = [], [], 500
    def terminal_info(self): return NS()
    def initialize(self): return True
    def last_error(self): return (0, "")
    def symbol_info(self, s): return NS(digits=2, point=0.01, trade_stops_level=10, trade_contract_size=1.0,
        volume_min=0.01, volume_max=1000.0, volume_step=0.01, filling_mode=2, trade_mode=4)
    def symbol_info_tick(self, s): return NS(bid=100.0, ask=100.1)
    def account_info(self): return NS(balance=1000.0, margin_free=1000.0)
    def order_calc_margin(self, *a): return 1.0
    def positions_get(self, symbol=None, **k): return [p for p in self.pos if symbol in (None, p.symbol)]
    def order_send(self, req):
        self.sent.append(req); self.n += 1
        self.pos.append(NS(ticket=self.n, identifier=self.n, symbol=req["symbol"], magic=req["magic"], type=req["type"],
                           volume=req["volume"], price_open=req["price"], sl=req["sl"], tp=req["tp"],
                           comment=req["comment"], time_msc=self.n, profit=0))
        return NS(retcode=10009, order=self.n, price=req["price"], comment="")
fm = FM(); mt5_orders.mt5 = fm; mt5_orders.resolve_mt5_symbol = lambda t: t
os.environ["RAATS_LIVE_TRADING"] = "1"
LA.wait_for_entry = lambda simulate=True: NS(seconds=0.0, simulated=True)
mgr = NS(risk_manager=RiskManager(), final_invest=[], closed_positions_today=[], daily_results=[], news_by_ticker={},
         enable_mt5=True, portfolio_value=1000.0, starting_balance=1000.0, hold_history=[])
pool = LA.FinalInvestPool()
eng = LA.PositionEngine(mgr, pool, notifier=NS(send_alert=lambda m: True), use_mt5=True, event_sink=lambda e: None,
                        market_data_fn=lambda t: {"close": 100.0, "atr": 2.0, "closes": [90 + i * 0.4 for i in range(30)]})
pool.put(LA.Candidate("AAA", confidence=0.8, batch=2, ready=True, approved=True))
assert eng.fill_slots() == 1
rec = eng.open["AAA"]
import glob
files = glob.glob(os.path.join("logs", "agent_performance_*.jsonl"))
rows = [json.loads(l) for f in files for l in open(f)]
op = [r for r in rows if r["ticker"] == "AAA" and r["stage"] == "opened"][0]
print("8. opened ->", {k: op[k] for k in ("signal", "decision", "initial_stop_loss", "initial_take_profit", "stage")})
assert op["signal"] == "INVEST" and op["decision"] == "BUY" and op["direction"] == "LONG"
assert op["initial_stop_loss"] == fm.sent[0]["sl"] and op["initial_take_profit"] == fm.sent[0]["tp"]
eng._finish(rec, 99.0, "stop_loss")
rows = [json.loads(l) for f in files for l in open(f)]
cl = [r for r in rows if r["ticker"] == "AAA" and r["stage"] == "closed"][0]
assert cl["decision"] == "BUY" and cl["initial_stop_loss"] == op["initial_stop_loss"]      # initial levels kept
eng.release_authority()
print("ALL DEEP-AGENT TESTS PASSED")
