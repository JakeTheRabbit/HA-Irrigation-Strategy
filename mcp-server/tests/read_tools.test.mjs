import test from "node:test";
import assert from "node:assert/strict";
import { mockHa, stdio, call, data } from "./mock-ha.mjs";

const ROOM = "room:room_b_";
const serviceCalls = (ha, service) =>
  ha.calls.filter((c) =>
    c.path.startsWith(`/api/services/crop_steering/${service}?`),
  );
const error = (result, pattern) => {
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, pattern);
};
// Every read tool, with arguments, and the service it reads.
const READS = [
  ["get_timeline", { room_id: ROOM, start: "2026-10-22T00:00:00", end: "2026-10-23T00:00:00" }, "timeline_get"],
  ["get_timeline", { room_id: ROOM, days: ["2026-10-21", "2026-10-22"] }, "timeline_summary"],
  ["get_changes", { room_id: ROOM, since: "2026-10-01T00:00:00Z" }, "history_changes"],
  ["get_events", { room_id: ROOM, since: "2026-10-22T00:00:00Z" }, "journal_query"],
  ["get_alert_rules", { room_id: ROOM }, "alert_rule_list"],
  ["get_supply", {}, "supply_get"],
  ["get_system_status", {}, "system_status_get"],
];

test("get_timeline calls timeline_get with api 2 and returns its data", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha);
  const out = data(
    await call(client, "get_timeline", {
      room_id: ROOM,
      start: "2026-10-22T00:00:00",
      end: "2026-10-23T00:00:00",
      zones: [1],
    }),
  );
  const [sent] = serviceCalls(ha, "timeline_get");
  assert.deepEqual(sent.body, {
    api: 2,
    rooms: [ROOM],
    start: "2026-10-22T00:00:00",
    end: "2026-10-23T00:00:00",
    zones: [1],
  });
  // The data, not the envelope; a field the integration adds later passes through.
  assert.deepEqual(out, ha.v2.timeline_get(sent.body));
  assert.equal(out.rooms[0].added_later, true);
});

test("get_timeline with days reads timeline_summary; a span and days together are refused", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha);
  const out = data(
    await call(client, "get_timeline", { room_id: ROOM, days: ["2026-10-22"] }),
  );
  assert.deepEqual(serviceCalls(ha, "timeline_summary")[0].body, {
    api: 2,
    rooms: [ROOM],
    days: ["2026-10-22"],
  });
  assert.equal(out.days[0].rooms[0].shots, 3);
  for (const args of [
    { room_id: ROOM },
    { room_id: ROOM, start: "2026-10-22T00:00:00" },
    { room_id: ROOM, days: ["2026-10-22"], start: "a", end: "b" },
    { room_id: ROOM, days: Array.from({ length: 15 }, () => "2026-10-22") },
    { room_id: ROOM, days: ["22/10/2026"] },
  ])
    assert.equal((await call(client, "get_timeline", args)).isError, true);
  assert.equal(serviceCalls(ha, "timeline_summary").length, 1);
  assert.equal(serviceCalls(ha, "timeline_get").length, 0);
});

test("get_events refuses a limit above 500", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha);
  const since = "2026-10-22T00:00:00Z";
  for (const limit of [501, 0, 1.5])
    error(
      await call(client, "get_events", { room_id: ROOM, since, limit }),
      /limit|500|integer|Invalid|Too/i,
    );
  assert.equal(serviceCalls(ha, "journal_query").length, 0);
  const out = data(
    await call(client, "get_events", {
      room_id: ROOM,
      since,
      limit: 500,
      kinds: ["shot.started"],
      zones: [1],
      actor: "engine",
      cursor: "1700000000000:4",
    }),
  );
  assert.deepEqual(serviceCalls(ha, "journal_query")[0].body, {
    api: 2,
    room_id: ROOM,
    since,
    limit: 500,
    kinds: ["shot.started"],
    zones: [1],
    actor: "engine",
    cursor: "1700000000000:4",
  });
  assert.equal(out.events[0].kind, "shot.started");
  assert.equal(out.cursor, null);
});

test("read tools never call a *_save service", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, { CROP_STEERING_ALLOW_WRITES: "true" });
  const tools = (await client.listTools()).tools;
  for (const [name, args, service] of READS) {
    const tool = tools.find((tool) => tool.name === name);
    assert.equal(tool.annotations.readOnlyHint, true, name);
    data(await call(client, name, args));
    const [sent] = serviceCalls(ha, service);
    assert.equal(sent.body.api, 2, service);
    assert.ok(!("client" in sent.body) && !("proposal_token" in sent.body));
  }
  const services = ha.calls
    .map((c) => /crop_steering\/([a-z_]+)\?/.exec(c.path)?.[1])
    .filter(Boolean);
  assert.ok(services.length >= READS.length);
  assert.ok(!services.some((s) => /_save$|_set$|_delete$|revert|append/.test(s)), services.join());
  assert.equal(ha.saveCount, 0);
});

test("each read returns its data; a room filter is passed and an unknown room never reaches HA", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha);
  assert.deepEqual(
    data(await call(client, "get_changes", { room_id: ROOM, since: "2026-10-01T00:00:00Z", zone: 1, kinds: ["setpoint"] })),
    { changes: [{ event_id: "e1", room_id: ROOM, key: "p1_target_vwc" }] },
  );
  assert.deepEqual(serviceCalls(ha, "history_changes")[0].body, {
    api: 2,
    room_id: ROOM,
    since: "2026-10-01T00:00:00Z",
    zone: 1,
    kinds: ["setpoint"],
  });
  assert.equal(data(await call(client, "get_alert_rules", {})).rules[0].room_id, "room:");
  assert.deepEqual(serviceCalls(ha, "alert_rule_list")[0].body, { api: 2 });
  assert.equal(data(await call(client, "get_supply")).revision, 2);
  assert.equal(data(await call(client, "get_system_status")).controller, "running");
  const before = ha.calls.length;
  for (const [name, args] of READS.filter(([, args]) => args.room_id))
    error(await call(client, name, { ...args, room_id: "room:nope_" }), /unknown/);
  assert.ok(
    ha.calls.slice(before).every((c) => c.path.includes("/setup_read?")),
  );
});

test("an ok:false answer is a tool error with its code and message; a bad shape is refused", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha);
  ha.refuse.timeline_get = { code: "invalid", message: "timeline span is at most 48 h" };
  error(
    await call(client, "get_timeline", { room_id: ROOM, start: "2026-10-20T00:00:00", end: "2026-10-23T00:00:00" }),
    /invalid: timeline span is at most 48 h/,
  );
  ha.refuse.journal_query = { code: "unavailable", message: "The journal is not open" };
  error(
    await call(client, "get_events", { room_id: ROOM, since: "2026-10-22T00:00:00Z" }),
    /unavailable: The journal is not open/,
  );
  ha.v2.supply_get = () => ({ revision: "two" });
  error(await call(client, "get_supply"), /Unsupported Crop Steering supply_get/);
  // An answer for another room is not passed off as this one's.
  ha.v2.timeline_get = () => ({ rooms: [{ room_id: "room:" }], errors: { count: 0, markers: [] } });
  delete ha.refuse.timeline_get;
  error(
    await call(client, "get_timeline", { room_id: ROOM, start: "2026-10-22T00:00:00", end: "2026-10-23T00:00:00" }),
    /Unsupported Crop Steering timeline_get/,
  );
});
