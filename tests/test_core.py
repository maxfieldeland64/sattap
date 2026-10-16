import json
from datetime import date

import numpy as np
import pytest

from sattap import config as C
from sattap.geo import FullDiskGrid, haversine_km
from sattap.scoring import score_for_distance, score_guess
from sattap.sources import parse_listing


@pytest.mark.parametrize("key", ["east", "west"])
def test_center_is_subsatellite_point(key):
    g = FullDiskGrid(key, C.FD_SIZE_2KM)
    mid = (g.size - 1) / 2
    lon, lat = g.pixel_to_lonlat(mid, mid)
    assert lon == pytest.approx(g.lon0, abs=0.01)
    assert lat == pytest.approx(0.0, abs=0.01)


@pytest.mark.parametrize("key", ["east", "west"])
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
