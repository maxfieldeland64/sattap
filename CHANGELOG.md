# Changelog

All notable changes to SatTap are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **Both satellites in every puzzle.** Each satellite now gets its own share of candidate crops
  and at least 2 of the 5 rounds (`MIN_ROUNDS_PER_SAT`); before, GOES-East supplied about 85% of
  rounds because the West disk is mostly ocean and morning light at build time. The build logs
  playable counts per satellite.
- **Frames come from around local solar noon** at each satellite's longitude instead of "now"
  (`SOLAR_NOON_CAPTURE`), so crops are sunny. At the 17:00 UTC build that is today for GOES-East
  and yesterday afternoon for GOES-West. Falls back to the newest frame if the CDN no longer has
  those. `fetch --at` still overrides.

### Added
- **Country names on the globe.** Names appear only where they fit inside their country at the
  current zoom, biggest first and never overlapping, so zooming in reveals more; they fade near the
  globe's edge. An **Aa** button turns them off (remembered on the device). Anchors come from
  `web/countries.json`, built by `tools/make_country_labels.mjs` from Natural Earth.

### Changed
- **The pin map is now a 3D globe.** Drag to spin (with momentum), scroll or pinch to zoom toward
  the cursor or fingers, tap to place a pin. North stays up, there are +/-/reset buttons and
  keyboard controls, and each round starts centred under the satellite that took the picture.
  The reveal flies to frame your guess, the answer and the crop's footprint. It replaces Leaflet
  with a canvas globe (`web/globe.js`) using vendored d3-geo and d3-array (`web/vendor/`, ISC),
  still on the bundled land and border data, so it needs no tiles, WebGL or API keys.
- The game moved from `/` to `/play/`. The SatTap name in the game's header links home.

### Added
- **Landing page** at `/` with a looping full-disk GOES-West view (the last hour, shrunk to 720 px;
  a still for people who prefer reduced motion), today's top 10 and your own rank, and a button
  into the game that reads "Start today's challenge", "Continue" or "See your result". The loop is
  built with the daily puzzle and ships in its JSON as `landing`.
- **Global daily leaderboard.** A shared board for everyone (hint and no-hint players together; the
  0.7 hint multiplier already evens things out), ordered by total, then fewer hints, then who
  finished first. Players are anonymous: a random id in the browser and a server-assigned name such
  as "Misty Cumulus 42", with a "new name" button. Stored in Cloudflare D1 (`migrations/`,
  `functions/api/player.js`, `functions/api/leaderboard.js`). Scores are recorded by the server from
  its own `/api/guess` result, never reported by the client. There is no one-attempt rule: replaying
  a round overwrites it.
- **Personal stats** on the summary: day streak, games played, average and best, kept on the device.
- A rank line in the shared result when the board is available.
- Ten tiers of funny feedback (from "a cry for help" to "NOAA wants to hire you") on each round's
  result and on the final summary, chosen by score.

## [1.2.0] - 2026-10-16

Animated loops, a hint, friendlier scoring, a bigger desktop layout, and a way to put the game online.

### Added
- **Animated loops.** Each round now shows the last hour of GOES imagery (6 frames, 10 minutes
  apart) as a looping animated WebP, so cloud motion is part of the clue. The reveal screen shows
  a still of the last frame. If fewer than two frames are cached, a round falls back to a still.
- **Wider-view hint.** An optional button swaps the close-up for a view three times wider with the
  crop outlined. It multiplies that round's score by 0.7, the penalty is applied on the server, and
  it survives a reload. Hints are marked 💡 on the summary and `*` in the shared result.
- **Country borders** on the guess map (land borders from Natural Earth 50m, no labels), built by
  `tools/make_borders.mjs`.
- **Side-by-side layout** on landscape screens at least 900 px wide: the satellite image is a large
  square next to the map. Phones and portrait tablets keep the stacked layout.
- **Cloudflare deployment**: static site on Cloudflare Pages, a Pages Function (`functions/api/guess.js`)
  that scores guesses against answers in Workers KV, `tools/publish.py` to assemble the site and the
  answer payload, a daily GitHub Actions workflow (`.github/workflows/daily.yml`), a CI workflow, and
  a setup guide (`docs/DEPLOY.md`). Includes Node tests that check the Function scores exactly like
  the Python code.
- **Game-day rollover** at 18:00 UTC (`ROLLOVER_UTC_HOUR`), so a US evening is not a gap before the
  next puzzle exists.
- Puzzles are served as static `/puzzles/<date>.json` and `/puzzles/latest.json` (the FastAPI app
  serves the same routes locally).
- `--at` for `fetch` and `build`, to use an earlier daytime hour when running at night, and a
  clear error message with the exact commands to run when no crop passes the daylight filter.
- `?fresh=1` on any puzzle URL clears that day's saved game (and removes itself from the address bar).
- Puzzle JSON gained `hint_image`, `hint_box`, `loop`, `hint_loop` and `frame_times` fields.

### Changed
- **Scoring is more forgiving.** A guess within 150 km scores 100, then the score decays with a
  2,500 km scale (was 1,500 km with no free radius). Roughly: 1,000 km off is about 71, 3,000 km
  about 32, 6,000 km about 9.
- `fetch` now downloads the last 6 frames per satellite (about 180 MB) instead of one.
- The default puzzle date for `build` and the "today" puzzle follow the game day, not the UTC date.
- Scores round half up (not banker's rounding) so Python and the Cloudflare Function always agree.

### Fixed
- A bare `--at HH:MM` now means the most recent past occurrence of that time, not a time that has
  not happened yet.

## [1.1.0] - 2026-10-16

First release: a playable proof of concept of the daily "Where is this?" game.

### Added
- **Imagery pipeline.** Fetches CIRA GeoColor full-disk JPEGs (5424 x 5424, 2 km) for GOES-East
  (GOES-19) and GOES-West (GOES-18) from the NOAA STAR CDN, with geostationary fixed-grid geometry
  (pixel to lat/lon and back) validated against a land mask to within about 10 px.
- **Puzzle builder.** Samples candidate crops and keeps only playable ones: full daylight (solar
  elevation of at least 15 degrees everywhere in the crop), at least 12% land, under 80% cloud, and
  not featureless. A difficulty heuristic (cloud cover and coastline) spreads the 5 daily rounds
  from easy to hard, with answers at least 1,500 km apart. Answers are kept in a private file.
- **API** (FastAPI): serves puzzles without answers and scores guesses on the server.
- **Mobile-first web app** (vanilla JS and Leaflet, no build step): tap the map to place a pin,
  lock in, then see the distance, score and crop footprint. Includes a bundled land-only world map
  (no tile server, labels or API keys), a pinch-to-zoom view of the image, a summary screen with a
  copyable result, per-day progress saved in the browser, and `?date=YYYY-MM-DD`.
- **Command line**: `fetch`, `build`, `synth` (synthetic imagery for offline development) and
  `check-geo`.
- Unit tests for geometry, scoring, listing parsing and solar elevation.

[Unreleased]: https://github.com/maxfieldeland64/sattap/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/maxfieldeland64/sattap/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/maxfieldeland64/sattap/releases/tag/v1.1.0
