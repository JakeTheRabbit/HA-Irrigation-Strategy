/** Graphical room telemetry against the isolated compiled demo. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
const html = await readFile(new URL("../../www/dashboard.html", import.meta.url));
const out = new URL("../../output/playwright/", import.meta.url);
await mkdir(out, { recursive: true });
const server = createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "text/html" });
  res.end(html);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({
  headless: true,
  ...(process.platform === "win32" ? { channel: "chrome" } : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1080 },
  colorScheme: "dark",
});
const page = await context.newPage();
const errors = [],
  forbidden = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.route("**/*", (route) => {
  if (
    !route.request().url().startsWith(origin) ||
    new URL(route.request().url()).pathname.startsWith("/api/")
  ) {
    forbidden.push(route.request().url());
    return route.abort();
  }
  return route.continue();
});
try {
  await page.goto(`${origin}/dashboard.html?demo=1#/overview`);
  const tank = page.locator("[data-tank-status]");
  await tank.waitFor();
  assert.equal(await tank.locator("[data-tank-level]").getAttribute("data-tank-level"), "42");
  assert.equal(await tank.locator("[data-pump-state]").getAttribute("data-pump-state"), "on");
  assert.match(await tank.innerText(), /3.06 mS\/cm/);
  assert.match(await tank.innerText(), /5.66 pH/);
  assert.match(await tank.innerText(), /17.6 °C/);
  assert.ok(await tank.locator("time").getAttribute("datetime"));
  assert.ok(await page.locator('[data-last-irrigation="1"]:visible').getAttribute("datetime"));
  await tank.screenshot({
    path: new URL("tank-status.png", out).pathname.replace(/^\/([A-Za-z]:)/, "$1"),
  });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.ok(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      `no horizontal overflow at ${width}`,
    );
    const audit = await new AxeBuilder({ page }).include("[data-tank-status]").analyze();
    assert.deepEqual(
      audit.violations.map((v) => ({ id: v.id, impact: v.impact })),
      [],
    );
  }
  await page.screenshot({
    path: new URL("tank-status-mobile.png", out).pathname.replace(/^\/([A-Za-z]:)/, "$1"),
    fullPage: true,
  });
  await page.goto(`${origin}/dashboard.html?demo=1&room=room%3Af1_#/overview`);
  await page.waitForFunction(
    () => document.querySelector("[data-tank-level]")?.getAttribute("data-tank-level") === "72",
  );
  assert.equal(await page.locator("[data-pump-state]").getAttribute("data-pump-state"), "off");
  assert.deepEqual(errors, []);
  assert.deepEqual(forbidden, []);
  await writeFile(
    new URL("tank-status-verification.json", out),
    JSON.stringify(
      {
        checks: [
          "graphical mapped tank readings",
          "zone event timestamps",
          "mobile layout and accessibility",
          "room isolation",
        ],
        errors,
        forbidden,
      },
      null,
      2,
    ),
  );
  console.log("4 tank/zone browser checks passed; no console errors or external/API requests.");
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
