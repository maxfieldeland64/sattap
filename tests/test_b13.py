"""The Band 13 challenge: cell finding, hint-ladder scoring, and the build/publish plumbing."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from sattap import config as C
from sattap.b13 import coldness, find_peaks, pick_b13_round, window_has_land
from sattap.geo import FullDiskGrid
from sattap.puzzle import SourceImage
from sattap.scoring import ladder_mult, score_guess

T = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)  # local noon-ish for GOES-East


# ---- colour ramp -> coldness ------------------------------------------------

def test_coldness_follows_the_enhancement_ramp():
    px = np.array([[
        (120, 120, 120),  # grey: warm surface or low cloud
        (0, 0, 0),        # black: off the disk
        (30, 60, 200),    # blue: just cold enough to be coloured
        (40, 220, 60),    # green
        (250, 240, 40),   # yellow
        (230, 30, 20),    # red: the coldest tops
        (230, 30, 60),    # a red that leans magenta must not wrap around to "warm"
    ]], dtype=np.uint8)
    c = coldness(px)[0]
    assert c[0] == 0 and c[1] == 0
    assert c[2] < 0.15 < 0.4 < c[3] < 0.6 < c[4] < c[5]
    assert c[5] > 0.9 and c[6] > 0.9


def test_find_peaks_keeps_peaks_apart_and_strongest_first():
    f = np.zeros((100, 100), dtype=np.float32)
    f[20, 20], f[25, 22], f[70, 70] = 0.9, 0.8, 0.7  # the second is inside the first's exclusion zone
    valid = np.ones_like(f, dtype=bool)
    peaks = find_peaks(f, valid, min_peak=0.5, sep_px=10, max_peaks=5)
    assert [(c, r) for c, r, _ in peaks] == [(20, 20), (70, 70)]
    valid[70, 70] = False
    assert len(find_peaks(f, valid, 0.5, 10, 5)) == 1
    assert find_peaks(f, valid, 0.95, 10, 5) == []


# ---- picking a cell on a hand-made image ------------------------------------

def _blob_image(path: Path, size: int, lonlat: tuple[float, float], sat: str = "east") -> None:
    """Grey disk with one colourised cell (blue ring, green, yellow, red core) at lon/lat."""
    img = np.full((size, size, 3), 110, dtype=np.uint8)
    grid = FullDiskGrid(sat, size)
    col, row = grid.lonlat_to_pixel(*lonlat)
    yy, xx = np.indices((size, size))
    dist = np.hypot(xx - col, yy - row) * (1356 / size)
    for r, rgb in ((30, (30, 60, 200)), (24, (40, 220, 60)), (16, (250, 240, 40)), (8, (230, 30, 20))):
        img[dist <= r] = rgb
    Image.fromarray(img).save(path, quality=95)


def _source(tmp_path: Path, lonlat: tuple[float, float], sat: str = "east", size: int = 1356) -> SourceImage:
    p = tmp_path / "b13.jpg"
    _blob_image(p, size, lonlat, sat)
    src = SourceImage(sat, tmp_path / "gc.jpg", T)
    src.b13_loop = [(T, p)]
    return src


def test_picks_an_open_ocean_cell_and_centres_on_it(tmp_path):
    src = _source(tmp_path, (-45.0, 25.0))  # mid-Atlantic
    pick = pick_b13_round([src], np.random.default_rng(0))
    assert pick is not None and pick.sat_key == "east"
    # the answer is where the cell is (within a few analysis pixels, ~10-20 km)
    from sattap.geo import haversine_km
    assert haversine_km(pick.crop.lon, pick.crop.lat, -45.0, 25.0) < 80
    assert pick.peak >= C.B13_MIN_PEAK
    assert C.B13_MIN_COLORED_FRAC <= pick.colored_frac <= C.B13_MAX_COLORED_FRAC


def test_rejects_cells_over_land(tmp_path, capsys):
    # Amazon basin: the CDN draws borders there, so the crop would give the answer away
    assert pick_b13_round([_source(tmp_path, (-62.0, -8.0))], np.random.default_rng(0)) is None
    assert "no eligible cell" in capsys.readouterr().out.lower()  # and the build says why: "land 1"


def test_rejects_cells_near_a_coast(tmp_path):
    # ~100 km off the Florida coast: open water at the centre, but the margin sees land
    assert pick_b13_round([_source(tmp_path, (-78.5, 29.0))], np.random.default_rng(0)) is None


def test_rejects_night_side_cells(tmp_path):
    src = _source(tmp_path, (-45.0, 25.0))
    src.b13_loop = [(T.replace(hour=4), src.b13_loop[0][1])]  # 04:00 UTC: night at 45W
    assert pick_b13_round([src], np.random.default_rng(0)) is None


def test_keeps_away_from_other_rounds_answers(tmp_path):
    src = _source(tmp_path, (-45.0, 25.0))
    assert pick_b13_round([src], np.random.default_rng(0), avoid=[(-45.0, 25.0)]) is None
    assert pick_b13_round([src], np.random.default_rng(0), avoid=[(100.0, 0.0)]) is not None


def test_sources_without_band_13_are_skipped(tmp_path):
    src = SourceImage("meteo", tmp_path / "x.jpg", T)  # no b13_loop
    assert pick_b13_round([src], np.random.default_rng(0)) is None


def test_window_has_land_sees_coasts_and_limb():
    g = FullDiskGrid("east", 1356)
    col, row = (int(round(v)) for v in g.lonlat_to_pixel(-45.0, 25.0))
    assert not window_has_land(g, col, row, 40)
    col, row = (int(round(v)) for v in g.lonlat_to_pixel(-62.0, -8.0))
    assert window_has_land(g, col, row, 40)
    assert window_has_land(g, 5, 5, 20)  # off the disk counts as unusable


# ---- hint-ladder scoring ----------------------------------------------------

def test_ladder_mult_clamps_to_the_ladder():
    assert [ladder_mult(C.B13_HINT_MULTS, k) for k in (-1, 0, 1, 2, 3, 99)] == [1.0, 1.0, 0.85, 0.6, 0.6, 0.6]


def test_score_guess_with_a_ladder_multiplier():
    _, s0 = score_guess(-100, 30, -100, 30, hint_mult=1.0)
    _, s1 = score_guess(-100, 30, -100, 30, hint_mult=0.85)
    _, s2 = score_guess(-100, 30, -100, 30, hint_mult=0.6)
    assert (s0, s1, s2) == (100, 85, 60)
    # without a ladder multiplier the single-hint behaviour is unchanged
    assert score_guess(-100, 30, -100, 30, hint_used=True)[1] == 70
    assert score_guess(-100, 30, -100, 30)[1] == 100


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from sattap import api

    (tmp_path / "private").mkdir()
    private = {
        "date": "2026-10-20",
        "scoring": {"free_km": 150, "scale_km": 2500, "hint_mult": 0.7, "earth_radius_km": 6371.0088},
        "rounds": [
            {"round": 1, "lat": 30.0, "lon": -100.0},
            {"round": 2, "lat": 30.0, "lon": -100.0, "hint_mults": [1.0, 0.85, 0.6]},
        ],
    }
    (tmp_path / "private" / "2026-10-20.json").write_text(json.dumps(private))
    monkeypatch.setattr(api, "DATA", tmp_path)
    return TestClient(api.app)


def _guess(c, rnd, **extra):
    body = {"date": "2026-10-20", "round": rnd, "lat": 30.0, "lon": -100.0, **extra}
    r = c.post("/api/guess", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_api_ladder_levels_set_the_penalty(api_client):
    got = [_guess(api_client, 2, hint_level=k) for k in (0, 1, 2)]
    assert [g["score"] for g in got] == [100, 85, 60]
    assert [g["hint_level"] for g in got] == [0, 1, 2]
    assert [g["hint_used"] for g in got] == [False, True, True]
    assert [g["hint_mult"] for g in got] == [1.0, 0.85, 0.6]


def test_api_ladder_edge_cases(api_client):
    assert _guess(api_client, 2, hint_used=True)["hint_level"] == 1  # a bare hint_used is level 1
    assert _guess(api_client, 2, hint_level=7)["score"] == 60  # beyond the ladder clamps to the last rung
    assert _guess(api_client, 2, hint_used=False, hint_level=2)["hint_used"] is True  # the level wins
    assert api_client.post("/api/guess", json={"date": "2026-10-20", "round": 2, "lat": 0, "lon": 0, "hint_level": -1}).status_code == 422


def test_api_plain_rounds_ignore_hint_level(api_client):
    plain = _guess(api_client, 1, hint_level=2)
    assert (plain["score"], plain["hint_used"], plain["hint_level"]) == (100, False, None)
    hinted = _guess(api_client, 1, hint_used=True)
    assert (hinted["score"], hinted["hint_mult"]) == (70, 0.7)


# ---- sources and cache ------------------------------------------------------

def test_fetch_b13_frames_downloads_skips_and_caches(tmp_path, monkeypatch):
    import requests

    from sattap import sources

    ok_time, missing = T, T + timedelta(minutes=10)
    calls = []

    class Resp:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            if self.status != 200:
                raise requests.HTTPError(f"{self.status}")

        def iter_content(self, n):
            yield b"jpegbytes"

    def fake_get(url, **kw):
        calls.append(url)
        return Resp(404 if "1700" not in url and "1710" in url else 200)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    frames = sources.fetch_b13_frames("east", [ok_time, missing], tmp_path)
    assert [f.observed_at for f in frames] == [ok_time]
    assert frames[0].path.name == "20262931700_GOES19-ABI-FD-13-5424x5424.jpg"
    assert "/GOES19/ABI/FD/13/" in calls[0]
    assert not list(tmp_path.glob("*.part"))
    # a second run reuses the file and only asks again about the missing one
    calls.clear()
    sources.fetch_b13_frames("east", [ok_time, missing], tmp_path)
    assert len(calls) == 1
    # Meteosat has no Band 13
    assert sources.fetch_b13_frames("meteo", [ok_time], tmp_path) == []


def test_cached_sources_attach_band_13_only_when_the_still_has_it(tmp_path):
    from sattap import cli
    from sattap.sources import cache_name

    t0 = T - timedelta(minutes=10)
    for key, with_b13 in (("east", {T, t0}), ("west", {t0})):
        for t in (t0, T):
            (tmp_path / cache_name(key, t, 5424)).write_bytes(b"x")
        for t in with_b13:
            (tmp_path / cache_name(key, t, 5424, C.B13_PRODUCT)).write_bytes(b"x")
    (tmp_path / cache_name("meteo", T, 4608)).write_bytes(b"x")
    by_key = {s.sat_key: s for s in cli._cached_sources(tmp_path)}
    assert [t for t, _ in by_key["east"].b13_loop] == [t0, T]
    assert by_key["west"].b13_loop == []  # the puzzle frame has no Band 13, so no Band 13 round
    assert by_key["meteo"].b13_loop == []
    assert by_key["east"].loop and by_key["east"].observed_at == T  # Band 13 files never become sources


# ---- build + publish --------------------------------------------------------

@pytest.fixture(scope="module")
def synth_sources(tmp_path_factory):
    from sattap.sources import cache_name
    from sattap.synth import make_b13_disk, make_full_disk

    cache = tmp_path_factory.mktemp("synth")
    out = []
    for i, key in enumerate(C.SATELLITES):
        gc = cache / cache_name(key, T, 1356)
        make_full_disk(key, 1356, gc, seed=i)
        src = SourceImage(key, gc, T, loop=[(T, gc)])
        if key != "meteo":
            b13 = cache / cache_name(key, T, 1356, C.B13_PRODUCT)
            make_b13_disk(key, 1356, b13, seed=i)
            src.b13_loop = [(T, b13)]
        out.append(src)
    return out


def test_build_makes_the_last_round_a_band_13_ladder(synth_sources, tmp_path):
    from datetime import date

    from sattap.puzzle import build_daily

    pub = build_daily(date(2026, 10, 20), synth_sources, tmp_path, n_candidates=120)
    rounds = pub["rounds"]
    assert len(rounds) == C.N_ROUNDS
    assert all("ladder" not in r for r in rounds[:-1])
    last = rounds[-1]
    assert last["band"].startswith("B13") and last["satellite"] != "Meteosat-12"
    assert last["ladder"]["band"] == "GeoColor" and last["ladder"]["mults"] == list(C.B13_HINT_MULTS)
    for rel in (last["image"], last["hint_image"], last["ladder"]["image"], last["ladder"]["hint_image"]):
        assert (tmp_path / rel.lstrip("/")).exists(), rel
    priv = json.loads((tmp_path / "private" / "2026-10-20.json").read_text())["rounds"]
    assert priv[-1]["hint_mults"] == list(C.B13_HINT_MULTS) and "hint_mults" not in priv[0]
    assert json.dumps(pub).count("lat") == 0  # nothing about the answer in the public file


def test_build_falls_back_to_five_plain_rounds_without_band_13(synth_sources, tmp_path, capsys):
    from datetime import date

    from sattap.puzzle import build_daily

    plain = [SourceImage(s.sat_key, s.path, s.observed_at, loop=s.loop) for s in synth_sources]
    pub = build_daily(date(2026, 10, 20), plain, tmp_path, n_candidates=120)
    out = capsys.readouterr().out
    assert "no Band 13 round" in out and "GOES-19 17:00 UTC" in out and "fetch" in out  # says what to do
    assert len(pub["rounds"]) == C.N_ROUNDS
    assert all("ladder" not in r and r["band"] == "GeoColor" for r in pub["rounds"])


def test_build_falls_back_when_no_cell_qualifies(synth_sources, tmp_path, monkeypatch):
    from datetime import date

    from sattap import puzzle

    monkeypatch.setattr(puzzle, "pick_b13_round", lambda *a, **k: None)
    pub = puzzle.build_daily(date(2026, 10, 20), synth_sources, tmp_path, n_candidates=120)
    assert len(pub["rounds"]) == C.N_ROUNDS and all("ladder" not in r for r in pub["rounds"])
