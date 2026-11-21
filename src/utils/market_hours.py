# src/utils/market_hours.py

import os
import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


NYSE_TZ = ZoneInfo("America/New_York")
TOKYO_TZ = ZoneInfo("Asia/Tokyo")
LONDON_TZ = ZoneInfo("Europe/London")
JOHANNESBURG_TZ = ZoneInfo("Africa/Johannesburg")
BERLIN_TZ = ZoneInfo("Europe/Berlin")
HONGKONG_TZ = ZoneInfo("Asia/Hong_Kong")
SYDNEY_TZ = ZoneInfo("Australia/Sydney")


def _is_market_open_in_zone(
    now: datetime,
    open_hour: int,
    open_minute: int,
    close_hour: int,
    close_minute: int,
) -> bool:
    if now.weekday() >= 5:
        return False

    market_open = now.replace(hour=open_hour, minute=open_minute, second=0, microsecond=0)
    market_close = now.replace(hour=close_hour, minute=close_minute, second=0, microsecond=0)
    return market_open <= now <= market_close


def is_market_open() -> bool:
    """Check whether at least one major stock market is currently open."""

    now_et = datetime.now(NYSE_TZ)
    now_at = datetime.now(TOKYO_TZ)
    now_uk = datetime.now(LONDON_TZ)

    # US: NYSE / NASDAQ (09:30-16:00 New York time)
    if _is_market_open_in_zone(now_et, 9, 30, 16, 0):
        return True

    # Asia: Tokyo Stock Exchange
    # Morning session: 09:00-11:30 JST, afternoon session: 12:30-15:30 JST
    if (
        _is_market_open_in_zone(now_at, 9, 0, 11, 30)
        or _is_market_open_in_zone(now_at, 12, 30, 15, 30)
    ):
        return True

    # Europe: London Stock Exchange (08:00-16:30 London time)
    if _is_market_open_in_zone(now_uk, 8, 0, 16, 30):
        return True

    return False


# ----------------------------------------------------------------------------------------
# PER-TICKER CHECK
#
# Tickers are Yahoo-style: AAPL (US), VOD.L (London), 7203.T (Tokyo), EURUSD=X (currency),
# GC=F (futures), BTC-USD (crypto). The check is a first, cheap screen on regular exchange
# hours; it knows no holidays. The broker's own order_check stays the final word, so a
# holiday is still caught there. RAATS_MARKET_HOURS_CHECK=0 switches this screen off.
# ----------------------------------------------------------------------------------------
_EXCHANGE_SESSIONS = {
    ".L": (LONDON_TZ, ((8, 0, 16, 30),)),
    ".T": (TOKYO_TZ, ((9, 0, 11, 30), (12, 30, 15, 30))),
    ".JO": (JOHANNESBURG_TZ, ((9, 0, 17, 0),)),
    ".DE": (BERLIN_TZ, ((9, 0, 17, 30),)),
    ".F": (BERLIN_TZ, ((9, 0, 17, 30),)),
    ".PA": (BERLIN_TZ, ((9, 0, 17, 30),)),
    ".AS": (BERLIN_TZ, ((9, 0, 17, 30),)),
    ".TO": (NYSE_TZ, ((9, 30, 16, 0),)),
    ".V": (NYSE_TZ, ((9, 30, 16, 0),)),
    ".HK": (HONGKONG_TZ, ((9, 30, 12, 0), (13, 0, 16, 0))),
    ".AX": (SYDNEY_TZ, ((10, 0, 16, 0),)),
}
_US_SESSION = ((9, 30, 16, 0),)
_CRYPTO_RE = re.compile(r"^[A-Z0-9]{2,10}-(USD|USDT|USDC|EUR|GBP|BTC|ETH)$")
_US_RE = re.compile(r"^[A-Z]{1,5}([.-][A-Z])?$")


def _check_enabled() -> bool:
    return os.environ.get("RAATS_MARKET_HOURS_CHECK", "1").strip().lower() not in (
        "0", "false", "no", "off")


def _in_sessions(now: datetime, sessions) -> bool:
    return any(_is_market_open_in_zone(now, *s) for s in sessions)


def _forex_open(now_et: datetime) -> bool:
    """Sunday 17:00 ET to Friday 17:00 ET."""
    wd, hour = now_et.weekday(), now_et.hour
    if wd == 5:
        return False
    if wd == 6:
        return hour >= 17
    if wd == 4:
        return hour < 17
    return True


def _futures_open(now_et: datetime) -> bool:
    """CME-style: Sunday 18:00 ET to Friday 17:00 ET, daily break 17:00-18:00 ET."""
    wd, hour = now_et.weekday(), now_et.hour
    if wd == 5:
        return False
    if wd == 6:
        return hour >= 18
    if wd == 4:
        return hour < 17
    return hour != 17


def market_open_for(ticker: str, now: Optional[datetime] = None) -> Optional[bool]:
    """True / False when the ticker's regular market hours are known, None when they are not
    (an index, an unknown exchange suffix): the caller then relies on the broker's check."""
    t = str(ticker or "").upper().strip()
    if not t:
        return None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if t.endswith("=X"):
        return _forex_open(now.astimezone(NYSE_TZ))
    if t.endswith("=F"):
        return _futures_open(now.astimezone(NYSE_TZ))
    if _CRYPTO_RE.match(t):
        return True
    if t.startswith("^"):
        return None
    for suffix, (tz, sessions) in _EXCHANGE_SESSIONS.items():
        if t.endswith(suffix):
            return _in_sessions(now.astimezone(tz), sessions)
    if _US_RE.match(t):
        return _in_sessions(now.astimezone(NYSE_TZ), _US_SESSION)
    return None


def is_ticker_market_open(ticker: str, now: Optional[datetime] = None, unknown: bool = True) -> bool:
    """Is this ticker's market open now? `unknown` is the answer when its hours are not known."""
    if not _check_enabled():
        return True
    state = market_open_for(ticker, now)
    return unknown if state is None else state
