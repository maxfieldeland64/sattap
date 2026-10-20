"""Game-day rollover, publish safety checks, and the static puzzle routes."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sattap import config as C
from sattap.gameday import game_day

ROOT = Path(__file__).resolve().parent.parent


def _load_publish():
    spec = importlib.util.spec_from_file_location("publish", ROOT / "tools" / "publish.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


publish = _load_publish()


def test_game_day_rolls_over_at_configured_hour():
    h = C.ROLLOVER_UTC_HOUR
    before = datetime(2026, 10, 16, h - 1, 59, tzinfo=timezone.utc)
    at = datetime(2026, 10, 16, h, 0, tzinfo=timezone.utc)
    assert game_day(before).isoformat() == "2026-10-15"
    assert game_day(at).isoformat() == "2026-10-16"
    # a US evening (03:00 UTC next day) is still the same game day
    assert game_day(datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)).isoformat() == "2026-10-16"


PUBLIC = {
    "date": "2026-10-16",
    "rounds": [{"round": 1, "image": "/images/2026-10-16/r1.jpg", "footprint_km": 600, "hint_box": [0.3, 0.3, 0.3, 0.3]}],
}


def test_assert_public_accepts_the_public_shape():
    publish.assert_public(PUBLIC, "ok")


@pytest.mark.parametrize("leak", ["lat", "lon", "stats", "crop"])
def test_assert_public_blocks_answer_fields(leak):
    bad = json.loads(json.dumps(PUBLIC))
    bad["rounds"][0][leak] = 1
    with pytest.raises(SystemExit):
        publish.assert_public(bad, "bad")


def test_kv_entry_has_only_answers_and_scoring():
    private = {
        "date": "2026-10-16",
        "scoring": {"free_km": 150, "scale_km": 2500, "hint_mult": 0.7, "earth_radius_km": 6371.0088},
        "rounds": [{"round": 1, "lat": 1.5, "lon": 2.5, "stats": {"cloud_frac": 0.1}, "crop": {"col": 1}}],
    }
    e = publish.kv_entry(private)
    assert e["key"] == "puzzle:2026-10-16"
    doc = json.loads(e["value"])
    assert doc["rounds"] == [{"round": 1, "lat": 1.5, "lon": 2.5}]
    assert doc["scoring"]["scale_km"] == 2500


def test_asset_paths_skip_missing_loops():
    p = {"rounds": [{"image": "/images/a.jpg", "hint_image": "/images/b.jpg", "loop": None, "hint_loop": None}]}
    assert publish.asset_paths(p) == ["images/a.jpg", "images/b.jpg"]


def test_static_puzzle_routes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from sattap import api

    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "2026-10-15.json").write_text(json.dumps({"date": "2026-10-15", "rounds": []}))
    (tmp_path / "public" / "2026-10-16.json").write_text(json.dumps({"date": "2026-10-16", "rounds": []}))
    monkeypatch.setattr(api, "DATA", tmp_path)
    c = TestClient(api.app)
    assert c.get("/puzzles/2026-10-15.json").json()["date"] == "2026-10-15"
    assert c.get("/puzzles/latest.json").json()["date"] == "2026-10-16"
    assert c.get("/puzzles/2030-01-01.json").status_code == 404
    assert c.get("/puzzles/readme.txt").status_code == 404


def test_landing_paths():
    assert publish.landing_paths({"rounds": []}) == []
    p = {"landing": {"image": "/images/landing/d.jpg", "loop": "/images/landing/d.webp"}}
    assert publish.landing_paths(p) == ["images/landing/d.jpg", "images/landing/d.webp"]
    assert publish.landing_paths({"landing": {"image": "/images/landing/d.jpg", "loop": None}}) == ["images/landing/d.jpg"]


def test_publish_ships_the_landing_media(tmp_path, monkeypatch):
    data = tmp_path / "data"
    for d in ("public", "private", "images/2026-10-16", "images/landing"):
        (data / d).mkdir(parents=True)
    puzzle = {
        "date": "2026-10-16",
        "rounds": [{"round": 1, "image": "/images/2026-10-16/r1.jpg", "hint_image": None, "loop": None, "hint_loop": None}],
        "landing": {"satellite": "GOES-18", "image": "/images/landing/2026-10-16.jpg", "loop": "/images/landing/2026-10-16.webp", "frame_times": []},
    }
    private = {"date": "2026-10-16", "scoring": {}, "rounds": [{"round": 1, "lat": 1.0, "lon": 2.0}]}
    (data / "public" / "2026-10-16.json").write_text(json.dumps(puzzle))
    (data / "private" / "2026-10-16.json").write_text(json.dumps(private))
    for rel in ("images/2026-10-16/r1.jpg", "images/landing/2026-10-16.jpg", "images/landing/2026-10-16.webp"):
        (data / rel).write_bytes(b"x")

    out = tmp_path / "dist"
    monkeypatch.setattr("sys.argv", ["publish", "--data", str(data), "--out", str(out), "--kv-out", str(tmp_path / "kv.json")])
    publish.main()
    assert (out / "images/landing/2026-10-16.webp").exists()
    assert (out / "images/landing/2026-10-16.jpg").exists()
    assert (out / "index.html").exists() and (out / "play" / "index.html").exists() and (out / "landing.js").exists()
    assert (out / "countries.json").exists()  # label anchors must pass the public-JSON check too
    assert json.loads((out / "puzzles" / "latest.json").read_text())["landing"]["satellite"] == "GOES-18"


LADDER_PUBLIC = {
    "date": "2026-10-20",
    "rounds": [
        {
            "round": 5, "image": "/images/d/r5.jpg", "hint_image": "/images/d/r5_ctx.jpg", "loop": None, "hint_loop": None,
            "ladder": {"band": "GeoColor", "image": "/images/d/r5_gc.jpg", "loop": "/images/d/r5_gc.webp",
                       "hint_image": "/images/d/r5_gc_ctx.jpg", "hint_loop": None, "mults": [1.0, 0.85, 0.6]},
        }
    ],
}


def test_asset_paths_include_the_ladder_layer():
    assert publish.asset_paths(LADDER_PUBLIC) == [
        "images/d/r5.jpg", "images/d/r5_ctx.jpg",
        "images/d/r5_gc.jpg", "images/d/r5_gc_ctx.jpg", "images/d/r5_gc.webp",
    ]
    publish.assert_public(LADDER_PUBLIC, "ladder")  # the ladder block carries no answer fields


def test_kv_entry_carries_hint_mults_only_for_ladder_rounds():
    private = {
        "date": "2026-10-20",
        "scoring": {"free_km": 150, "scale_km": 2500, "hint_mult": 0.7, "earth_radius_km": 6371.0088},
        "rounds": [
            {"round": 1, "lat": 1.5, "lon": 2.5, "stats": {}, "crop": {}},
            {"round": 5, "lat": 3.5, "lon": 4.5, "stats": {}, "crop": {}, "hint_mults": [1.0, 0.85, 0.6]},
        ],
    }
    doc = json.loads(publish.kv_entry(private)["value"])
    assert doc["rounds"][0] == {"round": 1, "lat": 1.5, "lon": 2.5}
    assert doc["rounds"][1] == {"round": 5, "lat": 3.5, "lon": 4.5, "hint_mults": [1.0, 0.85, 0.6]}
