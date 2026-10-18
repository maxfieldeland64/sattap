"""The landing page's full-disk GOES-West loop.

Built from the same cached frames as the puzzle (the last hour, 10 minutes apart), shrunk to a
web-friendly size. Written to data/images/landing/ with the game date in the name, because
/images/* is served with a one-year immutable cache.
"""
from __future__ import annotations

from datetime import date as Date
from pathlib import Path

from PIL import Image

from . import config as C
from .puzzle import SourceImage, save_loop

Image.MAX_IMAGE_PIXELS = None


def _shrink(path: Path, size: int) -> Image.Image:
    img = Image.open(path)
    img.draft("RGB", (size, size))  # JPEG decodes at 1/2, 1/4 or 1/8 scale: far less memory than 5424 px
    img = img.convert("RGB")
    return img.resize((size, size), Image.Resampling.LANCZOS) if img.size != (size, size) else img


def build_landing(sources: list[SourceImage], day: Date, data_dir: Path, size: int = C.LANDING_SIZE_PX) -> dict | None:
    """Write the GOES-West loop (plus a still for reduced-motion) and return its public metadata,
    or None when there are no West frames cached (e.g. only East was fetched)."""
    west = next((s for s in sources if s.sat_key == "west"), None)
    if west is None:
        return None
    frames = west.loop or [(west.observed_at, west.path)]

    out_dir = data_dir / "images" / "landing"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = day.isoformat()

    shrunk = [(t, _shrink(p, size)) for t, p in frames]
    still_rel = f"landing/{stem}.jpg"
    shrunk[-1][1].save(data_dir / "images" / still_rel, quality=85)
    loop_rel = None
    if len(shrunk) > 1:
        loop_rel = f"landing/{stem}.webp"
        save_loop([im for _, im in shrunk], data_dir / "images" / loop_rel, quality=C.LANDING_WEBP_QUALITY)

    return {
        "satellite": C.SATELLITES["west"]["name"],
        "image": f"/images/{still_rel}",
        "loop": f"/images/{loop_rel}" if loop_rel else None,
        "frame_times": [t.isoformat() for t, _ in shrunk],
    }
