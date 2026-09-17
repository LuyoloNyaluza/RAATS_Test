# src/utils/market_hours.py
from datetime import datetime
from zoneinfo import ZoneInfo

NYSE_TZ = ZoneInfo("America/New_York")


def is_market_open() -> bool:
    """Check if the current time is within NYSE market hours (9:30 AM to 4:00 PM ET) on a weekday."""
    now_et = datetime.now(NYSE_TZ)

    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6 in US Eastern terms
        return False

    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et <= market_close