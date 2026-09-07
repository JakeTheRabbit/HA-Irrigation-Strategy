import test from "node:test";
import assert from "node:assert/strict";
import { mockHa, stdio, call, data, planFixture, TOKEN } from "./mock-ha.mjs";

const preview = async (client) =>
  data(
    await call(client, "preview_setup", {
      room_id: "room:veg_",
      changes: {
        room_name: "Veg renamed",
        zones: [{ id: 1, plant_count: 48 }],
      },
    }),
  );
const apply = (client, p, overrides = {}) =>
  call(client, "apply_proposal", {
    room_id: p.room_id,
    expected_revision: p.expected_revision,
    proposal_token: p.proposal_token,
    ...overrides,
  });
const error = (result, pattern) => {
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, pattern);
};

test("real stdio initialize, tools/list, bounded reads, exact room isolation, and missing values", async (t) => {
  const ha = await mockHa(t),
    { client, stderr } = await stdio(t, ha);
  assert.equal(client.getServerVersion().name, "crop-steering");
  const tools = (await client.listTools()).tools;
  assert.equal(tools.length, 9);
  assert.deepEqual(
    tools
      .filter((tool) => !tool.annotations.readOnlyHint)
      .map((tool) => tool.name),
    ["apply_proposal"],
  );
  assert.ok(
    !tools.some((tool) =>
      /activate|turn_on|execute|create_room/.test(tool.name),
    ),
  );
  const rooms = data(await call(client, "list_rooms"));
  assert.equal(rooms.writes_enabled, false);
  assert.deepEqual(
    rooms.rooms.map((r) => r.room_id),
    ["room:", "room:veg_"],
  );
  assert.ok(!JSON.stringify(rooms).includes(TOKEN));
  const cfg = data(
    await call(client, "get_room_configuration", { room_id: "room:veg_" }),
  );
  assert.equal(cfg.hardware.pump_switch, "switch.veg_pump");
  const status = data(
    await call(client, "get_room_status", { room_id: "room:veg_" }),
  );
  assert.equal(
    status.readings.find((r) => r.entity_id.endsWith("last_irrigation_app"))
      .state,
    null,
  );
  assert.ok(!status.readings.some((r) => r.entity_id === "switch.pump"));
  assert.ok(!JSON.stringify(status).includes("internal_secret"));
  const search = data(
    await call(client, "search_candidate_entities", { query: "veg", limit: 2 }),
  );
  assert.equal(search.candidates.length, 2);
  assert.equal(search.next_offset, 2);
  const runs = data(
    await call(client, "get_room_runs", {
      room_id: "room:veg_",
      limit: 2,
      offset: 3,
    }),
  );
  assert.equal(runs.runs[0].id, "run-3");
  assert.equal(runs.total, 12);
  error(
    await call(client, "get_room_configuration", { room_id: "room:missing_" }),
    /unknown/,
  );
  error(
    await call(client, "get_room_status", { room_id: "room:veg_", zone_id: 2 }),
    /does not belong/,
  );
  assert.equal(ha.saveCount, 0);
  assert.equal(stderr(), "");
});

test("reviewed setup saves exact server payload and reads back, preserving other room/settings", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, { CROP_STEERING_ALLOW_WRITES: "true" });
  const before = structuredClone(ha.rooms[0]);
  const p = await preview(client);
  assert.equal(ha.saveCount, 0);
  assert.equal(p.expected_revision, 4);
  assert.equal(p.diff.length, 2);
  error(
    await apply(client, p, { changes: { room_name: "injected" } }),
    /Unrecognized|Invalid/,
  );
  error(await apply(client, p, { room_id: "room:" }), /does not match/);
  const saved = data(await apply(client, p));
  assert.equal(saved.verified, true);
  assert.equal(saved.revision, 5);
  assert.equal(ha.rooms[1].zones[0].plant_count, 48);
  assert.equal(ha.rooms[1].zones[0].substrate_volume, 6.75);
  assert.deepEqual(ha.rooms[0], before);
  assert.equal(ha.saveCount, 1);
  const submitted = ha.calls.find((row) =>
    row.path.includes("/setup_save?"),
  ).body;
  assert.deepEqual(submitted, {
    entry_id: "entry-veg_",
    expected_revision: 4,
    ...p.proposed_configuration,
  });
  error(await apply(client, p), /already used/);
  assert.equal(ha.saveCount, 1);
});

