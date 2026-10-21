// Run with: npm test  (node --test). No Cloudflare account needed: KV is faked.
import assert from 'node:assert/strict';
import test from 'node:test';

import { onRequestPost } from '../../functions/api/guess.js';

// Expected values below were produced by sattap/scoring.py (score_guess), so any drift between
// the Python and JS implementations fails here.
const PARITY = [
  { guess: { lon: -105, lat: 40 }, answer: { lon: -104, lat: 41 }, hint: false, distance_km: 139.7, score: 100 },
  { guess: { lon: -120, lat: 35 }, answer: { lon: -75, lat: 40 }, hint: false, distance_km: 3966.2, score: 22 },
  { guess: { lon: 10, lat: 10 }, answer: { lon: -60, lat: -20 }, hint: false, distance_km: 8350.8, score: 4 },
  { guess: { lon: -100, lat: 30 }, answer: { lon: -103.5, lat: 32 }, hint: true, distance_km: 400.9, score: 63 },
  { guess: { lon: -100, lat: 30 }, answer: { lon: -100, lat: 30 }, hint: true, distance_km: 0.0, score: 70 },
  { guess: { lon: 179, lat: 0 }, answer: { lon: -179, lat: 0 }, hint: false, distance_km: 222.4, score: 97 },
  { guess: { lon: -90, lat: 0 }, answer: { lon: -90, lat: 5 }, hint: true, distance_km: 556.0, score: 59 },
  { guess: { lon: -100, lat: 30 }, answer: { lon: -111, lat: 36 }, hint: true, distance_km: 1222.4, score: 46 },
];

const SCORING = { free_km: 150, scale_km: 2500, hint_mult: 0.7, earth_radius_km: 6371.0088 };

function fakeEnv(rounds) {
  const store = new Map([['puzzle:2026-10-16', { scoring: SCORING, rounds }]]);
  return { ANSWERS: { get: async (key) => store.get(key) ?? null } };
}

const post = (env, body) =>
  onRequestPost({
    env,
    request: new Request('https://x.test/api/guess', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: typeof body === 'string' ? body : JSON.stringify(body),
    }),
  });

test('matches the Python scoring for every parity case', async () => {
  for (const c of PARITY) {
    const env = fakeEnv([{ round: 1, lat: c.answer.lat, lon: c.answer.lon }]);
    const res = await post(env, { date: '2026-10-16', round: 1, lat: c.guess.lat, lon: c.guess.lon, hint_used: c.hint });
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.distance_km, c.distance_km, JSON.stringify(c));
    assert.equal(body.score, c.score, JSON.stringify(c));
    assert.equal(body.hint_used, c.hint);
    assert.deepEqual(body.answer, { lat: c.answer.lat, lon: c.answer.lon });
  }
});

test('hint defaults to false and must be a real boolean', async () => {
  const env = fakeEnv([{ round: 1, lat: 30, lon: -100 }]);
  const plain = await (await post(env, { date: '2026-10-16', round: 1, lat: 30, lon: -100 })).json();
  assert.equal(plain.score, 100);
  const sneaky = await (await post(env, { date: '2026-10-16', round: 1, lat: 30, lon: -100, hint_used: 'true' })).json();
  assert.equal(sneaky.hint_used, false);
});

test('rejects bad input with 400', async () => {
  const env = fakeEnv([{ round: 1, lat: 0, lon: 0 }]);
  const bad = [
    'not json',
    { date: '16-10-2026', round: 1, lat: 0, lon: 0 },
    { date: '2026-10-16', round: 0, lat: 0, lon: 0 },
    { date: '2026-10-16', round: 1.5, lat: 0, lon: 0 },
    { date: '2026-10-16', round: 1, lat: 91, lon: 0 },
    { date: '2026-10-16', round: 1, lat: 0, lon: '5' },
    { date: '2026-10-16', round: 1, lat: null, lon: 0 },
  ];
  for (const b of bad) assert.equal((await post(env, b)).status, 400, JSON.stringify(b));
});

test('404 for an unknown date or round, 500 if KV is not bound', async () => {
  const env = fakeEnv([{ round: 1, lat: 0, lon: 0 }]);
  assert.equal((await post(env, { date: '2026-01-01', round: 1, lat: 0, lon: 0 })).status, 404);
  assert.equal((await post(env, { date: '2026-10-16', round: 9, lat: 0, lon: 0 })).status, 404);
  assert.equal((await post({}, { date: '2026-10-16', round: 1, lat: 0, lon: 0 })).status, 500);
});

test('responses are never cached', async () => {
  const env = fakeEnv([{ round: 1, lat: 0, lon: 0 }]);
  const res = await post(env, { date: '2026-10-16', round: 1, lat: 0, lon: 0 });
  assert.equal(res.headers.get('cache-control'), 'no-store');
});

// ---- hint ladder (the Band 13 round) ----------------------------------------------------------
// Expected values come from sattap/scoring.py: score_guess(..., hint_mult=m).
const MULTS = [1.0, 0.85, 0.6];
const ladderEnv = () => fakeEnv([
  { round: 1, lat: 30, lon: -100 },
  { round: 5, lat: 32, lon: -103.5, hint_mults: MULTS },
]);
const ladderGuess = (env, extra) => post(env, { date: '2026-10-16', round: 5, lat: 30, lon: -100, ...extra }).then((r) => r.json());

test('a ladder round scores by hint level, matching the Python multipliers', async () => {
  const env = ladderEnv();
  // 400.9 km off: base score 90
  const expected = [90, 77, 54];
  for (const level of [0, 1, 2]) {
    const body = await ladderGuess(env, { hint_level: level });
    assert.equal(body.distance_km, 400.9);
    assert.equal(body.score, expected[level], `level ${level}`);
    assert.equal(body.hint_level, level);
    assert.equal(body.hint_used, level > 0);
    assert.equal(body.hint_mult, MULTS[level]);
  }
});

test('ladder edge cases: bare hint_used is level 1, big levels clamp, the level beats hint_used', async () => {
  const env = ladderEnv();
  assert.equal((await ladderGuess(env, { hint_used: true })).hint_level, 1);
  assert.equal((await ladderGuess(env, { hint_level: 7 })).hint_level, 2);
  const both = await ladderGuess(env, { hint_used: false, hint_level: 2 });
  assert.equal(both.hint_used, true);
  assert.equal(both.hint_mult, 0.6);
});

test('plain rounds ignore hint_level and keep the single-hint multiplier', async () => {
  const env = ladderEnv();
  const plain = await (await post(env, { date: '2026-10-16', round: 1, lat: 30, lon: -100, hint_level: 2 })).json();
  assert.deepEqual([plain.score, plain.hint_used, plain.hint_level, plain.hint_mult], [100, false, null, 1]);
  const hinted = await (await post(env, { date: '2026-10-16', round: 1, lat: 30, lon: -100, hint_used: true })).json();
  assert.deepEqual([hinted.score, hinted.hint_mult], [70, 0.7]);
});

test('hint_level must be an integer from 0 to 9', async () => {
  const env = ladderEnv();
  for (const bad of [-1, 10, 1.5, '1', null]) {
    const res = await post(env, { date: '2026-10-16', round: 5, lat: 30, lon: -100, hint_level: bad });
    assert.equal(res.status, 400, JSON.stringify(bad));
  }
});
