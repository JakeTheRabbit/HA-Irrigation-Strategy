/** Independent compiled-workspace browser contracts. All actions remain isolated demo/fixtures. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
/** Grow plan & presets arms at the room's next lights-on and names it (I4). */
const ARM_PLAN = /^Arm at (lights-on, \w{3} \d{1,2}:\d{2}( [ap]m)?|next lights-on)$/;
const out = fileURLToPath(new URL("../../output/playwright/", import.meta.url));
await mkdir(out, { recursive: true });
// CI must exercise the checked-out artifact without relying on a developer's server.
let server;
let url = process.env.WORKSPACE_URL;
if (!url) {
  const dashboard = await readFile(new URL("../../www/dashboard.html", import.meta.url));
  server = createServer((req, res) => {
    const pathname = new URL(req.url, "http://localhost").pathname;
    if (pathname !== "/" && pathname !== "/dashboard.html") {
      res.writeHead(404);
      res.end("Not found");
      return;
    }
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
    res.end(dashboard);
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  server.unref();
  url = `http://127.0.0.1:${server.address().port}/dashboard.html?demo=1`;
}
const origin = new URL(url).origin;
const browser = await chromium.launch({
  headless: true,
  ...(process.platform === "win32" ? { channel: "chrome" } : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
});
const forbidden = [],
  pageErrors = [],
  checks = [],
  accessibility = [];
await context.route("**/*", (route) => {
  const u = new URL(route.request().url());
  if (u.origin !== origin || u.pathname.startsWith("/api/")) {
    forbidden.push(u.origin + u.pathname);
    return route.abort();
  }
  return route.continue();
});
const page = await context.newPage();
page.setDefaultTimeout(10000);
page.on("dialog", (dialog) => dialog.accept());
page.on("pageerror", (e) => pageErrors.push(e.message));
async function visible(locator) {
  await locator.waitFor({ state: "visible", timeout: 10000 });
}
let freshId = 0;
async function fresh(route) {
  const target = new URL(url);
  target.searchParams.set("verification", String(++freshId));
  target.hash = "/" + route;
  await page.goto(target.toString(), { waitUntil: "networkidle" });
}
/** Opens a page from the tree menu: its section opened first if it is closed. */
async function tree(section, label, target = page) {
  const nav = target.locator('.desktop-sidebar nav[aria-label="Main navigation"]');
  const head = nav.locator(`button[data-nav-section="${section}"]`);
  if ((await head.getAttribute("aria-expanded")) === "false") await head.click();
  await nav.getByRole("link", { name: label, exact: true }).click();
}
/** A menu entry's own page, as the five-entry menu opened it before the tree. */
const ENTRY_PAGES = {
  Irrigation: ["plan", "Current day"],
  Plan: ["plan", "Current day"],
  Settings: ["settings", "Dashboards & display"],
};
async function navigate(label, target = page) {
  if (label === "Today") {
    await target.evaluate(() => (location.hash = "#/today"));
    return;
  }
  await tree(...ENTRY_PAGES[label], target);
}
/** A page under a menu entry, by its name in the tree. */
const VIEW_PAGES = { "Equipment/Setup": ["equipment", "Setup: pumps & valves"] };
async function navigateTo(section, view, target = page) {
  await tree(...VIEW_PAGES[`${section}/${view}`], target);
}
/** The room page's heading: the room's name. */
const roomHeading = (target = page) =>
  target.getByRole("heading", { level: 1, name: /^Room [AB]$/ });
/** Irrigation › Calendar keeps the steering balance, endpoint profiles and recipes together. */
async function openPlanner(tab = "Steering balance", target = page) {
  const advanced = target.locator("details.plan-advanced");
  await visible(advanced);
  if ((await advanced.getAttribute("open")) === null) await advanced.locator("> summary").click();
  await target
    .getByRole("tablist", { name: "Grow planner view" })
    .getByRole("tab", { name: tab, exact: true })
    .click();
  if (tab === "Steering balance") await visible(target.locator("#steering-balance"));
}
async function navigateSchedule(target = page) {
  await tree("plan", "Grow plan & presets", target);
  await openPlanner("Steering balance", target);
}
async function exported() {
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  return JSON.parse(await readFile(await (await download).path(), "utf8")).plan;
}
function block(plan, zone, day) {
  return plan.zones
    .find((z) => z.zone_id === zone)
    .schedule.find((s) => day >= s.start_day && day <= s.end_day);
}
async function setBalance(value) {
  await page.locator("#steering-balance").fill(String(value));
}
async function noOverflow() {
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
    true,
    "Document overflow",
  );
}
// Colours animate when the theme changes (transition-colors). Contrast measured mid-transition
// fails at random, so let the running finite animations and transitions finish (at most 2 s: a
// paused one never does), then two frames.
async function settle() {
  await page.evaluate(async () => {
    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const running = document
      .getAnimations()
      .filter((a) => a.playState === "running" && a.effect?.getTiming().iterations !== Infinity);
    await Promise.race([Promise.all(running.map((a) => a.finished.catch(() => {}))), wait(2000)]);
    for (let frame = 0; frame < 2; frame++)
      await Promise.race([new Promise((resolve) => requestAnimationFrame(resolve)), wait(100)]);
  });
}
async function axe(label) {
  await settle();
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  accessibility.push({ label, violations: result.violations });
  assert.deepEqual(
    result.violations.map((v) => v.id),
    [],
    label + " axe",
  );
}
async function check(name, run) {
  try {
    await run();
    checks.push({ name, status: "pass" });
    console.log("PASS " + name);
  } catch (e) {
    checks.push({ name, status: "fail", error: e.stack });
    console.error("FAIL " + name + ": " + e.message);
    await page.screenshot({
      path: out + "workspace-failure-" + checks.length + ".png",
      fullPage: true,
    });
  }
}
async function pause() {
  const pause = page.getByRole("button", {
    name: "Watering on: switch watering off…",
    exact: true,
  });
  if (await pause.count()) {
    await pause.click();
    await page.getByRole("button", { name: /Apply \d+ change/ }).click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
  }
}
async function saveSetup(target = page) {
  await target.getByRole("button", { name: "Review configuration", exact: true }).click();
  await visible(target.getByRole("heading", { name: "Review room configuration", exact: true }));
  await target.getByRole("button", { name: "Save configuration", exact: true }).click();
  await target.getByRole("dialog").waitFor({ state: "hidden", timeout: 10000 });
}
/** Mocked live Home Assistant with one room, so a check can read the exact setup_save payload.
 * `calls` records every service the page reached, which is how "never actuates" is proven. */
async function liveSetup(run, history = false, blockers = []) {
  const live = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const calls = [];
  const stamp = new Date().toISOString();
  const entity = (entity_id, state, attributes = {}) => ({
    entity_id,
    state,
    attributes,
    last_updated: stamp,
    last_changed: stamp,
  });
  const states = [
    entity("sensor.crop_steering_room_b_engine_config", "ready", {
      prefix: "room_b_",
      slug: "room_b",
      num_zones: 1,
      friendly_name: "Room B engine config",
      enable_flag: "switch.crop_steering_room_b_engine_enabled",
    }),
    entity("switch.crop_steering_room_b_engine_enabled", "off"),
  ];
  const room = {
    entry_id: "sizing-fixture-entry",
    revision: 1,
    room_name: "Room B",
    prefix: "room_b_",
    slug: "room_b",
    active: true,
    num_zones: 1,
    active_zone_ids: [1],
    zones: [
      {
        id: 1,
        name: "Zone 1",
        active: true,
        valve: "switch.fixture_valve",
        vwc_sensors: [],
        ec_sensors: [],
        plant_count: 12,
        substrate_volume: 6,
        drippers_per_plant: 1,
        dripper_flow_rate: 4,
      },
    ],
    hardware: {},
    safety: { ready: blockers.length === 0, blockers },
  };
  await live.addInitScript(() =>
    localStorage.setItem("hassTokens", JSON.stringify({ access_token: "sizing-fixture-token" })),
  );
  await live.route("**/*", (route) => {
    const req = route.request(),
      u = new URL(req.url());
    if (u.origin !== origin) {
      forbidden.push(u.origin + u.pathname);
      return route.abort();
    }
    if (!u.pathname.startsWith("/api/")) return route.continue();
    const reply = (data, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (u.pathname === "/api/states") return reply(states);
    // Home Assistant's time zone is a read, not a service: answer with the browser's own zone.
    if (u.pathname === "/api/config")
      return reply({ time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone });
    const action = u.pathname.split("/").at(-1),
      data = req.postDataJSON();
    calls.push({ action, data });
    if (history && action === "history_connection_get")
      return reply({
        service_response: {
          room_id: "room:room_b_",
          revision: 1,
          connection: { source: "recorder" },
          has_password: true,
          has_token: true,
        },
      });
    if (action === "setup_read")
      return reply({
        service_response: {
          api_version: 1,
          capabilities: { create: true, save: true, remove: true, stable_zone_ids: true },
          rooms: [room],
          candidates: [],
          limits: { max_zones: 24 },
        },
      });
    if (action === "setup_save") {
      if (blockers.length) return reply({ message: blockers.join("; ") }, 500);
      Object.assign(room, { zones: data.zones, revision: room.revision + 1 });
      return reply({ changed_states: [], service_response: room });
    }
    return reply({ message: "The sizing fixture has no such service" }, 400);
  });
  const lp = await live.newPage();
  lp.setDefaultTimeout(10000);
  lp.on("pageerror", (e) => pageErrors.push(e.message));
  try {
    await lp.goto(origin + "/dashboard.html?room=room_b#/setup");
    await visible(lp.locator("#room-name"));
    assert.equal(
      await lp.locator("#room-plumbing").count(),
      0,
      "An integration that does not report the plumbing capability must not be asked about it",
    );
    await run(lp, calls);
    assert.deepEqual(
      // The dashboard asks once per visit whether there is anything new to show: not the helpers.
      [...new Set(calls.map((call) => call.action))].filter((a) => a !== "whats_new_get").sort(),
      history
        ? ["history_connection_get", "setup_read", "setup_save"]
        : ["setup_read", "setup_save"],
      "Sizing helpers must reach no service except reading and saving the setup",
    );
  } finally {
    await live.close();
  }
}
const savedZone = (calls) => calls.findLast((call) => call.action === "setup_save").data.zones[0];
try {
  await check(
    "A setup refusal names the watering blocker and retains the draft for retry",
    async () => {
      const reason =
        "input_boolean.f2_control_enabled must read OFF before changing setup (it is ON: turn it off, then submit again)";
      await liveSetup(
        async (lp, calls) => {
          await lp.locator("#room-name").fill("My edited room");
          await lp.getByRole("button", { name: "Review configuration", exact: true }).click();
          const dialog = lp.getByRole("dialog");
          await visible(
            dialog.getByText("Equipment and sizing changes need watering off", { exact: true }),
          );
          await dialog.getByRole("button", { name: "Save configuration", exact: true }).click();
          await visible(dialog.getByRole("alert"));
          assert.equal(await dialog.getByRole("alert").innerText(), reason);
          assert.equal(calls.filter((c) => c.action === "setup_save").length, 1);
          await dialog.getByRole("button", { name: "Back to editing", exact: true }).click();
          assert.equal(await lp.locator("#room-name").inputValue(), "My edited room");
        },
        false,
        [reason],
      );
    },
  );
  await check(
    "Planning slider changes both the VWC and the EC setpoints; exact day and week edits preserve neighboring days and other zones",
    async () => {
      // An old address: the grow planner is Plan › Schedule, its balance under Advanced.
      await fresh("grow-plan");
      await openPlanner();
      await page.getByRole("button", { name: "Days", exact: true }).click();
      await page.locator("#preview-grow-day").fill("16");
      // The balance blends the two endpoints: the setpoints at it, beside the grid.
      const at = (text) =>
        page
          .locator(".plan-cell-table tbody tr")
          .filter({ hasText: text })
          .locator(".plan-cell-at")
          .allInnerTexts();
      const initial = await exported(),
        oldVwc = await at("VWC"),
        oldEc = await at("EC");
      assert.ok(oldVwc.length && oldEc.length, "VWC and EC setpoints move with the balance");
      await setBalance(90);
      assert.notDeepEqual(await at("VWC"), oldVwc);
      assert.notDeepEqual(await at("EC"), oldEc);
      let plan = await exported();
      assert.equal(block(plan, 1, 16).bias, 90);
      assert.equal(block(plan, 1, 15).bias, block(initial, 1, 15).bias);
      assert.equal(block(plan, 1, 17).bias, block(initial, 1, 17).bias);
      assert.deepEqual(plan.zones[1], initial.zones[1]);
      await page.getByRole("button", { name: "Weeks", exact: true }).click();
      await setBalance(30);
      plan = await exported();
      for (let d = 15; d <= 21; d++) assert.equal(block(plan, 1, d).bias, 30);
      assert.equal(block(plan, 1, 14).bias, 20);
      assert.equal(block(plan, 1, 22).bias, 70);
      await page.screenshot({ path: out + "workspace-grow-planner.png", fullPage: true });
    },
  );
  await check(
    "Typing a balance into a grid cell updates that cell and the slider; preview, Esc, rejection, arrows and Mixed weeks",
    async () => {
      await fresh("plan/schedule");
      await openPlanner();
      const initial = await exported();
      const cell = (zone, unit) =>
        page.getByRole("textbox", {
          name: `Zone ${zone}, ${unit}, steering balance percent generative`,
          exact: true,
        });
      const panel = page.locator(".plan-cell");
      const message = page.locator("#plan-cell-message");
      // Week 5 is days 29–35, inside the demo's 70% block for days 15–35.
      await cell(1, "week 5").click();
      await page.keyboard.type("55");
      assert.match(await panel.innerText(), /Preview at 55%, now 70%/);
      // The panel shows the page's own interpolation: P1 64 → 60 % VWC at 55% is 62, now 61.
      const p1 = panel.locator("tr").filter({ hasText: "Peak VWC target" });
      assert.equal((await p1.locator(".plan-cell-at").innerText()).trim(), "62");
      assert.match(await p1.innerText(), /% VWC\s+64\s+61\s+62\s+60/);
      assert.match(await panel.innerText(), /P3 dryback target % of peak/);
      assert.match(await panel.innerText(), /Week 4 → week 5: 70% → 55% \(−15 points\)/);
      assert.match(
        await panel.locator(".plan-cell-live").innerText(),
        /VWC\s+[\d.]+%\s+EC\s+[\d.]+ mS\/cm\s+Water today\s+[\d.]+ L/,
      );
      // The whole-grow sparkline draws the typed week's seven days.
      assert.equal(await panel.locator("rect.plan-cell-edit").count(), 7);
      assert.equal(
        await page.locator("#steering-balance").inputValue(),
        "70",
        "Typing applies nothing",
      );
      await page.keyboard.press("Escape");
      assert.equal(await cell(1, "week 5").inputValue(), "70%");
      await page.keyboard.type("150");
      await page.keyboard.press("Enter");
      assert.equal(await cell(1, "week 5").getAttribute("aria-invalid"), "true");
      assert.equal(await message.innerText(), "150 is outside 0–100.");
      await axe("grow-plan-cell-invalid");
      await page.keyboard.press("Escape");
      await page.keyboard.type("55");
      await page.keyboard.press("Enter");
      assert.equal(await cell(1, "week 5").inputValue(), "55%");
      assert.equal(await page.locator("#steering-balance").inputValue(), "55");
      let plan = await exported();
      for (let d = 29; d <= 35; d++) assert.equal(block(plan, 1, d).bias, 55);
      assert.equal(block(plan, 1, 28).bias, 70);
      assert.equal(block(plan, 1, 36).bias, 40);
      assert.deepEqual(plan.zones.slice(1), initial.zones.slice(1));
      // Both controls edit the same block.
      await setBalance(65);
      assert.equal(await cell(1, "week 5").inputValue(), "65%");
      // Arrows move between cells, and leaving a cell applies what was typed there.
      await cell(1, "week 5").click();
      await page.keyboard.press("ArrowRight");
      await page.keyboard.type("45");
      await page.keyboard.press("ArrowDown");
      assert.equal(await cell(1, "week 6").inputValue(), "45%");
      assert.equal(
        await page.evaluate(() => document.activeElement?.getAttribute("aria-label")),
        "Zone 2, week 6, steering balance percent generative",
      );
      await page.keyboard.type("4.5");
      await page.keyboard.press("Tab");
      assert.equal(
        await page.evaluate(() => document.activeElement?.getAttribute("aria-label")),
        "Zone 2, week 7, steering balance percent generative",
      );
      assert.match(await message.innerText(), /Zone 2, week 6: “4\.5” was not applied/);
      assert.equal(await cell(2, "week 6").inputValue(), "40%");
      // A day edit makes week 3 Mixed; one entry then sets exactly its seven days.
      await page.getByRole("button", { name: "Days", exact: true }).click();
      await cell(1, "day 16").click();
      await page.keyboard.type("90");
      await page.keyboard.press("Enter");
      await page.getByRole("button", { name: "Weeks", exact: true }).click();
      assert.equal(await cell(1, "week 3").inputValue(), "");
      assert.equal(await cell(1, "week 3").getAttribute("placeholder"), "Mixed");
      await cell(1, "week 3").click();
      await page.keyboard.type("30");
      await page.keyboard.press("Enter");
      plan = await exported();
      for (let d = 15; d <= 21; d++) assert.equal(block(plan, 1, d).bias, 30);
      assert.equal(block(plan, 1, 14).bias, 20);
      assert.equal(block(plan, 1, 22).bias, 70);
      await page.emulateMedia({ colorScheme: "dark" });
      await page.waitForFunction(() => document.documentElement.classList.contains("dark"));
      await cell(1, "week 4").click();
      await page.keyboard.type("5");
      await axe("grow-plan-cell-dark");
      await page.emulateMedia({ colorScheme: "light" });
    },
  );
  await check(
    "Planner draft guards navigation, hash changes, browser back and selected room; keep editing preserves draft",
    async () => {
      await fresh("plan/schedule");
      await openPlanner();
      await setBalance(83);
      // Current day and Grow plan are pages of their own in the tree menu: leaving the plan with a
      // draft asks first, and Keep editing stays on it with the draft.
      await tree("plan", "Current day");
      await visible(page.getByRole("heading", { name: "Discard unsaved workspace changes?" }));
      await page.getByRole("button", { name: "Keep editing" }).click();
      assert.equal(new URL(page.url()).hash, "#/plan/schedule");
      assert.equal(await page.locator("#steering-balance").inputValue(), "83");
      await navigate("Today");
      await visible(page.getByRole("heading", { name: "Discard unsaved workspace changes?" }));
      await page.getByRole("button", { name: "Keep editing" }).click();
      assert.equal(await page.locator("#steering-balance").inputValue(), "83");
      await page.evaluate(() => (location.hash = "/zones"));
      await visible(page.getByRole("heading", { name: "Discard unsaved workspace changes?" }));
      await page.getByRole("button", { name: "Keep editing" }).click();
      assert.equal(new URL(page.url()).hash, "#/plan/schedule");
      await page.locator('.desktop-sidebar .room-tree-row[data-room="room:room_b_"]').click();
      await visible(page.getByRole("heading", { name: "Discard unsaved workspace changes?" }));
      await page.getByRole("button", { name: "Keep editing" }).click();
      assert.equal(
        await page.locator('.desktop-sidebar .room-tree-row[data-room="room:"]').getAttribute("data-selected"),
        "true",
      );
      await navigate("Today");
      await page.getByRole("button", { name: "Discard and continue" }).click();
      await visible(roomHeading());
      await navigateSchedule();
      assert.notEqual(await page.locator("#steering-balance").inputValue(), "83");
      // Use a clean history entry: prior refused hash changes restore their own entries.
      await fresh("today");
      await navigateSchedule();
      await setBalance(81);
      await page.goBack();
      await visible(page.getByRole("heading", { name: "Discard unsaved workspace changes?" }));
      await page.getByRole("button", { name: "Keep editing" }).click();
      assert.equal(await page.locator("#steering-balance").inputValue(), "81");
    },
  );
  await check("Endpoint profile edits, duplicate and save/arm/disarm lifecycle", async () => {
    await fresh("plan/schedule");
    await openPlanner("Endpoint profiles");
    await page.getByRole("button", { name: "Duplicate profile" }).click();
    await page.locator("#profile-name").fill("Verification profile");
    await page.locator("#vegetative-p1_target_vwc").fill("66");
    await page.locator("#generative-p1_target_vwc").fill("62");
    // The same value at both endpoints: a target the balance does not move.
    await page.locator("#vegetative-p2_vwc_threshold").fill("57");
    await page.locator("#generative-p2_vwc_threshold").fill("57");
    const plan = await exported(),
      profile = plan.profiles.find((p) => p.name === "Verification profile");
    assert.equal(profile.vegetative.p2_vwc_threshold, profile.generative.p2_vwc_threshold);
    assert.equal(profile.vegetative.p1_target_vwc, 66);
    assert.equal(profile.generative.p1_target_vwc, 62);
    await openPlanner("Steering balance");
    await page.getByRole("button", { name: "Review & save", exact: true }).click();
    await visible(page.getByRole("heading", { name: "Review grow plan", exact: true }));
    assert.match(await page.getByRole("dialog").innerText(), /Room A only/);
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await visible(page.getByRole("button", { name: ARM_PLAN }));
    assert.equal(
      await page.getByRole("button", { name: ARM_PLAN }).isEnabled(),
      true,
    );
    await page.getByRole("button", { name: ARM_PLAN }).click();
    await page.getByRole("button", { name: "Arm for next lights-on", exact: true }).click();
    await visible(page.getByRole("button", { name: "Disarm plan", exact: true }));
    assert.equal(await page.locator("#steering-balance").isDisabled(), true);
    const gridCell = page.getByRole("textbox", {
      name: "Zone 1, week 2, steering balance percent generative",
    });
    assert.equal(await gridCell.isEditable(), false, "An armed plan's grid is read only");
    await page.getByRole("button", { name: "Disarm plan", exact: true }).click();
    await page.getByRole("button", { name: "Confirm disarm", exact: true }).click();
    await visible(page.getByRole("button", { name: ARM_PLAN }));
    assert.equal(await page.locator("#steering-balance").isEnabled(), true);
    assert.equal(await gridCell.isEditable(), true);
  });
  await check("Plan state says why a saved plan is or is not live, at 1440 and 390px", async () => {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await fresh("plan/schedule");
      await openPlanner();
      const label = page.locator(".plan-state"),
        why = page.locator(".plan-state-why");
      assert.equal(await label.innerText(), "Draft");
      assert.match(await why.innerText(), /^Saved, not running\./);
      await page.getByRole("button", { name: ARM_PLAN }).click();
      await page.getByRole("button", { name: "Arm for next lights-on", exact: true }).click();
      await visible(page.getByRole("button", { name: "Disarm plan", exact: true }));
      await label.filter({ hasText: /^Scheduled$/ }).waitFor({ state: "visible" });
      assert.match(await why.innerText(), /^Armed for the next lights-on\./);
      await noOverflow();
      await page.screenshot({ path: out + `workspace-plan-state-${width}.png`, fullPage: true });
      await page.getByRole("button", { name: "Disarm plan", exact: true }).click();
      await page.getByRole("button", { name: "Confirm disarm", exact: true }).click();
      await visible(page.getByRole("button", { name: ARM_PLAN }));
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check(
    "Setup room-change discard resets selected configuration and stale draft",
    async () => {
      // An old address: Rooms and setup is Equipment › Setup.
      await fresh("setup");
      await visible(page.locator("#room-name"));
      await page.locator("#room-name").fill("Must be discarded");
      await page.locator('.desktop-sidebar .room-tree-row[data-room="room:room_b_"]').click();
      await visible(page.getByRole("heading", { name: "Discard unsaved workspace changes?" }));
      await page.getByRole("button", { name: "Discard and continue" }).click();
      assert.equal(await page.locator("#room-name").inputValue(), "Room B");
      assert.equal(await page.locator("#setup-room option:checked").innerText(), "Room B");
    },
  );
  await check(
    "Setup maps a new zone, saves sizing, archives/restores the stable zone ID, and retains other room mappings",
    async () => {
      await fresh("plan/schedule");
      await openPlanner();
      await pause();
      await navigateTo("Equipment", "Setup");
      await visible(page.locator("#room-name"));
      await page.getByRole("button", { name: "Add zone", exact: true }).click();
      await page.getByRole("button", { name: "Map Zone 4 valve", exact: true }).click();
      await page
        .getByRole("textbox", { name: "Search Zone 4 valve entities" })
        .fill("switch.demo_spare_1");
      await page.locator(".mapping-result").filter({ hasText: "switch.demo_spare_1" }).click();
      await page.getByRole("button", { name: "Map Zone 4 VWC probes", exact: true }).click();
      await page
        .getByRole("textbox", { name: "Search Zone 4 VWC probes entities" })
        .fill("sensor.crop_steering_vwc_zone_1");
      await page
        .locator(".mapping-result")
        .filter({ hasText: "sensor.crop_steering_vwc_zone_1" })
        .click();
      await page.getByRole("button", { name: "Done", exact: true }).click();
      await page.locator("#zone-4-plant_count").fill("12");
      await page.locator("#zone-4-substrate_volume").fill("8");
      await saveSetup();
      assert.equal(
        await page.getByRole("textbox", { name: "Zone 4 name", exact: true }).count(),
        1,
      );
      const zone = page
        .locator(".setup-zone")
        .filter({ has: page.getByRole("textbox", { name: "Zone 4 name", exact: true }) });
      await zone.getByRole("button", { name: "Remove zone", exact: true }).click();
      await saveSetup();
      assert.equal(
        await page.getByRole("textbox", { name: "Zone 4 name", exact: true }).count(),
        0,
      );
      await page.locator(".archived-zones summary").click();
      await page.getByRole("button", { name: "Restore zone", exact: true }).click();
      await saveSetup();
      assert.equal(await page.locator("#zone-4-plant_count").inputValue(), "12");
      await page.locator("#setup-room").selectOption({ label: "Room B" });
      assert.equal(
        await page.getByRole("textbox", { name: "Zone 4 name", exact: true }).count(),
        0,
      );
      assert.equal(await page.locator("#zone-1-plant_count").inputValue(), "36");
      await navigateSchedule();
      await page.getByRole("button", { name: "Update zones from setup", exact: true }).click();
      assert.equal(
        await page.locator(".calendar-label").filter({ hasText: "Zone 4" }).count(),
        1,
        "A new active setup zone must be configurable in an existing plan",
      );
      await page.getByRole("button", { name: "Review & save", exact: true }).click();
      await page.getByRole("button", { name: "Save draft", exact: true }).click();
      await page.getByRole("dialog").waitFor({ state: "hidden" });
      const synced = await exported();
      assert.equal(synced.zones.length, 4);
    },
  );
  await check(
    "Setup creates a room without actuating equipment, then archives/restores it with stable identifiers",
    async () => {
      await fresh("setup");
      await visible(page.locator("#room-name"));
      await page.getByRole("button", { name: "Add room", exact: true }).first().click();
      await page.locator("#room-name").fill("Verification room");
      await page.getByRole("button", { name: "Map Zone 1 valve", exact: true }).click();
      await page
        .getByRole("textbox", { name: "Search Zone 1 valve entities" })
        .fill("switch.demo_spare_2");
      await page.locator(".mapping-result").filter({ hasText: "switch.demo_spare_2" }).click();
      // A new room has to SAY how it is plumbed; nothing is guessed from empty fields.
      const review = page.getByRole("button", { name: "Review configuration", exact: true });
      await visible(page.getByText("Choose how this room is plumbed.", { exact: true }));
      assert.ok(await review.isDisabled(), "A room with no plumbing answer must not be reviewable");
      // "It has a pump" with no pump chosen is the mistake 2.18.0 saved and then ran dry.
      await page.locator("#room-plumbing").selectOption("pump_valves");
      await visible(page.getByText(/plumbed with a pump: choose the pump switch/));
      assert.ok(await review.isDisabled(), "A pumped room with no pump must not be reviewable");
      await visible(page.getByRole("button", { name: "Map Room pump", exact: true }));
      assert.equal(
        await page.getByRole("button", { name: "Map Mainline valve", exact: true }).count(),
        0,
        "A layout without a main-line valve must not offer one",
      );
      // A one-switch room says so, and is then complete with nothing but its valve.
      await page.locator("#room-plumbing").selectOption("valves_only");
      assert.equal(
        await page.getByRole("button", { name: "Map Room pump", exact: true }).count(),
        0,
      );
      await page.getByRole("button", { name: "Review configuration", exact: true }).click();
      await visible(page.getByText("Plumbing: Zone valves only", { exact: true }));
      await page.getByRole("button", { name: "Save configuration", exact: true }).click();
      await page.getByRole("dialog").waitFor({ state: "hidden" });
      assert.equal(await page.locator("#room-plumbing").inputValue(), "valves_only");
      const id = await page.locator("#setup-room").inputValue();
      assert.ok(id);
      await page.getByRole("button", { name: "Archive room", exact: true }).click();
      await page.getByRole("textbox", { name: "Type the room name" }).fill("Verification room");
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Archive room", exact: true })
        .click();
      await page.getByRole("dialog").waitFor({ state: "hidden" });
      assert.equal(await page.locator("#setup-room").inputValue(), id);
      await page.getByRole("button", { name: "Restore room", exact: true }).click();
      await saveSetup();
      assert.equal(await page.locator("#setup-room").inputValue(), id);
      assert.equal(await page.locator("#room-name").inputValue(), "Verification room");
    },
  );
  await check(
    "The setup wizard walks a new room to Switch on, which waits for every safety check and names it",
    async () => {
      await fresh("setup");
      await visible(page.locator("#room-name"));
      await page.getByRole("button", { name: "Add room", exact: true }).first().click();
      await page.locator("#room-name").fill("Wizard room");
      await page.getByRole("button", { name: "Map Zone 1 valve", exact: true }).click();
      await page
        .getByRole("textbox", { name: "Search Zone 1 valve entities" })
        .fill("switch.demo_spare_4");
      await page.locator(".mapping-result").filter({ hasText: "switch.demo_spare_4" }).click();
      await page.locator("#room-plumbing").selectOption("valves_only");
      await saveSetup();
      const wizard = page.getByRole("region", { name: "Setup wizard" });
      await visible(wizard);
      const switchOn = wizard.getByRole("button", { name: "Switch on", exact: true });
      await visible(wizard.getByText("Waiting for Probes: Zone 1: map a moisture probe"));
      assert.ok(await switchOn.isDisabled(), "Switch on must wait for a moisture probe");

      await page.getByRole("button", { name: "Map Zone 1 VWC probes", exact: true }).click();
      await page
        .getByRole("textbox", { name: "Search Zone 1 VWC probes entities" })
        .fill("vwc_zone_1");
      await page.locator(".mapping-result").first().click();
      await page.keyboard.press("Escape");
      await saveSetup();
      await visible(wizard.getByText("Waiting for Test shot: Zone 1: run a test shot"));
      assert.ok(await switchOn.isDisabled(), "Switch on must wait for a test shot");

      await wizard.getByRole("button", { name: "Test shot · Zone 1", exact: true }).click();
      await visible(wizard.getByText(/Watch a dripper on Zone 1/));
      assert.ok(await switchOn.isDisabled(), "Switch on must wait for water to be seen");
      await wizard.getByRole("button", { name: "Yes", exact: true }).click();
      await visible(wizard.getByText("Water seen.", { exact: true }));
      assert.ok(!(await switchOn.isDisabled()), "Every safety check passed: Switch on is enabled");
      await switchOn.click();
      await wizard.waitFor({ state: "hidden" });
      // The first-run tour runs once, straight after Switch on, over the real pages.
      const tour = page.getByRole("dialog", { name: "Today" });
      await visible(tour.getByText("Stop 1 of 5"));
      assert.equal(new URL(page.url()).hash, "#/today");
      await noOverflow();
      const stops = [
        ["Plan", "#/plan/targets"],
        // The tour's old History address lands on the Explorer.
        ["History", "#/history/explorer"],
        ["Equipment", "#/equipment/probes"],
        ["Help", "#/help"],
      ];
      for (const [title, hash] of stops) {
        await page.locator(".tour").getByRole("button", { name: "Next", exact: true }).click();
        await visible(page.getByRole("dialog", { name: title }));
        assert.equal(new URL(page.url()).hash, hash);
      }
      await page.locator(".tour").getByRole("button", { name: "Done", exact: true }).click();
      await page.locator(".tour").waitFor({ state: "detached" });
    },
  );
  await check(
    "The tour never starts by itself on a room already set up, and Help takes it again",
    async () => {
      await fresh("today");
      await visible(page.locator(".main-inner"));
      assert.equal(await page.locator(".tour").count(), 0, "No tour on an upgraded installation");
      await fresh("help");
      await page.getByRole("button", { name: "Show the tour again", exact: true }).click();
      await visible(page.getByRole("dialog", { name: "Today" }).getByText("Stop 1 of 5"));
      assert.equal(new URL(page.url()).hash, "#/today");
      await page.setViewportSize({ width: 390, height: 844 });
      await noOverflow();
      await page.locator(".tour").getByRole("button", { name: "End tour", exact: true }).click();
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.locator(".tour").waitFor({ state: "detached" });
    },
  );
  await check("Optional long history reads settings only after the grower expands it", async () => {
    await liveSetup(async (lp, calls) => {
      const history = lp.getByRole("group", { name: "Long history source" });
      const summary = lp.locator("details[aria-label='Long history source'] > summary");
      await visible(summary);
      assert.equal(
        calls.filter((call) => call.action === "history_connection_get").length,
        0,
        "Closed optional settings must send no history service",
      );
      await summary.click();
      await visible(lp.getByRole("button", { name: "Save history source", exact: true }));
      assert.equal(
        calls.filter((call) => call.action === "history_connection_get").length,
        1,
        "Opening optional settings reads its redacted configuration once",
      );
      await summary.click();
      assert.equal(await history.getAttribute("open"), null);
      await lp.locator("#zone-1-substrate_volume").fill("7");
      await saveSetup(lp);
      assert.equal(
        calls.filter((call) => call.action === "history_connection_get").length,
        1,
        "Saving unrelated sizing after closing must send no history service",
      );
    }, true);
  });
  await check(
    "Sizing units: gallons and GPH are typed and shown, litres and L/h are saved, and the choice is remembered",
    async () => {
      await fresh("setup");
      await visible(page.locator("#room-name"));
      const volume = page.locator("#zone-1-substrate_volume");
      assert.equal(await page.locator("#sizing-unit-volume").inputValue(), "metric");
      assert.equal(await page.locator("#sizing-unit-flow").inputValue(), "metric");
      assert.equal(await volume.inputValue(), "6");
      await page.locator("#sizing-unit-volume").selectOption("us");
      await visible(page.getByLabel("Pot volume · US gal per plant").first());
      assert.equal(await volume.inputValue(), "1.585", "6 L shown in US gallons");
      assert.equal(
        await page.locator("#zone-1-substrate_volume-note").innerText(),
        "= 6 L per plant, saved in litres",
      );
      assert.equal(
        await page.getByRole("button", { name: "Review configuration", exact: true }).isDisabled(),
        true,
        "Changing the unit alone must not change the draft",
      );
      await volume.fill("60");
      assert.equal(await volume.getAttribute("aria-invalid"), "true");
      assert.equal(
        await page.locator("#zone-1-substrate_volume-note").innerText(),
        "Pot volume must be 0.027–52.834 US gal (0.1–200 L).",
      );
      assert.equal(
        await page.getByRole("button", { name: "Review configuration", exact: true }).isDisabled(),
        true,
      );
      await volume.fill("5");
      assert.equal(
        await page.locator("#zone-1-substrate_volume-note").innerText(),
        "= 18.927 L per plant, saved in litres",
      );
      await fresh("setup");
      await visible(page.locator("#room-name"));
      assert.equal(
        await page.locator("#sizing-unit-volume").inputValue(),
        "us",
        "The unit choice is remembered in this browser",
      );
      await page.locator("#sizing-unit-volume").selectOption("metric");
      await liveSetup(async (lp, calls) => {
        await lp.locator("#sizing-unit-volume").selectOption("us");
        await lp.locator("#sizing-unit-flow").selectOption("us");
        await lp.locator("#zone-1-substrate_volume").fill("5");
        await lp.locator("#zone-1-dripper_flow_rate").fill("2");
        await lp.getByRole("button", { name: "Review configuration", exact: true }).click();
        assert.match(
          await lp.getByRole("dialog").innerText(),
          /12 plants × 18\.927 L \(5 US gal\) · 1 drippers per plant × 7\.571 L\/h \(2 US GPH\)/,
        );
        await lp.getByRole("button", { name: "Back to editing", exact: true }).click();
        await saveSetup(lp);
        const zone = savedZone(calls);
        assert.equal(zone.substrate_volume, 18.92705892, "5 US gal at exactly 3.785411784 L");
        assert.equal(zone.dripper_flow_rate, 7.570823568, "2 US GPH at exactly 3.785411784 L");
        assert.equal(zone.plant_count, 12);
        assert.equal(await lp.locator("#zone-1-substrate_volume").inputValue(), "5");
        await lp.locator("#sizing-unit-volume").selectOption("metric");
        assert.equal(await lp.locator("#zone-1-substrate_volume").inputValue(), "18.927");
      });
    },
  );
  await check(
    "Sizing units default from the unit system of the Home Assistant page embedding the dashboard",
    async () => {
      const embedded = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      await embedded.route("**/*", (route) => {
        const u = new URL(route.request().url());
        if (u.origin !== origin || u.pathname.startsWith("/api/")) {
          forbidden.push(u.origin + u.pathname);
          return route.abort();
        }
        if (u.pathname === "/workspace-units-parent.html")
          return route.fulfill({
            contentType: "text/html",
            body: `<!doctype html><html><body style="margin:0"><home-assistant></home-assistant><script>document.querySelector("home-assistant").hass={config:{unit_system:{volume:"gal",length:"mi"}}};</script><iframe title="Crop Steering" src="/dashboard.html?demo=1#/setup" style="border:0;width:100vw;height:100vh"></iframe></body></html>`,
          });
        return route.continue();
      });
      const ep = await embedded.newPage();
      ep.on("pageerror", (e) => pageErrors.push(e.message));
      try {
        await ep.goto(origin + "/workspace-units-parent.html");
        const frame = ep.frames().find((f) => f !== ep.mainFrame());
        assert.ok(frame);
        await visible(frame.locator("#room-name"));
        assert.equal(await frame.locator("#sizing-unit-volume").inputValue(), "us");
        assert.equal(await frame.locator("#sizing-unit-flow").inputValue(), "us");
        assert.equal(await frame.locator("#zone-1-dripper_flow_rate").inputValue(), "1.057");
      } finally {
        await embedded.close();
      }
    },
  );
  await check(
    "Substrate presets fill the pot volume in litres, show their litres, and leave custom typing alone",
    async () => {
      await fresh("setup");
      await visible(page.locator("#room-name"));
      const preset = page.locator("#zone-1-substrate-preset");
      assert.equal(await preset.inputValue(), "custom", "6 L is not a preset");
      const options = await preset.locator("option").allInnerTexts();
      assert.deepEqual(options, [
        "Custom · type the pot volume",
        "Rockwool 4 in cube · 10 × 10 × 6.5 cm · 0.65 L",
        "Rockwool Delta 10 · 10 × 10 × 10 cm · 1 L",
        "Rockwool Hugo · 15 × 15 × 14.2 cm · 3.2 L",
        "Nutrifield 0.9 gal · 15 × 15 × 16 cm · 3.37 L",
        "Nutrifield 1.5 gal · 18 × 18 × 18 cm · 5.8 L",
        "Rockwool uni-slab · 5 L",
        "Rockwool Mama block · 8 L",
        "Rockwool slab · 10 L",
        "1 gal pot (nominal) · 3.8 L",
        "2 gal pot (nominal) · 7.6 L",
        "3 gal pot (nominal) · 11.4 L",
        "5 gal pot (nominal) · 18.9 L",
        "7 gal pot (nominal) · 26.5 L",
        "5 L pot · 5 L",
        "10 L pot · 10 L",
        "15 L pot · 15 L",
        "20 L pot · 20 L",
      ]);
      await visible(
        page
          .getByText(
            "Nursery “trade” pots often hold less than their nominal gallons, and shot sizes are a percentage of this volume, so measure it if unsure.",
            { exact: true },
          )
          .first(),
      );
      await preset.selectOption("rockwool-4in");
      assert.equal(await page.locator("#zone-1-substrate_volume").inputValue(), "0.65");
      await page.locator("#zone-1-substrate_volume").fill("6.5");
      assert.equal(await preset.inputValue(), "custom", "Typing a volume is a custom entry");
      await page.locator("#zone-1-substrate_volume").fill("20");
      assert.equal(
        await preset.inputValue(),
        "custom",
        "A typed volume is never named as a preset, even when it matches one",
      );
      await liveSetup(async (lp, calls) => {
        await lp.locator("#zone-1-substrate-preset").selectOption("pot-5gal");
        assert.equal(await lp.locator("#zone-1-substrate_volume").inputValue(), "18.9");
        await saveSetup(lp);
        assert.equal(savedZone(calls).substrate_volume, 18.9, "Nominal 5 gal pot is 18.9 L");
        await lp.locator("#zone-1-substrate-preset").selectOption("rockwool-hugo");
        await saveSetup(lp);
        assert.equal(savedZone(calls).substrate_volume, 3.2, "Hugo block is 3.2 L");
        assert.equal(savedZone(calls).dripper_flow_rate, 4, "Other sizing is untouched");
      });
    },
  );
  await check(
    "Catch test works out L/h, rejects nonsense, fills only the dripper-flow draft and actuates nothing",
    async () => {
      await fresh("setup");
      await visible(page.locator("#room-name"));
      const catchTest = page.locator("#zone-1-catch-test");
      await catchTest.locator("summary").click();
      assert.match(await catchTest.innerText(), /never opens a valve or runs a pump/);
      const use = catchTest.getByRole("button", { name: /^Use / });
      assert.equal(await use.isDisabled(), true);
      await catchTest.getByLabel("Run time · s", { exact: true }).fill("0");
      await catchTest.getByLabel("Water from one dripper · mL", { exact: true }).fill("65");
      assert.equal(
        await page.locator("#zone-1-catch-test-result").innerText(),
        "Run time must be more than 0 seconds.",
      );
      assert.equal(
        await catchTest.getByLabel("Run time · s", { exact: true }).getAttribute("aria-invalid"),
        "true",
      );
      assert.equal(await use.isDisabled(), true);
      await catchTest.getByLabel("Run time · s", { exact: true }).fill("1");
      await catchTest.getByLabel("Water from one dripper · mL", { exact: true }).fill("5000");
      assert.match(
        await page.locator("#zone-1-catch-test-result").innerText(),
        /^That works out to 18000 L\/h, above the 50 L\/h maximum for a dripper\./,
      );
      assert.equal(await use.isDisabled(), true);
      await catchTest.getByLabel("Run time · s", { exact: true }).fill("60");
      await catchTest.getByLabel("Water from one dripper · mL", { exact: true }).fill("65");
      assert.equal(
        await page.locator("#zone-1-catch-test-result").innerText(),
        "Flow per dripper: 3.9 L/h",
      );
      assert.equal(
        await page.locator("#zone-1-dripper_flow_rate").inputValue(),
        "4",
        "Computing a result must not touch the draft",
      );
      await axe("setup-sizing-helpers");
      await page.getByRole("button", { name: "Use 3.9 L/h as Zone 1 dripper flow" }).click();
      assert.equal(await page.locator("#zone-1-dripper_flow_rate").inputValue(), "3.9");
      assert.equal(await page.locator("#zone-2-dripper_flow_rate").inputValue(), "4");
      await liveSetup(async (lp, calls) => {
        const live = lp.locator("#zone-1-catch-test");
        await live.locator("summary").click();
        await live.getByLabel("Run time · s", { exact: true }).fill("47");
        await live.getByLabel("Water from one dripper · mL", { exact: true }).fill("100");
        await lp.getByRole("button", { name: "Use 7.66 L/h as Zone 1 dripper flow" }).click();
        assert.equal(
          calls.some((call) => call.action === "setup_save"),
          false,
          "Using the result must not save anything by itself",
        );
        await saveSetup(lp);
        assert.equal(savedZone(calls).dripper_flow_rate, 7.66);
        assert.equal(savedZone(calls).substrate_volume, 6, "Other sizing is untouched");
      });
    },
  );
  await check(
    "Grow plan and setup are accessible and fit 390px with keyboard reachable mappings",
    async () => {
      await fresh("plan/schedule");
      await openPlanner();
      await axe("grow-plan-desktop");
      await page.setViewportSize({ width: 390, height: 844 });
      await noOverflow();
      await page.locator("#steering-balance").focus();
      await page.locator("#steering-balance").press("ArrowRight");
      await page.screenshot({ path: out + "workspace-grow-mobile.png", fullPage: true });
      await axe("grow-plan-mobile");
      await fresh("equipment/setup");
      await visible(page.locator("#room-name"));
      await noOverflow();
      await axe("setup-mobile");
      await page.getByRole("button", { name: "Map Zone 1 VWC probes", exact: true }).click();
      await page.getByRole("textbox", { name: "Search Zone 1 VWC probes entities" }).fill("vwc");
      await noOverflow();
      await axe("mapping-mobile");
      await page.screenshot({ path: out + "workspace-setup-mobile.png", fullPage: true });
    },
  );
  await check(
    "The AI assistant page shows each of the demo's seven brain states at 390 and 1440 px",
    async () => {
      const states = [
        ["rules", "Watering by rules"],
        ["acting", "AI assistant is acting"],
        ["advising", "AI assistant is advising only"],
        ["budget", "Daily AI limit reached"],
        ["not_answering", /^AI not answering/],
        ["no_key", "No working Anthropic key"],
        ["stale", "Readings too old to judge"],
      ];
      for (const width of [390, 1440]) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
        for (const [state, headline] of states) {
          const target = new URL(url);
          target.searchParams.set("verification", String(++freshId));
          target.searchParams.set("brain", state);
          target.hash = "/today/ai";
          await page.goto(target.toString(), { waitUntil: "networkidle" });
          await visible(page.getByRole("heading", { name: "AI assistant", exact: true }));
          await visible(page.locator(".brain-page .brain-status strong").getByText(headline));
          assert.equal(
            await page.getByLabel("Sample AI state", { exact: true }).inputValue(),
            state,
            `${state}: the switcher shows the state`,
          );
          // Today explains current permissions; the canonical editor lives in Settings.
          const powers = page.locator("[data-brain-powers]");
          assert.equal(
            await powers.getByRole("checkbox").count(),
            0,
            `${state}: contextual permissions are read only`,
          );
          assert.equal(
            await powers.locator("li").count(),
            8,
            `${state}: all eight permissions remain visible`,
          );
          for (const label of ["Start the next phase early", "Tune shot sizes"])
            await visible(powers.getByText(label, { exact: true }));
          await visible(powers.getByRole("link", { name: "Manage permissions" }));
          await noOverflow();
          await axe(`brain-${state}-${width}`);
          await page.screenshot({
            path: out + `workspace-brain-${state}-${width}.png`,
            fullPage: true,
          });
        }
      }
      // The switcher moves the header chip with the page, with no reload.
      await page.getByLabel("Sample AI state", { exact: true }).selectOption("budget");
      await visible(page.locator(".brain-chip").getByText("AI paused: budget"));
      // The same permission has one editor in Settings: its judge's switch, written at once with Undo.
      await page
        .locator("[data-brain-powers]")
        .getByRole("link", { name: "Manage permissions" })
        .click();
      const tune = page.getByRole("switch", { name: "Shot sizes in Room A", exact: true });
      assert.equal(await tune.getAttribute("aria-checked"), "false");
      await tune.click();
      await visible(
        page.locator("[data-sonner-toast]").filter({ hasText: /^Shot sizes on in Room A\. Written and read back/ }),
      );
      assert.equal(await tune.getAttribute("aria-checked"), "true", "Permission reads back enabled");
      await page.setViewportSize({ width: 1440, height: 1000 });
    },
  );
  await check(
    "Strict response-bearing API contract, revision conflict draft retention, and active/stale plan overlay",
    async () => {
      const live = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      const apiCalls = [],
        states = {};
      let failSave = false,
        deferRead = false,
        releaseRead,
        readStarted;
      const stamp = () => new Date().toISOString();
      const put = (id, state, attributes = {}) =>
        (states[id] = {
          entity_id: id,
          state: String(state),
          attributes,
          last_updated: stamp(),
          last_changed: stamp(),
        });
      const values = {
        dryback_target: 10,
        p1_target_vwc: 64,
        p2_vwc_threshold: 54,
        p1_initial_shot_size: 6,
        p2_shot_size: 4,
        p3_emergency_vwc_threshold: 35,
        p3_emergency_shot_size: 3,
        ec_target_p0: 3,
        ec_target_p1: 3,
        ec_target_p2: 3,
        p0_maximum_wait_time: 120,
        p1_time_between_shots: 15,
        p1_maximum_shots: 8,
      };
      for (const prefix of ["", "room_b_"]) {
        const flag = `switch.crop_steering_${prefix}engine_enabled`;
        put(`sensor.crop_steering_${prefix}engine_config`, "ready", {
          prefix,
          slug: prefix ? "room_b" : "",
          num_zones: 1,
          friendly_name: prefix ? "Room B engine config" : "Room A engine config",
          enable_flag: flag,
        });
        put(flag, "off");
        put(`sensor.crop_steering_${prefix}ai_heartbeat`, "online", {
          enable_flag: flag,
          last_beat: stamp(),
          strategy_snapshot_version: 1,
        });
        put(`switch.crop_steering_${prefix}zone_1_enabled`, "on");
        put(`sensor.crop_steering_${prefix}zone_1_phase`, "P2");
        put(`sensor.crop_steering_${prefix}zone_1_status`, "monitoring");
        put(`sensor.crop_steering_${prefix}vwc_zone_1`, 55, { unit_of_measurement: "%" });
        put(`sensor.crop_steering_${prefix}ec_zone_1`, 3, { unit_of_measurement: "mS/cm" });
        for (const [key, value] of Object.entries(values))
          put(`number.crop_steering_${prefix}zone_1_${key}`, value, {
            min: 0,
            max: key.includes("time") ? 360 : 100,
            step: 0.1,
          });
      }
      const catalog = Object.fromEntries(
        Object.entries(values).map(([key, value]) => [
          key,
          {
            value,
            min: 0,
            max: key.includes("time") ? 360 : 100,
            step: 0.1,
            unit: key.startsWith("ec_") ? "mS/cm" : "%",
            entity_ids: [`number.crop_steering_room_b_zone_1_${key}`],
          },
        ]),
      );
      const document = {
        room_id: "room:room_b_",
        revision: 1,
        status: "draft",
        error: null,
        plan: {
          schema_version: 1,
          profiles: [
            {
              id: "fixture-profile",
              name: "Fixture endpoints",
              vegetative: values,
              generative: { ...values, p1_target_vwc: 60, p2_vwc_threshold: 48, ec_target_p2: 4 },
            },
          ],
          zones: [
            {
              zone_id: 1,
              start_date: stamp().slice(0, 10),
              schedule: [{ start_day: 1, end_day: 84, profile_id: "fixture-profile", bias: 50 }],
            },
          ],
        },
        catalog: { 1: catalog },
        active: { grow_day: null, zones: [] },
        capabilities: { strategy_snapshot_version: 1, controller_supported: true },
      };
      const setupRoom = {
        entry_id: "fixture-room-b-entry",
        revision: 1,
        room_name: "Room B",
        prefix: "room_b_",
        slug: "room_b",
        active: true,
        num_zones: 1,
        active_zone_ids: [1],
        zones: [
          {
            id: 1,
            name: "Zone 1",
            active: true,
            valve: "switch.fixture_valve",
            vwc_sensors: ["sensor.crop_steering_room_b_vwc_zone_1"],
            ec_sensors: ["sensor.crop_steering_room_b_ec_zone_1"],
            plant_count: 12,
            substrate_volume: 6,
            drippers_per_plant: 1,
            dripper_flow_rate: 4,
          },
        ],
        hardware: {},
        safety: { ready: true, blockers: [] },
      };
      await live.addInitScript(() =>
        localStorage.setItem(
          "hassTokens",
          JSON.stringify({ access_token: "workspace-fixture-token" }),
        ),
      );
      await live.addInitScript(() => {
        const interval = window.setInterval.bind(window);
        window.setInterval = (handler, ms, ...args) =>
          interval(handler, ms === 20000 ? 200 : ms, ...args);
      });
      await live.route("**/*", async (route) => {
        const req = route.request(),
          u = new URL(req.url());
        if (u.origin !== origin) {
          forbidden.push(u.origin + u.pathname);
          return route.abort();
        }
        if (!u.pathname.startsWith("/api/")) return route.continue();
        const reply = (data, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
        if (req.headers().authorization !== "Bearer workspace-fixture-token")
          return reply({ message: "Fixture authentication missing" }, 401);
        if (u.pathname === "/api/states") return reply(Object.values(states));
        // Home Assistant's time zone is a read, not a service: answer with the browser's own zone.
        if (u.pathname === "/api/config")
          return reply({ time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone });
        if (u.pathname.startsWith("/api/history/")) return reply([]);
        const action = u.pathname.split("/").at(-1),
          data = req.postDataJSON();
        apiCalls.push({ action, data });
        if (action === "setup_read")
          return reply({
            service_response: {
              api_version: 1,
              capabilities: { create: true, save: true, remove: true, stable_zone_ids: true },
              rooms: [setupRoom],
              candidates: [],
              limits: { max_zones: 24 },
            },
          });
        if (action === "setup_save") {
          if (data.entry_id !== setupRoom.entry_id || data.expected_revision !== setupRoom.revision)
            return reply({ message: "Setup revision or scope mismatch" }, 400);
          Object.assign(setupRoom, {
            room_name: data.room_name,
            active: data.active,
            zones: data.zones,
            hardware: data.hardware,
            revision: setupRoom.revision + 1,
          });
          return reply({ changed_states: [], service_response: setupRoom });
        }
        const schemas = {
          strategy_get: ["room_id"],
          strategy_preview: ["room_id", "plan", "date"],
          strategy_save: ["room_id", "plan", "expected_revision"],
          strategy_activate: ["room_id", "expected_revision"],
          strategy_disarm: ["room_id"],
        };
        if (!schemas[action] || Object.keys(data).some((k) => !schemas[action].includes(k)))
          return reply({ message: "Strict fixture schema rejected extra data" }, 400);
        if (data.room_id !== "room:room_b_")
          return reply({ message: "Wrong canonical room scope" }, 400);
        if (!u.searchParams.has("return_response"))
          return reply({ message: "Service response flag required" }, 400);
        if (action === "strategy_preview")
          return reply({
            service_response: {
              ...document,
              preview: {
                date: data.date,
                zones: [{ zone_id: 1, day: 1, bias: 50, parameters: values, errors: [] }],
              },
            },
          });
        if (action === "strategy_save") {
          if (failSave || data.expected_revision !== document.revision)
            return reply({ message: "Strategy revision changed; reload before saving" }, 400);
          if (document.status !== "draft") return reply({ message: "Only draft may save" }, 400);
          document.plan = structuredClone(data.plan);
          document.revision++;
        }
        if (action === "strategy_get" && deferRead) {
          deferRead = false;
          const pending = new Promise((resolve) => (releaseRead = resolve));
          readStarted?.();
          await pending;
        }
        if (action === "strategy_activate") {
          if (document.status !== "draft") return reply({ message: "Only draft may arm" }, 400);
          document.status = "armed";
          document.revision++;
        }
        if (action === "strategy_disarm") {
          document.status = document.status === "error" ? "disarming" : "draft";
          document.revision++;
        }
        return reply({ changed_states: [], service_response: structuredClone(document) });
      });
      const lp = await live.newPage();
      lp.setDefaultTimeout(10000);
      lp.on("pageerror", (e) => pageErrors.push(e.message));
      try {
        await lp.goto(origin + "/dashboard.html?room=room_b#/grow-plan");
        await openPlanner("Steering balance", lp);
        await lp.locator("#steering-balance").fill("80");
        await lp.getByRole("button", { name: "Review & save", exact: true }).click();
        failSave = true;
        await lp.getByRole("button", { name: "Save draft", exact: true }).click();
        await visible(lp.getByRole("dialog").getByRole("alert"));
        assert.match(await lp.getByRole("dialog").innerText(), /revision changed/);
        await lp.getByRole("button", { name: "Back to editing", exact: true }).click();
        assert.equal(await lp.locator("#steering-balance").inputValue(), "80");
        failSave = false;
        await lp.getByRole("button", { name: "Review & save", exact: true }).click();
        await lp.getByRole("button", { name: "Save draft", exact: true }).click();
        await lp.getByRole("dialog").waitFor({ state: "hidden" });
        await lp.getByRole("button", { name: ARM_PLAN }).click();
        await lp.getByRole("button", { name: "Arm for next lights-on", exact: true }).click();
        await visible(lp.getByRole("button", { name: "Disarm plan", exact: true }));
        await lp.locator("#preview-grow-day").fill("22");
        document.status = "active";
        document.revision++;
        await lp
          .locator(".plan-state")
          .filter({ hasText: /^Armed · running$/ })
          .waitFor({ state: "visible" });
        assert.equal(
          await lp.locator("#preview-grow-day").inputValue(),
          "22",
          "Background status must retain the preview day",
        );
        await lp.getByRole("button", { name: "Disarm plan", exact: true }).click();
        await lp.getByRole("button", { name: "Confirm disarm", exact: true }).click();
        await lp.getByRole("dialog").waitFor({ state: "hidden" });
        assert.deepEqual(apiCalls.find((c) => c.action === "strategy_disarm").data, {
          room_id: "room:room_b_",
        });
        const pendingRead = new Promise((resolve) => (readStarted = resolve));
        deferRead = true;
        await Promise.race([
          pendingRead,
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error("Background status read did not start")), 3000),
          ),
        ]);
        await lp.locator("#steering-balance").fill("91");
        document.plan.zones[0].schedule[0].bias = 12;
        document.revision++;
        const completedRead = lp.waitForResponse((response) =>
          response.url().includes("strategy_get"),
        );
        releaseRead();
        await completedRead;
        await lp.waitForTimeout(400);
        assert.equal(
          await lp.locator("#steering-balance").inputValue(),
          "91",
          "A late background response must not overwrite edits",
        );
        assert.equal(await lp.locator("#preview-grow-day").inputValue(), "22");
        await lp.getByRole("button", { name: "Discard draft", exact: true }).click();
        document.status = "error";
        document.error = "Fixture invalid snapshot";
        await lp.reload();
        await openPlanner("Steering balance", lp);
        assert.equal(await lp.locator("#steering-balance").isDisabled(), true);
        assert.equal(await lp.getByRole("button", { name: ARM_PLAN }).count(), 0);
        assert.equal(
          await lp.getByRole("button", { name: "Disarm plan", exact: true }).isEnabled(),
          true,
        );
        put("sensor.crop_steering_room_b_strategy_plan", "active", {
          enabled: true,
          snapshot_version: 1,
          room_id: "room:room_b_",
          updated_at: stamp(),
          valid_until: new Date(Date.now() + 120000).toISOString(),
          zones: [
            {
              zone_id: 1,
              status: "active",
              parameters: { ...values, p1_target_vwc: 84, p2_vwc_threshold: 77, ec_target_p2: 4.2 },
            },
          ],
        });
        await navigate("Today", lp);
        await lp.getByRole("button", { name: "Refresh controller data" }).click();
        // Today's line has a note for it; opened, it says the grow plan controls the room.
        await lp.locator(".today-alerts").click();
        await visible(
          lp
            .locator(".today-alert-list")
            .getByText("Grow plan controls this room.", { exact: true }),
        );
        // The zone's page shows the plan's targets, not the numbers kept for after it.
        await lp.evaluate(() => (location.hash = "#/zone/1"));
        await lp.getByText("Targets (read only)", { exact: true }).click();
        const targets = lp.locator(".zone-targets");
        await visible(targets.getByText("Set by the armed grow plan", { exact: true }));
        const rewater = targets.locator("tr").filter({ hasText: "Re-water point" });
        assert.match(await rewater.innerText(), /77/);
        const mutations = () =>
          apiCalls.filter(
            (call) => !["setup_read", "strategy_get", "strategy_preview", "preset_list"].includes(call.action),
          );
        const writesBeforeToday = structuredClone(mutations());
        await navigate("Plan", lp);
        await visible(lp.getByRole("heading", { name: "Irrigation", exact: true }));
        await visible(lp.getByText("Armed grow plan · read only", { exact: true }));
        await visible(lp.getByRole("link", { name: "Open schedule", exact: true }));
        const activeTargets = lp.locator(".targets-panel");
        const scheduled = (phase, label) =>
          activeTargets
            .locator("tbody")
            .filter({ has: lp.locator(`.pill[data-phase="${phase}"]`) })
            .locator("tr")
            .filter({ hasText: label })
            .locator("strong");
        assert.equal((await scheduled("P2", "Re-water point").innerText()).trim(), "77");
        assert.match((await scheduled("P2", "EC target").innerText()).trim(), /^4\.20?$/);
        assert.equal(
          await lp.locator('input[id^="setting-"]:visible, select[id^="choice-"]:visible').count(),
          0,
        );
        // The armed plan owns the targets: there is nothing to review and apply.
        assert.equal(await lp.locator(".review-apply").count(), 0);
        assert.deepEqual(
          mutations(),
          writesBeforeToday,
          "Reading scheduled targets must not write services",
        );
        states["sensor.crop_steering_room_b_strategy_plan"].attributes.valid_until = new Date(
          Date.now() - 1000,
        ).toISOString();
        await lp.getByRole("button", { name: "Refresh controller data" }).click();
        await visible(
          activeTargets.getByText(
            "Scheduled targets are unavailable. Reconnect to verify the active schedule.",
            { exact: true },
          ),
        );
        assert.ok(
          (await activeTargets.locator(".targets-table strong").allInnerTexts()).every(
            (text) => !/\d/.test(text),
          ),
          "An expired schedule shows no target values",
        );
        assert.equal(
          await lp.locator('input[id^="setting-"]:visible, select[id^="choice-"]:visible').count(),
          0,
        );
        assert.deepEqual(
          mutations(),
          writesBeforeToday,
          "An expired schedule must not enable fallback writes",
        );
        // Today says so first, as a critical line; the zone's page shows no stale numbers.
        await navigate("Today", lp);
        await lp.getByRole("button", { name: "Refresh controller data" }).click();
        await visible(lp.locator(".today-critical").getByText("Grow plan snapshot unavailable."));
        await lp.evaluate(() => (location.hash = "#/zone/1"));
        await lp.getByText("Targets (read only)", { exact: true }).click();
        await visible(rewater);
        assert.doesNotMatch(await rewater.innerText(), /77|54/);
        await lp.screenshot({ path: out + "workspace-stale-plan.png", fullPage: true });
        await navigateTo("Equipment", "Setup", lp);
        await visible(lp.locator("#room-name"));
        await lp.locator("#room-name").fill("Room B verified");
        await lp.getByRole("button", { name: "Review configuration", exact: true }).click();
        await lp.getByRole("button", { name: "Save configuration", exact: true }).click();
        await lp.getByRole("dialog").waitFor({ state: "hidden" });
        assert.equal(await lp.locator("#room-name").inputValue(), "Room B verified");
        assert.equal(setupRoom.revision, 2);
        assert.equal(
          apiCalls.find((c) => c.action === "setup_save").data.entry_id,
          "fixture-room-b-entry",
        );
        // A controller silent past its 10 min heartbeat: one band under the header, in words, on
        // a phone too, linking to the probes; the labelled header keeps both switches in words.
        states["sensor.crop_steering_room_b_ai_heartbeat"].last_updated = new Date(
          Date.now() - 14 * 60_000,
        ).toISOString();
        await navigate("Today", lp);
        await lp.getByRole("button", { name: "Refresh controller data" }).click();
        await lp.setViewportSize({ width: 390, height: 844 });
        const band = lp.locator(".stale-banner");
        await visible(band);
        assert.equal(
          await band.locator("p").innerText(),
          "The controller has not reported for 14 min. Moisture and phases below are its last report, not live. Watering is held by the controller's own safety rules.",
        );
        assert.equal(await lp.locator(".today-stopped").count(), 0, "the band, not a second line");
        assert.equal(await lp.locator(".data-age").innerText(), "Updated 14 min ago");
        // The fixture has no room switch: watering is the one switch, in words.
        assert.deepEqual(await lp.locator(".safety-switch-text").allInnerTexts(), [
          "Watering off",
          "Stop all",
        ]);
        assert.ok(
          await lp.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
          "The stale band and the header fit 390 px",
        );
        await lp.screenshot({ path: out + "workspace-stale-banner-390.png", fullPage: true });
        await band.getByRole("button", { name: "Probes", exact: true }).click();
        await visible(lp.getByRole("heading", { name: "Probes", exact: true }));
        await visible(band);
        await lp.setViewportSize({ width: 1440, height: 1000 });
      } finally {
        await live.close();
      }
    },
  );

  await check(
    "Same-origin Home Assistant theme inheritance, live palette changes, explicit override and bundled Roboto",
    async () => {
      const themed = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      await themed.addInitScript(() => localStorage.setItem("irrigation-theme", "auto"));
      const tp = await themed.newPage();
      tp.on("pageerror", (e) => pageErrors.push(e.message));
      await themed.route("**/*", (route) => {
        const u = new URL(route.request().url());
        if (u.origin !== origin || u.pathname.startsWith("/api/")) {
          forbidden.push(u.origin + u.pathname);
          return route.abort();
        }
        if (u.pathname === "/workspace-theme-parent.html")
          return route.fulfill({
            contentType: "text/html",
            body: `<!doctype html><html style="--primary-background-color:#111111;--card-background-color:#1c1c1c;--primary-text-color:#e1e1e1;--secondary-text-color:#9b9b9b;--primary-color:#03a9f4;--divider-color:#343434;--sidebar-background-color:#1c1c1c;--secondary-background-color:#262626;--primary-font-family:Roboto"><body style="margin:0"><iframe title="Home Assistant dashboard fixture" src="/dashboard.html?demo=1#/overview" style="border:0;width:100vw;height:100vh"></iframe></body></html>`,
          });
        return route.continue();
      });
      try {
        await tp.goto(origin + "/workspace-theme-parent.html");
        const frame = tp.frames().find((f) => f !== tp.mainFrame());
        assert.ok(frame);
        await visible(roomHeading(frame));
        await frame.waitForFunction(
          () =>
            document.documentElement.dataset.themeSource === "home-assistant" &&
            document.documentElement.classList.contains("dark"),
        );
        assert.equal(
          await frame.evaluate(() =>
            getComputedStyle(document.documentElement)
              .getPropertyValue("--ha-native-canvas")
              .trim(),
          ),
          "#111111",
        );
        assert.equal(
          await frame.evaluate(async () => {
            await document.fonts.ready;
            return [...document.fonts].some(
              (f) => f.family.includes("Roboto") && f.status === "loaded",
            );
          }),
          true,
        );
        assert.match(
          await frame.locator("script[data-font-license=Roboto]").textContent(),
          /SIL OPEN FONT LICENSE/,
        );
        await mkdir(fileURLToPath(new URL("../../img/", import.meta.url)), { recursive: true });
        await tp.screenshot({
          path: fileURLToPath(new URL("../../img/operator-dashboard.png", import.meta.url)),
        });
        await navigateSchedule(frame);
        // Capture the unified calendar and its shared planning canvas.
        const panel = frame.locator(".irrigation-workspace");
        await tp.evaluate(() => (document.querySelector("iframe").style.height = "3000px"));
        await panel.screenshot({
          path: fileURLToPath(new URL("../../img/grow-plan.png", import.meta.url)),
        });
        await tp.evaluate(() => (document.querySelector("iframe").style.height = "100vh"));
        await tp.screenshot({ path: out + "workspace-ha-native-dark.png", fullPage: true });
        await navigateTo("Equipment", "Setup", frame);
        await visible(frame.locator("#setup-room"));
        await tp.screenshot({
          path: fileURLToPath(new URL("../../img/rooms-setup.png", import.meta.url)),
        });
        await navigate("Today", frame);
        await visible(roomHeading(frame));
        await tp.setViewportSize({ width: 390, height: 844 });
        await tp.screenshot({
          path: fileURLToPath(new URL("../../img/mobile-overview.png", import.meta.url)),
        });
        await tp.setViewportSize({ width: 1440, height: 1000 });

        await tp.evaluate(() => {
          const s = document.documentElement.style;
          s.setProperty("--primary-background-color", "#fafafa");
          s.setProperty("--card-background-color", "#ffffff");
          s.setProperty("--primary-text-color", "#212121");
        });
        await frame.waitForFunction(
          () =>
            !document.documentElement.classList.contains("dark") &&
            getComputedStyle(document.documentElement)
              .getPropertyValue("--ha-native-canvas")
              .trim() === "#fafafa",
        );
        await navigate("Settings", frame);
        // Appearance sits under "More display options", closed until opened (Task 29).
        await frame.locator("details.more-display > summary").click();
        await frame.getByRole("button", { name: "Light", exact: true }).click();
        await frame.waitForFunction(
          () => document.documentElement.dataset.themeSource === "override",
        );
        await tp.evaluate(() =>
          document.documentElement.style.setProperty("--primary-background-color", "#111111"),
        );
        assert.equal(
          await frame.evaluate(() => document.documentElement.classList.contains("dark")),
          false,
        );
        await frame.getByRole("button", { name: "Home Assistant or system", exact: true }).click();
        await frame.waitForFunction(
          () =>
            document.documentElement.dataset.themeSource === "home-assistant" &&
            document.documentElement.classList.contains("dark"),
        );
      } finally {
        await themed.close();
      }
    },
  );

  assert.deepEqual(forbidden, [], "Demo unexpectedly attempted API/external traffic");
  assert.deepEqual(pageErrors, [], "Browser exceptions");
} finally {
  await writeFile(
    out + "workspace-verification.json",
    JSON.stringify({ url, checks, forbidden, pageErrors, accessibility }, null, 2),
  );
  await browser.close();
  if (server)
    await new Promise((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
}
if (checks.some((c) => c.status === "fail")) process.exitCode = 1;
