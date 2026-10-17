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
