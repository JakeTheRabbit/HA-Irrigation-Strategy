import test from "node:test";
import assert from "node:assert/strict";
import { mockHa, stdio, call, data } from "./mock-ha.mjs";

const ROOM = "room:room_b_";
const WRITES = { CROP_STEERING_ALLOW_WRITES: "true" };
const serviceCalls = (ha, service) =>
  ha.calls.filter((c) =>
    c.path.startsWith(`/api/services/crop_steering/${service}?`),
  );
const error = (result, pattern) => {
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, pattern);
};
const apply = (client, p) =>
  call(client, "apply_proposal", {
    proposal_token: p.proposal_token,
    expected_revision: p.expected_revision,
    ...(p.room_id === null ? {} : { room_id: p.room_id }),
  });
// The proposal every preview tool answers.
const proposal = (p, kind, room_id, expected_revision) => {
  assert.match(p.proposal_token, /^[a-f0-9]{64}$/);
  assert.equal(p.kind, kind);
  assert.equal(p.room_id, room_id);
  assert.equal(p.expected_revision, expected_revision);
  assert.ok(p.diff.length > 0);
  assert.ok(p.preview && typeof p.preview === "object");
};
const writeCall = (ha, service) =>
  serviceCalls(ha, service).filter((c) => !c.body.preview);

test("preview_supply returns a token and apply writes with client mcp", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, WRITES);
  const pumps = [
    { entity_id: "switch.room_b_pump", max_flow_lph: 900, max_concurrent_zones: 2 },
  ];
  const p = data(await call(client, "preview_supply", { irrigation_pumps: pumps }));
  proposal(p, "supply", null, 2);
  assert.deepEqual(p.preview.capacity_check, []);
  assert.equal(p.diff[0].path, "irrigation_pumps");
  const [previewed] = serviceCalls(ha, "supply_save");
  assert.deepEqual(previewed.body, {
    api: 2,
    expected_revision: 2,
    irrigation_pumps: pumps,
    preview: true,
  });
  assert.equal(ha.saveCount, 0);
  const out = data(await apply(client, p));
  assert.equal(out.verified, true);
  assert.equal(out.revision, 3);
  const [written] = writeCall(ha, "supply_save");
  assert.deepEqual(written.body, {
    api: 2,
    expected_revision: 2,
    irrigation_pumps: pumps,
    client: "mcp",
    proposal_token: p.proposal_token,
  });
  // Read back: supply_get, then an empty re-preview at the new revision.
  const after = serviceCalls(ha, "supply_save").at(-1);
  assert.equal(after.body.preview, true);
  assert.equal(after.body.expected_revision, 3);
  assert.deepEqual(ha.supply.irrigation_pumps, pumps);
  assert.equal(ha.saveCount, 1);
  // Single use.
  error(await apply(client, p), /missing, expired, or already used/);
});

test("apply refuses when the revision moved after preview", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, WRITES);
  const p = data(
    await call(client, "preview_timer_program", {
      room_id: ROOM,
      program: {
        id: "t1",
        name: "Morning",
        type: "simple",
        zones: [1],
        duration_s: 90,
        frequency_per_day: 2,
      },
    }),
  );
  proposal(p, "timer_program", ROOM, 3);
  assert.deepEqual(p.diff, [{ path: "/duration_s", before: 60, after: 90 }]);
  assert.equal(p.preview.total_s, 90);
  ha.timers.revision = 4; // another client saved
  error(await apply(client, p), /revision moved after preview/);
  assert.equal(ha.saveCount, 0);
  assert.equal(ha.timers.programs[0].duration_s, 60);
  // An alert rule and a probe offset say the same.
  const rule = data(
    await call(client, "preview_alert_rule", {
      room_id: ROOM,
      rule: { id: "r1", zones: [1], source: "zone.vwc", op: "below", threshold: 25 },
    }),
  );
  ha.rules.revision++;
  error(await apply(client, rule), /revision moved after preview/);
  const probe = data(
    await call(client, "preview_probe_offset", {
      room_id: ROOM,
      entity_id: "sensor.room_b_vwc",
      offset: 2,
    }),
  );
  ha.calibration.revision++;
  error(await apply(client, probe), /revision moved after preview/);
  assert.equal(ha.saveCount, 0);
});

