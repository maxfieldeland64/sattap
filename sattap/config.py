"""Tunable constants for the SatTap POC backend."""
from __future__ import annotations

# --- Satellites (GOES-East / GOES-West / Meteosat) -------------------------
# lon0 is the sub-satellite longitude. Verify against NOAA / EUMETSAT if the operational
# satellites change. `source` picks the fetcher: "star" = NOAA STAR CDN (GOES ABI GeoColor),
# "eumetview" = EUMETSAT's public EUMETView WMS (MTG FCI GeoColour, no account needed).
SATELLITES = {
    "east": {"name": "GOES-19", "slug": "GOES19", "lon0": -75.2, "source": "star"},
    "west": {"name": "GOES-18", "slug": "GOES18", "lon0": -137.0, "source": "star"},
    "meteo": {"name": "Meteosat-12", "slug": "MTG0", "lon0": 0.0, "source": "eumetview", "sweep": "y"},
}

# --- ABI fixed-grid geometry (full disk, 2 km, 5424 x 5424) ---------------
PERSPECTIVE_HEIGHT_M = 35786023.0
SEMI_MAJOR_M = 6378137.0
SEMI_MINOR_M = 6356752.31414
FD_HALF_EXTENT_RAD = 0.151844  # scan angle of outermost pixel centers
FD_SIZE_2KM = 5424
EARTH_LIMB_RAD = 0.1512  # conservative angular radius of the Earth disk

# --- Source (CIRA GeoColor via NOAA STAR CDN) ------------------------------
STAR_CDN = "https://cdn.star.nesdis.noaa.gov"
GEOCOLOR_SIZE = 5424  # which pre-rendered size to pull
HTTP_TIMEOUT_S = 60

# --- Source (MTG FCI GeoColour via EUMETSAT EUMETView WMS) -----------------
# One GetMap request returns the whole disk in the geostationary projection. The service
# refuses very large images (5600 px, the native 2 km size, comes back empty; 4608 works), so
# frames are ~2.4 km/pixel, a little coarser than the GOES ones. Pixel scale is relative to
# +-EUMETVIEW_HALF_EXTENT_M metres around the sub-satellite point.
EUMETVIEW_WMS = "https://view.eumetsat.int/geoserver/wms"
EUMETVIEW_LAYER = "mtg_fd:rgb_geocolour"
EUMETVIEW_SIZE_PX = 4608
EUMETVIEW_HALF_EXTENT_M = 5_600_000.0
EUMETVIEW_STEP_MIN = 10
EUMETVIEW_TIMEOUT_S = 180

# --- Crop sampling ---------------------------------------------------------
# Half-widths in pixels on the 5424 grid. 200 px ~ 800 km across at nadir.
CROP_HALF_PX_CHOICES = (150, 200, 260)
OUT_SIZE_PX = 640
MAX_RADIAL_FRAC = 0.80  # keep crop centers away from the limb
MAX_CORNER_FRAC = 0.95

# --- Playability filter ----------------------------------------------------
MIN_SUN_ELEV_DEG = 15.0  # every sampled point in the crop must be this far above the horizon
MIN_LUMA = 25.0  # backup guard against dark/night crops
MIN_LUMA_STD = 10.0  # reject featureless crops
MIN_LAND_FRAC = 0.12
MAX_LAND_FRAC = 0.98
MAX_CLOUD_FRAC = 0.80
CLOUD_MIN_LUMA = 150.0  # cloud = bright and nearly colorless in GeoColor
CLOUD_MAX_SPREAD = 55.0

# --- Puzzle building -------------------------------------------------------
N_ROUNDS = 5
N_CANDIDATES = 300
MIN_ANSWER_SEPARATION_KM = 1500.0
DIFFICULTY_QUANTILES = (0.10, 0.30, 0.50, 0.70, 0.90)
# Each satellite supplies at least this many of the day's rounds (when both have playable crops).
MIN_ROUNDS_PER_SAT = 2

