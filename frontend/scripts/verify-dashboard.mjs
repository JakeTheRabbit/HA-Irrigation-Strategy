/** Browser contracts against the compiled artifact. API traffic is fixture-only. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const root = fileURLToPath(new URL("../../", import.meta.url));
const publicRoot = path.join(root, "www");
const out = path.join(root, "output/playwright");
// The README's screenshots, from the same demo the checks drive.
const img = (name) => path.join(root, "img", name);
await mkdir(out, { recursive: true });
const server = createServer(async (req, res) => {
  try {
    const requested = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
    const file = path.resolve(publicRoot, "." + (requested === "/" ? "/index.html" : requested));
    if (!file.startsWith(publicRoot + path.sep)) {
      res.writeHead(403);
      return res.end();
    }
    const type =
      {
        ".html": "text/html",
        ".js": "text/javascript",
        ".css": "text/css",
        ".png": "image/png",
      }[path.extname(file)] || "application/octet-stream";
    res.writeHead(200, { "Content-Type": type, "Cache-Control": "no-store" });
    res.end(await readFile(file));
  } catch {
    res.writeHead(404);
    res.end("Not found");
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHANNEL || process.platform === "win32"
    ? { channel: process.env.PLAYWRIGHT_CHANNEL || "chrome" }
    : {}),
});
const checks = [];
const pageErrors = [];
const forbidden = [];
const accessibility = [];
const tabLayouts = [];
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
  reducedMotion: "reduce",
});
await context.route("**/*", (route) => {
  const url = new URL(route.request().url());
  if (url.origin !== base || url.pathname.startsWith("/api/")) {
    forbidden.push(url.origin + url.pathname);
    return route.abort();
  }
  return route.continue();
});
const page = await context.newPage();
page.on("pageerror", (error) => pageErrors.push(error.message));
// The demo keeps the clock (P3 and nothing firing from lights-off to lights-on): every check reads
// it at 4 PM on the demo's day, with the ramp done, maintenance running and the night to come.
const DEMO_DAY = new Date(2026, 8, 28, 16, 0, 0);
await page.clock.setFixedTime(DEMO_DAY);
const expectVisible = async (locator) => {
  await locator.waitFor({ state: "visible", timeout: 10_000 });
};
async function check(name, run) {
  await run();
  checks.push(name);
  console.log(`PASS ${name}`);
}
async function go(route, room = "f2") {
  await page.goto(`${base}/dashboard.html?demo&room=${room}#/${route}`, {
    waitUntil: "networkidle",
  });
}
async function noOverflow() {
  // A new window size reaches the layout a frame or two after it is set.
  await page
    .waitForFunction(() => document.documentElement.scrollWidth <= innerWidth + 1, null, {
      timeout: 2_000,
    })
    .catch(() => {});
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
    true,
    "Page has horizontal overflow",
  );
}
/** A menu entry's views sit in one row of tabs, none over another. */
async function tabsShareRow(section) {
  const tabs = await page
    .getByRole("navigation", { name: `${section} views` })
    .getByRole("button")
    .evaluateAll((buttons) =>
      buttons.map((button) => {
        const box = button.getBoundingClientRect();
        return { x: box.x, y: box.y, width: box.width, height: box.height };
      }),
    );
  assert.ok(tabs.length >= 2, `${section} has its views as tabs`);
  for (const [index, tab] of tabs.entries()) {
    if (!index) continue;
    const before = tabs[index - 1];
    assert.ok(Math.abs(tab.y - before.y) <= 2, `${section}: the views share one row`);
    assert.ok(
      tab.x >= before.x + before.width - 1,
      `${section}: a view sits beside the one before`,
    );
  }
  tabLayouts.push({ route: new URL(page.url()).hash, viewport: page.viewportSize(), tabs });
}
/** Runs `open`, then axe, in the light theme and again in the dark one, each chosen as a person
 * would (the saved preference, applied on load), and leaves the page light. */
