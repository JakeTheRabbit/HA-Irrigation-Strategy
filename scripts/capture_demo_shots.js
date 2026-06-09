// Capture the 6 f2.html?demo tab screenshots for the README gallery.
// Standalone demo mode (no HA / no token / no LAN) -> renders perfect mock data.
// Usage: NODE_PATH=$(npm root -g) node scripts/capture_demo_shots.js
const { chromium } = require('playwright');
const path = require('path');

const FILE = 'file:///' + path.resolve(__dirname, '..', 'www', 'f2.html').replace(/\\/g, '/') + '?demo';
const OUT = path.resolve(__dirname, '..', 'img');

// README gallery -> view id mapping
const SHOTS = [
  { name: 'status',  view: 'dashboard' },
  { name: 'zones',   view: 'zones' },
  { name: 'plan',    view: 'timeline' },
  { name: 'tune',    view: 'tune' },
  { name: 'climate', view: 'climate' },
  { name: 'operate', view: 'control' },
];

const setView = (page, v) => page.evaluate((view) => {
  const els = [...document.querySelectorAll('[x-data]')];
  for (const el of els) {
    const d = window.Alpine && window.Alpine.$data(el);
    if (d && typeof d.go === 'function' && 'view' in d) { d.go(view); return 'ok'; }
  }
  return 'noroot';
}, v);

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push('CONSOLE ' + m.text()); });

  console.log('loading', FILE);
  await page.goto(FILE, { waitUntil: 'load', timeout: 30000 });
  try { await page.waitForLoadState('networkidle', { timeout: 8000 }); } catch {}
  await page.waitForTimeout(2500); // Alpine boot + seedDemo + refresh

  for (const s of SHOTS) {
    const r = await setView(page, s.view);
    await page.waitForTimeout(1600); // async section render + charts/canvas
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(200);
    const file = path.join(OUT, `demo-${s.name}.png`);
    await page.screenshot({ path: file, fullPage: false });
    console.log(`  ${s.name.padEnd(8)} view=${s.view.padEnd(10)} setView=${r} -> ${file}`);
  }

  await browser.close();
  console.log(errs.length ? '\nPAGE ERRORS:\n' + errs.join('\n') : '\nno page errors');
})().catch(e => { console.error('FATAL', e); process.exit(1); });
