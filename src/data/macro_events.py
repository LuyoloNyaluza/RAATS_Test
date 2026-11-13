"""
MacroEventChecker: Blocks trade entries during high-impact macro events.
Checks FOMC, CPI, NFP, earnings dates via API or static calendar.
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path

import requests
import pandas as pd

logger = logging.getLogger("raats.data.macro_events")

# Default high-impact events (can be overridden by API)
DEFAULT_HIGH_IMPACT_EVENTS = {
    "FOMC": {"window_minutes": 30, "impact": "HIGH"},
    "CPI": {"window_minutes": 30, "impact": "HIGH"},
    "NFP": {"window_minutes": 30, "impact": "HIGH"},
    "PCE": {"window_minutes": 30, "impact": "HIGH"},
    "ISM_MANUFACTURING": {"window_minutes": 30, "impact": "MEDIUM"},
    "ISM_SERVICES": {"window_minutes": 30, "impact": "MEDIUM"},
    "RETAIL_SALES": {"window_minutes": 30, "impact": "MEDIUM"},
    "UNEMPLOYMENT_CLAIMS": {"window_minutes": 15, "impact": "MEDIUM"},
    "GDP": {"window_minutes": 30, "impact": "HIGH"},
    "FED_SPEECH": {"window_minutes": 15, "impact": "LOW"},
    # outside the US: central banks and the China data that move currencies and risk
    "ECB_RATE": {"window_minutes": 30, "impact": "HIGH"},
    "BOE_RATE": {"window_minutes": 30, "impact": "HIGH"},
    "BOC_RATE": {"window_minutes": 30, "impact": "HIGH"},
    "CN_GDP": {"window_minutes": 30, "impact": "HIGH"},
    "CN_CPI": {"window_minutes": 30, "impact": "MEDIUM"},
    "CN_PMI": {"window_minutes": 30, "impact": "MEDIUM"},
    "CN_LPR": {"window_minutes": 30, "impact": "MEDIUM"},
}

# Regions whose releases legitimately fall on a weekend (China's NBS publishes CPI/PMI on Saturdays
# and Sundays); every other region on a weekend is a calendar typo.
WEEKEND_OK_REGIONS = {"CN"}

# Static fallback calendar (update quarterly)
STATIC_CALENDAR_PATH = Path(__file__).parent / "macro_calendar.json"


@dataclass
class MacroEvent:
    name: str
    event_type: str
    scheduled_time: str  # ISO format string
    impact: str
    window_minutes: int
    actual_value: Optional[str] = None
    forecast_value: Optional[str] = None
    previous_value: Optional[str] = None
    region: str = "US"                         # US | EU | UK | CA | CN ...
    currencies: List[str] = field(default_factory=list)   # currencies the event moves
    global_risk: bool = False                  # moves every market (Fed, ECB, US CPI/NFP): blocks all
    confirmed: bool = True                     # False = indicative / rule-based date
    source: str = ""
    local_time: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "MacroEvent":
        """Tolerates keys this version does not know (a newer calendar file)."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def applies_to(self, currencies: Optional[Set[str]]) -> bool:
        """Does this event block an asset that trades in `currencies`?

        Unknown asset currencies, a global-risk event, or an event with no currency list
        (API events) block everything; otherwise only a matching currency blocks."""
        if not currencies or self.global_risk or not self.currencies:
            return True
        return bool(set(self.currencies) & set(currencies))

    @property
    def dt(self) -> datetime:
        return datetime.fromisoformat(self.scheduled_time.replace("Z", "+00:00"))
    
    def to_dict(self) -> dict:
        return asdict(self)


