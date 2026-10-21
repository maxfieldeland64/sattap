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
from .b13 import B13Pick, pick_b13_round
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
    # Band 13 frames at the same times (GOES only); empty when the still has no Band 13 image
    b13_loop: list[tuple[datetime, Path]] = field(default_factory=list)


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
    """About n playable crops, an equal share from each satellite.

    Each satellite gets its own attempt budget, so one whose disk is mostly ocean or shadow at
    this hour (usually GOES-West) is not crowded out by the other.
    """
    images, grids = {}, {}
    for s in sources:
        img = Image.open(s.path).convert("RGB")
        images[s.sat_key] = img
        grids[s.sat_key] = FullDiskGrid(s.sat_key, img.width)
    by_key = {s.sat_key: s for s in sources}
    share = -(-n // len(by_key))  # ceiling
    out: list[Candidate] = []
    for key in by_key:
        got = attempts = 0
        while got < share and attempts < share * 6:
            attempts += 1
            crop = sample_crop(grids[key], rng)
            if crop is None:
                continue
            tile = cut(images[key], crop)
            stats = compute_stats(grids[key], crop, tile, by_key[key].observed_at)
            if is_playable(stats):
                out.append(Candidate(crop, stats, tile, by_key[key]))
                got += 1
        print(f"candidates {C.SATELLITES[key]['name']}: {got} playable of {attempts} tried")
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
    chosen = _ensure_each_satellite(chosen, ordered, n_rounds)
    return sorted(chosen, key=lambda c: c.stats.difficulty)


def _ensure_each_satellite(chosen: list[Candidate], pool: list[Candidate], n_rounds: int) -> list[Candidate]:
    """Swap rounds so every satellite in the pool has at least MIN_ROUNDS_PER_SAT of them.

    The swap replaces a round from the most-represented satellite with the candidate from the
    short one closest in difficulty (so the ramp barely changes) that keeps answers apart.
    """
    keys = sorted({c.src.sat_key for c in pool})
    if len(keys) < 2:
        return chosen
    need = min(C.MIN_ROUNDS_PER_SAT, n_rounds // len(keys))
    chosen = list(chosen)

    def apart(c: Candidate, others: list[Candidate]) -> bool:
        return all(haversine_km(c.crop.lon, c.crop.lat, o.crop.lon, o.crop.lat) >= C.MIN_ANSWER_SEPARATION_KM for o in others)

    for key in keys:
        while sum(c.src.sat_key == key for c in chosen) < need:
            counts = {k: sum(c.src.sat_key == k for c in chosen) for k in keys}
            donor = max(counts, key=counts.get)
            if donor == key or counts[donor] <= need:
                break
            best = None
            for old in (c for c in chosen if c.src.sat_key == donor):
                rest = [c for c in chosen if c is not old]
                for new in (c for c in pool if c.src.sat_key == key and c not in chosen):
                    gap = abs(new.stats.difficulty - old.stats.difficulty)
                    if (best is None or gap < best[0]) and apart(new, rest):
                        best = (gap, old, new)
            if best is None:
                break
            chosen[chosen.index(best[1])] = best[2]
    return chosen


def _write_media(frames: list[Image.Image], data_dir: Path, rel_stem: str) -> tuple[str, str | None]:
    """Save the last frame as a JPEG still and, with more than one frame, the whole run as a
    looping WebP. Returns (still_rel, loop_rel_or_None), paths relative to data_dir/images."""
    still_rel = f"{rel_stem}.jpg"
    frames[-1].save(data_dir / "images" / still_rel, quality=88)
    loop_rel = None
    if len(frames) > 1:
        loop_rel = f"{rel_stem}.webp"
        save_loop(frames, data_dir / "images" / loop_rel)
    return still_rel, loop_rel


def build_b13_round(pick: B13Pick, i: int, day: Date, data_dir: Path) -> tuple[dict, dict]:
    """The Band 13 round: Band 13 is the picture, GeoColor is the first hint, the 3x-wider view
    (of whichever layer is showing) is the second. Returns (public_round, private_round)."""
    src = pick.src
    gc_path = dict(src.loop or [(src.observed_at, src.path)])
    crop = pick.crop
    b13_close, b13_wide, gc_close, gc_wide, times = [], [], [], [], []
    ctx_box = None
    # one full disk at a time (each is ~90 MB decoded)
    for t, b_path in src.b13_loop:
        if t not in gc_path:
            continue
        for path, close, wide in ((b_path, b13_close, b13_wide), (gc_path[t], gc_close, gc_wide)):
            img = Image.open(path).convert("RGB")
            ctx_img, ctx_box = cut_context(img, crop)
            close.append(cut(img, crop))
            wide.append(ctx_img)
            del img
        times.append(t)
    stem = f"{day.isoformat()}/r{i}"
    b_still, b_loop = _write_media(b13_close, data_dir, stem)
    bw_still, bw_loop = _write_media(b13_wide, data_dir, f"{stem}_ctx")
    g_still, g_loop = _write_media(gc_close, data_dir, f"{stem}_gc")
    gw_still, gw_loop = _write_media(gc_wide, data_dir, f"{stem}_gc_ctx")

    def url(rel: str | None) -> str | None:
        return f"/images/{rel}" if rel else None

    public = {
        "round": i,
        "type": "where",
        "image": url(b_still),
        "band": "B13 · clean IR",
        "satellite": C.SATELLITES[pick.sat_key]["name"],
        "observed_at": src.observed_at.isoformat(),
        "footprint_km": round(crop.width_km),
        "hint_image": url(bw_still),
        "hint_box": ctx_box,
        "loop": url(b_loop),
        "hint_loop": url(bw_loop),
        "frame_times": [t.isoformat() for t in times],
        # The hint ladder: level 1 shows this other layer, level 2 zooms out. The multipliers are
        # shown to players ("-15%"); the server applies its own copy (private hint_mults).
        "ladder": {
            "band": "GeoColor",
            "image": url(g_still),
            "loop": url(g_loop),
            "hint_image": url(gw_still),
            "hint_loop": url(gw_loop),
            "mults": list(C.B13_HINT_MULTS),
        },
    }
    private = {
        "round": i,
        "lat": round(crop.lat, 4),
        "lon": round(crop.lon, 4),
        "stats": pick.as_dict(),
        "crop": {"col": crop.col, "row": crop.row, "half": crop.half},
        "hint_mults": list(C.B13_HINT_MULTS),
    }
    return public, private


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
    # The last round is the Band 13 challenge when a GOES satellite has Band 13 frames and an
    # open-ocean convective cell turns up; otherwise the day stays n_rounds of "where" rounds.
    b13_pick: B13Pick | None = None
    have_b13 = any(s.b13_loop for s in sources)
    if not have_b13:
        print(
            "no Band 13 round: no GOES source has a Band 13 image for its newest frame ("
            + ", ".join(f"{C.SATELLITES[s.sat_key]['name']} {s.observed_at:%H:%M} UTC" for s in sources if s.sat_key != "meteo")
            + "). Run `fetch` again (it downloads Band 13 for the same times) or build with --at."
        )
    rounds = select_rounds(cands, n_rounds - 1 if n_rounds >= 2 and have_b13 else n_rounds)
    if len(rounds) < n_rounds:
        b13_pick = pick_b13_round(sources, np.random.default_rng((day.toordinal() if seed is None else seed) + 13),
                                  avoid=[(c.crop.lon, c.crop.lat) for c in rounds])
        if b13_pick is None:
            print("no eligible Band 13 cell today; building a normal GeoColor round instead")
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

    if b13_pick is not None:
        pub, priv = build_b13_round(b13_pick, len(public_rounds) + 1, day, data_dir)
        public_rounds.append(pub)
        private_rounds.append(priv)

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
