"""Build a daily puzzle: pick 5 playable crops ramping in difficulty.

Outputs (under data_dir):
  public/{date}.json            puzzle without answers (served to the client)
  private/{date}.json           answers + stats (server side only)
  images/{date}/r{n}.jpg        the crops
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date as Date, datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from . import config as C
from .crops import Crop, cut, cut_context, sample_crop
from .filters import Stats, compute_stats, is_playable
from .geo import FullDiskGrid, haversine_km
from .scoring import scoring_params

Image.MAX_IMAGE_PIXELS = None


@dataclass
class SourceImage:
    sat_key: str
    path: Path
    observed_at: datetime
    # earlier frames for the loop, [(observed_at, path)] oldest first, ending with this frame
    loop: list[tuple[datetime, Path]] = field(default_factory=list)


@dataclass
class Candidate:
    crop: Crop
    stats: Stats
    tile: Image.Image
    src: SourceImage


def save_loop(frames: list[Image.Image], dest: Path, quality: int = C.LOOP_WEBP_QUALITY) -> None:
    """Write frames as one looping animated WebP, holding on the last frame."""
    durations = [C.LOOP_FRAME_MS] * (len(frames) - 1) + [C.LOOP_FRAME_MS + C.LOOP_HOLD_MS]
    frames[0].save(
        dest,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        quality=quality,
        method=4,
    )


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

    # Cut the same crop and hint window out of every loop frame. Frames are opened one at a
    # time (each full disk is ~90 MB decoded) and shared by all rounds from that satellite.
    loops: dict[int, list[tuple[datetime, Image.Image, Image.Image]]] = {i: [] for i in range(len(rounds))}
    ctx_boxes: dict[int, list[float]] = {}
    for key in {c.src.sat_key for c in rounds}:
        mine = [i for i, c in enumerate(rounds) if c.src.sat_key == key]
        src = rounds[mine[0]].src
        frames = src.loop or [(src.observed_at, src.path)]
        for t, path in frames:
            img = Image.open(path).convert("RGB")
            for i in mine:
                crop = rounds[i].crop
                ctx_img, box = cut_context(img, crop)
                loops[i].append((t, cut(img, crop), ctx_img))
                ctx_boxes[i] = box
            del img

    public_rounds, private_rounds = [], []
    for i0, c in enumerate(rounds):
        i = i0 + 1
        frames_i = loops[i0]
        # the still (last frame) doubles as the reveal image and the no-animation fallback
        rel = f"{day.isoformat()}/r{i}.jpg"
        ctx_rel = f"{day.isoformat()}/r{i}_ctx.jpg"
        frames_i[-1][1].save(data_dir / "images" / rel, quality=88)
        frames_i[-1][2].save(data_dir / "images" / ctx_rel, quality=85)
        ctx_box = ctx_boxes[i0]
        loop_rel = ctx_loop_rel = None
        if len(frames_i) > 1:
            loop_rel = f"{day.isoformat()}/r{i}.webp"
            ctx_loop_rel = f"{day.isoformat()}/r{i}_ctx.webp"
            save_loop([f[1] for f in frames_i], data_dir / "images" / loop_rel)
            save_loop([f[2] for f in frames_i], data_dir / "images" / ctx_loop_rel)
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
                "loop": f"/images/{loop_rel}" if loop_rel else None,
                "hint_loop": f"/images/{ctx_loop_rel}" if ctx_loop_rel else None,
                "frame_times": [f[0].isoformat() for f in frames_i],
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
    # The landing page's disk loop is decoration: if it fails, the puzzle still ships without it.
    try:
        from .landing import build_landing

        landing = build_landing(sources, day, data_dir)
    except Exception as e:  # noqa: BLE001
        print(f"warning: landing loop not built: {e}")
        landing = None
    if landing:
        public["landing"] = landing
    private = {**meta, "scoring": scoring_params(), "rounds": private_rounds}
    (data_dir / "public" / f"{day.isoformat()}.json").write_text(json.dumps(public, indent=2))
    (data_dir / "private" / f"{day.isoformat()}.json").write_text(json.dumps(private, indent=2))
    return public