class MacroEventChecker:
    """
    Checks if current time falls within a high-impact macro event window.
    Blocks trade entry 30 min before and after FOMC, CPI, NFP, etc.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        calendar_path: Optional[Path] = None,
        enabled: bool = True,
        default_window_minutes: int = 30,
    ):
        self.enabled = enabled
        self.default_window_minutes = default_window_minutes
        self.calendar_path = calendar_path or STATIC_CALENDAR_PATH
        # API results go to a SEPARATE cache file. They used to overwrite the
        # hand-maintained static calendar on every successful API call.
        self.cache_path = Path(self.calendar_path).with_name("macro_calendar_api_cache.json")
        self.api_key = api_key or os.environ.get("RAATS_MACRO_API_KEY")
        self._events_cache: List[MacroEvent] = []
        self._last_fetch: Optional[datetime] = None
        self._cache_ttl = timedelta(hours=6)
        
    def load_calendar(self) -> List[MacroEvent]:
        """Load events from static JSON or API."""
        events = []
        
        # Try API first if key available
        if self.api_key:
            try:
                events = self._fetch_from_api()
                if events:
                    self._cache_events(events)
                    return events
            except Exception as e:
                logger.warning(f"Macro API failed, falling back to static: {e}")
        
        # Fall back to static calendar
        if self.calendar_path.exists():
            try:
                with open(self.calendar_path) as f:
                    data = json.load(f)
                events = [MacroEvent.from_dict(e) for e in data.get("events", [])]
                logger.info(f"Loaded {len(events)} macro events from static calendar")
                self._warn_on_weekend_events(events)
                return events
            except Exception as e:
                logger.error(f"Failed to load static calendar: {e}")
        
        # Then the last good API download, if any
        if self.cache_path.exists():
            try:
                with open(self.cache_path, encoding="utf-8") as f:
                    events = [MacroEvent.from_dict(e) for e in json.load(f).get("events", [])]
                logger.info(f"Loaded {len(events)} macro events from API cache")
                return events
            except Exception as e:
                logger.error(f"Failed to load API cache: {e}")

        # Last resort: empty list
        logger.warning("No macro calendar available - event blocking disabled")
        return []
    
    @staticmethod
    def _warn_on_weekend_events(events: List[MacroEvent]) -> None:
        """US macro releases never fall on a weekend - a date that does is a typo."""
        bad = [f"{e.event_type} {e.scheduled_time[:10]}" for e in events
               if e.dt.weekday() >= 5 and e.region not in WEEKEND_OK_REGIONS]
        if bad:
            logger.warning("macro calendar has %d event(s) on a weekend - check them: %s", len(bad), bad)

    def _fetch_from_api(self) -> List[MacroEvent]:
        """Fetch from economic calendar API (e.g., TradingEconomics, Alpha Vantage)."""
        # Example: Trading Economics API
        url = "https://api.tradingeconomics.com/calendar"
        params = {
            "c": self.api_key,
            "format": "json",
            "importance": "high,medium",
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        events = []
        for item in data:
            try:
                event_time = datetime.fromisoformat(item["DateTime"].replace("Z", "+00:00"))
                event_type = item.get("Category", "UNKNOWN")
                impact = item.get("Importance", "MEDIUM").upper()
                window = DEFAULT_HIGH_IMPACT_EVENTS.get(event_type, {}).get("window_minutes", 30)
                
                events.append(MacroEvent(
                    name=item.get("Event", event_type),
                    event_type=event_type,
                    scheduled_time=event_time.isoformat(),
                    impact=impact,
                    window_minutes=window,
                    actual_value=item.get("Actual"),
                    forecast_value=item.get("Forecast"),
                    previous_value=item.get("Previous"),
                ))
            except Exception as e:
                logger.debug(f"Skipping event parse error: {e}")
                continue
        return events
    
    def _cache_events(self, events: List[MacroEvent]) -> None:
        """Cache events to disk for offline use."""
        try:
            data = {"events": [e.to_dict() for e in events]}
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to cache calendar: {e}")
    
    def refresh_if_needed(self) -> None:
        """Refresh cache if stale."""
        if self._last_fetch is None or datetime.now() - self._last_fetch > self._cache_ttl:
            self._events_cache = self.load_calendar()
            self._last_fetch = datetime.now()
    
    def is_event_window_active(
        self,
        check_time: Optional[datetime] = None,
        event_types: Optional[Set[str]] = None,
        min_impact: str = "MEDIUM",
        currencies: Optional[Set[str]] = None,
    ) -> Optional[MacroEvent]:
        """
        Check if any high-impact event window is active at check_time.
        
        Returns the blocking event if active, None otherwise.
        """
        if not self.enabled:
            return None
            
        self.refresh_if_needed()
        if check_time is None:
            check_time = datetime.now(timezone.utc)
        # Event times are timezone-aware. A naive check_time (e.g. pd.Timestamp("2026-06-01")
        # from a simulated date) used to raise TypeError on the first comparison.
        if isinstance(check_time, pd.Timestamp):
            check_time = check_time.to_pydatetime()
        if check_time.tzinfo is None:
            check_time = check_time.replace(tzinfo=timezone.utc)
        
        impact_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        min_level = impact_order.get(min_impact.upper(), 1)
        
        for event in self._events_cache:
            if event_types and event.event_type not in event_types:
                continue
            if impact_order.get(event.impact, 1) < min_level:
                continue
            if not event.applies_to(currencies):
                continue

            event_time = event.dt
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
            window_start = event_time - timedelta(minutes=event.window_minutes)
            window_end = event_time + timedelta(minutes=event.window_minutes)
            
            if window_start <= check_time <= window_end:
                logger.warning(
                    f"BLOCKED: {event.name} ({event.event_type}) window active "
                    f"[{window_start} - {window_end}], impact={event.impact}"
                )
                return event
                
        return None
    
    def status(self, horizon_days: int = 14) -> Dict[str, object]:
        """Is the calendar usable? loaded / count / next event / last event / ok + a reason.

        ok is False when no calendar is loaded or it holds nothing in the next `horizon_days`
        (an empty or expired calendar silently disables the event block)."""
        self.refresh_if_needed()
        now = datetime.now(timezone.utc)
        future = sorted((e for e in self._events_cache if e.dt >= now), key=lambda e: e.dt)
        out: Dict[str, object] = {
            "loaded": bool(self._events_cache), "count": len(self._events_cache),
            "upcoming": len(future),
            "next": f"{future[0].name} {future[0].scheduled_time}" if future else None,
            "last": max((e.scheduled_time for e in self._events_cache), default=None),
            "unconfirmed_upcoming": sum(1 for e in future if not e.confirmed),
        }
        if not self._events_cache:
            out.update(ok=False, reason="no macro calendar loaded - event blocking is OFF")
        elif not future or (future[-1].dt - now).days < horizon_days:
            out.update(ok=False, reason=f"the macro calendar ends {out['last']} - update macro_calendar.json")
        else:
            out.update(ok=True, reason="ok")
        return out

    def get_upcoming_events(self, hours: int = 24) -> List[MacroEvent]:
        """Get events in the next N hours."""
        self.refresh_if_needed()
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours)
        return [e for e in self._events_cache if now <= e.dt <= cutoff]


# Convenience function for quick checks
# Yahoo suffix -> trading currencies (stocks listed outside the US)
_SUFFIX_CURRENCIES = {
    ".L": ["GBP"], ".TO": ["CAD"], ".V": ["CAD"], ".DE": ["EUR"], ".PA": ["EUR"], ".AS": ["EUR"],
    ".MI": ["EUR"], ".MC": ["EUR"], ".BR": ["EUR"], ".HK": ["HKD", "CNY"], ".SS": ["CNY"],
    ".SZ": ["CNY"], ".T": ["JPY"], ".AX": ["AUD"],
}
_INDEX_CURRENCIES = {
    "^GSPC": ["USD"], "^DJI": ["USD"], "^IXIC": ["USD"], "^RUT": ["USD"], "^FTSE": ["GBP"],
    "^GDAXI": ["EUR"], "^FCHI": ["EUR"], "^STOXX50E": ["EUR"], "^IBEX": ["EUR"], "^AEX": ["EUR"],
    "^N225": ["JPY"], "^HSI": ["HKD", "CNY"], "^AXJO": ["AUD"], "^BSESN": ["INR"], "^NSEI": ["INR"],
    "^KS11": ["KRW"], "^TWII": ["TWD"],
}
_COMMODITY_CURRENCIES = {"GC=F": ["USD"], "SI=F": ["USD"], "CL=F": ["USD"], "NG=F": ["USD"],
                         "HG=F": ["USD", "CNY"]}


def asset_currencies(ticker: str) -> Set[str]:
    """Currencies whose events move this Yahoo ticker: EURUSD=X -> {EUR, USD}, ^GDAXI -> {EUR},
    NKE -> {USD}. An unknown form returns {USD} (a plain US-listed stock)."""
    t = (ticker or "").upper().strip()
    if t.endswith("=X") and len(t) == 8:                 # EURUSD=X
        return {t[:3], t[3:6]}
    if t in _INDEX_CURRENCIES:
        return set(_INDEX_CURRENCIES[t])
    if t in _COMMODITY_CURRENCIES:
        return set(_COMMODITY_CURRENCIES[t])
    for suffix, cur in _SUFFIX_CURRENCIES.items():
        if t.endswith(suffix):
            return set(cur)
    return {"USD"}


def is_trade_blocked_by_macro(
    check_time: Optional[datetime] = None,
    min_impact: str = "MEDIUM",
    currencies: Optional[Set[str]] = None,
) -> bool:
    """Quick check - returns True if trade should be blocked."""
    checker = MacroEventChecker()
    return checker.is_event_window_active(
        check_time, min_impact=min_impact, currencies=currencies) is not None