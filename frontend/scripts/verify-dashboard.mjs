/** Browser contracts against the compiled artifact. API traffic is fixture-only. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
/** Grow plan & presets arms at the room's next lights-on and names it (I4). */
const ARM_PLAN = /^Arm at (lights-on, \w{3} \d{1,2}:\d{2}( [ap]m)?|next lights-on)$/;

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
    const body = await readFile(file);
    res.writeHead(200, { "Content-Type": type, "Cache-Control": "no-store" });
    res.end(body);
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
let reachedCheck = !process.env.DASHBOARD_CHECK_FROM;
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
context.setDefaultTimeout(10_000);
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
  if (!reachedCheck) reachedCheck = name.includes(process.env.DASHBOARD_CHECK_FROM);
  if (!reachedCheck) return;
  await run();
  checks.push(name);
  console.log(`PASS ${name}`);
}
async function go(route, room = "f2") {
  await page.goto(`${base}/dashboard.html?demo&room=${room}#/${route}`, {
    waitUntil: "networkidle",
  });
}
/** Opens a page from the tree menu: its section opened first if it is closed. */
async function openFromMenu(menu, section, label) {
  const head = menu.locator(`button[data-nav-section="${section}"]`);
  if ((await head.getAttribute("aria-expanded")) === "false") await head.click();
  await menu.getByRole("link", { name: label, exact: true }).click();
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
    .getByRole("navigation", { name: `${section} pages` })
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
  if (page.url() === "about:blank") await go("today");
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => localStorage.setItem("irrigation-theme", value), theme);
    await page.reload({ waitUntil: "networkidle" });
    await open();
    assert.equal(
      await page.evaluate(() => document.documentElement.classList.contains("dark")),
      theme === "dark",
    );
    // Let the reopened view reach its next paint before measuring.
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
    // An old bookmark opens the overview across all rooms.
    await page.goto(`${base}/index.html?demo&room=room_b#/zones`);
    await expectVisible(page.getByRole("heading", { name: "All rooms", exact: true }));
    assert.match(page.url(), /dashboard\.html\?demo=&room=room_b#\/all-zones$/);
    assert.equal(
      await page.locator('.desktop-sidebar .room-tree-row[data-selected]').getAttribute("data-room"),
      "room:room_b_",
    );
  });
  await check("default view persists while explicit links retain their destination", async () => {
    await page.goto(`${base}/dashboard.html?demo&room=f2`, { waitUntil: "networkidle" });
    await expectVisible(page.getByRole("heading", { name: "All rooms", exact: true, level: 1 }));
    await go("settings");
    const landing = page.getByLabel("Landing page", { exact: true });
    assert.equal(await landing.inputValue(), "all-zones");
    await landing.selectOption("plan/schedule");
    await page.reload({ waitUntil: "networkidle" });
    assert.equal(await landing.inputValue(), "plan/schedule");
    await page.goto(`${base}/dashboard.html?demo&room=room_b`, { waitUntil: "networkidle" });
    await expectVisible(page.getByRole("heading", { name: "Irrigation", exact: true }));
    assert.equal(await page.locator(".irrigation-workspace").getAttribute("data-view"), "calendar");
    assert.equal(
      await page.locator('.desktop-sidebar .room-tree-row[data-selected]').getAttribute("data-room"),
      "room:room_b_",
    );
    await go("today");
    await expectVisible(page.getByRole("heading", { name: "Room A", exact: true, level: 1 }));
    await page.goto(`${base}/dashboard.html?demo&room=f2&view=logs`, { waitUntil: "networkidle" });
    await expectVisible(page.getByRole("heading", { name: "Explorer", exact: true }));
    await go("settings");
    await landing.selectOption("all-zones");
  });
  await check("every old address lands where its content lives now", async () => {
    const moved = [
      ["overview", "today", "Room A"],
      ["zones", "all-zones", "All rooms"],
      ["strategy", "plan/targets", "Irrigation"],
      ["grow-plan", "plan/schedule", "Irrigation"],
      ["compare", "history/compare", "Compare runs"],
      ["insights", "equipment/probes", "Probes"],
      ["activity", "history/explorer", "Explorer"],
      ["sensors", "equipment/probes", "Probes"],
      ["stock", "equipment/stock", "Stock tanks"],
      ["setup", "equipment/setup", "Rooms and setup"],
      ["plan", "plan/watering", "Timeline"],
      ["history", "history/explorer", "Explorer"],
      ["history/timeline", "history/explorer", "Explorer"],
      ["equipment/feed", "equipment/dosing", "Dosing"],
      ["equipment", "equipment/probes", "Probes"],
    ];
    for (const [old, now, heading] of moved) {
      await go(old);
      await expectVisible(page.getByRole("heading", { name: heading, exact: true, level: 1 }));
      assert.equal(new URL(page.url()).hash, `#/${now}`, `#/${old} lands on #/${now}`);
    }
    // A Help link keeps its code; a retired single-page dashboard's ?view= opens its new home.
    await go("help?code=CS-605");
    await expectVisible(page.locator("details#cs-605[open]"));
    await page.goto(`${base}/dashboard.html?demo&room=f2&view=logs`, { waitUntil: "networkidle" });
    await expectVisible(page.getByRole("heading", { name: "Explorer", exact: true }));
    // Rewritten in place: Back returns to the page before, not to the old address.
    await go("today");
    const before = await page.evaluate(() => history.length);
    await page.evaluate(() => (location.hash = "#/sensors"));
    await expectVisible(page.getByRole("heading", { name: "Probes", exact: true }));
    assert.equal(new URL(page.url()).hash, "#/equipment/probes");
    assert.equal(await page.evaluate(() => history.length), before + 1);
    await page.goBack();
    await expectVisible(page.getByRole("heading", { name: "Room A", exact: true, level: 1 }));
  });
  const routes = [
    ["all-zones", "All rooms"],
    ["today", "Room A"],
    ["zone/1", "Zone 1"],
    ["today/ai", "AI assistant"],
    ["plan/targets", "Irrigation"],
    ["plan/schedule", "Irrigation"],
    ["plan/watering", "Timeline"],
    ["plan/timers", "Timer programs"],
    ["history/explorer", "Explorer"],
    ["history/water", "Water use"],
    ["history/compare", "Compare runs"],
    ["history/changes", "Changes"],
    ["equipment/probes", "Probes"],
    ["equipment/stock", "Stock tanks"],
    ["equipment/dosing", "Dosing"],
    ["equipment/pump-calibration", "Pump calibration"],
    ["equipment/feed-calibration", "Feed pH/EC calibration"],
    ["equipment/setup", "Rooms and setup"],
    ["settings", "Settings"],
    ["settings/alerts", "Alert rules"],
    ["settings/features", "Capabilities"],
    ["settings/notifications", "Notifications"],
    ["settings/system", "System status"],
    ["settings/ai", "AI assistant"],
    ["help", "Help"],
  ];
  const sectionOf = (route) =>
    ({
      plan: "Irrigation",
      history: "History",
      equipment: "Equipment",
      settings: "Settings",
      help: "Settings",
    })[route.split("/")[0]];
  for (const [route, heading] of routes)
    await check(`${route}: render, desktop layout and accessibility`, async () => {
      await go(route);
      await expectVisible(page.getByRole("heading", { name: heading, exact: true, level: 1 }));
      // A heading carries a sentence only for a behaviour someone could get wrong.
      if (!route.startsWith("plan/") && !["all-zones", "settings/features"].includes(route))
        assert.equal(
          await page.locator(".page-heading > div > p").count(),
          0,
          `${route}: the heading repeats itself in a description`,
        );
      // The tree menu lists every page on a desktop: the in-page tabs stay hidden.
      assert.equal(await page.locator(".page-tabs").isVisible(), false, `${route}: tabs hidden`);
      await noOverflow();
      await axe(route);
      await page.screenshot({
        path: path.join(out, `dashboard-${route.replace("/", "-")}.png`),
        fullPage: true,
      });
    });
  await check(
    "the menu: five sections as a tree, and a page's views with working history",
    async () => {
      await go("today");
      const menu = page.getByRole("navigation", { name: "Main navigation" });
      assert.deepEqual(await menu.locator("[data-nav-section]").allInnerTexts(), [
        "Status",
        "Irrigation",
        "History",
        "Equipment",
        "Settings",
      ]);
      await openFromMenu(menu, "plan", "Current day");
      await expectVisible(page.getByRole("heading", { name: "Irrigation", exact: true }));
      const views = page.getByRole("navigation", { name: "Irrigation views" });
      const targets = views.getByRole("button", { name: "Current day", exact: true });
      const schedule = views.getByRole("button", { name: "Calendar", exact: true });
      assert.equal(await targets.getAttribute("aria-current"), "page");
      await schedule.click();
      await expectVisible(page.getByRole("heading", { name: "Irrigation", exact: true }));
      assert.equal(new URL(page.url()).hash, "#/plan/targets");
      assert.equal(await schedule.getAttribute("aria-current"), "page");
      assert.equal(
        await menu.locator('[data-nav-page="plan/targets"]').getAttribute("aria-current"),
        "page",
      );
      await targets.click();
      assert.equal(await targets.getAttribute("aria-current"), "page");
      await openFromMenu(menu, "history", "Explorer");
      await page.goBack();
      await expectVisible(page.getByRole("heading", { name: "Irrigation", exact: true }));
      await page.goForward();
      await expectVisible(page.getByRole("heading", { name: "Explorer", exact: true }));
    },
  );
  await check(
    "the header: each room's state, the data's age and the two safety switches",
    async () => {
      await go("today");
      // On a desktop the menu's room tree is the room picker; the header chips step aside.
      assert.ok(!(await page.locator(".topbar .room-chips").isVisible()), "chips hidden");
      const rooms = page.locator(".desktop-sidebar .room-tree-room");
      assert.equal(await rooms.count(), 2, "one tree entry per room");
      const chip = (id) =>
        page.locator(`.desktop-sidebar .room-tree-room[data-room="${id}"] > button`).first();
      assert.equal(await chip("room:").getAttribute("aria-current"), "page");
      assert.match(await chip("room:").innerText(), /Room A\s+Watering/);
      assert.match(await page.locator(".data-age").innerText(), /^Updated \d+ (s|min) ago$/);
      await expectVisible(page.getByRole("button", { name: "Recent activity", exact: true }));
      assert.equal(await page.locator(".stale-banner").count(), 0, "a reporting room has no band");
      const switches = page.getByRole("group", { name: "Room A safety switches" });
      await expectVisible(
        switches.getByRole("button", { name: "Watering on: switch watering off…", exact: true }),
      );
      assert.equal(
        await switches
          .getByRole("button", { name: "Room on: switch room off…", exact: true })
          .count(),
        0,
      );

      // The breadcrumb, the status strip and the demo banner are gone.
      for (const gone of [".breadcrumb", ".status-line", ".demo-banner"])
        assert.equal(await page.locator(gone).count(), 0, `no ${gone}`);
      // Another room's chip opens it.
      await chip("room:room_b_").click();
      await expectVisible(page.getByRole("heading", { name: "Room B", exact: true, level: 1 }));
      assert.equal(await chip("room:room_b_").getAttribute("aria-current"), "page");
      // Watering switched off from the header, through its review.
      await page
        .getByRole("button", { name: "Watering on: switch watering off…", exact: true })
        .click();
      const review = page.getByRole("dialog", { name: "Review the kill switch" });
      await expectVisible(review);
      // The review says, before the values, that the kill switch is no emergency stop.
      const warning = review.getByRole("note").filter({ hasText: /^WARNING:/ });
      await expectVisible(warning);
      assert.match(
        await warning.innerText(),
        /^WARNING: Do not use this switch as an emergency stop\. Use the physical shut-off/,
      );
      await expectVisible(review.getByRole("note").filter({ hasText: /^CAUTION:/ }));
      await axe("header: watering review");
      await review.getByRole("button", { name: /Apply 1 change/ }).click();
      await review.waitFor({ state: "hidden" });
      await expectVisible(page.getByRole("button", { name: /^Watering off: switch watering on/ }));
    },
  );
  await check("today: a room not watering says why and uses the header control", async () => {
    await go("today", "room_b");
    await page.getByRole("button", { name: /^Watering on: switch watering off/ }).click();
    await page.getByRole("button", { name: /Apply \d+ change/ }).click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("link", { name: "Status", exact: true })
      .click();
    // The Status tabs give way to the room tree on a desktop; open the room page directly.
    await page.evaluate(() => {
      location.hash = "#/today";
    });
    await expectVisible(page.getByRole("heading", { name: "Room B", exact: true, level: 1 }));
    const stopped = page.locator(".today-stopped");
    assert.match(
      await stopped.innerText(),
      /Not watering\. The kill switch \(Watering\) of this room is off/,
    );
    assert.match(
      await page.locator('.desktop-sidebar .room-tree-row[data-room="room:room_b_"]').innerText(),
      /Not watering/,
    );
    // The room's own line says it is not watering, beside the header control that says why.
    assert.match(await page.locator("[data-today-sub]").innerText(), /^Not watering/);
    assert.equal(
      await stopped.getByRole("button", { name: "Switch it on in Settings", exact: true }).count(),
      0,
    );
    assert.match(await stopped.innerText(), /Use Watering in the header/);
    await page.getByRole("button", { name: /^Watering off: switch watering on/ }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /Apply 1 change/ })
      .click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    assert.equal(await stopped.count(), 0);
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
    await expectVisible(page.getByRole("heading", { name: "Explorer", exact: true }));
    assert.equal(await page.getByRole("dialog").count(), 0, "the panel closes when the log opens");
  });
  await check("today: a laptop view says which zone needs you and why, in place", async () => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await go("today");
    const rows = page.locator("article.today-zone");
    await expectVisible(rows.first());
    assert.equal(await rows.count(), 3, "one row per zone");
    // Today's shots are in before the page is measured: a track per zone.
    const tracks = page.locator('[data-today-strip] .st-row[data-kind="zone"]');
    await tracks.first().waitFor();
    assert.equal(await tracks.count(), 3, "a strip track per zone");
    // The header, today's strip and every zone row within 1.35 windows; the plan line and the AI
    // assistant's card follow.
    const bottom = await rows.last().evaluate((el) => el.getBoundingClientRect().bottom + scrollY);
    assert.ok(bottom <= 900 * 1.35, `the zone rows end ${bottom}px down a 900px window`);
    // The whole page: measured 1357px at 1440 x 900 with the demo, plus 10%.
    const whole = await page.evaluate(() => document.documentElement.scrollHeight);
    assert.ok(whole <= 1357 * 1.1, `Today is ${whole}px tall in a 900px window`);
    // The room: state, stage and plants; the grow day and its stage's end; water, lights, climate.
    assert.match(
      await page.locator("[data-today-sub]").innerText(),
      /^\S.* · Flower bulk · \d+ plants in 3 zones$/,
    );
    assert.match(
      await page.locator("[data-today-day]").innerText(),
      /^Day 38 of 63 · 25 days left · harvest \d{1,2} [A-Z][a-z]{2}$/,
    );
    assert.equal(await page.locator(".today-run-mark").innerText(), "Flower bulk ends day 49");
    const line = await page.locator("[data-today-line]").innerText();
    for (const part of [/Water today\s+[\d.]+ L room · [\d.]+ L per watered plant/, /Lights\s+O(n|ff) /, /Air \(reading\)/, /RH/, /VPD/])
      assert.match(line, part, `the room's line: ${line}`);
    // Each row: VWC, dryback and pore EC against their targets, water against the room's median,
    // and its sensors.
    for (const index of [0, 1, 2]) {
      const row = rows.nth(index);
      assert.equal(await row.locator(".today-gauge").count(), 3);
      assert.match(await row.locator(".today-gauge").nth(0).innerText(), /^VWC\s+target [\d.]+–[\d.]+%\s+[\d.]+%(\s*, [\d.]+ points (under|over))?$/);
      assert.match(await row.locator(".today-gauge").nth(2).innerText(), /^Pore EC\s+target 3\.5–6(\.0)?\s+[\d.]+(\s*, [\d.]+ mS\/cm (under|over))?$/);
      assert.match(await row.locator("[data-today-delta]").innerText(), /^[+−±]\d+ mL vs median \d+ mL$/);
      assert.equal(await row.locator(".today-sensors li").count(), 2, "front and back sensors");
    }
    // Problems in place: zone 1's pore EC under the stage's band on its gauge; zone 3's back EC
    // probe on its sensor, which says since when and what the zone reads; zone 2 quiet.
    assert.equal(await rows.nth(0).locator(".today-gauge").nth(2).getAttribute("data-state"), "abnormal");
    const back = rows.nth(2).locator('.today-sensors li[data-sensor="Back"]');
    assert.match(await back.locator(".today-sensor-reading").innerText(), /^silent \d+ h$/);
    assert.match(
      await back.locator(".today-sensor-note").innerText(),
      /^Last heard \S.*\. Left out: the zone reads the front sensor only\.$/,
    );
    assert.equal(await rows.nth(1).getAttribute("data-attention"), null);
    assert.equal(await rows.nth(1).locator("[data-today-problem], .today-sensor-note").count(), 0);
    // The AI assistant's changes are not repeated here, nor the zones as a table.
    assert.equal(await page.locator("[data-jev-today], [data-today-table]").count(), 0);
    // A row opens its zone.
    await rows.nth(1).getByRole("link", { name: "Zone 2" }).click();
    await expectVisible(page.getByRole("heading", { name: "Zone 2", exact: true }));
    assert.equal(new URL(page.url()).hash, "#/zone/2");
    // The strip opens the full timeline; the AI assistant's card opens its page.
    await go("today");
    await page.locator("[data-today-strip]").getByRole("button", { name: "Open full timeline" }).click();
    await expectVisible(page.getByRole("heading", { name: "Timeline", exact: true, level: 1 }));
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check("today: a phone keeps the room, the strip and each zone in one column, in both themes", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    const strip = '[data-today-strip] .st-row[data-kind="zone"]';
    await inBothThemes("today on a phone", async () => {
      await go("today");
      await page.locator(strip).first().waitFor();
    });
    await go("today");
    await page.locator(strip).first().waitFor();
    await page.locator("[data-plan-feed]").waitFor();
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    // The bottom section bar is fixed chrome; the page pads itself clear of it. Each zone row
    // carries its sensors in place, so the page is 2.85 phone screens at most (measured 2317px).
    const bar = await page.evaluate(() => document.querySelector(".bottom-nav")?.getBoundingClientRect().height ?? 0);
    assert.ok(height - bar <= 2.85 * 844, `Today is ${height}px tall on a 844px phone`);
    // Each zone row fits a screen, one column wide.
    const rows = await page.locator("article.today-zone").evaluateAll((all) =>
      all.map((row) => row.getBoundingClientRect()),
    );
    assert.equal(rows.length, 3);
    for (const row of rows) assert.ok(row.height <= 844 && row.right <= 390, `a zone row is ${row.height}px tall`);
    await noOverflow();
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check("today: every display option on keeps a compact laptop and phone view", async () => {
    // Settings › Display: each option turned on at once (the demo's ?display=all).
    const open = async () => {
      await page.goto(`${base}/dashboard.html?demo&room=f2&display=all#/today`, {
        waitUntil: "networkidle",
      });
      await page.locator('[data-today-strip] .st-row[data-kind="zone"]').first().waitFor();
      await page.locator("[data-plan-feed]").waitFor();
    };
    await page.setViewportSize({ width: 1440, height: 900 });
    await open();
    // The tank readout joins the room's line; the zone rows still end within 1.35 windows.
    await expectVisible(page.locator("[data-today-tank]"));
    const bottom = await page
      .locator("article.today-zone")
      .last()
      .evaluate((el) => el.getBoundingClientRect().bottom + scrollY);
    assert.ok(bottom <= 900 * 1.35, `with every option on the zone rows end ${bottom}px down`);
    await page.setViewportSize({ width: 390, height: 844 });
    await open();
    const phone = await page.evaluate(() => document.documentElement.scrollHeight);
    // The bottom section bar is fixed chrome; the page pads itself clear of it.
    const bar = await page.evaluate(() => document.querySelector(".bottom-nav")?.getBoundingClientRect().height ?? 0);
    assert.ok(phone - bar <= 3 * 844 + 64, `Today with every option on is ${phone}px tall on a phone`);
    await noOverflow();
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check(
    "today: the header owns the grow day; the plan line keeps the grow plan and the feed recipe",
    async () => {
      await go("today");
      // The day once, in the header, with its run bar; no second run strip.
      await expectVisible(page.locator("[data-today-run]"));
      assert.match(await page.locator("[data-today-day]").innerText(), /^Day 38 of 63 /);
      assert.equal(await page.locator("[data-run-figure], .run-bar").count(), 0);
      assert.equal(await page.getByText(/^Day\s+\d+ of \d+$/).count(), 0, "no second day count");
      const strip = page.locator("[data-plan-feed]");
      await expectVisible(strip);
      const recipe = (name) => strip.locator(`[data-run-recipe="${name}"]`).innerText();
      assert.match(await recipe("plan"), /^Grow plan\s+Unnamed plan · Draft$/);
      assert.match(await recipe("feed"), /^Feed\s+Bloom · week 3 of 12 · EC 2\.4 mS\/cm$/);
      // The stage is the header's.
      assert.equal(await strip.locator('[data-run-recipe="stage"]').count(), 0);
      // A tooltip on each, on keyboard focus too.
      await strip.locator('[data-run-recipe="feed"]').focus();
      assert.match(
        await page.getByRole("tooltip").innerText(),
        /^The batch tank mixes this feed recipe today\. The feed schedule selects this recipe for this week\./,
      );
      await page.keyboard.press("Escape");
      await page.evaluate(() => document.activeElement?.blur());
      await strip.screenshot({ path: path.join(out, "run-progress-desktop.png") });
      await axe("today plan line", "[data-plan-feed]");
      await axeDark("today plan line", "[data-plan-feed]");
      // At 375px the header's run bar and the plan line stay on the screen.
      await page.setViewportSize({ width: 375, height: 812 });
      await go("today");
      await expectVisible(strip);
      await noOverflow();
      const box = await page.locator("[data-today-run]").boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= 375, "the run bar fits a 375px screen");
      await strip.screenshot({ path: path.join(out, "run-progress-mobile.png") });
      await page.setViewportSize({ width: 1440, height: 1000 });
      // Run records have one owner in History.
      await go("history/grows");
      const ongoing = page.locator(".comparison-run-list article", { hasText: "Ongoing" });
      await ongoing.getByRole("button", { name: "Archive" }).click();
      // An archived run leaves the list.
      await ongoing.waitFor({ state: "detached" });
      // The room page's plan line does not depend on a run.
      await go("today");
      await expectVisible(page.locator("[data-plan-feed]"));
      assert.match(await recipe("plan"), /^Grow plan\s+Unnamed plan · Draft$/);
    },
  );
  await check(
    "zone page: the day as a phase reference chart, fitted to today, against yesterday or the last run",
    async () => {
      await go("zone/1");
      const day = page.locator("[data-day-timeline]");
      const layer = (name) => day.locator(`[data-layer="${name}"]`);
      // The earlier days load after today's: yesterday's line is the last to arrive.
      await expectVisible(layer("yesterday"));
      for (const name of ["vwc", "ec", "fc", "runoff", "maintenance", "projected", "shots", "jev"])
        assert.equal(await layer(name).count(), 1, `the ${name} layer is drawn`);
      // Today: a status line and four gauges, each against its target (VWC now, the peak, the
      // overnight dryback, pore EC against the stage's band); then water and each plant's share,
      // and shots.
      await expectVisible(day.locator(".zone-numbers-wrap [data-hmi-status]"));
      assert.equal(await day.locator(".zone-numbers-wrap [data-gauge]").count(), 4);
      const speech = (id) => day.locator(`[data-gauge="${id}"]`).getAttribute("aria-label");
      assert.match(await speech("vwc"), /^VWC now [\d.]+%, /);
      assert.match(await speech("peak"), /^Peak today [\d.]+%, target [\d.]+%, /);
      assert.match(
        await speech("dryback"),
        /dryback (no reading|[\d.]+%), target [\d.]+%.*, reference [\d.]+% to [\d.]+%$/,
      );
      assert.match(await speech("pore-ec"), /^Pore EC 2\.8, band 3\.5 to 6, 0\.7 mS\/cm under$/);
      assert.equal(
        await day.locator('[data-gauge="pore-ec"]').getAttribute("data-state"),
        "abnormal",
      );
      const numbers = await day.locator(".zone-numbers").innerText();
      for (const part of [
        /Water today\s+[\d.]+ L\s+\d+ mL\/plant\s+\d+% of the 40 L limit/,
        /Shots\s+\d+\s+last /,
      ])
        assert.match(numbers, part);
      assert.match(await day.locator(".zone-next").innerText(), /^Next: \S/);
      // The VWC axis fits today and the zone's targets: never 14-91 %.
      const ticks = (await day.locator(".grow-svg .axis-label").allTextContents())
        .filter((text) => text.endsWith("%"))
        .map(Number.parseFloat);
      assert.ok(ticks.length >= 3, `VWC gridlines: ${ticks}`);
      assert.ok(Math.max(...ticks) - Math.min(...ticks) <= 30, `VWC axis ${ticks}`);
      // Phases along the bottom as badges, every one there was today.
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
      const readings = day.getByRole("combobox", { name: "Readings" });
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
      // Compare with Off, Yesterday, the last run's day of the same number (mockup 04) or Typical.
      const compare = day.getByRole("group", { name: "Compare with" });
      const choice = (name) => compare.getByRole("button", { name, exact: true });
      await choice("Typical").click();
      await expectVisible(layer("typical"));
      assert.ok(
        (await layer("typical").locator(".typical-band").getAttribute("d")).length > 100,
        "the typical day is a p25-p75 band",
      );
      assert.equal(await layer("yesterday").count(), 0);
      // Off takes the typical day away again, as it was drawn a moment ago.
      await choice("Off").click();
      assert.equal(await layer("typical").count(), 0);
      assert.equal(await layer("yesterday").count(), 0);
      // The choices are remembered in the browser.
      await page.reload({ waitUntil: "networkidle" });
      await expectVisible(day.locator(".grow-svg"));
      assert.equal(await choice("Off").getAttribute("aria-pressed"), "true");
      assert.equal(await ecKey.getAttribute("aria-pressed"), "false");
      assert.equal(await layer("ec").count(), 0);
      await ecKey.click();
      await expectVisible(layer("ec"));
      await choice("Yesterday").click();
      await expectVisible(layer("yesterday"));
      await axe("zone day", "[data-day-timeline]");
      await axeDark("zone day", "[data-day-timeline]");
      await day.locator(".zone-day-chart").screenshot({ path: path.join(out, "dashboard-zone-day.png") });
    },
  );
  await check("zone page: why, the AI, the controls, and the rest on request", async () => {
    await go("zone/3");
    // Why this zone is doing this: the controller's reason from its decision record, always there.
    const why = page.locator("[data-zone-why]");
    await expectVisible(why);
    assert.match(await why.locator(".zone-reasons").innerText(), /Holding — within target band/);
    // The valve's normal state is a neutral word, never red.
    assert.deepEqual(
      (await pillTones(".zone-page-title .pill")).find(([text]) => text.startsWith("Valve")),
      ["Valve closed", "neutral"],
    );
    // Targets and probes stay closed until asked for; the 24 h chart is gone.
    assert.equal(await page.locator(".zone-targets, .zone-probes").count(), 0);
    assert.equal(await page.getByRole("group", { name: "History range" }).count(), 0);
    // The AI on this zone: what it may move and within what range, and its latest decisions.
    await page.getByText("AI proposals, applied changes and outcomes", { exact: true }).click();
    const jev = page.locator("[data-zone-jev]");
    await expectVisible(jev);
    assert.match(
      await jev.locator(".zone-jev-setpoints").innerText(),
      /^The AI assistant can change the P2 shot size 3\.5–5\.5% \(yours 4\.5%, now 4%\) and re-water point 59–62% \(yours 61%\)\. Last change /,
    );
    const decisions = jev.getByRole("list", { name: "Last AI assistant decisions" });
    assert.ok((await decisions.locator("li").count()) > 0);
    // Probes: each one of the zone's reading, zone 3's back EC probe left out.
    await page.getByText("Probes used and not used", { exact: true }).click();
    const probes = page.locator(".zone-probes .zone-probe-list li");
    await expectVisible(probes.first());
    assert.equal(await probes.count(), 4);
    assert.deepEqual((await pillTones(".zone-probes .pill")).at(-1), [
      "Silent 3 h, left out of the zone's reading",
      "warn",
    ]);
    // Targets, read only, with the AI assistant's ranges where it manages them.
    await page.getByText("Targets (read only)", { exact: true }).click();
    const targets = page.locator(".zone-targets");
    await expectVisible(targets);
    assert.deepEqual(await targets.locator(".jev-chip").allInnerTexts(), [
      "AI assistant · 59–62 %",
      "AI assistant · 3.5–5.5 %",
    ]);
    // Pause scheduling, through its review.
    const controls = page.locator(".zone-controls");
    await controls.getByRole("button", { name: "Pause zone scheduling" }).click();
    const review = page.getByRole("dialog", { name: "Review zone switch" });
    await expectVisible(review);
    await review.getByRole("button", { name: /Apply 1 change/ }).click();
    await review.waitFor({ state: "hidden" });
    await expectVisible(controls.getByRole("button", { name: "Enable zone scheduling" }));
    await expectVisible(page.locator(".zone-page-title").getByText("Scheduling paused"));
    // The switcher moves between zones; Edit in Plan opens this zone's targets.
    await page
      .locator(".desktop-sidebar .room-tree-room:has(.room-tree-row[data-selected])")
      .locator(".room-tree-zone", { hasText: "Zone 2" })
      .click();
    await expectVisible(page.getByRole("heading", { name: "Zone 2", exact: true }));
    await page.getByText("Targets (read only)", { exact: true }).click();
    await page.getByRole("button", { name: "Edit in Plan" }).click();
    await expectVisible(page.getByRole("heading", { name: "Irrigation", exact: true }));
    assert.equal(await page.locator("#irrigation-zone").inputValue(), "2");
    await go("zone/3");
    await axe("zone page, lower half", ".zone-page-stack");
    await axeDark("zone page, lower half", ".zone-page-stack");
    await axe("zone page, why", "[data-zone-why]");
    await axeDark("zone page, why", "[data-zone-why]");
  });
  await check(
    "zone page: an AI change goes back by itself, or is kept or undone through the review",
    async () => {
      for (const [button, title] of [
        ["Keep", "Keep the AI's change?"],
        ["Undo", "Undo the AI's change?"],
      ]) {
        // A fresh demo each time: the first pass's Keep has ended its overlay.
        await go("zone/3");
        await page.reload({ waitUntil: "networkidle" });
        await page.getByText("AI proposals, applied changes and outcomes", { exact: true }).click();
        const row = page.locator("[data-zone-jev] .overlay-rows li");
        await expectVisible(row);
        assert.match(
          await row.innerText(),
          /^Maintenance shot size 4\.5% → 4%\s*Set by AI .+ · goes back at lights-on /,
        );
        await row.getByRole("button", { name: button, exact: true }).click();
        const review = page.getByRole("dialog", { name: title });
        await expectVisible(review);
        assert.match(await review.locator(".review-row").innerText(), /4% \(AI\)/);
        await review.getByRole("button", { name: /Apply 1 change/ }).click();
        await review.waitFor({ state: "hidden" });
        await row.waitFor({ state: "detached" });
      }
    },
  );
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
    await move("P1 · Ramp", "P2 · Maintenance");
    await axe("zone phase picker");
    await move("P2 · Maintenance", "P1 · Ramp");
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
    "targets: a setting's ? explains it in STE (what, impact, guidance), in both themes, and closes on Escape",
    async () => {
      const trigger = () => page.getByRole("button", { name: "About Re-water point", exact: true });
      const help = () => page.getByRole("dialog", { name: "Re-water point" });
      await inBothThemes("setting explainer", async () => {
        await go("plan/targets");
        await trigger().click();
        await expectVisible(help());
        const text = await help().innerText();
        for (const part of ["Impact:", "Guidance:"])
          assert.match(text, new RegExp(part, "i"), `the explainer has "${part}"`);
        assert.match(text, /it gives a shot when VWC is below this value/);
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
        ["P0 Morning dryback", "P1 Ramp", "P2 Maintenance", "P3 Overnight dryback"],
      );
      const chips = await table.locator(".jev-chip").allInnerTexts();
      assert.deepEqual(chips, ["AI assistant · 59–62 %", "AI assistant · 3–5 %"]);
      // With the AI assistant's Setpoints judge on the room, the Auto switch says what it lets the AI assistant do.
      await expectVisible(page.getByText("AI assistant: P2 shot size, re-water point"));
      // Nothing is written until it is reviewed and applied in the bar.
      await expectVisible(page.getByText("Nothing is sent to the controller until you apply"));
      // The steering select says what the mode does, with the zone's own overnight dryback.
      assert.match(
        await page.locator(".targets-consequence").innerText(),
        /^Vegetative: wetter nights \(\d+(\.\d+)? % down from the peak\) and pore EC kept lower\./,
      );
      // The other mode's numbers sit beside the ones in use, muted, instead of one tap down.
      assert.deepEqual(await table.locator("thead th").allInnerTexts(), [
        "Setting",
        "Vegetative · in use",
        "Generative",
        "Ranges",
      ]);
      const other = await table
        .locator('tr[data-setting$="dryback_target"] .targets-other')
        .innerText();
      assert.match(other, /^\d+(\.\d+)? % of peak$/, "the generative dryback is shown");
      assert.equal(await page.locator("details.targets-more").count(), 0);
      // Switching the draft mode moves the in-use column; the stepper and sentence follow.
      const steering = page.locator(
        'select[id="choice-select.crop_steering_zone_1_steering_mode"]',
      );
      await steering.selectOption("Generative");
      assert.match(
        await page.locator(".targets-consequence").innerText(),
        /^Generative: drier nights/,
      );
      assert.equal(
        Number(await table.locator('tr[data-setting$="dryback_target"] input').inputValue()),
        Number(other.split(" ")[0]),
      );
      await steering.selectOption("Vegetative");
      assert.equal(
        await page.locator(".review-apply[data-pending]").count(),
        0,
        "switching back leaves no draft",
      );
      // The hardware is in Setup.
      assert.equal(
        await page
          .locator('input[id="setting-number.crop_steering_zone_1_substrate_volume"]')
          .count(),
        0,
        "substrate is set up in Equipment",
      );
      await page.getByRole("button", { name: "Equipment › Setup" }).click();
      await expectVisible(page.getByRole("heading", { name: "Rooms and setup", exact: true }));
    },
  );
  await check("targets: a draft survives refresh, validates, reviews and applies", async () => {
    await go("plan/targets");
    const field = page.locator('input[id="setting-number.crop_steering_zone_1_p1_target_vwc"]');
    const original = Number(await field.inputValue());
    await field.fill("999");
    await expectVisible(page.locator('[id="note-number.crop_steering_zone_1_p1_target_vwc"]'));
    await expectVisible(page.getByText("Fix the red check to apply"));
    assert.equal(
      await page.getByRole("button", { name: /^Apply \d+ changes?$/ }).count(),
      0,
      "an invalid draft has no Apply",
    );
    await field.fill(String(original + 1));
    await page.getByRole("button", { name: "Refresh controller data" }).click();
    assert.equal(await field.inputValue(), String(original + 1));
    // The Current day entry counts the unsaved change.
    assert.match(
      await page
        .getByRole("navigation", { name: "Main navigation" })
        .locator('[data-nav-page="plan/targets"]')
        .innerText(),
      /1$/,
    );
    const bar = page.getByRole("region", { name: "Review and apply" });
    await expectVisible(bar.getByText("1 change · Review & apply"));
    // The change is the selected room's only.
    await expectVisible(bar.getByText("These changes affect Room A only."));
    await axe("targets review");
    await page.screenshot({ path: path.join(out, "dashboard-review.png") });
    await bar.getByRole("button", { name: "Apply 1 change", exact: true }).click();
    await expectVisible(bar.getByText(/^Written and read back \d\d:\d\d$/));
    assert.equal(await field.inputValue(), String(original + 1));
    await field.fill(String(original + 2));
    await page.locator('.desktop-sidebar .room-tree-row[data-room="room:room_b_"]').click();
    await expectVisible(
      page.getByRole("heading", {
        name: "Discard unsaved workspace changes?",
      }),
    );
    await page.getByRole("button", { name: "Keep editing" }).click();
    assert.equal(await field.inputValue(), String(original + 2));
    await page.locator('.desktop-sidebar .room-tree-row[data-room="room:room_b_"]').click();
    await page.getByRole("button", { name: "Discard and continue" }).click();
    assert.equal(
      await page.locator('.desktop-sidebar .room-tree-row[data-selected]').getAttribute("data-room"),
      "room:room_b_",
    );
    await expectVisible(
      page.locator('input[id="setting-number.crop_steering_room_b_zone_1_p1_target_vwc"]'),
    );
  });
  await check(
    "schedule: the flower by stage, today marked, and when the next one starts",
    async () => {
      await go("plan/schedule");
      const workspace = page.locator(".irrigation-workspace");
      assert.equal(await workspace.getAttribute("data-view"), "calendar");
      assert.equal(await page.locator("#irrigation-zone").inputValue(), "1");
      await expectVisible(page.locator(".irrigation-canvas .planning-curve"));
      assert.equal(
        await page.locator(".irrigation-canvas .planning-curve").count(),
        1,
        "one shared planning canvas",
      );
      const guide = page.locator("details.irrigation-stage-guide");
      assert.equal(await guide.getAttribute("open"), null);
      await guide.locator("summary").click();
      assert.equal(await page.locator(".grow-stage-table tbody tr").count(), 3);
      const current = page.locator(".grow-stage-table tr[data-current]");
      assert.match(await current.innerText(), /^Flower bulk\s+Now \u00b7 week 6/);
      assert.match(
        await current.innerText(),
        /Vegetative\s+3\.5\u20136 mS\/cm\s+10\u201315 points of true water content/,
      );
      assert.match(
        await page.locator(".grow-stages .panel-heading p").innerText(),
        /^Flower day 37 of 56, week 6: flower bulk, steered vegetative\. Finish from .+ \(day 43\)\.$/,
      );
      assert.equal(await page.locator(".grow-weeks li[aria-current]").innerText(), "W6");
      // Validate and arm stay in view; the balance grid, endpoints and recipes are one tap down.
      await expectVisible(page.getByRole("button", { name: "Validate preview" }));
      await expectVisible(page.getByRole("button", { name: ARM_PLAN }));
      const advanced = page.locator("details.plan-advanced");
      if ((await advanced.getAttribute("open")) === null) await advanced.locator("summary").click();
      const tabs = page.getByRole("tablist", { name: "Grow planner view" });
      assert.deepEqual(await tabs.getByRole("tab").allInnerTexts(), [
        "Steering balance",
        "Endpoint profiles",
        "Recipes",
      ]);
      await expectVisible(page.getByRole("region", { name: "Grow schedule" }));
      assert.equal(await page.locator(".irrigation-canvas .planning-curve").count(), 1);
      await axe("schedule, advanced open");
    },
  );
  await check("explorer: the room's charts under its phase and shot lanes, chips and CSV export", async () => {
    await go("history/explorer");
    const explorer = page.locator("[data-room-explorer]");
    await expectVisible(explorer);
    await page.waitForFunction(
      () => Number(document.querySelector("[data-room-explorer]")?.dataset.explorerLoads) > 0,
      null,
      { timeout: 20_000 },
    );
    // The lanes and the charts: every zone's VWC and EC, the feed EC and the tank level.
    await expectVisible(page.locator("[data-phase-lane] [data-phase]").first());
    assert.deepEqual(await page.locator("[data-chart]").evaluateAll((all) => all.map((el) => el.dataset.chart)), [
      "VWC",
      "Pore EC",
      "Feed EC",
      "Tank level",
    ]);
    // The old list, its filters and the setpoint log are gone: changes live on History › Changes.
    assert.equal(await page.locator(".timeline-row").count(), 0);
    // A chip adds its chart; the export counts what is charted.
    const exportButton = page.locator("[data-export-csv]");
    assert.equal((await exportButton.innerText()).trim(), "Export CSV · 8 series");
    await page.getByRole("button", { name: "Room VPD", exact: true }).click();
    await expectVisible(page.locator('[data-chart="VPD"]'));
    assert.equal((await exportButton.innerText()).trim(), "Export CSV · 9 series");
    await page.getByRole("button", { name: "Room VPD", exact: true }).click();
    await inBothThemes("explorer", async () => {
      await go("history/explorer");
      await expectVisible(page.locator("[data-chart]").first());
    });
    // Room B: the same page on its own zones.
    await go("history/explorer", "room_b");
    await expectVisible(page.locator('[data-chart="VWC"]'));
    await go("history/explorer");
    await page.waitForFunction(
      () => Number(document.querySelector("[data-room-explorer]")?.dataset.explorerLoads) > 0,
      null,
      { timeout: 20_000 },
    );
    const downloadPromise = page.waitForEvent("download");
    await exportButton.click();
    const download = await downloadPromise;
    assert.match(download.suggestedFilename(), /room-a-explorer-.+\.csv/);
    await download.saveAs(path.join(out, "explorer-export.csv"));
    const csv = await readFile(path.join(out, "explorer-export.csv"), "utf8");
    assert.match(csv, /^\uFEFF?Time,Zone 1 VWC \(%\),Zone 1 Pore EC \(mS\/cm\),/);
  });
  await check("a zone page's history opens the explorer on that zone", async () => {
    await go("zone/2");
    await page.getByRole("button", { name: "Explore recorded history and comparisons" }).click();
    await expectVisible(page.getByRole("heading", { name: "Explorer", exact: true }));
    await expectVisible(page.locator('[data-zone-detail="2"] [data-history-explorer]'));
    assert.match(await page.locator(".explorer-lane-name").first().innerText(), /Zone 2/i);
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
        const [zone, today, perPlant, week, since, estimate] = await rows
          .nth(index)
          .locator("td")
          .allInnerTexts();
        assert.match(zone, new RegExp(`Zone ${index + 1}`));
        assert.match(perPlant, /[\d.]+ mL\n÷ \d+ current configured plants/);
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
      await panel.getByRole("button", { name: "About this week" }).focus();
      await expectVisible(panel.getByRole("tooltip", { name: /grow week/ }));
      assert.match(await rows.first().locator("td").nth(2).innerText(), /147\.2 mL/);
      assert.equal(
        await page.getByRole("region", { name: "Daily water by zone" }).count(),
        0,
        "daily water has one table",
      );
      await axe("water use");
      await axeDark("water use", ".wu-panel");
      await page.screenshot({ path: path.join(out, "dashboard-water-use.png"), fullPage: true });
    },
  );
  await check(
    "compare runs: by grow week, the biggest differences, the overlay toggle, the detail one tap down",
    async () => {
      await go("history/compare");
      // The run in progress against the latest ended one, chosen to start with.
      assert.match(
        await page.getByLabel("Current run").locator("option:checked").innerText(),
        /^Demo • current run/,
      );
      assert.match(
        await page.getByLabel("Past run").locator("option:checked").innerText(),
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
      // Charted by grow week: both runs on each measure's chart, with data, at desktop and phone width.
      const charts = page.locator(".rw-charts [data-rw-chart]");
      const plotted = async () => {
        assert.deepEqual(
          await charts.evaluateAll((figures) => figures.map((figure) => figure.dataset.rwChart)),
          ["moisture", "dryback", "pore-ec", "water", "shots"],
        );
        for (const id of ["moisture", "pore-ec", "water", "shots"]) {
          const chart = page.locator(`[data-rw-chart="${id}"]`);
          await expectVisible(chart.locator(".recharts-line-curve").first());
          const lines = await chart
            .locator(".recharts-line-curve")
            .evaluateAll(
              (paths) => paths.filter((path) => /\d/.test(path.getAttribute("d") || "")).length,
            );
          // Two runs: a peak and a trough line each for moisture and pore EC, one line each otherwise.
          assert.equal(
            lines,
            ["moisture", "pore-ec"].includes(id) ? 4 : 2,
            `${id} plots both runs`,
          );
          assert.match(
            await chart.locator('[role="img"]').getAttribute("aria-label"),
            /by grow week\. Demo • current run[^:]*: \d+ weeks? recorded.* Demo • previous run[^:]*: \d+ weeks recorded/,
          );
        }
        const bars = page.locator('[data-rw-chart="dryback"] .recharts-bar-rectangle path');
        await expectVisible(bars.first());
        assert.ok((await bars.count()) >= 4, "dryback bars for both runs");
        for (const figure of await charts.all()) {
          const box = await figure.boundingBox();
          assert.ok(box && box.width > 200 && box.height > 150, "each chart has room to read");
          const plot = await figure.locator(".rw-chart-plot").boundingBox();
          assert.ok(plot && plot.height >= 150, "each plot is drawn");
        }
        assert.equal(
          await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
          true,
          "the page itself never scrolls sideways",
        );
      };
      await plotted();
      await page
        .locator(".rw-charts")
        .screenshot({ path: path.join(out, "compare-runs-charts-1440.png") });
      await page.setViewportSize({ width: 390, height: 844 });
      await plotted();
      // Stacked, one chart per row.
      const [first, second] = await charts.evaluateAll((figures) =>
        figures.slice(0, 2).map((figure) => figure.getBoundingClientRect().top),
      );
      assert.ok(second > first, "the charts stack at phone width");
      // A chart is a keyboard stop that scrolls sideways when its weeks need more room.
      await page.locator('[data-rw-chart="moisture"] .rw-chart-scroll').focus();
      assert.equal(
        await page.evaluate(() => document.activeElement?.getAttribute("aria-label")),
        "Moisture chart",
      );
      await page
        .locator(".rw-charts")
        .screenshot({ path: path.join(out, "compare-runs-charts-390.png") });
      await axe("compare runs charts, phone", ".rw-charts");
      await page.setViewportSize({ width: 1440, height: 1000 });
      // The daily ranges are collapsed; the full-resolution overlay is behind the view toggle.
      assert.equal(
        await page.locator('details.comparison-more[data-section="quality"]').getAttribute("open"),
        null,
      );
      const view = page.getByRole("group", { name: "Comparison view" });
      const byWeek = view.getByRole("button", { name: "By grow week", exact: true }),
        overlay = view.getByRole("button", { name: "Overlay", exact: true });
      assert.equal(await byWeek.getAttribute("aria-pressed"), "true");
      assert.equal(await page.locator(".comparison-chart svg").isVisible(), false);
      await overlay.click();
      assert.equal(await overlay.getAttribute("aria-pressed"), "true");
      await expectVisible(page.locator(".comparison-chart svg"));
      // Both runs on one chart, by grow age.
      for (const series of ["current-vwc", "current-ec", "previous-vwc", "previous-ec"])
        await page.locator(`[data-comparison-series="${series}"]`).first().waitFor();
      assert.equal(await weeks.first().isVisible(), false, "the weekly table steps aside");
      await axe("compare runs, overlay", ".comparison-page");
      await byWeek.click();
      await expectVisible(weeks.first());
      assert.equal(await page.locator(".comparison-chart svg").isVisible(), false);
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
      await expectVisible(page.getByRole("heading", { name: "Source of the weekly figures" }));
      await axe("compare runs, all open");
      await axeDark("compare runs", ".comparison-page");
      // The run records themselves are kept in History, Grows.
      await page.getByRole("button", { name: "Run records", exact: true }).click();
      await expectVisible(page.getByRole("heading", { name: "Grows", exact: true }));
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
      // Each zone's valve; the controller and the AI assistant at the top.
      assert.equal(await page.locator(".probes-zone [data-zone-valve]").count(), 3);
      assert.match(
        await page.locator(".probes-status").innerText(),
        /Probes\s+11 of 12 OK[\s\S]*Controller\s+Reporting[\s\S]*AI assistant\s+On/,
      );
      // The controller's own sensors: collapsed, then as the Sensors page had them.
      const internals = page.locator("details.probes-more", {
        hasText: "All sensors of this room",
      });
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
  await check("probes: the picker chooses which probes count and a primary at 390px", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await go("equipment/probes");
    const zone1 = page.locator('[data-probe-choice="1:vwc"]');
    await expectVisible(zone1);
    assert.equal(await page.locator(".probe-picker fieldset").count(), 6);
    await noOverflow();
    await zone1.getByRole("checkbox", { name: "Zone 1 back VWC" }).uncheck();
    // The last probe that counts cannot be left out too, nor one left out be the primary.
    assert.ok(await zone1.getByRole("checkbox", { name: "Zone 1 front VWC" }).isDisabled());
    const primary = (name) =>
      zone1.getByRole("radio", { name: `${name} is the primary Zone 1 moisture probe` });
    assert.ok(await primary("Zone 1 back VWC").isDisabled());
    await primary("Zone 1 front VWC").check();
    await noOverflow();
    await axe("probe picker on a phone", ".probe-picker");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expectVisible(page.getByRole("status").filter({ hasText: "Saved" }));
    const row = (id) => page.locator(`.probes-table tr[data-probe="${id}"]`);
    assert.equal(
      await row("sensor.demo_z1_back_vwc").locator("[data-probe-health]").innerText(),
      "Does not count",
    );
    await expectVisible(row("sensor.demo_z1_front_vwc").locator("[data-probe-primary]"));
    assert.match(await page.locator(".probes-status").innerText(), /Probes\s+11 of 12 OK/);
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check(
    "stock tanks: the next to run out, refill, set a level, record a batch and add a tank",
    async () => {
      await go("equipment/stock");
      const card = (id) => page.locator(`[data-stock-tank="${id}"]`);
      await expectVisible(card("part_b"));
      assert.equal(await page.locator("[data-stock-tank]").count(), 4);
      assert.equal(
        await page.locator("[data-stock-next]").innerText(),
        "Next to run out: Part B, about 3 batches left.",
      );
      await page.screenshot({ path: img("stock-tanks.png") });
      // Each tank is linked to its dosing pump: drawn by what the pump doses, its draws listed.
      assert.equal(
        await card("part_b").locator("[data-stock-drawn]").innerText(),
        "Drawn by\nPart B as it doses",
      );
      assert.match(
        await card("silica").locator("[data-stock-draws] li").first().innerText(),
        /Dose\s+25 mL$/,
      );
      // Part B starts within half again of its low mark: amber, "Getting low".
      assert.equal(await card("part_b").locator(".pill").textContent(), "Getting low");
      await card("part_b").getByRole("button", { name: "Refilled", exact: true }).click();
      await expectVisible(card("part_b").getByText("OK", { exact: true }));
      assert.match(await card("part_b").locator("dd").first().textContent(), /^20 of 20 L$/);

      await card("cleaner").getByRole("button", { name: "Set level" }).click();
      await card("cleaner").getByLabel("Tank level (L)", { exact: true }).fill("0.8");
      await card("cleaner").getByRole("button", { name: "Save level", exact: true }).click();
      await expectVisible(card("cleaner").getByText("Low", { exact: true }));

      await page.getByRole("button", { name: "Record a batch", exact: true }).click();
      const confirm = page.getByRole("dialog");
      if (await confirm.count())
        await confirm.getByRole("button", { name: "Record the batch" }).click();
      // Recent draws start collapsed.
      const history = page.locator("details.stock-history-more");
      await expectVisible(history.locator("summary"));
      assert.equal(await history.getAttribute("open"), null);
      await history.locator("summary").click();
      await expectVisible(history.getByRole("heading", { name: "Recent draws" }));
      assert.match(await card("part_b").locator("dd").first().textContent(), /^18\.2 of 20 L$/);

      await page.getByRole("button", { name: "Edit stock tanks" }).click();
      const editor = page.getByRole("dialog");
      await editor.getByRole("button", { name: "Add a stock tank" }).click();
      const names = editor.getByLabel("Name", { exact: true });
      await names.last().fill("Enzymes");
      await editor.getByRole("button", { name: "Save stock tanks" }).click();
      await expectVisible(card("enzymes"));
      // No pump draws Enzymes: each batch takes its dose.
      assert.equal(await card("enzymes").locator("[data-stock-drawn]").count(), 0);
      await expectVisible(card("enzymes").getByText("Per batch"));
      await axe("stock tanks after edits");
      await noOverflow();
    },
  );
  await check(
    "dosing: each room's pumps, a dose and a batch through their reviews, and stop; only requests are sent",
    async () => {
      // Room A's four pumps and Room B's six, one of them not calibrated yet.
      const cards = page.locator("[data-dosing-pump]");
      const strip = page.locator("[data-stock-strip]");
      const stockOf = (id) => page.locator(`[data-dosing-pump="${id}"] [data-pump-stock]`);
      await go("equipment/dosing");
      await expectVisible(cards.first());
      assert.deepEqual(await cards.locator(".dosing-pump-select").allInnerTexts(), [
        "Silica",
        "Part B",
        "Part A",
        "Line cleaner",
      ]);
      assert.match(
        await page.locator("[data-batch-line]").innerText(),
        /^No batch running · last batch finished \S/,
      );
      await go("equipment/dosing", "room_b");
      await expectVisible(cards.first());
      assert.equal(await cards.count(), 6, "one card per pump");
      assert.deepEqual(await pillTones('[data-dosing-pump="finisher"] .pill'), [
        ["Not calibrated", "warn"],
      ]);
      assert.deepEqual(await strip.locator("[data-stock-gauge] strong").allInnerTexts(), [
        "Veg base",
        "Line cleaner",
        "Silica",
        "Finisher",
        "Part A",
        "Part B",
      ]);
      // Part A, passed by in the recipe and dosed by hand: its tank lasts doses at its last one.
      assert.equal(
        await stockOf("part_a").locator(".dosing-stock-left").innerText(),
        "about 287 doses left",
      );
      // Room B's tank is filled by hand: its batch passes the fill by.
      assert.equal(
        await page.locator('.dosing-steps [data-step="fill"]').getAttribute("data-state"),
        "skipped",
      );
      await inBothThemes("dosing", async () => {
        await go("equipment/dosing");
        await expectVisible(cards.first());
      });
      // A fresh Room A: each card shows the stock tank its pump is linked to, Part B's drawn to
      // scale with its litres and the batches its recipe amount leaves, and the stock strip every
      // linked tank in pump order.
      await go("equipment/dosing");
      await expectVisible(cards.first());
      assert.equal(await stockOf("part_b").getAttribute("data-pump-stock"), "part_b");
      assert.equal(
        await stockOf("part_b").locator(".dosing-stock-litres").innerText(),
        "5.4 L of 20 L",
      );
      assert.equal(
        await stockOf("part_b").locator(".dosing-stock-left").innerText(),
        "about 3 batches left",
      );
      assert.deepEqual(await strip.locator("[data-stock-gauge] strong").allInnerTexts(), [
        "Silica",
        "Part B",
        "Part A",
        "Line cleaner",
      ]);
      // A dose of Part B, through its review: its card doses, then the history has it.
      await page.locator('[data-dosing-pump="part_b"] .dosing-pump-select').click();
      await page.getByLabel("Quantity (mL)", { exact: true }).fill("60");
      assert.match(
        await page.locator("[data-dose-summary]").innerText(),
        /^Your request: 60 mL of Part B, about 5\.7 s$/,
      );
      await page.getByRole("button", { name: /^Start Part B/ }).click();
      const review = page.getByRole("dialog", { name: "Dose Part B?" });
      await expectVisible(review);
      await axe("dosing: the dose's review");
      await review.getByRole("button", { name: "Start Part B", exact: true }).click();
      await review.waitFor({ state: "hidden" });
      await expectVisible(page.locator('[data-dosing-pump="part_b"][data-state="dosing"]'));
      await expectVisible(page.locator('[data-dosing-pump="part_b"] [role="progressbar"]'));
      await page.screenshot({ path: path.join(out, "dashboard-dosing-dose.png"), fullPage: true });
      await page.waitForFunction(
        () =>
          document
            .querySelector('tr[data-history-kind="dose"]')
            ?.textContent.includes("Part B 60 mL"),
        null,
        { timeout: 20_000 },
      );
      assert.match(
        await page.locator('tr[data-history-kind="dose"]').first().innerText(),
        /Dose Part B\s+Finished\s+Part B 60 mL/,
      );
      assert.equal(
        await page.locator('[data-dosing-pump="part_b"]').getAttribute("data-state"),
        "idle",
      );
      // What it dosed came off Part B's stock tank: 5.4 L less 60 mL, on its card and in the strip.
      await expectVisible(
        stockOf("part_b").locator(".dosing-stock-litres", { hasText: "5.3 L of 20 L" }),
      );
      assert.equal(
        await strip.locator('[data-stock-gauge="part_b"] .dosing-stock-litres').innerText(),
        "5.3 L of 20 L",
      );
      // A batch, through its review: its steps walk, and stop ends it where it is.
      await page.getByRole("button", { name: "Make a batch", exact: true }).click();
      const batch = page.getByRole("dialog", { name: "Make a batch in Room A?" });
      await expectVisible(batch);
      await axe("dosing: the batch's review");
      await batch.getByRole("button", { name: "Make the batch", exact: true }).click();
      await batch.waitFor({ state: "hidden" });
      await expectVisible(page.locator('.dosing-steps [data-step="fill"][data-state="running"]'));
      await page.getByRole("button", { name: "Stop the batch", exact: true }).click();
      const stop = page.getByRole("dialog", { name: "Stop dosing in Room A?" });
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
        [
          "",
          "Room A",
          [pump("part_b", "Part B", 10.5), pump("veg_base", "Veg base", 10.9, "unavailable")],
        ],
        ["room_b_", "Room B", []],
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
      const part_b = live.locator('[data-dosing-pump="part_b"]');
      await expectVisible(part_b);
      // No pump is linked to a stock tank here: the cards say so, and there is no stock strip.
      assert.equal(await part_b.locator("[data-pump-stock]").innerText(), "No stock tank linked");
      assert.equal(await live.locator("[data-stock-strip]").count(), 0);
      // A pump whose dosing sensor is unavailable: greyed out, a question mark on its head.
      const veg_base = live.locator('[data-dosing-pump="veg_base"]');
      assert.equal(await veg_base.getAttribute("data-state"), "unavailable");
      assert.equal(await veg_base.locator(".pp-unknown").textContent(), "?");
      await live.getByLabel("Quantity (mL)", { exact: true }).fill("60");
      await live.getByRole("button", { name: /^Start Part B/ }).click();
      await live
        .getByRole("dialog")
        .getByRole("button", { name: "Start Part B", exact: true })
        .click();
      await expectVisible(live.locator('[data-request-stage="taken"]'));
      // The controller would refuse a batch with Veg base unavailable: said before it is asked for.
      assert.equal(
        await live.locator("[data-batch-warning]").innerText(),
        "Veg base is unavailable: the controller would refuse a batch now.",
      );
      await live.getByRole("button", { name: "Make a batch", exact: true }).click();
      await live.getByRole("dialog").getByRole("button", { name: "Make the batch" }).click();
      await live.getByRole("button", { name: "Stop the batch", exact: true }).click();
      await live.getByRole("dialog").getByRole("button", { name: "Send stop" }).click();
      await expectVisible(live.locator("[data-request-stage]", { hasText: "request to stop" }));
      assert.deepEqual(
        posts.filter((post) => post.path.endsWith("/dosing_request")).map((post) => post.body),
        [
          { action: "dose", pump: "part_b", ml: 60, room_id: "room:" },
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
      await live.locator('.desktop-sidebar .room-tree-row[data-room="room:room_b_"]').click();
      await expectVisible(live.getByRole("heading", { name: "No dosing pumps in Room B" }));
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
        ["room_b", 6],
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
      await inBothThemes("dosing, Room B", async () => {
        await go("equipment/dosing", "room_b");
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
      for (const room of ["room_b", "f2"]) {
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
      ["Room on", "on"],
    ]);
  });
  await check(
    "setup: the substrate, sizing and safety numbers, each through its review",
    async () => {
      await go("equipment/setup");
      const section = page.locator(".controller-settings");
      await expectVisible(section.getByRole("heading", { name: /substrate and safety limits/ }));
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
      const catchTest = page.locator("#zone-1-catch-test");
      await catchTest.locator("summary").click();
      await catchTest.locator('input[id="zone-1-catch-test-ml"]').fill("200");
      await catchTest.locator('input[id="zone-1-catch-test-seconds"]').fill("180");
      assert.match(await catchTest.locator(".catch-test-result").innerText(), /4 L\/h/);
      await catchTest
        .getByRole("button", { name: "Use 4 L/h as Zone 1 dripper flow", exact: true })
        .click();
      assert.equal(await page.locator("#zone-1-dripper_flow_rate").inputValue(), "4");
      await expectVisible(catchTest.getByText(/Nothing is saved until you review and save/));
      await axe("setup numbers, all open", ".controller-settings");
    },
  );
  await check(
    "settings: connection status stays here and run records live under History",
    async () => {
      await inBothThemes("settings", async () => {
        await go("settings");
        await expectVisible(page.locator(".settings-section [data-connection]"));
      });
      await go("settings");
      assert.equal(await page.locator("#run-records").count(), 0);
      assert.deepEqual(await pillTones(".settings-section .pill"), [["Demo mode", "warn"]]);
      await go("history/grows");
      await expectVisible(page.locator("#run-records .pill").first());
      assert.deepEqual(await pillTones("#run-records .pill"), [
        ["Ongoing", "on"],
        ["Ended", "neutral"],
      ]);
      // The advanced-workflow links are gone: the menu has them.
      assert.equal(await page.getByRole("heading", { name: "Advanced workflows" }).count(), 0);
    },
  );
  await check("settings: one switch flips every zone, through the review", async () => {
    // Room B's zone 3 is paused for inspection: the switch is on while any zone is on, as the
    // entities card's header toggle is, and switching it on again switches zone 3 on too.
    await go("equipment/setup", "room_b");
    await page.getByRole("tab", { name: "Rooms & mappings", exact: true }).click();
    const all = page.getByRole("switch", { name: "Every zone in Room B", exact: true });
    const count = page.locator("#config-room_active .all-zones-count");
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
    const choice = page.getByRole("group", { name: "Water today display", exact: true });
    const pressed = (name) =>
      choice.getByRole("button", { name, exact: true }).getAttribute("aria-pressed");
    assert.equal(await pressed("Zone total"), "true");
    await choice.getByRole("button", { name: "For each plant", exact: true }).click();
    await page.waitForFunction(() =>
      [...document.querySelectorAll(".water-view-options button")].some(
        (button) =>
          button.textContent.trim() === "For each plant" &&
          button.getAttribute("aria-pressed") === "true",
      ),
    );
    await axe("settings: water per plant");
    // The choice is Room A's: Room B keeps each zone's total.
    await page.locator('.desktop-sidebar .room-tree-row[data-room="room:room_b_"]').click();
    await page.waitForTimeout(300);
    assert.equal(await pressed("Zone total"), "true");
    await page.locator('.desktop-sidebar .room-tree-row[data-room="room:"]').click();
    await page.waitForTimeout(300);
    assert.equal(await pressed("For each plant"), "true");
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
      // The demo's saved setup: Owner everything, Grower hardware lockouts, stock tanks and dosing,
      // Manager emergencies only; a column per kind, in the order notify_get gives them.
      assert.equal(await rows.count(), 3);
      assert.deepEqual(await table.locator("tbody .notify-phone-name").allInnerTexts(), [
        "Owner",
        "Grower",
        "Manager",
      ]);
      assert.deepEqual(await table.locator("thead [data-kind]").allInnerTexts(), [
        "Emergencies",
        "Hardware lockouts",
        "Sensors and drift",
        "Shots stopped",
        "Phase changes",
        "Vitals",
        "Stock tanks",
        "Dosing",
        "AI assistant",
        "Setup and settings",
      ]);
      assert.equal((await ticked("notify.mobile_app_phone_1")).length, 10);
      assert.deepEqual(await ticked("notify.mobile_app_phone_2"), ["hardware", "stock", "dosing"]);
      assert.deepEqual(await ticked("notify.mobile_app_phone_3"), ["emergency"]);
      assert.equal(await page.locator("[data-uncovered]").count(), 0);
      // A heading says what its kind covers: its codes with Help's titles, its events in words.
      await table.getByRole("button", { name: "Hardware lockouts", exact: true }).click();
      const covers = page.getByRole("dialog", { name: "Hardware lockouts" });
      await expectVisible(covers);
      assert.match(await covers.innerText(), /CS-301\s+Hardware fault latch/);
      assert.match(await covers.innerText(), /CS-701\s+No water at the zone/);
      await axe("notifications: what a kind covers");
      await page.keyboard.press("Escape");
      await covers.waitFor({ state: "hidden" });
      await table.getByRole("button", { name: "Phase changes", exact: true }).click();
      assert.match(
        await page.getByRole("dialog", { name: "Phase changes" }).innerText(),
        /A zone changing phase, as a push/,
      );
      await page.keyboard.press("Escape");
      // Grower ticks Phase changes and keeps to Room B: a draft, reviewed phone by phone, saved.
      await box("Grower (Phone 2): Phase changes").check();
      await rooms("Grower (Phone 2)").getByRole("button", { name: "Room B" }).click();
      await expectVisible(page.locator(".draft-bar", { hasText: "Unsaved changes to 1 phone" }));
      await saveDraft();
      await expectVisible(review);
      assert.deepEqual(await review.locator(".review-row").allInnerTexts(), [
        "Grower (Phone 2)\nNew alert kinds: Phase changes\nRooms: All rooms → Room B",
      ]);
      await axe("notifications: the review");
      await review.getByRole("button", { name: "Save notifications", exact: true }).click();
      await review.waitFor({ state: "hidden" });
      await expectVisible(page.getByText("Saved as revision 4. The next push follows it."));
      assert.equal(await box("Grower (Phone 2): Phase changes").isChecked(), true);
      assert.equal(await page.locator(".draft-bar").count(), 0);
      // A test push, its answer beside the button.
      await page
        .getByRole("button", { name: "Send a test to Manager (Phone 3)", exact: true })
        .click();
      await expectVisible(
        page.locator('tr[data-notify-row="notify.mobile_app_phone_3"] [data-test-result="sent"]'),
      );
      // A room nobody gets emergencies for is named above the grid.
      await box("Owner (Phone 1): Emergencies").uncheck();
      await rooms("Manager (Phone 3)").getByRole("button", { name: "Room A" }).click();
      assert.deepEqual(await page.locator("[data-uncovered] strong").allInnerTexts(), [
        "Nobody gets emergencies for Room B",
      ]);
      await box("Manager (Phone 3): Emergencies").uncheck();
      assert.deepEqual(await page.locator("[data-uncovered] strong").allInnerTexts(), [
        "Nobody gets emergencies for Room A",
        "Nobody gets emergencies for Room B",
      ]);
      await discard();
      assert.equal(await page.locator("[data-uncovered]").count(), 0);
      // Add a phone from the site's phones not listed yet; it starts with Emergencies ticked.
      await page.getByRole("button", { name: "Add a phone", exact: true }).click();
      const add = page.getByRole("dialog", { name: "Add a phone" });
      await expectVisible(add);
      assert.deepEqual(await add.locator(".notify-add-choice strong").allInnerTexts(), [
        "Assistant (Phone 4)",
        "Visitor (Phone 5)",
        "A notify service by its name",
      ]);
      await axe("notifications: add a phone");
      await add.getByRole("button", { name: "Add", exact: true }).click();
      await add.waitFor({ state: "hidden" });
      assert.deepEqual(await ticked("notify.mobile_app_phone_4"), ["emergency"]);
      assert.equal(
        await page.evaluate(() => document.activeElement?.getAttribute("aria-label")),
        "Assistant (Phone 4): Emergencies",
        "focus carries on from the new row's first tick",
      );
      await page.getByRole("button", { name: "Remove Manager (Phone 3)", exact: true }).click();
      assert.equal(await rows.count(), 3);
      await saveDraft();
      assert.deepEqual(await review.locator(".review-row > strong").allInnerTexts(), [
        "Assistant (Phone 4) · added",
        "Manager (Phone 3) · removed",
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
      assert.equal(await cards.first().locator("input[data-kind]").count(), 10);
      // One card per phone, its kinds as chips: a phone's whole setup fits the screen, and a tap
      // anywhere on a chip ticks it.
      for (const height of await cards.evaluateAll((all) =>
        all.map((card) => card.getBoundingClientRect().height),
      ))
        assert.ok(height <= 360, `a phone's card is ${Math.round(height)} px tall, over 360`);
      const chip = cards.first().locator(".notify-chip", { hasText: "Vitals" });
      await chip.scrollIntoViewIfNeeded();
      const chipBox = await chip.boundingBox();
      assert.ok(chipBox.height >= 30, "a chip is a finger's height");
      assert.equal(
        await chip.evaluate(
          (label) =>
            document.elementFromPoint(
              label.getBoundingClientRect().left + 6,
              label.getBoundingClientRect().top + 6,
            ) === label.querySelector("input"),
        ),
        true,
        "a chip's whole face is its checkbox",
      );
      await noOverflow();
      await page.screenshot({ path: path.join(out, "mobile-notifications.png"), fullPage: true });
      await box("Grower (Phone 2): AI assistant").check();
      await expectVisible(page.locator(".draft-bar"));
      await noOverflow();
      await axe("notifications on a phone");
      await discard();
      await page.setViewportSize({ width: 1440, height: 1000 });
      // Grower, who is not an administrator (the demo as them): their own phone's row, nothing else.
      await page.goto(`${base}/dashboard.html?demo&notify-user=grower#/settings/notifications`, {
        waitUntil: "networkidle",
      });
      await expectVisible(table);
      await expectVisible(
        page.locator("[data-readonly-note]", {
          hasText: "Only an administrator can change other people's phones.",
        }),
      );
      for (const name of ["Owner (Phone 1)", "Manager (Phone 3)"]) {
        assert.equal(await box(`${name}: Emergencies`).isDisabled(), true, `${name} is read-only`);
        assert.equal(await box(`${name}: High priority for emergencies`).isDisabled(), true);
        assert.equal(
          await page
            .getByRole("button", { name: `Send a test to ${name}`, exact: true })
            .isDisabled(),
          true,
        );
      }
      assert.equal(await page.getByRole("button", { name: "Add a phone" }).count(), 0);
      assert.equal(await page.getByRole("button", { name: /^Remove / }).count(), 0);
      assert.equal(
        await page.getByRole("spinbutton", { name: /^Alert after no shot for/ }).isDisabled(),
        true,
      );
      await box("Grower (Phone 2): Emergencies").check();
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
        ["", "Room A"],
        ["room_b_", "Room B"],
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
        user_id: "u-grower",
        kinds: ["stock"],
        rooms: [],
        urgent_high_priority: false,
      };
      const iphone = {
        service: "notify.mobile_app_iphone",
        name: "iPhone",
        user_id: "u-owner",
        kinds: ["emergency"],
        rooms: ["room_b_"],
        urgent_high_priority: true,
      };
      let saved = { revision: 7, idle_hours: 3, recipients: [pixel, iphone] };
      // The first save meets one made elsewhere meanwhile: the owner's phone now covers every room.
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
          { service: pixel.service, name: "Pixel 7", user_id: "u-grower", user_name: "Grower" },
          { service: iphone.service, name: "iPhone", user_id: "u-owner", user_name: "Owner" },
        ],
        can_edit_all: true,
        user_id: "u-owner",
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
        "Grower",
        "Owner",
      ]);
      await box("Grower (Pixel 7): Phase changes", live).check();
      await live.getByRole("spinbutton", { name: /^Alert after no shot for/ }).fill("4");
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
      await live
        .getByRole("button", { name: "Send a test to Owner (iPhone)", exact: true })
        .click();
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
      await dialog
        .locator(".whats-new-actions")
        .getByRole("button", { name: "Close", exact: true })
        .click();
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
      assert.deepEqual(fit.reach, [true, true], "Close and the release notes stay in reach");
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
      await dialog
        .locator(".whats-new-actions")
        .getByRole("button", { name: "Close", exact: true })
        .click();
      await dialog.waitFor({ state: "hidden" });
    },
  );
  await check("help: every error code is listed, searchable and linkable", async () => {
    const catalog = JSON.parse(await readFile(path.join(root, "docs/error-codes.json"), "utf8"));
    await go("help");
    await expectVisible(page.getByRole("heading", { name: "Alert codes", exact: true }));
    const codes = page.locator("details.error-code");
    assert.deepEqual(
      await codes.evaluateAll((all) => all.map((d) => d.id)),
      catalog.codes.map((entry) => entry.code.toLowerCase()),
      "Help must list exactly the codes in docs/error-codes.json",
    );
    const search = page.getByRole("textbox", { name: "Search alert codes" });
    await search.fill("101");
    assert.equal(await codes.count(), 1);
    const found = page.locator("details#cs-101");
    assert.equal(await found.getAttribute("open"), "", "A code typed in full opens by itself");
    await expectVisible(found.getByText("Probable causes", { exact: true }));
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
      "P1 · Ramp",
      "P2 · Maintenance",
      "P3 · Overnight dryback",
    ])
      assert.ok(terms.includes(term), `the glossary has ${term}`);
    for (const gone of ["ol.daily-routine", ".specialist-links", ".help-note"])
      assert.equal(await page.locator(gone).count(), 0, `no ${gone}`);
  });
  await check("reduced motion: theme text changes without transient light colours", async () => {
    await go("zone/1");
    await page.getByText("AI proposals, applied changes and outcomes", { exact: true }).click();
    await expectVisible(page.locator(".zone-jev-what strong").first());
    // Without a declared transition, CSS defaults transition-property to `all`. Giving every
    // element even a tiny duration creates staggered inherited colour transitions during themes.
    // Reduced motion must change the panel's text together with the root, in the same style flush.
    for (const dark of [false, true, false]) {
      const colours = await page.evaluate((value) => {
        document.documentElement.classList.toggle("dark", value);
        const probe = document.createElement("span");
        probe.style.color = "var(--foreground)";
        document.body.append(probe);
        const palette = getComputedStyle(probe).color;
        probe.remove();
        return {
          root: palette,
          text: getComputedStyle(document.querySelector(".zone-jev-what strong")).color,
        };
      }, dark);
      assert.equal(
        colours.text,
        colours.root,
        "theme text follows its root without a colour transition",
      );
    }
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
    await expectVisible(page.getByRole("heading", { name: "Room A", exact: true, level: 1 }));
    assert.equal(await page.evaluate(() => document.activeElement?.id), "main-content");
    assert.match(page.url(), /#\/today$/);
    await openFromMenu(
      page.getByRole("navigation", { name: "Main navigation" }),
      "equipment",
      "Probes & offsets",
    );
    await expectVisible(page.getByRole("heading", { name: "Probes", exact: true }));
    await page.goBack();
    await expectVisible(page.getByRole("heading", { name: "Room A", exact: true, level: 1 }));
    await page.goForward();
    await expectVisible(page.getByRole("heading", { name: "Probes", exact: true }));
  });
  await check("history explorer: range, any sensor, previous run, 390px", async () => {
    await go("history/explorer?zone=1");
    const explorer = page.locator("[data-history-explorer]");
    await expectVisible(explorer);
    const loads = async () => Number(await explorer.getAttribute("data-explorer-loads"));
    const loaded = async (after) =>
      page.waitForFunction(
        (count) =>
          Number(document.querySelector("[data-history-explorer]")?.dataset.explorerLoads) > count,
        after,
        { timeout: 20_000 },
      );
    await loaded(0);
    // The zone's own VWC and EC by default, over the grow-day from lights-on (10:00).
    assert.equal(await explorer.getAttribute("data-explorer-series"), "2");
    const lines = explorer.locator(
      ".recharts-line:not(.history-explorer-previous) path.recharts-curve",
    );
    assert.equal(await lines.count(), 2);
    assert.equal(
      Number(await explorer.getAttribute("data-range-start")),
      new Date(2026, 8, 28, 10, 0).getTime(),
    );
    // A range change reads the recorder again for the new range, and the address keeps it.
    const before = await loads();
    await explorer.getByRole("button", { name: "7 d", exact: true }).click();
    await loaded(before);
    assert.equal(
      Number(await explorer.getAttribute("data-range-start")),
      DEMO_DAY.getTime() - 7 * 86_400_000,
    );
    const rangeQuery = new URLSearchParams(new URL(page.url()).hash.split("?")[1]);
    assert.equal(new URL(page.url()).hash.split("?")[0], "#/history/explorer");
    assert.equal(rangeQuery.get("zone"), "1");
    assert.equal(rangeQuery.get("range"), "7d");
    // Any sensor of the room: ticking one adds its series, on an axis of its own unit.
    const more = await loads();
    await explorer.locator('[data-sensor="sensor.demo_vpd"]').check();
    await explorer.locator('[data-sensor="sensor.demo_air_humidity"]').check();
    await loaded(more);
    assert.equal(await explorer.getAttribute("data-explorer-series"), "4");
    await page.waitForFunction(
      () =>
        document.querySelectorAll(
          "[data-history-explorer] .recharts-line:not(.history-explorer-previous) path.recharts-curve",
        ).length === 4,
    );
    assert.match(await explorer.locator(".history-explorer-legend").innerText(), /VPD/);
    // "All VWC" ticks every moisture reading of the room.
    await explorer.getByRole("button", { name: "All VWC" }).click();
    assert.equal(
      await explorer.getByRole("button", { name: "All VWC" }).getAttribute("aria-pressed"),
      "true",
    );
    await explorer.getByRole("button", { name: "All VWC" }).click();
    // The previous run at the same grow days: days 8 to 15 of this run (it began 14 days ago at
    // lights-on), so the same days of the previous run, which began 112 days ago.
    await explorer.locator("[data-compare-toggle]").check();
    const legend = explorer.locator("[data-previous-legend]");
    await expectVisible(legend);
    assert.match(await legend.innerText(), /^Run Demo • previous run — Room A, days 8–15$/);
    assert.equal(await explorer.getAttribute("data-compare-days"), "8-15");
    // Seven elapsed days can cross DST: in NZ this range starts at 15:00 standard time,
    // although its end is 16:00 daylight time. Compare the selected start's grow-day offset.
    const rangeStartClock = new Date(Number(await explorer.getAttribute("data-range-start")));
    const day8 = new Date(
      2026,
      8,
      28 - 112 + 7,
      rangeStartClock.getHours(),
      rangeStartClock.getMinutes(),
    ).getTime();
    assert.ok(
      Math.abs(Number(await explorer.getAttribute("data-compare-start")) - day8) < 60_000,
      "the previous run starts at the same hour after lights-on of its grow day 8",
    );
    await page.waitForFunction(
      () =>
        [
          ...document.querySelectorAll(
            "[data-history-explorer] .history-explorer-previous path.recharts-curve",
          ),
        ].some((path) => (path.getAttribute("d") || "").length > 20),
      null,
      { timeout: 20_000 },
    );
    assert.equal(await explorer.locator("[data-compare-note]").count(), 0);
    // The choice is in the address: a reload, light and dark, keeps it.
    await inBothThemes("zone history explorer", async () => {
      await expectVisible(page.locator("[data-previous-legend]"));
    });
    await page.evaluate(() => localStorage.setItem("irrigation-theme", "dark"));
    await page.reload({ waitUntil: "networkidle" });
    await expectVisible(page.locator("[data-previous-legend]"));
    await page.locator("[data-history-explorer]").scrollIntoViewIfNeeded();
    await page
      .locator("[data-history-explorer]")
      .screenshot({ path: path.join(out, "history-explorer-1440-dark.png") });
    // A phone: the controls in a sheet, the chart scrolls sideways inside its panel.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: "networkidle" });
    await expectVisible(page.locator("[data-previous-legend]"));
    await noOverflow();
    await page.getByRole("button", { name: "Range and sensors" }).click();
    const sheet = page.getByRole("dialog", { name: "Range and sensors" });
    await expectVisible(sheet);
    assert.equal(await sheet.locator('[data-sensor="sensor.demo_vpd"]').isChecked(), true);
    await axe("zone history explorer sheet, phone, dark");
    await page.keyboard.press("Escape");
    await noOverflow();
    await page.locator("[data-history-explorer]").scrollIntoViewIfNeeded();
    await page
      .locator("[data-history-explorer]")
      .screenshot({ path: path.join(out, "history-explorer-390-dark.png") });
    await page.evaluate(() => localStorage.setItem("irrigation-theme", "light"));
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check("mobile navigation and every page fit 390px", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await go("today");
    // The phone header in words: the room and the data's age, then both switches and Stop all labelled.
    assert.match(await page.locator(".data-age").innerText(), /^Updated \d+ (s|min) ago$/);
    assert.deepEqual(await page.locator(".safety-switch-text").allInnerTexts(), [
      "Watering on",
      "Stop all",
    ]);
    // The five sections along the bottom of the phone.
    assert.deepEqual(
      await page.getByRole("navigation", { name: "Sections" }).locator("button").allInnerTexts(),
      ["Status", "Irrigation", "History", "Equipment", "Settings"],
    );
    await page.getByRole("button", { name: "Open navigation" }).click();
    await axe("mobile navigation");
    const mobileMenu = page.getByRole("dialog");
    const entries = await mobileMenu
      .getByRole("navigation", { name: "Main navigation" })
      .locator("[data-nav-section]")
      .allInnerTexts();
    assert.deepEqual(entries, ["Status", "Irrigation", "History", "Equipment", "Settings"]);
    // Under the sections: every room, and every zone under its room, one tap each.
    const tree = mobileMenu.getByRole("navigation", { name: "Rooms" });
    assert.ok((await tree.locator(".room-tree-room").count()) >= 2, "every room listed");
    assert.ok((await tree.locator(".room-tree-zone").count()) >= 2, "zones listed under rooms");
    await openFromMenu(
      mobileMenu.getByRole("navigation", { name: "Main navigation" }),
      "plan",
      "Current day",
    );
    await expectVisible(page.getByRole("heading", { name: "Irrigation", exact: true }));
    const views = page.getByRole("navigation", { name: "Irrigation views" });
    await views.getByRole("button", { name: "Calendar", exact: true }).click();
    await expectVisible(page.getByRole("heading", { name: "Irrigation", exact: true }));
    await noOverflow();
    for (const [route, heading] of routes) {
      await go(route);
      await expectVisible(page.getByRole("heading", { name: heading, exact: true, level: 1 }));
      if (sectionOf(route)) await tabsShareRow(sectionOf(route));
      await noOverflow();
      await page.screenshot({
        path: path.join(out, `mobile-${route.replace("/", "-")}.png`),
        fullPage: true,
      });
    }
    await axe("mobile help");
    // An "About" button on a phone, by keyboard: it opens with Enter, fits the screen, shows its
    // caution, and Escape closes it.
    await go("settings");
    const about = page.getByRole("button", { name: "About Hardware panel", exact: true });
    await about.focus();
    await page.keyboard.press("Enter");
    const tip = page.getByRole("dialog", { name: "Hardware panel", exact: true });
    await expectVisible(tip);
    const box = await tip.boundingBox();
    assert.ok(box && box.x >= 0 && box.x + box.width <= 390, "the tip fits a 390 px screen");
    const notices = await tip.locator(".info-tip-notice strong").allInnerTexts();
    assert.deepEqual(notices, ["CAUTION:"], "the hardware-control tip shows its caution");
    assert.match(await tip.innerText(), /Impact:[\s\S]*Guidance:/i);
    await axe("mobile about tip");
    await page.keyboard.press("Escape");
    assert.equal(await tip.count(), 0, "Escape closes the tip");
    await noOverflow();
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check(
    "probe comparison: independent row pickers retain choices and fit a phone",
    async () => {
      await page.goto(`${base}/dashboard.html?demo&room=f2#/settings/features`, {
        waitUntil: "networkidle",
      });
      const catalogueRow = page
        .locator(".features-row")
        .filter({ hasText: "Per-probe grow comparison" });
      await expectVisible(catalogueRow);
      assert.equal(await catalogueRow.getByRole("link").getAttribute("href"), "#/history/explorer");
      await axe("per-probe compare catalogue");
      await page.goto(`${base}/dashboard.html?demo&room=f2#/history/explorer?zone=1&range=7d`, {
        waitUntil: "networkidle",
      });
      const picker = page.locator("[data-probe-compare]").first();
      await picker.waitFor();
      const id = await picker.getAttribute("data-probe-compare");
      const checkbox = page.locator(`[data-sensor="${id}"]`);
      if (!(await checkbox.isChecked())) await checkbox.check();
      await picker.selectOption("last");
      await page.locator(`[data-probe-source="${id}"]`).waitFor();
      assert.match(await page.locator(`[data-probe-source="${id}"]`).innerText(), /previous run/);
      assert.equal(await page.locator("[data-probe-compare]").nth(1).inputValue(), "off");
      await page.reload({ waitUntil: "networkidle" });
      assert.equal(await page.locator(`[data-probe-compare="${id}"]`).inputValue(), "last");
      await page.setViewportSize({ width: 390, height: 844 });
      await page.getByRole("button", { name: "Range and sensors" }).click();
      await expectVisible(page.getByRole("dialog", { name: "Range and sensors" }));
      await axe("per-probe compare picker, phone");
      await page.keyboard.press("Escape");
      await noOverflow();
      await page.setViewportSize({ width: 1440, height: 1000 });
    },
  );
  assert.ok(checks.length > 0, "At least one requested workflow must execute");
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
