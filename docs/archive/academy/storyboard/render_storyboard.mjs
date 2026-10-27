// Render and verify the local storyboard. No network or Home Assistant calls.
import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
import { existsSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { homedir } from 'node:os';

const root = dirname(fileURLToPath(import.meta.url));
const preview = join(root, 'review');
mkdirSync(preview, { recursive: true });
let executablePath = process.env.STORYBOARD_CHROMIUM;
if (!executablePath && !existsSync(chromium.executablePath())) {
  const cache = join(process.env.LOCALAPPDATA || join(homedir(), 'AppData/Local'), 'ms-playwright');
  if (existsSync(cache)) {
    executablePath = readdirSync(cache)
      .filter(name => /^chromium-\d+$/.test(name))
      .sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]))
      .map(name => join(cache, name, 'chrome-win64/chrome.exe'))
      .find(existsSync);
  }
}
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(join(root, 'index.html')).href);
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map(img => img.decode()));
  });
  const images = await page.locator('.scene img').evaluateAll(items => items.map(img => ({
    src: img.getAttribute('src'), loaded: img.complete && img.naturalWidth > 0,
  })));
  if (images.length !== 27 || images.some(img => !img.loaded)) throw new Error('Missing scene image');
  if (errors.length) throw new Error(errors.join('\n'));
  await page.pdf({ path: join(root, 'storyboard.pdf'), printBackground: true, preferCSSPageSize: true,
    displayHeaderFooter: true, headerTemplate: '<span></span>',
    footerTemplate: '<div style="width:100%;font:8px Arial;color:#68766e;padding:0 12mm;display:flex;justify-content:space-between"><span>Crop Steering from Zero · illustrated pilot storyboard · review copy</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>' });
  await page.getByRole('button', { name: 'Toggle contact sheet' }).click();
  if (await page.getByRole('button', { name: 'Toggle contact sheet' }).getAttribute('aria-pressed') !== 'true') {
    throw new Error('Contact-sheet toggle failed');
  }
  for (const id of ['A1', 'A2', 'A3', 'B1', 'C1']) {
    await page.locator('#' + id).screenshot({ path: join(preview, id + '-contact-sheet.png') });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  if (mobileOverflow) throw new Error('Mobile horizontal overflow');
  await page.getByRole('button', { name: 'Toggle contact sheet' }).click();
  await page.locator('#A2-03').screenshot({ path: join(preview, 'mobile-scene.png') });
  const report = { sceneCount: images.length, imagesLoaded: images.every(i => i.loaded), errors,
    contactToggle: 'passed', mobileOverflow, browserVersion: await browser.version() };
  writeFileSync(join(preview, 'validation.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
}
