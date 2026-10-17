// Leaderboard storage on D1: record each guess into the player's run, and read the board.
// `db` is a D1 binding (env.DB). All SQL is plain SQLite.

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

// Called after every scored guess. Latest guess per round wins, a run is "done" once every round
// has a score. Replaying a day just overwrites that player's rounds (no one-attempt rule).
export async function recordGuess(db, { date, player, round, score, hintUsed, nRounds, now = Date.now() }) {
  const row = await db.prepare('SELECT scores FROM runs WHERE date = ?1 AND player = ?2').bind(date, player).first();
  const scores = row ? JSON.parse(row.scores) : {};
  scores[round] = { s: score, h: hintUsed ? 1 : 0 };
  const entries = Object.values(scores);
  const total = entries.reduce((a, e) => a + e.s, 0);
  const hints = entries.reduce((a, e) => a + e.h, 0);
  const done = entries.length >= nRounds ? 1 : 0;
  await db
    .prepare(
      `INSERT INTO runs (date, player, scores, total, hints, done, finished_at)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
       ON CONFLICT (date, player) DO UPDATE SET
         scores = excluded.scores, total = excluded.total, hints = excluded.hints,
         done = excluded.done, finished_at = excluded.finished_at`,
    )
    .bind(date, player, JSON.stringify(scores), total, hints, done, done ? now : null)
    .run();
}

// Top 10 plus the caller's own standing. Ties on (total, hints) share a rank.
export async function readBoard(db, date, player) {
  const [top, mine, count] = await db.batch([
    db
      .prepare(
        `SELECT r.player, p.name, r.total, r.hints
         FROM runs r JOIN players p ON p.id = r.player
         WHERE r.date = ?1 AND r.done = 1
         ORDER BY r.total DESC, r.hints ASC, r.finished_at ASC
         LIMIT 10`,
      )
      .bind(date),
    db
      .prepare(
        `SELECT r.total, r.hints, p.name
         FROM runs r JOIN players p ON p.id = r.player
         WHERE r.date = ?1 AND r.player = ?2 AND r.done = 1`,
      )
      .bind(date, player ?? ''),
    db.prepare('SELECT COUNT(*) AS n FROM runs WHERE date = ?1 AND done = 1').bind(date),
  ]);

  const totalPlayers = count.results[0].n;
  const rows = top.results;
  let prev = null;
  const board = rows.map((r, i) => {
    const same = prev && prev.total === r.total && prev.hints === r.hints;
    const rank = same ? prev.rank : i + 1;
    prev = { total: r.total, hints: r.hints, rank };
    return { rank, name: r.name, total: r.total, hints: r.hints, you: r.player === player };
  });

  let you = null;
  if (mine.results.length) {
    const { total, hints, name } = mine.results[0];
    const [ahead, behind] = await db.batch([
      db
        .prepare(
          `SELECT COUNT(*) AS n FROM runs
           WHERE date = ?1 AND done = 1 AND (total > ?2 OR (total = ?2 AND hints < ?3))`,
        )
        .bind(date, total, hints),
      db
        .prepare(
          `SELECT COUNT(*) AS n FROM runs
           WHERE date = ?1 AND done = 1 AND (total < ?2 OR (total = ?2 AND hints > ?3))`,
        )
        .bind(date, total, hints),
    ]);
    you = {
      rank: ahead.results[0].n + 1,
      name,
      total,
      hints,
      // share of the *other* players you finished ahead of
      ahead_pct: totalPlayers > 1 ? Math.floor((100 * behind.results[0].n) / (totalPlayers - 1)) : null,
    };
  }
  return { date, total_players: totalPlayers, top: board, you };
}
