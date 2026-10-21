// Builds web/lakes.geojson: lake polygons from Natural Earth 50m (public domain), which the globe
// paints in the ocean colour over web/land.geojson (the land polygons are solid, so lakes such as
// the Great Lakes, Victoria or the Caspian would otherwise read as land). Geometry only: no names.
//
// The Caspian Sea is not in Natural Earth's lakes layer (it sits in the ocean layer), so that one
// polygon is picked out of ne_50m_ocean by its bounding box.
//
//   node tools/make_lakes.mjs                                    # downloads both layers
//   node tools/make_lakes.mjs ne_50m_lakes.geojson ne_50m_ocean.geojson
import { readFileSync, writeFileSync } from 'node:fs';

const BASE = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/';
const load = async (arg, name) =>
  JSON.parse(arg ? readFileSync(arg, 'utf8') : await (await fetch(BASE + name)).text());
const fc = await load(process.argv[2], 'ne_50m_lakes.geojson');
const ocean = await load(process.argv[3], 'ne_50m_ocean.geojson');

const r = (n) => Math.round(n * 100) / 100; // about 1 km, plenty for a 50 m dataset
const ring = (rg) => {
  const out = [];
  for (const [x, y] of rg) {
    const p = [r(x), r(y)];
    const last = out[out.length - 1];
    if (!last || last[0] !== p[0] || last[1] !== p[1]) out.push(p); // drop points that rounding collapsed
  }
  return out.length >= 4 ? out : null;
};
const poly = (p) => {
  const rings = p.map(ring);
  return rings[0] ? rings.filter(Boolean) : null; // keep holes (islands in lakes) if they survive
};

const partsOf = (g) => (g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : []);

const polys = [];
for (const f of fc.features) {
  if (!f.geometry) continue;
  for (const p of partsOf(f.geometry)) {
    const q = poly(p);
    if (q) polys.push(q);
  }
}

// Caspian Sea: the ocean-layer polygon that sits entirely inside this box
const inCaspian = (p) => p[0].every(([x, y]) => x > 45 && x < 56 && y > 35 && y < 48);
const caspian = ocean.features.flatMap((f) => partsOf(f.geometry)).filter(inCaspian);
if (caspian.length !== 1) throw new Error(`expected one Caspian polygon, found ${caspian.length}`);
polys.push(poly(caspian[0]));

const geo = { type: 'Feature', properties: {}, geometry: { type: 'MultiPolygon', coordinates: polys } };
writeFileSync('web/lakes.geojson', JSON.stringify(geo));
console.log(`wrote web/lakes.geojson with ${polys.length} lakes`);
