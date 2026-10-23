/** Publication images from the checked-out compiled demo only. Build, then run this file.
 * No live URL override or Home Assistant credential is accepted. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
const source = new URL("../../www/dashboard.html", import.meta.url);
const html = await readFile(source);
const server = createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(html);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({
  headless: true,
  ...(process.platform === "win32" ? { channel: "chrome" } : {}),
});
const forbidden = [],
  errors = [],
  captures = [];
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  deviceScaleFactor: 1,
  colorScheme: "light",
  reducedMotion: "reduce",
});
await context.route("**/*", (route) => {
  const u = new URL(route.request().url());
  if (u.origin !== origin || u.pathname.startsWith("/api/")) {
    forbidden.push(u.origin + u.pathname);
    return route.abort();
  }
  return route.continue();
});
const page = await context.newPage();
page.setDefaultTimeout(15000);
page.on("pageerror", (e) => errors.push(e.message));
await page.clock.setFixedTime(new Date(2026, 9, 18, 15, 50));
async function go(route) {
  await page.goto(`${origin}/dashboard.html?demo=1#/${route}`, { waitUntil: "networkidle" });
  await page.locator("main").waitFor();
  await page.evaluate(() => document.fonts.ready);
}
async function shot(name, selector) {
  await page.evaluate(() => {
    document.activeElement?.blur();
    window.scrollTo(0, 0);
  });
  const target = selector ? page.locator(selector).first() : page;
  if (selector) await target.waitFor({ state: "visible" });
  await target.screenshot({
    path: fileURLToPath(new URL(`../../img/${name}.png`, import.meta.url)),
    ...(selector ? {} : { fullPage: name === "all-zones" }),
  });
  captures.push({
    file: `img/${name}.png`,
    route: new URL(page.url()).hash,
    viewport: page.viewportSize(),
    selector: selector ?? (name === "all-zones" ? "full page" : "viewport"),
  });
}
try {
  await go("all-zones");
  await shot("all-zones");
  // A phone: the sections in the bottom bar, every zone card one tap from its page.
  const desktop = page.viewportSize();
  await page.setViewportSize({ width: 390, height: 844 });
  await go("all-zones");
  await shot("mobile-all-rooms");
  await page.setViewportSize(desktop);
  await go("today");
  await shot("operator-dashboard");
  await shot("jev-today");
  await page.setViewportSize({ width: 390, height: 844 });
  await shot("mobile-overview");
  await shot("jev-today-phone");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await go("zone/1");
  // ZoneDay lays out through the zone page grid (display: contents): its charts are the last child.
  await shot("jev-zone-day", "[data-day-timeline] > :last-child");
  await shot("jev-zone-panel", "[data-zone-why]");
  await go("plan/targets");
  await shot("irrigation-workspace");
  await shot("manual-setpoints");
  await shot("plan-graph", ".planning-curve");
  await shot("jev-plan-targets", ".targets-panel");
  await go("plan/schedule");
  await shot("grow-plan");
  await page.locator("details.irrigation-stage-guide > summary").click();
  await shot("jev-stages", ".grow-stages:visible");
  const advanced = page.locator("details.plan-advanced");
  if ((await advanced.getAttribute("open")) === null)
    await advanced.locator(":scope > summary").click();
  await page.getByRole("tab", { name: "Recipes", exact: true }).click();
  const library = page.locator(".recipe-library");
  if ((await library.getAttribute("open")) === null)
    await library.locator("summary").first().click();
  await shot("recipe-library", ".recipe-library");
  // History › Explorer: a zone's probes below the room charts, the AI assistant's decisions under
  // them; who changed which setting is History › Changes.
  await go("history/explorer?zone=1");
  await shot("sensor-history", ".history-explorer");
  await shot("jev-history", ".explorer-ai");
  await go("history/changes");
  await shot("jev-history-setpoints", "[data-changes-backend]");
  await go("history/water");
  await shot("water-use");
  await go("history/compare");
  await shot("run-comparison");
  await go("equipment/probes");
  await shot("jev-equipment", ".probes-status");
  await go("equipment/stock");
  await shot("stock-tanks");
  await go("equipment/setup");
  await shot("rooms-setup");
  await go("equipment/feed");
  await shot("tank-status", "[data-tank-status]");
  await page.locator("[data-tank-level-chart] .tank-level-svg").waitFor();
  await shot("tank-level", "[data-tank-level-chart]");
  await page
    .locator("[data-tank-status]")
    .getByRole("button", { name: "History", exact: true })
    .click();
  await page.getByRole("dialog", { name: "Tank EC and pH" }).waitFor();
  await shot("tank-history", '[role="dialog"]');
  await go("equipment/setup");
  await page.getByRole("button", { name: "Switch room off…", exact: true }).click();
  await page.getByRole("button", { name: /^Apply 1 change/ }).click();
  await page.getByRole("button", { name: "Switch room on…", exact: true }).waitFor();
  await page.evaluate(() => {
    location.hash = "#/today";
  });
  await page.locator(".room-off-banner").waitFor();
  await shot("room-off");
  assert.deepEqual(
    forbidden,
    [],
    "publication capture must not request external or HA API resources",
  );
  assert.deepEqual(errors, [], "no browser runtime errors");
  await writeFile(
    new URL("../../img/screenshots.json", import.meta.url),
    JSON.stringify(
      {
        source: "www/dashboard.html?demo=1",
        sourceSha256: createHash("sha256").update(html).digest("hex"),
        fixedLocalTime: "2026-10-18T15:50:00",
        captures,
      },
      null,
      2,
    ) + "\n",
  );
  console.log(
    `Captured ${captures.length} publication images from the isolated compiled demo; no external/API requests or runtime errors.`,
  );
} finally {
  await browser.close();
  server.close();
}
