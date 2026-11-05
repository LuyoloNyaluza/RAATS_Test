"""
src/agents/main_agent.py

The RAATS main agent, built like the newsletter editor in the example:

    agent = create_deep_agent(model=..., tools=[...], system_prompt=MAIN_PROMPT,
                              subagents=SUBAGENTS, permissions=main_permissions)

It prepares the batches: it delegates each candidate to the subagents with the task tool (in
parallel), collects what they return into final INVEST, and completes the batch. It does NOT
trade. Positions are opened, managed and closed by the position engine (live_agents.py) on its
own loop, which is the only holder of the MT5 write authority. That loop never depends on this
agent: if the model stalls, open positions are still monitored and their SL/TP still updated.

The Orchestrator below decides WHEN the agent is run (the pause / resume rule) and falls back
to the built-in threaded pipeline if the agent keeps failing, so a model problem cannot stop
discovery.
"""

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.agents.models import AGENT_MODEL
from src.agents.permissions import main_permissions
from src.agents.subagents import SUBAGENTS, validate_subagents
from src.agents.tools import runtime
from src.agents.tools.main_tools import (batch_status, complete_batch, next_candidates,
                                         notify_discord, positions_status)

MAIN_PROMPT = """You are the main agent of RAATS, an automated trading system. You prepare candidates
in batches. You never trade: a separate position engine opens, manages and closes positions, and
only from the candidates that reach final INVEST (never more than 10).

Keep a to-do list with write_todos while you work.

Your job each time you are run:
1. Call batch_status.
2. If no batch is active, delegate to the discovery subagent using the task tool to load the
   candidate pool for the next batch (give it the batch number and the folder /candidates/<batch>/).
3. Repeat until the batch is complete:
   a. Call next_candidates. It returns the tickers that still fit in final INVEST.
   b. For EACH returned ticker, delegate to the scoring subagent using the task tool - fire them
      off in parallel. Tell each one which single ticker to score, the batch number, and which
      assigned folder to use (/scored/<batch>/), and ask for one short result.
   c. For EACH ticker that was scored, delegate to the analysis subagent the same way, with the
      folder /analysis/<batch>/.
   d. If batch_status shows reserve_needed, delegate to the discovery subagent to load the reserve.
   e. Call complete_batch. If it says the batch is complete, stop. Otherwise go back to (a).
4. Collect the returned results. Do NOT score or analyse tickers yourself, do NOT invent tickers,
   and only delegate to the discovery, scoring and analysis subagents. complete_batch is the only
   judge of whether a batch is complete; fewer than 10 approved candidates is fine when the
   candidates are used up.
5. When the batch is complete, write_file a short report to /reports/batch_<batch>.md (candidates
   approved, with BUY or SELL side and confidence), then reply with one short line: the batch
   number and how many candidates are in final INVEST."""

main_tools = [batch_status, next_candidates, complete_batch, positions_status, notify_discord]


def dynamic_subagents_enabled() -> bool:
    return os.environ.get("RAATS_DYNAMIC_SUBAGENTS", "").strip().lower() in ("1", "true", "yes")


def _middleware() -> List[Any]:
    """Planning (write_todos) is opt-in, so it is added here. The code interpreter for dynamic
    subagents (beta; pip install "deepagents[quickjs]", Python 3.11+) is added only when asked."""
    middleware: List[Any] = []
    try:
        from langchain.agents.middleware import TodoListMiddleware
        middleware.append(TodoListMiddleware())
    except ImportError:
        pass
    if dynamic_subagents_enabled():
        from langchain_quickjs import CodeInterpreterMiddleware
        middleware.append(CodeInterpreterMiddleware())
    return middleware


def build_main_agent() -> Any:
    """The main agent, with its subagents listed (needs: pip install deepagents langchain-ollama)."""
    from deepagents import create_deep_agent        # imported here so the rest works without it
    validate_subagents()
    return create_deep_agent(
        model=AGENT_MODEL,
        tools=main_tools,
        system_prompt=MAIN_PROMPT,
        subagents=SUBAGENTS,
        middleware=_middleware(),
        permissions=main_permissions,
        name="raats-main",
    )


