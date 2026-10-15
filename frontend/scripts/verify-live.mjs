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
for (const prefix of ["", "f1_"]) {
  const name = prefix ? "Flower 1" : "Flower 2",
    flag = prefix ? "switch.crop_steering_f1_engine_enabled" : "input_boolean.f2_control_enabled";
  put(`sensor.crop_steering_${prefix}engine_config`, "ready", {
    prefix,
    slug: prefix ? "f1" : "",
    num_zones: 2,
    friendly_name: `${name} engine config`,
    enable_flag: flag,
    // F1 runs a pair that reports its versions; the default room models an older pair that does not
    ...(prefix ? { integration_version: "2.19.1" } : {}),
  });
  put(`sensor.crop_steering_${prefix}ai_heartbeat`, "online", {
    enable_flag: flag,
    last_beat: new Date().toISOString(),
    ...(prefix ? { controller_version: "0.16.1" } : {}),
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
const menu = (name) =>
  page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name, exact: true })
    .click();
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
    await connected();
    assert.equal(await page.locator("#desktop-room").inputValue(), "room:f1_");
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
      await page.locator("#desktop-room").selectOption("room:");
      await visible(versions.getByText("not reported").first());
      assert.equal((await versions.innerText()).match(/not reported/g).length, 2);
      await page.locator("#desktop-room").selectOption("room:f1_");
      await visible(versions.getByText("2.19.1"));
    },
  );
  await check(
    "the navigation scrolls on a phone and in a short window, down to the versions in its footer",
    async () => {
      // Seen on a real phone: the drawer was screen-high, the menu taller, and it would not scroll.
      const phone = await context.newPage();
      try {
        await phone.setViewportSize({ width: 390, height: 640 });
        await phone.goto(`${base}/dashboard.html?room=f1#/today`, { waitUntil: "networkidle" });
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
        assert.ok(box && box.y >= 0 && box.y + box.height <= 640, "versions must be reachable");
        assert.match(await versions.innerText(), /Controller\s+0\.16\.1/);
        assert.ok((await drawer.evaluate((el) => el.scrollTop)) > 0, "it really scrolled");
        // and the first item is still reachable on the way back
        await drawer.getByRole("button", { name: "Today" }).scrollIntoViewIfNeeded();
      } finally {
        await phone.close();
      }
      const short = await context.newPage();
      try {
        await short.setViewportSize({ width: 1280, height: 480 });
        await short.goto(`${base}/dashboard.html?room=f1#/today`, { waitUntil: "networkidle" });
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
    "an open dropdown can be read on a dark Home Assistant theme (targets, timeline, zone, compare)",
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
        for (const route of ["plan/targets", "history/timeline", "zone/1", "history/compare"]) {
          await themed.goto(`${base}/dashboard.html?room=f1#/${route}`, {
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
    await menu("Today");
    await visible(page.getByRole("heading", { name: "Flower 1 today", exact: true }));
    // The room's line counts the alert; opened, it says which zone and why.
    await page.locator(".today-alerts").click();
    await visible(
      page
        .locator(".today-alert-list")
        .getByText("Zone 1: sensor data unavailable.", { exact: true }),
    );
    assert.equal(await page.getByText("Invalid Date", { exact: false }).count(), 0);
    assert.equal(await page.locator(".demo-pill").count(), 0);
    // The room's line first, then a card per zone.
    const order = await page.evaluate(() =>
      [...document.querySelectorAll(".today-head, .today-zones, [data-jev-today]")].map(
        (el) => el.classList[0],
      ),
    );
    assert.deepEqual(order, ["today-head", "today-zones"]);
    assert.equal(await page.locator("article.today-zone").count(), 2);
  });
  await check(
    "stale probe is unavailable on Equipment › Probes and in the controller's sensors",
    async () => {
      const probe = "sensor.crop_steering_f1_vwc_zone_1";
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
      const ec = "sensor.crop_steering_f1_ec_zone_1";
      assert.equal(await health(ec).getAttribute("data-probe-health"), "no-reading");
      assert.equal(await health(ec).getAttribute("data-tone"), "off");
      assert.equal(
        await health("sensor.crop_steering_f1_ec_zone_2").getAttribute("data-tone"),
        "on",
      );
      assert.match(await page.locator(".probes-status").innerText(), /Probes\s+2 of 4 OK/);
      // The controller's own sensors, one tap down: stale is amber, reporting green, down red.
      const internals = page.locator("details.probes-more", { hasText: "Controller internals" });
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
          .filter({ hasText: "sensor.crop_steering_f1_ec_zone_2" })
          .locator(".pill")
          .getAttribute("data-tone"),
        "on",
      );
      assert.match(await internals.locator("summary").innerText(), /\(\d+ of \d+ reporting\)/);
      await internals
        .getByRole("combobox", { name: "Filter sensor availability" })
        .selectOption("unavailable");
      await visible(row);
    },
  );
  await check(
    "probes: each probe's line, and the controller's sensors', one request each",
    async () => {
      // Settings reads no history: anything asked for after this is Equipment's.
      await menu("Settings & help");
      await visible(page.getByRole("heading", { name: "Settings", exact: true }));
      await page.waitForTimeout(1000);
      history.length = 0;
      await menu("Equipment");
      await visible(page.getByRole("heading", { name: "Probes", exact: true }));
      await page.waitForFunction(() => document.querySelectorAll(".probes-table tr").length > 1);
      await page.waitForTimeout(1000);
      const probes = [1, 2]
        .flatMap((zone) => [
          `sensor.crop_steering_f1_vwc_zone_${zone}`,
          `sensor.crop_steering_f1_ec_zone_${zone}`,
        ])
        .sort();
      const numeric = Object.values(states)
        .filter(
          (e) =>
            e.entity_id.startsWith("sensor.crop_steering_f1_") &&
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
      const internals = page.locator("details.probes-more", { hasText: "Controller internals" });
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
        .getByRole("button", { name: "Tank & pump", exact: true })
        .click();
      await visible(
        page
          .locator("[data-tank-status]")
          .getByText("Disconnected · last received", { exact: true }),
      );
      await menu("Plan");
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
    await visible(page.getByRole("heading", { name: "No zones discovered", exact: true }));
    await visible(page.getByRole("heading", { level: 1, name: "Today", exact: true }));
    assert.equal(await page.locator("#desktop-room").isDisabled(), true);
    // A zone's old address finds no zone either, and says so.
    await page.evaluate(() => (location.hash = "#/zone/1"));
    await visible(page.getByRole("heading", { name: "No zones discovered", exact: true }));
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
      assert.equal(await page.locator("#desktop-room").inputValue(), "room:f2_");
      await visible(
        page.locator('input[id="setting-number.crop_steering_f2_zone_1_p2_vwc_threshold"]'),
      );
      await menu("Settings & help");
      await page
        .getByRole("navigation", { name: "Settings & help views" })
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
      await page.locator("#desktop-room").selectOption("room:");
      await visible(page.getByRole("heading", { name: "Help", exact: true }));
      assert.equal(await page.locator("#desktop-room").inputValue(), "room:");
      assert.equal(new URL(page.url()).hash, "#/help");
    },
  );
  await check("classic roundtrip preserves default and F1 alongside a named F2", async () => {
    for (const [query, expected] of [
      ["?room=f2", "room:"],
      ["?room=f1", "room:f1_"],
      ["", "room:"],
    ]) {
      await page.goto(`${base}/f2-classic.html${query}`, { waitUntil: "networkidle" });

      await connected();
      assert.equal(await page.locator("#desktop-room").inputValue(), expected);
      assert.equal(new URL(page.url()).searchParams.get("room"), expected);
    }
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
    await page.goto(`${base}/dashboard.html?room=f1#/today`, { waitUntil: "networkidle" });
    await visible(dialog);
    assert.deepEqual(
      (await dialog.locator("section h3").allInnerTexts()).map((text) => text.split("\n")[0]),
      ["Version 2.25.0"],
    );
    // Told as it opens, with the installed version, over the REST call the integration answers.
    assert.deepEqual(told(), [
      { path: "/api/services/crop_steering/whats_new_seen?return_response", version: "2.25.0" },
    ]);
    await dialog.getByRole("button", { name: "Got it", exact: true }).click();
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
