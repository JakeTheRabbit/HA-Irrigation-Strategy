/** Mock-HA integration checks. No connection to a live Home Assistant installation. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
const root = fileURLToPath(new URL("../../", import.meta.url)),
  out = path.join(root, "output/playwright");
await mkdir(out, { recursive: true });
const html = await readFile(path.join(root, "www/dashboard.html"));
const classicRedirect = await readFile(path.join(root, "www/f2-classic.html"));
const server = createServer((req, res) => {
  res.writeHead(200, {
    "Content-Type": "text/html",
    "Cache-Control": "no-store",
  });
  res.end(html);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHANNEL || process.platform === "win32"
    ? { channel: process.env.PLAYWRIGHT_CHANNEL || "chrome" }
    : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
await context.addInitScript(() =>
  localStorage.setItem(
    "hassTokens",
    JSON.stringify({
      access_token: "browser-fixture-token",
      expires: Date.now() + 3600000,
    }),
  ),
);
const states = {};
const calls = [];
const errors = [];
const checks = [];
let failStates = false,
  failWrite = "",
  ignoreWrite = "",
  noEntities = false;
const put = (entity_id, state, attributes = {}) =>
  (states[entity_id] = {
    entity_id,
    state: String(state),
    attributes,
    last_changed: new Date().toISOString(),
    last_updated: new Date().toISOString(),
  });
for (const prefix of ["", "f1_"]) {
  const name = prefix ? "Flower 1" : "Flower 2",
    flag = prefix ? "switch.crop_steering_f1_engine_enabled" : "input_boolean.f2_control_enabled";
  put(`sensor.crop_steering_${prefix}engine_config`, "ready", {
    prefix,
    slug: prefix ? "f1" : "",
    num_zones: 2,
    friendly_name: `${name} engine config`,
    enable_flag: flag,
  });
  put(`sensor.crop_steering_${prefix}ai_heartbeat`, "online", {
    enable_flag: flag,
    last_beat: new Date().toISOString(),
  });
  put(flag, "on");
  put(`sensor.crop_steering_${prefix}activity_log`, "active", {
    feed: `12:30 ${prefix ? "f1 " : ""}Z1 P1 -> P2`,
  });
  for (let z = 1; z <= 2; z++) {
    const k = `crop_steering_${prefix}zone_${z}_`;
    put(`switch.${k}enabled`, "on");
    put(`sensor.${k}phase`, "P2");
    put(`sensor.${k}status`, "monitoring");
    put(`sensor.crop_steering_${prefix}vwc_zone_${z}`, 54 + z, {
      unit_of_measurement: "%",
    });
    put(`sensor.crop_steering_${prefix}ec_zone_${z}`, 3, {
      unit_of_measurement: "mS/cm",
    });
    put(`number.${k}p1_target_vwc`, 64, {
      min: 10,
      max: 90,
      step: 1,
      unit_of_measurement: "%",
    });
    put(`number.${k}p2_vwc_threshold`, 54, {
      min: 10,
      max: 90,
      step: 1,
      unit_of_measurement: "%",
    });
    put(`select.${k}steering_mode`, "Vegetative", {
      options: ["Vegetative", "Generative"],
    });
  }
}
await context.route("**/*", async (route) => {
  const req = route.request(),
    url = new URL(req.url());
  if (url.origin !== base) {
    errors.push(`Unexpected external request ${url.origin}`);
    return route.abort();
  }
  if (url.pathname.endsWith("/f2-classic.html"))
    return route.fulfill({ contentType: "text/html", body: classicRedirect });
  if (!url.pathname.startsWith("/api/")) return route.continue();
  if (req.headers().authorization !== "Bearer browser-fixture-token") {
    errors.push("Missing fixture auth");
    return route.fulfill({ status: 401, body: "Unauthorized" });
  }
  const reply = (body, status = 200) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  if (url.pathname === "/api/states")
    return failStates
      ? reply({ message: "Unauthorized" }, 401)
      : reply(noEntities ? [] : Object.values(states));
  if (url.pathname.startsWith("/api/states/")) {
    const id = decodeURIComponent(url.pathname.slice("/api/states/".length));
    return states[id] ? reply(states[id]) : reply({}, 404);
  }
  if (url.pathname.startsWith("/api/history/")) return reply([]);
  if (url.pathname.startsWith("/api/services/crop_steering/"))
    return reply({ message: "Fixture has no workspace API" }, 404);
  if (url.pathname.startsWith("/api/services/")) {
    const body = req.postDataJSON();
    calls.push({ path: url.pathname, ...body });
    if (body.entity_id === failWrite) return reply({ message: "Fixture refused write" }, 500);
    if (body.entity_id !== ignoreWrite)
      states[body.entity_id].state = String(
        body.value ?? body.option ?? (url.pathname.endsWith("turn_on") ? "on" : "off"),
      );
    return reply([]);
  }
  return reply({}, 404);
});
const page = await context.newPage();
page.on("pageerror", (e) => errors.push(e.message));
const visible = (locator) => locator.waitFor({ state: "visible", timeout: 10000 });
async function check(name, run) {
  await run();
  checks.push(name);
  console.log("PASS " + name);
}
const field = (key) => page.locator(`input[id="setting-number.crop_steering_f1_zone_1_${key}"]`);
try {
  await check("live connection selects requested room without showing demo", async () => {
    await page.goto(`${base}/dashboard.html?room=f1#/strategy`, {
      waitUntil: "networkidle",
    });
    await visible(page.getByText("Connected", { exact: true }));
    assert.equal(await page.locator("#desktop-room").inputValue(), "room:f1_");
    assert.equal(await page.locator(".demo-banner").count(), 0);
    await visible(field("p1_target_vwc"));
  });
  await check("partial failure keeps failed draft and writes only selected room", async () => {
    failWrite = "number.crop_steering_f1_zone_1_p2_vwc_threshold";
    await field("p1_target_vwc").fill("65");
    await field("p2_vwc_threshold").fill("55");
    await page.getByRole("button", { name: /^Review 2 changes/ }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Apply 2 changes", exact: true })
      .click();
    await visible(page.getByText("Some changes were not applied.", { exact: true }));
    assert.equal(states["number.crop_steering_f1_zone_1_p1_target_vwc"].state, "65");
    assert.equal(states["number.crop_steering_zone_1_p1_target_vwc"].state, "64");
    assert.equal(calls.length, 2);
    assert.equal(
      calls.every((c) => c.entity_id.startsWith("number.crop_steering_f1_")),
      true,
    );
    await page.screenshot({
      path: path.join(out, "live-partial-failure.png"),
      fullPage: true,
    });
    failWrite = "";
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Apply 1 change", exact: true })
      .click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    assert.equal(calls.length, 3);
    assert.equal(calls[2].entity_id, "number.crop_steering_f1_zone_1_p2_vwc_threshold");
  });
  await check("service acknowledgement without readback is a visible failure", async () => {
    ignoreWrite = "number.crop_steering_f1_zone_1_p1_target_vwc";
    await field("p1_target_vwc").fill("66");
    await page.getByRole("button", { name: /^Review 1 change/ }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Apply 1 change", exact: true })
      .click();
    await visible(page.getByText("Some changes were not applied.", { exact: true }));
    assert.equal(states[ignoreWrite].state, "65");
    await page.getByRole("button", { name: "Back to editing" }).click();
    await page.getByRole("button", { name: "Discard draft" }).click();
    ignoreWrite = "";
  });
  await check("missing live sensor stays unavailable and timestamps remain honest", async () => {
    states["sensor.crop_steering_f1_ec_zone_1"].state = "unavailable";
    await page.getByRole("button", { name: "Refresh controller data" }).click();
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Overview", exact: true })
      .click();
    await visible(page.getByText("Zone 1: sensor data unavailable", { exact: true }));
    assert.equal(await page.getByText("Invalid Date", { exact: false }).count(), 0);
    assert.equal(await page.locator(".demo-banner").count(), 0);
  });
  await check("stale probe is unavailable in both overview and sensor diagnostics", async () => {
    const probe = "sensor.crop_steering_f1_vwc_zone_1";
    states[probe].last_updated = "2020-01-01T00:00:00Z";
    await page.getByRole("button", { name: "Refresh controller data" }).click();
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Sensors", exact: true })
      .click();
    const row = page.getByRole("row").filter({ hasText: probe });
    await visible(row.getByText("Stale or unverified", { exact: true }));
    await visible(row.getByText("Unavailable", { exact: true }));
    await page
      .getByRole("combobox", { name: "Filter sensor availability" })
      .selectOption("unavailable");
    await visible(row);
  });
  await check(
    "authentication failure preserves explicit offline state and disables writes",
    async () => {
      failStates = true;
      await page.getByRole("button", { name: "Refresh controller data" }).click();
      await visible(page.getByText("Controller disconnected", { exact: true }));
      await page
        .getByRole("navigation", { name: "Main navigation" })
        .getByRole("button", { name: "Irrigation plan", exact: true })
        .click();
      assert.equal(await field("p1_target_vwc").isDisabled(), true);
      assert.equal(await page.locator(".demo-banner").count(), 0);
      await page.screenshot({
        path: path.join(out, "live-disconnected.png"),
        fullPage: true,
      });
    },
  );
  await check("empty HA response clears stale room controls with useful empty state", async () => {
    failStates = false;
    noEntities = true;
    await page.getByRole("button", { name: "Refresh controller data" }).click();
    await page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("button", { name: "Zones", exact: true })
      .click();
    await visible(page.getByRole("heading", { name: "No zones discovered", exact: true }));
    assert.equal(await page.locator("#desktop-room").isDisabled(), true);
  });
  await check(
    "named F2 stays distinct from default and unsupported tools cannot misroute",
    async () => {
      noEntities = false;
      const prefix = "f2_",
        flag = "switch.crop_steering_f2_engine_enabled";
      put("sensor.crop_steering_f2_engine_config", "ready", {
        prefix,
        slug: "f2",
        num_zones: 1,
        friendly_name: "Named F2 engine config",
        enable_flag: flag,
      });
      put(flag, "on");
      put("sensor.crop_steering_f2_ai_heartbeat", "online", { enable_flag: flag });
      put("switch.crop_steering_f2_zone_1_enabled", "on");
      put("sensor.crop_steering_f2_zone_1_phase", "P2");
      put("sensor.crop_steering_f2_vwc_zone_1", 60, { unit_of_measurement: "%" });
      put("sensor.crop_steering_f2_ec_zone_1", 3, { unit_of_measurement: "mS/cm" });
      put("number.crop_steering_f2_zone_1_p2_vwc_threshold", 50, {
        min: 10,
        max: 90,
        step: 1,
        unit_of_measurement: "%",
      });
      await page.goto(`${base}/dashboard.html?room=f2#/strategy`, { waitUntil: "networkidle" });
      assert.equal(await page.locator("#desktop-room").inputValue(), "room:f2_");
      await visible(
        page.locator('input[id="setting-number.crop_steering_f2_zone_1_p2_vwc_threshold"]'),
      );
      await page
        .getByRole("navigation", { name: "Main navigation" })
        .getByRole("button", { name: "Help & tools", exact: true })
        .click();
      assert.equal(
        await page.locator('a[href*="f2-classic.html"]').count(),
        0,
        "Named F2 must not open default classic controls",
      );
      await page.goto(`${base}/dashboard.html?room=f2&view=climate`, { waitUntil: "networkidle" });
      await visible(page.getByRole("heading", { name: "Sensors", exact: true }));
      assert.equal(
        new URL(page.url()).pathname,
        "/dashboard.html",
        "Unsupported legacy query must stay in the safe dashboard",
      );
      await page.goto(`${base}/dashboard.html?room=f2#/help`, { waitUntil: "networkidle" });
      await page.locator("#desktop-room").selectOption("room:");
      const planner = page.locator('a[href="#/grow-plan"]').first();
      await visible(planner);
      assert.equal(await page.locator("#desktop-room").inputValue(), "room:");
    },
  );
  await check("classic roundtrip preserves default and F1 alongside a named F2", async () => {
    for (const [query, expected] of [
      ["?room=f2", "room:"],
      ["?room=f1", "room:f1_"],
      ["", "room:"],
    ]) {
      await page.goto(`${base}/f2-classic.html${query}`, { waitUntil: "networkidle" });

      await visible(page.getByText("Connected", { exact: true }));
      assert.equal(await page.locator("#desktop-room").inputValue(), expected);
      assert.equal(new URL(page.url()).searchParams.get("room"), expected);
    }
  });
  await check("explicit missing room never falls through to default controls", async () => {
    await page.goto(`${base}/dashboard.html?room=missing-room#/strategy`, {
      waitUntil: "networkidle",
    });
    assert.equal(await page.locator("#desktop-room").inputValue(), "");
    assert.equal(await page.locator('input[type="number"]').count(), 0);
  });
  assert.deepEqual(errors, []);
  console.log(`PASS ${checks.length} mocked HA workflow groups.`);
} catch (error) {
  console.error(error);
  await page
    .screenshot({ path: path.join(out, "live-failure.png"), fullPage: true })
    .catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(
    path.join(out, "live-verification.json"),
    JSON.stringify({ checks, calls, errors }, null, 2),
  );
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
