// Verify home.html?demo (tabbed v2) renders with no errors. Probes + screenshots of tabs + room modal.
const { chromium } = require('playwright');
const path = require('path');
const FILE = 'file:///' + path.resolve(__dirname, '..', 'www', 'home.html').replace(/\\/g, '/') + '?demo';
const IMG = (n) => path.resolve(__dirname, '..', 'img', n);
const G = (id) => `(document.getElementById('${id}')||{}).children` ;
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1480, height: 1000 }, deviceScaleFactor: 1.4 });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => errs.push('PAGEERR ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push('CONSOLE ' + m.text()); });
  console.log('loading', FILE);
  await page.goto(FILE, { waitUntil: 'load', timeout: 30000 });
  try { await page.waitForLoadState('networkidle', { timeout: 9000 }); } catch {}
  await page.waitForTimeout(2800);
  const cnt = (id) => page.evaluate((i) => { const el = document.getElementById(i); return el ? el.children.length : -1; }, id);
  const probe = {
    conn: await page.evaluate(() => (document.getElementById('connTxt') || {}).textContent),
    vitals: await cnt('vitalsStrip'), attention: await cnt('attention'), roomMini: await cnt('roomMini'),
    rooms: await cnt('rooms'), access: await cnt('access'), lighting: await cnt('lighting'),
    contacts: await cnt('contacts'), system: await cnt('system'), hero: await cnt('powerHero'),
    capacity: await page.evaluate(() => !!document.querySelector('#capacity svg')),
  };
  await page.screenshot({ path: IMG('home-demo-overview.png'), fullPage: true });
  // Rooms tab
  await page.evaluate(() => { const t=[...document.querySelectorAll('[data-tab]')].find(x=>x.dataset.tab==='rooms'); t&&t.click(); });
  await page.waitForTimeout(700);
  await page.screenshot({ path: IMG('home-demo-rooms.png'), fullPage: true });
  // open a room modal
  await page.evaluate(() => { const r=document.querySelector('#rooms [data-room]'); r&&r.click(); });
  await page.waitForTimeout(700);
  probe.roomModalOpen = await page.evaluate(() => document.getElementById('roomBackdrop').classList.contains('on'));
  probe.roomModalRows = await page.evaluate(() => document.querySelectorAll('#roomModal .erow').length);
  await page.screenshot({ path: IMG('home-demo-roommodal.png') });
  console.log('probe', JSON.stringify(probe));
  console.log(errs.length ? 'ERRORS:\n' + errs.join('\n') : 'NO PAGE ERRORS');
  await browser.close();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
