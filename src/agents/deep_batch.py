"""
src/agents/deep_batch.py

The batch pipeline on Deep Agents: ONE MAIN AGENT + THREE SUBAGENTS.

    main agent (batch coordinator)
        |-- task -> discovery-agent   wraps BatchPipeline._subagent1  (first half of discovery.main())
        |-- task -> scoring-agent     wraps BatchPipeline._subagent2  (news + sentiment scoring)
        '-- task -> analysis-agent    wraps BatchPipeline._subagent3  (RGR, daily cycle, replacements,
                                                                      reserve, order plan, balance guard,
                                                                      DISCORD APPROVAL of the batch)

NOTHING IN trading_loop_dynamic.py / discovery.py IS CHANGED OR RE-IMPLEMENTED. Each subagent has one
tool, and that tool calls the existing stage method as written. The stages already pass their data
through queues; here the same queues are used, in the same order, on one thread.

WHY THE DATA NEVER GOES THROUGH THE MODEL
-----------------------------------------
DataFrames, the DynamicTradingManager and the approval state live in Python (the pipeline object).
A tool takes no arguments and returns a short JSON summary, so the LLM only ever sees counts,
flags and a few tickers. It cannot change, invent or drop a candidate.

WHO CAN DO WHAT
---------------
* tools       the ONLY real access control: a subagent can call only the tools listed in its spec.
              No agent here has an order, MT5-write, SL/TP or Discord-send tool. Opening, sizing and
              managing positions stays in live_agents.MainAgent (plain code); the human approval of the
              batch stays inside the analysis stage, exactly as before.
* permissions Deep Agents' permissions only govern the FILESYSTEM tools (a virtual, in-memory
              filesystem by default). Each subagent may write notes only under /batch/<n>/<stage>/;
              the main agent may read them but write nothing.
* skills      each subagent has one skill (SKILL.md + reference.md) that explains what a blocked /
              exhausted / failed result means. The agent reads reference.md only when the result is
              not a plain ok (progressive disclosure), so normal batches cost no extra context.
* memory      /memories/AGENTS.md holds the coordinator's standing rules. It is READ-ONLY here: no agent
              may write memory, because what an LLM writes there would come back into every later
              batch (and could be steered by web/news text). Cross-batch history stays in the
              deterministic code (BatchLedger, TickerMemory).
* guards      every stage runs at most once (a second call returns the first result, so the Discord
              approval can never be sent twice), and a stage refuses to run before the one it depends on.

THE CODE IS THE GUARANTEE, NOT THE MODEL
----------------------------------------
After the agent finishes (or fails: model down, bad tool call, timeout) run() executes any stage that
did not run, in order, directly. A weak or unreachable model can therefore never lose a batch; at
worst the pipeline runs exactly as it did before this module existed.

Settings (environment)
----------------------
RAATS_DEEP_AGENTS            1 = on (default), 0 = use the plain thread pipeline
RAATS_DEEP_MODEL             chat model for the main agent, e.g. "ollama:llama3.1" or
                             "anthropic:claude-haiku-4-5" (any langchain init_chat_model string)
RAATS_DEEP_DISCOVERY_MODEL / RAATS_DEEP_SCORING_MODEL / RAATS_DEEP_ANALYSIS_MODEL
                             optional per-subagent overrides (default: the main agent's model)
RAATS_DEEP_RECURSION_LIMIT   graph step limit for one batch (default 40)
RAATS_DEEP_MAX_INPUT_TOKENS  the model's real context size (e.g. your Ollama num_ctx). Lets the built-in
                             SummarizationMiddleware trigger at 85% of the right number; unset = the
                             model's own profile
RAATS_DEEP_SKILLS            skills folder   (default: src/skills)
RAATS_DEEP_MEMORIES          memory folder   (default: src/memories; holds AGENTS.md)

Wire-up (live_agents.py, in _prepare_live):
    from src.agents.deep_batch import DeepBatchPipeline
    runner = BatchRunner(LiveSink(main, ledger, use_mt5), use_mt5,
                         first_batch=not (recovered or restored),
                         pipeline_cls=DeepBatchPipeline)
"""

