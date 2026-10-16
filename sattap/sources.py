"""Fetching CIRA GeoColor full-disk JPEGs from the NOAA STAR CDN.

URL layout (as published by NOAA STAR):
  {CDN}/{GOES19|GOES18}/ABI/FD/GEOCOLOR/            <- HTML directory listing
  {CDN}/.../YYYYDDDHHMM_GOES19-ABI-FD-GEOCOLOR-5424x5424.jpg

Not verified from the build sandbox (no access to the CDN there), so run
`python -m sattap.cli fetch` on a machine with network access first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import config as C

_NAME_RE = re.compile(r"(\d{11})_(GOES\d+)-ABI-FD-GEOCOLOR-(\d+)x(\d+)\.jpg")
_HEADERS = {"User-Agent": "sattap-poc/0.1 (hobby project)"}


@dataclass
class Frame:
    sat_key: str
    url: str
    observed_at: datetime
    path: Path | None = None


def listing_url(sat_key: str) -> str:
    slug = C.SATELLITES[sat_key]["slug"]
    return f"{C.STAR_CDN}/{slug}/ABI/FD/GEOCOLOR/"


def parse_listing(html: str, size: int = C.GEOCOLOR_SIZE) -> list[tuple[datetime, str]]:
    """Return [(observed_at_utc, filename)] for the requested size, oldest first."""
    out = []
    for m in _NAME_RE.finditer(html):
        stamp, _sat, w, h = m.groups()
        if int(w) != size or int(h) != size:
            continue
        t = datetime.strptime(stamp, "%Y%j%H%M").replace(tzinfo=timezone.utc)
        out.append((t, m.group(0)))
    return sorted(set(out))


def latest_frame(sat_key: str, size: int = C.GEOCOLOR_SIZE) -> Frame:
    base = listing_url(sat_key)
    r = requests.get(base, headers=_HEADERS, timeout=C.HTTP_TIMEOUT_S)
    r.raise_for_status()
    items = parse_listing(r.text, size)
    if not items:
        raise RuntimeError(f"No {size}x{size} GeoColor files found at {base}")
    t, name = items[-1]
    return Frame(sat_key=sat_key, url=base + name, observed_at=t)


def download(frame: Frame, cache_dir: Path) -> Frame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / Path(frame.url).name
    if not dest.exists():
        tmp = dest.with_suffix(".part")
        with requests.get(frame.url, headers=_HEADERS, timeout=C.HTTP_TIMEOUT_S, stream=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        tmp.replace(dest)
    frame.path = dest
    return frame


def fetch_latest(sat_key: str, cache_dir: Path) -> Frame:
    return download(latest_frame(sat_key), cache_dir)
