"""Synthetic GeoColor-like full-disk images for offline development and tests.

Real land/ocean geometry (from global-land-mask) plus procedural clouds, painted
with the same fixed-grid geometry as the real product. Lets you exercise the
whole pipeline without network access.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from global_land_mask import globe
from PIL import Image

from .geo import FullDiskGrid


def _smooth_noise(size: int, rng: np.random.Generator, octaves=((6, 1.0), (16, 0.5), (40, 0.25))) -> np.ndarray:
    total = np.zeros((size, size))
    for cells, amp in octaves:
        small = rng.random((cells, cells)).astype(np.float32)
        big = Image.fromarray((small * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC)
        total += amp * (np.asarray(big, dtype=float) / 255.0)
    total -= total.min()
    return total / total.max()


def make_full_disk(sat_key: str, size: int, out_path: Path, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    grid = FullDiskGrid(sat_key, size)
    cols, rows = np.meshgrid(np.arange(size), np.arange(size))
    lon, lat = grid.pixel_to_lonlat(cols, rows)
    on_disk = np.isfinite(lon) & np.isfinite(lat)
    land = np.zeros((size, size), dtype=bool)
    land[on_disk] = globe.is_land(lat[on_disk], lon[on_disk])

    img = np.zeros((size, size, 3), dtype=float)
    ocean = np.array([12, 42, 77], dtype=float)
    green = np.array([70, 100, 58], dtype=float)
    brown = np.array([128, 108, 74], dtype=float)
    veg = _smooth_noise(size, rng)[..., None]
    land_rgb = green * (1 - veg) + brown * veg
    img[:] = np.where(land[..., None], land_rgb, ocean)

    clouds = _smooth_noise(size, rng, octaves=((5, 1.0), (14, 0.6), (36, 0.3), (90, 0.15)))
    alpha = np.clip((clouds - 0.52) * 4.0, 0, 1)[..., None]
    img = img * (1 - alpha) + np.array([245, 247, 250]) * alpha
    img[~on_disk] = 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img.clip(0, 255).astype(np.uint8)).save(out_path, quality=92)
    return out_path
