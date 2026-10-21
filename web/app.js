/* SatTap web POC: vanilla JS + a d3-geo globe (web/globe.js). Talks to /puzzles/*, /api/guess and /api/leaderboard. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const COLORS = { accent: '#7CE0C3', you: '#FFB547', line: '#E6EDF3' };

  const state = {
    puzzle: null,
    index: 0, // current round (0-based)
    results: [], // [{round, score, distance_km, guess:{lat,lon}, answer:{lat,lon}}]
    phase: 'guess', // 'guess' | 'reveal'
    guess: null,
    hintUsed: false, // any hint taken this round (penalises the score)
    hintLevel: 0, // hint-ladder rounds: 0 none, 1 second layer, 2 zoomed out (plain rounds: 0 or 1)
    hintView: false, // currently showing the wider view
    layer: 'main', // hint-ladder rounds: which layer is on screen, 'main' or 'alt'
  };

  let globe;

  // ---------- storage ----------
  const key = (d) => `sattap:${d}`;
  const load = (d) => { try { return JSON.parse(localStorage.getItem(key(d))); } catch { return null; } };
  const save = () => {
    try {
      // hintRound/hintLevel remember an unscored hint so a reload can't undo the penalty
      const pending = state.hintUsed && state.phase === 'guess';
      localStorage.setItem(key(state.puzzle.date), JSON.stringify({
        results: state.results,
        hintRound: pending ? state.index : null,
        hintLevel: pending ? state.hintLevel : 0,
      }));
    } catch { /* private mode etc. */ }
  };

  // ---------- player (anonymous, server-named) ----------
  // The id lives only in this browser. The server hands out a playful name; no sign-up, no typing.
  const PLAYER_KEY = 'sattap:player';
  const readPlayer = () => { try { return JSON.parse(localStorage.getItem(PLAYER_KEY)); } catch { return null; } };
  const writePlayer = (p) => { try { localStorage.setItem(PLAYER_KEY, JSON.stringify(p)); } catch { /* ignore */ } };
  let player = readPlayer(); // {player, name} or null when the leaderboard is unavailable

  async function ensurePlayer(reroll = false) {
    try {
      const res = await getJSON('/api/player', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player: player && player.player, reroll }),
      });
      player = { player: res.player, name: res.name };
      writePlayer(player);
    } catch { /* no leaderboard here (e.g. local dev server): the game still works */ }
    return player;
  }

  // Personal stats come straight from the per-day saves already in localStorage.
  function personalStats() {
    const days = [];
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const m = /^sattap:(\d{4}-\d{2}-\d{2})$/.exec(localStorage.key(i));
        if (!m) continue;
        const v = JSON.parse(localStorage.getItem(localStorage.key(i)));
        if (v && Array.isArray(v.results) && v.results.length >= nRounds()) {
          days.push({ date: m[1], total: v.results.reduce((a, r) => a + r.score, 0) });
        }
      }
    } catch { /* ignore */ }
    days.sort((a, b) => (a.date < b.date ? -1 : 1));
    const played = new Set(days.map((d) => d.date));
    // streak = consecutive game days ending today (or yesterday if today is not finished yet)
    const dayMs = 86400e3;
    let cur = Date.parse(gameDay() + 'T00:00:00Z');
    if (!played.has(new Date(cur).toISOString().slice(0, 10))) cur -= dayMs;
    let streak = 0;
    while (played.has(new Date(cur).toISOString().slice(0, 10))) { streak++; cur -= dayMs; }
    const totals = days.map((d) => d.total);
    return {
      games: days.length,
      streak,
      avg: totals.length ? Math.round(totals.reduce((a, b) => a + b, 0) / totals.length) : 0,
      best: totals.length ? Math.max(...totals) : 0,
    };
  }

  async function renderBoard() {
    const box = $('board');
    box.hidden = true;
    if (!player) return;
    let b;
    try {
      b = await getJSON(`/api/leaderboard?date=${encodeURIComponent(state.puzzle.date)}&player=${encodeURIComponent(player.player)}`);
    } catch { return; }
    box.hidden = false;
    const head = $('boardYou');
    if (b.you) {
      const pct = b.you.ahead_pct == null ? '' : ` · ahead of ${b.you.ahead_pct}%`;
      head.textContent = `You: #${b.you.rank} of ${b.total_players}${pct}`;
    } else {
      head.textContent = `${b.total_players} finished so far`;
    }
    const list = $('boardList');
    list.innerHTML = '';
    b.top.forEach((r) => {
      const li = document.createElement('li');
      if (r.you) li.className = 'me';
      const rank = document.createElement('span'); rank.className = 'mono'; rank.textContent = `#${r.rank}`;
      const name = document.createElement('span'); name.textContent = r.name + (r.hints ? ' 💡'.repeat(Math.min(r.hints, 1)) : '');
      const tot = document.createElement('strong'); tot.textContent = r.total;
      li.append(rank, name, tot);
      list.appendChild(li);
    });
    if (b.you && !b.top.some((r) => r.you)) {
      const li = document.createElement('li'); li.className = 'me';
      const rank = document.createElement('span'); rank.className = 'mono'; rank.textContent = `#${b.you.rank}`;
      const name = document.createElement('span'); name.textContent = b.you.name;
      const tot = document.createElement('strong'); tot.textContent = b.you.total;
      li.append(rank, name, tot);
      list.appendChild(li);
    }
    $('boardName').textContent = player.name;
    window.__lastRank = b.you ? `#${b.you.rank} of ${b.total_players}` : null;
  }

  // ---------- api ----------
  async function getJSON(url, opts) {
    const r = await fetch(url, opts);
    // A host that answers misses with an HTML page (SPA fallback) counts as "not found".
    const isJson = (r.headers.get('content-type') || '').includes('json');
    if (!r.ok || !isJson) {
      const e = new Error(`HTTP ${r.status}`);
      e.status = r.ok ? 404 : r.status;
      throw e;
    }
    return r.json();
  }

  // The puzzle for day D is live from ROLLOVER_UTC_HOUR on D until the same hour on D+1.
  // Must match ROLLOVER_UTC_HOUR in sattap/config.py.
  const ROLLOVER_UTC_HOUR = 18;
  const gameDay = () => new Date(Date.now() - ROLLOVER_UTC_HOUR * 3600e3).toISOString().slice(0, 10);

  // Puzzles are plain JSON files (static on Cloudflare Pages, served by FastAPI locally).
  async function loadPuzzle() {
    const wanted = new URLSearchParams(location.search).get('date');
    if (wanted) return { puzzle: await getJSON(`/puzzles/${wanted}.json`), fallback: false };
    try {
      return { puzzle: await getJSON(`/puzzles/${gameDay()}.json`), fallback: false };
    } catch (e) {
      if (e.status !== 404) throw e;
      return { puzzle: await getJSON('/puzzles/latest.json'), fallback: true };
    }
  }

  // ---------- helpers ----------
  function countUp(node, to, ms = 600) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { node.textContent = to; return; }
    const t0 = performance.now();
    const step = (t) => {
      const p = Math.min((t - t0) / ms, 1);
      node.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // Funny feedback, ten tiers from shame to glory. Picked by score (a hinted score is scaled back
  // up by the hint penalty first, so using the hint doesn't cost you a tier).
  const HINT_MULT = 0.7; // matches HINT_SCORE_MULT in sattap/config.py
  const QUIPS = [
    [97, 'Bullseye. NOAA wants to hire you.'],
    [85, 'Scary good. Are you the satellite?'],
    [70, 'Nice. You can read clouds AND coastlines.'],
    [55, 'Okay, be humble, this is good but still embarrasing.'],
    [40, "Respectable-ish. Actually, I think you need to spend more time thinking about maps, do you even think at all?"],
    [30, 'Warm-ish. Like coffee left on the dashboard.'],
    [20, 'Your geography teacher just felt a chill.'],
    [10, "Right planet. That's the nicest thing we can say."],
    [3, 'The satellite saw that. The satellite is judging you.'],
    [0, "That wasn't a guess, that was a cry for help."],
  ];
  // Score multiplier a result was played under: the server sends it (hint ladders have several),
  // older saves only know whether a hint was used.
  const multOf = (r) => (r.hint_mult != null ? r.hint_mult : r.hint_used ? HINT_MULT : 1);
  const rawScore = (score, mult) => (mult < 1 ? Math.min(100, Math.round(score / mult)) : score);
  const quipFor = (raw) => QUIPS.find(([min]) => raw >= min)[1];

  const total = () => state.results.reduce((a, r) => a + r.score, 0);
  const nRounds = () => state.puzzle.rounds.length;

  // ---------- globe ----------
  // A 3D-looking globe (web/globe.js) instead of a flat map: drag to spin, pinch or scroll to zoom,
  // tap to drop a pin. Land polygons (Natural Earth, bundled in /land.geojson) and country borders
  // are drawn over a flat ocean; there are no labels, roads or API keys.
  // Each round opens centred under the satellite that took the picture (the chip already names it).
  const SAT_LON = { 'GOES-18': -137.0, 'GOES-19': -75.2, 'Meteosat-12': 0.0 }; // sub-satellite longitudes, as in sattap/config.py
  const startLon = (round) => (SAT_LON[round.satellite] !== undefined ? SAT_LON[round.satellite] : -100);

  function initMap() {
    globe = SatTapGlobe.create($('globe'), { onTap: onGlobeTap, colors: COLORS });
    globe.resize();
    fetch('/land.geojson')
      .then((r) => r.json())
      .then((data) => globe.setData({ land: data }))
      .catch(() => { /* the globe still works as a blank ball */ });
    fetch('/borders.geojson')
      .then((r) => r.json())
      .then((data) => globe.setData({ borders: data }))
      .catch(() => { /* borders are a nicety */ });
    fetch('/countries.json')
      .then((r) => r.json())
      .then((data) => globe.setData({ countries: data }))
      .catch(() => { /* names are a nicety */ });
    // country names: on by default, and the choice is remembered on this device
    const LABELS_KEY = 'sattap:labels';
    let labelsOn = true;
    try { labelsOn = localStorage.getItem(LABELS_KEY) !== '0'; } catch { /* private mode etc. */ }
    const applyLabels = () => {
      globe.setLabels(labelsOn);
      $('labelBtn').setAttribute('aria-pressed', String(labelsOn));
    };
    applyLabels();
    $('labelBtn').addEventListener('click', () => {
      labelsOn = !labelsOn;
      try { localStorage.setItem(LABELS_KEY, labelsOn ? '1' : '0'); } catch { /* ignore */ }
      applyLabels();
    });
    $('zoomIn').addEventListener('click', () => globe.zoomBy(1.7));
    $('zoomOut').addEventListener('click', () => globe.zoomBy(1 / 1.7));
    $('zoomReset').addEventListener('click', () => {
      const round = state.puzzle && state.puzzle.rounds[state.index];
      globe.resetView(round ? startLon(round) : -100);
    });
  }

  function onGlobeTap({ lat, lon }) {
    if (state.phase !== 'guess') return;
    state.guess = { lat, lon };
    globe.setGuess(state.guess);
    $('mapHint').hidden = true;
    $('actionBtn').disabled = false;
  }

  // ---------- rendering ----------
  function renderProgress() {
    const wrap = $('progress');
    wrap.innerHTML = '';
    for (let i = 0; i < nRounds(); i++) {
      const d = document.createElement('div');
      if (i < state.results.length) d.className = 'done';
      else if (i === state.index) d.className = 'current';
      wrap.appendChild(d);
    }
  }

  function fmtTime(iso) {
    const d = new Date(iso);
    return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')} UTC`;
  }

  // Position the "your crop is here" box over the contained hint image.
  function layoutHintBox() {
    if (!state.puzzle) return;
    const r = state.puzzle.rounds[state.index];
    const box = $('hintBox');
    if (!state.hintView || !r.hint_box) { box.hidden = true; return; }
    const host = $('crop');
    const side = Math.min(host.clientWidth, host.clientHeight);
    const ox = (host.clientWidth - side) / 2;
    const oy = (host.clientHeight - side) / 2;
    const [x, y, w, h] = r.hint_box;
    box.style.left = `${ox + x * side}px`;
    box.style.top = `${oy + y * side}px`;
    box.style.width = `${w * side}px`;
    box.style.height = `${h * side}px`;
    box.hidden = false;
  }

  // A hint-ladder round (the Band 13 challenge) starts on one layer and unlocks, in order:
  // hint 1 = a second layer of the same scene (GeoColor), hint 2 = the zoomed-out view.
  // r.ladder holds the second layer's media; `mults` are the score multipliers per level.
  const ladderOf = (r) => r.ladder || null;
  const pct = (mult) => `−${Math.round((1 - mult) * 100)}%`;
  const shortBand = (name) => name.split(' ')[0];
  // the layer on screen: the round's own media, or (hint 1+) the ladder's
  const layerOf = (r) => (ladderOf(r) && state.layer === 'alt' ? ladderOf(r) : r);

  function hintLabel(r) {
    const lad = ladderOf(r);
    if (!lad) {
      return state.hintView ? 'Back to close-up' : state.hintUsed ? 'Show wider view' : 'Hint · wider view (−30%)';
    }
    if (state.hintLevel === 0) return `Hint 1 · add ${lad.band} (${pct(lad.mults[1])})`;
    if (state.hintLevel === 1) return `Hint 2 · zoom out (${pct(lad.mults[2])})`;
    return state.hintView ? 'Back to close-up' : 'Show wider view';
  }

  function setHintView(on) {
    const r = state.puzzle.rounds[state.index];
    const lad = ladderOf(r);
    state.hintView = on;
    $('crop').classList.toggle('hinted', on);
    // Loops play while guessing; the reveal (and any missing loop) falls back to the still.
    const animate = state.phase === 'guess';
    const m = layerOf(r);
    const close = (animate && m.loop) || m.image;
    const wide = (animate && m.hint_loop) || m.hint_image;
    $('cropImg').src = on && wide ? wide : close;
    $('lightboxImg').src = close;
    const band = lad && state.layer === 'alt' ? lad.band : r.band;
    $('chipBand').textContent = band;
    // channel info only exists for the Band 13 picture, while guessing
    $('infoBtn').hidden = !(band.startsWith('B13') && state.phase === 'guess');
    $('hintBtn').textContent = hintLabel(r);
    // the layer switch only exists once hint 1 has put a second layer on the table
    const showSwitch = !!lad && state.hintLevel >= 1 && state.phase === 'guess';
    $('layerBtn').hidden = !showSwitch;
    if (showSwitch) {
      const other = state.layer === 'alt' ? r.band : lad.band;
      $('layerBtn').textContent = `Switch to ${shortBand(other)}`;
    }
    layoutHintBox();
  }

  function onHint() {
    if (state.phase !== 'guess') return;
    const r = state.puzzle.rounds[state.index];
    const lad = ladderOf(r);
    if (!lad) {
      if (!state.hintUsed) { state.hintUsed = true; state.hintLevel = 1; save(); }
      setHintView(!state.hintView);
      return;
    }
    if (state.hintLevel === 0) {
      state.hintLevel = 1; state.hintUsed = true; state.layer = 'alt'; // show the new layer straight away
      save();
      setHintView(false);
    } else if (state.hintLevel === 1) {
      state.hintLevel = 2; save();
      setHintView(true);
    } else {
      setHintView(!state.hintView);
    }
  }

  function onLayer() {
    if (state.phase !== 'guess' || !ladderOf(state.puzzle.rounds[state.index])) return;
    state.layer = state.layer === 'alt' ? 'main' : 'alt';
    setHintView(state.hintView);
  }

  function showRound() {
    const r = state.puzzle.rounds[state.index];
    state.phase = 'guess';
    state.guess = null;
    // a hint taken before a reload still counts (the saved level, or level 1 for older saves)
    const resumed = state.pendingHint === state.index;
    state.hintLevel = resumed ? Math.min(state.pendingLevel || 1, ladderOf(r) ? r.ladder.mults.length - 1 : 1) : 0;
    state.hintUsed = state.hintLevel > 0;
    state.pendingHint = null;
    state.pendingLevel = 0;
    state.hintView = false;
    state.layer = ladderOf(r) && state.hintLevel >= 1 ? 'alt' : 'main';
    $('hintBtn').hidden = !r.hint_image;
    globe.clear();
    globe.resize();
    globe.resetView(startLon(r), state.index > 0);

    $('roundLabel').innerHTML = `Round ${state.index + 1} of ${nRounds()} <small>&middot; Where is this?${ladderOf(r) ? ' &middot; Band 13' : ''}</small>`;
    $('runningScore').textContent = total();
    setHintView(false);
    $('chipSat').textContent = r.satellite;
    const ft = r.frame_times || [];
    const when = ft.length > 1 ? `${fmtTime(ft[0]).replace(' UTC', '')}–${fmtTime(ft[ft.length - 1])}` : fmtTime(r.observed_at);
    $('chipMeta').textContent = `~${r.footprint_km.toLocaleString()} km across · ${when}`;
    $('mapHint').hidden = false;
    $('result').hidden = true;
    const btn = $('actionBtn');
    btn.textContent = 'Lock in';
    btn.disabled = true;
    renderProgress();
    setTimeout(() => globe.resize(), 0);
  }

  function showReveal(res, round) {
    state.phase = 'reveal';
    state.layer = 'main'; // the reveal shows the round's own picture
    setHintView(false);
    $('lightboxImg').src = state.puzzle.rounds[state.index].image;
    $('hintBtn').hidden = true;
    const g = state.guess;
    const a = res.answer;

    $('result').hidden = false;
    const hintNote = res.hint_level ? ` · hint ${res.hint_level}` : res.hint_used ? ' · hint' : '';
    $('resDist').textContent = `${Math.round(res.distance_km).toLocaleString()} km${hintNote}`;
    countUp($('resScore'), res.score);
    $('resQuip').textContent = quipFor(rawScore(res.score, multOf(res))) + (res.hint_used ? ' (Hint noted.)' : '');
    $('runningScore').textContent = total();
    const last = state.index === nRounds() - 1;
    const btn = $('actionBtn');
    btn.textContent = last ? 'See results' : 'Next round';
    btn.disabled = false;
    // the result strip just took some height from the globe: re-measure, then frame guess + answer
    globe.resize();
    globe.showReveal({ guess: g, answer: a, footprintKm: round.footprint_km });
  }

  function showSummary() {
    const max = nRounds() * 100;
    $('sumDate').textContent = `SatTap · ${state.puzzle.date}`;
    $('sumTotal').textContent = total();
    $('sumMax').textContent = max;
    const avg = state.results.reduce((a, r) => a + rawScore(r.score, multOf(r)), 0) / Math.max(state.results.length, 1);
    $('sumQuip').textContent = quipFor(Math.round(avg));
    const list = $('sumList');
    list.innerHTML = '';
    state.results.forEach((r) => {
      const li = document.createElement('li');
      li.innerHTML = `<span>Round ${r.round}${r.hint_used ? ' 💡' : ''}</span><span class="mono">${Math.round(r.distance_km).toLocaleString()} km</span><strong>${r.score}</strong>`;
      list.appendChild(li);
    });
    const st = personalStats();
    $('stGames').textContent = st.games;
    $('stStreak').textContent = st.streak;
    $('stAvg').textContent = st.avg;
    $('stBest').textContent = st.best;
    $('summary').hidden = false;
    renderBoard();
  }

  // Share card, MapTap style:
  //   sattap.pages.dev October 19
  //   71🌍 99🛰️ 80🌍 72🌍 85🚀
  //   Final score: 401
  // One emoji per round from the guess itself (hints don't change it); a hinted round gets a 💡 after it.
  const SHARE_EMOJI = [
    [97, '🛰️'], [85, '🚀'], [70, '🌍'], [55, '☀️'], [40, '⛅'],
    [30, '☁️'], [20, '🌧️'], [10, '⛈️'], [3, '🤡'], [0, '💀'],
  ];
  const emojiFor = (raw) => SHARE_EMOJI.find(([min]) => raw >= min)[1];
  function shareDate() {
    const d = new Date(`${state.puzzle.date}T00:00:00Z`);
    return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', timeZone: 'UTC' });
  }
  function shareText() {
    const cells = state.results.map((r) => `${r.score}${emojiFor(rawScore(r.score, multOf(r)))}${r.hint_used ? '💡' : ''}`);
    return [`${location.host} ${shareDate()}`, cells.join(' '), `Final score: ${total()}`].join('\n');
  }

  // ---------- actions ----------
  async function onAction() {
    const btn = $('actionBtn');
    if (state.phase === 'guess') {
      if (!state.guess) return;
      btn.disabled = true;
      btn.textContent = 'Checking…';
      const round = state.puzzle.rounds[state.index];
      try {
        const res = await getJSON('/api/guess', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            date: state.puzzle.date, round: round.round, lat: state.guess.lat, lon: state.guess.lon,
            hint_used: state.hintUsed, hint_level: ladderOf(round) ? state.hintLevel : undefined,
            player: player ? player.player : undefined,
          }),
        });
        state.results.push({
          round: round.round,
          score: res.score,
          hint_used: !!res.hint_used,
          hint_level: res.hint_level ?? null,
          hint_mult: res.hint_mult ?? null,
          distance_km: res.distance_km,
          guess: { ...state.guess },
          answer: res.answer,
        });
        save();
        showReveal(res, round);
      } catch (e) {
        btn.textContent = 'Lock in';
        btn.disabled = false;
        alert('Could not score that guess. Is the server running?');
      }
      return;
    }
    // reveal -> next
    if (state.index === nRounds() - 1) {
      showSummary();
    } else {
      state.index += 1;
      showRound();
    }
  }

  function bindUi() {
    $('actionBtn').addEventListener('click', onAction);
    $('hintBtn').addEventListener('click', onHint);
    $('layerBtn').addEventListener('click', onLayer);
    window.addEventListener('resize', layoutHintBox);
    $('cropBtn').addEventListener('click', () => { $('lightbox').hidden = false; });
    const openInfo = () => { $('chanInfo').hidden = false; $('chanInfo').querySelector('.chan-card').focus(); };
    const closeInfo = () => { $('chanInfo').hidden = true; $('infoBtn').focus(); };
    $('infoBtn').addEventListener('click', openInfo);
    $('chanClose').addEventListener('click', closeInfo);
    $('chanDone').addEventListener('click', closeInfo);
    $('chanInfo').addEventListener('click', (e) => { if (e.target === $('chanInfo')) closeInfo(); });
    $('lightboxClose').addEventListener('click', () => { $('lightbox').hidden = true; });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        $('lightbox').hidden = true;
        if (!$('chanInfo').hidden) closeInfo();
      }
    });
    $('rerollBtn').addEventListener('click', async () => {
      $('rerollBtn').disabled = true;
      await ensurePlayer(true);
      $('rerollBtn').disabled = false;
      renderBoard();
    });
    $('reviewBtn').addEventListener('click', () => { $('summary').hidden = true; });
    $('copyBtn').addEventListener('click', async () => {
      const text = shareText();
      try {
        await navigator.clipboard.writeText(text);
        $('copyBtn').textContent = 'Copied';
      } catch {
        window.prompt('Copy your result:', text);
      }
      setTimeout(() => { $('copyBtn').textContent = 'Copy result'; }, 1500);
    });
  }

  // ---------- boot ----------
  async function boot() {
    bindUi();
    initMap();
    ensurePlayer(); // fire and forget; /api/guess works without it
    try {
      const { puzzle, fallback } = await loadPuzzle();
      state.puzzle = puzzle;
      if (fallback) {
        const n = $('notice');
        n.hidden = false;
        n.textContent = `No puzzle for today yet. Showing ${puzzle.date}.`;
      }
      // dev shortcut: ?fresh=1 forgets saved progress for this puzzle date
      // (the param is dropped from the URL afterwards so a reload keeps your progress)
      const qs = new URLSearchParams(location.search);
      if (qs.has('fresh')) {
        try { localStorage.removeItem(key(puzzle.date)); } catch { /* ignore */ }
        qs.delete('fresh');
        const rest = qs.toString();
        history.replaceState(null, '', location.pathname + (rest ? `?${rest}` : ''));
      }
      const saved = load(puzzle.date);
      if (saved && Array.isArray(saved.results)) {
        state.results = saved.results;
        state.index = Math.min(saved.results.length, nRounds() - 1);
        state.pendingHint = saved.hintRound ?? null;
        state.pendingLevel = saved.hintLevel || 0;
      }
      if (state.results.length >= nRounds()) {
        // Finished already: show the last round's reveal behind the summary, never allow a re-guess.
        state.index = nRounds() - 1;
        showRound();
        const last = state.results[nRounds() - 1];
        state.guess = last.guess;
        showReveal(last, state.puzzle.rounds[state.index]);
        showSummary();
      } else {
        showRound();
      }
    } catch (e) {
      $('roundLabel').textContent = 'No puzzle available';
      const n = $('notice');
      n.hidden = false;
      n.textContent = 'Build one with: python -m sattap.cli build';
    }
  }

  boot();
})();
