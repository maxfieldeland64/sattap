"""Assemble the deployable site and the answer payload from a finished build.

  python tools/publish.py [--date YYYY-MM-DD] [--site-url https://sattap.pages.dev]

Reads   data/public/<date>.json, data/images/<date>/*, data/images/landing/<date>.*, data/private/<date>.json, web/
Writes  dist/              static site for Cloudflare Pages (web app + puzzles + images)
        build/kv.json      answers for Workers KV (NEVER inside dist/)

Only the newest puzzle is built on each run. The few days before it are carried over by
downloading them from the live site (--site-url), because every Pages deploy replaces the whole
site. Answers for older days stay in KV, so carried puzzles keep scoring.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSET_KEYS = ("image", "hint_image", "loop", "hint_loop")
FORBIDDEN_KEYS = {"lat", "lon", "stats", "crop"}  # answer data that must never be public
UA = {"User-Agent": "sattap-publish/1.0"}

HEADERS_FILE = """\
/puzzles/*
  Cache-Control: public, max-age=300

/images/*
  Cache-Control: public, max-age=31536000, immutable
"""

NOT_FOUND_HTML = """<!doctype html><meta charset="utf-8"><title>Not found</title>
<body style="font-family:system-ui;background:#0B0F14;color:#E6EDF3;padding:2rem">Not found.</body>
"""


def asset_paths(puzzle: dict) -> list[str]:
    out = []
    for r in puzzle["rounds"]:
        # a hint-ladder round carries a second layer's media under "ladder"
        for holder in (r, r.get("ladder") or {}):
            for k in ASSET_KEYS:
                if holder.get(k):
                    out.append(holder[k].lstrip("/"))
    return out


def landing_paths(puzzle: dict) -> list[str]:
    """Media for the landing page's disk loop. Only the newest puzzle ships these."""
    landing = puzzle.get("landing") or {}
    return [landing[k].lstrip("/") for k in ("image", "loop") if landing.get(k)]


def assert_public(puzzle: dict, where: str) -> None:
    def walk(node):
        if isinstance(node, dict):
            bad = FORBIDDEN_KEYS & node.keys()
            if bad:
                raise SystemExit(f"Refusing to publish: {where} contains answer fields {sorted(bad)}")
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(puzzle)


def fetch(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            return r.read()
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  could not fetch {url}: {e}", file=sys.stderr)
        return None


def carry_previous(site_url: str, dist: Path, current: str, days: int) -> list[str]:
    """Download up to `days` earlier puzzles (JSON + media) from the live site into dist/."""
    raw = fetch(f"{site_url.rstrip('/')}/puzzles/index.json")
    if raw is None:
        print("No live index.json (first deploy?); nothing to carry over.")
        return []
    try:
        dates = [d for d in json.loads(raw)["dates"] if d != current]
    except (ValueError, KeyError):
        print("Live index.json is not valid; nothing to carry over.", file=sys.stderr)
        return []
    kept = []
    for d in sorted(dates, reverse=True)[:days]:
        body = fetch(f"{site_url.rstrip('/')}/puzzles/{d}.json")
        if body is None:
            continue
        puzzle = json.loads(body)
        assert_public(puzzle, f"carried puzzle {d}")
        files = {}
        for rel in asset_paths(puzzle):
            data = fetch(f"{site_url.rstrip('/')}/{rel}")
            if data is None:
                break
            files[rel] = data
        else:
            (dist / "puzzles").mkdir(parents=True, exist_ok=True)
            (dist / "puzzles" / f"{d}.json").write_bytes(body)
            for rel, data in files.items():
                (dist / rel).parent.mkdir(parents=True, exist_ok=True)
                (dist / rel).write_bytes(data)
            kept.append(d)
            continue
        print(f"  skipping {d}: a media file was missing", file=sys.stderr)
    print(f"Carried over {len(kept)} earlier puzzle(s): {kept}")
    return kept


def kv_entry(private: dict) -> dict:
    def entry(r: dict) -> dict:
        e = {"round": r["round"], "lat": r["lat"], "lon": r["lon"]}
        if r.get("hint_mults"):  # hint-ladder round: the Function needs the per-level multipliers
            e["hint_mults"] = r["hint_mults"]
        return e

    doc = {"scoring": private["scoring"], "rounds": [entry(r) for r in private["rounds"]]}
    return {"key": f"puzzle:{private['date']}", "value": json.dumps(doc, separators=(",", ":"))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--kv-out", default=str(ROOT / "build" / "kv.json"))
    ap.add_argument("--date", help="puzzle date to publish (default: newest in data/public)")
    ap.add_argument("--site-url", help="live site to carry earlier days over from")
    ap.add_argument("--carry-days", type=int, default=6)
    ap.add_argument("--kv-all", action="store_true", help="put every local private puzzle in the KV payload (backfill)")
    args = ap.parse_args()

    data, dist, kv_out = Path(args.data), Path(args.out), Path(args.kv_out)
    public_dir = data / "public"
    date = args.date or (sorted(public_dir.glob("*.json"))[-1].stem if list(public_dir.glob("*.json")) else None)
    if not date:
        raise SystemExit(f"No built puzzles in {public_dir}. Run `python -m sattap.cli build` first.")

    puzzle = json.loads((public_dir / f"{date}.json").read_text())
    private = json.loads((data / "private" / f"{date}.json").read_text())
    assert_public(puzzle, f"data/public/{date}.json")

    if dist.exists():
        shutil.rmtree(dist)
    shutil.copytree(ROOT / "web", dist)
    (dist / "puzzles").mkdir()
    (dist / "puzzles" / f"{date}.json").write_text(json.dumps(puzzle, separators=(",", ":")))
    for rel in asset_paths(puzzle) + landing_paths(puzzle):
        src = data / rel
        if not src.exists():
            raise SystemExit(f"Missing media file {src}")
        (dist / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dist / rel)

    carried = carry_previous(args.site_url, dist, date, args.carry_days) if args.site_url and args.carry_days > 0 else []

    dates = sorted({date, *carried}, reverse=True)
    (dist / "puzzles" / "index.json").write_text(json.dumps({"latest": dates[0], "dates": dates}))
    shutil.copy2(dist / "puzzles" / f"{dates[0]}.json", dist / "puzzles" / "latest.json")
    (dist / "_headers").write_text(HEADERS_FILE)
    (dist / "404.html").write_text(NOT_FOUND_HTML)  # without it Pages serves index.html for every miss

    entries = [kv_entry(private)]
    if args.kv_all:
        entries = [kv_entry(json.loads(p.read_text())) for p in sorted((data / "private").glob("*.json"))]
    kv_out.parent.mkdir(parents=True, exist_ok=True)
    kv_out.write_text(json.dumps(entries))

    # last line of defence: nothing from the private side may be in dist/
    for p in dist.rglob("*.json"):
        if p.name != "land.geojson":
            assert_public(json.loads(p.read_text()), str(p))
    n_files = sum(1 for p in dist.rglob("*") if p.is_file())
    size_mb = sum(p.stat().st_size for p in dist.rglob("*") if p.is_file()) / 1e6
    print(f"Published puzzle {date} -> {dist} ({n_files} files, {size_mb:.1f} MB); answers for {[e['key'] for e in entries]} -> {kv_out}")


if __name__ == "__main__":
    main()
