"""Sampling candidate crops from a full-disk image and describing them."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from . import config as C
from .geo import FullDiskGrid, haversine_km


@dataclass
class Crop:
    sat_key: str
    col: int  # center pixel
    row: int
    half: int  # half-width in pixels
    lon: float  # center lon/lat = the answer
    lat: float
    width_km: float

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.col - self.half, self.row - self.half, self.col + self.half, self.row + self.half)


def sample_crop(grid: FullDiskGrid, rng: np.random.Generator) -> Crop | None:
    scale = grid.size / C.FD_SIZE_2KM
    half = max(8, int(round(rng.choice(C.CROP_HALF_PX_CHOICES) * scale)))
    lo, hi = half, grid.size - half
    if hi <= lo:
        return None
    for _ in range(200):
        col = int(rng.integers(lo, hi))
        row = int(rng.integers(lo, hi))
        if grid.radial_frac(col, row) > C.MAX_RADIAL_FRAC:
            continue
        corners = [(col + dx, row + dy) for dx in (-half, half) for dy in (-half, half)]
        if any(grid.radial_frac(c, r) > C.MAX_CORNER_FRAC for c, r in corners):
            continue
        lon, lat = grid.pixel_to_lonlat(col, row)
        if np.isnan(lon) or np.isnan(lat):
            continue
        lon_l, lat_l = grid.pixel_to_lonlat(col - half, row)
        lon_r, lat_r = grid.pixel_to_lonlat(col + half, row)
        if np.isnan([lon_l, lat_l, lon_r, lat_r]).any():
            continue
        width_km = float(haversine_km(lon_l, lat_l, lon_r, lat_r))
        return Crop(grid.sat_key, col, row, half, lon, lat, width_km)
    return None


def cut(img: Image.Image, crop: Crop, out_size: int = C.OUT_SIZE_PX) -> Image.Image:
    return img.crop(crop.box).resize((out_size, out_size), Image.LANCZOS)


def lonlat_grid(grid: FullDiskGrid, crop: Crop, n: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """n x n lon/lat samples spread over the crop footprint."""
    cols = np.linspace(crop.col - crop.half, crop.col + crop.half, n)
    rows = np.linspace(crop.row - crop.half, crop.row + crop.half, n)
    cc, rr = np.meshgrid(cols, rows)
    return grid.pixel_to_lonlat(cc, rr)
