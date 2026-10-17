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