import json
import os
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

from src.agents.trading_loop_dynamic import BatchPipeline, BatchResult, StageFailure

STAGES = ("discovery", "scoring", "analysis")

_WARNED_NO_MODEL = False


class _NoModel(Exception):
    """RAATS_DEEP_MODEL is not set: skip the agent and run the stages directly."""

# Skills and standing memory live under src/ (read-only for every agent):
#   src/skills/<stage>/<skill-name>/SKILL.md (+ reference.md)   -> /skills/<stage>/...
#   src/memories/AGENTS.md                                      -> /memories/AGENTS.md
# (src/ is the parent of this file's folder.) Override with RAATS_DEEP_SKILLS / RAATS_DEEP_MEMORIES.
_SRC_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = Path(os.environ.get("RAATS_DEEP_SKILLS", _SRC_DIR / "skills"))
MEMORIES_DIR = Path(os.environ.get("RAATS_DEEP_MEMORIES", _SRC_DIR / "memories"))
MEMORY_PATH = "/memories/AGENTS.md"


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


# ======================================================================
# system prompts
# ======================================================================
MAIN_PROMPT = """You are the RAATS batch coordinator. You run ONE trading batch (batch {batch_no}) by
delegating to three subagents with the task tool, strictly ONE AT A TIME and in this order:

  1. discovery-agent   finds and ranks the market universe
  2. scoring-agent     fetches the news and scores the top candidates
  3. analysis-agent    analyses them, builds the order plan and sends the batch for human approval

Rules:
- Each stage depends on the one before it, so never run two at once and never skip one.
- Call each subagent exactly ONCE. If one reports a problem (ok=false, blocked, exhausted), still
  continue with the next stage: the stages pass such results along safely.
- You have no trading tools. You cannot open or close positions, change SL/TP, or approve anything;
  the approval happens inside the analysis stage, by a human.
- Never invent tickers, counts or results. Quote only what the subagents report.
- Finish with a short plain-text report (3-5 lines): what each stage returned and the final result."""

DISCOVERY_PROMPT = """You are the discovery subagent of RAATS.

Your single job: call run_discovery() ONCE. It builds the 50-instrument market universe (top gainers,
topped up from most-active; commodities; currencies), ranks it, applies the MT5 broker filter, the macro
event check and the ticker memory, and prepares the top-50 / top-10 / waiting-list arrays.

How to work:
1. Call run_discovery() with no arguments. Do not call it again; a repeat only returns the same result.
2. Optionally call show_candidates() to read a few tickers.
3. Write nothing else to the filesystem except short notes under your assigned folder.

If the result is anything other than a plain ok (blocked, exhausted, ok=false), use your
discovery-outcomes skill to explain it.

Return ONLY a short report: ok, whether blocked (macro window) or exhausted, and the counts.
Do not invent anything the tool did not return."""

SCORING_PROMPT = """You are the news and scoring subagent of RAATS.

Your single job: call run_scoring() ONCE. It fetches the news for the top candidates and scores their
sentiment, using the discovery result that is already prepared.

How to work:
1. Call run_scoring() with no arguments. If it says discovery has not run, report that and stop;
   do not try to run discovery yourself.
2. Do not call it twice.

If the result is anything other than a plain ok, use your scoring-outcomes skill.

Return ONLY a short report: ok, and how many candidates were scored. Do not invent anything."""

ANALYSIS_PROMPT = """You are the analysis subagent of RAATS.

Your single job: call run_analysis() ONCE. It runs the full analysis session: the RGR screen, the daily
cycle, replacements, the reserve top-up, the MT5 order plan and the balance guard, and it sends the batch
to Discord for HUMAN approval. That approval can take a long time: wait for the tool to return; never
call it again while it runs and never try to approve or reject anything yourself.

How to work:
1. Call run_analysis() with no arguments (it refuses if scoring has not run: report that and stop).
2. After it returns, optionally call show_final_invest() to read the approved tickers.

If the batch was not approved, blocked, empty or failed, use your analysis-outcomes skill.

Return ONLY a short report: ok, exhausted/blocked/rejected if it says so, and the final INVEST tickers
exactly as the tool returned them. Never add a ticker."""


