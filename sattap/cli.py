"""Command line entry point.

  python -m sattap.cli fetch [--frames 6]          # download the last hour of GeoColor (East, West, Meteosat)
  python -m sattap.cli build [--date YYYY-MM-DD]   # build a daily puzzle from cached images
  python -m sattap.cli synth                       # make fake full-disk images (offline dev)
  python -m sattap.cli check-geo                   # sanity-check geometry numbers
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config as C
from .gameday import game_day
from .geo import FullDiskGrid
from .puzzle import SourceImage, build_daily

DEFAULT_DATA = Path("data")


def _parse_at(text: str | None) -> datetime | None:
    """--at accepts 'YYYY-MM-DDTHH:MM' (UTC) or just 'HH:MM' meaning today (UTC)."""
    if not text:
        return None
    if len(text) <= 5:
        h, m = (int(x) for x in text.split(":"))
        now = datetime.now(timezone.utc)
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        # most recent past occurrence: if that clock time hasn't happened yet today (UTC), use yesterday
        return t - timedelta(days=1) if t > now else t
    t = datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _cached_sources(cache_dir: Path, at: datetime | None = None) -> list[SourceImage]:
    """Newest cached image per satellite (at or before `at`), observed_at parsed from the filename."""
    from .sources import CACHE_NAME_RE

    best: dict[str, SourceImage] = {}
    seen: dict[str, dict[datetime, Path]] = {}
    for p in sorted(cache_dir.glob("*.jpg")):
        m = CACHE_NAME_RE.fullmatch(p.name)
        if not m:
            continue
        stamp, sat_slug, w, _ = m.groups()
        key = next((k for k, v in C.SATELLITES.items() if v["slug"] == sat_slug), None)
        if key is None:
            continue
        t = datetime.strptime(stamp, "%Y%j%H%M").replace(tzinfo=timezone.utc)
        if at is not None and t > at:
            continue
        seen.setdefault(key, {})[t] = p
        if key not in best or t > best[key].observed_at:
            best[key] = SourceImage(key, p, t)
    # loop = cached frames at the 10-minute slots ending at the newest frame (oldest first)
    for key, src in best.items():
        slots = [src.observed_at - timedelta(minutes=C.LOOP_STEP_MIN * k) for k in range(C.LOOP_FRAMES - 1, -1, -1)]
        src.loop = [(t, seen[key][t]) for t in slots if t in seen[key]]
    return list(best.values())


def cmd_fetch(args) -> None:
    from .sources import fetch_loop

    from .sun import latest_solar_noon

    cache = Path(args.data) / "cache"
    explicit = _parse_at(args.at)
    now = datetime.now(timezone.utc)
    failed: list[str] = []
    for key in C.SATELLITES:
        at = explicit
        if at is None and C.SOLAR_NOON_CAPTURE:
            noon = latest_solar_noon(C.SATELLITES[key]["lon0"], now)
            at = min(noon + timedelta(minutes=C.CAPTURE_AFTER_NOON_MIN), now)
        try:
            try:
                frames = fetch_loop(key, cache, args.frames, at)
            except RuntimeError as e:
                if explicit is not None or at is None:
                    raise
                print(f"{key}: no frames near local noon ({e}); using the newest instead")
                frames = fetch_loop(key, cache, args.frames, None)
        except Exception as e:  # noqa: BLE001  one source being down should not cancel the day's puzzle
            failed.append(key)
            print(f"{key}: FAILED, building without it: {e}")
            continue
        print(f"{key}: {len(frames)} frames, {frames[0].observed_at:%H:%M} to {frames[-1].observed_at:%H:%M} UTC")
        for f in frames:
            print(f"  {f.path}")
    if len(failed) == len(C.SATELLITES):
        raise SystemExit("No satellite could be fetched.")


def cmd_build(args) -> None:
    cache = Path(args.data) / "cache"
    sources = _cached_sources(cache, _parse_at(args.at))
    if not sources:
        raise SystemExit(f"No cached images in {cache}. Run `fetch` (or `synth`) first.")
    day = date.fromisoformat(args.date) if args.date else game_day()
    try:
        pub = build_daily(day, sources, Path(args.data), args.rounds, args.candidates, args.seed)
    except RuntimeError as e:
        newest = max(s.observed_at for s in sources)
        raise SystemExit(
            f"{e}\n\nThe newest cached frame is {newest:%Y-%m-%d %H:%M} UTC. That is probably night over the "
            "Americas (roughly 15-19 UTC works best). To build from an earlier daytime hour, run:\n"
            f"  python3 -m sattap.cli fetch --at {newest:%Y-%m-%d}T17:00\n"
            f"  python3 -m sattap.cli build --at {newest:%Y-%m-%d}T17:00"
        )
    print(json.dumps(pub, indent=2))


def cmd_synth(args) -> None:
    from .sources import cache_name
    from .synth import make_full_disk

    cache = Path(args.data) / "cache"
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%j%H%M")
    for i, key in enumerate(C.SATELLITES):
        out = cache / cache_name(key, now, args.size)
        make_full_disk(key, args.size, out, seed=args.seed + i)
        print("wrote", out)


def cmd_check_geo(_args) -> None:
    for key in C.SATELLITES:
        g = FullDiskGrid(key, C.FD_SIZE_2KM)
        mid = (g.size - 1) / 2
        lon, lat = g.pixel_to_lonlat(mid, mid)
        print(f"{key}: image center -> lon {lon:.2f}, lat {lat:.2f} (expect sub-satellite point {g.lon0}, 0)")
        # Landmark check: Baja California tip (~-109.9, 22.9) from GOES-West, Florida Keys
        # (~-81.8, 24.6) from GOES-East, Cape Verde's Dakar peninsula (~-17.5, 14.7) from
        # Meteosat. Open the full-disk JPEG at the printed pixel and confirm it is on that landmark.
        lm = {"west": (-109.9, 22.9), "east": (-81.8, 24.6), "meteo": (-17.5, 14.7)}[key]
        c, r = g.lonlat_to_pixel(*lm)
        print(f"  landmark {lm} -> pixel col {c:.0f}, row {r:.0f}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="sattap")
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="data directory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch")
    f.add_argument("--frames", type=int, default=C.LOOP_FRAMES, help="frames per loop (10 min apart)")
    f.add_argument("--at", help="end the loop at this UTC time instead of now: HH:MM (most recent past, UTC) or YYYY-MM-DDTHH:MM")
    f.set_defaults(fn=cmd_fetch)

    b = sub.add_parser("build")
    b.add_argument("--date")
    b.add_argument("--rounds", type=int, default=C.N_ROUNDS)
    b.add_argument("--candidates", type=int, default=C.N_CANDIDATES)
    b.add_argument("--seed", type=int)
    b.add_argument("--at", help="use the newest cached frames at or before this UTC time (same format as fetch --at)")
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
