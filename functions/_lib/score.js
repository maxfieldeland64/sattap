// Scoring for the Cloudflare Function. Mirrors sattap/scoring.py exactly (same constants come
// from the "scoring" block published with the answers, rounding is floor(x + 0.5) in both).

const toRad = (d) => (d * Math.PI) / 180;

export function haversineKm(lon1, lat1, lon2, lat2, radiusKm) {
  const p1 = toRad(lat1);
  const p2 = toRad(lat2);
  const dp = p2 - p1;
  const dl = toRad(lon2 - lon1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * radiusKm * Math.asin(Math.min(1, Math.sqrt(a)));
}

const roundHalfUp = (x) => Math.floor(x + 0.5);

export function scoreForDistance(distanceKm, { free_km, scale_km }) {
  const over = Math.max(distanceKm - free_km, 0);
  return roundHalfUp(100 * Math.exp(-over / scale_km));
}

// Multiplier once hint `level` has been reached on a hint-ladder round (0 = no hint).
export function ladderMult(mults, level) {
  return mults[Math.min(Math.max(level, 0), mults.length - 1)];
}

// `hintMult` (from a hint ladder) overrides the single-hint multiplier.
export function scoreGuess(guess, answer, scoring, hintUsed = false, hintMult = null) {
  const d = haversineKm(guess.lon, guess.lat, answer.lon, answer.lat, scoring.earth_radius_km);
  let score = scoreForDistance(d, scoring);
  const mult = hintMult ?? (hintUsed ? scoring.hint_mult : 1);
  if (mult !== 1) score = roundHalfUp(score * mult);
  return { distance_km: d, score };
}