# ======================================================================
# summaries: what the model is allowed to see
# ======================================================================
def _peek(q: "queue.Queue[Any]") -> Any:
    """Look at the next item of a stage queue without removing it."""
    with q.mutex:
        return q.queue[0] if q.queue else None


def _count(value: Any) -> Optional[int]:
    try:
        return len(value)
    except Exception:
        return None


def _tickers_of(value: Any, limit: int = 10) -> List[str]:
    """First few tickers of a list / DataFrame, whatever it holds. Never raises."""
    try:
        if value is None:
            return []
        if hasattr(value, "columns") and "Ticker" in value.columns:
            return [str(t) for t in value["Ticker"].tolist()[:limit]]
        out = []
        for item in list(value)[:limit]:
            out.append(str(item.get("Ticker") if isinstance(item, dict) else item))
        return out
    except Exception:
        return []


def _summarize(item: Any) -> Dict[str, Any]:
    if item is None:
        return {"ok": False, "error": "the stage produced no result"}
    if isinstance(item, StageFailure):
        return {"ok": False, "stage": item.stage,
                "error": f"{type(item.error).__name__}: {item.error}"}
    name = type(item).__name__
    if name == "DiscoveryBatch":
        return {"ok": True, "batch_no": item.batch_no, "blocked": item.blocked,
                "exhausted": item.exhausted, "universe": _count(item.universe),
                "top_50": _count(item.top_50), "top_10": _count(item.top_10),
                "waiting_list": _count(item.waiting)}
    if name == "ScoredBatch":
        d = item.discovery
        return {"ok": True, "blocked": d.blocked, "exhausted": d.exhausted,
                "scored_top_10": _count(item.scored_top_10)}
    if name == "BatchResult":
        manager = item.manager
        out: Dict[str, Any] = {"ok": True, "batch_no": item.batch_no, "exhausted": item.exhausted}
        if manager is not None:
            out.update({
                "final_invest": list(getattr(manager, "final_invest", []) or []),
                "session_blocked": bool(getattr(manager, "session_blocked", False)),
                "approval_response": getattr(manager, "approval_response", None),
            })
        return out
    return {"ok": True, "result": name}


