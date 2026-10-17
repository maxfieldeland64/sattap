// POST /api/guess  {date, round, lat, lon, hint_used?, player?}
// -> {round, distance_km, score, hint_used, answer: {lat, lon}}
//
// Answers never ship with the site. The daily GitHub Action writes them to the ANSWERS KV
// namespace under "puzzle:<date>" (see tools/publish.py), and this Function is the only reader.
import { scoreGuess } from '../_lib/score.js';
import { recordGuess, UUID_RE } from '../_lib/board.js';

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const JSON_HEADERS = { 'content-type': 'application/json', 'cache-control': 'no-store' };

const reply = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

export async function onRequestPost({ request, env }) {
  let g;
  try {
    g = await request.json();
  } catch {
    return reply({ detail: 'Body must be JSON' }, 400);
  }
  if (!g || typeof g.date !== 'string' || !DATE_RE.test(g.date)) return reply({ detail: 'date must be YYYY-MM-DD' }, 400);
  if (!Number.isInteger(g.round) || g.round < 1) return reply({ detail: 'round must be an integer >= 1' }, 400);
  if (!isNum(g.lat) || g.lat < -90 || g.lat > 90) return reply({ detail: 'lat must be within [-90, 90]' }, 400);
  if (!isNum(g.lon) || g.lon < -180 || g.lon > 180) return reply({ detail: 'lon must be within [-180, 180]' }, 400);
  const hintUsed = g.hint_used === true;

  if (!env.ANSWERS) return reply({ detail: 'ANSWERS KV namespace is not bound' }, 500);
  const doc = await env.ANSWERS.get(`puzzle:${g.date}`, 'json');
  if (!doc) return reply({ detail: `No puzzle for ${g.date}` }, 404);
  const answer = doc.rounds.find((r) => r.round === g.round);
  if (!answer) return reply({ detail: 'No such round' }, 404);

  const { distance_km, score } = scoreGuess({ lat: g.lat, lon: g.lon }, answer, doc.scoring, hintUsed);

  // Optional leaderboard recording. Never let a database problem break scoring.
  if (env.DB && typeof g.player === 'string' && UUID_RE.test(g.player)) {
    try {
      await recordGuess(env.DB, {
        date: g.date, player: g.player, round: g.round, score, hintUsed, nRounds: doc.rounds.length,
      });
    } catch (err) {
      console.error('recordGuess failed', err);
    }
  }
  return reply({
    round: g.round,
    distance_km: Math.round(distance_km * 10) / 10,
    score,
    hint_used: hintUsed,
    answer: { lat: answer.lat, lon: answer.lon },
  });
}
