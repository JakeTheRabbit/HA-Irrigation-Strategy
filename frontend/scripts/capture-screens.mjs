/** The 3.18 release screenshots in docs/screens/, from frontend/dist: run after `vite build`, then
 * optimise with scripts/optimise_screens.py. Every page opens in the demo on the 3.18 backend with
 * the clock pinned to 18 October 2026 15:50, once at 1440x900 in the light theme and once at
 * 390x844 in the dark theme, the window then grown to the page's height (up to a cap). Fails on any browser
 * error or off-origin/API request. PORT pins the loopback server's port. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const PAGES = [
  ["status-all-rooms", "/all-zones"],
  ["status-room", "/today"],
  ["zone", "/zone/1"],
  ["irrigation-timeline", "/plan/watering"],
  ["irrigation-current-day", "/plan/targets"],
  ["timer-programs", "/plan/timers"],
  ["grow-plan-presets", "/plan/schedule"],
  ["history-explorer", "/history/explorer"],
  ["water-and-flow", "/history/water"],
  ["history-changes", "/history/changes"],
  ["feed-dosing", "/equipment/dosing"],
  ["pump-calibration", "/equipment/pump-calibration"],
  ["feed-calibration", "/equipment/feed-calibration"],
  ["setup-pumps-valves", "/equipment/setup"],
  ["alert-rules", "/settings/alerts"],
  ["notifications", "/settings/notifications"],
  ["system-status", "/settings/system"],
  ["ai-assistant", "/settings/ai"],
  ["dashboards-display", "/settings"],
];
// Parts of a page shown on their own: [file, route, selector].
const PARTS = [
  ["presets", "/plan/schedule", "aside.plan-side"],
  ["upgrade-report", "/settings/system", "[data-upgrade-report]"],
];
const LOOKS = [
  { look: "desktop-light", width: 1440, height: 900, scale: 1, theme: "light", cap: 2000 },
  { look: "phone-dark", width: 390, height: 844, scale: 2, theme: "dark", cap: 1800 },
];
const PINNED = new Date(2026, 9, 18, 15, 50);
const out = (name) => fileURLToPath(new URL(`../../docs/screens/${name}.png`, import.meta.url));

const html = await readFile(new URL("../dist/index.html", import.meta.url));
const server = createServer((_req, res) => {
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(html);
});
await new Promise((resolve) => server.listen(Number(process.env.PORT) || 0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
await mkdir(fileURLToPath(new URL("../../docs/screens/", import.meta.url)), { recursive: true });

let browser;
for (const extra of [{}, { channel: "chrome" }, { channel: "msedge" }]) {
  try {
    browser = await chromium.launch({ headless: true, ...extra });
    break;
  } catch {
    // The next channel.
  }
}
assert.ok(browser, "a Chromium to launch");
const problems = [];
const written = [];
try {
  for (const { look, width, height, scale, theme, cap } of LOOKS) {
    const context = await browser.newContext({
      viewport: { width, height },
      deviceScaleFactor: scale,
      colorScheme: theme,
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15_000);
    page.on("pageerror", (e) => problems.push(`${look}: ${e.message}`));
    page.on("console", (m) => m.type() === "error" && problems.push(`${look}: ${m.text()}`));
    await page.route("**/*", (r) => {
      const url = new URL(r.request().url());
      if (url.origin !== origin || url.pathname.startsWith("/api/")) {
        problems.push(`${look}: request ${url.href}`);
        return r.abort();
      }
      return r.continue();
    });
    await page.clock.setFixedTime(PINNED);
    const open = async (route) => {
      await page.goto(`${origin}/dashboard.html?demo=1#${route}`);
      await page.locator("main h1").first().waitFor();
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(1000);
      await page.evaluate(() => {
        document.activeElement?.blur();
        window.scrollTo(0, 0);
      });
    };
    for (const [name, route] of PAGES) {
      await open(route);
      // A window as tall as the page (up to the cap), so the menu and the phone's bottom bar sit
      // where they would on a tall screen instead of mid-image.
      const full = await page.evaluate(() => document.documentElement.scrollHeight);
      await page.setViewportSize({ width, height: Math.max(height, Math.min(full, cap)) });
      await page.waitForTimeout(400);
      const file = `${name}-${look}`;
      await page.screenshot({ path: out(file), animations: "disabled" });
      await page.setViewportSize({ width, height });
      written.push({ file: `docs/screens/${file}.png`, route });
    }
    for (const [name, route, selector] of PARTS) {
      await open(route);
      const part = page.locator(selector).first();
      await part.waitFor({ state: "visible" });
      const file = `${name}-${look}`;
      await part.screenshot({ path: out(file), animations: "disabled" });
      written.push({ file: `docs/screens/${file}.png`, route, selector });
    }
    await context.close();
  }
} finally {
  await browser.close();
  server.close();
}
assert.deepEqual(problems, [], "browser errors or blocked requests");
for (const w of written) console.log(`${w.file}  ${w.route}${w.selector ? ` ${w.selector}` : ""}`);
console.log(`Captured ${written.length} screenshots from the 3.18 demo, clock 2026-10-18 15:50.`);
