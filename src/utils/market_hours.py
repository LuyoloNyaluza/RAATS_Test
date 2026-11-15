
# src/utils/market_hours.py

from datetime import datetime
from zoneinfo import ZoneInfo


NYSE_TZ = ZoneInfo("America/New_York")
TOKYO_TZ = ZoneInfo("Asia/Tokyo")
LONDON_TZ = ZoneInfo("Europe/London")


def is_market_open() -> bool:
    """Check whether at least one major stock market is currently open."""

    now_et = datetime.now(NYSE_TZ)
    now_at = datetime.now(TOKYO_TZ)
    now_uk = datetime.now(LONDON_TZ)

    def _is_market_open_in_zone(
        now: datetime,
        open_hour: int,
        open_minute: int,
        close_hour: int,
        close_minute: int,
    ) -> bool:
        if now.weekday() >= 5:
            return False

        market_open = now.replace(
            hour=open_hour,
            minute=open_minute,
            second=0,
            microsecond=0,
        )

        market_close = now.replace(
            hour=close_hour,
            minute=close_minute,
            second=0,
            microsecond=0,
        )

        return market_open <= now <= market_close

    # US: NYSE / NASDAQ (09:30–16:00 New York time)
    if _is_market_open_in_zone(now_et, 9, 30, 16, 0):
        return True

    # Asia: Tokyo Stock Exchange
    # Morning session: 09:00–11:30 JST
    # Afternoon session: 12:30–15:30 JST
    if (
        _is_market_open_in_zone(now_at, 9, 0, 11, 30)
        or _is_market_open_in_zone(now_at, 12, 30, 15, 30)
    ):
        return True

    # Europe: London Stock Exchange (08:00–16:30 London time)
    if _is_market_open_in_zone(now_uk, 8, 0, 16, 30):
        return True

    return False
