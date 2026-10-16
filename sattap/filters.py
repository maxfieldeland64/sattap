"""Playability filter and difficulty heuristic for candidate crops."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime

import numpy as np
from global_land_mask import globe
from PIL import Image

from . import config as C
from .crops import Crop, lonlat_grid
from .geo import FullDiskGrid
from .sun import solar_elevation_deg


@dataclass
class Stats:
    luma: float
    luma_std: float
    cloud_frac: float
    land_frac: float
    coastness: float  # 1.0 when ~50% land, 0 when all land or all water
    min_sun_elev: float  # degrees; low values mean the crop touches the terminator
    difficulty: float  # 0 (easy) .. 1 (hard)

    def as_dict(self) -> dict:
        return {k: round(v, 3) for k, v in asdict(self).items()}


def land_fraction(grid: FullDiskGrid, crop: Crop) -> float:
    lon, lat = lonlat_grid(grid, crop)
    ok = np.isfinite(lon) & np.isfinite(lat)
    if not ok.any():
        return float("nan")
    return float(globe.is_land(lat[ok], lon[ok]).mean())


def min_sun_elevation(grid: FullDiskGrid, crop: Crop, when: datetime) -> float:
    lon, lat = lonlat_grid(grid, crop)
    ok = np.isfinite(lon) & np.isfinite(lat)
    if not ok.any():
        return float("-inf")
    return float(solar_elevation_deg(lat[ok], lon[ok], when).min())


def compute_stats(grid: FullDiskGrid, crop: Crop, tile: Image.Image, observed_at: datetime) -> Stats:
    small = np.asarray(tile.convert("RGB").resize((64, 64), Image.BILINEAR), dtype=float)
    r, g, b = small[..., 0], small[..., 1], small[..., 2]
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    spread = small.max(axis=-1) - small.min(axis=-1)
    cloud = (luma > C.CLOUD_MIN_LUMA) & (spread < C.CLOUD_MAX_SPREAD)
    cloud_frac = float(cloud.mean())
    land = land_fraction(grid, crop)
    coast = 1.0 - abs(2.0 * land - 1.0) if np.isfinite(land) else 0.0
    difficulty = float(np.clip(0.6 * cloud_frac + 0.4 * (1.0 - coast), 0.0, 1.0))
    sun = min_sun_elevation(grid, crop, observed_at)
    return Stats(float(luma.mean()), float(luma.std()), cloud_frac, land, coast, sun, difficulty)


def is_playable(s: Stats) -> bool:
    return (
        s.min_sun_elev >= C.MIN_SUN_ELEV_DEG
        and s.luma >= C.MIN_LUMA
        and s.luma_std >= C.MIN_LUMA_STD
        and np.isfinite(s.land_frac)
        and C.MIN_LAND_FRAC <= s.land_frac <= C.MAX_LAND_FRAC
        and s.cloud_frac <= C.MAX_CLOUD_FRAC
    )
