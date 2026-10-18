"""The landing page's GOES-West disk loop."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from PIL import Image

from sattap import config as C
from sattap.landing import build_landing
from sattap.puzzle import SourceImage

DAY = date(2026, 10, 17)
T0 = datetime(2026, 10, 17, 17, 0, tzinfo=timezone.utc)


def _source(tmp_path, key, n_frames):
    loop = []
    for i in range(n_frames):
        p = tmp_path / f"{key}{i}.jpg"
        Image.new("RGB", (400, 400), (20 * i, 80, 120)).save(p)
        loop.append((T0 - timedelta(minutes=10 * (n_frames - 1 - i)), p))
    return SourceImage(key, loop[-1][1], loop[-1][0], loop)


def test_builds_loop_and_still_from_west(tmp_path):
    out = tmp_path / "data"
    meta = build_landing([_source(tmp_path, "east", 3), _source(tmp_path, "west", 4)], DAY, out, size=96)
    assert meta["satellite"] == C.SATELLITES["west"]["name"]
    assert meta["loop"] == "/images/landing/2026-10-17.webp"
    assert meta["image"] == "/images/landing/2026-10-17.jpg"
    assert len(meta["frame_times"]) == 4
    loop = Image.open(out / "images" / "landing" / "2026-10-17.webp")
    assert loop.n_frames == 4 and loop.size == (96, 96)
    assert Image.open(out / "images" / "landing" / "2026-10-17.jpg").size == (96, 96)


def test_single_frame_gives_a_still_only(tmp_path):
    meta = build_landing([_source(tmp_path, "west", 1)], DAY, tmp_path / "data", size=64)
    assert meta["loop"] is None and meta["image"]


def test_no_west_frames_means_no_landing(tmp_path):
    assert build_landing([_source(tmp_path, "east", 2)], DAY, tmp_path / "data", size=64) is None