test("timer programs, alert rules and probe offsets apply and read back revision + 1", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, WRITES);
  const timer = data(
    await call(client, "preview_timer_program", {
      room_id: ROOM,
      program: { name: "Evening", type: "recycle", zones: [2, 3], duration_s: 30, interval_min: 45 },
      hours: 12,
    }),
  );
  assert.deepEqual(serviceCalls(ha, "timer_program_preview")[0].body.hours, 12);
  let out = data(await apply(client, timer));
  assert.equal(out.verified, true);
  assert.equal(out.revision, 4);
  const [set] = writeCall(ha, "timer_program_set");
  assert.equal(set.body.client, "mcp");
  assert.equal(set.body.proposal_token, timer.proposal_token);
  assert.equal(set.body.expected_revision, 3);
  assert.equal(set.body.program.active, true);
  // A zone twice is refused before any call.
  error(
    await call(client, "preview_timer_program", {
      room_id: ROOM,
      program: { name: "x", type: "simple", zones: [1, 1], duration_s: 1, frequency_per_day: 1 },
    }),
    /zones|unique/i,
  );

  const rule = data(
    await call(client, "preview_alert_rule", {
      room_id: ROOM,
      rule: { zones: [3, 1], source: "zone.vwc", op: "below", threshold: 25 },
    }),
  );
  proposal(rule, "alert_rule", ROOM, 5);
  assert.match(rule.preview.summary_sentence, /below 25/);
  const [previewedRule] = serviceCalls(ha, "alert_rule_preview");
  assert.equal(previewedRule.body.rule.room_id, ROOM);
  assert.deepEqual(previewedRule.body.rule.zones, [1, 3]);
  out = data(await apply(client, rule));
  assert.equal(out.revision, 6);
  assert.equal(writeCall(ha, "alert_rule_set")[0].body.client, "mcp");

  // A handheld match is stored as the offset it worked out, so apply writes what was reviewed.
  const probe = data(
    await call(client, "preview_probe_offset", {
      room_id: ROOM,
      entity_id: "sensor.room_b_vwc",
      match_handheld: 53,
    }),
  );
  proposal(probe, "probe_offset", ROOM, 9);
  assert.ok(!probe.diff.some((row) => row.path.endsWith(".at")));
  out = data(await apply(client, probe));
  assert.equal(out.revision, 10);
  const [offset] = writeCall(ha, "probe_offset_set");
  assert.deepEqual(offset.body, {
    api: 2,
    room_id: ROOM,
    entity_id: "sensor.room_b_vwc",
    offset: 3,
    curve: "none",
    expected_revision: 9,
    client: "mcp",
    proposal_token: probe.proposal_token,
  });
  // A rule for another room's probe is refused by HA, as a tool error.
  error(
    await call(client, "preview_probe_offset", {
      room_id: ROOM,
      entity_id: "sensor.vwc",
      offset: 1,
    }),
    /invalid: That is not a moisture probe/,
  );
  // A readback that does not match is never reported as verified.
  const again = data(
    await call(client, "preview_alert_rule", {
      room_id: ROOM,
      rule: { id: "r1", zones: [1], source: "zone.vwc", op: "above", threshold: 80 },
    }),
  );
  ha.v2.alert_rule_list = (body) => ({ rules: [], revision: ha.rules.revision });
  error(await apply(client, again), /readback did not match/);
});

