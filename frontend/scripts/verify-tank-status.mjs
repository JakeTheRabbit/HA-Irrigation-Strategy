/** Graphical room telemetry against the isolated compiled demo. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
const html = await readFile(new URL("../../www/dashboard.html", import.meta.url));
const out = new URL("../../output/playwright/", import.meta.url);
const file = (name) => new URL(name, out).pathname.replace(/^\/([A-Za-z]:)/, "$1");
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
const errors = [],
  forbidden = [];
async function open(target) {
  const page = await target.newPage();
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
  return page;
}
/** Opens the tank's History panel and waits for its chart. */
async function openHistory(page) {
  await page
    .locator("[data-tank-status]")
    .getByRole("button", { name: "History", exact: true })
    .click();
  const sheet = page.getByRole("dialog", { name: "Tank EC and pH" });
  await sheet.waitFor();
  await sheet.locator("[data-tank-chart]").waitFor();
  return sheet;
}
/** No text in the open panel set below the 12 px floor, the chart's own labels included. */
async function noSmallText(sheet) {
  const small = await sheet.evaluate((root) =>
    [...root.querySelectorAll("*")]
      .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))
      .map((el) => [el.textContent.trim().slice(0, 30), parseFloat(getComputedStyle(el).fontSize)])
      .filter(([, size]) => size < 12),
  );
  assert.deepEqual(small, [], "text below 12 px in the History panel");
}
const page = await open(context);
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
  // The tank and its first reading sit as far below the heading as the tank sits from the left.
  const inset = await tank.evaluate((panel) => {
    const box = panel.getBoundingClientRect();
    const heading = panel.querySelector(".panel-heading").getBoundingClientRect();
    const drawing = panel.querySelector(".tank-vessel svg").getBoundingClientRect();
    const first = panel.querySelector(".tank-quality > div").getBoundingClientRect();
    return {
      left: Math.round(drawing.left - box.left),
      top: Math.round(drawing.top - heading.bottom),
      readingTop: Math.round(first.top - heading.bottom),
    };
  });
  assert.ok(
    Math.abs(inset.top - inset.left) <= 2,
    `tank inset: top ${inset.top}, left ${inset.left}`,
  );
  assert.ok(
    Math.abs(inset.readingTop - inset.left) <= 2,
    `first reading inset: top ${inset.readingTop}, left ${inset.left}`,
  );
  // A last-day sparkline beside the EC and the pH value, and no full graph on the Overview.
  for (const key of ["ec", "ph"]) {
    const spark = tank.locator(`[data-tank-spark="${key}"]`);
    await spark.waitFor();
    assert.ok(
      (await spark.locator("path").getAttribute("d")).split("L").length > 20,
      `${key} sparkline drawn`,
    );
    assert.match(await spark.getAttribute("aria-label"), /over the last 24 h: [\d.]+ to [\d.]+/);
  }
  assert.equal(await page.locator("[data-tank-chart]").count(), 0, "a full graph on the Overview");
  await tank.screenshot({ path: file("tank-status.png") });
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
  await page.screenshot({ path: file("tank-status-mobile.png"), fullPage: true });

  // History: both readings over time, in a panel beside the Overview.
  await page.setViewportSize({ width: 1440, height: 1000 });
  let sheet = await openHistory(page);
  const chart = sheet.locator("[data-tank-chart]");
  for (const key of ["ec", "ph"])
    assert.ok(
      (await chart.locator(`.tank-line-${key} path.recharts-line-curve`).getAttribute("d")).split(
        "L",
      ).length > 50,
      `${key} history line drawn`,
    );
  assert.match(
    await chart.getAttribute("aria-label"),
    /EC latest 3\.06, lowest \d\.\d\d, highest \d\.\d\d mS\/cm\. pH latest 5\.66, lowest \d\.\d\d, highest \d\.\d\d/,
  );
  assert.equal(await sheet.locator("[data-tank-summary]").count(), 2, "latest, lowest, highest");
  // Flower 2 checks its feed water on these probes: its gate is drawn and named as such.
  assert.ok((await chart.locator(".recharts-reference-line").count()) >= 2, "gate lines drawn");
  assert.match(
    await sheet.locator('[data-tank-gate="ec"]').innerText(),
    /2\.3–3\.5 mS\/cm\. Irrigation is held while this probe reads outside the gate/,
  );
  // A room saved in Rooms & setup gates on the probes mapped there: no word of app options.
  assert.equal(await sheet.locator("[data-tank-gate-option]").count(), 0);
  for (const range of ["7 days", "30 days"]) {
    await sheet.getByRole("button", { name: range, exact: true }).click();
    await sheet.locator("caption", { hasText: `Last ${range}` }).waitFor();
    for (const key of ["ec", "ph"])
      assert.ok(
        (await chart.locator(`.tank-line-${key} path.recharts-line-curve`).getAttribute("d")).split(
          "L",
        ).length > 50,
        `${key} line over ${range}`,
      );
  }
  await noSmallText(sheet);
  const dark = await new AxeBuilder({ page }).analyze();
  assert.deepEqual(
    dark.violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })),
    [],
    "History panel accessibility, dark",
  );
  await page.screenshot({ path: file("tank-history.png") });
  // Closing hands focus back to History. Radix restores it as the panel unmounts: wait for it.
  await page.keyboard.press("Escape");
  await sheet.waitFor({ state: "hidden" });
  await page
    .waitForFunction(() => document.activeElement?.textContent?.trim() === "History", null, {
      timeout: 5_000,
    })
    .catch(() => {
      throw new Error("focus did not return to the History button");
    });

  // The Overview stays two screens at most at 1440×800, zones beside the tank, and History
  // beside Map sensors in the tank's heading.
  await page.setViewportSize({ width: 1440, height: 800 });
  const layout = await page.evaluate(() => {
    const box = (selector) => document.querySelector(selector).getBoundingClientRect();
    const [history, map] = [
      ...document.querySelectorAll("[data-tank-status] .tank-actions button"),
    ];
    return {
      height: document.documentElement.scrollHeight,
      window: innerHeight,
      zonesTop: box(".overview-grid > .panel").top,
      tankTop: box("[data-tank-status]").top,
      historyTop: history.getBoundingClientRect().top,
      mapTop: map.getBoundingClientRect().top,
      titleBottom: box("[data-tank-status] .panel-heading h2").bottom,
    };
  });
  assert.ok(
    layout.height <= 2 * layout.window,
    `Overview is ${layout.height}px tall in a ${layout.window}px window`,
  );
  assert.equal(layout.zonesTop, layout.tankTop, "zones and tank share a row");
  assert.equal(layout.historyTop, layout.mapTop, "History sits beside Map sensors");
  assert.ok(layout.historyTop < layout.titleBottom, "the tank's actions share the title's line");

  // Light theme: the open panel stays readable.
  const lightContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    colorScheme: "light",
  });
  const light = await open(lightContext);
  await light.goto(`${origin}/dashboard.html?demo=1#/overview`);
  sheet = await openHistory(light);
  await noSmallText(sheet);
  const audit = await new AxeBuilder({ page: light }).analyze();
  assert.deepEqual(
    audit.violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })),
    [],
    "History panel accessibility, light",
  );
  // The hover tooltip names both readings in the text colour, not the lighter series hues.
  const plot = await sheet.locator("[data-tank-chart]").boundingBox();
  await light.mouse.move(plot.x + plot.width / 2, plot.y + plot.height / 2);
  const tooltip = light.locator(".recharts-tooltip-wrapper");
  await light.waitForFunction(() =>
    /EC .*mS\/cm[\s\S]*pH/.test(document.querySelector(".recharts-tooltip-wrapper")?.textContent),
  );
  const tip = await new AxeBuilder({ page: light }).include(".recharts-tooltip-wrapper").analyze();
  assert.deepEqual(
    tip.violations.map((v) => v.id),
    [],
    `tooltip contrast: ${await tooltip.innerText()}`,
  );
  await lightContext.close();

  await page.goto(`${origin}/dashboard.html?demo=1&room=room%3Af1_#/overview`);
  await page.waitForFunction(
    () => document.querySelector("[data-tank-level]")?.getAttribute("data-tank-level") === "72",
  );
  assert.equal(await page.locator("[data-pump-state]").getAttribute("data-pump-state"), "off");
  // Flower 1 maps no feed-water probe: no gate is drawn, and the panel says its limits hold nothing.
  await page.setViewportSize({ width: 1440, height: 1000 });
  sheet = await openHistory(page);
  assert.equal(await sheet.locator(".recharts-reference-line").count(), 0, "no gate in Flower 1");
  assert.match(
    await sheet.locator('[data-tank-gate="ec"]').innerText(),
    /Off: no feed-water EC probe is mapped, so 2\.3–3\.5 mS\/cm is not applied\./,
  );
  assert.equal(await sheet.locator("[data-tank-gate-option]").count(), 0, "named room: no option");
  assert.match(
    await sheet.locator("[data-tank-chart]").getAttribute("aria-label"),
    /EC latest 2\.80/,
  );
  assert.deepEqual(errors, []);
  assert.deepEqual(forbidden, []);
  const checks = [
    "graphical mapped tank readings",
    "zone event timestamps",
    "mobile layout and accessibility",
    "EC and pH sparklines, no full graph on the Overview",
    "History panel: both series over 24 h, 7 days and 30 days, with the source-water gate",
    "History panel and tooltip accessibility, light and dark, no text below 12 px",
    "focus returns to History on close",
    "Overview two screens at most, zones beside the tank, History beside Map sensors",
    "room isolation, and no gate where no feed-water probe is mapped",
  ];
  await writeFile(
    new URL("tank-status-verification.json", out),
    JSON.stringify({ checks, errors, forbidden }, null, 2),
  );
  console.log(
    `${checks.length} tank/zone browser checks passed; no console errors or external/API requests.`,
  );
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
