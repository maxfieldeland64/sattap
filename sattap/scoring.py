"""Distance-based scoring.

Rounding is floor(x + 0.5) rather than Python's round() so the Cloudflare Function
(functions/api/guess.js, Math.round) produces identical scores.
"""
from __future__ import annotations

import math

from . import config as C
from .geo import haversine_km


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def score_for_distance(
    distance_km: float,
    scale_km: float = C.SCORE_SCALE_KM,
    free_km: float = C.SCORE_FREE_KM,
) -> int:
    """100 inside the free radius, then exponential decay with distance beyond it."""
    over = max(distance_km - free_km, 0.0)
    return _round_half_up(100.0 * math.exp(-over / scale_km))


def score_guess(
    guess_lon: float, guess_lat: float, ans_lon: float, ans_lat: float, hint_used: bool = False
) -> tuple[float, int]:
    d = float(haversine_km(guess_lon, guess_lat, ans_lon, ans_lat))
    score = score_for_distance(d)
    if hint_used:
        score = _round_half_up(score * C.HINT_SCORE_MULT)
    return d, score


def scoring_params() -> dict:
    """Published alongside the answers so the Cloudflare Function uses the same numbers."""
    return {
        "free_km": C.SCORE_FREE_KM,
        "scale_km": C.SCORE_SCALE_KM,
        "hint_mult": C.HINT_SCORE_MULT,
        "earth_radius_km": 6371.0088,
    }