# ======================================================================
# the pipeline: same interface as BatchPipeline, so BatchRunner can use it (pipeline_cls=)
# ======================================================================
class DeepBatchPipeline(BatchPipeline):
    """BatchPipeline whose run() is driven by a Deep Agent instead of three bare threads."""

    _STAGE_FN = {"discovery": "_subagent1", "scoring": "_subagent2", "analysis": "_subagent3"}

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._stage_lock = threading.RLock()
        self._done: Dict[str, Dict[str, Any]] = {}

    # ---- the one place where a stage actually runs ------------------------------------------
    def _stage_queue(self, stage: str) -> "queue.Queue[Any]":
        return {"discovery": self.q12, "scoring": self.q23, "analysis": self.q_out}[stage]

    def _run_stage(self, stage: str) -> Dict[str, Any]:
        """Run `stage` through the EXISTING method, once. Idempotent and order-checked."""
        with self._stage_lock:
            if stage in self._done:                         # never run twice (no second Discord approval)
                return {**self._done[stage], "note": "already ran; this is the same result"}
            for earlier in STAGES[:STAGES.index(stage)]:
                if earlier not in self._done:
                    return {"ok": False, "error": f"{earlier} has not run yet; it must run before {stage}"}
            try:
                getattr(self, self._STAGE_FN[stage])()     # the original, unchanged stage code
            except BaseException as exc:                    # the stages catch everything; belt and braces
                self._stage_queue(stage).put(StageFailure(stage, exc))
            summary = _summarize(_peek(self._stage_queue(stage)))
            self._done[stage] = summary
            return summary

    # ---- tools -------------------------------------------------------------------------------
    def _make_tools(self) -> Dict[str, List[Any]]:
        pipe = self

        @tool
        def run_discovery() -> str:
            """Run the batch discovery stage (universe, ranking, MT5 filter, macro check, ticker memory).
            Takes no arguments. Runs once; calling it again returns the same result."""
            return json.dumps(pipe._run_stage("discovery"), default=str)

        @tool
        def show_candidates() -> str:
            """Read-only: the first few tickers of the discovered top-10 and waiting list."""
            item = _peek(pipe.q12) if "scoring" not in pipe._done else None
            found = item if getattr(item, "top_10", None) is not None else None
            if found is None:
                return json.dumps({"top_10": [], "note": "discovery has not produced candidates yet"})
            return json.dumps({"top_10": _tickers_of(found.top_10),
                               "waiting_list": _tickers_of(found.waiting, 5)}, default=str)

        @tool
        def run_scoring() -> str:
            """Run the news and sentiment scoring stage on the discovered top candidates.
            Takes no arguments. Needs discovery to have run. Runs once."""
            return json.dumps(pipe._run_stage("scoring"), default=str)

        @tool
        def run_analysis() -> str:
            """Run the analysis session and send the batch to Discord for human approval.
            Takes no arguments. Needs scoring to have run. Runs once; may wait a long time for the human."""
            return json.dumps(pipe._run_stage("analysis"), default=str)

        @tool
        def show_final_invest() -> str:
            """Read-only: the final INVEST tickers of this batch (after analysis and approval)."""
            item = _peek(pipe.q_out)
            manager = getattr(item, "manager", None)
            return json.dumps({"final_invest": list(getattr(manager, "final_invest", []) or [])})

        @tool
        def batch_status() -> str:
            """Read-only: which stages of this batch have already run."""
            return json.dumps({"batch_no": pipe.batch_no, "stages_done": list(pipe._done)})

        return {"discovery": [run_discovery, show_candidates], "scoring": [run_scoring],
                "analysis": [run_analysis, show_final_invest], "main": [batch_status]}

    # ---- agents ------------------------------------------------------------------------------
    @staticmethod
    def _resolve_model(name: Optional[str]) -> Any:
        """A langchain chat model from a 'provider:model' string; None = the Deep Agents default."""
        if not name:
            return None
        from langchain.chat_models import init_chat_model
        model = init_chat_model(name)
        raw = os.environ.get("RAATS_DEEP_MAX_INPUT_TOKENS", "").strip()
        if raw.isdigit():                       # must be set on the model OBJECT, not a model string
            try:
                setattr(model, "profile", {**(getattr(model, "profile", None) or {}), "max_input_tokens": int(raw)})
            except Exception as exc:
                print(f"[deep] could not set max_input_tokens: {exc}")
        return model

    @staticmethod
    def _backend() -> Any:
        """Virtual in-memory filesystem for notes; skills and standing memory read from disk.
        Nothing an agent writes ever reaches the real disk (permissions also deny every write
        outside a stage's own notes folder)."""
        routes: Dict[str, Any] = {}
        for prefix, folder in (("/skills/", SKILLS_DIR), ("/memories/", MEMORIES_DIR)):
            if folder.is_dir():
                routes[prefix] = FilesystemBackend(root_dir=str(folder), virtual_mode=True)
        return CompositeBackend(default=StateBackend(), routes=routes)

    def build_agent(self, model: Any = None, stage_models: Optional[Dict[str, Any]] = None) -> Any:
        n = self.batch_no
        tools = self._make_tools()
        stage_models = stage_models or {}

        def scoped(stage: str) -> List[FilesystemPermission]:
            """Read/write only /batch/<n>/<stage>/**; write nowhere else (first match wins)."""
            return [
                FilesystemPermission(operations=["read", "write"],
                                     paths=[f"/batch/{n}/{stage}/**"], mode="allow"),
                FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
            ]

        def spec(name: str, stage: str, description: str, prompt: str) -> Dict[str, Any]:
            sub: Dict[str, Any] = {
                "name": name,
                "description": description,
                "system_prompt": prompt + f"\n\nYour assigned notes folder: /batch/{n}/{stage}/",
                "tools": tools[stage],                       # override: only these custom tools
                "permissions": scoped(stage),                # override: scoped filesystem writes
            }
            if (SKILLS_DIR / stage).is_dir():
                sub["skills"] = [f"/skills/{stage}"]        # override: this stage's own skill only
            if stage_models.get(stage) is not None:
                sub["model"] = stage_models[stage]          # override: e.g. a stronger model for analysis
            return sub

        subagents: List[Any] = [
            spec("discovery-agent", "discovery",
                 "Stage 1. Discover and rank the market universe for this batch (gainers, most-active "
                 "top-up, commodities, currencies, MT5 filter, macro check). Call first, once.",
                 DISCOVERY_PROMPT),
            spec("scoring-agent", "scoring",
                 "Stage 2. Fetch the news and score the sentiment of the discovered candidates. "
                 "Call second, once, after discovery-agent.",
                 SCORING_PROMPT),
            spec("analysis-agent", "analysis",
                 "Stage 3. Run the full analysis session and send the batch for human approval on "
                 "Discord. Call third, once, after scoring-agent.",
                 ANALYSIS_PROMPT),
        ]
        return create_deep_agent(
            model=model,
            tools=tools["main"],                              # the main agent can only read the status
            system_prompt=MAIN_PROMPT.format(batch_no=n),
            subagents=subagents,
            permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
            backend=self._backend(),
            memory=[MEMORY_PATH] if (MEMORIES_DIR / "AGENTS.md").is_file() else None,
            name=f"raats-main-batch-{n}",
        )

    # ---- run ---------------------------------------------------------------------------------
    def _stage_models(self) -> Dict[str, Any]:
        return {s: self._resolve_model(os.environ.get(f"RAATS_DEEP_{s.upper()}_MODEL")) for s in STAGES}

    def run(self) -> BatchResult:
        if not _env_flag("RAATS_DEEP_AGENTS", True):
            return super().run()                              # the plain thread pipeline

        have_model = bool(os.environ.get("RAATS_DEEP_MODEL", "").strip())
        if not have_model:
            # Without a model, create_deep_agent would fall back to Anthropic and fail on the key.
            global _WARNED_NO_MODEL
            if not _WARNED_NO_MODEL:
                _WARNED_NO_MODEL = True
                print("[deep] RAATS_DEEP_MODEL is not set: running the three stages directly "
                      "(no LLM). Set it, e.g. ollama:<model>, to let the agents coordinate them.")

        try:
            if not have_model:
                raise _NoModel()
            agent = self.build_agent(self._resolve_model(os.environ.get("RAATS_DEEP_MODEL")),
                                     self._stage_models())
            out = agent.invoke(
                {"messages": [{"role": "user", "content": f"Run batch {self.batch_no} now."}]},
                config={"recursion_limit": int(os.environ.get("RAATS_DEEP_RECURSION_LIMIT", "40"))},
            )
            report = out["messages"][-1].content              # the coordinator's closing report
            if isinstance(report, str) and report.strip():
                print(f"[deep] batch {self.batch_no} coordinator report: {report.strip()}")
        except _NoModel:
            pass
        except Exception as exc:                              # model down, bad tool call, limit hit ...
            print(f"[deep] batch {self.batch_no}: agent run failed "
                  f"({type(exc).__name__}: {exc}); finishing the stages directly.")

        # The guarantee: whatever the model did or did not do, every stage runs, in order, once.
        missing = [s for s in STAGES if s not in self._done]
        if missing:
            if have_model:
                print(f"[deep] batch {self.batch_no}: running {missing} directly (the agent did not).")
            for stage in missing:
                self._run_stage(stage)

        try:
            result = self.q_out.get_nowait()
        except queue.Empty:
            raise RuntimeError("the batch pipeline ended without a result")
        if isinstance(result, StageFailure):
            try:
                from src.utils.logger import log_error
                log_error(ticker="-", date=datetime.now().strftime("%Y-%m-%d"),
                          error=str(result.error), stage=f"batch_pipeline_{result.stage}",
                          context={"batch_no": self.batch_no})
            except Exception:
                pass
            raise result.error
        return result