// Leaderboard tests run against a real SQLite (node:sqlite) wrapped to look like D1.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

import { onRequestPost as guess } from '../../functions/api/guess.js';
import { onRequestPost as player } from '../../functions/api/player.js';
import { onRequestGet as board } from '../../functions/api/leaderboard.js';

function d1() {
  const db = new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('../../migrations/0001_init.sql', import.meta.url), 'utf8'));
  const mk = (sql, args = []) => ({
    _sql: sql, _args: args,
    bind: (...a) => mk(sql, a),
    first: async () => db.prepare(sql).get(...args) ?? null,
    all: async () => ({ results: db.prepare(sql).all(...args) }),
    run: async () => { db.prepare(sql).run(...args); return {}; },
  });
  return {
    prepare: (sql) => mk(sql),
    batch: async (list) => list.map((s) => ({ results: db.prepare(s._sql).all(...s._args) })),
    raw: db,
  };
}

const SCORING = { free_km: 150, scale_km: 2500, hint_mult: 0.7, earth_radius_km: 6371.0088 };
const DATE = '2026-10-16';
const rounds = [1, 2].map((n) => ({ round: n, lat: 40, lon: -100 }));
const mkEnv = () => {
  const store = new Map([[`puzzle:${DATE}`, { scoring: SCORING, rounds }]]);
  return { DB: d1(), ANSWERS: { get: async (k) => store.get(k) ?? null } };
};
const post = (fn, env, body) =>
  fn({ env, request: new Request('https://x.test/', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }) });
const get = (env, qs) => board({ env, request: new Request(`https://x.test/api/leaderboard?${qs}`) });
const newPlayer = async (env) => (await (await post(player, env, {})).json());
// guess at a given longitude offset; lat/lon 40,-100 is the answer so offset 0 scores 100
const play = (env, id, round, lonOffset, hint = false) =>
  post(guess, env, { date: DATE, round, lat: 40, lon: -100 + lonOffset, hint_used: hint, player: id });

test('player creation, idempotence and re-roll', async () => {
  const env = mkEnv();
  const a = await newPlayer(env);
  assert.match(a.player, /^[0-9a-f-]{36}$/);
  assert.match(a.name, /^\w+ \w+ \d{2}$/);
  const again = await (await post(player, env, { player: a.player })).json();
  assert.deepEqual(again, a);
  const re = await (await post(player, env, { player: a.player, reroll: true })).json();
  assert.equal(re.player, a.player);
  const saved = env.DB.raw.prepare('SELECT name FROM players WHERE id = ?').get(a.player);
  assert.equal(saved.name, re.name);
});

test('a run only appears on the board once every round is scored', async () => {
  const env = mkEnv();
  const a = await newPlayer(env);
  await play(env, a.player, 1, 0);
  let b = await (await get(env, `date=${DATE}&player=${a.player}`)).json();
  assert.equal(b.total_players, 0);
  assert.equal(b.you, null);
  await play(env, a.player, 2, 0);
  b = await (await get(env, `date=${DATE}&player=${a.player}`)).json();
  assert.equal(b.total_players, 1);
  assert.equal(b.top[0].total, 200);
  assert.equal(b.top[0].you, true);
  assert.equal(b.you.rank, 1);
  assert.equal(b.you.ahead_pct, null);
});

test('ranking: score, then fewer hints, ties share a rank, you outside the top 10', async () => {
  const env = mkEnv();
  const ps = [];
  for (let i = 0; i < 12; i++) {
    const p = await newPlayer(env);
    ps.push(p);
    // later players are further off, so scores strictly decrease
    await play(env, p.player, 1, i * 3);
    await play(env, p.player, 2, i * 3);
  }
  const hinted = await newPlayer(env); // same score as player 0 but used hints -> ranks below
  await play(env, hinted.player, 1, 0, true);
  await play(env, hinted.player, 2, 0, true);
  const twin = await newPlayer(env); // exact tie with `hinted`
  await play(env, twin.player, 1, 0, true);
  await play(env, twin.player, 2, 0, true);

  const last = ps[11];
  const b = await (await get(env, `date=${DATE}&player=${last.player}`)).json();
  assert.equal(b.total_players, 14);
  assert.equal(b.top.length, 10);
  assert.equal(b.top[0].name, ps[0].name);
  assert.ok(b.top.every((r, i) => i === 0 || b.top[i - 1].total >= r.total));
  assert.equal(b.you.name, last.name);
  assert.ok(b.you.rank >= 13);
  const bh = await (await get(env, `date=${DATE}&player=${hinted.player}`)).json();
  const bt = await (await get(env, `date=${DATE}&player=${twin.player}`)).json();
  assert.equal(bh.you.rank, bt.you.rank); // tie shares a rank
  // hinted score is 70 per round (140 total); everyone strictly above 140 ranks ahead of it
  const ahead = env.DB.raw.prepare('SELECT COUNT(*) n FROM runs WHERE date = ? AND total > 140').get(DATE).n;
  assert.equal(bh.you.rank, ahead + 1);
  assert.ok(ahead >= 1);
});

test('replaying a round overwrites it (latest guess wins) and bad input is rejected', async () => {
  const env = mkEnv();
  const a = await newPlayer(env);
  await play(env, a.player, 1, 40);
  await play(env, a.player, 1, 0);
  await play(env, a.player, 2, 0);
  const b = await (await get(env, `date=${DATE}&player=${a.player}`)).json();
  assert.equal(b.top[0].total, 200);
  assert.equal((await get(env, 'date=nope')).status, 400);
  // unknown/invalid player id: guess still scores, nothing recorded
  const r = await post(guess, env, { date: DATE, round: 1, lat: 40, lon: -100, player: 'not-a-uuid' });
  assert.equal(r.status, 200);
  assert.equal(env.DB.raw.prepare('SELECT COUNT(*) n FROM runs').get().n, 1);
});

test('guess still works with no database bound', async () => {
  const env = mkEnv();
  delete env.DB;
  const r = await post(guess, env, { date: DATE, round: 1, lat: 40, lon: -100, player: crypto.randomUUID() });
  assert.equal(r.status, 200);
  assert.equal((await r.json()).score, 100);
});
