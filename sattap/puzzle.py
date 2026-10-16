"""Build a daily puzzle: pick 5 playable crops ramping in difficulty.

Outputs (under data_dir):
  public/{date}.json            puzzle without answers (served to the client)
  private/{date}.json           answers + stats (server side only)
  images/{date}/r{n}.jpg        the crops
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date as Date, datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from . import config as C
from .crops import Crop, cut, cut_context, sample_crop
from .filters import Stats, compute_stats, is_playable
from .geo import FullDiskGrid, haversine_km

Image.MAX_IMAGE_PIXELS = None


@dataclass
class SourceImage:
    sat_key: str
    path: Path
    observed_at: datetime


@dataclass
class Candidate:
    crop: Crop
    stats: Stats
    tile: Image.Image
    src: SourceImage


def collect_candidates(sources: list[SourceImage], n: int, rng: np.random.Generator) -> list[Candidate]:
    images, grids = {}, {}
    for s in sources:
        img = Image.open(s.path).convert("RGB")
        images[s.sat_key] = img
        grids[s.sat_key] = FullDiskGrid(s.sat_key, img.width)
    by_key = {s.sat_key: s for s in sources}
    keys = list(by_key)
    out: list[Candidate] = []
    attempts = 0
    while len(out) < n and attempts < n * 6:
        attempts += 1
        key = keys[int(rng.integers(len(keys)))]
        grid = grids[key]
        crop = sample_crop(grid, rng)
        if crop is None:
            continue
        tile = cut(images[key], crop)
        stats = compute_stats(grid, crop, tile, by_key[key].observed_at)
        if is_playable(stats):
            out.append(Candidate(crop, stats, tile, by_key[key]))
    return out


def select_rounds(cands: list[Candidate], n_rounds: int = C.N_ROUNDS) -> list[Candidate]:
    """Pick n_rounds spread across difficulty quantiles, with answers kept apart."""
    if len(cands) < n_rounds:
        raise RuntimeError(f"Only {len(cands)} playable candidates; need {n_rounds}. Try more candidates.")
    ordered = sorted(cands, key=lambda c: c.stats.difficulty)
    qs = C.DIFFICULTY_QUANTILES[:n_rounds] if n_rounds <= len(C.DIFFICULTY_QUANTILES) else np.linspace(0.1, 0.9, n_rounds)
    chosen: list[Candidate] = []
    for q in qs:
        target = int(round(q * (len(ordered) - 1)))
        # search outward from the target index for one that is far enough from the picks
        for offset in range(len(ordered)):
            for idx in (target + offset, target - offset):
                if not 0 <= idx < len(ordered):
                    continue
                c = ordered[idx]
                if c in chosen:
                    continue
                if all(
                    haversine_km(c.crop.lon, c.crop.lat, p.crop.lon, p.crop.lat) >= C.MIN_ANSWER_SEPARATION_KM
                    for p in chosen
                ):
                    chosen.append(c)
                    break
            else:
                continue
            break
    if len(chosen) < n_rounds:
        # relax separation if the pool was too tight
        for c in ordered:
            if len(chosen) == n_rounds:
                break
            if c not in chosen:
                chosen.append(c)
    return sorted(chosen, key=lambda c: c.stats.difficulty)


def build_daily(
    day: Date,
    sources: list[SourceImage],
    data_dir: Path,
    n_rounds: int = C.N_ROUNDS,
    n_candidates: int = C.N_CANDIDATES,
    seed: int | None = None,
) -> dict:
    rng = np.random.default_rng(day.toordinal() if seed is None else seed)
    cands = collect_candidates(sources, n_candidates, rng)
    rounds = select_rounds(cands, n_rounds)

    img_dir = data_dir / "images" / day.isoformat()
    img_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "public").mkdir(parents=True, exist_ok=True)
    (data_dir / "private").mkdir(parents=True, exist_ok=True)

    full_images: dict[str, Image.Image] = {}
    public_rounds, private_rounds = [], []
    for i, c in enumerate(rounds, start=1):
        rel = f"{day.isoformat()}/r{i}.jpg"
        c.tile.save(data_dir / "images" / rel, quality=88)
        if c.src.sat_key not in full_images:
            full_images[c.src.sat_key] = Image.open(c.src.path).convert("RGB")
        ctx_img, ctx_box = cut_context(full_images[c.src.sat_key], c.crop)
        ctx_rel = f"{day.isoformat()}/r{i}_ctx.jpg"
        ctx_img.save(data_dir / "images" / ctx_rel, quality=85)
        public_rounds.append(
            {
                "round": i,
                "type": "where",
                "image": f"/images/{rel}",
                "band": "GeoColor",
                "satellite": C.SATELLITES[c.src.sat_key]["name"],
                "observed_at": c.src.observed_at.isoformat(),
                "footprint_km": round(c.crop.width_km),
                "hint_image": f"/images/{ctx_rel}",
                "hint_box": ctx_box,
            }
        )
        private_rounds.append(
            {
                "round": i,
                "lat": round(c.crop.lat, 4),
                "lon": round(c.crop.lon, 4),
                "stats": c.stats.as_dict(),
                "crop": {"col": c.crop.col, "row": c.crop.row, "half": c.crop.half},
            }
        )

    meta = {
        "schema": 1,
        "date": day.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    public = {**meta, "rounds": public_rounds}
    private = {**meta, "rounds": private_rounds}
    (data_dir / "public" / f"{day.isoformat()}.json").write_text(json.dumps(public, indent=2))
    (data_dir / "private" / f"{day.isoformat()}.json").write_text(json.dumps(private, indent=2))
    return public
