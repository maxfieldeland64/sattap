// Builds web/countries.json: one label anchor per country (name, a [lon, lat] point on its largest
// piece, and its area) from Natural Earth 50m via the world-atlas package. The globe uses it to write country
// names, showing only the ones that fit at the current zoom.
//
//   npm i --no-save world-atlas topojson-client d3-geo
//   node tools/make_country_labels.mjs
import { readFileSync, writeFileSync } from 'node:fs';

import { geoArea, geoCentroid } from 'd3-geo';
import { feature } from 'topojson-client';

const topo = JSON.parse(readFileSync('node_modules/world-atlas/countries-50m.json', 'utf8'));
const countries = feature(topo, topo.objects.countries).features;

// Natural Earth abbreviates a lot of names to fit its own maps; spell the common ones out.
const NAMES = {
  'United States of America': 'United States',
  'Dem. Rep. Congo': 'DR Congo',
  'Dominican Rep.': 'Dominican Republic',
  'Bosnia and Herz.': 'Bosnia & Herz.',
  'S. Sudan': 'South Sudan',
  'W. Sahara': 'Western Sahara',
  'Eq. Guinea': 'Equatorial Guinea',
  'Solomon Is.': 'Solomon Islands',
  'Falkland Is.': 'Falkland Islands',
  'Macedonia': 'North Macedonia',
  'eSwatini': 'Eswatini',
  'Central African Rep.': 'Central African Rep.',
  'N. Cyprus': 'N. Cyprus',
};
// pieces too small to carry a label anywhere (and not countries a player would look for)
const SKIP = new Set(['Fr. S. Antarctic Lands', 'Heard I. and McDonald Is.', 'S. Geo. and the Is.', 'Indian Ocean Ter.', 'Siachen Glacier', 'Br. Indian Ocean Ter.', 'Ashmore and Cartier Is.', 'Antarctica']);

const r = (n, d = 2) => Math.round(n * 10 ** d) / 10 ** d;
const out = [];
for (const f of countries) {
  const name = f.properties.name;
  if (!name || SKIP.has(name)) continue;
  const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
  // label the biggest piece (mainland France, not French Guiana)
  let best = null, bestA = -1, total = 0;
  for (const coordinates of polys) {
    const g = { type: 'Polygon', coordinates };
    const a = geoArea(g);
    total += a;
    if (a > bestA) { best = g; bestA = a; }
  }
  const [lon, lat] = geoCentroid(best);
  // the point is a [lon, lat] pair, not lat/lon keys: tools/publish.py refuses any public JSON with those keys
  out.push({ n: NAMES[name] || name, at: [r(lon), r(lat)], a: r(bestA, 6) });
}
out.sort((x, y) => y.a - x.a); // biggest first: they win when labels collide
writeFileSync('web/countries.json', JSON.stringify(out));
console.log(`wrote web/countries.json with ${out.length} labels`);
