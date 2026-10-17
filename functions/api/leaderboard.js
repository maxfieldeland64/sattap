// GET /api/leaderboard?date=YYYY-MM-DD&player=<uuid> -> {date, total_players, top[], you|null}
import { readBoard, UUID_RE } from '../_lib/board.js';

const H = { 'content-type': 'application/json', 'cache-control': 'no-store' };
const reply = (b, s = 200) => new Response(JSON.stringify(b), { status: s, headers: H });

export async function onRequestGet({ request, env }) {
  if (!env.DB) return reply({ detail: 'Leaderboard is not enabled' }, 503);
  const url = new URL(request.url);
  const date = url.searchParams.get('date') ?? '';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return reply({ detail: 'date must be YYYY-MM-DD' }, 400);
  const p = url.searchParams.get('player');
  return reply(await readBoard(env.DB, date, p && UUID_RE.test(p) ? p : null));
}
