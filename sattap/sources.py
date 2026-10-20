"""Fetching full-disk GeoColor images: GOES from the NOAA STAR CDN, Meteosat from EUMETView.

URL layout (as published by NOAA STAR):
  {CDN}/{GOES19|GOES18}/ABI/FD/GEOCOLOR/            <- HTML directory listing
  {CDN}/.../YYYYDDDHHMM_GOES19-ABI-FD-GEOCOLOR-5424x5424.jpg
  {CDN}/{GOES19|GOES18}/ABI/FD/13/YYYYDDDHHMM_GOES19-ABI-FD-13-5424x5424.jpg   <- Band 13, same grid

Meteosat (MTG FCI) comes from EUMETSAT's public EUMETView WMS: one GetMap request per frame,
asking for the whole disk in the geostationary projection (no account or API key). Frames are
saved in the cache as YYYYDDDHHMM_MTG0-FCI-FD-GEOCOLOR-{size}x{size}.jpg.

Not verified from the build sandbox (no access to the CDN there), so run
`python -m sattap.cli fetch` on a machine with network access first.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import config as C

_NAME_RE = re.compile(r"(\d{11})_(GOES\d+)-ABI-FD-GEOCOLOR-(\d+)x(\d+)\.jpg")
# Cached file names for every source (GOES ABI and Meteosat FCI).
CACHE_NAME_RE = re.compile(r"(\d{11})_([A-Z0-9]+)-(?:ABI|FCI)-FD-GEOCOLOR-(\d+)x(\d+)\.jpg")
# Cached Band 13 (clean IR) frames, GOES only.
B13_NAME_RE = re.compile(r"(\d{11})_(GOES\d+)-ABI-FD-" + re.escape(C.B13_PRODUCT) + r"-(\d+)x(\d+)\.jpg")
_HEADERS = {"User-Agent": "sattap-poc/0.1 (hobby project)"}


@dataclass
class Frame:
    sat_key: str
    url: str
    observed_at: datetime
    path: Path | None = None


def is_eumetview(sat_key: str) -> bool:
    return C.SATELLITES[sat_key].get("source") == "eumetview"


def cache_name(sat_key: str, observed_at: datetime, size: int, product: str = "GEOCOLOR") -> str:
    sat = C.SATELLITES[sat_key]
    instrument = "FCI" if is_eumetview(sat_key) else "ABI"
    return f"{observed_at:%Y%j%H%M}_{sat['slug']}-{instrument}-FD-{product}-{size}x{size}.jpg"


def has_b13(sat_key: str) -> bool:
    """Band 13 comes from the NOAA STAR CDN, so only the GOES satellites have it."""
    return not is_eumetview(sat_key)


def b13_url(sat_key: str, when: datetime, size: int = C.GEOCOLOR_SIZE) -> str:
    slug = C.SATELLITES[sat_key]["slug"]
    return f"{C.STAR_CDN}/{slug}/ABI/FD/{C.B13_PRODUCT}/{when:%Y%j%H%M}_{slug}-ABI-FD-{C.B13_PRODUCT}-{size}x{size}.jpg"


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


# ---- Meteosat via EUMETView ------------------------------------------------

def eumetview_latest() -> datetime:
    """Newest observation time the WMS can serve (the layer's default time dimension)."""
    r = requests.get(
        C.EUMETVIEW_WMS,
        params={"service": "WMS", "request": "GetCapabilities", "version": "1.3.0"},
        headers=_HEADERS,
        timeout=C.HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    m = re.search(r'<Name>' + re.escape(C.EUMETVIEW_LAYER) + r'</Name>.*?<Dimension name="time"[^>]*default="([^"]+)"', r.text, re.S)
    if not m:
        raise RuntimeError(f"EUMETView has no time dimension for {C.EUMETVIEW_LAYER}")
    return datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def eumetview_params(when: datetime, size: int = C.EUMETVIEW_SIZE_PX) -> dict:
    e = C.EUMETVIEW_HALF_EXTENT_M
    return {
        "service": "WMS", "version": "1.3.0", "request": "GetMap",
        "layers": C.EUMETVIEW_LAYER, "styles": "", "format": "image/jpeg", "transparent": "false",
        "exceptions": "INIMAGE", "crs": "AUTO:97004,9001,0,0",
        "bbox": f"{-e:.0f},{-e:.0f},{e:.0f},{e:.0f}", "width": size, "height": size,
        "time": f"{when:%Y-%m-%dT%H:%M:%S}Z",
    }


def eumetview_download(sat_key: str, when: datetime, cache_dir: Path, size: int = C.EUMETVIEW_SIZE_PX) -> Frame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / cache_name(sat_key, when, size)
    if not dest.exists():
        last: Exception | None = None
        for _ in range(3):
            try:
                r = requests.get(C.EUMETVIEW_WMS, params=eumetview_params(when, size), headers=_HEADERS, timeout=C.EUMETVIEW_TIMEOUT_S)
                r.raise_for_status()
                # a refused request still answers 200 with an empty body or an XML/text error
                if "image/jpeg" not in r.headers.get("content-type", "") or len(r.content) < 50_000:
                    raise RuntimeError(f"EUMETView returned no image for {when:%Y-%m-%d %H:%M} UTC ({len(r.content)} bytes)")
                tmp = dest.with_suffix(".part")
                tmp.write_bytes(r.content)
                tmp.replace(dest)
                last = None
                break
            except (requests.RequestException, RuntimeError) as e:
                last = e
        if last is not None:
            raise RuntimeError(str(last))
    return Frame(sat_key, f"{C.EUMETVIEW_WMS}?time={when:%Y-%m-%dT%H:%M}Z", when, dest)


def eumetview_slots(newest: datetime, n: int) -> list[datetime]:
    """n slots 10 minutes apart ending at `newest` (rounded down to a slot), oldest first."""
    newest = newest.replace(minute=newest.minute - newest.minute % C.EUMETVIEW_STEP_MIN, second=0, microsecond=0)
    return [newest - timedelta(minutes=C.EUMETVIEW_STEP_MIN * k) for k in range(n - 1, -1, -1)]


def eumetview_loop(sat_key: str, cache_dir: Path, n: int, at: datetime | None) -> list[Frame]:
    latest = eumetview_latest()
    end = min(at, latest) if at is not None else latest
    slots = eumetview_slots(end, n)

    def one(t: datetime) -> Frame | None:
        try:
            return eumetview_download(sat_key, t, cache_dir)
        except RuntimeError as e:
            print(f"  skipping {t:%H:%M} UTC: {e}")
            return None

    with ThreadPoolExecutor(max_workers=3) as pool:
        frames = [f for f in pool.map(one, slots) if f is not None]
    if not frames:
        raise RuntimeError(f"No EUMETView frames for {C.SATELLITES[sat_key]['name']} at or before {end:%Y-%m-%d %H:%M} UTC")
    return frames


def latest_frame(sat_key: str, size: int = C.GEOCOLOR_SIZE) -> Frame:
    if is_eumetview(sat_key):
        t = eumetview_latest()
        return Frame(sat_key, f"{C.EUMETVIEW_WMS}?time={t:%Y-%m-%dT%H:%M}Z", t)
    base = listing_url(sat_key)
    r = requests.get(base, headers=_HEADERS, timeout=C.HTTP_TIMEOUT_S)
    r.raise_for_status()
    items = parse_listing(r.text, size)
    if not items:
        raise RuntimeError(f"No {size}x{size} GeoColor files found at {base}")
    t, name = items[-1]
    return Frame(sat_key=sat_key, url=base + name, observed_at=t)


def download(frame: Frame, cache_dir: Path) -> Frame:
    if is_eumetview(frame.sat_key):
        return eumetview_download(frame.sat_key, frame.observed_at, cache_dir)
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


def loop_frames(
    sat_key: str,
    n: int = C.LOOP_FRAMES,
    step_min: int = C.LOOP_STEP_MIN,
    size: int = C.GEOCOLOR_SIZE,
    at: datetime | None = None,
) -> list[Frame]:
    """The newest frame (at or before `at`, if given) plus up to n-1 earlier ones at
    step_min spacing, oldest first.

    Missing slots (the CDN occasionally skips a scan) are skipped rather than substituted,
    so the loop can come back shorter than n.
    """
    if is_eumetview(sat_key):
        return eumetview_loop_frames(sat_key, n, at)
    base = listing_url(sat_key)
    r = requests.get(base, headers=_HEADERS, timeout=C.HTTP_TIMEOUT_S)
    r.raise_for_status()
    items = parse_listing(r.text, size)
    if at is not None:
        items = [it for it in items if it[0] <= at]
    if not items:
        raise RuntimeError(f"No {size}x{size} GeoColor files found at {base}" + (f" at or before {at:%Y-%m-%d %H:%M} UTC" if at else ""))
    by_time = dict(items)
    newest = items[-1][0]
    want = [newest - timedelta(minutes=step_min * k) for k in range(n - 1, -1, -1)]
    return [Frame(sat_key, base + by_time[t], t) for t in want if t in by_time]


def eumetview_loop_frames(sat_key: str, n: int, at: datetime | None) -> list[Frame]:
    latest = eumetview_latest()
    end = min(at, latest) if at is not None else latest
    return [Frame(sat_key, f"{C.EUMETVIEW_WMS}?time={t:%Y-%m-%dT%H:%M}Z", t) for t in eumetview_slots(end, n)]


def fetch_loop(sat_key: str, cache_dir: Path, n: int = C.LOOP_FRAMES, at: datetime | None = None) -> list[Frame]:
    if is_eumetview(sat_key):
        return eumetview_loop(sat_key, cache_dir, n, at)
    return [download(f, cache_dir) for f in loop_frames(sat_key, n, at=at)]


def fetch_b13_frames(sat_key: str, times: list[datetime], cache_dir: Path, size: int = C.GEOCOLOR_SIZE) -> list[Frame]:
    """Band 13 full disks for the given observation times (the GeoColor loop's own timestamps).

    Band 13 and GeoColor share a 10-minute cadence, so the times line up. A frame the CDN does
    not have (or that fails to download) is skipped; the round simply uses the frames that exist.
    """
    if not has_b13(sat_key):
        return []
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: list[Frame] = []
    for t in times:
        url = b13_url(sat_key, t, size)
        dest = cache_dir / cache_name(sat_key, t, size, C.B13_PRODUCT)
        if not dest.exists():
            tmp = dest.with_suffix(".part")
            try:
                with requests.get(url, headers=_HEADERS, timeout=C.HTTP_TIMEOUT_S, stream=True) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                tmp.replace(dest)
            except requests.RequestException as e:
                tmp.unlink(missing_ok=True)
                print(f"  no Band 13 for {C.SATELLITES[sat_key]['name']} {t:%H:%M} UTC: {e}")
                continue
        out.append(Frame(sat_key, url, t, dest))
    return out
