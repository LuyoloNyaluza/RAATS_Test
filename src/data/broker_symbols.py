"""
src/data/broker_symbols.py

The broker's OWN symbol list (FBS or any other MT5 server), used as the first guardrail:

    discovery      only tickers the broker offers are ever pulled in, ranked, scored and analysed
    live agents    a ticker that is still not found at trade time goes into the ticker memory

WHY A LIST AND NOT GUESSING
---------------------------
Brokers name stocks differently ("AAPL", "AAPL.US", "#GFS", "TSLA_i"). Guessing suffixes
(mt5_bridge.EQUITY_SUFFIXES) misses prefix styles such as "#GFS" and asks the terminal about every
candidate one by one. The catalog reads mt5.symbols_get() ONCE, saves it under data/broker/, and
answers "does the broker offer this Yahoo ticker?" from memory.

* Cached: data/broker/symbols_<server>.json. Refreshed from MT5 when older than
  RAATS_BROKER_CATALOG_HOURS (default 24). If MT5 cannot be reached, the newest cached file is used.
* Changing account or broker needs nothing: the file is per server name, and a new server
  fetches its own list.
* Only FULL trading symbols count (long and short), as everywhere else in RAATS.
* Fails OPEN: no MT5 and no cached file means no filtering (a warning is printed), never a crash.
* Read-only and lock-safe: MT5 is read through mt5_orders.session() (the same lock and reconnect
  logic the Main Agent uses) and is NEVER shut down here.

Settings
--------
RAATS_BROKER_FILTER           0 switches the catalog off (default on)
RAATS_USE_MT5                 0/false/no (paper mode) also switches it off
RAATS_BROKER_CATALOG_HOURS    cache age before a refresh (24)
RAATS_BROKER_DIR              folder for the cache (data/broker)

Command line (run it once to see what your broker offers)
---------------------------------------------------------
    python -m src.data.broker_symbols               refresh and summarise
    python -m src.data.broker_symbols ORKA AAPL     show how each ticker resolves
"""

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("raats.data.broker_symbols")

FULL_TRADE_MODE = 4                  # MT5 SYMBOL_TRADE_MODE_FULL (long and short)
RETRY_SECONDS = 60                   # do not hammer an unreachable terminal
SERVER_CHECK_SECONDS = 300           # how often a running session checks the terminal's account

# Paths that are clearly not shares; a stock ticker is never matched to these by base name.
_NON_EQUITY_PATH = ("forex", "fx", "crypto", "index", "indices", "metal", "energ", "commod",
                    "bond", "future", "currenc")

_LOCK = threading.RLock()
_STATE: Dict[str, Any] = {"catalog": None, "loaded": 0.0, "next_try": 0.0, "server_checked": 0.0}