test("read-only default and strict input schema block saves and control flags", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha);
  const p = await preview(client);
  error(await apply(client, p), /Writes are disabled/);
  for (const changes of [
    { enabled: true },
    { hardware: { enable_flag: "switch.engine" } },
    { zones: [{ id: 1, active: true }] },
    { zones: [{ id: 1, plant_count: 1.5 }] },
    { hardware: { pump_switch: "http://outside" } },
  ]) {
    error(
      await call(client, "preview_setup", { room_id: "room:veg_", changes }),
      /Invalid|Unrecognized|integer/,
    );
  }
  assert.equal(ha.saveCount, 0);
});

test("stale revision or sizing changed without revision invalidates exact preview", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, { CROP_STEERING_ALLOW_WRITES: "true" });
  const p = await preview(client);
  ha.rooms[1].revision++;
  error(await apply(client, p), /changed after preview/);
  const q = await preview(client);
  ha.rooms[1].zones[0].dripper_flow_rate = 2;
  error(await apply(client, q), /changed after preview/);
  assert.equal(ha.saveCount, 0);
});

test("setup blocks unavailable equipment and HA remains final safety authority", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, { CROP_STEERING_ALLOW_WRITES: "true" });
  let p = await preview(client);
  ha.rooms[1].safety = { ready: false, blockers: ["Unknown pump"] };
  error(await apply(client, p), /setup blockers/);
  assert.equal(ha.saveCount, 0);
  ha.rooms[1].safety = { ready: true, blockers: [] };
  p = await preview(client);
  ha.intercept = (req, res, body, json) => {
    if (!req.url.includes("/setup_save?")) return false;
    json({ message: "New mapped pump must read OFF" }, 400);
    return true;
  };
  error(await apply(client, p), /must read OFF/);
  assert.equal(ha.saveCount, 0);
});

test("candidate existence, units, duplicate zones and foreign zones are checked before token issue", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha);
  for (const [changes, pattern] of [
    [{ hardware: { tank_ec_sensor: "sensor.veg_vwc" } }, /Incompatible ec/],
    [{ hardware: { pump_switch: "switch.missing" } }, /existing switch/],
    [{ zones: [{ id: 2, plant_count: 20 }] }, /existing zone IDs/],
    [{ zones: [{ id: 1 }, { id: 1 }] }, /Duplicate/],
    [
      { zones: [{ id: 1, vwc_sensors: ["sensor.veg_vwc", "sensor.veg_vwc"] }] },
      /unique/,
    ],
  ])
    error(
      await call(client, "preview_setup", { room_id: "room:veg_", changes }),
      pattern,
    );
  assert.equal(ha.saveCount, 0);
});

test("HA validates plan preview, then only draft saved with exact readback; no activation call", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, { CROP_STEERING_ALLOW_WRITES: "true" });
  const plan = planFixture();
  plan.profiles[0].vegetative.p1_target_vwc = 65;
  const p = data(
    await call(client, "preview_plan", { room_id: "room:veg_", plan }),
  );
  assert.equal(ha.saveCount, 0);
  assert.equal(p.preview.zones[0].parameters.p1_target_vwc, 65);
  const result = data(await apply(client, p));
  assert.equal(result.status, "draft");
  assert.equal(result.revision, 8);
  assert.deepEqual(ha.plans["room:veg_"].plan, plan);
  assert.equal(ha.plans["room:"].revision, 7);
  assert.ok(ha.calls.some((row) => row.path.includes("/strategy_preview?")));
  assert.ok(
    !ha.calls.some((row) =>
      /activate|disarm|turn_on|number\/set_value/.test(row.path),
    ),
  );
  const invalid = planFixture();
  invalid.profiles[0].vegetative.p1_target_vwc = 99;
  error(
    await call(client, "preview_plan", { room_id: "room:veg_", plan: invalid }),
    /outside readable HA bounds/,
  );
  ha.plans["room:veg_"].status = "active";
  error(
    await call(client, "preview_plan", { room_id: "room:veg_", plan }),
    /not draft/,
  );
});

test("changed plan bounds or active status after preview block draft save", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, { CROP_STEERING_ALLOW_WRITES: "true" });
  const plan = planFixture();
  plan.profiles[0].name = "New profile";
  let p = data(
    await call(client, "preview_plan", { room_id: "room:veg_", plan }),
  );
  ha.plans["room:veg_"].catalog = {
    1: { p1_target_vwc: { min: 20, max: 60 } },
  };
  error(await apply(client, p), /bounds changed/);
  p = data(await call(client, "preview_plan", { room_id: "room:veg_", plan }));
  ha.plans["room:veg_"].status = "armed";
  error(await apply(client, p), /bounds changed/);
  assert.equal(ha.saveCount, 0);
});

