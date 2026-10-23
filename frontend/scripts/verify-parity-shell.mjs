/** Shell: the top bar and the jump-to palette (Task 30; mockups 03 at 1440 and 24 at 390), against
 * frontend/dist: run after `vite build`. Serves on PORT (default: any free port), so parallel runs
 * never share one.
 *
 * The clock is pinned to today 14:10 local.
 *
 * Interactions asserted, on both backends (`?demo=1` and `?demo=1&backend=3.17`):
 * - 1440: the header reads "Updated N s ago", the AI chip, "Jump to… Ctrl K", the room's name as
 *   plain text, "Watering on" and "Stop all", in that order; no room chip buttons;
 * - 1440: Ctrl K → type "changes" → Enter opens #/history/changes (heading "Changes"), and focus
 *   goes back to where it was;
 * - 1440: the Jump to… button opens the palette, Escape closes it and focus returns to the button;
 * - 1440: "/" opens it, "cal ph" lists "Calibrate <room> feed pH" first, ArrowDown moves the
 *   active option; a word nothing has says "Nothing matches";
 * - 1440: picking another room's zone opens that room's zone page;
 * - 390: the page title over "Updated N s ago · <AI state>", no Jump to… button, both switches in
 *   words, no horizontal overflow.
 * Writes output/playwright/parity/shell-compare.json (screenshot sizes and every region asserted). */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const outDir = new URL("../../output/playwright/parity/", import.meta.url);
