"""Split polygon rings that jump across the antimeridian into separate closed rings.

Natural Earth land (via world-atlas/topojson) is cut at +/-180, which shows up as ring edges
that leap from -180 to +180. Drawn as-is, the fill between two such edges paints a full-width
band. Cutting each ring at those jumps and closing every piece on its own fixes that.

Usage: python tools/split_antimeridian.py web/land.geojson
"""
from __future__ import annotations

import json
import sys

JUMP = 180.0  # a longitude step bigger than this is a wrap, not a real edge


def split_ring(ring: list[list[float]]) -> list[list[list[float]]]:
    pts = ring[:-1] if ring[0] == ring[-1] else ring[:]
    n = len(pts)
    cuts = [i for i in range(n) if abs(pts[(i + 1) % n][0] - pts[i][0]) > JUMP]
    if not cuts:
        return [ring]
    out = []
    for k, start in enumerate(cuts):
        end = cuts[(k + 1) % len(cuts)]
        seg = []
        i = (start + 1) % n
        while True:
            seg.append(pts[i])
            if i == end:
                break
            i = (i + 1) % n
        if len(seg) >= 3:
            out.append(seg + [seg[0]])
    return out


def fix_polygon(poly: list) -> list[list]:
    """A polygon is [outer, hole, ...]. Returns a list of polygons."""
    outer_parts = split_ring(poly[0])
    if len(outer_parts) == 1 and outer_parts[0] is poly[0]:
        return [poly]
    # holes do not cross the antimeridian in this dataset, so keep them out of the cut pieces
    return [[part] for part in outer_parts]


def main(path: str) -> None:
    g = json.load(open(path))
    feats = g["features"] if g["type"] == "FeatureCollection" else [g]
    for f in feats:
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        fixed = []
        for poly in polys:
            fixed.extend(fix_polygon(poly))
        f["geometry"] = {"type": "MultiPolygon", "coordinates": fixed}
    json.dump(g, open(path, "w"), separators=(",", ":"))
    left = 0
    for f in feats:
        for poly in f["geometry"]["coordinates"]:
            for ring in poly:
                left += sum(1 for a, b in zip(ring, ring[1:]) if abs(a[0] - b[0]) > JUMP)
    print(f"wrote {path}; remaining wrap edges: {left}")


if __name__ == "__main__":
    main(sys.argv[1])
