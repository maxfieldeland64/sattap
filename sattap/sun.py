"""Solar elevation (NOAA low-precision formulas, good to a fraction of a degree)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np


def solar_elevation_deg(lat, lon, when: datetime):
    """Sun elevation above the horizon in degrees. lat/lon in degrees, arrays or scalars."""
    when = when.astimezone(timezone.utc)
    day = when.timetuple().tm_yday
    hour = when.hour + when.minute / 60 + when.second / 3600
    g = 2 * np.pi / 365 * (day - 1 + (hour - 12) / 24)
    decl = (
        0.006918
        - 0.399912 * np.cos(g)
        + 0.070257 * np.sin(g)
        - 0.006758 * np.cos(2 * g)
        + 0.000907 * np.sin(2 * g)
        - 0.002697 * np.cos(3 * g)
        + 0.00148 * np.sin(3 * g)
    )
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * np.cos(g)
        - 0.032077 * np.sin(g)
        - 0.014615 * np.cos(2 * g)
        - 0.040849 * np.sin(2 * g)
    )
    tst = hour * 60 + eqtime + 4 * np.asarray(lon, dtype=float)  # true solar time, minutes
    ha = np.radians(tst / 4 - 180)
    lat_r = np.radians(np.asarray(lat, dtype=float))
    sin_el = np.sin(lat_r) * np.sin(decl) + np.cos(lat_r) * np.cos(decl) * np.cos(ha)
    return np.degrees(np.arcsin(np.clip(sin_el, -1, 1)))


def latest_solar_noon(lon: float, now: datetime) -> datetime:
    """The most recent local solar noon (UTC) at `lon` that is not after `now`.

    Mean solar time, ignoring the equation of time (up to ~16 minutes), which is plenty here.
    """
    now = now.astimezone(timezone.utc)
    noon = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=12 - lon / 15.0)
    while noon > now:
        noon -= timedelta(days=1)
    while noon + timedelta(days=1) <= now:
        noon += timedelta(days=1)
    return noon