test("simultaneous token replay submits at most one write", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, { CROP_STEERING_ALLOW_WRITES: "true" });
  const p = await preview(client);
  const results = await Promise.all([apply(client, p), apply(client, p)]);
  assert.equal(results.filter((r) => !r.isError).length, 1);
  assert.equal(ha.saveCount, 1);
});

test("write timeout is uncertain, consumes token, never automatically retries", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, {
      CROP_STEERING_ALLOW_WRITES: "true",
      HA_TIMEOUT_MS: "100",
    });
  const p = await preview(client);
  ha.intercept = (req, res) => {
    if (!req.url.includes("/setup_save?")) return false;
    ha.saveCount++;
    return true;
  };
  error(await apply(client, p), /timed out.*Do not assume/);
  error(await apply(client, p), /already used/);
  assert.equal(ha.saveCount, 1);
});

test("redirects are rejected without forwarding credentials and errors redact secrets", async (t) => {
  const ha = await mockHa(t),
    sink = await mockHa(t),
    { client } = await stdio(t, ha);
  ha.intercept = (req, res) => {
    res.writeHead(302, { Location: sink.url + "/api/states" });
    res.end();
    return true;
  };
  error(await call(client, "list_rooms"), /Redirects are rejected/);
  assert.equal(sink.calls.length, 0);
  ha.intercept = (req, res, body, json) => {
    json({ message: `Rejected ${TOKEN}` }, 400);
    return true;
  };
  const result = await call(client, "list_rooms");
  error(result, /REDACTED/);
  assert.ok(!JSON.stringify(result).includes(TOKEN));
});

test("readback mismatch is reported as submitted, never verified success", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, { CROP_STEERING_ALLOW_WRITES: "true" });
  const p = await preview(client);
  ha.intercept = (req, res, body, json) => {
    if (!req.url.includes("/setup_save?")) return false;
    ha.saveCount++;
    json({ service_response: {} });
    return true;
  };
  error(await apply(client, p), /submitted but readback did not match/);
  assert.equal(ha.saveCount, 1);
});

test("legacy default descriptor is default-only and its prefix must match the room", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha);
  ha.states.delete("sensor.crop_steering_ai_heartbeat");
  ha.states.set("sensor.crop_steering_system_engine_config", {
    state: "configured",
    attributes: { prefix: "", enable_flag: "switch.legacy_engine" },
  });
  ha.states.set("switch.legacy_engine", { state: "off" });
  const status = data(
    await call(client, "get_room_status", { room_id: "room:" }),
  );
  assert.equal(
    status.readings.find((row) => row.entity_id === "switch.legacy_engine")
      .state,
    "off",
  );
  ha.calls.length = 0;
  await call(client, "get_room_status", { room_id: "room:veg_" });
  assert.ok(!ha.calls.some((row) => row.path.includes("system_engine_config")));
  ha.states.set("sensor.crop_steering_veg_engine_config", {
    state: "configured",
    attributes: { prefix: "", enable_flag: "switch.legacy_engine" },
  });
  error(
    await call(client, "get_room_status", { room_id: "room:veg_" }),
    /prefix does not match/,
  );
});

test("legacy null mappings normalize only inbound, preserve setup, reject new null writes", async (t) => {
  const ha = await mockHa(t);
  ha.rooms[1].hardware.waste_switch = null;
  const { client } = await stdio(t, ha, { CROP_STEERING_ALLOW_WRITES: "true" });
  const cfg = data(
    await call(client, "get_room_configuration", { room_id: "room:veg_" }),
  );
  assert.equal(cfg.hardware.waste_switch, "");
  const p = await preview(client);
  assert.equal(p.proposed_configuration.hardware.waste_switch, "");
  const applied = data(await apply(client, p));
  assert.equal(applied.verified, true);
  assert.equal(ha.rooms[1].hardware.pump_switch, "switch.veg_pump");
  error(
    await call(client, "preview_setup", {
      room_id: "room:veg_",
      changes: { hardware: { waste_switch: null } },
    }),
    /Invalid/,
  );
});
