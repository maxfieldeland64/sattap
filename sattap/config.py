"""Tunable constants for the SatTap POC backend."""
from __future__ import annotations

# --- Satellites (GOES-East / GOES-West) -----------------------------------
# lon0 is the sub-satellite longitude. Verify against NOAA if the operational
# satellites change.
SATELLITES = {
    "east": {"name": "GOES-19", "slug": "GOES19", "lon0": -75.2},
    "west": {"name": "GOES-18", "slug": "GOES18", "lon0": -137.0},
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

# --- Loop (animated WebP) --------------------------------------------------
LOOP_FRAMES = 6          # frames per loop, ending at the puzzle frame
LOOP_STEP_MIN = 10       # GeoColor full disk cadence
LOOP_FRAME_MS = 280      # display time per frame
LOOP_HOLD_MS = 1000      # extra hold on the last frame before it restarts
LOOP_WEBP_QUALITY = 72

# --- Scoring ---------------------------------------------------------------
# Guesses within SCORE_FREE_KM of the answer score 100 (about the crop's own radius),
# then score = round(100 * exp(-(distance_km - SCORE_FREE_KM) / SCORE_SCALE_KM)).
SCORE_FREE_KM = 150.0
SCORE_SCALE_KM = 2500.0
# Using the wider-view hint multiplies that round's score by this.
HINT_SCORE_MULT = 0.70
# The hint image covers this many times the crop's width (clamped to the full disk).
HINT_CONTEXT_FACTOR = 3