def _enabled() -> bool:
    if os.environ.get("RAATS_BROKER_FILTER", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    if os.environ.get("RAATS_USE_MT5", "").strip().lower() in ("0", "false", "no"):
        return False                                   # paper mode: no broker to ask
    return True


def _max_age_hours() -> float:
    try:
        return float(os.environ.get("RAATS_BROKER_CATALOG_HOURS", "24"))
    except ValueError:
        return 24.0


def _catalog_dir() -> Path:
    return Path(os.environ.get("RAATS_BROKER_DIR", "data/broker"))


def _base(name: str) -> str:
    """'AAPL.US' -> 'AAPL', '#GFS' -> 'GFS', 'TSLA_i' -> 'TSLA', 'EURUSD' -> 'EURUSD'."""
    text = str(name or "").upper().strip().lstrip("#$")
    return re.split(r"[._\-#/ ]", text, maxsplit=1)[0]


def _is_equity_form(ticker: str) -> bool:
    return ticker.isalpha() and len(ticker) <= 5


class Catalog:
    """The broker's symbols, indexed by exact name and by base name."""

    def __init__(self, symbols: List[Dict[str, Any]], server: str, fetched_at: str):
        self.symbols = symbols
        self.server = server
        self.fetched_at = fetched_at
        self.by_name: Dict[str, Dict[str, Any]] = {}
        self.by_base: Dict[str, List[Dict[str, Any]]] = {}
        for s in symbols:
            name = str(s.get("name", "")).upper()
            if not name:
                continue
            self.by_name[name] = s
            self.by_base.setdefault(_base(name), []).append(s)

    def __len__(self) -> int:
        return len(self.symbols)

    @staticmethod
    def _full(s: Dict[str, Any]) -> bool:
        return int(s.get("trade_mode", 0) or 0) == FULL_TRADE_MODE

    @staticmethod
    def _non_equity(s: Dict[str, Any]) -> bool:
        """The symbol sits under Forex / Metals / Indices / Crypto ... (not a share)."""
        return any(w in str(s.get("path", "")).lower() for w in _NON_EQUITY_PATH)

    def resolve(self, ticker: str) -> Optional[str]:
        """The broker's FULL-trading symbol for a Yahoo ticker, or None if it is not offered."""
        t = str(ticker or "").upper().strip()
        if not t:
            return None
        # 1. the project's own mapping first (static map, RAATS_MT5_SYMBOL_MAP, suffix guesses)
        try:
            from src.data.mt5_bridge import candidates_for
            for name in candidates_for(t):
                s = self.by_name.get(name.upper())
                if s is None or not self._full(s):
                    continue
                if _is_equity_form(t) and self._non_equity(s):
                    continue                    # a share ticker is never a forex/metal symbol
                return str(s["name"])
        except Exception:
            pass
        # 2. a share: match by base name (handles "#GFS", "AAPL.US", "TSLA_i", ...)
        if _is_equity_form(t):
            matches = [s for s in self.by_base.get(t, [])
                       if self._full(s) and not self._non_equity(s)]
            if matches:
                us = [s for s in matches if "us" in re.split(r"[\\/ ._-]", str(s.get("path", "")).lower())]
                return str((us or matches)[0]["name"])
        return None

    def has(self, ticker: str) -> bool:
        return self.resolve(ticker) is not None


# ------------------------------------------------------------------ fetch / cache
def _read_server() -> Optional[str]:
    """The server the terminal is logged in to right now (None if it cannot be read)."""
    try:
        from src.data import mt5_orders
        with mt5_orders.session() as ok:
            mt5 = mt5_orders.mt5
            if not ok or mt5 is None:
                return None
            info = mt5.account_info()
            server = str(getattr(info, "server", "") or "")
            return server or None
    except Exception:
        return None


def current_server() -> Optional[str]:
    """The server of the catalog in use (no terminal call), or None."""
    with _LOCK:
        cat = _STATE["catalog"]
        return cat.server if cat is not None else None


def _fetch_from_mt5() -> Optional[Catalog]:
    """Read the whole symbol list through the order layer's locked, reconnecting session."""
    try:
        from src.data import mt5_orders
    except Exception:
        return None
    try:
        with mt5_orders.session() as ok:
            mt5 = mt5_orders.mt5
            if not ok or mt5 is None:
                return None
            raw = mt5.symbols_get()
            if not raw:
                return None
            info = mt5.account_info()
            server = str(getattr(info, "server", "") or "unknown")
            symbols = [{
                "name": s.name,
                "path": getattr(s, "path", ""),
                "description": getattr(s, "description", ""),
                "trade_mode": int(getattr(s, "trade_mode", 0) or 0),
                "currency_base": getattr(s, "currency_base", ""),
                "currency_profit": getattr(s, "currency_profit", ""),
            } for s in raw]
    except Exception as exc:
        logger.warning("broker symbol list could not be read: %s", exc)
        return None
    return Catalog(symbols, server, datetime.now().isoformat(timespec="seconds"))


def _file_for(server: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", server) or "unknown"
    return _catalog_dir() / f"symbols_{safe}.json"


def _save(cat: Catalog) -> None:
    try:
        path = _file_for(cat.server)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"server": cat.server, "fetched_at": cat.fetched_at,
                   "count": len(cat), "symbols": cat.symbols}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception as exc:
        logger.warning("broker symbol list could not be saved: %s", exc)


def _load_newest_file() -> Optional[Catalog]:
    try:
        files = sorted(_catalog_dir().glob("symbols_*.json"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        if not files:
            return None
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
        symbols = data.get("symbols") or []
        if not symbols:
            return None
        return Catalog(symbols, str(data.get("server", "unknown")), str(data.get("fetched_at", "")))
    except Exception as exc:
        logger.warning("cached broker symbol list could not be read: %s", exc)
        return None


def _age_hours(cat: Catalog) -> float:
    try:
        return (datetime.now() - datetime.fromisoformat(cat.fetched_at)).total_seconds() / 3600.0
    except Exception:
        return 1e9


def get_catalog(refresh: bool = False) -> Optional[Catalog]:
    """The catalog, or None (filter off / no MT5 and no cache). Never raises.

    The module lock is NOT held while MT5 is read: another thread may hold the MT5 lock and
    call back into this module (mt5_bridge.resolve_mt5_symbol), which would deadlock."""
    if not _enabled():
        return None
    now = time.time()
    verify = False
    with _LOCK:
        cat = _STATE["catalog"]
        fresh = cat is not None and _age_hours(cat) < _max_age_hours()
        if fresh and not refresh:
            if now - _STATE["server_checked"] < SERVER_CHECK_SECONDS:
                return cat
            _STATE["server_checked"] = now
            verify = True                                      # has the account changed?
        elif not refresh and now < _STATE["next_try"] and cat is not None:
            return cat                                         # unreachable a moment ago
    if verify and cat is not None:
        live = _read_server()                                  # outside the module lock
        if live is None or live == cat.server:
            return cat
        print(f"[broker] the MT5 account changed ({cat.server} -> {live}): loading its symbol list")
    fetched = _fetch_from_mt5()                                # outside the module lock
    switched = False
    with _LOCK:
        if fetched is not None:
            previous = _STATE["catalog"]
            switched = previous is not None and previous.server != fetched.server
            _save(fetched)
            _STATE.update(catalog=fetched, loaded=time.time(), next_try=0.0,
                          server_checked=time.time())          # just fetched: the server is known
            print(f"[broker] symbol list: {len(fetched)} symbols from {fetched.server}")
    if fetched is not None and switched:
        _reset_symbol_caches()                                 # outside the module lock
    if fetched is not None:
        return fetched
    with _LOCK:
        _STATE["next_try"] = time.time() + RETRY_SECONDS
        if _STATE["catalog"] is not None:
            return _STATE["catalog"]
        cached = _load_newest_file()
        if cached is not None:
            _STATE.update(catalog=cached, loaded=time.time())
            print(f"[broker] MT5 not reachable: using the cached symbol list of {cached.server} "
                  f"({len(cached)} symbols, saved {cached.fetched_at})")
            return cached
        return None


def _reset_symbol_caches() -> None:
    """A broker switch makes every remembered ticker -> symbol answer wrong ("AAPL" -> "AAPL.OLD"):
    forget mt5_bridge's per-session resolutions so they are looked up again on the new server."""
    try:
        from src.data import mt5_bridge
        mt5_bridge._cache.clear()
        mt5_bridge._missing.clear()
    except Exception as exc:
        logger.warning("symbol caches could not be reset: %s", exc)


def accepts(ticker: str) -> bool:
    """Does the broker offer this Yahoo ticker? Fails OPEN (True) when there is no catalog."""
    try:
        cat = get_catalog()
        return True if cat is None else cat.has(ticker)
    except Exception:
        return True


def broker_symbol(ticker: str) -> Optional[str]:
    """The broker's name for a Yahoo ticker, or None (not offered or no catalog)."""
    try:
        cat = get_catalog()
        return None if cat is None else cat.resolve(ticker)
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    catalog = get_catalog(refresh=True)
    if catalog is None:
        print("No symbol list available: is MetaTrader 5 running and logged in?")
        raise SystemExit(1)
    full = sum(1 for s in catalog.symbols if Catalog._full(s))
    print(f"Server {catalog.server}: {len(catalog)} symbols, {full} with full trading "
          f"(saved to {_file_for(catalog.server)})")
    for arg in sys.argv[1:]:
        print(f"  {arg.upper():8s} -> {catalog.resolve(arg) or 'NOT OFFERED'}")