/** Independent compiled-workspace browser contracts. All actions remain isolated demo/fixtures. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
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
async function navigate(label) {
  await page.locator(".desktop-sidebar").getByRole("button", { name: label, exact: true }).click();
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
async function axe(label) {
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
  await navigate("Settings");
  const pause = page.getByRole("button", { name: "Pause scheduling…", exact: true });
  if (await pause.count()) {
    await pause.click();
    await page.getByRole("button", { name: /Apply \d+ change/ }).click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
  }
}
async function saveSetup() {
  await page.getByRole("button", { name: "Review configuration", exact: true }).click();
  await visible(page.getByRole("heading", { name: "Review room configuration", exact: true }));
  await page.getByRole("button", { name: "Save configuration", exact: true }).click();
  await page.getByRole("dialog").waitFor({ state: "hidden", timeout: 10000 });
}
try {
  await check(
    "Planning slider changes both plotted VWC and EC; exact day and week edits preserve neighboring days and other zones",
    async () => {
      await fresh("grow-plan");
      await visible(page.locator("#steering-balance"));
      await page.getByRole("button", { name: "Days", exact: true }).click();
      await page.locator("#preview-grow-day").fill("16");
      const initial = await exported(),
        oldVwc = await page.locator('[data-planning-line="vwc"]').getAttribute("d"),
        oldEc = await page
          .locator('[data-planning-line="ec"]')
          .evaluateAll((es) => es.map((e) => e.getAttribute("d")));
      await setBalance(90);
      assert.notEqual(await page.locator('[data-planning-line="vwc"]').getAttribute("d"), oldVwc);
      assert.notDeepEqual(
        await page
          .locator('[data-planning-line="ec"]')
          .evaluateAll((es) => es.map((e) => e.getAttribute("d"))),
        oldEc,
      );
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
    "Planner draft guards navigation, hash changes, browser back and selected room; keep editing preserves draft",
    async () => {
      await fresh("grow-plan");
      await visible(page.locator("#steering-balance"));
      await setBalance(83);
      await navigate("Overview");
      await visible(page.getByRole("heading", { name: "Discard unsaved workspace changes?" }));
      await page.getByRole("button", { name: "Keep editing" }).click();
      assert.equal(await page.locator("#steering-balance").inputValue(), "83");
      await page.evaluate(() => (location.hash = "/zones"));
      await visible(page.getByRole("heading", { name: "Discard unsaved workspace changes?" }));
      await page.getByRole("button", { name: "Keep editing" }).click();
      assert.equal(new URL(page.url()).hash, "#/grow-plan");
      await page.locator("#desktop-room").selectOption({ label: "Flower 1" });
      await visible(page.getByRole("heading", { name: "Discard unsaved workspace changes?" }));
      await page.getByRole("button", { name: "Keep editing" }).click();
      assert.equal(await page.locator("#desktop-room").inputValue(), "room:");
      await navigate("Overview");
      await page.getByRole("button", { name: "Discard and continue" }).click();
      await visible(page.getByRole("heading", { name: "Room overview", exact: true }));
      await navigate("Grow plan");
      assert.notEqual(await page.locator("#steering-balance").inputValue(), "83");
      await setBalance(81);
      await page.goBack();
      await visible(page.getByRole("heading", { name: "Discard unsaved workspace changes?" }));
      await page.getByRole("button", { name: "Keep editing" }).click();
      assert.equal(await page.locator("#steering-balance").inputValue(), "81");
    },
  );
  await check(
    "Endpoint profile edits, duplicate, local curve handle and save/arm/disarm lifecycle",
    async () => {
      await fresh("grow-plan");
      await visible(page.locator("#steering-balance"));
      await page.getByRole("tab", { name: "Endpoint profiles" }).click();
      await page.getByRole("button", { name: "Duplicate profile" }).click();
      await page.locator("#profile-name").fill("Verification profile");
      await page.locator("#vegetative-p1_target_vwc").fill("66");
      await page.locator("#generative-p1_target_vwc").fill("62");
      await page.getByRole("tab", { name: "Schedule & curve" }).click();
      const handle = page.getByRole("slider", { name: "P2 VWC threshold", exact: true });
      const before = Number(await handle.getAttribute("aria-valuenow"));
      await handle.focus();
      await handle.press("ArrowUp");
      assert.ok(Number(await handle.getAttribute("aria-valuenow")) > before);
      const plan = await exported(),
        profile = plan.profiles.find((p) => p.name === "Verification profile");
      assert.equal(profile.vegetative.p2_vwc_threshold, profile.generative.p2_vwc_threshold);
      assert.equal(profile.vegetative.p1_target_vwc, 66);
      await page.getByRole("button", { name: "Review & save", exact: true }).click();
      await visible(page.getByRole("heading", { name: "Review grow plan", exact: true }));
      assert.match(await page.getByRole("dialog").innerText(), /Flower 2 only/);
      await page.getByRole("button", { name: "Save draft", exact: true }).click();
      await visible(page.getByRole("button", { name: "Arm plan", exact: true }));
      assert.equal(
        await page.getByRole("button", { name: "Arm plan", exact: true }).isEnabled(),
        true,
      );
      await page.getByRole("button", { name: "Arm plan", exact: true }).click();
      await page.getByRole("button", { name: "Arm for next lights-on", exact: true }).click();
      await visible(page.getByRole("button", { name: "Disarm plan", exact: true }));
      assert.equal(await page.locator("#steering-balance").isDisabled(), true);
      await page.getByRole("button", { name: "Disarm plan", exact: true }).click();
      await page.getByRole("button", { name: "Confirm disarm", exact: true }).click();
      await visible(page.getByRole("button", { name: "Arm plan", exact: true }));
      assert.equal(await page.locator("#steering-balance").isEnabled(), true);
    },
  );
  await check(
    "Setup room-change discard resets selected configuration and stale draft",
    async () => {
      await fresh("setup");
      await visible(page.locator("#room-name"));
      await page.locator("#room-name").fill("Must be discarded");
      await page.locator("#desktop-room").selectOption({ label: "Flower 1" });
      await visible(page.getByRole("heading", { name: "Discard unsaved workspace changes?" }));
      await page.getByRole("button", { name: "Discard and continue" }).click();
      assert.equal(await page.locator("#room-name").inputValue(), "Flower 1");
      assert.equal(await page.locator("#setup-room option:checked").innerText(), "Flower 1");
    },
  );
  await check(
    "Setup maps a new zone, saves sizing, archives/restores the stable zone ID, and retains other room mappings",
    async () => {
      await fresh("grow-plan");
      await visible(page.locator("#steering-balance"));
      await pause();
      await navigate("Rooms & setup");
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
      await page.locator("#setup-room").selectOption({ label: "Flower 1" });
      assert.equal(
        await page.getByRole("textbox", { name: "Zone 4 name", exact: true }).count(),
        0,
      );
      assert.equal(await page.locator("#zone-1-plant_count").inputValue(), "36");
      await navigate("Grow plan");
      await visible(page.locator("#steering-balance"));
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
      await saveSetup();
      const id = await page.locator("#setup-room").inputValue();
      assert.ok(id);
      await page.getByRole("button", { name: "Archive room", exact: true }).click();
      await page
        .getByRole("textbox", { name: "Type the room name to confirm" })
        .fill("Verification room");
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
    "Grow plan and setup are accessible and fit 390px with keyboard reachable mappings",
    async () => {
      await fresh("grow-plan");
      await visible(page.locator("#steering-balance"));
      await axe("grow-plan-desktop");
      await page.setViewportSize({ width: 390, height: 844 });
      await noOverflow();
      await page.locator("#steering-balance").focus();
      await page.locator("#steering-balance").press("ArrowRight");
      await page.screenshot({ path: out + "workspace-grow-mobile.png", fullPage: true });
      await axe("grow-plan-mobile");
      await fresh("setup");
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
      for (const prefix of ["", "f1_"]) {
        const flag = `switch.crop_steering_${prefix}engine_enabled`;
        put(`sensor.crop_steering_${prefix}engine_config`, "ready", {
          prefix,
          slug: prefix ? "f1" : "",
          num_zones: 1,
          friendly_name: prefix ? "Flower 1 engine config" : "Flower 2 engine config",
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
            entity_ids: [`number.crop_steering_f1_zone_1_${key}`],
          },
        ]),
      );
      const document = {
        room_id: "room:f1_",
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
        entry_id: "fixture-f1-entry",
        revision: 1,
        room_name: "Flower 1",
        prefix: "f1_",
        slug: "f1",
        active: true,
        num_zones: 1,
        active_zone_ids: [1],
        zones: [
          {
            id: 1,
            name: "Zone 1",
            active: true,
            valve: "switch.fixture_valve",
            vwc_sensors: ["sensor.crop_steering_f1_vwc_zone_1"],
            ec_sensors: ["sensor.crop_steering_f1_ec_zone_1"],
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
        if (data.room_id !== "room:f1_")
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
        await lp.goto(origin + "/dashboard.html?room=f1#/grow-plan");
        await visible(lp.locator("#steering-balance"));
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
        await lp.getByRole("button", { name: "Arm plan", exact: true }).click();
        await lp.getByRole("button", { name: "Arm for next lights-on", exact: true }).click();
        await visible(lp.getByRole("button", { name: "Disarm plan", exact: true }));
        await lp.locator("#preview-grow-day").fill("22");
        document.status = "active";
        document.revision++;
        await lp
          .locator(".plan-state")
          .filter({ hasText: /^active$/i })
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
          room_id: "room:f1_",
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
        await visible(lp.locator("#steering-balance"));
        assert.equal(await lp.locator("#steering-balance").isDisabled(), true);
        assert.equal(await lp.getByRole("button", { name: "Arm plan", exact: true }).count(), 0);
        assert.equal(
          await lp.getByRole("button", { name: "Disarm plan", exact: true }).isEnabled(),
          true,
        );
        put("sensor.crop_steering_f1_strategy_plan", "active", {
          enabled: true,
          snapshot_version: 1,
          room_id: "room:f1_",
          updated_at: stamp(),
          valid_until: new Date(Date.now() + 120000).toISOString(),
          zones: [
            {
              zone_id: 1,
              status: "active",
              parameters: { ...values, p2_vwc_threshold: 77, ec_target_p2: 4.2 },
            },
          ],
        });
        await lp
          .locator(".desktop-sidebar")
          .getByRole("button", { name: "Overview", exact: true })
          .click();
        await lp.getByRole("button", { name: "Refresh controller data" }).click();
        await visible(lp.getByText("Grow plan controls this room", { exact: true }));
        const targetCell = lp
          .locator(".table-scroll tbody tr")
          .first()
          .locator("td")
          .filter({ hasText: "Plan · P2 base VWC threshold" });
        assert.match(await targetCell.innerText(), /77/);
        await lp
          .locator(".desktop-sidebar")
          .getByRole("button", { name: "Manual setpoints", exact: true })
          .click();
        assert.equal(await lp.locator('input[type="number"]').first().isDisabled(), true);
        states["sensor.crop_steering_f1_strategy_plan"].attributes.valid_until = new Date(
          Date.now() - 1000,
        ).toISOString();
        await lp
          .locator(".desktop-sidebar")
          .getByRole("button", { name: "Overview", exact: true })
          .click();
        await lp.getByRole("button", { name: "Refresh controller data" }).click();
        await visible(lp.getByText("Grow plan snapshot unavailable", { exact: true }));
        assert.doesNotMatch(await targetCell.innerText(), /77|54/);
        await lp.screenshot({ path: out + "workspace-stale-plan.png", fullPage: true });
        await lp
          .locator(".desktop-sidebar")
          .getByRole("button", { name: "Rooms & setup", exact: true })
          .click();
        await visible(lp.locator("#room-name"));
        await lp.locator("#room-name").fill("Flower 1 verified");
        await lp.getByRole("button", { name: "Review configuration", exact: true }).click();
        await lp.getByRole("button", { name: "Save configuration", exact: true }).click();
        await lp.getByRole("dialog").waitFor({ state: "hidden" });
        assert.equal(await lp.locator("#room-name").inputValue(), "Flower 1 verified");
        assert.equal(setupRoom.revision, 2);
        assert.equal(
          apiCalls.find((c) => c.action === "setup_save").data.entry_id,
          "fixture-f1-entry",
        );
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
        await visible(frame.getByRole("heading", { name: "Room overview", exact: true }));
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
        await frame
          .locator(".desktop-sidebar")
          .getByRole("button", { name: "Grow plan", exact: true })
          .click();
        await visible(frame.locator("#steering-balance"));
        assert.equal(await frame.locator('[data-planning-cadence="p1"]').count(), 1);
        const panel = frame
          .locator(".workspace-card")
          .filter({ has: frame.locator(".planning-curve") });
        await tp.evaluate(() => (document.querySelector("iframe").style.height = "3000px"));
        await panel.screenshot({
          path: fileURLToPath(new URL("../../img/grow-plan.png", import.meta.url)),
        });
        await tp.evaluate(() => (document.querySelector("iframe").style.height = "100vh"));
        await tp.screenshot({ path: out + "workspace-ha-native-dark.png", fullPage: true });
        await frame
          .locator(".desktop-sidebar")
          .getByRole("button", { name: "Rooms & setup", exact: true })
          .click();
        await visible(frame.locator("#setup-room"));
        await tp.screenshot({
          path: fileURLToPath(new URL("../../img/rooms-setup.png", import.meta.url)),
        });
        await frame
          .locator(".desktop-sidebar")
          .getByRole("button", { name: "Overview", exact: true })
          .click();
        await visible(frame.getByRole("heading", { name: "Room overview", exact: true }));
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
        await frame
          .locator(".desktop-sidebar")
          .getByRole("button", { name: "Settings", exact: true })
          .click();
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
        await frame.getByRole("button", { name: "Home Assistant / system", exact: true }).click();
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
