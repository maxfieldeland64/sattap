"""Tiny FastAPI app: serves today's puzzle (without answers) and scores guesses.

  GET  /api/puzzle/today        -> public puzzle JSON (UTC date)
  GET  /api/puzzle/{date}       -> same for a given YYYY-MM-DD
  POST /api/guess               -> {date, round, lat, lon} -> distance, score, answer
  GET  /images/...              -> crop images
  GET  /healthz

Answers live in data/private/*.json and are only revealed by /api/guess.
Run:  uvicorn sattap.api:app --reload
Env:  SATTAP_DATA (default ./data)
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config as C
from .gameday import game_day
from .scoring import ladder_mult, score_guess

DATA = Path(os.environ.get("SATTAP_DATA", "data"))

app = FastAPI(title="SatTap POC")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1024)  # land.geojson is ~900 KB raw
(DATA / "images").mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=DATA / "images"), name="images")


def _load(kind: str, day: str) -> dict:
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    path = DATA / kind / f"{day}.json"
    if not path.exists():
        raise HTTPException(404, f"No puzzle for {day}. Build one with `python -m sattap.cli build --date {day}`.")
    return json.loads(path.read_text())


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/puzzles/{name}")
def puzzle_static(name: str) -> dict:
    """Same URLs the Cloudflare deployment serves as static files: /puzzles/YYYY-MM-DD.json
    and /puzzles/latest.json."""
    if not name.endswith(".json"):
        raise HTTPException(404, "Not found")
    stem = name[: -len(".json")]
    if stem == "latest":
        return puzzle_latest()
    return _load("public", stem)


@app.get("/api/puzzle/today")
def puzzle_today() -> dict:
    return _load("public", game_day().isoformat())


@app.get("/api/puzzle/latest")
def puzzle_latest() -> dict:
    files = sorted((DATA / "public").glob("*.json"))
    if not files:
        raise HTTPException(404, "No puzzles built yet. Run `python -m sattap.cli build`.")
    return json.loads(files[-1].read_text())


@app.get("/api/puzzle/{day}")
def puzzle_for(day: str) -> dict:
    return _load("public", day)


class Guess(BaseModel):
    date: str
    round: int = Field(ge=1)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    hint_used: bool = False
    # Hint-ladder rounds (the Band 13 round): 0 = none, 1 = second layer, 2 = zoomed out.
    hint_level: int | None = Field(default=None, ge=0, le=9)


@app.post("/api/guess")
def guess(g: Guess) -> dict:
    private = _load("private", g.date)
    match = next((r for r in private["rounds"] if r["round"] == g.round), None)
    if match is None:
        raise HTTPException(404, "No such round")
    mults = match.get("hint_mults")
    if mults:
        # a ladder round: the level decides the penalty (a bare hint_used counts as level 1)
        level = g.hint_level if g.hint_level is not None else (1 if g.hint_used else 0)
        level = min(level, len(mults) - 1)
        mult, hint_used = ladder_mult(mults, level), level > 0
    else:
        level, mult, hint_used = None, None, g.hint_used
    distance_km, score = score_guess(g.lon, g.lat, match["lon"], match["lat"], hint_used, mult)
    return {
        "round": g.round,
        "distance_km": round(distance_km, 1),
        "score": score,
        "hint_used": hint_used,
        "hint_level": level,
        "hint_mult": mult if mult is not None else (C.HINT_SCORE_MULT if hint_used else 1.0),
        "answer": {"lat": match["lat"], "lon": match["lon"]},
    }


# Static web app at "/" (mounted last so the /api and /images routes win).
WEB = Path(__file__).resolve().parent.parent / "web"
if WEB.exists():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