# --- Game day --------------------------------------------------------------
# The puzzle for day D is live from ROLLOVER_UTC_HOUR on D until the same hour on D+1.
# 18:00 UTC = noon in Denver / 2pm in New York, an hour after the daily build job (17:00 UTC)
# so a late scheduled run still lands before players roll over. Keep web/app.js in sync.
ROLLOVER_UTC_HOUR = 18

# --- Capture time ----------------------------------------------------------
# Real time matters less than good light. Each satellite's frames are taken around local solar
# noon at its sub-satellite longitude (the latest such moment that has already happened), instead
# of "now". At the 17:00 UTC build that is today for GOES-East (noon ~17:00 UTC) but yesterday
# afternoon for GOES-West (noon ~21:08 UTC), whose disk is mostly morning light at build time.
SOLAR_NOON_CAPTURE = True
CAPTURE_AFTER_NOON_MIN = 25  # the loop ends this long after noon

# --- Loop (animated WebP) --------------------------------------------------
LOOP_FRAMES = 6          # frames per loop, ending at the puzzle frame
LOOP_STEP_MIN = 10       # GeoColor full disk cadence
LOOP_FRAME_MS = 280      # display time per frame
LOOP_HOLD_MS = 1000      # extra hold on the last frame before it restarts
LOOP_WEBP_QUALITY = 72

# --- Landing page: full-disk GOES-West loop --------------------------------
LANDING_SIZE_PX = 720    # the 5424 px disk, shrunk
LANDING_WEBP_QUALITY = 70

# --- Scoring ---------------------------------------------------------------
# Guesses within SCORE_FREE_KM of the answer score 100 (about the crop's own radius),
# then score = round(100 * exp(-(distance_km - SCORE_FREE_KM) / SCORE_SCALE_KM)).
SCORE_FREE_KM = 150.0
SCORE_SCALE_KM = 2500.0
# Using the wider-view hint multiplies that round's score by this.
HINT_SCORE_MULT = 0.70
# The hint image covers this many times the crop's width (clamped to the full disk).
HINT_CONTEXT_FACTOR = 3

# --- Band 13 challenge (the final round) ------------------------------------
# The last round of the day swaps GeoColor for the NOAA STAR CDN's enhanced Band 13 (clean
# longwave IR, 10.3 um) image of the same scene. Cold cloud tops are colourised (blue -> green ->
# yellow -> red as they get colder), warm surfaces stay grey. The CDN draws coastlines and country
# borders on that image, so the crop must be open ocean (no land inside the crop plus a margin) or
# the overlay would hand over the answer. The crop is centred on the strongest convective core.
# Only the GOES satellites have it (Meteosat is not on the CDN).
B13_PRODUCT = "13"
B13_CROP_HALF_PX = 260        # on the 5424 grid: ~1040 km across at nadir, a bit wider than a normal crop
B13_ANALYSIS_SIZE = 1356      # cell search runs on a 1/4-size copy (JPEG decodes at 1/4 scale cheaply)
B13_COAST_MARGIN = 1.2        # land must be absent from this many times the crop's half-width
B13_MIN_SPREAD = 40           # max-min channel spread that counts as "colourised" (grey = warm)
B13_SMOOTH_PX = 6.0           # blur radius (analysis pixels, ~50 km) so a cell is a blob, not a speckle
B13_MIN_PEAK = 0.45           # smoothed coldness needed at the centre (0 = blue edge .. 1 = red core)
B13_MIN_COLORED_FRAC = 0.03   # share of the crop that is colourised, lower: nothing to look at
B13_MAX_COLORED_FRAC = 0.50   # upper: a solid blob with no structure
B13_TARGET_COLORED_FRAC = 0.15
B13_TOP_K = 6                 # choose among this many best candidates, with the day's seed
# Hint ladder for this round: 0 = Band 13 close-up, 1 = + GeoColor, 2 = + zoom out.
# Score multiplier once that level has been reached.
B13_HINT_MULTS = (1.0, 0.85, 0.6)
