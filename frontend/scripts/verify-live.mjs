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
/** The entity ids of each history request, in order. */
const history = [];
const errors = [];
const checks = [];
let failStates = false,
  failWrite = "",
  ignoreWrite = "",
  noEntities = false,
  /** What crop_steering.whats_new_get answers; null: an integration without What's new. */
  whatsNew = null;
const put = (entity_id, state, attributes = {}) =>
  (states[entity_id] = {
    entity_id,
    state: String(state),
    attributes,
    last_changed: new Date().toISOString(),
    last_updated: new Date().toISOString(),
  });
for (const prefix of ["", "room_b_"]) {
  const name = prefix ? "Room B" : "Room A",
    flag = prefix
      ? "switch.crop_steering_room_b_engine_enabled"
      : "input_boolean.f2_control_enabled";
  put(`sensor.crop_steering_${prefix}engine_config`, "ready", {
    prefix,
    slug: prefix ? "room_b" : "",
    num_zones: 2,
    friendly_name: `${name} engine config`,
    enable_flag: flag,
    // Room B's pair reports its versions; the default room models an older pair that does not
    ...(prefix ? { integration_version: "2.19.1" } : {}),
  });
  put(`sensor.crop_steering_${prefix}ai_heartbeat`, "online", {
    enable_flag: flag,
    last_beat: new Date().toISOString(),
    ...(prefix ? { controller_version: "0.16.1" } : {}),
  });
  put(flag, "on");
  // What the AI assistant may do: Room B's integration has a switch per power at its default; the
  // default room's is from before the powers.
  if (prefix)
    for (const [key, on] of [
      ["advance_phase", "on"],
      ["ramp_control", "on"],
      ["set_probe_aside", "on"],
      ["ec_mode", "on"],
      ["nudge_setpoints", "on"],
      ["plan_catch_up", "on"],
      ["set_targets_from_achievable", "off"],
      ["tune_shot_sizes", "off"],
    ])
      put(`switch.crop_steering_${prefix}ai_power_${key}`, on);
  put(`sensor.crop_steering_${prefix}activity_log`, "active", {
    feed: `12:30 ${prefix ? "room_b " : ""}Z1 P1 -> P2`,
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
  if (url.pathname.startsWith("/api/history/")) {
    history.push(url.searchParams.get("filter_entity_id")?.split(",") ?? []);
    return reply([]);
  }
  if (whatsNew && url.pathname.startsWith("/api/services/crop_steering/whats_new_")) {
    const action = url.pathname.split("/").pop(),
      body = req.postDataJSON() ?? {};
    calls.push({ path: url.pathname + url.search, ...body });
    if (action === "whats_new_seen") whatsNew.seen = body.version;
    return reply({
      changed_states: [],
      service_response: action === "whats_new_get" ? whatsNew : { seen: whatsNew.seen },
    });
  }
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
/** The header says the dashboard reads Home Assistant live (not the demo, not offline). */
const connected = (target = page) =>
  visible(target.locator('header.topbar[data-connection="live"]'));
const menu = async (name) => {
  await page
    .getByRole("navigation", { name: "Main navigation" })
    // Status is a link to its page; the other sections are disclosures.
    .getByRole(name === "Today" ? "link" : "button", { name: name === "Today" ? "Status" : name, exact: true })
    .click();
  if (name === "Today")
    // The Status tabs give way to the room tree on a desktop; open the room page directly.
    await page.evaluate(() => {
      location.hash = "#/today";
    });
};
async function check(name, run) {
  await run();
  checks.push(name);
  console.log("PASS " + name);
}
const roomChip = (id) => page.locator(`.desktop-sidebar .room-tree-row[data-room="${id}"]`);
const selectedRoom = () =>
  page.locator(".desktop-sidebar .room-tree-row[data-selected]").getAttribute("data-room");
const field = (key) =>
  page.locator(`input[id="setting-number.crop_steering_room_b_zone_1_${key}"]`);
try {
  await check("live connection selects requested room without showing demo", async () => {
    await page.goto(`${base}/dashboard.html?room=room_b#/strategy`, {
      waitUntil: "networkidle",
    });
    await connected();
    assert.equal(await selectedRoom(), "room:room_b_");
    assert.equal(await page.locator(".demo-pill").count(), 0);
    await visible(field("p1_target_vwc"));
  });
  await check(
    "sidebar shows the versions the running integration and controller report, per room",
    async () => {
      const versions = page.locator(".desktop-sidebar .sidebar-versions");
      await visible(versions);
      assert.match(await versions.innerText(), /Integration\s+2\.19\.1/);
      assert.match(await versions.innerText(), /Controller\s+0\.16\.1/);
      // An older pair reports nothing: say so, never show a number this page made up.
      await roomChip("room:").click();
      await visible(versions.getByText("not reported").first());
      assert.equal((await versions.innerText()).match(/not reported/g).length, 2);
      await roomChip("room:room_b_").click();
      await visible(versions.getByText("2.19.1"));
    },
  );
  await check(
    "the navigation scrolls on a phone and in a short window, down to the versions in its footer",
    async () => {
      // Seen on a real phone: the drawer was screen-high, the menu taller, and it would not scroll.
      const phone = await context.newPage();
      try {
        await phone.setViewportSize({ width: 390, height: 400 });
        await phone.goto(`${base}/dashboard.html?room=room_b#/today`, { waitUntil: "networkidle" });
        await phone.getByRole("button", { name: "Open navigation", exact: true }).click();
        const drawer = phone.locator(".mobile-sidebar");
        await drawer.waitFor({ state: "visible" });
        const fits = await drawer.evaluate((el) => ({
          taller: el.scrollHeight > el.clientHeight,
          overflowY: getComputedStyle(el).overflowY,
        }));
        assert.ok(fits.taller, "the fixture must make the menu taller than the drawer");
        assert.ok(["auto", "scroll"].includes(fits.overflowY), "the drawer must scroll");
        const versions = drawer.locator(".sidebar-versions");
        await versions.scrollIntoViewIfNeeded();
        const box = await versions.boundingBox();
        assert.ok(box && box.y >= 0 && box.y + box.height <= 400, "versions must be reachable");
        assert.match(await versions.innerText(), /Controller\s+0\.16\.1/);
        assert.ok((await drawer.evaluate((el) => el.scrollTop)) > 0, "it really scrolled");
        // and the first item is still reachable on the way back
        await drawer
          .getByRole("link", { name: "Status", exact: true })
          .scrollIntoViewIfNeeded();
      } finally {
        await phone.close();
      }
      const short = await context.newPage();
      try {
        await short.setViewportSize({ width: 1280, height: 480 });
        await short.goto(`${base}/dashboard.html?room=room_b#/today`, { waitUntil: "networkidle" });
        const versions = short.locator(".desktop-sidebar .sidebar-versions");
        await versions.scrollIntoViewIfNeeded();
        const box = await versions.boundingBox();
        assert.ok(box && box.y + box.height <= 480, "versions must be reachable in a short window");
      } finally {
        await short.close();
      }
    },
  );
  await check(
    "an open dropdown can be read on a dark Home Assistant theme (targets, timeline, capability directory, compare)",
    async () => {
      // Home Assistant's input fill is a translucent rgba of the text colour. The browser cannot
      // paint an option list with it and fell back to white under light text.
      const themed = await context.newPage();
      try {
        const alpha = (colour) => {
          const parts = colour.match(/[\d.]+/g).map(Number);
          return parts.length < 4 ? 1 : parts[3];
        };
        const luminance = (colour) => {
          const [r, g, b] = colour.match(/[\d.]+/g).map(Number);
          return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
        };
        for (const route of [
          "plan/targets",
          "history/timeline",
          "settings/features",
          "history/compare",
        ]) {
          await themed.goto(`${base}/dashboard.html?room=room_b#/${route}`, {
            waitUntil: "networkidle",
          });
          await themed.evaluate(() => {
            document.documentElement.classList.add("dark");
            document.documentElement.style.setProperty(
              "--ha-native-input",
              "rgba(225, 225, 225, 0.05)",
            );
          });
          const options = await themed.locator("select option").evaluateAll((nodes) =>
            nodes.map((node) => {
              const style = getComputedStyle(node);
              return {
                text: node.textContent,
                background: style.backgroundColor,
                colour: style.color,
              };
            }),
          );
          assert.ok(options.length > 0, `${route}: expected at least one dropdown`);
          for (const option of options) {
            assert.equal(
              alpha(option.background),
              1,
              `${route}: "${option.text}" has a see-through background`,
            );
            assert.ok(
              Math.abs(luminance(option.background) - luminance(option.colour)) > 0.4,
              `${route}: "${option.text}" is ${option.colour} on ${option.background}`,
            );
          }
        }
      } finally {
        await themed.close();
      }
    },
  );
  await check("partial failure keeps failed draft and writes only selected room", async () => {
    failWrite = "number.crop_steering_room_b_zone_1_p2_vwc_threshold";
    await field("p1_target_vwc").fill("65");
    await field("p2_vwc_threshold").fill("55");
    await page.getByRole("button", { name: /^Review 2 changes/ }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Apply 2 changes", exact: true })
      .click();
    await visible(page.getByText("Some changes were not applied.", { exact: true }));
    assert.equal(states["number.crop_steering_room_b_zone_1_p1_target_vwc"].state, "65");
    assert.equal(states["number.crop_steering_zone_1_p1_target_vwc"].state, "64");
    assert.equal(calls.length, 2);
    assert.equal(
      calls.every((c) => c.entity_id.startsWith("number.crop_steering_room_b_")),
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
    assert.equal(calls[2].entity_id, "number.crop_steering_room_b_zone_1_p2_vwc_threshold");
  });
  await check("service acknowledgement without readback is a visible failure", async () => {
    ignoreWrite = "number.crop_steering_room_b_zone_1_p1_target_vwc";
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
    states["sensor.crop_steering_room_b_ec_zone_1"].state = "unavailable";
    await page.getByRole("button", { name: "Refresh controller data" }).click();
    await menu("Today");
    await visible(page.getByRole("heading", { name: "Room B", exact: true, level: 1 }));
    // The room's line counts the alert; opened, it says which zone and why.
    await page.locator(".today-alerts").click();
    await visible(
      page
        .locator(".today-alert-list")
        .getByText("Zone 1: sensor data unavailable.", { exact: true }),
    );
    assert.equal(await page.getByText("Invalid Date", { exact: false }).count(), 0);
    assert.equal(await page.locator(".demo-pill").count(), 0);
    // The room's line first, then today's strip, then a row per zone; the AI assistant's changes
    // are not repeated on the room page.
    const order = await page.evaluate(() =>
      [...document.querySelectorAll(".today-head, [data-today-strip], .today-zones, [data-jev-today]")].map(
        (el) => (el.matches("[data-today-strip]") ? "today-strip" : el.classList[0]),
      ),
    );
    assert.deepEqual(order, ["today-head", "today-strip", "today-zones"]);
    assert.equal(await page.locator("article.today-zone").count(), 2);
  });
  await check(
    "stale probe is unavailable on Equipment › Probes and in the controller's sensors",
    async () => {
      const probe = "sensor.crop_steering_room_b_vwc_zone_1";
      states[probe].last_updated = "2020-01-01T00:00:00Z";
      await page.getByRole("button", { name: "Refresh controller data" }).click();
      await menu("Equipment");
      await visible(page.getByRole("heading", { name: "Probes", exact: true }));
      // An older integration names no probes: each zone's combined reading stands in for them. Zone 1's
      // moisture has gone quiet (amber) and its pore EC reads nothing (red); zone 2's are fine.
      const health = (id) =>
        page.locator(`.probes-table tr[data-probe="${id}"] [data-probe-health]`);
      await visible(health(probe));
      assert.equal(await health(probe).getAttribute("data-probe-health"), "stale");
      assert.equal(await health(probe).getAttribute("data-tone"), "warn");
      const ec = "sensor.crop_steering_room_b_ec_zone_1";
      assert.equal(await health(ec).getAttribute("data-probe-health"), "no-reading");
      assert.equal(await health(ec).getAttribute("data-tone"), "off");
      assert.equal(
        await health("sensor.crop_steering_room_b_ec_zone_2").getAttribute("data-tone"),
        "on",
      );
      assert.match(await page.locator(".probes-status").innerText(), /Probes\s+2 of 4 OK/);
      // The controller's own sensors, one tap down: stale is amber, reporting green, down red.
      const internals = page.locator("details.probes-more", {
        hasText: "All sensors of this room",
      });
      await internals.locator("summary").click();
      const row = internals.locator(".sensors-table tr").filter({ hasText: probe });
      await visible(row.getByText("Stale or unverified", { exact: true }));
      await visible(row.getByText("Unavailable", { exact: true }));
      assert.equal(
        await row.locator(".pill", { hasText: "Stale or unverified" }).getAttribute("data-tone"),
        "warn",
      );
      assert.equal(
        await internals
          .locator(".sensors-table tr")
          .filter({ hasText: ec })
          .locator(".pill")
          .getAttribute("data-tone"),
        "off",
      );
      assert.equal(
        await internals
          .locator(".sensors-table tr")
          .filter({ hasText: "sensor.crop_steering_room_b_ec_zone_2" })
          .locator(".pill")
          .getAttribute("data-tone"),
        "on",
      );
      assert.match(await internals.locator("summary").innerText(), /\(\d+ of \d+ reporting\)/);
      await internals
        .getByRole("combobox", { name: "Sensor status filter" })
        .selectOption("unavailable");
      await visible(row);
    },
  );
  await check(
    "probes: each probe's line, and the controller's sensors', one request each",
    async () => {
      // Settings reads no history: anything asked for after this is Equipment's.
      await menu("Settings");
      await visible(page.getByRole("heading", { name: "Settings", exact: true }));
      await page.waitForTimeout(1000);
      history.length = 0;
      await menu("Equipment");
      await visible(page.getByRole("heading", { name: "Probes", exact: true }));
      await page.waitForFunction(() => document.querySelectorAll(".probes-table tr").length > 1);
      await page.waitForTimeout(1000);
      const probes = [1, 2]
        .flatMap((zone) => [
          `sensor.crop_steering_room_b_vwc_zone_${zone}`,
          `sensor.crop_steering_room_b_ec_zone_${zone}`,
        ])
        .sort();
      const numeric = Object.values(states)
        .filter(
          (e) =>
            e.entity_id.startsWith("sensor.crop_steering_room_b_") &&
            e.state.trim() &&
            Number.isFinite(Number(e.state)),
        )
        .map((e) => e.entity_id)
        .sort();
      assert.ok(numeric.length > 1, "the fixture has several numeric sensors");
      assert.ok(history.length >= 1, "the Probes page asks for its probes' readings");
      const same = (ids, set) => JSON.stringify([...ids].sort()) === JSON.stringify(set);
      for (const ids of history) assert.ok(same(ids, probes), `one request for the probes: ${ids}`);
      // The controller's sensors, once opened: one request for every numeric one. A later re-read may
      // repeat a request; it is never one request per row.
      history.length = 0;
      const internals = page.locator("details.probes-more", {
        hasText: "All sensors of this room",
      });
      if ((await internals.getAttribute("open")) === null)
        await internals.locator("summary").click();
      await page.waitForFunction(() => document.querySelectorAll(".sensors-table tr").length > 1);
      await page.waitForTimeout(1000);
      assert.ok(
        history.some((ids) => same(ids, numeric)),
        "one request for the sensors",
      );
      for (const ids of history)
        assert.ok(
          same(ids, numeric) || same(ids, probes),
          `a request per page, not per row: ${ids}`,
        );
    },
  );
  await check(
    "authentication failure preserves explicit offline state and disables writes",
    async () => {
      failStates = true;
      await page.getByRole("button", { name: "Refresh controller data" }).click();
      await visible(page.getByText("Controller disconnected", { exact: true }));
      assert.equal(await page.locator(".data-age").innerText(), "Offline");
      await menu("Equipment");
      await page
        .getByRole("navigation", { name: "Equipment views" })
        .getByRole("button", { name: "Tank and feed", exact: true })
        .click();
      await visible(
        page
          .locator("[data-tank-status]")
          .getByText("Disconnected · last received", { exact: true }),
      );
      await menu("Irrigation");
      assert.equal(await field("p1_target_vwc").isDisabled(), true);
      assert.equal(await page.locator(".demo-pill").count(), 0);
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
    await menu("Today");
    await visible(page.getByRole("heading", { name: "No zones found", exact: true }));
    await visible(page.getByRole("heading", { level: 1, name: "Today", exact: true }));
    assert.equal(await page.locator("header.topbar [data-room]").count(), 0);
    // A zone's old address finds no zone either, and says so.
    await page.evaluate(() => (location.hash = "#/zone/1"));
    await visible(page.getByRole("heading", { name: "No zones found", exact: true }));
    await visible(page.getByRole("heading", { level: 1, name: "Zone", exact: true }));
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
      assert.equal(await selectedRoom(), "room:f2_");
      await visible(
        page.locator('input[id="setting-number.crop_steering_f2_zone_1_p2_vwc_threshold"]'),
      );
      await menu("Settings");
      await page
        .getByRole("navigation", { name: "Settings views" })
        .getByRole("button", { name: "Help", exact: true })
        .click();
      await visible(page.getByRole("heading", { name: "Help", exact: true }));
      assert.equal(
        await page.locator('a[href*="f2-classic.html"]').count(),
        0,
        "Named F2 must not open default classic controls",
      );
      await page.goto(`${base}/dashboard.html?room=f2&view=climate`, { waitUntil: "networkidle" });
      await visible(page.getByRole("heading", { name: "Probes", exact: true }));
      assert.equal(
        new URL(page.url()).pathname,
        "/dashboard.html",
        "Unsupported legacy query must stay in the safe dashboard",
      );
      await page.goto(`${base}/dashboard.html?room=f2#/help`, { waitUntil: "networkidle" });
      await roomChip("room:").click();
      await visible(page.getByRole("heading", { name: "Help", exact: true }));
      assert.equal(await selectedRoom(), "room:");
      assert.equal(new URL(page.url()).hash, "#/help");
    },
  );
  await check("classic roundtrip keeps default, a second room and the old f1 link", async () => {
    for (const [query, expected] of [
      ["?room=f2", "room:"],
      ["?room=room:room_b_", "room:room_b_"],
      ["", "room:"],
    ]) {
      await page.goto(`${base}/f2-classic.html${query}`, { waitUntil: "networkidle" });

      await connected();
      assert.equal(await selectedRoom(), expected);
      assert.equal(new URL(page.url()).searchParams.get("room"), expected);
    }
    // An old ?room=f1 link still opens the dashboard on the room with prefix f1_.
    const opened = page.waitForRequest((req) => new URL(req.url()).pathname === "/dashboard.html");
    await page.goto(`${base}/f2-classic.html?room=f1`, { waitUntil: "networkidle" });
    assert.equal(new URL((await opened).url()).searchParams.get("room"), "room:f1_");
  });
  await check("what's new: an update shows it once, and the integration is told", async () => {
    // Every check above ran against an integration without What's new: no window, no error.
    const dialog = page.getByRole("dialog", { name: "What’s new in Crop Steering", exact: true });
    assert.equal(await dialog.count(), 0);
    whatsNew = {
      version: "2.25.0",
      seen: "2.24.0",
      releases: [
        { version: "2.25.0", date: "2026-10-05", items: ["Each zone says what it waits for."] },
        { version: "2.24.0", date: "2026-09-26", items: ["Bug fixes and improvements."] },
      ],
    };
    const told = () =>
      calls.filter((call) => call.path.startsWith("/api/services/crop_steering/whats_new_seen"));
    await page.goto(`${base}/dashboard.html?room=room_b#/today`, { waitUntil: "networkidle" });
    await visible(dialog);
    assert.deepEqual(
      (await dialog.locator("section h3").allInnerTexts()).map((text) => text.split("\n")[0]),
      ["Version 2.25.0"],
    );
    // Told as it opens, with the installed version, over the REST call the integration answers.
    assert.deepEqual(told(), [
      { path: "/api/services/crop_steering/whats_new_seen?return_response", version: "2.25.0" },
    ]);
    await dialog
      .locator(".whats-new-actions")
      .getByRole("button", { name: "Close", exact: true })
      .click();
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    assert.equal(await dialog.count(), 0, "the next visit, by anyone, does not show it again");
    assert.equal(told().length, 1);
    whatsNew = null;
  });
  await check("explicit missing room never falls through to default controls", async () => {
    await page.goto(`${base}/dashboard.html?room=missing-room#/strategy`, {
      waitUntil: "networkidle",
    });
    assert.equal(await page.locator(".desktop-sidebar .room-tree-row[data-selected]").count(), 0);
    assert.equal(await page.locator('input[type="number"]').count(), 0);
  });
  await check(
    "capability directory is read-only and links to the target owner without writes",
    async () => {
      const before = calls.length;
      await page.goto(`${base}/dashboard.html?room=room_b#/settings/features`, {
        waitUntil: "networkidle",
      });
      await visible(page.getByRole("heading", { name: "Capabilities", exact: true }));
      assert.equal(
        await page.locator("main input[type=number], main input[role=switch]").count(),
        0,
      );
      const targetLink = page
        .locator('[data-feature="p1"]')
        .getByRole("link", { name: "Open Irrigation" });
      assert.match(await targetLink.getAttribute("href"), /plan\/targets\?feature=p1$/);
      await page.getByRole("searchbox", { name: "Search features" }).fill("p1_target_vwc");
      assert.equal(await page.locator("[data-feature]").count(), 1);
      assert.equal(calls.length, before, "searching and browsing never writes settings");
    },
  );
  await check(
    "AI permissions: reviewed owner, read-only Today summary, refusal preserves draft, 1440 and 390",
    async () => {
      const labels = [
        "Start the next phase early",
        "End the morning ramp",
        "Set a probe aside",
        "Change the EC steer",
        "Adjust maintenance watering",
        "Apply today's plan day",
        "Set targets from what a zone reaches",
        "Tune shot sizes",
      ];
      const id = (key) => `switch.crop_steering_room_b_ai_power_${key}`;
      const box = (key) => page.locator(`#config-ai_power_${key}`).getByRole("switch");
      async function applyReview() {
        await page.getByRole("button", { name: "Review changes", exact: true }).click();
        await page
          .getByRole("dialog")
          .getByRole("button", { name: "Apply 1 change", exact: true })
          .click();
      }
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
        await page.goto(`${base}/dashboard.html?room=room_b#/settings/ai`, {
          waitUntil: "networkidle",
        });
        await connected();
        const powers = page.locator('[id^="config-ai_power_"]');
        await visible(powers.first());
        assert.equal(await powers.getByRole("switch").count(), 8);
        for (const label of labels)
          await visible(powers.getByRole("heading", { name: new RegExp(label, "i") }));
        for (const toggle of await powers.getByRole("switch").all())
          assert.ok(
            (await toggle.getAttribute("aria-label"))?.endsWith("Room default"),
            "permission has an accessible room-scoped label",
          );
        assert.equal(
          await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
          true,
          `no horizontal scroll at ${width}`,
        );
        await page.screenshot({
          path: path.join(out, `live-ai-powers-${width}.png`),
          fullPage: true,
        });
      }
      let before = calls.length;
      await box("advance_phase").click();
      assert.equal(calls.length, before, "permission changes stay draft until reviewed");
      await applyReview();
      await page.getByRole("dialog").waitFor({ state: "hidden" });
      assert.equal(await box("advance_phase").isChecked(), false);
      assert.deepEqual(calls.slice(before), [
        { path: "/api/services/switch/turn_off", entity_id: id("advance_phase") },
      ]);
      before = calls.length;
      await box("tune_shot_sizes").click();
      await applyReview();
      await page.getByRole("dialog").waitFor({ state: "hidden" });
      assert.equal(await box("tune_shot_sizes").isChecked(), true);
      assert.deepEqual(calls.slice(before), [
        { path: "/api/services/switch/turn_on", entity_id: id("tune_shot_sizes") },
      ]);
      failWrite = id("ec_mode");
      await box("ec_mode").click();
      await applyReview();
      await visible(page.getByRole("dialog").getByText(/Fixture refused write/));
      assert.equal(states[id("ec_mode")].state, "on");
      await page.getByRole("button", { name: "Back to editing" }).click();
      assert.equal(
        await box("ec_mode").isChecked(),
        false,
        "failed permission draft remains available",
      );
      await page.getByRole("button", { name: "Discard draft", exact: true }).click();
      assert.equal(await box("ec_mode").isChecked(), true);
      failWrite = "";
      before = calls.length;
      await page.goto(`${base}/dashboard.html?room=room_b#/today/ai`, { waitUntil: "networkidle" });
      assert.equal(
        await page.locator("[data-brain-powers] input").count(),
        0,
        "Today AI only summarizes permissions",
      );
      await visible(page.getByRole("link", { name: "Manage permissions" }));
      await page.setViewportSize({ width: 1440, height: 1000 });
      await roomChip("room:").click();
      const old = page.locator("[data-brain-powers]");
      await visible(old);
      assert.equal(await old.locator("input").count(), 0);
      assert.match(await old.innerText(), /Unavailable/);
      await page.getByRole("link", { name: "Manage permissions" }).click();
      assert.equal(
        await page.locator('[id^="config-ai_power_"] input').count(),
        0,
        "missing entities have no pretend editor",
      );
      assert.equal(calls.length, before);
    },
  );
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
