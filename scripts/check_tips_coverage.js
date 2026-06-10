const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const TIPS = JSON.parse(fs.readFileSync(path.resolve(__dirname, 'tips_data.json'), 'utf8'));
const FILE = 'file:///' + path.resolve(__dirname, '..', 'www', 'f2.html').replace(/\\/g, '/') + '?demo';
(async () => {
  const b = await chromium.launch({ channel: 'chrome', headless: true });
  const p = await b.newContext({ viewport: { width: 1440, height: 1100 } }).then(c => c.newPage());
  await p.goto(FILE, { waitUntil: 'load', timeout: 30000 });
  await p.waitForTimeout(2500);
  const keys = await p.evaluate(() => {
    const r = [...document.querySelectorAll('[x-data]')].map(e => window.Alpine && Alpine.$data(e)).find(d => d && 'snapshot' in d);
    return {
      snapshot: r.snapshot.map(s => [s.label]),
      plant: r.plant.map(g => [g.label]),
      'climate tiles': r.climate.map(m => [m.label]),
      climateCtl: r.climateCtl.flatMap(g => g.items.map(it => [it.id, it.label])),
      relays: r.relays.flatMap(g => g.rows.map(x => [x.id, x.label])),
      arm: r.control.arm.map(t => [t.id, t.label]),
      telemetry: r.control.telemetry.map(t => [t.label]),
      summary: r.control.summary.map(s => [s.k]),
      raw: r.raw.map(x => [x.label]),
      'zones nums': r.zones.flatMap(z => (z.nums || []).map(n => [n.id, n.label])),
      'zones selects': r.zones.flatMap(z => (z.selects || []).map(n => [n.id, n.label])),
      steeringMeta: (r.steeringMeta || []).map(m => [m.label]),
      nav: [['nav:dashboard','Status'],['nav:zones','Zones'],['nav:climate','Climate'],['nav:control','Operate'],['nav:tune','Tune'],['nav:timeline','Plan'],['nav:floor','3D Floor']],
    };
  });
  await b.close();
  let tot = 0, hits = 0; const missAll = [];
  for (const [name, list] of Object.entries(keys)) {
    const miss = list.filter(ks => !ks.some(k => k && TIPS[k]));
    tot += list.length; hits += list.length - miss.length;
    console.log(name.padEnd(15), (list.length - miss.length) + '/' + list.length, miss.length ? ' miss: ' + miss.map(m => m[1] || m[0]).slice(0, 10).join(', ') : '');
    missAll.push(...miss.map(m => ({ group: name, keys: m })));
  }
  console.log('\nTOTAL', hits + '/' + tot);
  fs.writeFileSync('C:/tmp/tip_misses.json', JSON.stringify(missAll, null, 1));
})().catch(e => { console.error('FATAL', e); process.exit(1); });
