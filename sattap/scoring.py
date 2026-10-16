"""Distance-based scoring."""
from __future__ import annotations

import math

from . import config as C
from .geo import haversine_km


def score_for_distance(
    distance_km: float,
    scale_km: float = C.SCORE_SCALE_KM,
    free_km: float = C.SCORE_FREE_KM,
) -> int:
    """100 inside the free radius, then exponential decay with distance beyond it."""
    over = max(distance_km - free_km, 0.0)
    return int(round(100.0 * math.exp(-over / scale_km)))


def score_guess(
    guess_lon: float, guess_lat: float, ans_lon: float, ans_lat: float, hint_used: bool = False
) -> tuple[float, int]:
    d = float(haversine_km(guess_lon, guess_lat, ans_lon, ans_lat))
    score = score_for_distance(d)
    if hint_used:
        score = int(round(score * C.HINT_SCORE_MULT))
    return d, score
