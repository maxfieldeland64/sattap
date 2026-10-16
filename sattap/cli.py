"""Command line entry point.

  python -m sattap.cli fetch                       # download latest GeoColor for East + West
  python -m sattap.cli build [--date YYYY-MM-DD]   # build a daily puzzle from cached images
  python -m sattap.cli synth                       # make fake full-disk images (offline dev)
  python -m sattap.cli check-geo                   # sanity-check geometry numbers
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from . import config as C
from .geo import FullDiskGrid
from .puzzle import SourceImage, build_daily

DEFAULT_DATA = Path("data")


def _cached_sources(cache_dir: Path) -> list[SourceImage]:
    """Newest cached image per satellite, with observed_at parsed from the filename."""
    from .sources import _NAME_RE

    best: dict[str, SourceImage] = {}
    for p in sorted(cache_dir.glob("*.jpg")):
        m = _NAME_RE.fullmatch(p.name)
        if not m:
            continue
        stamp, sat_slug, _, _ = m.groups()
        key = next((k for k, v in C.SATELLITES.items() if v["slug"] == sat_slug), None)
        if key is None:
            continue
        t = datetime.strptime(stamp, "%Y%j%H%M").replace(tzinfo=timezone.utc)
        if key not in best or t > best[key].observed_at:
            best[key] = SourceImage(key, p, t)
    return list(best.values())


def cmd_fetch(args) -> None:
    from .sources import fetch_latest

    cache = Path(args.data) / "cache"
    for key in ("east", "west"):
        f = fetch_latest(key, cache)
        print(f"{key}: {f.url} -> {f.path} ({f.observed_at.isoformat()})")


def cmd_build(args) -> None:
    cache = Path(args.data) / "cache"
    sources = _cached_sources(cache)
    if not sources:
        raise SystemExit(f"No cached images in {cache}. Run `fetch` (or `synth`) first.")
    day = date.fromisoformat(args.date) if args.date else datetime.now(timezone.utc).date()
    pub = build_daily(day, sources, Path(args.data), args.rounds, args.candidates, args.seed)
    print(json.dumps(pub, indent=2))


def cmd_synth(args) -> None:
    from .synth import make_full_disk

    cache = Path(args.data) / "cache"
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%j%H%M")
    for i, key in enumerate(("east", "west")):
        slug = C.SATELLITES[key]["slug"]
        out = cache / f"{stamp}_{slug}-ABI-FD-GEOCOLOR-{args.size}x{args.size}.jpg"
        make_full_disk(key, args.size, out, seed=args.seed + i)
        print("wrote", out)


def cmd_check_geo(_args) -> None:
    for key in ("east", "west"):
        g = FullDiskGrid(key, C.FD_SIZE_2KM)
        mid = (g.size - 1) / 2
        lon, lat = g.pixel_to_lonlat(mid, mid)
        print(f"{key}: image center -> lon {lon:.2f}, lat {lat:.2f} (expect sub-satellite point {g.lon0}, 0)")
        # Landmark check: Baja California tip (~-109.9, 22.9) from GOES-West,
        # Florida Keys (~-81.8, 24.6) from GOES-East. Open the full-disk JPEG at the
        # printed pixel and confirm it is on that landmark.
        lm = (-109.9, 22.9) if key == "west" else (-81.8, 24.6)
        c, r = g.lonlat_to_pixel(*lm)
        print(f"  landmark {lm} -> pixel col {c:.0f}, row {r:.0f}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="sattap")
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="data directory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch").set_defaults(fn=cmd_fetch)

    b = sub.add_parser("build")
    b.add_argument("--date")
    b.add_argument("--rounds", type=int, default=C.N_ROUNDS)
    b.add_argument("--candidates", type=int, default=C.N_CANDIDATES)
    b.add_argument("--seed", type=int)
    b.set_defaults(fn=cmd_build)

    s = sub.add_parser("synth")
    s.add_argument("--size", type=int, default=1356)
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(fn=cmd_synth)

    sub.add_parser("check-geo").set_defaults(fn=cmd_check_geo)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
