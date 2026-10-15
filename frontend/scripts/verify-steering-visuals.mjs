/** Compiled visual editing, delivery and comparison contracts; isolated demo only. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
const out = fileURLToPath(new URL("../../output/playwright/", import.meta.url));
await mkdir(out, { recursive: true });
const html = await readFile(new URL("../../www/dashboard.html", import.meta.url));
const server = createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "text/html", "Cache-Control": "no-store" });
  res.end(html);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({
  headless: true,
  ...(process.platform === "win32" ? { channel: "chrome" } : {}),
});
const context = await browser.newContext({
  viewport: { width: 1600, height: 1100 },
  acceptDownloads: true,
  colorScheme: "dark",
  ...(process.env.VERIFY_TZ ? { timezoneId: process.env.VERIFY_TZ } : {}),
});
const forbidden = [],
  errors = [],
  checks = [],
  accessibility = [];
const isolate = (route) => {
  const u = new URL(route.request().url());
  if (u.origin !== origin || u.pathname.startsWith("/api/")) {
    forbidden.push(u.origin + u.pathname);
    return route.abort();
  }
  return route.continue();
};
await context.route("**/*", isolate);
const page = await context.newPage();
// The demo's readings depend on the hour. VERIFY_TZ=UTC VERIFY_AT=2026-09-20T11:41:00Z replays any
// wall clock (CI runs in UTC, at whatever hour the push happened) without changing how timers run.
if (process.env.VERIFY_AT) await page.clock.setFixedTime(new Date(process.env.VERIFY_AT));
page.setDefaultTimeout(10000);
page.on("pageerror", (e) => errors.push(e.message));
page.on("dialog", (d) => d.accept());
async function fresh(route) {
  await page.goto(`${origin}/dashboard.html?demo=1#/${route}`, { waitUntil: "networkidle" });
  await page.reload({ waitUntil: "networkidle" });
}
/** Moves within the page, so the demo keeps what this check changed (a reload resets it). */
async function open(route) {
  await page.evaluate((hash) => (location.hash = hash), `#/${route}`);
}
async function check(name, fn) {
  try {
    await fn();
    checks.push({ name, status: "pass" });
    console.log("PASS " + name);
  } catch (e) {
    checks.push({ name, status: "fail", error: e.stack });
    console.error("FAIL " + name + ": " + e.message);
    await page.screenshot({
      path: out + "visual-failure-" + checks.length + ".png",
      fullPage: true,
    });
  }
}
async function axe(name) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  accessibility.push({ name, violations: result.violations });
  assert.deepEqual(
    result.violations.map((v) => v.id),
    [],
    name + " accessibility",
  );
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
    "Document overflow",
  );
}
const field = (suffix) => page.locator(`[id="setting-number.crop_steering_zone_1_${suffix}"]`);
const line = (name) => page.locator(`[data-planning-line="${name}"]`);
try {
  await check(
    "P3 floor follows numeric edits; saved baseline and room values remain unchanged",
    async () => {
      // An old address: the targets are Plan › Targets, every phase in one table.
      await fresh("strategy");
      await page.getByRole("heading", { name: "Targets", exact: true }).waitFor();
      const floor = field("p3_emergency_vwc_threshold");
      // Each zone's axis scales to its own recorded data, so zones are compared by value and a
      // zone's draft line only against that same zone's saved line, never by pixels across zones.
      const zoneTab = (n) =>
        page
          .getByRole("navigation", { name: "Targets for" })
          .getByRole("button", { name: new RegExp("Zone " + n) });
      const otherFloor = page.locator(
        '[id="setting-number.crop_steering_zone_2_p3_emergency_vwc_threshold"]',
      );
      await zoneTab(2).click();
      const other = await otherFloor.inputValue();
      await zoneTab(1).click();
      const original = await floor.inputValue();
      const savedY = await line("baseline-p3-floor").getAttribute("y1");
      const curve = await line("vwc").getAttribute("d");
      await floor.fill(String(Number(original) + 5));
      assert.notEqual(await line("p3-floor").getAttribute("y1"), savedY);
      assert.equal(await line("baseline-p3-floor").getAttribute("y1"), savedY);
      assert.equal(
        await line("vwc").getAttribute("d"),
        curve,
        "Emergency floor must not pretend to reshape daytime moisture",
      );
      await page.getByRole("button", { name: "Discard draft", exact: true }).waitFor();
      await noOverflow();
      await axe("manual preview");
      await page.evaluate(() => {
        document.activeElement?.blur();
        window.scrollTo(0, 0);
      });
      await page.screenshot({
        path: fileURLToPath(new URL("../../img/manual-setpoints.png", import.meta.url)),
      });
      await zoneTab(2).click();
      assert.equal(await otherFloor.inputValue(), other, "Zone 2 remains unchanged");
      assert.equal(
        await line("p3-floor").getAttribute("y1"),
        await line("baseline-p3-floor").getAttribute("y1"),
        "Zone 2 draws no draft floor",
      );
      await zoneTab(1).click();
      assert.equal(await floor.inputValue(), String(Number(original) + 5));
      await page.getByRole("button", { name: "Discard draft", exact: true }).click();
      assert.equal(await floor.inputValue(), original);
      assert.equal(await line("p3-floor").getAttribute("y1"), savedY);
    },
  );
  await check("Today graph carries the recorded probe and the whole projected day", async () => {
    // The demo's history always ends at its fixed live reading, so what the recorded day looks like
    // depends on the hour. An hour before lights-on the grow-day is complete (P0 dip, ramp, top-ups,
    // overnight dry-down) and lines up with the targets; a pinned clock also stops the README images
    // changing on every run. The clock belongs to the browser context, so this gets its own and the
    // other checks keep real time.
    const pinned = await browser.newContext({
      viewport: { width: 1600, height: 1100 },
      colorScheme: "dark",
    });
    await pinned.route("**/*", isolate);
    const shot = await pinned.newPage();
    shot.on("pageerror", (e) => errors.push(e.message));
    await shot.clock.setFixedTime(new Date(2026, 8, 20, 9, 0, 0));
    await shot.goto(`${origin}/dashboard.html?demo=1#/plan/targets`, { waitUntil: "networkidle" });
    const graph = shot.locator(".planning-curve");
    await graph.locator('[data-planning-line="recorded-vwc"]').waitFor();
    assert.ok(await graph.locator('[data-planning-line="recorded-vwc-previous"]').count());
    assert.ok(await graph.locator('[data-planning-line="recorded-ec"]').count());
    assert.match(
      await graph.locator(".planning-recorded").innerText(),
      /Now[\s\S]*Peak · this grow-day[\s\S]*Trough · this grow-day/,
    );
    // every phase is drawn the way it runs: all six demo ramp shots, and the P2 top-ups
    assert.equal(await graph.locator('[data-planning-shot="P1"]').count(), 6);
    assert.ok((await graph.locator('[data-planning-shot="P2"]').count()) > 1);
    assert.match(
      await graph.locator(".planning-projection").innerText(),
      /Projected day[\s\S]*measured from this zone/,
    );
    assert.doesNotMatch(await graph.innerText(), /NaN|undefined/);
    await graph.scrollIntoViewIfNeeded();
    await graph.screenshot({
      path: fileURLToPath(new URL("../../img/plan-graph.png", import.meta.url)),
    });
    // What the probes recorded over days, against the targets: on the zone's page, on request.
    await shot.evaluate(() => (location.hash = "#/zone/1"));
    await shot.locator("details.zone-recorded > summary").click();
    const history = shot
      .locator("section")
      .filter({ has: shot.getByRole("heading", { name: "Recorded sensor behaviour" }) })
      .first();
    await history.locator(".sensor-chart").first().waitFor();
    await history.scrollIntoViewIfNeeded();
    await history.screenshot({
      path: fileURLToPath(new URL("../../img/sensor-history.png", import.meta.url)),
    });
    await pinned.close();
  });
  await check("Room off stands the room down and says so", async () => {
    await fresh("settings");
    await page.getByRole("button", { name: "Switch room off…", exact: true }).click();
    await page.getByRole("button", { name: /^Apply 1 change/ }).click();
    await page.getByRole("button", { name: "Switch room on…", exact: true }).waitFor();
    // Same document, so the demo keeps its in-memory state; a reload would switch the room back on.
    await open("overview");
    const banner = page.locator(".room-off-banner");
    await banner.waitFor();
    assert.match(await banner.innerText(), /no irrigation, no alerts/i);
    assert.match(await page.locator('.room-chip[data-room="room:"]').innerText(), /Room off/);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: fileURLToPath(new URL("../../img/room-off.png", import.meta.url)),
      clip: { x: 0, y: 0, width: 1600, height: 760 },
    });
  });
  await check("P1 controls reshape preview; invalid drafts cannot apply", async () => {
    await fresh("plan/targets");
    const target = field("p1_target_vwc");
    // The VWC axis scales to what is plotted, so compare what each line plots, not its pixels.
    const before = await line("vwc").getAttribute("data-planning-values");
    await target.fill("70");
    assert.notEqual(await line("vwc").getAttribute("data-planning-values"), before);
    assert.equal(await line("baseline-vwc").getAttribute("data-planning-values"), before);
    await target.fill("999");
    assert.equal(await target.getAttribute("aria-invalid"), "true");
    assert.equal(
      await page.getByRole("button", { name: "Review changes", exact: true }).isDisabled(),
      true,
    );
    await page.getByRole("button", { name: "Discard draft", exact: true }).click();
  });
  await check(
    "Field capacity suggestion names its source, fills only the local draft and is never applied by itself",
    async () => {
      // Full saturation is the substrate's: Equipment › Setup.
      await fresh("equipment/setup");
      const section = page.locator(".controller-settings");
      const capacity = field("field_capacity");
      const note = page.locator('[id="note-number.crop_steering_zone_1_field_capacity"]');
      // Zone 1's supervisor is tracking, so the controller has a learned peak to offer.
      const learned = note.locator(".setting-suggestion");
      await learned.waitFor();
      assert.match(
        await learned.innerText(),
        /^Suggestion · Learned peak 60\.0%, the ceiling the controller’s Auto Setpoints has learned for this zone\./,
      );
      assert.equal(await capacity.inputValue(), "70", "A suggestion must not change the field");
      assert.equal(
        await section.getByRole("button", { name: "Discard draft", exact: true }).count(),
        0,
        "A suggestion must not create a draft",
      );
      await note.getByRole("button", { name: "Use 60% in draft", exact: true }).click();
      assert.equal(await capacity.inputValue(), "60", "The draft holds the suggested value");
      // Draft only: the controller keeps its saved value until the change is reviewed and applied.
      await note.getByText("Currently 70 %", { exact: true }).waitFor();
      assert.equal(
        await note.getByRole("button", { name: "Use 60% in draft", exact: true }).isDisabled(),
        true,
      );
      await section.getByRole("button", { name: /^Review 1 change/ }).click();
      assert.match(
        await page.getByRole("dialog").locator(".review-row").innerText(),
        /Zone 1 · Full saturation \(most it holds\)[\s\S]*70 %[\s\S]*60 %/,
      );
      await page.getByRole("button", { name: "Back to editing", exact: true }).click();
      await page.getByRole("dialog").waitFor({ state: "hidden" });
      await section.getByRole("button", { name: "Discard draft", exact: true }).click();
      assert.equal(await capacity.inputValue(), "70");
      // Zone 2's supervisor is still learning: the suggestion falls back to recorded history.
      await page
        .getByRole("navigation", { name: "Settings for" })
        .getByRole("button", { name: /Zone 2/ })
        .click();
      const typical = page.locator(
        '[id="note-number.crop_steering_zone_2_field_capacity"] .setting-suggestion',
      );
      await typical.waitFor();
      assert.match(
        await typical.innerText(),
        /^Suggestion · Typical daily peak \d+\.\d%, the median daily high this probe recorded over \d+ days? \(72 h window\)\./,
      );
      await axe("field capacity suggestion");
    },
  );
  await check(
    "Runtime estimates show all-plant zone litres and per-plant water separately",
    async () => {
      // What a shot delivers is set up with the drippers: Equipment › Setup, Water & calibration.
      await fresh("equipment/setup");
      await page.locator("details.controller-settings-water > summary").click();
      const water = page.getByRole("region", { name: "Zone 1 water delivery" });
      // A labelled section is exposed as a region by the accessibility tree.
      await water.getByLabel("Try a valve-open runtime · seconds").fill("120");
      assert.match(await water.locator(".wd-effective").innerText(), /133\.3 mL \/ plant/);
      assert.match(await water.locator(".wd-effective").innerText(), /4\.8(?:0)? L \/ zone/);
      await water.getByLabel("Try a valve-open runtime · seconds").fill("60");
      assert.match(await water.locator(".wd-effective").innerText(), /66\.7 mL \/ plant/);
      assert.match(await water.locator(".wd-effective").innerText(), /2\.4(?:0)? L \/ zone/);
      assert.match(await water.innerText(), /Total substrate capacity/);
      assert.match(await water.innerText(), /216/);
      // Water per plant today, zone by zone: History › Water use.
      await fresh("history/water");
      const summary = page.locator(".wd-daily");
      const row = summary.getByRole("row").filter({ hasText: "Zone 1" });
      assert.match(await row.innerText(), /5\.3(?:0)? L/);
      assert.match(await row.innerText(), /147\.2 mL/);
    },
  );
  await check(
    "Register, compare and archive runs with bounded dates and room isolation",
    async () => {
      // Run records are kept in Settings; History › Compare runs lines them up.
      await fresh("settings");
      const records = page.locator("#run-records");
      await records.waitFor();
      const dateAgo = (days) => new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
      async function register(name, start, end = "") {
        await records.getByRole("button", { name: "Add run", exact: true }).click();
        await page.getByLabel("Run name", { exact: true }).fill(name);
        await page.getByLabel("Run start date", { exact: true }).fill(start);
        await page.getByLabel("Run end date", { exact: true }).fill(end);
        await page.getByRole("button", { name: "Save run record", exact: true }).click();
        await page.locator(".comparison-run-list article").filter({ hasText: name }).waitFor();
      }
      await records.getByRole("button", { name: "Add run", exact: true }).click();
      await page.getByLabel("Run name", { exact: true }).fill("Unsaved run draft");
      await page
        .locator(".desktop-sidebar")
        .getByRole("button", { name: "Today", exact: true })
        .click();
      await page.getByRole("heading", { name: "Discard unsaved workspace changes?" }).waitFor();
      await page.getByRole("button", { name: "Keep editing", exact: true }).click();
      assert.equal(
        await page.getByLabel("Run name", { exact: true }).inputValue(),
        "Unsaved run draft",
      );
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
      await register("Previous room run", dateAgo(80), dateAgo(50));
      await register("Current room run", dateAgo(16));
      const downloaded = page.waitForEvent("download");
      await records.getByRole("button", { name: "Export metadata", exact: true }).click();
      const metadata = JSON.parse(await readFile(await (await downloaded).path(), "utf8"));
      assert.equal(metadata.room_id, "room:");
      assert.equal(metadata.runs.length, 5); // Three sample records plus this workflow's two.
      assert.ok(metadata.runs.every((run) => run.zones.length === 3 && run.captured_at));
      // Compared on History, in the same visit.
      await page
        .locator(".desktop-sidebar")
        .getByRole("button", { name: "History", exact: true })
        .click();
      await page
        .getByRole("navigation", { name: "History views" })
        .getByRole("button", { name: "Compare runs", exact: true })
        .click();
      await page.getByRole("heading", { name: "Compare runs", exact: true }).waitFor();
      await page.locator('details[data-section="chart"] > summary').click();
      await page.getByRole("img", { name: /Recorded VWC and EC/ }).waitFor();
      await page
        .getByLabel("Previous run", { exact: true })
        .selectOption({ label: "Previous room run" });
      const previous = page.locator(".comparison-chart path").filter({ hasText: "Previous VWC" });
      await previous.waitFor();
      assert.ok((await previous.getAttribute("d"))?.length > 10, "Previous retained curve");
      for (const period of ["day", "week", "month", "run"]) {
        await page.getByLabel("Comparison history range", { exact: true }).selectOption(period);
        await page
          .getByText("Loading selected-zone Recorder history…", { exact: true })
          .waitFor({ state: "hidden" });
        await page.getByRole("img", { name: /Recorded VWC and EC/ }).waitFor();
        assert.ok((await page.locator(".comparison-chart path").count()) >= 4);
      }
      await page.getByLabel("Comparison history range", { exact: true }).selectOption("week");
      await page.getByLabel("Target reference", { exact: true }).selectOption("saved");
      await page
        .getByText("Loading selected-zone Recorder history…", { exact: true })
        .waitFor({ state: "hidden" });
      assert.ok(
        (await page.locator('[data-comparison-series="target-floor"]').count()) > 0,
        "Daily P3 reference is rendered",
      );
      assert.ok(
        (await page.locator('[data-comparison-series="target-vwc"]').count()) > 0,
        "Full daily VWC reference is rendered",
      );
      await noOverflow();
      await axe("run comparison");
      await page.evaluate(() => {
        document.activeElement?.blur();
        window.scrollTo(0, 0);
      });
      await page.screenshot({
        path: fileURLToPath(new URL("../../img/run-comparison.png", import.meta.url)),
        fullPage: true,
      });
      // Archived and restored in Settings; each room keeps its own records.
      await page.getByRole("button", { name: "Run records", exact: true }).click();
      await records.waitFor();
      const past = page
        .locator(".comparison-run-list article")
        .filter({ hasText: "Previous room run" });
      await past.getByRole("button", { name: "Archive", exact: true }).click();
      await past.waitFor({ state: "hidden" });
      await records.getByLabel("Include archived run records").check();
      await page
        .locator(".comparison-run-list article")
        .filter({ hasText: "Previous room run" })
        .getByRole("button", { name: "Restore", exact: true })
        .click();
      await page.locator("#desktop-room").selectOption("room:f1_");
      await page.waitForFunction(
        () => document.querySelectorAll(".comparison-run-list article").length >= 2,
      );
      assert.equal(
        await page
          .locator(".comparison-run-list article")
          .filter({ hasText: "Previous room run" })
          .count(),
        0,
      );
      assert.equal(
        await page
          .locator(".comparison-run-list article")
          .filter({ hasText: "Current room run" })
          .count(),
        0,
      );
      await open("history/compare");
      await page.getByRole("heading", { name: "Compare runs", exact: true }).waitFor();
      await page.setViewportSize({ width: 390, height: 844 });
      await noOverflow();
      await axe("mobile run comparison");
      await page.screenshot({ path: out + "visual-mobile-comparison.png", fullPage: true });
      await page.setViewportSize({ width: 1600, height: 1100 });
    },
  );
  await check("Mobile target editing stays usable without page overflow", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await fresh("plan/targets");
    await field("p3_emergency_vwc_threshold").fill("40");
    await noOverflow();
    await axe("mobile setpoints");
    await page.screenshot({ path: out + "visual-mobile-setpoints.png", fullPage: true });
    await page.setViewportSize({ width: 1600, height: 1100 });
  });
  assert.deepEqual(forbidden, [], "Demo attempted external/API traffic");
  assert.deepEqual(errors, [], "Browser exceptions");
} finally {
  await writeFile(
    out + "steering-visual-verification.json",
    JSON.stringify({ checks, forbidden, errors, accessibility }, null, 2),
  );
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
if (checks.some((c) => c.status === "fail")) process.exitCode = 1;
