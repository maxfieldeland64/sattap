/* SatTap globe: a 3D-looking world you can spin and zoom, drawn on a 2D canvas with d3-geo's
 * orthographic projection. No tiles, no WebGL, no API keys: it draws the bundled Natural Earth
 * land and border data. Needs d3-array + d3-geo (web/vendor/) loaded first.
 *
 *   const globe = SatTapGlobe.create(canvas, { onTap({lat, lon}), colors });
 *   globe.setData({ land, borders, countries });   // countries: label anchors (web/countries.json)
 *   globe.setLabels(true);                      // country names on or off
 *   globe.resetView(-137);                      // centre on a longitude, whole globe in view
 *   globe.setGuess({lat, lon});                 // your pin
 *   globe.showReveal({ guess, answer, footprintKm });
 *
 * Controls: drag to spin (with a little momentum), wheel or pinch to zoom toward the cursor or
 * fingers, tap to drop a pin. Arrow keys spin, +/- zoom, Enter drops a pin at the centre.
 * North always stays up, so there is no roll to get lost in.
 */
(() => {
  'use strict';

  const RAD = Math.PI / 180;
  const K_MIN = 1;
  const K_MAX = 40; // at 40x the 50 m land data is about 1 km per pixel: more than enough for a 1,000 km crop
  const TAP_SLOP_PX = 6;
  const TAP_MAX_MS = 600;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const normLon = (l) => ((((l + 180) % 360) + 360) % 360) - 180;
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

  const DEFAULT_COLORS = {
    space: '#080C12',
    ocean: ['#13243A', '#08111C'], // lit side, shadow side
    land: '#2C4159',
    coast: '#5A7594',
    border: '#6B84A3',
    label: '#D2DEEB',
    labelHalo: 'rgba(8, 12, 18, 0.88)',
    graticule: 'rgba(230, 237, 243, 0.06)',
    glow: 'rgba(124, 224, 195, 0.20)',
    accent: '#7CE0C3',
    you: '#FFB547',
    line: '#E6EDF3',
    pinStroke: '#0B0F14',
  };

  function create(canvas, opts = {}) {
    const d3 = window.d3;
    if (!d3 || !d3.geoOrthographic) throw new Error('d3-geo is not loaded');
    const colors = { ...DEFAULT_COLORS, ...(opts.colors || {}) };
    const onTap = opts.onTap || (() => {});
    const ctx = canvas.getContext('2d');

    // ---- view state: the point at the middle of the screen, and the zoom factor ----
    let center = [-100, 15]; // [lon, lat]
    let k = 1;
    let w = 300, h = 300, dpr = 1;
    let baseR = 140; // globe radius in CSS pixels at k = 1

    // ---- data and overlays ----
    let land = null, borders = null;
    let countries = null; // [{n: name, at: [lon, lat], a: area in steradians}], biggest first
    let showLabels = true;
    const graticule = d3.geoGraticule().step([30, 30])();
    let guess = null, answer = null, footprint = null;

    const projection = d3.geoOrthographic().clipAngle(90).precision(0.6);
    const path = d3.geoPath(projection, ctx);

    function syncProjection() {
      projection
        .translate([w / 2, h / 2])
        .scale(baseR * k)
        .rotate([-center[0], -center[1]])
        .clipExtent([[-8, -8], [w + 8, h + 8]]);
    }

    // ---- drawing ----
    let dirty = false;
    let interacting = false;
    function requestDraw() {
      if (dirty) return;
      dirty = true;
      requestAnimationFrame(() => { dirty = false; draw(); });
    }

    const visible = (p) => d3.geoDistance(center, p) < Math.PI / 2 - 0.002;

    function drawPin(p, fill, r) {
      if (!p || !visible([p.lon, p.lat])) return;
      const xy = projection([p.lon, p.lat]);
      if (!xy) return;
      ctx.beginPath();
      ctx.arc(xy[0], xy[1], r, 0, 2 * Math.PI);
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = colors.pinStroke;
      ctx.stroke();
    }

    // ---- country names ----
    // Only names that fit inside their own country at this zoom are drawn, biggest countries first,
    // and a name that would overlap one already placed is skipped. So zooming in reveals more.
    const widths = new Map();
    function textWidth(text, size) {
      const key = size + '|' + text;
      let v = widths.get(key);
      if (v === undefined) { v = ctx.measureText(text).width; widths.set(key, v); }
      return v;
    }

    function drawLabels(R) {
      if (!showLabels || !countries) return;
      const placed = [];
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.lineJoin = 'round';
      ctx.lineWidth = 3;
      for (const c of countries) {
        if (placed.length >= 90) break;
        const dist = d3.geoDistance(center, c.at);
        if (dist > 1.35) continue; // about 77 degrees out: too close to the edge to read
        const fore = Math.cos(dist); // how face-on that part of the globe is
        const sizePx = Math.sqrt(c.a) * R * fore; // rough width of the country on screen
        const size = sizePx > 150 ? 13 : 11;
        ctx.font = `500 ${size}px "Instrument Sans", system-ui, sans-serif`;
        const tw = textWidth(c.n, size);
        if (sizePx < tw * 0.9) continue; // would not fit inside the country
        const xy = projection(c.at);
        if (!xy || xy[0] < -20 || xy[0] > w + 20 || xy[1] < -10 || xy[1] > h + 10) continue;
        const x0 = xy[0] - tw / 2 - 3, y0 = xy[1] - size / 2 - 2, bw = tw + 6, bh = size + 4;
        if (placed.some((p) => x0 < p[0] + p[2] && x0 + bw > p[0] && y0 < p[1] + p[3] && y0 + bh > p[1])) continue;
        placed.push([x0, y0, bw, bh]);
        ctx.globalAlpha = clamp((fore - 0.2) / 0.35, 0, 1) * 0.92; // fade toward the edge
        ctx.strokeStyle = colors.labelHalo;
        ctx.strokeText(c.n, xy[0], xy[1]);
        ctx.fillStyle = colors.label;
        ctx.fillText(c.n, xy[0], xy[1]);
      }
      ctx.globalAlpha = 1;
    }

    function draw() {
      syncProjection();
      const R = baseR * k;
      const cx = w / 2, cy = h / 2;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = colors.space;
      ctx.fillRect(0, 0, w, h);

      // soft atmosphere ring, only while the globe's edge is on screen
      if (R < Math.hypot(w, h)) {
        const g = ctx.createRadialGradient(cx, cy, R * 0.97, cx, cy, R * 1.14);
        g.addColorStop(0, colors.glow);
        g.addColorStop(1, 'rgba(124, 224, 195, 0)');
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(cx, cy, R * 1.14, 0, 2 * Math.PI);
        ctx.fill();
      }

      // ocean, lit from the upper left
      const og = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R * 1.02);
      og.addColorStop(0, colors.ocean[0]);
      og.addColorStop(1, colors.ocean[1]);
      ctx.fillStyle = og;
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, 2 * Math.PI);
      ctx.fill();

      ctx.lineJoin = 'round';
      if (k < 12) {
        ctx.beginPath(); path(graticule);
        ctx.lineWidth = 1; ctx.strokeStyle = colors.graticule; ctx.stroke();
      }
      if (land) {
        ctx.beginPath(); path(land);
        ctx.fillStyle = colors.land; ctx.fill();
        ctx.lineWidth = 0.6; ctx.strokeStyle = colors.coast; ctx.stroke();
      }
      // borders are the heaviest layer, so they sit out while you are mid-spin on a slow device
      if (borders && !(interacting && k < 2)) {
        ctx.beginPath(); path(borders);
        ctx.lineWidth = 0.9; ctx.strokeStyle = colors.border; ctx.globalAlpha = 0.85; ctx.stroke();
        ctx.globalAlpha = 1;
      }

      // limb shading so the sphere reads as round (darkens toward the edge)
      if (R < Math.hypot(w, h)) {
        const sg = ctx.createRadialGradient(cx, cy, R * 0.55, cx, cy, R);
        sg.addColorStop(0, 'rgba(5, 8, 12, 0)');
        sg.addColorStop(1, 'rgba(5, 8, 12, 0.38)');
        ctx.fillStyle = sg;
        ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.fill();
        ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI);
        ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(230, 237, 243, 0.14)'; ctx.stroke();
      }

      drawLabels(R);

      // reveal overlays, then pins on top
      if (footprint) {
        ctx.beginPath(); path(footprint);
        ctx.setLineDash([4, 3]); ctx.lineWidth = 1.2; ctx.strokeStyle = colors.line; ctx.globalAlpha = 0.6; ctx.stroke();
        ctx.globalAlpha = 1; ctx.setLineDash([]);
      }
      if (guess && answer) {
        ctx.beginPath();
        path({ type: 'LineString', coordinates: [[guess.lon, guess.lat], [answer.lon, answer.lat]] }); // a great circle
        ctx.setLineDash([4, 5]); ctx.lineWidth = 2; ctx.strokeStyle = colors.accent; ctx.globalAlpha = 0.9; ctx.stroke();
        ctx.globalAlpha = 1; ctx.setLineDash([]);
      }
      if (answer) {
        drawPin(guess, colors.you, 7);
        drawPin(answer, colors.accent, 9);
      } else {
        drawPin(guess, colors.accent, 9);
      }
    }

    // ---- sizing ----
    function resize() {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      w = rect.width; h = rect.height;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      baseR = Math.min(w, h) / 2 * 0.9;
      requestDraw();
    }
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(resize) : null;
    if (ro) ro.observe(canvas); else window.addEventListener('resize', resize);

    // ---- moving the view ----
    let anim = null; // {raf} while a fly-to or a momentum spin is running
    function stopAnim() { if (anim) { cancelAnimationFrame(anim.raf); anim = null; } }

    function rotateBy(dx, dy) {
      // 1 px of drag is about 1 px of surface under the finger at the centre of the screen
      const degPerPx = 1 / (baseR * k * RAD);
      const lonScale = 1 / Math.max(Math.cos(center[1] * RAD), 0.25);
      center = [normLon(center[0] - dx * degPerPx * lonScale), clamp(center[1] + dy * degPerPx, -89, 89)];
      requestDraw();
    }

    // Zoom so the spot under (x, y) stays roughly where it is: nudge the centre toward it.
    function zoomAt(x, y, factor) {
      const nk = clamp(k * factor, K_MIN, K_MAX);
      if (nk === k) return;
      syncProjection();
      const dx = x - w / 2, dy = y - h / 2;
      if (dx * dx + dy * dy < (baseR * k) ** 2) {
        const p = projection.invert([x, y]);
        if (p && p.every(Number.isFinite)) {
          const t = 1 - k / nk; // zooming in pulls toward the cursor, zooming out eases back
          const c = d3.geoInterpolate(center, p)(t);
          center = [normLon(c[0]), clamp(c[1], -89, 89)];
        }
      }
      k = nk;
      requestDraw();
    }

    function flyTo(toCenter, toK, ms = 700) {
      stopAnim();
      toK = clamp(toK, K_MIN, K_MAX);
      if (reduceMotion() || ms <= 0) {
        center = [normLon(toCenter[0]), clamp(toCenter[1], -89, 89)]; k = toK; requestDraw(); return;
      }
      const c0 = center.slice(), k0 = k;
      const interp = d3.geoInterpolate(c0, toCenter);
      const t0 = performance.now();
      anim = { raf: 0 };
      const step = (now) => {
        const t = clamp((now - t0) / ms, 0, 1);
        const e = easeInOut(t);
        const c = interp(e);
        center = [normLon(c[0]), clamp(c[1], -89, 89)];
        k = k0 * Math.pow(toK / k0, e);
        interacting = t < 1;
        draw();
        if (t < 1) anim.raf = requestAnimationFrame(step);
        else { anim = null; requestDraw(); }
      };
      anim.raf = requestAnimationFrame(step);
    }

    function coast(vx, vy) { // momentum after letting go, px/ms
      if (reduceMotion() || Math.hypot(vx, vy) < 0.05) return;
      stopAnim();
      let last = performance.now();
      anim = { raf: 0 };
      const step = (now) => {
        const dt = Math.min(now - last, 40); last = now;
        rotateBy(vx * dt, vy * dt);
        const decay = Math.pow(0.0025, dt / 1000); // loses ~99.7% of its speed per second
        vx *= decay; vy *= decay;
        interacting = true;
        draw();
        if (Math.hypot(vx, vy) > 0.02) anim.raf = requestAnimationFrame(step);
        else { anim = null; interacting = false; requestDraw(); }
      };
      anim.raf = requestAnimationFrame(step);
    }

    // ---- pointer input ----
    const pointers = new Map(); // id -> {x, y}
    let gesture = null; // single-finger/mouse: {sx, sy, st, lx, ly, lt, vx, vy, moved}
    let pinch = null; // two fingers: {dist, mx, my}

    const local = (e) => { const r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };

    function tapAt(x, y) {
      syncProjection();
      const dx = x - w / 2, dy = y - h / 2;
      if (dx * dx + dy * dy > (baseR * k) ** 2) return; // missed the globe
      const p = projection.invert([x, y]);
      if (!p || !p.every(Number.isFinite)) return;
      onTap({ lat: clamp(p[1], -90, 90), lon: normLon(p[0]) });
    }

    canvas.addEventListener('pointerdown', (e) => {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      try { canvas.setPointerCapture(e.pointerId); } catch { /* synthetic or already-ended pointer */ }
      stopAnim();
      const { x, y } = local(e);
      pointers.set(e.pointerId, { x, y });
      interacting = true;
      if (pointers.size === 1) {
        gesture = { sx: x, sy: y, st: performance.now(), lx: x, ly: y, lt: performance.now(), vx: 0, vy: 0, moved: false };
        pinch = null;
      } else if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y) || 1, mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
        if (gesture) gesture.moved = true; // a second finger means this is not a tap
      }
    });

    canvas.addEventListener('pointermove', (e) => {
      if (!pointers.has(e.pointerId)) return;
      const { x, y } = local(e);
      pointers.set(e.pointerId, { x, y });
      if (pointers.size >= 2 && pinch) {
        const [a, b] = [...pointers.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y) || 1;
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
        rotateBy(mx - pinch.mx, my - pinch.my); // two-finger drag still spins
        zoomAt(mx, my, dist / pinch.dist);
        pinch = { dist, mx, my };
        return;
      }
      if (!gesture) return;
      if (!gesture.moved && Math.hypot(x - gesture.sx, y - gesture.sy) > TAP_SLOP_PX) gesture.moved = true;
      if (gesture.moved) {
        const now = performance.now();
        const dt = Math.max(now - gesture.lt, 1);
        const ddx = x - gesture.lx, ddy = y - gesture.ly;
        rotateBy(ddx, ddy);
        // smoothed release velocity in px/ms
        gesture.vx = 0.7 * (ddx / dt) + 0.3 * gesture.vx;
        gesture.vy = 0.7 * (ddy / dt) + 0.3 * gesture.vy;
        gesture.lt = now;
      }
      gesture.lx = x; gesture.ly = y;
    });

    function endPointer(e, cancelled) {
      if (!pointers.has(e.pointerId)) return;
      pointers.delete(e.pointerId);
      if (pointers.size === 1 && pinch) {
        // one finger lifted mid-pinch: carry on spinning with the other, never as a tap
        const p = [...pointers.values()][0];
        gesture = { sx: p.x, sy: p.y, st: 0, lx: p.x, ly: p.y, lt: performance.now(), vx: 0, vy: 0, moved: true };
        pinch = null;
        return;
      }
      if (pointers.size > 0) return;
      pinch = null;
      const g = gesture; gesture = null;
      interacting = false;
      if (!g || cancelled) { requestDraw(); return; }
      if (!g.moved && performance.now() - g.st <= TAP_MAX_MS) { requestDraw(); tapAt(g.sx, g.sy); return; }
      // flick: only if the finger was still moving when it lifted
      const idle = performance.now() - g.lt;
      if (g.moved && idle < 80) coast(g.vx, g.vy);
      else requestDraw();
    }
    canvas.addEventListener('pointerup', (e) => endPointer(e, false));
    canvas.addEventListener('pointercancel', (e) => endPointer(e, true));
    canvas.addEventListener('lostpointercapture', (e) => endPointer(e, true));

    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      stopAnim();
      const { x, y } = local(e);
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
      const speed = e.ctrlKey ? 0.012 : 0.0016; // pinch on a trackpad arrives as ctrl+wheel
      zoomAt(x, y, Math.exp(-e.deltaY * unit * speed));
    }, { passive: false });

    canvas.addEventListener('keydown', (e) => {
      const step = 60;
      const handled = {
        ArrowLeft: () => rotateBy(step, 0), ArrowRight: () => rotateBy(-step, 0),
        ArrowUp: () => rotateBy(0, step), ArrowDown: () => rotateBy(0, -step),
        '+': () => zoomAt(w / 2, h / 2, 1.5), '=': () => zoomAt(w / 2, h / 2, 1.5), '-': () => zoomAt(w / 2, h / 2, 1 / 1.5),
        Enter: () => onTap({ lat: center[1], lon: center[0] }),
      }[e.key];
      if (handled) { e.preventDefault(); stopAnim(); handled(); }
    });

    // ---- public API ----
    function fitView(points, extraRad = 0) {
      // centre on the points and zoom until they (plus a margin) fill the panel
      let c;
      if (points.length === 1) c = points[0];
      else c = d3.geoInterpolate(points[0], points[1])(0.5);
      let theta = extraRad;
      points.forEach((p) => { theta = Math.max(theta, d3.geoDistance(c, p) + extraRad); });
      const avail = Math.min(w, h) / 2 - 40;
      const fitK = theta < 0.002 ? K_MAX : avail / (baseR * Math.sin(Math.min(theta, Math.PI / 2)));
      return { center: c, k: clamp(fitK, K_MIN, K_MAX) };
    }

    return {
      resize,
      setData(d) {
        if (d.land !== undefined) land = d.land;
        if (d.borders !== undefined) borders = d.borders;
        if (d.countries !== undefined) countries = d.countries;
        requestDraw();
      },
      setLabels(on) { showLabels = !!on; requestDraw(); },
      /** Whole globe in view, centred on `lon` (a satellite's longitude, say). */
      resetView(lon = -100, animate = true) {
        flyTo([normLon(lon), 12], 1, animate ? 650 : 0);
      },
      setGuess(p) {
        guess = p ? { lat: p.lat, lon: p.lon } : null;
        answer = null; footprint = null;
        requestDraw();
      },
      clear() { guess = answer = footprint = null; requestDraw(); },
      showReveal({ guess: g, answer: a, footprintKm }) {
        guess = { lat: g.lat, lon: g.lon };
        answer = { lat: a.lat, lon: a.lon };
        // the crop's footprint as a lat/lon box (a little wider toward the poles)
        const dLat = footprintKm / 2 / 111.2;
        const dLon = dLat / Math.max(Math.cos(a.lat * RAD), 0.05);
        footprint = d3.geoGraticule().extent([[a.lon - dLon, a.lat - dLat], [a.lon + dLon, a.lat + dLat]]).precision(0.5).outline();
        const half = (footprintKm / 2) * Math.SQRT2 / 6371;
        const fit = fitView([[g.lon, g.lat], [a.lon, a.lat]], half);
        flyTo(fit.center, fit.k, 900);
      },
      zoomBy(factor) { stopAnim(); zoomAt(w / 2, h / 2, factor); },
      get view() { return { center: center.slice(), k }; },
      destroy() { stopAnim(); if (ro) ro.disconnect(); },
    };
  }

  window.SatTapGlobe = { create };
})();