const toPath = (url) => url.pathname.replace(/^\/([A-Za-z]:)/, "$1");
const html = await readFile(new URL("../dist/index.html", import.meta.url));
await mkdir(outDir, { recursive: true });
const server = createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "text/html" });
  res.end(html);
});
await new Promise((resolve) => server.listen(Number(process.env.PORT ?? 0), "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;

async function launch() {
  let last;
  for (const extra of [{}, { channel: "chrome" }, { channel: "msedge" }]) {
    try {
      return await chromium.launch({ headless: true, ...extra });
    } catch (e) {
      last = e;
    }
  }
  throw last;
}

const UPDATED = /^Updated \d+ (s|min) ago$/;
const browser = await launch();
const errors = [];
const forbidden = [];
const shots = [];
const regions = new Set();
const region = (name) => regions.add(name);

async function open(width, height, backend, route) {
  const label = `${width}px backend ${backend}`;
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  page.on("pageerror", (e) => errors.push(`${label}: ${e.message}`));
  await page.route("**/*", (r) => {
    const url = new URL(r.request().url());
    if (url.origin !== origin || url.pathname.startsWith("/api/")) {
      forbidden.push(`${label}: ${r.request().method()} ${url.href}`);
      return r.abort();
    }
    return r.continue();
  });
  const pinned = new Date();
  pinned.setHours(14, 10, 0, 0);
  await page.clock.setFixedTime(pinned);
  const query = backend === "3.17" ? "?demo=1&backend=3.17" : "?demo=1";
  await page.goto(`${origin}/dashboard.html${query}#${route}`);
  return { page, context, label };
}

async function finish(page, context, label, width, backend) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  assert.ok(overflow <= 1, `${label}: page overflows horizontally by ${overflow}px`);
  const audit = await new AxeBuilder({ page }).include("header.topbar").analyze();
  assert.deepEqual(
    audit.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
    [],
    `${label}: axe violations in the header`,
  );
  const file = `shell-${width}-${backend}.png`;
  await page.screenshot({ path: toPath(new URL(file, outDir)), animations: "disabled" });
  shots.push({ width, backend, file, w: width * 2, h: (await page.evaluate(() => innerHeight)) * 2 });
  await context.close();
}

try {
  for (const backend of ["3.18", "3.17"]) {
    // Desktop: the room page, as mockup 03.
    {
      const { page, context, label } = await open(1440, 1000, backend, "/today");
      const header = page.locator("header.topbar");
      await header.locator(".data-age").waitFor();
      region("top bar");
      assert.match(await header.locator(".data-age").innerText(), UPDATED, `${label}: data age`);
      const roomName = (await page.getByRole("heading", { level: 1 }).first().innerText()).trim();
      assert.equal(
        (await header.locator(".header-safety-scope").innerText()).trim(),
        roomName,
        `${label}: the room's name beside its switches`,
      );
      const jump = header.getByRole("button", { name: /^Jump to…/ });
      assert.equal((await jump.innerText()).replace(/\s+/g, " ").trim(), "Jump to… Ctrl K");
      // In mockup order: age, AI, Jump to…, room, Watering, Stop all.
      const xs = await Promise.all(
        [
          header.locator(".data-age"),
          header.locator(".brain-chip"),
          jump,
          header.locator(".header-safety-scope"),
          header.getByRole("button", { name: /^Watering on/ }),
          header.getByRole("button", { name: /^Stop all/ }),
        ].map(async (l) => (await l.boundingBox()).x),
      );
      assert.deepEqual([...xs].sort((a, b) => a - b), xs, `${label}: header order ${xs}`);
      region("no room chips");
      assert.equal(await header.locator("[data-room], .room-chip, .room-chips").count(), 0);
      assert.equal(await header.getByRole("group", { name: "Rooms" }).count(), 0);

      // Ctrl K → "changes" → Enter.
      region("palette: Ctrl K to Changes");
      const palette = page.getByRole("dialog", { name: "Jump to" });
      const field = palette.getByRole("combobox");
      await page.locator("main h1").first().click();
      await page.keyboard.press("Control+k");
      await palette.waitFor();
      assert.ok(await field.evaluate((el) => el === document.activeElement), `${label}: field focused`);
      await field.fill("changes");
      assert.equal((await palette.getByRole("option").first().innerText()).split("\n")[0], "Changes");
      await page.keyboard.press("Enter");
      await palette.waitFor({ state: "hidden" });
      await page.waitForFunction(() => location.hash === "#/history/changes");
      await page.getByRole("heading", { level: 1, name: "Changes", exact: true }).waitFor();

      // Jump to… → Escape → focus back on the button.
      region("palette: Escape returns focus");
      await jump.click();
      await palette.waitFor();
      await page.keyboard.press("Escape");
      await palette.waitFor({ state: "hidden" });
      assert.ok(await jump.evaluate((el) => el === document.activeElement), `${label}: focus back on Jump to…`);

      // "/" opens it; "cal ph" leads with the calibration action.
      region("palette: search");
      await page.locator("main h1").first().click();
      await page.keyboard.press("/");
      await palette.waitFor();
      await field.fill("cal ph");
      const first = palette.getByRole("option").first();
      if (backend === "3.18")
        await page.screenshot({ path: toPath(new URL("shell-palette-1440.png", outDir)), animations: "disabled" });
      assert.equal((await first.innerText()).split("\n")[0], `Calibrate ${roomName} feed pH`);
      assert.equal(await first.getAttribute("aria-selected"), "true");
      await page.keyboard.press("ArrowDown");
      assert.equal(await palette.getByRole("option").nth(1).getAttribute("aria-selected"), "true");
      await field.fill("qqqq");
      await palette.getByText("Nothing matches “qqqq”.").waitFor();
      await page.keyboard.press("Escape");
      await palette.waitFor({ state: "hidden" });

      // Another room's zone opens in that room.
      region("palette: another room's zone");
      await jump.click();
      await field.fill("room b zone 2");
      await page.keyboard.press("Enter");
      await page.waitForFunction(() => location.hash === "#/zone/2");
      await page.waitForFunction(() => new URLSearchParams(location.search).get("room") !== null);
      assert.equal((await header.locator(".header-safety-scope").innerText()).trim(), "Room B");
      await page.goto(`${origin}/dashboard.html${backend === "3.17" ? "?demo=1&backend=3.17" : "?demo=1"}#/today`);
      await header.locator(".data-age").waitFor();
      await finish(page, context, label, 1440, backend);
    }
    // Phone: All rooms, as mockup 24.
    {
      const { page, context, label } = await open(390, 844, backend, "/all-zones");
      const header = page.locator("header.topbar");
      await header.locator(".data-age").waitFor();
      region("phone top bar");
      assert.equal((await header.locator(".topbar-title").innerText()).trim(), "All rooms");
      const facts = (await header.locator(".topbar-facts").innerText()).replace(/\s+/g, " ").trim();
      assert.match(facts, /^Updated \d+ (s|min) ago · AI \S/, `${label}: ${facts}`);
      assert.equal(await header.getByRole("button", { name: /^Jump to…/ }).isVisible(), false);
      assert.deepEqual(await header.locator(".safety-switch-text").allInnerTexts(), ["Watering on", "Stop all"]);
      await finish(page, context, label, 390, backend);
    }
  }
} finally {
  await browser.close();
  server.close();
}
await writeFile(
  new URL("shell-compare.json", outDir),
  JSON.stringify(
    { id: "shell", mockup: "03-S2-Room.png", phoneMockup: "24-P1-AllRooms.png", shots, regions: [...regions] },
    null,
    2,
  ) + "\n",
);
assert.deepEqual(errors, [], "page errors");
assert.deepEqual(forbidden, [], "off-origin or /api/ requests");
console.log(`verify-parity-shell: ${shots.length} views, ${regions.size} regions passed.`);