test("preset apply is verified by an empty re-preview diff, not a revision", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, WRITES);
  const p = data(
    await call(client, "preview_preset_apply", {
      room_id: ROOM,
      preset_id: "p1",
      zones: [1],
    }),
  );
  proposal(p, "preset_apply", ROOM, 0);
  assert.deepEqual(p.diff, [
    { target: { room_id: ROOM, zone: 1 }, key: "p1_target_vwc", old: 58, new: 65 },
  ]);
  const out = data(await apply(client, p));
  assert.equal(out.verified, true);
  assert.equal(ha.numbers[ROOM + "/1"].p1_target_vwc, 65);
  const calls = serviceCalls(ha, "preset_apply");
  // preview, unchanged-since-review check, write, empty re-preview
  assert.deepEqual(
    calls.map((c) => Boolean(c.body.preview)),
    [true, true, false, true],
  );
  assert.deepEqual(calls[2].body, {
    api: 2,
    preset_id: "p1",
    to: [{ room_id: ROOM, zone: 1 }],
    client: "mcp",
    proposal_token: p.proposal_token,
  });
  // No revision is involved: no *_list or supply_get readback.
  assert.equal(serviceCalls(ha, "timer_program_list").length, 0);

  // A write that does not take leaves a diff: not verified.
  ha.numbers[ROOM + "/1"].p1_target_vwc = 58;
  ha.presetFault = "sticky";
  const sticky = data(
    await call(client, "preview_preset_apply", { room_id: ROOM, preset_id: "p1", zones: [1] }),
  );
  error(await apply(client, sticky), /not verified|did not read back/);
});

test("a refused timer row blocks verification; a copy previews and applies the same way", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, WRITES);
  // Copy zone 1 of the default room to Room B's zone 1.
  const p = data(
    await call(client, "preview_copy_config", {
      room_id: ROOM,
      from: { room_id: "room:", zone: 1 },
      zones: [1],
      sections: ["targets"],
    }),
  );
  proposal(p, "copy_config", ROOM, 0);
  assert.deepEqual(serviceCalls(ha, "copy_config")[0].body, {
    api: 2,
    from: { room_id: "room:", zone: 1 },
    to: [{ room_id: ROOM, zone: 1 }],
    sections: ["targets"],
    preview: true,
  });
  // Once written, the re-preview has an empty diff but names a refused timer row in `missing`.
  ha.presetFault = "timer";
  const result = await apply(client, p);
  error(result, /not verified/);
  assert.match(result.content[0].text, /source room has no timer programs/);
  assert.equal(ha.numbers[ROOM + "/1"].p1_target_vwc, 66);
  // A preview that already names a value HA cannot write is refused: it could never verify.
  error(
    await call(client, "preview_copy_config", {
      room_id: ROOM,
      from: { room_id: "room:", zone: 1 },
      zones: [1],
      sections: ["targets"],
    }),
    /could never be verified/,
  );
});

test("a preset target that changed after review is refused before the write", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, WRITES);
  const p = data(
    await call(client, "preview_preset_apply", { room_id: ROOM, preset_id: "p1" }),
  );
  ha.numbers[ROOM].p1_target_vwc = 61;
  error(await apply(client, p), /changed after preview/);
  assert.equal(writeCall(ha, "preset_apply").length, 0);
  assert.equal(ha.numbers[ROOM].p1_target_vwc, 61);
});

test("previews work with writes disabled and never send client or proposal_token", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha);
  const previews = [
    ["preview_supply", { irrigation_pumps: [{ entity_id: "switch.room_b_pump" }] }],
    ["preview_timer_program", { room_id: ROOM, program: { name: "N", type: "one_off", zones: [1], duration_s: 5, start_at: "2026-10-24T06:00:00+13:00" } }],
    ["preview_alert_rule", { room_id: ROOM, rule: { zones: [1], source: "zone.vwc", op: "above", threshold: 70 } }],
    ["preview_preset_apply", { room_id: ROOM, preset_id: "p1" }],
    ["preview_copy_config", { room_id: ROOM, from: { room_id: "room:", zone: 1 }, sections: ["targets"] }],
    ["preview_probe_offset", { room_id: ROOM, entity_id: "sensor.room_b_vwc", offset: 1 }],
  ];
  const tools = (await client.listTools()).tools;
  let proposals = [];
  for (const [name, args] of previews) {
    assert.equal(tools.find((tool) => tool.name === name).annotations.readOnlyHint, true);
    const p = data(await call(client, name, args));
    assert.equal(p.writes_enabled, false);
    proposals.push(p);
  }
  for (const c of ha.calls.filter((c) => c.body))
    assert.ok(!("client" in c.body) && !("proposal_token" in c.body), c.path);
  for (const p of proposals) error(await apply(client, p), /Writes are disabled/);
  assert.equal(ha.saveCount, 0);
  assert.ok(ha.calls.every((c) => !c.body || c.body.preview !== false));
  // An unknown room never reaches the previewing service.
  const before = ha.calls.length;
  error(
    await call(client, "preview_preset_apply", { room_id: "room:nope_", preset_id: "p1" }),
    /unknown/,
  );
  assert.ok(ha.calls.slice(before).every((c) => c.path.includes("/setup_read?")));
});

