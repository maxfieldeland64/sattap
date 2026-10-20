# SatTap POC backend

Turns GeoColor full-disk imagery from GOES-East (GOES-19), GOES-West (GOES-18) and Meteosat-12 (0°)
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
3. Confirm sub-satellite longitudes in `sattap/config.py` (GOES-East 75.2 W, GOES-West 137.0 W, Meteosat 0).

## Web app

`uvicorn sattap.api:app --reload` also serves a small mobile-first web app at
`http://127.0.0.1:8000/` (vanilla JS + a d3-geo globe, no build step, files in `web/`).

- `/` is the landing page: a looping full-disk GOES-West view, today's leaderboard, and a button
  into the game (it reads "Continue" or "See your result" once you have started or finished).
  The loop is built by the daily `build` from the same cached frames as the puzzle
  (`sattap/landing.py`). The leaderboard section hides itself where `/api/leaderboard` is not
  available (the local FastAPI server).
- `/play/` is the game itself. It
  loads the current game day's puzzle (rolls over at 18:00 UTC), or the latest built one if it
  does not exist yet (`?date=YYYY-MM-DD` loads a specific day).
- The map is a 3D globe (`web/globe.js`, drawn on a canvas with d3-geo's orthographic projection;
  d3 is vendored in `web/vendor/`, so there is no CDN dependency for it). Drag to spin (it keeps
  a little momentum), scroll or pinch to zoom toward the cursor or your fingers, tap to drop a
  pin. Arrow keys spin, `+`/`-` zoom, Enter pins the centre; on-screen +, - and reset buttons
  too. North always stays up. Each round opens centred on the satellite that took the picture.
- **Lock in** scores the pin through `/api/guess`; the reveal frames your guess, the answer and
  the crop's footprint on the globe, and a summary screen offers a copy-able result.
- Progress is saved in `localStorage` per date, so a reload resumes instead of replaying.
- The globe has no tile server: it draws Natural Earth 50m land polygons (`web/land.geojson`) and
  country borders (`web/borders.geojson`, built by `tools/make_borders.mjs`; both public domain)
  over a flat ocean, so there are no API keys. Country names (`web/countries.json`, built by
  `tools/make_country_labels.mjs`; names follow Natural Earth) show only where they fit inside
  their country at the current zoom, so zooming in reveals more; the **Aa** button turns them off
  (remembered on the device). On landscape screens at least 900 px wide
  the image and globe sit side by side; phones and portrait tablets stay stacked.

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
  sources.py   GeoColor fetch: GOES from the NOAA STAR CDN, Meteosat from EUMETSAT EUMETView;
               plus GOES Band 13 from the same CDN for the last round
  b13.py       the Band 13 round: finds an open-ocean convective cell in the enhanced image
  crops.py     candidate crop sampling
  filters.py   playability filter + difficulty heuristic (uses a real land mask)
  puzzle.py    builds the daily puzzle (4 GeoColor rounds across the difficulty range + the Band 13 round)
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
`LOOP_*` in `sattap/config.py`. A fetch is ~12 full-disk GeoColor JPEGs (~180 MB) plus ~12 GOES Band 13 JPEGs
(~10 MB each, for the last round); a build takes under a minute.
Animated WebP is supported by current Safari, Chrome and Firefox; there is no JS frame-cycler fallback yet.

### Building outside daylight hours

The CDN keeps history, so you can build from an earlier daytime hour at any time:

```bash
python3 -m sattap.cli fetch --at 17:00        # loop ending 17:00 UTC today (or --at 2026-10-16T17:00)
python3 -m sattap.cli build --at 17:00
```

## The Band 13 round

The last round is a Band 13 (10.3 um, "clean window" IR) challenge. The picture is the NOAA STAR
CDN's enhanced Band 13 image: warm surfaces stay grey and cold cloud tops are coloured blue, green,
yellow, red as they get colder. The answer is the strongest cold-top core in the crop, so the pin
says "where is this cell?".

The CDN burns coastlines and country borders into that image, so a crop with land in it would hand
over the answer. Only open-ocean crops are used (`window_has_land`, with a margin), which also means
the shoreline-matching skill is useless here; players have to read cloud regimes, cell structure and
timing, and use the hints for geography:

| Level | What the player sees | Score multiplier |
|---|---|---|
| 0 | Band 13 close-up (animated loop) | 1.0 |
| 1 | + the GeoColor layer of the same scene, with a Band 13 / GeoColor switch | 0.85 |
| 2 | + the 3x-wider view of either layer, crop outlined (shows the coast) | 0.6 |

The level is sent as `hint_level` to `/api/guess`; the multipliers live in the private answers
(`hint_mults`), so the Function and FastAPI both apply the server's copy. Band 13 comes only from the
GOES CDN (Meteosat has no equivalent source here yet), so if a satellite has no Band 13 for the
puzzle frame or no ocean cell qualifies, the day is five GeoColor rounds.

Not calibrated: the CDN JPEGs carry a colour enhancement, not brightness temperatures, so the build
ranks cloud tops by the colour ramp. Real temperatures (Level 2 CMI from the NOAA AWS buckets) would
allow rounds like "estimate the temperature here".

## Playability filter

These apply to the four GeoColor rounds. Candidates are rejected unless they are in full daylight (solar elevation >= 15 degrees at every
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

- `B13_*`: the Band 13 round. `B13_CROP_HALF_PX` (crop size), `B13_COAST_MARGIN` (how far from any
  land the crop must be), `B13_MIN_PEAK` / `B13_*_COLORED_FRAC` (what counts as a good cell),
  `B13_HINT_MULTS` (score multiplier per hint level, default 1.0 / 0.85 / 0.6).

Build timing matters: run the daily build when most of the disk is sunlit (roughly 15-19 UTC).
At 23:30 UTC GOES-East is mostly dusk and GOES-West is mostly open ocean, so almost nothing passes
the filters.

## Known gaps (on purpose, for the POC)

- Difficulty is a color-based heuristic (cloud fraction + coastline), not learned from players.
- Night-side crops are excluded by brightness rather than handled.
- Scoring answers are not rate limited, so a player can re-guess a round via the API.
- Guess requests are not rate limited (see docs/DEPLOY.md for the Cloudflare-side fix).


## Meteosat (Europe, Africa, the Atlantic)

Meteosat-12 (MTG-I1, 0 degrees) comes from EUMETSAT's public **EUMETView** WMS
(`mtg_fd:rgb_geocolour`), with no account or API key. One GetMap request returns the whole disk in
the geostationary projection, so it goes through the same crop and scoring code as GOES.

- Frames are 4608 px (about 2.4 km per pixel). The service returns an empty image for bigger
  requests (5600 px, the native 2 km size), so this is a little coarser than GOES.
- A request for a time after the layer's newest frame comes back empty, so `sources.py` reads the
  newest time from GetCapabilities and never asks past it. Archive back to 2024-09 is available.
- Geometry (`geo.py`) was checked by overlaying Natural Earth coastlines on a real frame: they
  line up to a few pixels. Re-run `python -m sattap.cli check-geo` if EUMETSAT changes the layer.
- If EUMETView is down, `fetch` logs it and the puzzle builds from the satellites that worked.
- EUMETView imagery is credited "(c) EUMETSAT" on the landing page.
