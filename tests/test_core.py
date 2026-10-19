import json
from datetime import date

import numpy as np
import pytest

from sattap import config as C
from sattap.geo import FullDiskGrid, haversine_km
from sattap.scoring import score_for_distance, score_guess
from sattap.sources import parse_listing


@pytest.mark.parametrize("key", ["east", "west", "meteo"])
def test_center_is_subsatellite_point(key):
    g = FullDiskGrid(key, C.FD_SIZE_2KM)
    mid = (g.size - 1) / 2
    lon, lat = g.pixel_to_lonlat(mid, mid)
    assert lon == pytest.approx(g.lon0, abs=0.01)
    assert lat == pytest.approx(0.0, abs=0.01)


@pytest.mark.parametrize("key", ["east", "west", "meteo"])
def test_roundtrip(key):
    g = FullDiskGrid(key, 1356)
    cols = np.array([300.0, 678.0, 900.0])
    rows = np.array([400.0, 700.0, 800.0])
    lon, lat = g.pixel_to_lonlat(cols, rows)
    c2, r2 = g.lonlat_to_pixel(lon, lat)
    assert np.allclose(c2, cols, atol=0.01) and np.allclose(r2, rows, atol=0.01)


def test_off_disk_is_nan():
    g = FullDiskGrid("east", 1356)
    lon, lat = g.pixel_to_lonlat(0, 0)
    assert np.isnan(lon) and np.isnan(lat)


def test_north_is_up():
    g = FullDiskGrid("east", 1356)
    _, lat_top = g.pixel_to_lonlat(678, 300)
    _, lat_bottom = g.pixel_to_lonlat(678, 1000)
    assert lat_top > lat_bottom


def test_pixel_size_near_2km_at_nadir():
    g = FullDiskGrid("east", C.FD_SIZE_2KM)
    mid = g.size // 2
    assert g.pixel_width_km_at(mid, mid) == pytest.approx(2.0, abs=0.1)


def test_scoring():
    assert score_for_distance(0) == 100
    assert score_for_distance(C.SCORE_FREE_KM) == 100
    assert score_for_distance(C.SCORE_FREE_KM + C.SCORE_SCALE_KM) == 37
    assert score_for_distance(20000) == 0
    d, s = score_guess(-105.0, 40.0, -105.0, 40.0)
    assert d == pytest.approx(0, abs=1e-6) and s == 100
    _, s_hint = score_guess(-105.0, 40.0, -105.0, 40.0, hint_used=True)
    assert s_hint == round(100 * C.HINT_SCORE_MULT)
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.2, abs=0.5)


def test_solar_elevation():
    from datetime import datetime, timezone
    from sattap.sun import solar_elevation_deg

    noon_equinox = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)  # solar noon at lon 0
    assert solar_elevation_deg(0.0, 0.0, noon_equinox) > 85  # near-zenith sun
    assert solar_elevation_deg(0.0, 180.0, noon_equinox) < -80  # opposite side is night
    # midsummer solstice, local solar noon at 40N: elevation = 90 - 40 + 23.4
    solstice = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    assert solar_elevation_deg(40.0, 0.0, solstice) == pytest.approx(73.4, abs=1.0)


def test_parse_listing():
    html = (
        '<a href="20262891600_GOES19-ABI-FD-GEOCOLOR-5424x5424.jpg">x</a>'
        '<a href="20262891610_GOES19-ABI-FD-GEOCOLOR-5424x5424.jpg">x</a>'
        '<a href="20262891610_GOES19-ABI-FD-GEOCOLOR-678x678.jpg">x</a>'
    )
    items = parse_listing(html, 5424)
    assert [n for _, n in items] == [
        "20262891600_GOES19-ABI-FD-GEOCOLOR-5424x5424.jpg",
        "20262891610_GOES19-ABI-FD-GEOCOLOR-5424x5424.jpg",
    ]
    assert items[-1][0].isoformat() == "2026-10-16T16:10:00+00:00"


def test_save_loop(tmp_path):
    from PIL import Image

    from sattap.puzzle import save_loop

    frames = [Image.new("RGB", (32, 32), (i * 30, 0, 0)) for i in range(4)]
    out = tmp_path / "x.webp"
    save_loop(frames, out)
    im = Image.open(out)
    assert im.n_frames == 4 and im.info.get("loop") == 0


def test_latest_solar_noon():
    from datetime import datetime, timezone
    from sattap.sun import latest_solar_noon

    now = datetime(2026, 10, 19, 17, 5, tzinfo=timezone.utc)
    east = latest_solar_noon(-75.2, now)  # noon ~17:01 UTC, already happened today
    assert east.date() == now.date() and east.hour == 17 and east <= now
    west = latest_solar_noon(-137.0, now)  # noon ~21:08 UTC, not yet today -> yesterday
    assert west.date() == date(2026, 10, 18) and west.hour == 21
    assert latest_solar_noon(-137.0, datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc)).date() == now.date()