test("hardware-moving services are not in the allowlist", async () => {
  const { SERVICES, HaClient } = await import("../dist/ha.js");
  for (const service of SERVICES)
    assert.doesNotMatch(service, /^(intent_submit|pump_|calibration_)/, service);
  for (const service of [
    "timer_program_preview",
    "alert_rule_preview",
    "timer_program_list",
    "timer_program_set",
    "alert_rule_set",
    "preset_apply",
    "copy_config",
    "probe_offset_set",
    "supply_save",
  ])
    assert.ok(SERVICES.includes(service), service);
  const ha = new HaClient({ url: "http://127.0.0.1:9", token: "t", writes: true, timeoutMs: 100 });
  for (const service of ["intent_submit", "pump_prime", "pump_calibrate", "calibration_start", "calibration_get"])
    await assert.rejects(ha.service(service), /Unsupported Crop Steering service/);
  // A write is gated; its preview is not.
  const off = new HaClient({ url: "http://127.0.0.1:9", token: "t", writes: false, timeoutMs: 100 });
  for (const service of ["timer_program_set", "alert_rule_set", "preset_apply", "copy_config", "probe_offset_set", "supply_save"])
    await assert.rejects(off.service(service, {}), /Writes are disabled/);
  await assert.rejects(off.service("preset_apply", { preview: true }), /connection failed|timed out/);
});

test("a refused preset or copy row lists what was already changed and what was not", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, WRITES);
  ha.presetFault = "refuse";
  for (const [name, args, service] of [
    ["preview_preset_apply", { room_id: ROOM, preset_id: "p1", zones: [1] }, "preset_apply"],
    ["preview_copy_config", { room_id: ROOM, from: { room_id: "room:", zone: 1 }, sections: ["targets"] }, "copy_config"],
  ]) {
    const p = data(await call(client, name, args));
    const result = await apply(client, p);
    error(result, /guard_refused/);
    const text = result.content[0].text;
    if (service === "preset_apply") {
      // One row, refused: nothing changed.
      assert.match(text, /Changed: nothing/);
      assert.match(text, /Not changed: room:room_b_ zone 1 p1_target_vwc 58 -> 65 \(refused: out of bounds\)/);
    } else {
      // Two rows: p1_target_vwc written, p2_shot_size refused.
      assert.match(text, /Changed: room:room_b_ p1_target_vwc 60 -> 66\./);
      assert.match(text, /Not changed: room:room_b_ p2_shot_size 2 -> 3 \(refused: out of bounds\)/);
      assert.equal(ha.numbers[ROOM].p1_target_vwc, 66);
    }
  }
});

test("preview_timer_program refuses a list answer that carries another room's program", async (t) => {
  const ha = await mockHa(t),
    { client } = await stdio(t, ha, WRITES);
  ha.v2.timer_program_list = () => ({
    programs: [{ ...ha.timers.programs[0], room_id: "room:" }],
    revision: 3,
    error: null,
  });
  error(
    await call(client, "preview_timer_program", {
      room_id: ROOM,
      program: { id: "t1", name: "Morning", type: "simple", zones: [1], duration_s: 90, frequency_per_day: 2 },
    }),
    /Unsupported Crop Steering timer_program_list answer/,
  );
  assert.equal(serviceCalls(ha, "timer_program_preview").length, 0);
});
