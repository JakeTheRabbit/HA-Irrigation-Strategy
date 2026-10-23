/** Graphical room telemetry against the isolated compiled demo. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { readmeImage } from "./readme-images.mjs";
const html = await readFile(new URL("../../www/dashboard.html", import.meta.url));
const out = new URL("../../output/playwright/", import.meta.url);
const file = (name) => new URL(name, out).pathname.replace(/^\/([A-Za-z]:)/, "$1");
// The README's screenshots.
const img = readmeImage;
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
  // The demo keeps the clock: overnight its pump rests. Read it at 4 PM, mid-maintenance.
  await page.clock.setFixedTime(new Date(2026, 8, 28, 16, 0, 0));
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
async function noSmallText(sheet, name = "the History panel") {
  const small = await sheet.evaluate((root) =>
    [...root.querySelectorAll("*")]
      .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))
      .map((el) => [el.textContent.trim().slice(0, 30), parseFloat(getComputedStyle(el).fontSize)])
      .filter(([, size]) => size < 12),
  );
  assert.deepEqual(small, [], `text below 12 px in ${name}`);
}
/** The tank level chart under the card, once its history is drawn. */
async function levelChart(page) {
  const level = page.locator("[data-tank-level-chart]");
  await level.locator(".tank-level-svg").waitFor();
  return level;
}
/** Hovers the newest mark on the level line, scrolled into view, and returns the tooltip's text. */
async function hoverShot(page, level) {
  const mark = level.locator('[data-layer="shots"] circle').last();
  await mark.scrollIntoViewIfNeeded();
  const dot = await mark.boundingBox();
  await page.mouse.move(dot.x + dot.width / 2, dot.y + dot.height / 2);
  await level.locator(".grow-tip").waitFor();
  return level.locator(".grow-tip").innerText();
}
const page = await open(context);
try {
  // Each zone's last shot on Today is a machine-readable time.
  await page.goto(`${origin}/dashboard.html?demo=1#/today`);
  await page.locator('[data-last-irrigation="1"]').waitFor();
  assert.ok(await page.locator('[data-last-irrigation="1"]:visible').getAttribute("datetime"));
  // The tank: Equipment › Tank & feed. The old Tank & pump address still opens it.
  await page.goto(`${origin}/dashboard.html?demo=1#/equipment/tank`);
  await page.waitForFunction(() => location.hash === "#/equipment/feed");
  const tank = page.locator("[data-tank-status]");
  await tank.waitFor();
  assert.equal(
    await page
      .getByRole("navigation", { name: "Equipment views" })
      .locator('[aria-current="page"]')
      .innerText(),
    "Tank and feed",
  );
  // The demo tank was filled to 100 % two hours ago and is being drawn down since.
  const cardLevel = Number(await tank.locator("[data-tank-level]").getAttribute("data-tank-level"));
  assert.ok(cardLevel > 25 && cardLevel < 100, `tank card level ${cardLevel}`);
  assert.equal(await tank.locator("[data-pump-state]").getAttribute("data-pump-state"), "on");
  assert.match(await tank.innerText(), /3.06 mS\/cm/);
  assert.match(await tank.innerText(), /5.66 pH/);
  assert.match(await tank.innerText(), /17.6 °C/);
  assert.ok(await tank.locator("time").getAttribute("datetime"));
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
  // A last-day sparkline beside the EC and the pH value; the full graph opens on request.
  for (const key of ["ec", "ph"]) {
    const spark = tank.locator(`[data-tank-spark="${key}"]`);
    await spark.waitFor();
    assert.ok(
      (await spark.locator("path").getAttribute("d")).split("L").length > 20,
      `${key} sparkline drawn`,
    );
    assert.match(await spark.getAttribute("aria-label"), /over the last 24 h: [\d.]+ to [\d.]+/);
  }
  assert.equal(await page.locator("[data-tank-chart]").count(), 0, "a full graph before History");
  await tank.screenshot({ path: file("tank-status.png") });
  await tank.screenshot({ path: img("tank-status.png") });

  // The reservoir minimum, in words, between the card and the level chart: watering allowed, its
  // marks, the litres left above the minimum, and the batch on the tank with a way to Dosing.
  const guard = page.locator("[data-reservoir-guard]");
  assert.equal(await guard.getAttribute("data-reservoir-guard"), "ok");
  const guardText = await guard.innerText();
  assert.match(guardText, /Watering allowed/);
  assert.match(guardText, /8 % · starts again at 12 %/);
  assert.match(guardText, /About [\d.,]+ L/);
  assert.match(guardText, /2\.4 L/);
  assert.match(guardText, /Last batch: |Batch running: |No batch made yet/);
  assert.doesNotMatch(guardText, /crop_steering|below_minimum|litres_per_pct|vwc/i);
  const order = await page.evaluate(() =>
    ["[data-tank-status]", "[data-reservoir-guard]", "[data-tank-level-chart]"].map(
      (selector) => document.querySelector(selector).getBoundingClientRect().top,
    ),
  );
  assert.ok(order[0] < order[1] && order[1] < order[2], "card, minimum, then the level chart");
  await guard.screenshot({ path: file("reservoir-guard.png") });

  // Under the card, the tank's level over time with what moved it: the demo's recorded history.
  const level = await levelChart(page);
  const summary = () => level.locator(".tank-level-svg").getAttribute("aria-label");
  // The chart ends where the card reads, after a fill to 100 % from a tank run low.
  const day = (await summary()).match(
    /^Tank level over the last 24 h: latest ([\d.]+)%, lowest ([\d.]+)%, highest 100%\. \d+ shots, pump on \d[^,]*, \d+ recorded fills?\.$/,
  );
  assert.ok(day, `level summary: ${await summary()}`);
  assert.equal(Number(day[1]), cardLevel, "the chart ends where the card reads");
  assert.ok(Number(day[2]) <= 25, `the tank ran down to ${day[2]} % before its fill`);
  assert.ok(
    (await level.locator('[data-layer="level"]').getAttribute("d")).split("H").length > 10,
    "level line drawn",
  );
  assert.ok((await level.locator('[data-layer="shots"] circle').count()) > 5, "shots on the line");
  assert.ok((await level.locator('[data-run="pump"]').count()) > 10, "pump runs drawn");
  assert.ok(
    (await level.locator('[data-run="filling"]').count()) >= 1,
    "the filling before a fill",
  );
  // The controller's minimum across the level, in the key; this room sets no refill reminder.
  assert.equal(await level.locator('[data-level-line="minimum"]').getAttribute("data-value"), "8");
  assert.equal(await level.locator('[data-level-line="remind"]').count(), 0, "no reminder here");
  assert.match(await level.locator(".grow-legend").innerText(), /Minimum 8 %/);
  // The newest recorded fill is the demo's last fill, two hours ago.
  assert.equal(
    await level.locator("[data-fill]").last().getAttribute("data-fill"),
    new Date(2026, 8, 28, 14, 0, 0).toISOString(),
  );
  // A shot says which zone, how long, and how much at the configured flow.
  assert.match(
    await hoverShot(page, level),
    /· Zone \d\nP[12] shot \d+ min( \d+ s)?, ≈[\d.]+ L at the configured flow/,
  );
  const tipAudit = await new AxeBuilder({ page }).include("[data-tank-level-chart]").analyze();
  assert.deepEqual(
    tipAudit.violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })),
    [],
    "tank level chart and tooltip accessibility, dark",
  );
  await page.mouse.move(0, 0);
  await level.locator(".grow-tip").waitFor({ state: "hidden" });
  // Half a day: the newest fill, two hours ago, and the shots since it.
  await level.getByRole("button", { name: "12 h", exact: true }).click();
  await page.waitForFunction(() =>
    document
      .querySelector("[data-tank-level-chart] .tank-level-svg")
      ?.getAttribute("aria-label")
      ?.startsWith("Tank level over the last 12 h:"),
  );
  assert.ok((await level.locator("[data-fill]").count()) >= 1, "a fill in the last 12 h");
  assert.ok((await level.locator('[data-layer="shots"] circle').count()) > 0, "shots in 12 h");
  assert.equal(await level.locator('[data-level-line="minimum"]').count(), 1);
  // Every range: one or two refills a day, each to 100 %, as a real batch tank is filled.
  for (const [range, days] of [
    ["3 days", 3],
    ["7 days", 7],
  ]) {
    await level.getByRole("button", { name: range, exact: true }).click();
    await page.waitForFunction(
      (label) =>
        document
          .querySelector("[data-tank-level-chart] .tank-level-svg")
          ?.getAttribute("aria-label")
          ?.startsWith(label),
      `Tank level over the last ${range}:`,
    );
    const fills = await level.locator("[data-fill]").count();
    assert.ok(fills >= days && fills <= 2 * days, `${fills} recorded fills over ${range}`);
    assert.match(await summary(), /, highest 100%\./);
  }
  assert.match(
    await level.locator(".timeline-events summary").innerText(),
    /^\d+ shots · pump on /,
  );
  await noSmallText(level, "the tank level chart");
  // The Tank & feed tab, card and chart: the README's screenshot.
  await level.screenshot({ path: file("tank-level.png") });
  await page.screenshot({ path: img("tank-level.png") });
  await level.getByRole("button", { name: "24 h", exact: true }).click();
  await page.waitForFunction(() =>
    document
      .querySelector("[data-tank-level-chart] .tank-level-svg")
      ?.getAttribute("aria-label")
      ?.startsWith("Tank level over the last 24 h:"),
  );
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.ok(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      `no horizontal overflow at ${width}`,
    );
    for (const panel of [
      "[data-tank-status]",
      "[data-reservoir-guard]",
      "[data-tank-level-chart]",
    ]) {
      const audit = await new AxeBuilder({ page }).include(panel).analyze();
      assert.deepEqual(
        audit.violations.map((v) => ({ id: v.id, impact: v.impact })),
        [],
        `${panel} accessibility at ${width}`,
      );
    }
  }
  // At phone width the level chart keeps its shots, its minimum and its tooltip.
  assert.match(await hoverShot(page, await levelChart(page)), /· Zone \d\n/);
  assert.equal(await page.locator('[data-level-line="minimum"]').count(), 1);
  await page.mouse.move(0, 0);
  await page.screenshot({ path: file("tank-status-mobile.png"), fullPage: true });

  // History: both readings over time, in a panel beside the page.
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
  await sheet.screenshot({ path: img("tank-history.png") });
  // Room A checks its feed water on these probes: its gate is drawn and named as such.
  assert.ok((await chart.locator(".recharts-reference-line").count()) >= 2, "gate lines drawn");
  assert.match(
    await sheet.locator('[data-tank-gate="ec"]').innerText(),
    /2\.3–3\.5 mS\/cm\. Irrigation is held while this probe reads outside the gate/,
  );
  // A room saved in Rooms and setup gates on the probes mapped there: no word of app options.
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

  // The tank card is one screen at 1440×800 (a 1440×900 laptop's browser window), with History
  // beside Map sensors in its heading; the level chart follows it.
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.waitForFunction(() => innerHeight === 800 && innerWidth === 1440);
  const layout = await page.evaluate(() => {
    const box = (selector) => document.querySelector(selector).getBoundingClientRect();
    const [history, map] = [
      ...document.querySelectorAll("[data-tank-status] .tank-actions button"),
    ];
    return {
      bottom: box("[data-tank-status]").bottom + scrollY,
      window: innerHeight,
      historyTop: history.getBoundingClientRect().top,
      mapTop: map.getBoundingClientRect().top,
      titleBottom: box("[data-tank-status] .panel-heading h2").bottom,
    };
  });
  assert.ok(
    layout.bottom <= layout.window,
    `the tank card ends ${layout.bottom}px down a ${layout.window}px window`,
  );
  assert.equal(layout.historyTop, layout.mapTop, "History sits beside Map sensors");
  assert.ok(layout.historyTop < layout.titleBottom, "the tank's actions share the title's line");

  // Light theme: the open panel stays readable.
  const lightContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    colorScheme: "light",
  });
  const light = await open(lightContext);
  await light.goto(`${origin}/dashboard.html?demo=1#/equipment/feed`);
  // The level chart and a shot's tooltip, in the light theme.
  const lightLevel = await levelChart(light);
  await noSmallText(lightLevel, "the tank level chart");
  await hoverShot(light, lightLevel);
  const levelAudit = await new AxeBuilder({ page: light })
    .include("[data-tank-level-chart]")
    .analyze();
  assert.deepEqual(
    levelAudit.violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })),
    [],
    "tank level chart and tooltip accessibility, light",
  );
  await light.mouse.move(0, 0);
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

  await page.goto(`${origin}/dashboard.html?demo=1&room=room%3Aroom_b_#/equipment/feed`);
  await page.waitForFunction(
    () => document.querySelector("[data-pump-state]")?.getAttribute("data-pump-state") === "off",
  );
  // Room B maps no tank level for the minimum: it says it is off and how to arm it.
  assert.equal(
    await page.locator("[data-reservoir-guard]").getAttribute("data-reservoir-guard"),
    "unmapped",
  );
  assert.match(
    await page.locator("[data-reservoir-guard]").innerText(),
    /Map the tank level[\s\S]*Off: no tank level mapped/,
  );
  // Room B's card and level chart are its own tank's: another level, where its chart ends.
  const roomBLevel = Number(await page.locator("[data-tank-level]").getAttribute("data-tank-level"));
  assert.notEqual(roomBLevel, cardLevel, "Room B reads its own tank");
  const roomBDay = (
    await (await levelChart(page)).locator(".tank-level-svg").getAttribute("aria-label")
  ).match(
    /^Tank level over the last 24 h: latest ([\d.]+)%, .*, highest 100%\..* recorded fills?\.$/,
  );
  assert.equal(Number(roomBDay?.[1]), roomBLevel, "Room B's chart ends where its card reads");
  // Room B: no minimum, its level not read by the controller; the refill reminder at 20 %.
  assert.equal(await page.locator('[data-level-line="minimum"]').count(), 0, "no minimum in Room B");
  assert.equal(await page.locator('[data-level-line="remind"]').getAttribute("data-value"), "20");
  // Room B maps no feed-water probe: no gate is drawn, and the panel says its limits hold nothing.
  await page.setViewportSize({ width: 1440, height: 1000 });
  sheet = await openHistory(page);
  assert.equal(await sheet.locator(".recharts-reference-line").count(), 0, "no gate in Room B");
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
    "EC and pH sparklines, the full graph on request",
    "History panel: both series over 24 h, 7 days and 30 days, with the source-water gate",
    "History panel and tooltip accessibility, light and dark, no text below 12 px",
    "focus returns to History on close",
    "the tank card one screen, History beside Map sensors, the level chart after it",
    "level chart: level, shots, pump runs, filling and recorded fills over 24 h, 3 days and 7 days",
    "level chart tooltip names the zone, length and litres; accessible light, dark and at 390 px",
    "room isolation, and no gate where no feed-water probe is mapped",
    "Tank & feed: the old tank address redirects, the reservoir minimum and the batch in words",
    "the reservoir minimum is off, and says how to arm it, where no tank level is mapped",
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