def _cand(sat, difficulty, lon):
    from datetime import datetime, timezone
    from sattap.crops import Crop
    from sattap.filters import Stats
    from sattap.puzzle import Candidate, SourceImage

    src = SourceImage(sat, None, datetime(2026, 10, 19, 17, tzinfo=timezone.utc))
    crop = Crop(sat, 0, 0, 100, lon, 0.0, 800.0)
    return Candidate(crop, Stats(100, 30, 0.2, 0.5, 1.0, 40, difficulty), None, src)


def test_select_rounds_gives_each_satellite_its_minimum():
    from sattap.puzzle import select_rounds

    # East is plentiful and sits at every difficulty; West has only a few, all hard
    pool = [_cand("east", i / 40, -170 + i * 4) for i in range(40)]
    pool += [_cand("west", 0.8 + i * 0.02, 100 + i * 12) for i in range(4)]
    picked = select_rounds(pool, 5)
    assert len(picked) == 5
    assert sum(c.src.sat_key == "west" for c in picked) >= C.MIN_ROUNDS_PER_SAT
    assert sum(c.src.sat_key == "east" for c in picked) >= C.MIN_ROUNDS_PER_SAT
    assert [c.stats.difficulty for c in picked] == sorted(c.stats.difficulty for c in picked)


def test_select_rounds_single_satellite_unchanged():
    from sattap.puzzle import select_rounds

    pool = [_cand("east", i / 40, -170 + i * 8) for i in range(40)]
    assert len(select_rounds(pool, 5)) == 5


def test_eumetview_grid_matches_the_wms_extent():
    g = FullDiskGrid("meteo", C.EUMETVIEW_SIZE_PX)
    # the first and last pixel edges sit at +-EUMETVIEW_HALF_EXTENT_M, centres half a pixel inside
    x_edge = (g.x0 - g.step / 2) * C.PERSPECTIVE_HEIGHT_M
    assert x_edge == pytest.approx(-C.EUMETVIEW_HALF_EXTENT_M, abs=1.0)
    # Gibraltar lands where we measured it against the real image (col ~2112, row ~821 at 4608 px)
    col, row = g.lonlat_to_pixel(-5.35, 36.14)
    assert col == pytest.approx(2112, abs=6) and row == pytest.approx(821, abs=6)
    # limb: the Earth's edge sits at ~0.97 of the half extent, inside the image
    assert g.radial_frac(0, 0) > 1.0 and g.radial_frac(2303, 2303) < 0.01


def test_cache_names_round_trip():
    from datetime import datetime, timezone
    from sattap.sources import CACHE_NAME_RE, cache_name

    t = datetime(2026, 10, 19, 12, 20, tzinfo=timezone.utc)
    for key, slug, inst in (("east", "GOES19", "ABI"), ("meteo", "MTG0", "FCI")):
        name = cache_name(key, t, 1234)
        assert name == f"2026292" + "1220" + f"_{slug}-{inst}-FD-GEOCOLOR-1234x1234.jpg"
        m = CACHE_NAME_RE.fullmatch(name)
        assert m and m.group(2) == slug and int(m.group(3)) == 1234


def test_eumetview_slots_and_request():
    from datetime import datetime, timezone
    from sattap.sources import eumetview_params, eumetview_slots

    slots = eumetview_slots(datetime(2026, 10, 19, 12, 27, 31, tzinfo=timezone.utc), 3)
    assert [f"{t:%H:%M}" for t in slots] == ["12:00", "12:10", "12:20"]
    q = eumetview_params(slots[-1])
    assert q["layers"] == C.EUMETVIEW_LAYER and q["time"] == "2026-10-19T12:20:00Z"
    assert q["bbox"] == "-5600000,-5600000,5600000,5600000" and q["width"] == C.EUMETVIEW_SIZE_PX


def test_eumetview_refuses_empty_images(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from sattap import sources

    class Resp:
        headers = {"content-type": "image/jpeg"}
        content = b""

        def raise_for_status(self):
            pass

    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: Resp())
    with pytest.raises(RuntimeError, match="no image"):
        sources.eumetview_download("meteo", datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_select_rounds_three_satellites_each_get_one():
    from sattap.puzzle import select_rounds

    pool = [_cand("east", i / 60, -170 + i * 5) for i in range(60)]
    pool += [_cand("west", 0.6 + i * 0.02, 100 + i * 9) for i in range(5)]
    pool += [_cand("meteo", 0.7 + i * 0.02, -80 + i * 30) for i in range(5)]
    picked = select_rounds(pool, 5)
    assert {c.src.sat_key for c in picked} == {"east", "west", "meteo"}
