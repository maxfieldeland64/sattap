"""Which puzzle is 'today'?

The day rolls over at ROLLOVER_UTC_HOUR (not at midnight UTC), so a US evening does not
fall into a gap where the next puzzle has not been built yet.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import config as C


def game_day(now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(hours=C.ROLLOVER_UTC_HOUR)).date()