def save_reports(result: Any, report_dir: Optional[str] = None) -> List[str]:
    """Trusted host code reads the finished files out of result["files"] (the agent's virtual
    filesystem is state-backed, not on disk) and keeps the reports."""
    out: List[str] = []
    files = (result or {}).get("files", {}) if isinstance(result, dict) else {}
    folder = Path(report_dir or os.environ.get("RAATS_REPORT_DIR", "data/reports"))
    for path, data in files.items():
        if not str(path).startswith("/reports/"):
            continue
        content = data.get("content") if isinstance(data, dict) else data
        if isinstance(content, (list, tuple)):
            content = "\n".join(str(x) for x in content)
        if not content:
            continue
        target = folder / Path(path).name
        try:
            folder.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
            out.append(str(target))
        except OSError as exc:
            print(f"[orchestrator] could not save {target}: {exc}")
    return out


class Orchestrator(threading.Thread):
    """Runs the main agent when a batch should be prepared; applies pause / resume."""

    def __init__(
        self,
        agent: Any,
        subs: Any,
        engine: Any,
        alert: Callable[[str], None] = print,
        note: Callable[[str, Dict[str, Any]], None] = lambda kind, data: None,
        fallback: Optional[Callable[[], None]] = None,
        poll_sec: float = 5.0,
        max_failures: int = 2,
        recursion_limit: int = 1000,
    ):
        super().__init__(name="raats-orchestrator", daemon=True)
        self.agent, self.subs, self.engine = agent, subs, engine
        self.alert, self.note, self.fallback = alert, note, fallback
        self.poll_sec, self.max_failures, self.recursion_limit = poll_sec, max_failures, recursion_limit
        self.failures = 0
        self.fell_back = False
        self.runs = 0
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _progress_marker(self) -> tuple:
        st = self.subs
        return (st.batch_no, len(st.batch_queue), st.inflight(), len(st.pool), len(st.completed),
                st.reserve_used, st._exhausted_until)

    def step(self) -> str:
        """One decision: paused, waiting, ran, or failed."""
        subs, pool = self.subs, self.subs.pool
        if pool.full() and self.engine.open_count() >= self.engine.max_positions:
            if not subs.paused:
                subs.paused = True
                print("\n[orchestrator] paused: open positions 10 and final INVEST 10")
                self.note("subagents_paused", {})
            return "paused"
        if subs.paused:
            subs.paused = False
            print("\n[orchestrator] resumed")
            self.note("subagents_resumed", {})
        if time.time() < subs._exhausted_until:
            return "waiting"
        if not subs.batch_active and pool.free() <= 0:
            return "waiting"

        before = self._progress_marker()
        try:
            # "workflow" is the cue that makes the code interpreter dispatch the subagents by
            # script; it is only used when dynamic subagents are switched on.
            word = "workflow" if dynamic_subagents_enabled() else "batch"
            result = self.agent.invoke(
                {"messages": [{"role": "user", "content":
                               f"Run the {word} for batch {subs.batch_no}. "
                               f"Current state: {subs.status()}"}]},
                config={"recursion_limit": self.recursion_limit},
            )
            self.runs += 1
            saved = save_reports(result)
            if saved:
                print(f"[orchestrator] report saved: {saved}")
        except Exception as exc:
            return self._failed(f"{type(exc).__name__}: {exc}")

        waiting_for_new_tickers = time.time() < subs._exhausted_until
        if self._progress_marker() == before and not waiting_for_new_tickers:
            return self._failed("the main agent made no progress")
        self.failures = 0
        return "ran"

    def _failed(self, why: str) -> str:
        self.failures += 1
        print(f"\n[orchestrator] main agent problem ({self.failures}/{self.max_failures}): {why}")
        if self.failures >= self.max_failures and not self.fell_back:
            self.fell_back = True
            self.alert("The deep main agent keeps failing - switching to the built-in pipeline "
                       f"for discovery, scoring and analysis. Last problem: {why}")
            if self.fallback is not None:
                self.fallback()
            self.stop()
        return "failed"

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                outcome = self.step()
            except Exception as exc:
                outcome = "failed"
                print(f"[orchestrator] error: {exc}")
            if outcome != "ran":
                self._stop_event.wait(self.poll_sec)


def start_orchestration(manager: Any, pool: Any, seen: Any, discovery: Any, subs: Any,
                        engine: Any, analyze_fn: Callable, alert: Callable[[str], None],
                        note: Callable[[str, Dict[str, Any]], None]) -> Orchestrator:
    """Bind the runtime, build the main agent with its subagents, and start running batches.

    Raises ImportError (deepagents / model package missing) so the caller can fall back.
    """
    runtime.bind(manager=manager, pool=pool, seen=seen, discovery=discovery, subs=subs,
                 engine=engine, analyze_fn=analyze_fn)
    agent = build_main_agent()
    orch = Orchestrator(agent, subs, engine, alert=alert, note=note, fallback=subs.start)
    orch.start()
    return orch