async function inBothThemes(label, open) {
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => localStorage.setItem("irrigation-theme", value), theme);
    await page.reload({ waitUntil: "networkidle" });
    await open();
    assert.equal(
      await page.evaluate(() => document.documentElement.classList.contains("dark")),
      theme === "dark",
    );
    // Colours transition (even at reduced motion); measure after two frames, not mid-change.
    await page.evaluate(
      () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))),
    );
    await axe(theme === "dark" ? `${label}, dark` : label);
  }
  await page.evaluate(() => localStorage.setItem("irrigation-theme", "light"));
  await page.reload({ waitUntil: "networkidle" });
}
/** The words and the colour (tone, or phase) of every pill `scope` matches. */
async function pillTones(scope) {
  return page
    .locator(scope)
    .evaluateAll((pills) =>
      pills.map((pill) => [pill.textContent.trim(), pill.dataset.tone ?? pill.dataset.phase]),
    );
}
async function axe(label, include) {
  let builder = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]);
  if (include) builder = builder.include(include);
  const result = await builder.analyze();
  accessibility.push({
    page: label,
    violations: result.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      description: v.description,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        summary: n.failureSummary,
      })),
    })),
  });
  assert.equal(
    result.violations.length,
    0,
    `${label} accessibility: ${result.violations.map((v) => v.id).join(", ")}`,
  );
}
/** axe on one part of the page in the dark theme, without the rest of it being judged. */
async function axeDark(label, include) {
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.evaluate(
    () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))),
  );
  await axe(`${label}, dark`, include);
  await page.evaluate(() => document.documentElement.classList.remove("dark"));
}
try {
  await check("primary entry preserves room, demo and route", async () => {
    // An old bookmark: the Zones page is now Today.
    await page.goto(`${base}/index.html?demo&room=f1#/zones`);
    await expectVisible(page.getByRole("heading", { name: "Flower 1 today", exact: true }));
    assert.match(page.url(), /dashboard\.html\?demo=&room=f1#\/today$/);
    assert.equal(await page.locator("#desktop-room").inputValue(), "room:f1_");
  });
  await check("every old address lands where its content lives now", async () => {
    const moved = [
      ["overview", "today", "Flower 2 today"],
      ["zones", "today", "Flower 2 today"],
      ["strategy", "plan/targets", "Targets"],
      ["grow-plan", "plan/schedule", "Schedule"],
      ["compare", "history/compare", "Compare runs"],
      ["insights", "equipment/probes", "Probes"],
      ["activity", "history/timeline", "Timeline"],
      ["sensors", "equipment/probes", "Probes"],
      ["stock", "equipment/stock", "Stock tanks"],
      ["setup", "equipment/setup", "Rooms & setup"],
      ["plan", "plan/targets", "Targets"],
      ["history", "history/timeline", "Timeline"],
      ["equipment", "equipment/probes", "Probes"],
    ];
    for (const [old, now, heading] of moved) {
      await go(old);
      await expectVisible(page.getByRole("heading", { name: heading, exact: true }));
      assert.equal(new URL(page.url()).hash, `#/${now}`, `#/${old} lands on #/${now}`);
    }
    // A Help link keeps its code; a retired single-page dashboard's ?view= opens its new home.
    await go("help?code=CS-605");
    await expectVisible(page.locator("details#cs-605[open]"));
    await page.goto(`${base}/dashboard.html?demo&room=f2&view=logs`, { waitUntil: "networkidle" });
    await expectVisible(page.getByRole("heading", { name: "Timeline", exact: true }));
    // Rewritten in place: Back returns to the page before, not to the old address.
    await go("today");
    const before = await page.evaluate(() => history.length);
    await page.evaluate(() => (location.hash = "#/sensors"));
    await expectVisible(page.getByRole("heading", { name: "Probes", exact: true }));
    assert.equal(new URL(page.url()).hash, "#/equipment/probes");
    assert.equal(await page.evaluate(() => history.length), before + 1);
    await page.goBack();
    await expectVisible(page.getByRole("heading", { name: "Flower 2 today", exact: true }));
  });
  const routes = [
    ["today", "Flower 2 today"],
    ["zone/1", "Zone 1"],
    ["plan/targets", "Targets"],
    ["plan/schedule", "Schedule"],
    ["history/timeline", "Timeline"],
    ["history/water", "Water use"],
    ["history/compare", "Compare runs"],
    ["equipment/probes", "Probes"],
    ["equipment/stock", "Stock tanks"],
    ["equipment/tank", "Tank & pump"],
    ["equipment/dosing", "Dosing"],
    ["equipment/setup", "Rooms & setup"],
    ["settings", "Settings"],
    ["settings/notifications", "Notifications"],
    ["help", "Help"],
  ];
  const sectionOf = (route) =>
    ({
      plan: "Plan",
      history: "History",
      equipment: "Equipment",
      settings: "Settings & help",
      help: "Settings & help",
    })[route.split("/")[0]];
  for (const [route, heading] of routes)
    await check(`${route}: render, desktop layout and accessibility`, async () => {
      await go(route);
      await expectVisible(page.getByRole("heading", { name: heading, exact: true }));
      // A heading carries a sentence only for a behaviour someone could get wrong.
      if (route !== "plan/schedule")
        assert.equal(
          await page.locator(".page-heading > div > p").count(),
          0,
          `${route}: the heading repeats itself in a description`,
        );
      if (sectionOf(route)) await tabsShareRow(sectionOf(route));
      await noOverflow();
      await axe(route);
      await page.screenshot({
        path: path.join(out, `dashboard-${route.replace("/", "-")}.png`),
        fullPage: true,
      });
    });
  await check(
    "the menu: five entries, and a page's views as tabs with working history",
    async () => {
      await go("today");
      const menu = page.getByRole("navigation", { name: "Main navigation" });
      assert.deepEqual(await menu.getByRole("button").allInnerTexts(), [
        "Today",
        "Plan",
        "History",
        "Equipment",
        "Settings & help",
      ]);
      await menu.getByRole("button", { name: "Plan", exact: true }).click();
      await expectVisible(page.getByRole("heading", { name: "Targets", exact: true }));
      const views = page.getByRole("navigation", { name: "Plan views" });
      const targets = views.getByRole("button", { name: "Targets", exact: true });
      const schedule = views.getByRole("button", { name: "Schedule", exact: true });
      assert.equal(await targets.getAttribute("aria-current"), "page");
      await schedule.click();
      await expectVisible(page.getByRole("heading", { name: "Schedule", exact: true }));
      assert.equal(new URL(page.url()).hash, "#/plan/schedule");
      assert.equal(
        await menu.getByRole("button", { name: "Plan", exact: true }).getAttribute("aria-current"),
        "page",
      );
      assert.equal(await schedule.getAttribute("aria-current"), "page");
      await page.goBack();
      await expectVisible(page.getByRole("heading", { name: "Targets", exact: true }));
      await page.goForward();
      await expectVisible(page.getByRole("heading", { name: "Schedule", exact: true }));
      await targets.click();
      await expectVisible(page.getByRole("heading", { name: "Targets", exact: true }));
    },
  );
  await check(
    "the header: each room's state, the data's age and the two safety switches",
    async () => {
      await go("today");
      const chips = page.getByRole("group", { name: "Rooms" }).getByRole("button");
      assert.equal(await chips.count(), 2, "one chip per room");
      const chip = (id) => page.locator(`.room-chip[data-room="${id}"]`);
      assert.equal(await chip("room:").getAttribute("aria-pressed"), "true");
      assert.match(await chip("room:").innerText(), /Flower 2\s+Watering/);
      assert.match(await page.locator(".data-age").innerText(), /old|<1 min/);
      const switches = page.getByRole("group", { name: "Flower 2 safety switches" });
      await expectVisible(
        switches.getByRole("button", { name: "Watering on: switch watering off…", exact: true }),
      );
      await expectVisible(
        switches.getByRole("button", { name: "Room on: switch room off…", exact: true }),
      );
      // The breadcrumb, the status strip and the demo banner are gone.
      for (const gone of [".breadcrumb", ".status-line", ".demo-banner"])
        assert.equal(await page.locator(gone).count(), 0, `no ${gone}`);
      // Another room's chip opens it.
      await chip("room:f1_").click();
      await expectVisible(page.getByRole("heading", { name: "Flower 1 today", exact: true }));
      assert.equal(await page.locator("#desktop-room").inputValue(), "room:f1_");
      // Watering switched off from the header, through its review.
      await page
        .getByRole("button", { name: "Watering on: switch watering off…", exact: true })
        .click();
      const review = page.getByRole("dialog", { name: "Review watering" });
      await expectVisible(review);
      await axe("header: watering review");
      await review.getByRole("button", { name: /Apply 1 change/ }).click();
      await review.waitFor({ state: "hidden" });
      await expectVisible(
        page.getByRole("button", { name: "Watering off: switch watering on…", exact: true }),
      );
    },
  );
  await check("today: a room not watering says why, and opens its Settings", async () => {
    await go("settings", "f1");
    await page.getByRole("button", { name: "Switch watering off…", exact: true }).click();
    await page.getByRole("button", { name: /Apply \d+ change/ }).click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Today", exact: true })
      .click();
    await expectVisible(page.getByRole("heading", { name: "Flower 1 today", exact: true }));
    const stopped = page.locator(".today-stopped");
    assert.match(
      await stopped.innerText(),
      /Not watering\. Watering is switched off for this room \(its engine switch\)/,
    );
    assert.match(
      await page.locator('.room-chip[data-room="room:f1_"]').innerText(),
      /Not watering/,
    );
    assert.match(await page.locator("[data-today-line]").innerText(), /Watering off/);
    await stopped.getByRole("button", { name: "Switch it on in Settings", exact: true }).click();
    await expectVisible(page.getByRole("heading", { name: "Settings", exact: true }));
    assert.equal(await page.locator("#desktop-room").inputValue(), "room:f1_");
    await expectVisible(page.getByText("Watering off", { exact: true }).first());
    await expectVisible(page.getByRole("button", { name: "Switch watering on…", exact: true }));
  });
  await check("recent activity opens beside any page and leads to the timeline", async () => {
    await go("plan/targets");
    assert.equal(await page.getByRole("dialog").count(), 0, "the panel starts closed");
    await page.getByRole("button", { name: "Recent activity", exact: true }).click();
    const panel = page.getByRole("dialog", { name: "Recent activity" });
    await expectVisible(panel);
    assert.ok((await panel.locator(".event-row").count()) > 0, "the demo room has records");
    assert.equal(
      await panel.locator(".event-meta [data-event-type]").count(),
      await panel.locator(".event-row").count(),
      "every record in the panel names its type in a pill",
    );
    await axe("recent activity panel");
    await page.screenshot({ path: path.join(out, "dashboard-activity-panel.png") });
    // Closing hands focus back to the button that opened it.
    await page.keyboard.press("Escape");
    await panel.waitFor({ state: "hidden" });
    // Radix restores focus as the panel unmounts, a moment after it is hidden: wait, don't sample.
    await page
      .waitForFunction(
        () => document.activeElement?.getAttribute("aria-label") === "Recent activity",
        null,
        { timeout: 5_000 },
      )
      .catch(() => {
        throw new Error("focus did not return to the Recent activity button");
      });
    await page.getByRole("button", { name: "Recent activity", exact: true }).click();
    await expectVisible(panel);
    await panel.getByRole("button", { name: "Open the timeline" }).click();
    await expectVisible(page.getByRole("heading", { name: "Timeline", exact: true }));
    assert.equal(await page.getByRole("dialog").count(), 0, "the panel closes when the log opens");
  });
  await check("today: one laptop screen says which zone needs you and why", async () => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await go("today");
    const cards = page.locator("article.today-zone");
    await expectVisible(cards.first());
    assert.equal(await cards.count(), 3, "one card per zone");
    // The demo's readings are in before the page is measured.
    await page.locator(".today-spark").first().waitFor();
    // The new window size reaches the layout a frame or two after it is set: read until it settles.
    await page
      .waitForFunction(() => document.documentElement.scrollHeight <= innerHeight, null, {
        timeout: 3_000,
      })
      .catch(() => {});
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    assert.ok(height <= 900, `Today is ${height}px tall in a 900px window`);
    // The room in one line: watering, the stage and its day, steering, lights, the phase, alerts.
    const line = await page.locator("[data-today-line]").innerText();
    for (const part of [
      "Watering on",
      "Flower bulk",
      "day 37 of 56",
      "Vegetative",
      "Pore EC 3.5–6",
    ])
      assert.ok(line.includes(part), `the room's line says "${part}": ${line}`);
    // Flagged only when needed, with the reason in a line: zone 1's pore EC under the stage's band,
    // zone 3's back EC probe left out; zone 2 quiet.
    const flags = await cards.evaluateAll((all) =>
      all.map((card) => card.querySelector(".today-flag")?.textContent.trim() ?? null),
    );
    assert.match(flags[0], /^Pore EC 2\.8, under the stage’s 3\.5–6/);
    assert.equal(flags[1], null);
    assert.match(flags[2], /^A pore EC probe left out: not reporting/);
    // Each card: moisture with its bar, water per plant against the room, the last shot and the next.
    for (const index of [0, 1, 2]) {
      const card = cards.nth(index);
      assert.match(await card.locator(".today-vwc").innerText(), /^Moisture\s*[\d.]+\s*%$/);
      await expectVisible(card.locator(".moisture-bar"));
      const facts = await card.locator(".today-zone-facts").innerText();
      assert.match(facts, /Water\s+[\d.]+ (mL|L)\/plant · (≈ the room|[\d.]+× the room)/);
      assert.match(facts, /Last shot\s+\S/);
      assert.match(facts, /Next\s+\S/);
    }
    // What Jev changed today: three at most, newest first, with the way to the rest.
    const jev = page.locator("[data-jev-today]");
    const changes = jev.locator(".today-jev-list li");
    assert.ok((await changes.count()) > 0 && (await changes.count()) <= 3);
    await expectVisible(jev.getByRole("button", { name: "History" }));
    // A card opens its zone.
    await cards.nth(1).getByRole("link", { name: "Zone 2" }).click();
    await expectVisible(page.getByRole("heading", { name: "Zone 2", exact: true }));
    assert.equal(new URL(page.url()).hash, "#/zone/2");
    await go("today");
    await jev.getByRole("button", { name: "History" }).click();
    await expectVisible(page.getByRole("heading", { name: "Timeline", exact: true }));
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check("today: two phone screens at most, in both themes", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await inBothThemes("today on a phone", async () => {
      await go("today");
      await page.locator(".today-spark").first().waitFor();
    });
    await go("today");
    await page.locator(".today-spark").first().waitFor();
    await page
      .waitForFunction(() => document.documentElement.scrollHeight <= 2 * innerHeight, null, {
        timeout: 3_000,
      })
      .catch(() => {});
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    assert.ok(height <= 2 * 844, `Today is ${height}px tall on a 844px phone`);
    await noOverflow();
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check(
    "zone page: the day in Athena's chart language, fitted to today, against yesterday or a typical day",
    async () => {
      await go("zone/1");
      const day = page.locator("[data-day-timeline]");
      const layer = (name) => day.locator(`[data-layer="${name}"]`);
      // The earlier days load after today's: yesterday's line is the last to arrive.
      await expectVisible(layer("yesterday"));
      for (const name of ["vwc", "ec", "fc", "runoff", "maintenance", "projected", "shots", "jev"])
        assert.equal(await layer(name).count(), 1, `the ${name} layer is drawn`);
      // Today in numbers: moisture and its drying rate, pore EC against the stage's band, water and
      // each plant's share, shots, the overnight dryback against Athena's.
      const numbers = await day.locator(".zone-numbers").innerText();
      for (const part of [
        /Moisture\s+[\d.]+%/,
        /Pore EC\s+[\d.]+\s+below 3\.5–6/,
        /Water today\s+[\d.]+ L\s+\d+ mL\/plant\s+\d+% of the 40 L limit/,
        /Shots\s+\d+\s+last /,
        /dryback\s+[\d.]+% of peak\s+Athena 30–40%/,
      ])
        assert.match(numbers, part);
      assert.match(await day.locator(".zone-next").innerText(), /^Next: \S/);
      // The VWC axis fits today and the zone's targets: never 14-91 %.
      const ticks = (await day.locator(".grow-svg .axis-label").allTextContents())
        .filter((text) => text.endsWith("%"))
        .map(Number.parseFloat);
      assert.ok(ticks.length >= 3, `VWC gridlines: ${ticks}`);
      assert.ok(Math.max(...ticks) - Math.min(...ticks) <= 30, `VWC axis ${ticks}`);
      // Phases along the bottom as Athena's badges, every one there was today.
      assert.deepEqual(await day.locator(".phase-badge .badge-text").allTextContents(), [
        "P0",
        "P1",
        "P2",
        "P3",
      ]);
      const key = day.getByRole("list", { name: "Chart key" });
      assert.ok((await key.locator("li").count()) <= 8, "the key stays small");
      // Pointing at a shot says what it was, under the chart rather than over it, and a bar up the
      // plot marks where the reading is taken.
      const svg = day.locator(".grow-svg");
      const box = await svg.boundingBox();
      const dot = await svg
        .locator(".shot-dot")
        .nth(2)
        .evaluate((circle) => ({ x: +circle.getAttribute("cx"), y: +circle.getAttribute("cy") }));
      const readout = day.locator(".grow-readout");
      await page.mouse.move(box.x + dot.x, box.y + dot.y);
      await day.locator(".cursor-bar").waitFor({ state: "attached" }); // a 0-wide line: never "visible"
      assert.match(await readout.innerText(), /P1 shot /);
      assert.equal(await day.locator(".grow-tip").count(), 0, "nothing floats over the plot");
      assert.equal(
        Math.round(+(await day.locator(".cursor-bar").getAttribute("x1"))),
        Math.round(dot.x),
        "the bar stands where the pointer is",
      );
      await page.mouse.move(0, 0);
      await day.locator(".cursor-bar").waitFor({ state: "detached" });
      assert.match(await readout.innerText(), /Point at the chart/);
      // Or over the chart by the pointer, when that is chosen.
      const readings = day.getByLabel("Readings");
      await readings.selectOption("over");
      assert.equal(await readout.count(), 0);
      await page.mouse.move(box.x + dot.x, box.y + dot.y);
      await expectVisible(day.locator(".grow-tip"));
      assert.match(await day.locator(".grow-tip").innerText(), /P1 shot /);
      await page.mouse.move(0, 0);
      await day.locator(".grow-tip").waitFor({ state: "hidden" });
      await readings.selectOption("below");
      // Every entry in the key switches its layer, off the chart and out of the readings.
      const ecKey = key.getByRole("button", { name: "Pore EC" });
      assert.equal(await ecKey.getAttribute("aria-pressed"), "true");
      await expectVisible(layer("ec"));
      await ecKey.click();
      assert.equal(await ecKey.getAttribute("aria-pressed"), "false");
      assert.equal(await layer("ec").count(), 0);
      const plot = await svg.locator(".vwc-line").boundingBox();
      await page.mouse.move(plot.x + plot.width / 2, box.y + box.height / 2);
      assert.doesNotMatch(await readout.innerText(), /pore EC/);
      await page.mouse.move(0, 0);
      assert.equal(await key.getByRole("button").count(), await key.locator("li").count());
      const compare = day.getByLabel("Compare with");
      await compare.selectOption("typical");
      await expectVisible(layer("typical"));
      assert.ok(
        (await layer("typical").locator(".typical-band").getAttribute("d")).length > 100,
        "the typical day is a p25-p75 band",
      );
      assert.equal(await layer("yesterday").count(), 0);
      await compare.selectOption("none");
      assert.equal(await layer("typical").count(), 0);
      assert.equal(await layer("yesterday").count(), 0);
      // The choices are remembered in the browser.
      await page.reload({ waitUntil: "networkidle" });
      await expectVisible(day.locator(".grow-svg"));
      assert.equal(await compare.inputValue(), "none");
      assert.equal(await ecKey.getAttribute("aria-pressed"), "false");
      assert.equal(await layer("ec").count(), 0);
      await ecKey.click();
      await expectVisible(layer("ec"));
      await compare.selectOption("yesterday");
      await expectVisible(layer("yesterday"));
      await axe("zone day", "[data-day-timeline]");
      await axeDark("zone day", "[data-day-timeline]");
      await day.screenshot({ path: path.join(out, "dashboard-zone-day.png") });
    },
  );
  await check("zone page: Jev, the probes, the targets and the controls", async () => {
    await go("zone/3");
    // Jev on this zone: what it may move and within what range, and its latest decisions.
    const jev = page.locator("[data-zone-jev]");
    await expectVisible(jev);
    assert.match(
      await jev.locator(".zone-jev-setpoints").innerText(),
      /^Jev may move the P2 shot size 3\.5–5\.5% \(yours 4\.5%, now 4%\) and re-water point 59–62% \(yours 61%\)\. Last change /,
    );
    const decisions = jev.getByRole("list", { name: "Jev's latest decisions on this zone" });
    assert.ok((await decisions.locator("li").count()) > 0);
    // Probes: each one of the zone's reading, zone 3's back EC probe left out.
    const probes = page.locator(".zone-probes .zone-probe-list li");
    assert.equal(await probes.count(), 4);
    assert.deepEqual((await pillTones(".zone-probes .pill")).at(-1), [
      "Silent 3 h, left out of the zone's reading",
      "warn",
    ]);
    // Targets, read only, with Jev's ranges where it manages them.
    const targets = page.locator(".zone-targets");
    assert.deepEqual(await targets.locator(".jev-chip").allInnerTexts(), [
      "Jev · 59–62 %",
      "Jev · 3.5–5.5 %",
    ]);
    // Pause scheduling, through its review.
    const controls = page.locator(".zone-controls");
    await controls.getByRole("button", { name: "Pause zone scheduling" }).click();
    const review = page.getByRole("dialog", { name: "Review zone scheduling" });
    await expectVisible(review);
    await review.getByRole("button", { name: /Apply 1 change/ }).click();
    await review.waitFor({ state: "hidden" });
    await expectVisible(controls.getByRole("button", { name: "Enable zone scheduling" }));
    await expectVisible(page.locator(".zone-page-title").getByText("Scheduling paused"));
    // History: yesterday or the last week, on request.
    const range = page.getByRole("group", { name: "History range" });
    await range.getByRole("button", { name: "7 days" }).click();
    assert.equal(
      await range.getByRole("button", { name: "7 days" }).getAttribute("aria-pressed"),
      "true",
    );
    // The switcher moves between zones; Edit in Plan opens this zone's targets.
    await page
      .getByRole("navigation", { name: "Zones" })
      .getByRole("button", { name: "Zone 2" })
      .click();
    await expectVisible(page.getByRole("heading", { name: "Zone 2", exact: true }));
    await page.getByRole("button", { name: "Edit in Plan" }).click();
    await expectVisible(page.getByRole("heading", { name: "Targets", exact: true }));
    assert.equal(
      await page
        .getByRole("navigation", { name: "Targets for" })
        .getByRole("button", { name: "Zone 2" })
        .getAttribute("aria-current"),
      "page",
    );
    await go("zone/3");
    await axe("zone page, lower half", ".zone-page-grid");
    await axeDark("zone page, lower half", ".zone-page-grid");
  });
  await check("zone page: a zone is moved to a phase by hand, through the review", async () => {
    await go("zone/1");
    const picker = page.getByRole("group", { name: "Move Zone 1 to" });
    await expectVisible(picker);
    const move = async (from, to) => {
      assert.equal(
        await picker.getByRole("button", { name: from, exact: true }).isDisabled(),
        true,
      );
      await picker.getByRole("button", { name: to, exact: true }).click();
      const review = page.getByRole("dialog", { name: `Move Zone 1 to ${to.slice(0, 2)}?` });
      await expectVisible(review);
      await review.getByRole("button", { name: /^Apply 1 change/ }).click();
      await review.waitFor({ state: "hidden" });
      await expectVisible(page.locator(`.zone-page-title .pill[data-phase="${to.slice(0, 2)}"]`));
    };
    await move("P1 · Ramp-up", "P2 · Maintenance");
    await axe("zone phase picker");
    await move("P2 · Maintenance", "P1 · Ramp-up");
  });
  await check("zone page: each zone says what the controller waits for next", async () => {
    // The controller's own thresholds against the readings now, as the demo's controller publishes
    // them: zone 1 ramping, zone 2 in maintenance.
    await go("zone/1");
    assert.match(
      await page.locator(".zone-waiting").innerText(),
      /^The controller waits for\s+ramp shot (due|at .+) \(VWC [\d.]+% under [\d.]+%\) · P2 at VWC ≥ /,
    );
    await go("zone/2");
    assert.match(
      await page.locator(".zone-waiting").innerText(),
      /^The controller waits for\s+shot when VWC < [\d.]+% \(now [\d.]+%[^)]*\) · dilution if pwEC > [\d.]+ \(now [\d.]+\) · P3 by /,
    );
    // The chart's own line says what comes next in a few words.
    assert.match(await page.locator(".zone-next").innerText(), /^Next: \S/);
  });
  await check(
    "targets: a setting's ? explains it, in both themes, and closes on Escape",
    async () => {
      const trigger = () => page.getByRole("button", { name: "About Re-water point", exact: true });
      const help = () => page.getByRole("dialog", { name: "Re-water point" });
      await inBothThemes("setting explainer", async () => {
        await go("plan/targets");
        await trigger().click();
        await expectVisible(help());
        const text = await help().innerText();
        for (const part of ["What it is", "When it acts", "What it affects", "Athena Handbook"])
          assert.match(text, new RegExp(part, "i"), `the explainer has "${part}"`);
        assert.match(text, /a level, not a crossing/);
      });
      await go("plan/targets");
      await trigger().click();
      await expectVisible(help());
      await page.keyboard.press("Escape");
      assert.equal(await help().count(), 0, "Escape closes the explainer");
      // The popover hands focus back as it finishes closing, a moment after Escape: read it until it
      // arrives (up to 2 s) rather than once, which failed at random on a slower machine.
      let focused = false;
      for (let tries = 0; tries < 20 && !focused; tries++) {
        focused = await trigger().evaluate((button) => button === document.activeElement);
        if (!focused) await page.waitForTimeout(100);
      }
      assert.equal(focused, true, "focus returns to the ?");
    },
  );
  await check(
    "targets: one table by phase, Jev's ranges beside the values it manages",
    async () => {
      await go("plan/targets");
      const table = page.locator(".targets-panel > .targets-table");
      const phases = await table.locator(".targets-phase th").allInnerTexts();
      assert.deepEqual(
        phases.map((text) => text.replace(/\s+/g, " ").trim()),
        ["P0 Morning dryback", "P1 Ramp-up", "P2 Maintenance", "P3 Overnight dryback"],
      );
      const chips = await table.locator(".jev-chip").allInnerTexts();
      assert.deepEqual(chips, ["Jev · 59–62 %", "Jev · 3–5 %"]);
      // With Jev's Setpoints judge on the room, the Auto switch says what it lets Jev do.
      await expectVisible(page.getByText("Jev manages the P2 shot size and re-water point"));
      // The other steering mode's own targets are one tap down; the hardware is in Setup.
      await table.page().locator(".targets-more > summary").click();
      await expectVisible(
        page.locator('input[id="setting-number.crop_steering_zone_1_generative_dryback_target"]'),
      );
      assert.equal(
        await page
          .locator('input[id="setting-number.crop_steering_zone_1_substrate_volume"]')
          .count(),
        0,
        "substrate is set up in Equipment",
      );
      await page.getByRole("button", { name: "Equipment › Setup" }).click();
      await expectVisible(page.getByRole("heading", { name: "Rooms & setup", exact: true }));
    },
  );
  await check("targets: a draft survives refresh, validates, reviews and applies", async () => {
    await go("plan/targets");
    const field = page.locator('input[id="setting-number.crop_steering_zone_1_p1_target_vwc"]');
    const original = Number(await field.inputValue());
    await field.fill("999");
    await expectVisible(page.locator('[id="note-number.crop_steering_zone_1_p1_target_vwc"]'));
    assert.equal(
      await page
        .getByRole("button", { name: /^Review/ })
        .first()
        .isDisabled(),
      true,
    );
    await field.fill(String(original + 1));
    await page.getByRole("button", { name: "Refresh controller data" }).click();
    assert.equal(await field.inputValue(), String(original + 1));
    // The Plan entry counts the unsaved change.
    assert.match(
      await page
        .getByRole("navigation", { name: "Main navigation" })
        .getByRole("button", { name: /Plan/ })
        .innerText(),
      /1$/,
    );
    await page.getByRole("button", { name: /^Review 1 change/ }).click();
    await expectVisible(page.getByRole("dialog").getByText(/Flower 2 only/));
    await axe("targets review");
    await page.screenshot({ path: path.join(out, "dashboard-review.png") });
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Apply 1 change", exact: true })
      .click();
    await expectVisible(page.getByText("Changes applied and verified by controller readback."));
    assert.equal(await field.inputValue(), String(original + 1));
    await field.fill(String(original + 2));
    await page.locator("#desktop-room").selectOption("room:f1_");
    await expectVisible(
      page.getByRole("heading", {
        name: "Discard unsaved workspace changes?",
      }),
    );
    await page.getByRole("button", { name: "Keep editing" }).click();
    assert.equal(await field.inputValue(), String(original + 2));
    await page.locator("#desktop-room").selectOption("room:f1_");
    await page.getByRole("button", { name: "Discard and continue" }).click();
    assert.equal(await page.locator("#desktop-room").inputValue(), "room:f1_");
    await expectVisible(
      page.locator('input[id="setting-number.crop_steering_f1_zone_1_p1_target_vwc"]'),
    );
  });
  await check(
    "schedule: the flower by stage, today marked, and when the next one starts",
    async () => {
      await go("plan/schedule");
      const stages = page.locator(".grow-stage-table tbody tr");
      assert.equal(await stages.count(), 3);
      const current = page.locator(".grow-stage-table tr[data-current]");
      assert.match(await current.innerText(), /^Flower bulk\s+Now · week 6/);
      assert.match(await current.innerText(), /Vegetative\s+3\.5–6 mS\/cm\s+30–40 % of peak/);
      assert.match(
        await page.locator(".grow-stages .panel-heading p").innerText(),
        /^Flower day 37 of 56, week 6: flower bulk, steered vegetative\. Finish from .+ \(day 43\)\.$/,
      );
      assert.equal(await page.locator(".grow-weeks li[aria-current]").innerText(), "W6");
      // Validate and arm stay in view; the balance grid, endpoints and recipes are one tap down.
      await expectVisible(page.getByRole("button", { name: "Validate preview" }));
      await expectVisible(page.getByRole("button", { name: "Arm plan" }));
      const advanced = page.locator("details.plan-advanced");
      assert.equal(await advanced.getAttribute("open"), null);
      await advanced.locator("summary").click();
      const tabs = page.getByRole("tablist", { name: "Grow planner view" });
      assert.deepEqual(await tabs.getByRole("tab").allInnerTexts(), [
        "Steering balance",
        "Endpoint profiles",
        "Recipes",
      ]);
      await expectVisible(page.getByRole("region", { name: "Grow schedule" }));
      // The daily plan chart lives on Targets only.
      assert.equal(await page.locator(".planning-curve").count(), 0);
      await axe("schedule, advanced open");
    },
  );
  await check("timeline: one list with Jev in it, filtered, with its outcome checks", async () => {
    await go("history/timeline");
    const rows = page.locator(".timeline-row");
    await expectVisible(rows.first());
    const all = await rows.count();
    assert.ok(all > 10, `the demo's records and Jev's journal, ${all}`);
    assert.deepEqual(await page.locator(".timeline-day h2").allInnerTexts(), [
      "TODAY",
      "YESTERDAY",
    ]);
    // Jev's actions by default; every decision on request.
    const toggle = page.getByLabel("All Jev decisions");
    await toggle.check();
    assert.ok((await rows.count()) > all, "every decision shows more rows");
    await toggle.uncheck();
    assert.equal(await rows.count(), all);
    // An outcome is a tick or a cross on the decision it checks.
    assert.ok((await page.locator(".timeline-outcome").count()) > 0);
    // Water only; one zone; the room only.
    const types = page.getByRole("group", { name: "Record type" });
    await types.getByRole("button", { name: "Water", exact: true }).click();
    const kinds = await rows.evaluateAll((all) => [...new Set(all.map((row) => row.dataset.kind))]);
    assert.deepEqual(kinds, ["water"]);
    await types.getByRole("button", { name: "All", exact: true }).click();
    const zone = page.getByLabel("Timeline zone");
    await zone.selectOption("2");
    const zones = await rows.locator(".timeline-zone").allInnerTexts();
    assert.ok(zones.length > 0 && zones.every((name) => name === "Zone 2"), zones.join());
    await zone.selectOption("room");
    assert.deepEqual([...new Set(await rows.locator(".timeline-zone").allInnerTexts())], ["Room"]);
    await zone.selectOption("all");
    // A setpoint changed by hand is yours; Jev only noted it.
    await types.getByRole("button", { name: "Setpoints", exact: true }).click();
    await expectVisible(page.locator('.timeline-jev-tag[data-by="you"]').first());
    await expectVisible(page.getByText("Noted by Jev").first());
    await types.getByRole("button", { name: "All", exact: true }).click();
    await inBothThemes("timeline", async () => {
      await go("history/timeline");
      await expectVisible(page.locator(".timeline-row").first());
    });
    // A room without Jev: its controller records, without Jev's toggle.
    await go("history/timeline", "f1");
    await expectVisible(page.locator(".timeline-row").first());
    assert.equal(await page.getByLabel("All Jev decisions").count(), 0);
    assert.equal(await page.locator('.timeline-row[data-source="jev"]').count(), 0);
    // Every kind of record is coloured the way the pills are: water blue, phase violet, alerts amber.
    const colours = await page
      .locator(".timeline-kind")
      .evaluateAll((all) => [...new Set(all.map((kind) => kind.dataset.kind))].sort());
    assert.deepEqual(colours, ["alert", "phase", "water"]);
  });
  await check("timeline: search, clear and CSV export", async () => {
    await go("history/timeline");
    await page.getByRole("textbox", { name: "Search the timeline" }).fill("no-such-event");
    await expectVisible(page.getByRole("heading", { name: "Nothing matches this view" }));
    await page.getByRole("button", { name: "Clear filters" }).click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export CSV" }).click();
    const download = await downloadPromise;
    assert.match(download.suggestedFilename(), /flower-2-timeline-.+\.csv/);
    await download.saveAs(path.join(out, "timeline-export.csv"));
    const csv = await readFile(path.join(out, "timeline-export.csv"), "utf8");
    assert.match(csv, /Timestamp.*Room.*Zone.*Type.*Message.*Result/);
    assert.match(csv, /"Jev · /);
  });
  await check("a zone page's Jev history opens the timeline on that zone", async () => {
    await go("zone/2");
    await page.locator("[data-zone-jev]").getByRole("button", { name: "History" }).click();
    await expectVisible(page.getByRole("heading", { name: "Timeline", exact: true }));
    assert.equal(await page.getByLabel("Timeline zone").inputValue(), "2");
  });
  await check(
    "water use: every zone's litres, its grow weeks, and water per plant today",
    async () => {
      await go("history/water");
      const panel = page.locator(".wu-panel");
      await expectVisible(panel.getByRole("heading", { name: "Litres by zone", exact: true }));
      const rows = panel.locator(".wu-table tbody tr");
      await expectVisible(rows.first());
      assert.equal(await rows.count(), 3, "one row per demo zone");
      for (let index = 0; index < 3; index++) {
        const [zone, today, week, since, estimate] = await rows
          .nth(index)
          .locator("td")
          .allInnerTexts();
        assert.match(zone, new RegExp(`Zone ${index + 1}`));
        // Litres, and the grow-days each number covers.
        assert.match(today, /[\d.]+ L\n.+ from 10:00/, `Zone ${index + 1} today: ${today}`);
        assert.match(week, /[\d,.]+ L\nWeek \d+ · /, `Zone ${index + 1} this week: ${week}`);
        assert.match(
          since,
          /[\d,.]+ L\n.+ · grow-day \d+/,
          `Zone ${index + 1} since start: ${since}`,
        );
        assert.match(estimate, /≈ [\d,]+ L\n.*last 7 days’ average.*\n84-day plan/);
      }
      // Today is the live counter; the demo's saved draft plan dates the grow and says so.
      assert.match((await rows.first().locator("td").allInnerTexts())[1], /^5\.3 L/);
      await expectVisible(
        panel.getByText(/^Grow start: .+ saved grow plan \(a draft, not armed\)/),
      );
      const chart = panel.getByRole("img", {
        name: /^Litres per grow week for Zone 1, Zone 2, Zone 3/,
      });
      await expectVisible(chart);
      const bars = chart.locator(".recharts-bar-rectangle");
      await bars.first().waitFor();
      const count = await bars.count();
      assert.ok(count >= 6 && count % 3 === 0, `one bar per zone and grow week, got ${count}`);
      await panel.screenshot({ path: img("water-use.png") });
      // The definition of "This week" is reachable from the keyboard.
      await panel.getByRole("button", { name: "How this week is counted" }).focus();
      await expectVisible(panel.getByRole("tooltip", { name: /grow week/ }));
      // This grow-day's water per plant, the table the Zones page had.
      const plants = page.getByRole("region", { name: "Daily water by zone and per plant" });
      assert.match(
        await plants.locator("tbody tr").first().innerText(),
        /Zone 1\s+36\s+5\.3 L\s+147\.2 mL/,
      );
      await axe("water use");
      await axeDark("water use", ".wu-panel");
      await page.screenshot({ path: path.join(out, "dashboard-water-use.png"), fullPage: true });
    },
  );
  await check(
    "compare runs: by grow week, the biggest differences, and the detail one tap down",
    async () => {
      await go("history/compare");
      // The run in progress against the latest ended one, chosen to start with.
      assert.match(
        await page.getByLabel("Current run").locator("option:checked").innerText(),
        /^Demo • current run/,
      );
      assert.match(
        await page.getByLabel("Previous run").locator("option:checked").innerText(),
        /^Demo • previous run/,
      );
      const weeks = page.locator(".rw-table tbody tr");
      await expectVisible(weeks.first());
      assert.ok((await weeks.count()) >= 3, "every week either run reached");
      assert.match(await weeks.first().innerText(), /^Week 1/);
      // Each cell: this run, then the compared run under it.
      const cell = weeks.first().locator("td").first();
      await expectVisible(cell.locator(".rw-this"));
      await expectVisible(cell.locator(".rw-other"));
      const differences = page.locator(".rw-differences li");
      assert.ok((await differences.count()) > 0 && (await differences.count()) <= 3);
      assert.match(await differences.first().innerText(), /^Week \d+: /);
      // The full-resolution chart and the daily ranges are collapsed.
      for (const section of ["chart", "quality"])
        assert.equal(
          await page
            .locator(`details.comparison-more[data-section="${section}"]`)
            .getAttribute("open"),
          null,
        );
      await page.locator('details[data-section="chart"] > summary').click();
      await expectVisible(page.locator(".comparison-chart svg"));
      await page.locator('details[data-section="quality"] > summary').click();
      const table = ".comparison-table tbody";
      await page.locator(`${table} .meter`).first().waitFor();
      const cells = await page.locator(`${table} tr`).evaluateAll((rows) =>
        rows.flatMap((row) =>
          [...row.cells].slice(1).map((cell) => {
            const meter = cell.querySelector(".meter");
            return meter
              ? [
                  meter.querySelector(".meter-fill").dataset.tone,
                  meter.getBoundingClientRect().width,
                ]
              : null;
          }),
        ),
      );
      assert.ok(cells.length > 0 && cells.every(Boolean), "every recorded day has its range bars");
      // Current VWC, current EC, previous VWC, previous EC: the previous run's ranges are grey.
      assert.deepEqual(
        [...new Set(cells.map(([tone], i) => `${i % 4 < 2 ? "current" : "previous"} ${tone}`))],
        ["current normal", "previous muted"],
      );
      assert.equal(new Set(cells.map(([, width]) => width)).size, 1, "one scale width for all");
      await expectVisible(
        page.getByRole("heading", { name: "Where the weekly figures come from" }),
      );
      await axe("compare runs, all open");
      await axeDark("compare runs", ".comparison-page");
      // The run records themselves are kept in Settings.
      await page.getByRole("button", { name: "Run records" }).click();
      await expectVisible(page.getByRole("heading", { name: "Settings", exact: true }));
      await expectVisible(page.locator("#run-records"));
      assert.deepEqual(await pillTones(".comparison-run-list h3 .pill"), [
        ["Ongoing", "on"],
        ["Ended", "neutral"],
      ]);
    },
  );
  await check(
    "probes: every probe's health, the controller and Jev, the internals one tap down",
    async () => {
      await go("equipment/probes");
      const rows = page.locator(".probes-table tr[data-probe]");
      await expectVisible(rows.first());
      assert.equal(await rows.count(), 12, "two moisture and two EC probes in each of three zones");
      // Name first, entity id under it.
      const first = await rows.first().locator("td").first().innerText();
      assert.match(first, /^Zone 1 front VWC\nsensor\.demo_z1_front_vwc$/);
      const health = await pillTones(".probes-table [data-probe-health]");
      assert.equal(health.filter(([text]) => text === "OK").length, 11);
      assert.deepEqual(
        health.find(([text]) => text !== "OK"),
        ["Silent 3 h, left out of the zone's reading", "warn"],
      );
      // Each probe's last six hours.
      await page.locator(".probes-table [data-sensor-trend] .sparkline").first().waitFor();
      assert.equal(await page.locator(".probes-table [data-sensor-trend] .sparkline").count(), 12);
      // Each zone's valve; the controller and Jev at the top.
      assert.equal(await page.locator(".probes-zone [data-zone-valve]").count(), 3);
      assert.match(
        await page.locator(".probes-status").innerText(),
        /Probes\s+11 of 12 OK[\s\S]*Controller\s+Reporting[\s\S]*Jev\s+On/,
      );
      // The controller's own sensors: collapsed, then as the Sensors page had them.
      const internals = page.locator("details.probes-more", { hasText: "Controller internals" });
      assert.equal(await internals.getAttribute("open"), null);
      await internals.locator("summary").click();
      const trends = "[data-sensor-trend] .sparkline";
      await internals.locator(trends).first().waitFor();
      const sensors = await internals.locator(".sensors-table tbody tr").evaluateAll((rows) =>
        rows.map((row) => ({
          numeric: /^-?\d+(\.\d+)?(\s|$)/.test(row.cells[1].textContent.trim()),
          line: !!row.cells[2].querySelector(".sparkline"),
          pill: [
            row.cells[3].textContent.trim(),
            row.cells[3].querySelector(".pill")?.dataset.tone,
          ],
        })),
      );
      assert.ok(sensors.some((row) => row.numeric) && sensors.some((row) => !row.numeric));
      for (const row of sensors) {
        assert.equal(row.line, row.numeric, "a line for every numeric reading, and only for those");
        const tones = { Reporting: "on", "Stale or unverified": "warn", Unavailable: "off" };
        assert.equal(row.pill[1], tones[row.pill[0]], row.pill[0]);
      }
      // The room map, from Insights.
      const map = page.locator("details.probes-more", { hasText: "Room map" });
      await map.locator("summary").click();
      await expectVisible(map.locator(".insight-room-map"));
      await axe("probes, all open");
      await axeDark("probes", "#main-content");
    },
  );
  await check(
    "stock tanks: the next to run out, refill, set a level, record a batch and add a tank",
    async () => {
      await go("equipment/stock");
      const card = (id) => page.locator(`[data-stock-tank="${id}"]`);
      await expectVisible(card("bloom"));
      assert.equal(await page.locator("[data-stock-tank]").count(), 4);
      assert.equal(
        await page.locator("[data-stock-next]").innerText(),
        "Next to run out: Bloom, about 3 batches left.",
      );
      await page.screenshot({ path: img("stock-tanks.png") });
      // Each tank is linked to its dosing pump: drawn by what the pump doses, its draws listed.
      assert.equal(
        await card("bloom").locator("[data-stock-drawn]").innerText(),
        "Drawn by\nBloom as it doses",
      );
      assert.match(
        await card("balance").locator("[data-stock-draws] li").first().innerText(),
        /Dose\s+25 mL$/,
      );
      // Bloom starts within half again of its low mark: amber, "Getting low".
      assert.equal(await card("bloom").locator(".pill").textContent(), "Getting low");
      await card("bloom").getByRole("button", { name: "Refilled" }).click();
      await expectVisible(card("bloom").getByText("OK", { exact: true }));
      assert.match(await card("bloom").locator("dd").first().textContent(), /^20 of 20 L$/);

      await card("cleanse").getByRole("button", { name: "Set level" }).click();
      await card("cleanse").getByLabel("Level read off the tank (L)").fill("0.8");
      await card("cleanse").getByRole("button", { name: "Save level" }).click();
      await expectVisible(card("cleanse").getByText("Low", { exact: true }));

      await page.getByRole("button", { name: "Record a batch" }).click();
      const confirm = page.getByRole("dialog");
      if (await confirm.count())
        await confirm.getByRole("button", { name: "Record the batch" }).click();
      // Recent draws start collapsed.
      const history = page.locator("details.stock-history-more");
      await expectVisible(history.locator("summary"));
      assert.equal(await history.getAttribute("open"), null);
      await history.locator("summary").click();
      await expectVisible(history.getByRole("heading", { name: "Recent draws" }));
      assert.match(await card("bloom").locator("dd").first().textContent(), /^18\.2 of 20 L$/);

      await page.getByRole("button", { name: "Edit stock tanks" }).click();
      const editor = page.getByRole("dialog");
      await editor.getByRole("button", { name: "Add a stock tank" }).click();
      const names = editor.getByLabel("Name");
      await names.last().fill("Silica");
      await editor.getByRole("button", { name: "Save stock tanks" }).click();
      await expectVisible(card("silica"));
      // No pump draws Silica: each batch takes its dose.
      assert.equal(await card("silica").locator("[data-stock-drawn]").count(), 0);
      await expectVisible(card("silica").getByText("Per batch"));
      await axe("stock tanks after edits");
      await noOverflow();
    },
  );
  await check(
    "dosing: each room's pumps, a dose and a batch through their reviews, and stop; only requests are sent",
    async () => {
      // Flower 2's four pumps and Flower 1's six, one of them not calibrated yet.
      const cards = page.locator("[data-dosing-pump]");
      const strip = page.locator("[data-stock-strip]");
      const stockOf = (id) => page.locator(`[data-dosing-pump="${id}"] [data-pump-stock]`);
      await go("equipment/dosing");
      await expectVisible(cards.first());
      assert.deepEqual(await cards.locator(".dosing-pump-select").allInnerTexts(), [
        "Balance",
        "Bloom",
        "Core",
        "Cleanse",
      ]);
      assert.match(
        await page.locator("[data-batch-line]").innerText(),
        /^No batch running · last batch finished \S/,
      );
      await go("equipment/dosing", "f1");
      await expectVisible(cards.first());
      assert.equal(await cards.count(), 6, "one card per pump");
      assert.deepEqual(await pillTones('[data-dosing-pump="fade"] .pill'), [
        ["Not calibrated", "warn"],
      ]);
      assert.deepEqual(await strip.locator("[data-stock-gauge] strong").allInnerTexts(), [
        "Grow",
        "Cleanse",
        "Balance",
        "Fade",
        "Core",
        "Bloom",
      ]);
      // Core, passed by in the recipe and dosed by hand: its tank lasts doses at its last one.
      assert.equal(
        await stockOf("core").locator(".dosing-stock-left").innerText(),
        "about 287 doses left",
      );
      // Flower 1's tank is filled by hand: its batch passes the fill by.
      assert.equal(
        await page.locator('.dosing-steps [data-step="fill"]').getAttribute("data-state"),
        "skipped",
      );
      await inBothThemes("dosing", async () => {
        await go("equipment/dosing");
        await expectVisible(cards.first());
      });
      // A fresh Flower 2: each card shows the stock tank its pump is linked to, Bloom's drawn to
      // scale with its litres and the batches its recipe amount leaves, and the stock strip every
      // linked tank in pump order.
      await go("equipment/dosing");
      await expectVisible(cards.first());
      assert.equal(await stockOf("bloom").getAttribute("data-pump-stock"), "bloom");
      assert.equal(
        await stockOf("bloom").locator(".dosing-stock-litres").innerText(),
        "5.4 L of 20 L",
      );
      assert.equal(
        await stockOf("bloom").locator(".dosing-stock-left").innerText(),
        "about 3 batches left",
      );
      assert.deepEqual(await strip.locator("[data-stock-gauge] strong").allInnerTexts(), [
        "Balance",
        "Bloom",
        "Core",
        "Cleanse",
      ]);
      // A dose of Bloom, through its review: its card doses, then the history has it.
      await page.locator('[data-dosing-pump="bloom"] .dosing-pump-select').click();
      await page.getByLabel("Amount (mL)").fill("60");
      assert.match(
        await page.locator("[data-dose-summary]").innerText(),
        /^Your request: 60 mL of Bloom, about 5\.7 s$/,
      );
      await page.getByRole("button", { name: /^Start Bloom/ }).click();
      const review = page.getByRole("dialog", { name: "Dose Bloom?" });
      await expectVisible(review);
      await axe("dosing: the dose's review");
      await review.getByRole("button", { name: "Start Bloom", exact: true }).click();
      await review.waitFor({ state: "hidden" });
      await expectVisible(page.locator('[data-dosing-pump="bloom"][data-state="dosing"]'));
      await expectVisible(page.locator('[data-dosing-pump="bloom"] [role="progressbar"]'));
      await page.screenshot({ path: path.join(out, "dashboard-dosing-dose.png"), fullPage: true });
      await page.waitForFunction(
        () =>
          document
            .querySelector('tr[data-history-kind="dose"]')
            ?.textContent.includes("Bloom 60 mL"),
        null,
        { timeout: 20_000 },
      );
      assert.match(
        await page.locator('tr[data-history-kind="dose"]').first().innerText(),
        /Dose Bloom\s+Finished\s+Bloom 60 mL/,
      );
      assert.equal(
        await page.locator('[data-dosing-pump="bloom"]').getAttribute("data-state"),
        "idle",
      );
      // What it dosed came off Bloom's stock tank: 5.4 L less 60 mL, on its card and in the strip.
      await expectVisible(
        stockOf("bloom").locator(".dosing-stock-litres", { hasText: "5.3 L of 20 L" }),
      );
      assert.equal(
        await strip.locator('[data-stock-gauge="bloom"] .dosing-stock-litres').innerText(),
        "5.3 L of 20 L",
      );
      // A batch, through its review: its steps walk, and stop ends it where it is.
      await page.getByRole("button", { name: "Make a batch", exact: true }).click();
      const batch = page.getByRole("dialog", { name: "Make a batch in Flower 2?" });
      await expectVisible(batch);
      await axe("dosing: the batch's review");
      await batch.getByRole("button", { name: "Make the batch", exact: true }).click();
      await batch.waitFor({ state: "hidden" });
      await expectVisible(page.locator('.dosing-steps [data-step="fill"][data-state="running"]'));
      await page.getByRole("button", { name: "Stop the batch", exact: true }).click();
      const stop = page.getByRole("dialog", { name: "Stop dosing in Flower 2?" });
      await expectVisible(stop);
      await stop.getByRole("button", { name: "Send stop", exact: true }).click();
      await stop.waitFor({ state: "hidden" });
      await expectVisible(
        page.locator("[data-batch-summary]", {
          hasText: /^Last batch stopped \S.* \(stop requested during [a-z ]+\)$/,
        }),
      );
      assert.equal((await pillTones('tr[data-history-kind="batch"] .pill'))[0][1], "warn");
      // The setup open for editing, like the page, fits a phone.
      await page.setViewportSize({ width: 390, height: 844 });
      await page.locator("details.dosing-setup > summary").click();
      await page.getByRole("button", { name: "Edit dosing setup", exact: true }).click();
      await expectVisible(page.getByRole("button", { name: "Review dosing setup" }));
      await noOverflow();
      await axe("dosing setup, editing, on a phone");
      await page.screenshot({ path: path.join(out, "mobile-dosing-setup.png"), fullPage: true });
      await page.setViewportSize({ width: 1440, height: 1000 });

      // Against Home Assistant: every action is a dosing_request, and nothing else is written.
      const ha = await browser.newContext({
        viewport: { width: 1440, height: 1000 },
        reducedMotion: "reduce",
      });
      const posts = [];
      const fixture = {};
      const stamp = () => new Date().toISOString();
      const put = (entity_id, state, attributes = {}) =>
        (fixture[entity_id] = {
          entity_id,
          state: String(state),
          attributes,
          last_changed: stamp(),
          last_updated: stamp(),
        });
      const pump = (id, name, flow, dosing = "off") => {
        put(`number.${id}_volume`, 100, { unit_of_measurement: "mL" });
        put(`button.${id}_start`, "unknown");
        put(`binary_sensor.${id}_dosing`, dosing);
        put(`switch.${id}_power`, "on");
        put(`number.${id}_flow`, flow, { unit_of_measurement: "mL/s" });
        return {
          id,
          name,
          volume_entity: `number.${id}_volume`,
          start_entity: `button.${id}_start`,
          dosing_entity: `binary_sensor.${id}_dosing`,
          dosing_prefix: "Dosing",
          power_entity: `switch.${id}_power`,
          flow_entity: `number.${id}_flow`,
          max_ml: 2000,
          restore_volume: true,
        };
      };
      const idle = {
        step: "idle",
        pump: null,
        started_at: null,
        step_started_at: null,
        steps: [],
        result: null,
        ended_at: null,
      };
      for (const [prefix, name, pumps] of [
        ["", "Flower 2", [pump("bloom", "Bloom", 10.5), pump("grow", "Grow", 10.9, "unavailable")]],
        ["f1_", "Flower 1", []],
      ]) {
        put(`sensor.crop_steering_${prefix}engine_config`, "ready", {
          prefix,
          num_zones: 1,
          friendly_name: `${name} engine config`,
          enable_flag: `switch.crop_steering_${prefix}engine_enabled`,
        });
        put(`switch.crop_steering_${prefix}engine_enabled`, "on");
        put(`sensor.crop_steering_${prefix}ai_heartbeat`, "online", { last_beat: stamp() });
        put(`sensor.crop_steering_${prefix}dosing_config`, 1, {
          pumps,
          batch: {
            fill_valve: null,
            full_entity: null,
            full_state: "on",
            fill_timeout_min: 20,
            mix_pump: null,
            mix_valves: [],
            mix_power_sensor: null,
            mix_min_w: 0,
            premix_min: 1,
            postmix_min: 1,
            close_entities: [],
            hold_entity: null,
            filled_at_entity: null,
            recipe: pumps.map((item) => ({ pump: item.id, ml: 100, ml_entity: null })),
          },
          request: null,
        });
        put(`sensor.crop_steering_${prefix}dosing`, "idle", {
          pumps: Object.fromEntries(
            pumps.map((item) => [
              item.id,
              { state: "idle", flow_ml_s: 10, target_ml: null, started_at: null, last: null },
            ]),
          ),
          batch: idle,
          handled: null,
          handled_result: null,
          history: [],
        });
      }
      await ha.route("**/*", async (route) => {
        const request = route.request(),
          url = new URL(request.url());
        if (url.origin !== base) return route.abort();
        if (!url.pathname.startsWith("/api/")) return route.continue();
        const reply = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
        if (url.pathname === "/api/states") return reply(Object.values(fixture));
        if (url.pathname.startsWith("/api/states/")) {
          const entity = fixture[decodeURIComponent(url.pathname.slice(12))];
          return entity ? reply(entity) : reply({}, 404);
        }
        if (request.method() !== "POST") return reply([]);
        const body = request.postDataJSON() ?? {};
        posts.push({ path: url.pathname, body });
        const prefix = String(body.room_id ?? "").replace(/^room:/, "");
        const config = fixture[`sensor.crop_steering_${prefix}dosing_config`];
        const status = fixture[`sensor.crop_steering_${prefix}dosing`];
        if (url.pathname === "/api/services/crop_steering/dosing_get")
          return reply({
            service_response: {
              schema_version: 1,
              room_id: body.room_id,
              config: { revision: Number(config.state), ...config.attributes },
              candidates: [],
              error: null,
            },
          });
        if (url.pathname !== "/api/services/crop_steering/dosing_request")
          return reply({ message: "Not a dosing service" }, 400);
        const taken = {
          id: `request${posts.length}`,
          action: body.action,
          pump: body.pump ?? null,
          ml: body.ml ?? null,
          at: stamp(),
          by: "Fixture",
        };
        config.attributes = { ...config.attributes, request: taken };
        // The controller takes it at once: a dose is over in an instant, a batch fills until stopped.
        status.state = body.action === "batch" ? "batch" : "idle";
        status.attributes = {
          ...status.attributes,
          handled: taken.id,
          handled_result: body.action === "stop" ? "stopped" : "taken",
          batch:
            body.action === "batch"
              ? {
                  ...idle,
                  step: "fill",
                  started_at: stamp(),
                  steps: [
                    { step: "hold", state: "done" },
                    { step: "close", state: "done" },
                    { step: "fill", state: "running" },
                  ],
                }
              : idle,
        };
        return reply({ service_response: { request: taken, error: null } });
      });
      const live = await ha.newPage();
      live.on("pageerror", (error) => pageErrors.push(error.message));
      await live.goto(`${base}/dashboard.html?room=room:#/equipment/dosing`, {
        waitUntil: "networkidle",
      });
      const bloom = live.locator('[data-dosing-pump="bloom"]');
      await expectVisible(bloom);
      // No pump is linked to a stock tank here: the cards say so, and there is no stock strip.
      assert.equal(await bloom.locator("[data-pump-stock]").innerText(), "No stock tank linked");
      assert.equal(await live.locator("[data-stock-strip]").count(), 0);
      // A pump whose dosing sensor is unavailable: greyed out, a question mark on its head.
      const grow = live.locator('[data-dosing-pump="grow"]');
      assert.equal(await grow.getAttribute("data-state"), "unavailable");
      assert.equal(await grow.locator(".pp-unknown").textContent(), "?");
      await live.getByLabel("Amount (mL)").fill("60");
      await live.getByRole("button", { name: /^Start Bloom/ }).click();
      await live
        .getByRole("dialog")
        .getByRole("button", { name: "Start Bloom", exact: true })
        .click();
      await expectVisible(live.locator('[data-request-stage="taken"]'));
      // The controller would refuse a batch with Grow unavailable: said before it is asked for.
      assert.equal(
        await live.locator("[data-batch-warning]").innerText(),
        "Grow is unavailable: the controller would refuse a batch now.",
      );
      await live.getByRole("button", { name: "Make a batch", exact: true }).click();
      await live.getByRole("dialog").getByRole("button", { name: "Make the batch" }).click();
      await live.getByRole("button", { name: "Stop the batch", exact: true }).click();
      await live.getByRole("dialog").getByRole("button", { name: "Send stop" }).click();
      await expectVisible(live.locator("[data-request-stage]", { hasText: "request to stop" }));
      assert.deepEqual(
        posts.filter((post) => post.path.endsWith("/dosing_request")).map((post) => post.body),
        [
          { action: "dose", pump: "bloom", ml: 60, room_id: "room:" },
          { action: "batch", room_id: "room:" },
          { action: "stop", room_id: "room:" },
        ],
      );
      // Besides reads (dosing_get, and What's new on opening), those three requests are all it sent:
      // no pump, valve or number was written.
      assert.deepEqual(
        posts
          .map((post) => post.path)
          .filter((path) => !/\/crop_steering\/(dosing_get|whats_new_get)$/.test(path)),
        Array(3).fill("/api/services/crop_steering/dosing_request"),
        "the page wrote nothing but its dosing requests",
      );
      // A room without pumps says what dosing does, and offers to set it up.
      await live.locator("#desktop-room").selectOption("room:f1_");
      await expectVisible(live.getByRole("heading", { name: "No dosing pumps in Flower 1" }));
      await expectVisible(live.getByRole("button", { name: "Set up dosing", exact: true }));
      await ha.close();
    },
  );
  await check(
    "dosing: each room's stock strip, light and dark, on a phone, and its way to Stock tanks",
    async () => {
      const strip = page.locator("[data-stock-strip]");
      const gauges = strip.locator("[data-stock-gauge]");
      for (const [room, count] of [
        ["f2", 4],
        ["f1", 6],
      ]) {
        await go("equipment/dosing", room);
        await expectVisible(strip);
        assert.equal(await gauges.count(), count, `${room}: a gauge per linked tank`);
        // Each labelled with its level, its litres and what it has left, its low mark drawn.
        for (const text of await gauges.allInnerTexts())
          assert.match(
            text,
            /\n\d+%\n[\d.]+ L of [\d.]+ L(\n(about \d+|less than one) (batch|batches|dose|doses) left)?/,
          );
        assert.equal(await gauges.locator(".sb-low").count(), count);
      }
      await inBothThemes("dosing, Flower 1", async () => {
        await go("equipment/dosing", "f1");
        await expectVisible(strip);
      });
      await go("equipment/dosing");
      await expectVisible(strip);
      await page.screenshot({ path: path.join(out, "dashboard-dosing-light.png"), fullPage: true });
      await page.evaluate(() => localStorage.setItem("irrigation-theme", "dark"));
      await page.reload({ waitUntil: "networkidle" });
      await expectVisible(strip);
      await page.screenshot({ path: path.join(out, "dashboard-dosing-dark.png"), fullPage: true });
      await page.evaluate(() => localStorage.setItem("irrigation-theme", "light"));
      // A phone: both rooms fit, the strip two tanks to a row.
      await page.setViewportSize({ width: 390, height: 844 });
      for (const room of ["f1", "f2"]) {
        await go("equipment/dosing", room);
        await expectVisible(strip);
        await noOverflow();
      }
      await axe("dosing on a phone");
      await page.screenshot({ path: path.join(out, "mobile-dosing.png"), fullPage: true });
      await page.setViewportSize({ width: 1440, height: 1000 });
      await strip.getByRole("button", { name: /^Stock tanks/ }).click();
      await expectVisible(page.getByRole("heading", { name: "Stock tanks", exact: true }));
      assert.match(page.url(), /#\/equipment\/stock$/);
    },
  );
  await check("setup: every mapping says whether it is mapped; the checks are pills", async () => {
    await inBothThemes("rooms & setup", async () => {
      await go("equipment/setup");
      await expectVisible(page.locator("#room-name"));
    });
    await go("equipment/setup");
    await expectVisible(page.locator("#room-name"));
    const mappings = await page.locator(".mapping-picker").evaluateAll((pickers) =>
      pickers.map((picker) => ({
        mapped: !!picker.querySelector(".mapping-id"),
        pill: [
          picker.querySelector(".mapping-head .pill")?.textContent.trim(),
          picker.querySelector(".mapping-head .pill")?.dataset.tone,
        ],
      })),
    );
    assert.ok(mappings.some((m) => m.mapped) && mappings.some((m) => !m.mapped));
    for (const { mapped, pill } of mappings)
      assert.deepEqual(pill, mapped ? ["Mapped", "on"] : ["Not mapped", "neutral"]);
    assert.deepEqual(await pillTones(".workspace-card .pill:has(.pill-dot)"), [
      ["Controller acknowledgement pending", "warn"],
      ["Room descriptor discovered", "on"],
    ]);
  });
  await check(
    "setup: the substrate, sizing and safety numbers, each through its review",
    async () => {
      await go("equipment/setup");
      const section = page.locator(".controller-settings");
      await expectVisible(
        section.getByRole("heading", { name: /substrate, sizing and safety limits/ }),
      );
      const capacity = section.locator(
        'input[id="setting-number.crop_steering_zone_1_field_capacity"]',
      );
      await capacity.fill("72");
      await section.getByRole("button", { name: /^Review 1 change/ }).click();
      const review = page.getByRole("dialog");
      await expectVisible(review.getByText("Zone 1 · Full saturation (most it holds)"));
      await review.getByRole("button", { name: "Apply 1 change", exact: true }).click();
      await expectVisible(
        section.getByText("Changes applied and verified by controller readback."),
      );
      // Safety limits are one tap down; so are the water calculator and the catch test.
      const safety = section.locator("details.controller-settings-safety");
      await safety.locator("> summary").click();
      await expectVisible(
        safety.locator('input[id="setting-number.crop_steering_zone_1_max_daily_volume"]'),
      );
      const water = section.locator("details.controller-settings-water");
      await water.locator("> summary").click();
      await section.getByLabel("Collected water per dripper · mL").fill("200");
      await section.getByLabel("Collection time · minutes").fill("3");
      assert.match(await section.locator(".calibration-result").innerText(), /4 L\/h/);
      await section.getByRole("button", { name: "Use estimate in the calculation" }).click();
      await expectVisible(
        section.getByText("Using your catch-test flow in this calculation only."),
      );
      await axe("setup numbers, all open", ".controller-settings");
    },
  );
  await check(
    "settings: the connection, the room, its watering and its runs are state pills",
    async () => {
      await inBothThemes("settings", async () => {
        await go("settings");
        await expectVisible(page.locator(".settings-section [data-connection]"));
      });
      await go("settings");
      await expectVisible(page.locator("#run-records .pill").first());
      assert.deepEqual(await pillTones(".settings-section .pill"), [
        ["Demo mode", "warn"],
        ["Room on", "on"],
        ["Watering on", "on"],
        ["Ongoing", "on"],
        ["Ended", "neutral"],
      ]);
      // The advanced-workflow links are gone: the menu has them.
      assert.equal(await page.getByRole("heading", { name: "Advanced workflows" }).count(), 0);
    },
  );
  await check("settings: one switch flips every zone, through the review", async () => {
    // Flower 1's zone 3 is paused for inspection: the switch is on while any zone is on, as the
    // entities card's header toggle is, and switching it on again switches zone 3 on too.
    await go("settings", "f1");
    const all = page.getByRole("switch", { name: "Every zone in Flower 1", exact: true });
    const count = page.locator(".settings-zones .all-zones-count");
    const flip = async (title, rows, after) => {
      await all.click();
      const review = page.getByRole("dialog", { name: title, exact: true });
      await expectVisible(review);
      assert.deepEqual(
        await review.locator(".review-row strong").allInnerTexts(),
        rows.map((zone) => `Zone ${zone} scheduling`),
      );
      await axe(`every zone: ${title}`);
      await review.getByRole("button", { name: `Apply ${rows.length} changes` }).click();
      await review.waitFor({ state: "hidden" });
      assert.equal(await count.innerText(), after);
    };
    assert.equal(await all.getAttribute("aria-checked"), "true");
    assert.equal(await count.innerText(), "2 of 3 zones on");
    await flip("Pause every zone", [1, 2], "0 of 3 zones on");
    assert.equal(await all.getAttribute("aria-checked"), "false");
    await flip("Switch every zone on", [1, 2, 3], "3 of 3 zones on");
    assert.equal(await all.getAttribute("aria-checked"), "true");
    await page.setViewportSize({ width: 390, height: 844 });
    await noOverflow();
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check("settings: water today per plant is the room's choice", async () => {
    await go("settings");
    const choice = page.getByRole("group", { name: "Water today, shown as", exact: true });
    const pressed = (name) =>
      choice.getByRole("button", { name, exact: true }).getAttribute("aria-pressed");
    assert.equal(await pressed("Zone total"), "true");
    await choice.getByRole("button", { name: "Per plant", exact: true }).click();
    await page.waitForFunction(() =>
      [...document.querySelectorAll(".water-view-options button")].some(
        (button) =>
          button.textContent.trim() === "Per plant" &&
          button.getAttribute("aria-pressed") === "true",
      ),
    );
    await axe("settings: water per plant");
    // The choice is Flower 2's: Flower 1 keeps each zone's total.
    await page.locator("#desktop-room").selectOption("room:f1_");
    await page.waitForTimeout(300);
    assert.equal(await pressed("Zone total"), "true");
    await page.locator("#desktop-room").selectOption("room:");
    await page.waitForTimeout(300);
    assert.equal(await pressed("Per plant"), "true");
    // A zone's page leads with each plant's share, the zone's litres under it.
    await page.evaluate(() => (location.hash = "#/zone/1"));
    const water = page.locator(".zone-numbers > div", { hasText: "Water today" });
    await expectVisible(water);
    assert.match(await water.innerText(), /^Water today\s+\d+ mL\/plant\s+[\d.]+ L in the zone/);
    await page.evaluate(() => (location.hash = "#/settings"));
    await choice.getByRole("button", { name: "Zone total", exact: true }).click();
  });
  await check(
    "notifications: a checkbox per phone and kind, saved through the review, a test push, others' phones read-only; only notify_save and notify_test are sent",
    async () => {
      const table = page.locator("table.notify-table");
      const rows = table.locator("tbody tr");
      const box = (name, on = page) => on.getByRole("checkbox", { name, exact: true });
      const rooms = (name) => page.getByRole("group", { name: `${name}: rooms`, exact: true });
      const ticked = (service) =>
        page
          .locator(`tr[data-notify-row="${service}"] input[data-kind]`)
          .evaluateAll((boxes) =>
            boxes.filter((item) => item.checked).map((item) => item.dataset.kind),
          );
      const review = page.getByRole("dialog", { name: "Save notifications?" });
      const saveDraft = () => page.getByRole("button", { name: /^Review and save/ }).click();
      const discard = () =>
        page.getByRole("button", { name: "Discard draft", exact: true }).click();
      await go("settings/notifications");
      await expectVisible(table);
      // The demo's saved setup: Ben everything, Callum hardware lockouts, stock tanks and dosing,
      // Stewart emergencies only; a column per kind, in the order notify_get gives them.
      assert.equal(await rows.count(), 3);
      assert.deepEqual(await table.locator("tbody .notify-phone-name").allInnerTexts(), [
        "Ben",
        "Callum",
        "Stewart",
      ]);
      assert.deepEqual(await table.locator("thead [data-kind]").allInnerTexts(), [
        "Emergencies",
        "Hardware lockouts",
        "Sensors and drift",
        "Watering stopped",
        "Phase changes",
        "Stock tanks",
        "Dosing",
        "Jev",
        "Setup and settings",
      ]);
      assert.equal((await ticked("notify.mobile_app_s23ultra")).length, 9);
      assert.deepEqual(await ticked("notify.mobile_app_callum_phone"), [
        "hardware",
        "stock",
        "dosing",
      ]);
      assert.deepEqual(await ticked("notify.mobile_app_stews_iphone"), ["emergency"]);
      assert.equal(await page.locator("[data-uncovered]").count(), 0);
      // A heading says what its kind covers: its codes with Help's titles, its events in words.
      await table.getByRole("button", { name: "Hardware lockouts", exact: true }).click();
      const covers = page.getByRole("dialog", { name: "Hardware lockouts" });
      await expectVisible(covers);
      assert.match(await covers.innerText(), /CS-301\s+CRITICAL hardware fault, watering stopped/);
      assert.match(await covers.innerText(), /CS-701\s+Water isn't reaching this zone/);
      await axe("notifications: what a kind covers");
      await page.keyboard.press("Escape");
      await covers.waitFor({ state: "hidden" });
      await table.getByRole("button", { name: "Phase changes", exact: true }).click();
      assert.match(
        await page.getByRole("dialog", { name: "Phase changes" }).innerText(),
        /A zone changing phase, as a push/,
      );
      await page.keyboard.press("Escape");
      // Callum ticks Phase changes and keeps to Flower 1: a draft, reviewed phone by phone, saved.
      await box("Callum (Callum Phone): Phase changes").check();
      await rooms("Callum (Callum Phone)").getByRole("button", { name: "Flower 1" }).click();
      await expectVisible(page.locator(".draft-bar", { hasText: "Unsaved changes to 1 phone" }));
      await saveDraft();
      await expectVisible(review);
      assert.deepEqual(await review.locator(".review-row").allInnerTexts(), [
        "Callum (Callum Phone)\nStarts getting: Phase changes\nRooms: All rooms → Flower 1",
      ]);
      await axe("notifications: the review");
      await review.getByRole("button", { name: "Save notifications", exact: true }).click();
      await review.waitFor({ state: "hidden" });
      await expectVisible(page.getByText("Saved as revision 4. The next push follows it."));
      assert.equal(await box("Callum (Callum Phone): Phase changes").isChecked(), true);
      assert.equal(await page.locator(".draft-bar").count(), 0);
      // A test push, its answer beside the button.
      await page
        .getByRole("button", { name: "Send a test to Stewart (Stews iPhone)", exact: true })
        .click();
      await expectVisible(
        page.locator(
          'tr[data-notify-row="notify.mobile_app_stews_iphone"] [data-test-result="sent"]',
        ),
      );
      // A room nobody gets emergencies for is named above the grid.
      await box("Ben (S23Ultra): Emergencies").uncheck();
      await rooms("Stewart (Stews iPhone)").getByRole("button", { name: "Flower 2" }).click();
      assert.deepEqual(await page.locator("[data-uncovered] strong").allInnerTexts(), [
        "Nobody gets emergencies for Flower 1",
      ]);
      await box("Stewart (Stews iPhone): Emergencies").uncheck();
      assert.deepEqual(await page.locator("[data-uncovered] strong").allInnerTexts(), [
        "Nobody gets emergencies for Flower 2",
        "Nobody gets emergencies for Flower 1",
      ]);
      await discard();
      assert.equal(await page.locator("[data-uncovered]").count(), 0);
      // Add a phone from the site's phones not listed yet; it starts with Emergencies ticked.
      await page.getByRole("button", { name: "Add a phone", exact: true }).click();
      const add = page.getByRole("dialog", { name: "Add a phone" });
      await expectVisible(add);
      assert.deepEqual(await add.locator(".notify-add-choice strong").allInnerTexts(), [
        "Sean (Sean iPhone)",
        "Pete (Pete)",
        "A notify service by its name",
      ]);
      await axe("notifications: add a phone");
      await add.getByRole("button", { name: "Add", exact: true }).click();
      await add.waitFor({ state: "hidden" });
      assert.deepEqual(await ticked("notify.mobile_app_sean_iphone"), ["emergency"]);
      assert.equal(
        await page.evaluate(() => document.activeElement?.getAttribute("aria-label")),
        "Sean (Sean iPhone): Emergencies",
        "focus carries on from the new row's first tick",
      );
      await page
        .getByRole("button", { name: "Remove Stewart (Stews iPhone)", exact: true })
        .click();
      assert.equal(await rows.count(), 3);
      await saveDraft();
      assert.deepEqual(await review.locator(".review-row > strong").allInnerTexts(), [
        "Sean (Sean iPhone) · added",
        "Stewart (Stews iPhone) · removed",
      ]);
      await review.getByRole("button", { name: "Back to editing", exact: true }).click();
      await review.waitFor({ state: "hidden" });
      await discard();
      // Both themes, and a phone: a card per phone with the same checkboxes.
      await inBothThemes("notifications", async () => {
        await go("settings/notifications");
        await expectVisible(table);
      });
      await go("settings/notifications");
      await expectVisible(table);
      await page.screenshot({
        path: path.join(out, "dashboard-notifications-light.png"),
        fullPage: true,
      });
      await page.evaluate(() => localStorage.setItem("irrigation-theme", "dark"));
      await page.reload({ waitUntil: "networkidle" });
      await expectVisible(table);
      await page.screenshot({
        path: path.join(out, "dashboard-notifications-dark.png"),
        fullPage: true,
      });
      await page.evaluate(() => localStorage.setItem("irrigation-theme", "light"));
      await page.reload({ waitUntil: "networkidle" });
      await page.setViewportSize({ width: 390, height: 844 });
      const cards = page.locator("[data-notify-card]");
      await expectVisible(cards.first());
      assert.equal(await cards.count(), 3);
      assert.equal(await table.isVisible(), false);
      assert.equal(await cards.first().locator("input[data-kind]").count(), 9);
      await noOverflow();
      await page.screenshot({ path: path.join(out, "mobile-notifications.png"), fullPage: true });
      await box("Callum (Callum Phone): Jev").check();
      await expectVisible(page.locator(".draft-bar"));
      await noOverflow();
      await axe("notifications on a phone");
      await discard();
      await page.setViewportSize({ width: 1440, height: 1000 });
      // Callum, who is not an administrator (the demo as him): his own phone's row, nothing else.
      await page.goto(`${base}/dashboard.html?demo&notify-user=callum#/settings/notifications`, {
        waitUntil: "networkidle",
      });
      await expectVisible(table);
      await expectVisible(
        page.locator("[data-readonly-note]", {
          hasText: "Only an administrator can change other people's phones.",
        }),
      );
      for (const name of ["Ben (S23Ultra)", "Stewart (Stews iPhone)"]) {
        assert.equal(await box(`${name}: Emergencies`).isDisabled(), true, `${name} is read-only`);
        assert.equal(await box(`${name}: High priority for emergencies`).isDisabled(), true);
        assert.equal(
          await page.getByRole("button", { name: `Send a test to ${name}` }).isDisabled(),
          true,
        );
      }
      assert.equal(await page.getByRole("button", { name: "Add a phone" }).count(), 0);
      assert.equal(await page.getByRole("button", { name: /^Remove / }).count(), 0);
      assert.equal(
        await page.getByLabel("Tell me when a room has watered nothing for").isDisabled(),
        true,
      );
      await box("Callum (Callum Phone): Emergencies").check();
      await saveDraft();
      await review.getByRole("button", { name: "Save notifications", exact: true }).click();
      await expectVisible(page.getByText("Saved as revision 4. The next push follows it."));
      await axe("notifications, not an administrator");
      await page.screenshot({
        path: path.join(out, "dashboard-notifications-not-admin.png"),
        fullPage: true,
      });

      // Against Home Assistant: read with notify_get, save with notify_save through the review,
      // test with notify_test, and nothing else.
      const ha = await browser.newContext({
        viewport: { width: 1440, height: 1000 },
        reducedMotion: "reduce",
      });
      const posts = [];
      const stamp = () => new Date().toISOString();
      const fixture = {};
      for (const [prefix, name] of [
        ["", "Flower 2"],
        ["f1_", "Flower 1"],
      ]) {
        const flag = `switch.crop_steering_${prefix}engine_enabled`;
        for (const [entity_id, state, attributes] of [
          [
            `sensor.crop_steering_${prefix}engine_config`,
            "ready",
            { prefix, num_zones: 1, friendly_name: `${name} engine config`, enable_flag: flag },
          ],
          [flag, "on", {}],
        ])
          fixture[entity_id] = {
            entity_id,
            state,
            attributes,
            last_changed: stamp(),
            last_updated: stamp(),
          };
      }
      const pixel = {
        service: "notify.mobile_app_pixel_7",
        name: "Pixel 7",
        user_id: "u-callum",
        kinds: ["stock"],
        rooms: [],
        urgent_high_priority: false,
      };
      const iphone = {
        service: "notify.mobile_app_iphone",
        name: "iPhone",
        user_id: "u-ben",
        kinds: ["emergency"],
        rooms: ["f1_"],
        urgent_high_priority: true,
      };
      let saved = { revision: 7, idle_hours: 3, recipients: [pixel, iphone] };
      // The first save meets one made elsewhere meanwhile: Ben's phone now covers every room.
      let elsewhere = true;
      const answer = () => ({
        schema_version: 1,
        config: saved,
        kinds: [
          { id: "emergency", name: "Emergencies", detail: "", codes: ["CS-301"], events: [] },
          { id: "stock", name: "Stock tanks", detail: "", codes: ["CS-608"], events: [] },
          { id: "phases", name: "Phase changes", detail: "", codes: [], events: ["phase"] },
        ],
        phones: [
          { service: pixel.service, name: "Pixel 7", user_id: "u-callum", user_name: "Callum" },
          { service: iphone.service, name: "iPhone", user_id: "u-ben", user_name: "Ben" },
        ],
        can_edit_all: true,
        user_id: "u-ben",
      });
      await ha.route("**/*", async (route) => {
        const request = route.request(),
          url = new URL(request.url());
        if (url.origin !== base) return route.abort();
        if (!url.pathname.startsWith("/api/")) return route.continue();
        const reply = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
        if (url.pathname === "/api/states") return reply(Object.values(fixture));
        if (url.pathname.startsWith("/api/states/")) {
          const entity = fixture[decodeURIComponent(url.pathname.slice(12))];
          return entity ? reply(entity) : reply({}, 404);
        }
        if (request.method() !== "POST") return reply([]);
        const body = request.postDataJSON() ?? {};
        posts.push({ path: url.pathname, body });
        if (url.pathname === "/api/services/crop_steering/notify_get")
          return reply({ service_response: answer() });
        if (url.pathname === "/api/services/crop_steering/notify_test")
          return reply({ service_response: { sent: true } });
        if (url.pathname !== "/api/services/crop_steering/notify_save")
          return reply({ message: "Not a notification service" }, 400);
        if (elsewhere) {
          elsewhere = false;
          saved = { ...saved, revision: 8, recipients: [pixel, { ...iphone, rooms: [] }] };
          return reply({ service_response: { error: "revision" } });
        }
        saved = {
          revision: saved.revision + 1,
          idle_hours: body.idle_hours,
          recipients: body.recipients,
        };
        return reply({ service_response: answer() });
      });
      const live = await ha.newPage();
      live.on("pageerror", (error) => pageErrors.push(error.message));
      await live.goto(`${base}/dashboard.html?room=room:#/settings/notifications`, {
        waitUntil: "networkidle",
      });
      const grid = live.locator("table.notify-table");
      await expectVisible(grid);
      assert.deepEqual(await grid.locator("tbody .notify-phone-name").allInnerTexts(), [
        "Callum",
        "Ben",
      ]);
      await box("Callum (Pixel 7): Phase changes", live).check();
      await live.getByLabel("Tell me when a room has watered nothing for").fill("4");
      await live.getByRole("button", { name: /^Review and save/ }).click();
      const liveReview = live.getByRole("dialog", { name: "Save notifications?" });
      const liveSave = liveReview.getByRole("button", { name: "Save notifications", exact: true });
      await liveSave.click();
      // Saved elsewhere meanwhile: read again with this draft kept on top, and said so.
      await expectVisible(liveReview.getByText(/^Someone else saved the notifications meanwhile/));
      await liveSave.click();
      await liveReview.waitFor({ state: "hidden" });
      await expectVisible(live.getByText("Saved as revision 9. The next push follows it."));
      const callum = { ...pixel, kinds: ["stock", "phases"] };
      assert.deepEqual(
        posts.filter((post) => post.path.endsWith("/notify_save")).map((post) => post.body),
        [
          { expected_revision: 7, recipients: [callum, iphone], idle_hours: 4 },
          { expected_revision: 8, recipients: [callum, { ...iphone, rooms: [] }], idle_hours: 4 },
        ],
      );
      await live.getByRole("button", { name: "Send a test to Ben (iPhone)", exact: true }).click();
      await expectVisible(
        live.locator(`tr[data-notify-row="${iphone.service}"] [data-test-result="sent"]`),
      );
      // Besides its reads (notify_get, and What's new on opening), that is all the page sent.
      assert.deepEqual(
        posts
          .map((post) => post.path)
          .filter((path) => !/\/crop_steering\/(notify_get|whats_new_get)$/.test(path)),
        [
          "/api/services/crop_steering/notify_save",
          "/api/services/crop_steering/notify_save",
          "/api/services/crop_steering/notify_test",
        ],
      );
      assert.deepEqual(posts.at(-1).body, { service: iphone.service });
      await ha.close();
    },
  );
  await check(
    "what's new: once after an update, on a desktop and a phone, and from Help",
    async () => {
      const dialog = page.getByRole("dialog", { name: "What’s new in Crop Steering", exact: true });
      const versions = () => dialog.locator("section h3").allInnerTexts();
      // Every other check opens the demo as a new installation: nothing to catch up on.
      await go("today");
      await page.waitForTimeout(300);
      assert.equal(await dialog.count(), 0, "a new installation shows no What's new");
      // Updated from 2.22.0: the releases since, newest first, in both themes.
      const updated = async () => {
        await page.goto(`${base}/dashboard.html?demo&whats-new=2.22.0#/today`, {
          waitUntil: "networkidle",
        });
        await expectVisible(dialog);
      };
      await inBothThemes("what's new", updated);
      await updated();
      assert.deepEqual(
        (await versions()).map((text) => text.split("\n")[0]),
        ["Version 2.24.0", "Version 2.23.0"],
      );
      assert.equal(
        await dialog.getByRole("link", { name: /Full release notes/ }).getAttribute("href"),
        "https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/releases/tag/v2.24.0",
      );
      await page.screenshot({ path: path.join(out, "whats-new-desktop.png") });
      await dialog.getByRole("button", { name: "Got it", exact: true }).click();
      await dialog.waitFor({ state: "hidden" });
      await page.evaluate(() => (location.hash = "#/plan/targets")); // another page, same visit
      await page.waitForTimeout(300);
      assert.equal(await dialog.count(), 0, "shown once, not on every page");
      // A phone, where it cannot know what was shown: the last 30 days, inside the screen with a
      // margin, the list scrolling and both buttons in reach.
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`${base}/dashboard.html?demo&whats-new=unknown#/today`, {
        waitUntil: "networkidle",
      });
      await expectVisible(dialog);
      assert.equal((await versions()).length, 4, "2.21.0 to 2.24.0, all within 30 days");
      const fit = await dialog.evaluate((box) => {
        const outer = box.getBoundingClientRect();
        const list = box.querySelector(".whats-new-releases");
        const reach = [...box.querySelectorAll(".whats-new-actions > *")].map((item) => {
          const rect = item.getBoundingClientRect();
          return rect.top >= 0 && rect.bottom <= innerHeight;
        });
        return {
          margins: Math.min(outer.left, innerWidth - outer.right),
          inside: outer.top >= 0 && outer.bottom <= innerHeight,
          scrolls: list.scrollHeight > list.clientHeight,
          reach,
        };
      });
      assert.ok(fit.margins >= 16, `${fit.margins}px from the screen's edge`);
      assert.ok(fit.inside, "the window fits the screen");
      assert.ok(fit.scrolls, "the releases scroll inside the window");
      assert.deepEqual(fit.reach, [true, true], "Got it and the release notes stay in reach");
      await axe("what's new on a phone");
      await noOverflow();
      await page.screenshot({ path: path.join(out, "whats-new-phone.png") });
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "hidden" });
      await page.setViewportSize({ width: 1440, height: 1000 });
      // Help opens it again at any time, whatever the window has shown.
      await go("help");
      await page.getByRole("button", { name: "What’s new", exact: true }).click();
      await expectVisible(dialog);
      assert.equal((await versions()).length, 4);
      await dialog.getByRole("button", { name: "Got it", exact: true }).click();
      await dialog.waitFor({ state: "hidden" });
    },
  );
  await check("help: every error code is listed, searchable and linkable", async () => {
    const catalog = JSON.parse(await readFile(path.join(root, "docs/error-codes.json"), "utf8"));
    await go("help");
    await expectVisible(page.getByRole("heading", { name: "Error codes", exact: true }));
    const codes = page.locator("details.error-code");
    assert.deepEqual(
      await codes.evaluateAll((all) => all.map((d) => d.id)),
      catalog.codes.map((entry) => entry.code.toLowerCase()),
      "Help must list exactly the codes in docs/error-codes.json",
    );
    const search = page.getByRole("textbox", { name: "Search error codes" });
    await search.fill("101");
    assert.equal(await codes.count(), 1);
    const found = page.locator("details#cs-101");
    assert.equal(await found.getAttribute("open"), "", "A code typed in full opens by itself");
    await expectVisible(found.getByText("Likely causes", { exact: true }));
    await expectVisible(found.getByText(/No plant in the cube/));
    await search.fill("zqxw vjqk"); // words in no code (real words turn up as the catalog grows)
    await expectVisible(page.getByText(/No code matches/));
    await page.goto(`${base}/dashboard.html?demo&room=f2#/help?code=CS-605`, {
      waitUntil: "networkidle",
    });
    await expectVisible(page.locator("details#cs-605[open]"));
    assert.equal(await search.inputValue(), "CS-605");
    await search.fill("");
    await codes.evaluateAll((all) => all.forEach((d) => (d.open = true)));
    await noOverflow();
    await axe("help error codes, all open");
    await axeDark("help error codes, all open", ".error-codes");
    await page.screenshot({
      path: path.join(out, "dashboard-help-error-codes.png"),
      fullPage: true,
    });
  });
  await check("help: a short glossary, and no daily routine or workflow links", async () => {
    await go("help");
    const terms = await page.locator(".glossary dt").allInnerTexts();
    for (const term of [
      "VWC (moisture)",
      "Pore EC",
      "Dryback",
      "P0 · Morning dryback",
      "P1 · Ramp-up",
      "P2 · Maintenance",
      "P3 · Overnight dryback",
    ])
      assert.ok(terms.includes(term), `the glossary has ${term}`);
    for (const gone of ["ol.daily-routine", ".specialist-links", ".help-note"])
      assert.equal(await page.locator(gone).count(), 0, `no ${gone}`);
  });
  await check("dark theme persists and remains accessible", async () => {
    await go("settings");
    await page.getByRole("button", { name: "Dark", exact: true }).click();
    assert.equal(await page.locator("html").evaluate((el) => el.classList.contains("dark")), true);
    await page.reload({ waitUntil: "networkidle" });
    assert.equal(await page.locator("html").evaluate((el) => el.classList.contains("dark")), true);
    await axe("dark settings");
    await page.screenshot({
      path: path.join(out, "dashboard-dark.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Light", exact: true }).click();
  });
  await check("keyboard skip retains page and browser history works", async () => {
    await go("today");
    await page.getByRole("link", { name: "Skip to content" }).focus();
    await page.keyboard.press("Enter");
    await expectVisible(page.getByRole("heading", { name: "Flower 2 today", exact: true }));
    assert.equal(await page.evaluate(() => document.activeElement?.id), "main-content");
    assert.match(page.url(), /#\/today$/);
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Equipment", exact: true })
      .click();
    await expectVisible(page.getByRole("heading", { name: "Probes", exact: true }));
    await page.goBack();
    await expectVisible(page.getByRole("heading", { name: "Flower 2 today", exact: true }));
    await page.goForward();
    await expectVisible(page.getByRole("heading", { name: "Probes", exact: true }));
  });
  await check("mobile navigation and every page fit 390px", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await go("today");
    await page.getByRole("button", { name: "Open navigation" }).click();
    await axe("mobile navigation");
    const mobileMenu = page.getByRole("dialog");
    const entries = await mobileMenu.getByRole("button").allInnerTexts();
    assert.deepEqual(
      entries.filter((text) => text !== "Close"),
      ["Today", "Plan", "History", "Equipment", "Settings & help"],
    );
    await mobileMenu.getByRole("button", { name: "Plan", exact: true }).click();
    await expectVisible(page.getByRole("heading", { name: "Targets", exact: true }));
    const views = page.getByRole("navigation", { name: "Plan views" });
    await views.getByRole("button", { name: "Schedule", exact: true }).click();
    await expectVisible(page.getByRole("heading", { name: "Schedule", exact: true }));
    await noOverflow();
    for (const [route, heading] of routes) {
      await go(route);
      await expectVisible(page.getByRole("heading", { name: heading, exact: true }));
      if (sectionOf(route)) await tabsShareRow(sectionOf(route));
      await noOverflow();
      await page.screenshot({
        path: path.join(out, `mobile-${route.replace("/", "-")}.png`),
        fullPage: true,
      });
    }
    await axe("mobile help");
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  assert.deepEqual(forbidden, [], "Demo attempted live API or external CDN requests");
  assert.deepEqual(pageErrors, [], "Browser JavaScript exceptions");
  console.log(`PASS ${checks.length} workflow groups; no runtime CDN/API calls in demo.`);
} catch (error) {
  await page.screenshot({ path: path.join(out, "failure.png"), fullPage: true }).catch(() => {});
  await writeFile(path.join(out, "failure.txt"), String(error.stack));
  console.error(error);
  process.exitCode = 1;
} finally {
  await writeFile(
    path.join(out, "verification.json"),
    JSON.stringify({ checks, pageErrors, forbidden, accessibility, tabLayouts }, null, 2),
  );
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
