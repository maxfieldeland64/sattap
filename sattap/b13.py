"""The Band 13 challenge: find an open-ocean convective cell in the CDN's enhanced B13 image.

The NOAA STAR CDN's Band 13 (clean longwave IR) JPEG is colourised by temperature: warm surfaces
and low cloud stay grey, and cold cloud tops run blue -> green -> yellow -> red as they get
colder. We do not have calibrated brightness temperatures, but the colour ramp is enough to rank
how cold a cloud top is, which is all the round needs (it picks the coldest convective core and
the player pins where it is).

The CDN also draws coastlines and country borders on this image. A crop that contains land would
show them and give the answer away, so only crops with no land (plus a margin) are eligible, which
is also what makes the round about reading the weather instead of recognising a shoreline.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from global_land_mask import globe
from PIL import Image, ImageFilter

from . import config as C
from .crops import Crop, crop_at
from .filters import min_sun_elevation
from .geo import FullDiskGrid, haversine_km

Image.MAX_IMAGE_PIXELS = None


@dataclass
class B13Pick:
    crop: Crop
    src: object  # the SourceImage (its b13_loop and GeoColor loop supply the frames)
    peak: float  # smoothed coldness at the centre, 0..1
    colored_frac: float  # share of the crop that is colourised (cold cloud)
    min_sun_elev: float

    @property
    def sat_key(self) -> str:
        return self.crop.sat_key

    def as_dict(self) -> dict:
        return {
            "peak": round(self.peak, 3),
            "colored_frac": round(self.colored_frac, 3),
            "min_sun_elev": round(self.min_sun_elev, 1),
        }


def coldness(rgb: np.ndarray, min_spread: float = C.B13_MIN_SPREAD) -> np.ndarray:
    """Per-pixel coldness 0..1 from the enhanced image: 0 for grey (warm) pixels, and for
    colourised ones the hue along the ramp (blue ~0.05, cyan 0.25, green 0.5, yellow 0.75, red 1)."""
    a = rgb.astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx = a.max(axis=-1)
    spread = mx - a.min(axis=-1)
    d = np.where(spread == 0, 1.0, spread)
    hue = np.where(
        mx == r, ((g - b) / d) % 6.0, np.where(mx == g, (b - r) / d + 2.0, (r - g) / d + 4.0)
    ) * 60.0
    hue = np.where(hue > 300.0, 0.0, hue)  # reds that lean magenta wrap past 300 degrees
    cold = np.clip((240.0 - hue) / 240.0, 0.0, 1.0)
    colored = (spread >= min_spread) & (mx >= 40)
    return np.where(colored, cold, 0.0).astype(np.float32)


def load_analysis(path: Path, size: int = C.B13_ANALYSIS_SIZE) -> np.ndarray:
    """The B13 image at analysis size as an RGB array (JPEG draft mode decodes 1/4 scale fast)."""
    img = Image.open(path)
    img.draft("RGB", (size, size))
    img = img.convert("RGB")
    if img.size != (size, size):
        img = img.resize((size, size), Image.BILINEAR)
    return np.asarray(img)


def smooth_field(cold: np.ndarray, radius: float = C.B13_SMOOTH_PX) -> np.ndarray:
    """Gaussian-blurred coldness, so the maximum sits in the middle of a cell's cold core
    instead of on one noisy pixel. Goes through an 8-bit image because PIL blurs those."""
    img = Image.fromarray((cold * 255.0).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(img, dtype=np.float32) / 255.0


def find_peaks(field: np.ndarray, valid: np.ndarray, min_peak: float, sep_px: int, max_peaks: int) -> list[tuple[int, int, float]]:
    """Greedy local maxima of `field` inside `valid`, each at least sep_px from the others."""
    work = np.where(valid, field, 0.0).copy()
    yy, xx = np.indices(work.shape)
    peaks: list[tuple[int, int, float]] = []
    while len(peaks) < max_peaks:
        idx = int(work.argmax())
        row, col = divmod(idx, work.shape[1])
        val = float(work[row, col])
        if val < min_peak:
            break
        peaks.append((col, row, val))
        work[(xx - col) ** 2 + (yy - row) ** 2 <= sep_px**2] = 0.0
    return peaks


def window_has_land(analysis_grid: FullDiskGrid, col: int, row: int, half: int) -> bool:
    """True if any pixel of the (analysis-scale) window around (col, row) is land or unknown."""
    size = analysis_grid.size
    c0, c1 = max(col - half, 0), min(col + half, size - 1)
    r0, r1 = max(row - half, 0), min(row + half, size - 1)
    cc, rr = np.meshgrid(np.arange(c0, c1 + 1), np.arange(r0, r1 + 1))
    lon, lat = analysis_grid.pixel_to_lonlat(cc, rr)
    ok = np.isfinite(lon) & np.isfinite(lat)
    if not ok.all():
        return True  # window reaches past the limb
    return bool(globe.is_land(lat, lon).any())


def pick_b13_round(
    sources,
    rng: np.random.Generator,
    avoid: list[tuple[float, float]] | None = None,
    min_separation_km: float = C.MIN_ANSWER_SEPARATION_KM,
) -> B13Pick | None:
    """Best open-ocean convective cell across the sources that have Band 13, or None.

    `sources` are SourceImage objects; one needs a non-empty `b13_loop` whose last entry is the
    still. `avoid` lists (lon, lat) of other rounds' answers to keep apart from.
    """
    avoid = avoid or []
    scored: list[tuple[float, B13Pick]] = []
    why = {"edge": 0, "land": 0, "night": 0, "structure": 0, "near other rounds": 0}  # why cells were rejected
    for src in sources:
        if not getattr(src, "b13_loop", None):
            continue
        t_still, path = src.b13_loop[-1]
        with Image.open(path) as im:
            full_size = im.width
        a_size = min(C.B13_ANALYSIS_SIZE, full_size)
        agrid = FullDiskGrid(src.sat_key, a_size)
        rgb = load_analysis(path, a_size)
        cold = coldness(rgb)
        field = smooth_field(cold)

        yy, xx = np.indices(field.shape)
        valid = agrid.radial_frac(xx, yy) <= C.MAX_RADIAL_FRAC
        half_full = max(8, int(round(C.B13_CROP_HALF_PX * full_size / C.FD_SIZE_2KM)))
        scale = (a_size - 1) / (full_size - 1)  # full-grid pixel -> analysis pixel
        half_a = max(2, int(round(half_full * scale)))
        peaks = find_peaks(field, valid, C.B13_MIN_PEAK, sep_px=int(half_a * 1.5), max_peaks=60)

        full = FullDiskGrid(src.sat_key, full_size)
        for col_a, row_a, peak in peaks:
            col, row = int(round(col_a / scale)), int(round(row_a / scale))
            crop = crop_at(full, col, row, half_full)
            if crop is None:
                why["edge"] += 1
                continue
            if window_has_land(agrid, col_a, row_a, int(np.ceil(half_a * C.B13_COAST_MARGIN))):
                why["land"] += 1
                continue
            sun = min_sun_elevation(full, crop, t_still)
            if sun < C.MIN_SUN_ELEV_DEG:
                why["night"] += 1
                continue
            win = cold[max(row_a - half_a, 0): row_a + half_a + 1, max(col_a - half_a, 0): col_a + half_a + 1]
            frac = float((win > 0).mean())
            if not C.B13_MIN_COLORED_FRAC <= frac <= C.B13_MAX_COLORED_FRAC:
                why["structure"] += 1
                continue
            if any(haversine_km(crop.lon, crop.lat, lo, la) < min_separation_km for lo, la in avoid):
                why["near other rounds"] += 1
                continue
            # a strong core and a crop with some structure around it score best
            score = peak - abs(frac - C.B13_TARGET_COLORED_FRAC)
            scored.append((score, B13Pick(crop, src, peak, frac, sun)))
        print(f"b13 {C.SATELLITES[src.sat_key]['name']}: {len(peaks)} cells, {len(scored)} eligible so far")

    if not scored:
        print("b13: no eligible cell. Cells rejected for: " + ", ".join(f"{k} {v}" for k, v in why.items() if v))
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: max(1, C.B13_TOP_K)]
    return top[int(rng.integers(len(top)))][1]
