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
const planViewLayouts = [];
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
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
    true,
    "Page has horizontal overflow",
  );
}
async function planViewsShareRow() {
  const views = page.getByRole("navigation", { name: "Irrigation plan views" });
  const [today, schedule] = await Promise.all([
    views.getByRole("button", { name: "Today", exact: true }).boundingBox(),
    views.getByRole("button", { name: "Schedule", exact: true }).boundingBox(),
  ]);
  assert.ok(today && schedule, "Both irrigation plan view buttons must be visible");
  assert.ok(
    Math.abs(today.y - schedule.y) <= 2 &&
      Math.abs(today.y + today.height - schedule.y - schedule.height) <= 2,
    "Today and Schedule must share one horizontal row",
  );
  assert.ok(
    schedule.x >= today.x + today.width - 1,
    "Schedule must sit beside Today without overlap",
  );
  planViewLayouts.push({
    route: new URL(page.url()).hash,
    viewport: page.viewportSize(),
    today,
    schedule,
  });
}
async function axe(label) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
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
try {
  await check("primary entry preserves room, demo and route", async () => {
    await page.goto(`${base}/index.html?demo&room=f1#/zones`);
    await expectVisible(page.getByRole("heading", { name: "Zones", exact: true }));
    assert.match(page.url(), /dashboard\.html\?demo=&room=f1#\/zones/);
    assert.equal(await page.locator("#desktop-room").inputValue(), "room:f1_");
  });
  const routes = [
    ["overview", "Flower 2 overview"],
    ["zones", "Zones"],
    ["strategy", "Today’s targets"],
    ["grow-plan", "Scheduled targets"],
    ["compare", "Compare runs"],
    ["setup", "Rooms & setup"],
    ["insights", "Insights"],
    ["activity", "Activity"],
    ["sensors", "Sensors"],
    ["settings", "Settings"],
    ["help", "Help & tools"],
  ];
  for (const [route, heading] of routes)
    await check(`${route}: render, desktop layout and accessibility`, async () => {
      await go(route);
      await expectVisible(page.getByRole("heading", { name: heading, exact: true }));
      // A heading carries a sentence only for a behaviour someone could get wrong.
      if (!["strategy", "grow-plan"].includes(route))
        assert.equal(
          await page.locator(".page-heading > div > p").count(),
          0,
          `${route}: the heading repeats itself in a description`,
        );
      if (["strategy", "grow-plan"].includes(route)) await planViewsShareRow();
      await noOverflow();
      await axe(route);
      await page.screenshot({
        path: path.join(out, `dashboard-${route}.png`),
        fullPage: true,
      });
    });
  await check("help: the daily routine replaces the Overview's workflow card", async () => {
    await go("help");
    const routine = page.locator("ol.daily-routine");
    await expectVisible(routine);
    assert.deepEqual(
      await routine.locator("a").evaluateAll((links) => links.map((a) => a.getAttribute("href"))),
      ["#/overview", "#/zones", "#/strategy"],
    );
    await go("overview");
    assert.equal(await page.getByRole("heading", { name: "Your daily workflow" }).count(), 0);
  });
  await check("recent activity opens beside any page and leads to the full log", async () => {
    await go("zones");
    assert.equal(await page.getByRole("dialog").count(), 0, "the panel starts closed");
    await page.getByRole("button", { name: "Recent activity", exact: true }).click();
    const panel = page.getByRole("dialog", { name: "Recent activity" });
    await expectVisible(panel);
    assert.ok((await panel.locator(".event-row").count()) > 0, "the demo room has records");
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
    await panel.getByRole("button", { name: "Open the activity log" }).click();
    await expectVisible(page.getByRole("heading", { name: "Activity", exact: true }));
    assert.equal(await page.getByRole("dialog").count(), 0, "the panel closes when the log opens");
    await go("overview");
    assert.equal(await page.getByRole("heading", { name: "Recent activity" }).count(), 0);
  });
  await check("overview: the grow day comes first, above the tank", async () => {
    await go("overview");
    const timeline = page.locator("[data-day-timeline]");
    await expectVisible(timeline.locator(".timeline-zone").first());
    const tops = await page.evaluate(() =>
      ["[data-day-timeline]", "[data-tank-status]", ".zone-table-desktop"].map(
        (selector) => document.querySelector(selector).getBoundingClientRect().top,
      ),
    );
    assert.ok(tops[0] < tops[1] && tops[0] < tops[2], `timeline ${tops[0]}, tank ${tops[1]}`);
    assert.equal(await page.locator(".wd-daily").count(), 0, "no water table on the Overview");
    assert.equal(await page.getByText("Controller scheduling", { exact: true }).count(), 0);
  });
  await check("overview: every zone and room metric has its mini visual", async () => {
    await go("overview");
    await expectVisible(page.locator(".zone-table-desktop th", { hasText: "Dryback" }));
    // The dryback waits for the recorded readings; every row gets one once they arrive.
    await page.waitForFunction(
      () =>
        document.querySelectorAll(".zone-table-desktop [data-dryback]").length ===
        document.querySelectorAll(".zone-table-desktop tbody tr").length,
    );
    const facts = await page.evaluate(() => ({
      rows: document.querySelectorAll(".zone-table-desktop tbody tr").length,
      sparklines: document.querySelectorAll(".zone-table-desktop .dryback .sparkline").length,
      water: [...document.querySelectorAll(".zone-table-desktop .water-use .meter")].map((m) =>
        m.getAttribute("aria-label"),
      ),
      valves: [...document.querySelectorAll(".zone-table-desktop [data-zone-valve]")].map((v) => [
        v.textContent.trim(),
        v.dataset.tone,
      ]),
      bars: [...document.querySelectorAll(".metric-strip .mini-bars")].map(
        (b) => b.querySelectorAll(".mini-bar").length,
      ),
      captions: [...document.querySelectorAll(".metric-caption")].map((c) => c.textContent.trim()),
    }));
    assert.ok(facts.rows > 0);
    assert.equal(facts.sparklines, facts.rows, "every zone draws its recent moisture");
    assert.equal(facts.water.length, facts.rows, "every zone shows water against its daily limit");
    for (const label of facts.water) assert.match(label, /^\d+% of the [\d.]+ L daily limit$/);
    for (const [text, tone] of facts.valves)
      assert.equal(tone, /on$/.test(text) ? "on" : /off$/.test(text) ? "off" : "unknown", text);
    assert.deepEqual(facts.bars, [facts.rows, facts.rows, facts.rows, facts.rows]);
    assert.ok(
      facts.captions.some((c) => /^Avg [\d.]+ L per zone$/.test(c)),
      facts.captions.join(" | "),
    );
  });
  await check("overview: two screens at most, zones beside the tank", async () => {
    // 1440×800 ≈ the browser window of a 1440×900 laptop; the Overview was 3.2 screens tall.
    await page.setViewportSize({ width: 1440, height: 800 });
    await go("overview");
    await expectVisible(page.getByRole("heading", { name: "Flower 2 overview", exact: true }));
    const layout = await page.evaluate(() => {
      const top = (selector) => document.querySelector(selector).getBoundingClientRect().top;
      const table = document.querySelector(".zone-table-desktop");
      return {
        height: document.documentElement.scrollHeight,
        window: innerHeight,
        zonesTop: top(".overview-grid > .panel"),
        tankTop: top("[data-tank-status]"),
        tableScrolls: table.scrollWidth > table.clientWidth + 1,
        subtitles: document.querySelectorAll("#main-content .panel-heading p").length,
      };
    });
    assert.ok(
      layout.height <= 2 * layout.window,
      `Overview is ${layout.height}px tall in a ${layout.window}px window`,
    );
    assert.equal(layout.zonesTop, layout.tankTop, "zones and tank share a row");
    assert.equal(layout.tableScrolls, false, "the zone table scrolls sideways");
    assert.equal(layout.subtitles, 0, "a panel on the Overview repeats its title in a subtitle");
    await page.screenshot({
      path: path.join(out, "dashboard-overview-laptop.png"),
      fullPage: true,
    });
    // A narrow desktop stacks the columns without sideways page scroll.
    await page.setViewportSize({ width: 1100, height: 800 });
    await noOverflow();
    const stacked = await page.evaluate(() => {
      const zones = document.querySelector(".overview-grid > .panel").getBoundingClientRect();
      const tank = document.querySelector("[data-tank-status]").getBoundingClientRect();
      return tank.top >= zones.bottom;
    });
    assert.ok(stacked, "below 1200 px the tank stacks under the zones");
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check("help: every error code is listed, searchable and linkable", async () => {
    const catalog = JSON.parse(await readFile(path.join(root, "docs/error-codes.json"), "utf8"));
    await go("help");
    await expectVisible(page.getByRole("heading", { name: "Error codes", exact: true }));
    const codes = page.locator("details.error-code");
    assert.deepEqual(
      await codes.evaluateAll((all) => all.map((d) => d.id)),
      catalog.codes.map((entry) => entry.code.toLowerCase()),
      "Help & tools must list exactly the codes in docs/error-codes.json",
    );
    const search = page.getByRole("textbox", { name: "Search error codes" });
    await search.fill("101");
    assert.equal(await codes.count(), 1);
    const found = page.locator("details#cs-101");
    assert.equal(await found.getAttribute("open"), "", "A code typed in full opens by itself");
    await expectVisible(found.getByText("Likely causes", { exact: true }));
    await expectVisible(found.getByText(/No plant in the cube/));
    await search.fill("nothing like this");
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
    // Dark: only the new section. Toggling the class alone is not the app's full dark theme, so
    // the rest of the page is not judged on it here.
    await page.evaluate(() => document.documentElement.classList.add("dark"));
    // Colours transition (even at reduced motion); measure after two frames, not mid-change.
    await page.evaluate(
      () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))),
    );
    const dark = await new AxeBuilder({ page })
      .include(".error-codes")
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    accessibility.push({
      page: "help error codes, all open, dark",
      violations: dark.violations.map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })),
    });
    assert.deepEqual(
      dark.violations.map((v) => v.id),
      [],
      "Error codes must be readable on a dark theme",
    );
    await page.screenshot({
      path: path.join(out, "dashboard-help-error-codes.png"),
      fullPage: true,
    });
    await page.evaluate(() => document.documentElement.classList.remove("dark"));
  });
  await check(
    "one Irrigation plan entry exposes Today and Schedule with working history",
    async () => {
      await go("overview");
      const primary = page.getByRole("navigation", { name: "Main navigation" });
      const plan = primary.getByRole("button", { name: "Irrigation plan", exact: true });
      assert.equal(await plan.count(), 1);
      assert.equal(
        await primary.getByRole("button", { name: "Manual setpoints", exact: true }).count(),
        0,
      );
      assert.equal(
        await primary.getByRole("button", { name: "Grow plan", exact: true }).count(),
        0,
      );
      await plan.click();
      await expectVisible(page.getByRole("heading", { name: "Today’s targets", exact: true }));
      const views = page.getByRole("navigation", { name: "Irrigation plan views" });
      const today = views.getByRole("button", { name: "Today", exact: true });
      const schedule = views.getByRole("button", { name: "Schedule", exact: true });
      assert.equal(await today.getAttribute("aria-current"), "page");
      assert.equal(await schedule.getAttribute("aria-current"), null);
      await schedule.click();
      await expectVisible(page.getByRole("heading", { name: "Scheduled targets", exact: true }));
      assert.equal(new URL(page.url()).hash, "#/grow-plan");
      assert.equal(await plan.getAttribute("aria-current"), "page");
      assert.equal(await schedule.getAttribute("aria-current"), "page");
      assert.equal(await today.getAttribute("aria-current"), null);
      await page.goBack();
      await expectVisible(page.getByRole("heading", { name: "Today’s targets", exact: true }));
      await page.goForward();
      await expectVisible(page.getByRole("heading", { name: "Scheduled targets", exact: true }));
      await today.click();
      await expectVisible(page.getByRole("heading", { name: "Today’s targets", exact: true }));
    },
  );
  await check("keyboard skip retains page and browser history works", async () => {
    await go("zones");
    await page.getByRole("link", { name: "Skip to content" }).focus();
    await page.keyboard.press("Enter");
    await expectVisible(page.getByRole("heading", { name: "Zones", exact: true }));
    assert.equal(await page.evaluate(() => document.activeElement?.id), "main-content");
    assert.match(page.url(), /#\/zones$/);
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Sensors", exact: true })
      .click();
    await expectVisible(page.getByRole("heading", { name: "Sensors", exact: true }));
    await page.goBack();
    await expectVisible(page.getByRole("heading", { name: "Zones", exact: true }));
    await page.goForward();
    await expectVisible(page.getByRole("heading", { name: "Sensors", exact: true }));
  });
  await check("zone search, clear and detail drawer", async () => {
    await go("zones");
    await page.getByRole("textbox", { name: "Search zones" }).fill("no-such-zone");
    await expectVisible(page.getByRole("heading", { name: "No matching zones" }));
    await page.getByRole("button", { name: "Clear search" }).click();
    await page.getByRole("button", { name: "View Zone 1", exact: true }).click();
    await expectVisible(page.getByRole("dialog"));
    await axe("zone drawer");
    await page.screenshot({
      path: path.join(out, "dashboard-zone-detail.png"),
    });
    await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
  });
  await check("strategy draft survives refresh, validates, reviews and applies", async () => {
    await go("strategy");
    const field = page.locator('input[id="setting-number.crop_steering_zone_1_p1_target_vwc"]');
    const original = Number(await field.inputValue());
    await field.fill("999");
    await expectVisible(page.locator('[id="hint-number.crop_steering_zone_1_p1_target_vwc"]'));
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
    await page.getByRole("button", { name: /^Review 1 change/ }).click();
    await expectVisible(page.getByRole("dialog").getByText(/Flower 2 only/));
    await axe("strategy review");
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
  await check("activity filters and CSV export", async () => {
    await go("activity");
    await page.getByRole("textbox", { name: "Search activity" }).fill("no-such-event");
    await expectVisible(page.getByRole("heading", { name: "No activity matches this view" }));
    await page.getByRole("button", { name: "Clear filters" }).click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export CSV" }).click();
    const download = await downloadPromise;
    assert.match(download.suggestedFilename(), /flower-2-activity-.+\.csv/);
    await download.saveAs(path.join(out, "activity-export.csv"));
    const csv = await readFile(path.join(out, "activity-export.csv"), "utf8");
    assert.match(csv, /Timestamp.*Room.*Zone.*Type.*Message/);
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
  await check("mobile navigation and every primary page fit 390px", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await go("overview");
    await page.getByRole("button", { name: "Open navigation" }).click();
    await axe("mobile navigation");
    const mobileMenu = page.getByRole("dialog");
    assert.equal(
      await mobileMenu.getByRole("button", { name: "Irrigation plan", exact: true }).count(),
      1,
    );
    assert.equal(
      await mobileMenu.getByRole("button", { name: "Manual setpoints", exact: true }).count(),
      0,
    );
    assert.equal(
      await mobileMenu.getByRole("button", { name: "Grow plan", exact: true }).count(),
      0,
    );
    await mobileMenu.getByRole("button", { name: "Irrigation plan", exact: true }).click();
    await expectVisible(page.getByRole("heading", { name: "Today’s targets", exact: true }));
    const views = page.getByRole("navigation", { name: "Irrigation plan views" });
    await views.getByRole("button", { name: "Schedule", exact: true }).click();
    await expectVisible(page.getByRole("heading", { name: "Scheduled targets", exact: true }));
    await noOverflow();
    await views.getByRole("button", { name: "Today", exact: true }).click();
    await expectVisible(page.getByRole("heading", { name: "Today’s targets", exact: true }));
    for (const [route, heading] of routes) {
      await go(route);
      await expectVisible(page.getByRole("heading", { name: heading, exact: true }));
      if (["strategy", "grow-plan"].includes(route)) await planViewsShareRow();
      await noOverflow();
      await page.screenshot({
        path: path.join(out, `mobile-${route}.png`),
        fullPage: true,
      });
    }
    await axe("mobile help");
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
    JSON.stringify({ checks, pageErrors, forbidden, accessibility, planViewLayouts }, null, 2),
  );
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
