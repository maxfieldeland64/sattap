// POST /api/player  {player?: uuid, reroll?: bool} -> {player, name}
//   no body / unknown id : create a player with a random name
//   known id             : return the existing name (or give a new one if reroll is true)
import { randomName } from '../_lib/names.js';
import { UUID_RE } from '../_lib/board.js';

const H = { 'content-type': 'application/json', 'cache-control': 'no-store' };
const reply = (b, s = 200) => new Response(JSON.stringify(b), { status: s, headers: H });

export async function onRequestPost({ request, env }) {
  if (!env.DB) return reply({ detail: 'Leaderboard is not enabled' }, 503);
  let body = {};
  try {
    body = (await request.json()) ?? {};
  } catch {
    /* empty body is fine */
  }
  const id = typeof body.player === 'string' && UUID_RE.test(body.player) ? body.player : null;
  const existing = id ? await env.DB.prepare('SELECT name FROM players WHERE id = ?1').bind(id).first() : null;

  if (existing && body.reroll !== true) return reply({ player: id, name: existing.name });
  if (existing) {
    const name = randomName();
    await env.DB.prepare('UPDATE players SET name = ?2 WHERE id = ?1').bind(id, name).run();
    return reply({ player: id, name });
  }
  const player = id ?? crypto.randomUUID();
  const name = randomName();
  await env.DB.prepare('INSERT INTO players (id, name, created_at) VALUES (?1, ?2, ?3)').bind(player, name, Date.now()).run();
  return reply({ player, name });
}
