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

export function scoreGuess(guess, answer, scoring, hintUsed = false) {
  const d = haversineKm(guess.lon, guess.lat, answer.lon, answer.lat, scoring.earth_radius_km);
  let score = scoreForDistance(d, scoring);
  if (hintUsed) score = roundHalfUp(score * scoring.hint_mult);
  return { distance_km: d, score };
}
