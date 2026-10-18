/* SatTap landing page: GOES-West disk loop, today's leaderboard, and the way into the game. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

  // Same rule as web/app.js and sattap/config.py: the puzzle for day D is live from
  // ROLLOVER_UTC_HOUR on D until the same hour on D+1. Keep all three in sync.
  const ROLLOVER_UTC_HOUR = 18;
  const gameDay = () => new Date(Date.now() - ROLLOVER_UTC_HOUR * 3600e3).toISOString().slice(0, 10);
  const nextRollover = () => {
    const t = new Date();
    t.setUTCHours(ROLLOVER_UTC_HOUR, 0, 0, 0);
    if (t.getTime() <= Date.now()) t.setUTCDate(t.getUTCDate() + 1);
    return t.getTime();
  };

  async function getJSON(url) {
    const r = await fetch(url);
    // A host that answers misses with an HTML page counts as "not found".
    const isJson = (r.headers.get('content-type') || '').includes('json');
    if (!r.ok || !isJson) {
      const e = new Error(`HTTP ${r.status}`);
      e.status = r.ok ? 404 : r.status;
      throw e;
    }
    return r.json();
  }

  const readLS = (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } };

  let puzzle = null;
  let isFallback = false;

  // ---------- puzzle ----------
  async function loadPuzzle() {
    try {
      return { puzzle: await getJSON(`/puzzles/${gameDay()}.json`), fallback: false };
    } catch (e) {
      if (e.status !== 404) throw e;
      return { puzzle: await getJSON('/puzzles/latest.json'), fallback: true };
    }
  }

  // ---------- disk loop ----------
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function renderDisk() {
    const landing = puzzle && puzzle.landing;
    if (!landing) return;
    const img = $('diskImg');
    // a still instead of the animation for people who ask their system for less motion
    const src = reduceMotion.matches ? landing.image : (landing.loop || landing.image);
    if (!src || img.getAttribute('src') === src) return;
    img.onload = () => { img.hidden = false; $('disk').classList.add('ready'); };
    img.src = src;

    $('chipSat').textContent = `${landing.satellite} · full disk`;
    const times = landing.frame_times || [];
    if (times.length > 1) {
      const hm = (iso) => iso.slice(11, 16);
      $('chipTime').textContent = `${hm(times[0])}–${hm(times[times.length - 1])} UTC`;
    } else if (times.length === 1) {
      $('chipTime').textContent = `${times[0].slice(11, 16)} UTC`;
    }
  }

  // ---------- start button ----------
  const fmtLeft = (ms) => {
    const m = Math.max(1, Math.round(ms / 60000));
    const h = Math.floor(m / 60);
    return h ? `${h}h ${m % 60}m` : `${m}m`;
  };

  function renderStart() {
    const btn = $('startBtn');
    const note = $('startNote');
    if (!puzzle) return;
    const n = puzzle.rounds.length;
    const saved = readLS(`sattap:${puzzle.date}`);
    const done = saved && Array.isArray(saved.results) ? saved.results : [];
    const left = fmtLeft(nextRollover() - Date.now());

    btn.classList.remove('done');
    if (done.length >= n) {
      const total = done.reduce((a, r) => a + r.score, 0);
      btn.textContent = 'See your result';
      btn.classList.add('done');
      note.textContent = `You scored ${total} / ${n * 100} · next puzzle in ${left}`;
    } else if (done.length > 0) {
      btn.textContent = `Continue · round ${done.length + 1} of ${n}`;
      note.textContent = `Next puzzle in ${left}`;
    } else {
      btn.textContent = "Start today's challenge";
      note.textContent = isFallback
        ? `Today's puzzle isn't ready yet, so this is ${puzzle.date}`
        : `${n} rounds · next puzzle in ${left}`;
    }
  }

  // ---------- leaderboard ----------
  function row(rank, name, total, me, hinted) {
    const li = document.createElement('li');
    if (me) li.className = 'me';
    const r = document.createElement('span'); r.className = 'mono'; r.textContent = `#${rank}`;
    const nm = document.createElement('span'); nm.textContent = name + (hinted ? ' 💡' : '');
    const t = document.createElement('strong'); t.textContent = total;
    li.append(r, nm, t);
    return li;
  }

  async function renderBoard() {
    const section = $('board');
    if (!puzzle) { section.hidden = true; return; }
    const player = readLS('sattap:player');
    let b;
    try {
      const q = player && player.player ? `&player=${encodeURIComponent(player.player)}` : '';
      b = await getJSON(`/api/leaderboard?date=${encodeURIComponent(puzzle.date)}${q}`);
    } catch {
      section.hidden = true; // no leaderboard here (local dev, or D1 not set up): hide it quietly
      return;
    }
    section.hidden = false;

    const list = $('boardList');
    const empty = $('boardEmpty');
    list.innerHTML = '';
    $('boardCount').textContent = b.total_players ? `${b.total_players} finished` : '';

    if (!b.top.length) {
      empty.hidden = false;
      empty.textContent = 'Nobody has finished yet. Be the first on the board.';
      return;
    }
    empty.hidden = true;
    b.top.forEach((r) => list.appendChild(row(r.rank, r.name, r.total, r.you, r.hints)));
    if (b.you && !b.top.some((r) => r.you)) {
      const gap = document.createElement('li'); gap.className = 'gap'; gap.textContent = '···';
      list.append(gap, row(b.you.rank, b.you.name, b.you.total, true, b.you.hints));
    }
  }

  // ---------- boot ----------
  function renderDynamic() {
    renderStart();
    renderBoard();
  }

  async function boot() {
    try {
      const res = await loadPuzzle();
      puzzle = res.puzzle;
      isFallback = res.fallback;
    } catch {
      $('startNote').textContent = 'No puzzle available yet.';
      $('board').hidden = true;
      return;
    }
    const d = new Date(`${puzzle.date}T00:00:00Z`);
    $('dateLabel').textContent = d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' });
    renderDisk();
    renderDynamic();
    setInterval(renderStart, 60e3);
  }

  reduceMotion.addEventListener('change', renderDisk);
  // coming back from the game via the back button: pick up the new score and rank
  window.addEventListener('pageshow', (e) => { if (e.persisted && puzzle) renderDynamic(); });
  boot();
})();
