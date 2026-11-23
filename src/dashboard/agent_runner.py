"""Start / stop the live agent as a child process and keep its console output."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional, Tuple

from .events import ROOT

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STOP_FILE = Path(os.environ.get("RAATS_STOP_FILE", "data/STOP"))
AGENT_MODULE = os.environ.get("RAATS_DASH_AGENT_MODULE", "src.agents.live_agents")


def _stop_path() -> Path:
    return STOP_FILE if STOP_FILE.is_absolute() else ROOT / STOP_FILE


class AgentRunner:
    def __init__(self, max_lines: int = 3000):
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._lines: Deque[Tuple[int, str]] = deque(maxlen=max_lines)
        self._next = 0
        self.started_at: Optional[float] = None
        self.stopping = False

    # ---- state
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def status(self) -> dict:
        proc = self._proc
        running = proc is not None and proc.poll() is None
        state = "stopping" if (running and self.stopping) else "running" if running else "ready"
        return {"state": state, "pid": proc.pid if proc is not None and running else None,
            "started_at": self.started_at, "exit_code": None if running or proc is None else proc.returncode}

    # ---- console
    def _add(self, text: str) -> None:
        with self._lock:
            self._lines.append((self._next, ANSI.sub("", text.rstrip("\r\n"))))
            self._next += 1

    def lines_after(self, last_id: int) -> List[Tuple[int, str]]:
        with self._lock:
            return [(i, t) for i, t in self._lines if i > last_id]

    def _pump(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            self._add(line)
        code = proc.wait()
        if self.stopping:
            try:
                _stop_path().unlink()          # a leftover STOP file would stop the next terminal run at once
            except FileNotFoundError:
                pass
        self._add(f"[dashboard] agent exited with code {code}")

    # ---- control
    def start(self) -> dict:
        if self.running():
            return {"ok": False, "message": "The agent is already running."}
        try:
            _stop_path().unlink()
        except FileNotFoundError:
            pass
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-m", AGENT_MODULE], cwd=str(ROOT), env=env, creationflags=flags,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1)
        self.started_at, self.stopping = time.time(), False
        self._add(f"[dashboard] started {AGENT_MODULE} (pid {self._proc.pid})")
        threading.Thread(target=self._pump, args=(self._proc,), daemon=True).start()
        return {"ok": True, "message": "Agent started."}

    def stop(self) -> dict:
        """First press: graceful (the STOP file; the agent leaves open positions on MT5).
        Second press while still stopping: terminate the process (e.g. stuck in discovery)."""
        if not self.running():
            return {"ok": False, "message": "The agent is not running."}
        if self.stopping:
            assert self._proc is not None
            self._proc.terminate()
            self._add("[dashboard] agent terminated; open MT5 positions keep their SL/TP")
            return {"ok": True, "message": "Agent terminated."}
        path = _stop_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stop requested from the dashboard\n", encoding="utf-8")
        self.stopping = True
        self._add("[dashboard] stop requested; open positions are kept. Press Stop again to force.")
        return {"ok": True, "message": "Stop requested."}


RUNNER = AgentRunner()
