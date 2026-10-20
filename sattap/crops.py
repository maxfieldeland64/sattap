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


def crop_at(grid: FullDiskGrid, col: int, row: int, half: int) -> Crop | None:
    """The crop centred on pixel (col, row), or None if it leaves the image or nears the limb."""
    if col - half < 0 or row - half < 0 or col + half > grid.size or row + half > grid.size:
        return None
    if grid.radial_frac(col, row) > C.MAX_RADIAL_FRAC:
        return None
    corners = [(col + dx, row + dy) for dx in (-half, half) for dy in (-half, half)]
    if any(grid.radial_frac(c, r) > C.MAX_CORNER_FRAC for c, r in corners):
        return None
    lon, lat = grid.pixel_to_lonlat(col, row)
    if np.isnan(lon) or np.isnan(lat):
        return None
    lon_l, lat_l = grid.pixel_to_lonlat(col - half, row)
    lon_r, lat_r = grid.pixel_to_lonlat(col + half, row)
    if np.isnan([lon_l, lat_l, lon_r, lat_r]).any():
        return None
    width_km = float(haversine_km(lon_l, lat_l, lon_r, lat_r))
    return Crop(grid.sat_key, col, row, half, lon, lat, width_km)


def sample_crop(grid: FullDiskGrid, rng: np.random.Generator) -> Crop | None:
    scale = grid.size / C.FD_SIZE_2KM
    half = max(8, int(round(rng.choice(C.CROP_HALF_PX_CHOICES) * scale)))
    lo, hi = half, grid.size - half
    if hi <= lo:
        return None
    for _ in range(200):
        col = int(rng.integers(lo, hi))
        row = int(rng.integers(lo, hi))
        crop = crop_at(grid, col, row, half)
        if crop is not None:
            return crop
    return None


def cut(img: Image.Image, crop: Crop, out_size: int = C.OUT_SIZE_PX) -> Image.Image:
    return img.crop(crop.box).resize((out_size, out_size), Image.LANCZOS)


def cut_context(
    img: Image.Image, crop: Crop, factor: int = C.HINT_CONTEXT_FACTOR, out_size: int = C.OUT_SIZE_PX
) -> tuple[Image.Image, list[float]]:
    """A wider view around the crop for the hint.

    Returns the image and the crop's box inside it as fractions [x, y, w, h]. The window is
    shifted (not shrunk) to stay inside the full disk image where it can.
    """
    half_c = min(crop.half * factor, img.width // 2)
    x0 = min(max(crop.col - half_c, 0), img.width - 2 * half_c)
    y0 = min(max(crop.row - half_c, 0), img.height - 2 * half_c)
    ctx = img.crop((x0, y0, x0 + 2 * half_c, y0 + 2 * half_c)).resize((out_size, out_size), Image.LANCZOS)
    side = 2 * half_c
    box = [
        (crop.col - crop.half - x0) / side,
        (crop.row - crop.half - y0) / side,
        2 * crop.half / side,
        2 * crop.half / side,
    ]
    return ctx, [round(v, 4) for v in box]


def lonlat_grid(grid: FullDiskGrid, crop: Crop, n: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """n x n lon/lat samples spread over the crop footprint."""
    cols = np.linspace(crop.col - crop.half, crop.col + crop.half, n)
    rows = np.linspace(crop.row - crop.half, crop.row + crop.half, n)
    cc, rr = np.meshgrid(cols, rows)
    return grid.pixel_to_lonlat(cc, rr)
