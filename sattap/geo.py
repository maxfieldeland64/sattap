"""Geostationary fixed-grid <-> lon/lat conversion for full-disk images (GOES ABI, Meteosat FCI)."""
from __future__ import annotations

import math

import numpy as np
from pyproj import CRS, Transformer

from . import config as C

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lon1, lat1, lon2, lat2):
    """Great-circle distance in km. Accepts scalars or numpy arrays."""
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


class FullDiskGrid:
    """Maps pixel (col, row) of a square full-disk image to lon/lat and back.

    GOES (source "star"): the image is assumed to span the ABI full-disk fixed grid, so pixel
    centers run from -FD_HALF_EXTENT_RAD to +FD_HALF_EXTENT_RAD in both axes, with row 0 at the
    north edge. Meteosat (source "eumetview"): the WMS image covers +-EUMETVIEW_HALF_EXTENT_M
    metres of the projection around the sub-satellite point. Both are assumptions about rendered
    JPEGs; validate with `python -m sattap.cli check-geo` against a known landmark.
    """

    def __init__(self, sat_key: str, size: int):
        sat = C.SATELLITES[sat_key]
        self.sat_key = sat_key
        self.sat_name = sat["name"]
        self.lon0 = sat["lon0"]
        self.size = int(size)
        # scan angle (radians) of pixel centre x = x0 + col * step; y = -x0 - row * step
        if sat.get("source") == "eumetview":
            self.step = 2 * C.EUMETVIEW_HALF_EXTENT_M / C.PERSPECTIVE_HEIGHT_M / self.size
            self.x0 = -C.EUMETVIEW_HALF_EXTENT_M / C.PERSPECTIVE_HEIGHT_M + self.step / 2
        else:
            self.step = 2 * C.FD_HALF_EXTENT_RAD / (self.size - 1)
            self.x0 = -C.FD_HALF_EXTENT_RAD
        crs_geos = CRS.from_proj4(
            f"+proj=geos +h={C.PERSPECTIVE_HEIGHT_M} +lon_0={self.lon0} "
            f"+sweep={sat.get('sweep', 'x')} +a={C.SEMI_MAJOR_M} +b={C.SEMI_MINOR_M} +units=m +no_defs"
        )
        self._fwd = Transformer.from_crs(crs_geos, CRS.from_epsg(4326), always_xy=True)
        self._inv = Transformer.from_crs(CRS.from_epsg(4326), crs_geos, always_xy=True)

    # -- scan angles --------------------------------------------------------
    def scan_angles(self, col, row):
        col = np.asarray(col, dtype=float)
        row = np.asarray(row, dtype=float)
        x = self.x0 + col * self.step
        y = -self.x0 - row * self.step
        return x, y

    def radial_frac(self, col, row):
        """Distance from disk center as a fraction of the Earth's angular radius."""
        x, y = self.scan_angles(col, row)
        return np.hypot(x, y) / C.EARTH_LIMB_RAD

    # -- conversions --------------------------------------------------------
    def pixel_to_lonlat(self, col, row):
        x, y = self.scan_angles(col, row)
        lon, lat = self._fwd.transform(x * C.PERSPECTIVE_HEIGHT_M, y * C.PERSPECTIVE_HEIGHT_M)
        lon = np.where(np.isfinite(lon), lon, np.nan)
        lat = np.where(np.isfinite(lat), lat, np.nan)
        if np.ndim(lon) == 0:
            return float(lon), float(lat)
        return lon, lat

    def lonlat_to_pixel(self, lon, lat):
        x_m, y_m = self._inv.transform(lon, lat)
        x = np.asarray(x_m, dtype=float) / C.PERSPECTIVE_HEIGHT_M
        y = np.asarray(y_m, dtype=float) / C.PERSPECTIVE_HEIGHT_M
        col = (x - self.x0) / self.step
        row = (-self.x0 - y) / self.step
        if np.ndim(col) == 0:
            return float(col), float(row)
        return col, row

    def pixel_width_km_at(self, col, row):
        """Approximate ground width of one pixel at (col, row), via east neighbor."""
        lon1, lat1 = self.pixel_to_lonlat(col, row)
        lon2, lat2 = self.pixel_to_lonlat(col + 1, row)
        if any(math.isnan(v) for v in (lon1, lat1, lon2, lat2)):
            return float("nan")
        return float(haversine_km(lon1, lat1, lon2, lat2))
