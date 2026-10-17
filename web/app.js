/* SatTap web POC: vanilla JS + Leaflet. Talks to /api/puzzle/* and /api/guess. */
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
    hintUsed: false, // wider-view hint taken this round (score x0.7)
    hintView: false, // currently showing the wider view
  };

  let map, layers;

  // ---------- storage ----------
  const key = (d) => `sattap:${d}`;
  const load = (d) => { try { return JSON.parse(localStorage.getItem(key(d))); } catch { return null; } };
  const save = () => {
    try {
      // hintRound remembers an unscored hint so a reload can't undo the penalty
      const hintRound = state.hintUsed && state.phase === 'guess' ? state.index : null;
      localStorage.setItem(key(state.puzzle.date), JSON.stringify({ results: state.results, hintRound }));
    } catch { /* private mode etc. */ }
  };

  // ---------- api ----------
  async function getJSON(url, opts) {
    const r = await fetch(url, opts);
    if (!r.ok) {
      const e = new Error(`HTTP ${r.status}`);
      e.status = r.status;
      throw e;
    }
    return r.json();
  }

  async function loadPuzzle() {
    const wanted = new URLSearchParams(location.search).get('date');
    if (wanted) return { puzzle: await getJSON(`/api/puzzle/${wanted}`), fallback: false };
    try {
      return { puzzle: await getJSON('/api/puzzle/today'), fallback: false };
    } catch (e) {
      if (e.status !== 404) throw e;
      return { puzzle: await getJSON('/api/puzzle/latest'), fallback: true };
    }
  }

  // ---------- helpers ----------
  const normLng = (lng) => ((((lng + 180) % 360) + 360) % 360) - 180;

  function footprintBounds(lat, lon, km) {
    const dLat = km / 2 / 111.2;
    const dLon = dLat / Math.max(Math.cos((lat * Math.PI) / 180), 0.05);
    return L.latLngBounds([lat - dLat, lon - dLon], [lat + dLat, lon + dLon]);
  }

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

  const total = () => state.results.reduce((a, r) => a + r.score, 0);
  const nRounds = () => state.puzzle.rounds.length;

  // ---------- map ----------
  // World view used at the start of every round (fits the whole map in the panel).
  const WORLD = [[-58, -170], [72, 170]];

  function resetView() {
    map.setMinZoom(0);
    map.fitBounds(WORLD, { animate: false });
    map.setMinZoom(map.getZoom());
  }

  function initMap() {
    // No tile server: land polygons (Natural Earth, bundled in /land.geojson) over a flat ocean.
    // No labels, borders, or roads, so players have to work from shape and context alone.
    map = L.map('map', {
      zoomControl: false,
      zoomSnap: 0.25,
      maxZoom: 9,
      preferCanvas: true,
      maxBounds: [[-85, -180], [85, 180]],
      maxBoundsViscosity: 1.0,
      attributionControl: true,
    });
    map.attributionControl.setPrefix(false);
    map.attributionControl.addAttribution('Land: Natural Earth');
    map.createPane('land').style.zIndex = 250;
    layers = L.layerGroup().addTo(map);
    resetView();
    fetch('/land.geojson')
      .then((r) => r.json())
      .then((data) => {
        L.geoJSON(data, {
          pane: 'land',
          interactive: false,
          style: { color: '#2B3A4D', weight: 0.6, fillColor: '#1A2736', fillOpacity: 1 },
        }).addTo(map);
      })
      .catch(() => { /* map still works as a blank canvas */ });
    map.on('click', onMapClick);
    window.addEventListener('resize', () => {
      map.invalidateSize();
      if (state.phase === 'guess' && !state.guess) resetView();
    });
  }

  const pin = (latlng, color, r = 9) =>
    L.circleMarker(latlng, { radius: r, color: '#0B0F14', weight: 2, fillColor: color, fillOpacity: 1 });

  function onMapClick(e) {
    if (state.phase !== 'guess') return;
    const lat = Math.max(-90, Math.min(90, e.latlng.lat));
    const lon = normLng(e.latlng.lng);
    state.guess = { lat, lon };
    layers.clearLayers();
    pin([lat, lon], COLORS.accent).addTo(layers);
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

  function setHintView(on) {
    const r = state.puzzle.rounds[state.index];
    state.hintView = on;
    $('crop').classList.toggle('hinted', on);
    // Loops play while guessing; the reveal (and any missing loop) falls back to the still.
    const animate = state.phase === 'guess';
    const close = (animate && r.loop) || r.image;
    const wide = (animate && r.hint_loop) || r.hint_image;
    $('cropImg').src = on && wide ? wide : close;
    $('hintBtn').textContent = on
      ? 'Back to close-up'
      : state.hintUsed ? 'Show wider view' : 'Hint · wider view (−30%)';
    layoutHintBox();
  }

  function onHint() {
    if (state.phase !== 'guess') return;
    if (!state.hintUsed) { state.hintUsed = true; save(); }
    setHintView(!state.hintView);
  }

  function showRound() {
    const r = state.puzzle.rounds[state.index];
    state.phase = 'guess';
    state.guess = null;
    state.hintUsed = state.pendingHint === state.index;
    state.pendingHint = null;
    state.hintView = false;
    $('hintBtn').hidden = !r.hint_image;
    layers.clearLayers();
    map.invalidateSize();
    resetView();

    $('roundLabel').innerHTML = `Round ${state.index + 1} of ${nRounds()} <small>&middot; Where is this?</small>`;
    $('runningScore').textContent = total();
    setHintView(false);
    $('lightboxImg').src = r.loop || r.image;
    $('chipBand').textContent = r.band;
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
    setTimeout(() => map.invalidateSize(), 0);
  }

  function showReveal(res, round) {
    state.phase = 'reveal';
    setHintView(false);
    $('lightboxImg').src = state.puzzle.rounds[state.index].image;
    $('hintBtn').hidden = true;
    const g = state.guess;
    const a = res.answer;
    layers.clearLayers();
    const fp = footprintBounds(a.lat, a.lon, round.footprint_km);
    L.rectangle(fp, { color: COLORS.line, weight: 1.2, opacity: 0.55, dashArray: '4 3', fill: false, interactive: false }).addTo(layers);
    L.polyline([[g.lat, g.lon], [a.lat, a.lon]], { color: COLORS.accent, weight: 2, dashArray: '4 5', opacity: 0.9 }).addTo(layers);
    pin([g.lat, g.lon], COLORS.you, 7).addTo(layers);
    pin([a.lat, a.lon], COLORS.accent, 9).addTo(layers);
    const bounds = L.latLngBounds([[g.lat, g.lon], [a.lat, a.lon]]).extend(fp);
    map.fitBounds(bounds, { padding: [48, 48], maxZoom: 6 });

    $('result').hidden = false;
    $('resDist').textContent = `${Math.round(res.distance_km).toLocaleString()} km${res.hint_used ? ' · hint' : ''}`;
    countUp($('resScore'), res.score);
    $('runningScore').textContent = total();
    const last = state.index === nRounds() - 1;
    const btn = $('actionBtn');
    btn.textContent = last ? 'See results' : 'Next round';
    btn.disabled = false;
    setTimeout(() => map.invalidateSize(), 0);
  }

  function showSummary() {
    const max = nRounds() * 100;
    $('sumDate').textContent = `SatTap · ${state.puzzle.date}`;
    $('sumTotal').textContent = total();
    $('sumMax').textContent = max;
    const list = $('sumList');
    list.innerHTML = '';
    state.results.forEach((r) => {
      const li = document.createElement('li');
      li.innerHTML = `<span>Round ${r.round}${r.hint_used ? ' 💡' : ''}</span><span class="mono">${Math.round(r.distance_km).toLocaleString()} km</span><strong>${r.score}</strong>`;
      list.appendChild(li);
    });
    $('summary').hidden = false;
  }

  function shareText() {
    return [
      `SatTap ${state.puzzle.date}`,
      state.results.map((r) => `${r.score}${r.hint_used ? '*' : ''}`).join(' · '),
      state.results.some((r) => r.hint_used) ? '* used a hint' : null,
      `Total ${total()}/${nRounds() * 100}`,
    ].filter(Boolean).join('\n');
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
          body: JSON.stringify({ date: state.puzzle.date, round: round.round, lat: state.guess.lat, lon: state.guess.lon, hint_used: state.hintUsed }),
        });
        state.results.push({
          round: round.round,
          score: res.score,
          hint_used: !!res.hint_used,
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
    window.addEventListener('resize', layoutHintBox);
    $('cropBtn').addEventListener('click', () => { $('lightbox').hidden = false; });
    $('lightboxClose').addEventListener('click', () => { $('lightbox').hidden = true; });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { $('lightbox').hidden = true; }
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
    try {
      const { puzzle, fallback } = await loadPuzzle();
      state.puzzle = puzzle;
      if (fallback) {
        const n = $('notice');
        n.hidden = false;
        n.textContent = `No puzzle for today yet. Showing ${puzzle.date}.`;
      }
      const saved = load(puzzle.date);
      if (saved && Array.isArray(saved.results)) {
        state.results = saved.results;
        state.index = Math.min(saved.results.length, nRounds() - 1);
        state.pendingHint = saved.hintRound ?? null;
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
