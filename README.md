# SatTap POC backend

Turns CIRA GeoColor full-disk imagery from GOES-East (GOES-19) and GOES-West (GOES-18)
into a daily "Where is this?" puzzle: 5 cropped satellite tiles with known answer
coordinates, plus a tiny API to serve them and score guesses.

Scope for this POC: **where** rounds only.

## Setup (macOS / Linux)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Offline smoke test (no network needed)

```bash
python -m pytest -q tests
python -m sattap.cli synth                 # fake full-disk images with real land/ocean geometry
python -m sattap.cli build --date 2026-10-16
uvicorn sattap.api:app --reload            # then open http://127.0.0.1:8000/api/puzzle/2026-10-16
```

## Live data

```bash
python -m sattap.cli check-geo             # prints pixel coords for known landmarks
python -m sattap.cli fetch                 # downloads the last hour (6 frames, 10 min apart) of 5424x5424 GeoColor, East + West
python -m sattap.cli build                 # builds today's (UTC) puzzle from the newest cached frames
```

Validated against live data on 2026-10-16: the CDN listing/filename pattern works, and the
geostationary geometry lines up with a land mask to within ~10 px (about 20 km) on both
satellites, so no constants needed adjusting. If NOAA changes anything, re-run this check:

1. `check-geo` prints the pixel for a landmark (Baja tip on West, Florida Keys on East).
   Open the downloaded full-disk JPEG at that pixel and confirm it lands on the landmark.
   If it is off by a constant amount, adjust `FD_HALF_EXTENT_RAD` in `sattap/config.py`
   (the JPEGs may be padded or slightly cropped).
2. Confirm the CDN directory listing still matches the filename regex in
   `sattap/sources.py` (`YYYYDDDHHMM_GOES19-ABI-FD-GEOCOLOR-5424x5424.jpg`).
3. Confirm sub-satellite longitudes in `sattap/config.py` (GOES-East 75.2 W, GOES-West 137.0 W).

## Web app

`uvicorn sattap.api:app --reload` also serves a small mobile-first web app at
`http://127.0.0.1:8000/` (vanilla JS + Leaflet, no build step, files in `web/`).

- Loads the current game day's puzzle (rolls over at 18:00 UTC), or the latest built one if it
  does not exist yet (`?date=YYYY-MM-DD` loads a specific day).
- Tap the map to place a pin, **Lock in** scores it through `/api/guess`, the reveal shows
  distance, score, and the crop footprint, and a summary screen offers a copy-able result.
- Progress is saved in `localStorage` per date, so a reload resumes instead of replaying.
- The map has no tile server: it draws Natural Earth 50m land polygons (`web/land.geojson`,
  public domain) over a flat ocean, so there are no labels, borders, or API keys.
  (CARTO's free dark_nolabels tiles now require an API key, which is why this is bundled.)
  Leaflet itself loads from cdnjs.

## API

| Route | Purpose |
|---|---|
| `GET /puzzles/{YYYY-MM-DD}.json`, `/puzzles/latest.json` | puzzle for a date / the newest one, **no answers** (static files on Cloudflare) |
| `GET /api/puzzle/today` | the current game day's puzzle (rolls over at 18:00 UTC), FastAPI only |
| `POST /api/guess` | `{date, round, lat, lon}` -> `{distance_km, score, answer}` |
| `GET /images/{date}/r{n}.jpg` | crop images |

Answers live in `data/private/` and are only returned by `/api/guess`.

## Deploying

Production setup is Cloudflare Pages (static site + one Function) with a daily GitHub Action that
builds the puzzle and deploys it. Step-by-step: [docs/DEPLOY.md](docs/DEPLOY.md).

Local pieces: `npm test` (Function tests), `tools/publish.py` (assembles `dist/` and the KV payload),
`npm run dev` (Pages + Function + local KV). `?fresh=1` on any puzzle URL clears that day's saved game.

## Layout

```
sattap/
  config.py    constants and tunables (crop sizes, filter thresholds, score scale)
  geo.py       fixed-grid <-> lon/lat, haversine
  sources.py   CIRA GeoColor fetch from NOAA STAR CDN
  crops.py     candidate crop sampling
  filters.py   playability filter + difficulty heuristic (uses a real land mask)
  puzzle.py    builds the daily puzzle (5 rounds across the difficulty range)
  scoring.py   distance -> score
  synth.py     synthetic full-disk images for offline dev
  api.py       FastAPI app
  cli.py       fetch / build / synth / check-geo
tests/
```

## Loops

Each round is a looping animation of the last hour (6 frames, 10 minutes apart) instead of a single
frame. The same crop box is cut from every frame, so the scene stays registered and only the clouds
(and light) move. Output per round under `data/images/{date}/`:

- `r{n}.webp` / `r{n}_ctx.webp`: animated close-up and 3x-wider hint loops (plain `<img>`, no JS player)
- `r{n}.jpg` / `r{n}_ctx.jpg`: stills of the last frame (reveal screen, and the fallback if a loop is missing)

If fewer than two frames are cached for a satellite the build falls back to stills. Tunables are
`LOOP_*` in `sattap/config.py`. A fetch is ~12 full-disk JPEGs (~180 MB); a build takes under a minute.
Animated WebP is supported by current Safari, Chrome and Firefox; there is no JS frame-cycler fallback yet.

### Building outside daylight hours

The CDN keeps history, so you can build from an earlier daytime hour at any time:

```bash
python3 -m sattap.cli fetch --at 17:00        # loop ending 17:00 UTC today (or --at 2026-10-16T17:00)
python3 -m sattap.cli build --at 17:00
```

## Playability filter

Candidates are rejected unless they are in full daylight (solar elevation >= 15 degrees at every
sampled point, so no terminator crops), contain at least 12% land, are under 80% cloud, and are
not featureless. Difficulty is a mix of cloud cover and how coastal the crop is.

`web/land.geojson` was built from Natural Earth 50m land (`world-atlas` on npm), then run
through `tools/split_antimeridian.py` to remove polygon edges that wrap across 180 degrees.

## Tuning knobs worth playing with

- `CROP_HALF_PX_CHOICES`: zoom level (bigger crop = more context = easier)
- `MIN_LAND_FRAC` / `MAX_CLOUD_FRAC`: what counts as playable
- `DIFFICULTY_QUANTILES`: how the 5 rounds ramp
- `SCORE_FREE_KM` / `SCORE_SCALE_KM`: how forgiving scoring is. Within the free radius you get 100,
  beyond it score = 100 * exp(-(distance - free) / scale). Defaults 150 km / 2500 km
  (1,000 km off ~ 71, 3,000 km ~ 32, 6,000 km ~ 9).
- `HINT_SCORE_MULT` / `HINT_CONTEXT_FACTOR`: the optional hint swaps the close-up for a view
  3x wider with the crop outlined, and multiplies that round's score by 0.7. The penalty is
  applied server-side (`hint_used` on `/api/guess`) and remembered across reloads.

Build timing matters: run the daily build when most of the disk is sunlit (roughly 15-19 UTC).
At 23:30 UTC GOES-East is mostly dusk and GOES-West is mostly open ocean, so almost nothing passes
the filters.

## Known gaps (on purpose, for the POC)

- Difficulty is a color-based heuristic (cloud fraction + coastline), not learned from players.
- Night-side crops are excluded by brightness rather than handled.
- Scoring answers are not rate limited, so a player can re-guess a round via the API.
- Guess requests are not rate limited (see docs/DEPLOY.md for the Cloudflare-side fix).
