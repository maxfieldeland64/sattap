"""Distance-based scoring."""
from __future__ import annotations

import math

from . import config as C
from .geo import haversine_km


def score_for_distance(distance_km: float, scale_km: float = C.SCORE_SCALE_KM) -> int:
    return int(round(100.0 * math.exp(-max(distance_km, 0.0) / scale_km)))


def score_guess(guess_lon: float, guess_lat: float, ans_lon: float, ans_lat: float) -> tuple[float, int]:
    d = float(haversine_km(guess_lon, guess_lat, ans_lon, ans_lat))
    return d, score_for_distance(d)
