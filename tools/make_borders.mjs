// Builds web/borders.geojson: the land borders between countries (no coastlines, those come from
// web/land.geojson) from Natural Earth 50m via the world-atlas package. No labels, names or flags.
//
//   npm i --no-save world-atlas topojson-client
//   node tools/make_borders.mjs
import { readFileSync, writeFileSync } from 'node:fs';

import { mesh } from 'topojson-client';

const topo = JSON.parse(readFileSync('node_modules/world-atlas/countries-50m.json', 'utf8'));
// interior borders only: arcs shared by two different countries
const lines = mesh(topo, topo.objects.countries, (a, b) => a !== b).coordinates;

const r = (n) => Math.round(n * 1000) / 1000;
const out = [];
for (const line of lines) {
  // split any segment that jumps across the antimeridian so it is not drawn across the whole map
  let cur = [];
  for (let i = 0; i < line.length; i++) {
    const [x, y] = line[i];
    if (cur.length && Math.abs(x - cur[cur.length - 1][0]) > 180) {
      if (cur.length > 1) out.push(cur);
      cur = [];
    }
    cur.push([r(x), r(y)]);
  }
  if (cur.length > 1) out.push(cur);
}

const geo = { type: 'Feature', properties: {}, geometry: { type: 'MultiLineString', coordinates: out } };
writeFileSync('web/borders.geojson', JSON.stringify(geo));
console.log(`wrote web/borders.geojson with ${out.length} lines`);
