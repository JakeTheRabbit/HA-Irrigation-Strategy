import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";
import { NeedsIntegration } from "@/components/needs-integration";
import { callV2, isMissingService, pagedQuery, PARITY_ACTIONS, PARITY_MIN_VERSION, useParity } from "./parity-api";
import { parityDemo } from "./parity-demo";
import { DEMO_TIMER_PROGRAM_ID } from "./parity-demo/journal";
import { DEMO_PRESET_IDS } from "./parity-demo/presets";
import { demoController, fakeController } from "./test-helpers";
import type { CsEvent } from "./parity-types";

const ev = (n: number): CsEvent => ({
  v: 1, id: String(n).padStart(26, "0"), seq: n, ts: "2026-10-22T07:00:00+13:00", room_id: "room:f2_",
  zone: 1, kind: "shot.completed", outcome: "ok", code: null, source: { actor: "engine" }, data: {},
});

test("callV2 maps service_not_found to missing", async () => {
  const c = fakeController({ operator: () => Promise.reject(Object.assign(new Error("Service crop_steering.timeline_get not found."), { code: "not_found" })) });
  expect(await callV2(c, "timeline_get", {})).toEqual({ kind: "missing" });
});
test("callV2 maps a v1-shaped answer to missing", async () => {
  const c = fakeController({ operator: () => Promise.resolve({ revision: 3, zones: [] }) });
  expect((await callV2(c, "setup_read", {})).kind).toBe("missing");
});
test("callV2 unwraps the v2 envelope", async () => {
  const c = fakeController({ operator: () => Promise.resolve({ api: 2, ok: true, revision: 42, readback: { status: "verified", at: "2026-10-22T14:02:00+13:00" }, event_ids: ["e1"], data: { x: 1 } }) });
  expect(await callV2(c, "supply_get", {})).toEqual({ kind: "ok", data: { x: 1 }, revision: 42, readback: { status: "verified", at: "2026-10-22T14:02:00+13:00" }, eventIds: ["e1"] });
});
test("callV2 keeps stale_revision and current revision", async () => {
  const c = fakeController({ operator: () => Promise.resolve({ api: 2, ok: false, error: { code: "stale_revision", message: "m", current_revision: 43 } }) });
  expect(await callV2(c, "supply_save", {})).toMatchObject({ kind: "error", code: "stale_revision", currentRevision: 43 });
});
test("callV2 never sends client or proposal_token", async () => {
  const op = vi.fn().mockResolvedValue({ api: 2, ok: true, data: {} });
  await callV2(fakeController({ operator: op }), "supply_save", { client: "mcp", proposal_token: "t", x: 1 });
  expect(op.mock.calls[0][1]).toEqual({ x: 1, api: 2 });
});
test("callV2 reports an unknown thrown error as an error, not missing", async () => {
  const c = fakeController({ operator: () => Promise.reject(new Error("Home Assistant request timed out.")) });
  expect(await callV2(c, "supply_get", {})).toEqual({ kind: "error", code: "unknown", message: "Home Assistant request timed out." });
});

describe("isMissingService", () => {
  test.each([
    [{ code: "not_found", message: "x" }],
    [{ code: "service_not_found", message: "x" }],
    [new Error("Service crop_steering.timeline_get not found.")],
    [new Error("Action crop_steering.timeline_get not found.")],
    [new Error("This action needs the updated Crop Steering integration. Open Setup for installation instructions.")],
    [new Error("extra keys not allowed @ data['api']")],
  ])("matches %o", (error) => expect(isMissingService(error)).toBe(true));
  test("does not match other errors", () => {
    expect(isMissingService(new Error("Plan changed. Reload before saving."))).toBe(false);
    expect(isMissingService(null)).toBe(false);
  });
});

test("pagedQuery follows cursor until empty", async () => {
  const pages = [
    { events: Array.from({ length: 500 }, (_, i) => ev(i)), cursor: "a" },
    { events: Array.from({ length: 500 }, (_, i) => ev(500 + i)), cursor: "b" },
    { events: [], cursor: null },
  ];
  const op = vi.fn((_a: string, _d: Record<string, unknown>) => Promise.resolve({ api: 2, ok: true, data: pages.shift() }));
  const out = await pagedQuery(fakeController({ operator: op as never }), { room_id: "room:f2_", since: "2026-10-21T00:00:00Z", kinds: ["shot.completed"] });
  expect(out.kind).toBe("ok");
  if (out.kind === "ok") expect(out.data.events).toHaveLength(1000);
  expect(op).toHaveBeenCalledTimes(3);
  for (const call of op.mock.calls) expect(call[1]).toMatchObject({ room_id: "room:f2_", limit: 500, kinds: ["shot.completed"] });
  expect(op.mock.calls[0][1]).not.toHaveProperty("cursor");
  expect(op.mock.calls[1][1]).toMatchObject({ cursor: "a" });
  expect(op.mock.calls[2][1]).toMatchObject({ cursor: "b" });
});
test("pagedQuery stops at max", async () => {
  const op = vi.fn().mockImplementation(() => Promise.resolve({ api: 2, ok: true, data: { events: Array.from({ length: 500 }, (_, i) => ev(i)), cursor: "more" } }));
  const out = await pagedQuery(fakeController({ operator: op }), { room_id: "room:f2_", since: "x" }, 700);
  expect(op).toHaveBeenCalledTimes(2);
  if (out.kind === "ok") expect(out.data.events).toHaveLength(700);
});
test("pagedQuery passes missing through", async () => {
  const op = vi.fn().mockRejectedValue({ code: "not_found", message: "Service crop_steering.journal_query not found." });
  expect(await pagedQuery(fakeController({ operator: op }), { room_id: "room:", since: "x" })).toEqual({ kind: "missing" });
});

// One demo controller per action (alert previews replay a day minute by minute): slower than 5 s on a loaded machine.
test("demo with backend=3.17 answers every parity action as missing", async () => {
  for (const a of PARITY_ACTIONS) expect((await callV2(demoController("?demo=1&backend=3.17"), a, {})).kind).toBe("missing");
}, 30_000);
// The timer writes and preview need a program the demo can check, as the integration does.
const DAY_TIMER = { id: DEMO_TIMER_PROGRAM_ID, name: "Zone 3 day timer", type: "recycle", zones: [3], duration_s: 60, interval_min: 45, window: { kind: "lights_on" } };
const TANK_RULE = { room_id: "room:", source: "tank.level", op: "below", threshold: 25 };
const ASKED: Partial<Record<string, Record<string, unknown>>> = {
  timer_program_set: { expected_revision: 1, program: DAY_TIMER },
  // The demo keeps the supply as the integration does: a save names the pumps and the revision.
  supply_save: { expected_revision: 1, irrigation_pumps: [], preview: true },
  timer_program_preview: { program: DAY_TIMER },
  timer_program_delete: { expected_revision: 1, id: DEMO_TIMER_PROGRAM_ID },
  preset_save: { name: "Room A now", scope: "all", from: { room_id: "room:" }, expected_revision: 1 },
  preset_apply: { preset_id: DEMO_PRESET_IDS.roomB, to: [{ room_id: "room:" }], preview: true },
  preset_delete: { id: DEMO_PRESET_IDS.timer, expected_revision: 1 },
  copy_config: { from: { room_id: "room:" }, to: [{ room_id: "room:room_b_" }], sections: ["targets"], preview: true },
  // The alert rules are checked as the integration checks them (parity-demo/settings.ts).
  alert_rule_set: { expected_revision: 4, rule: TANK_RULE },
  alert_rule_delete: { expected_revision: 4, id: "01JDEMRULE0000000000000002" },
  alert_rule_test: { rule: TANK_RULE },
  alert_rule_preview: { rule: TANK_RULE },
  dashboard_create: { template: "facility_wall", rooms: ["room:"] },
  probe_offset_set: { entity_id: "sensor.demo_z1_front_vwc", match_handheld: 60, preview: true },
};
test("demo 3.18 answers every parity action ok", async () => {
  for (const a of PARITY_ACTIONS) expect([a, (await callV2(demoController("?demo=1"), a, ASKED[a] ?? {})).kind]).toEqual([a, "ok"]);
}, 30_000);
test("demo 3.18 wraps an existing service in the envelope; 3.17 answers it v1", async () => {
  expect((await callV2(demoController("?demo=1"), "display_get", {})).kind).toBe("ok");
  expect((await callV2(demoController("?demo=1&backend=3.17"), "display_get", {})).kind).toBe("missing");
});
test("a one-room service gets the selected room unless the caller names one; all-rooms reads get none", async () => {
  const c = demoController("?demo=1");
  const since = new Date(Date.now() - 86_400_000).toISOString();
  const own = await callV2<{ events: CsEvent[] }>(c, "journal_query", { since });
  const other = await callV2<{ events: CsEvent[] }>(c, "journal_query", { since, room_id: "room:room_b_" });
  const all = await callV2<{ changes: { room_id: string }[] }>(c, "history_changes", { since });
  if (own.kind !== "ok" || other.kind !== "ok" || all.kind !== "ok") throw new Error("not ok");
  expect(new Set(own.data.events.map((e) => e.room_id))).toEqual(new Set([c.roomId]));
  expect(new Set(other.data.events.map((e) => e.room_id))).toEqual(new Set(["room:room_b_"]));
  expect(new Set(all.data.changes.map((e) => e.room_id))).toEqual(new Set(["room:", "room:room_b_"]));
});
test("pump_stop and reads are never refused behind a write in flight", async () => {
  const c = demoController("?demo=1");
  // All four start before the prime's answer arrives.
  const calls = [
    callV2(c, "pump_prime", { pump: "a", seconds: 10 }),
    callV2(c, "pump_stop", { pump: "a" }),
    callV2(c, "supply_get", {}),
    callV2(c, "supply_save", { expected_revision: 1 }),
  ];
  expect((await Promise.all(calls)).map((o) => o.kind)).toEqual(["ok", "ok", "ok", "error"]);
});
test("preview: true skips the write lock only on the four previewable services", async () => {
  const c = demoController("?demo=1");
  const calls = [
    // Room A's day timer saved as it is (the demo checks a program as the integration does).
    callV2(c, "timer_program_set", {
      room_id: "room:",
      expected_revision: 1,
      program: DAY_TIMER,
    }),
    callV2(c, "pump_prime", { pump: "a", seconds: 10, preview: true }),
    callV2(c, "supply_save", { expected_revision: 1, irrigation_pumps: [], preview: true }),
  ];
  expect((await Promise.all(calls)).map((o) => o.kind)).toEqual(["ok", "error", "ok"]);
});
test("pagedQuery stops on an empty page even with a cursor", async () => {
  const op = vi.fn().mockResolvedValue({ api: 2, ok: true, data: { events: [], cursor: "still" } });
  const out = await pagedQuery(fakeController({ operator: op }), { room_id: "room:", since: "x" });
  expect(op).toHaveBeenCalledTimes(1);
  expect(out.kind === "ok" && out.data.events).toEqual([]);
});
test("useParity is idle, not loading, while there is nothing to ask", () => {
  let seen = "";
  const Probe = ({ data }: { data: Record<string, unknown> | null }) => {
    seen = useParity(fakeController({}), "supply_get", data, [1]).state;
    return null;
  };
  renderToStaticMarkup(createElement(Probe, { data: null }));
  expect(seen).toBe("idle");
  renderToStaticMarkup(createElement(Probe, { data: {} }));
  expect(seen).toBe("loading");
});
test("demo prime refuses more than 30 s the way the integration does", async () => {
  expect(await callV2(demoController("?demo=1"), "pump_prime", { pump: "a", seconds: 31 })).toMatchObject({ kind: "error", code: "invalid" });
  expect((await callV2(demoController("?demo=1"), "pump_prime", { pump: "a", seconds: 30 })).kind).toBe("ok");
});
test("demo 3.18 answers an existing service's refusal in the envelope, keeping stale_revision", async () => {
  expect(await callV2(demoController("?demo=1"), "display_save", { expected_revision: -1, options: {} })).toEqual({
    kind: "error", code: "stale_revision", message: "Display options changed elsewhere. Reload before saving.",
  });
});
test("the timer-mode zone is not a paused zone", async () => {
  const now = Date.now();
  const list = (await parityDemo("timer_program_list", {}, now, "3.18")) as { data: { programs: { room_id: string; zones: number[] }[] } };
  const since = new Date(now - 2 * 86_400_000).toISOString();
  for (const program of list.data.programs) {
    const page = (await parityDemo("journal_query", { room_id: program.room_id, since }, now, "3.18")) as { data: { events: CsEvent[] } };
    const paused = page.data.events.filter((e) => e.kind === "intent.held" && e.data.reason === "zone disabled");
    for (const zone of program.zones) expect(paused.some((e) => e.zone === zone)).toBe(false);
  }
});
test("journal fixture filters by kinds and pages by cursor", async () => {
  const now = Date.parse("2026-10-22T15:00:00+13:00");
  const ask = (data: Record<string, unknown>) => parityDemo("journal_query", data, now, "3.18") as Promise<{ data: { events: CsEvent[]; cursor: string | null } }>;
  const since = "2026-10-21T15:00:00+13:00";
  const all = (await ask({ room_id: "room:", since })).data.events;
  const kinds = new Set(all.map((e) => e.kind));
  for (const k of ["shot.started", "shot.completed", "flow.reconciled", "phase.changed", "intent.queued", "intent.held",
    "alert.raised", "alert.cleared", "target.changed", "config.changed", "calibration.committed", "ai.judgement",
    "ai.outcome"]) expect(kinds).toContain(k);
  // The room's last refill is older: the one its stock tanks read (stock-demo.ts).
  const refills = (await ask({ room_id: "room:", since: new Date(now - 10 * 86_400_000).toISOString(), kinds: ["stock.refilled"] })).data.events;
  expect(refills.map((e) => e.data.tank)).toEqual(["part_a"]);
  expect(all.every((e) => Date.parse(e.ts) <= now && e.room_id === "room:")).toBe(true);
  const shots = (await ask({ room_id: "room:", since, kinds: ["shot.completed"] })).data.events;
  expect(shots.length).toBeGreaterThan(5);
  expect(new Set(shots.map((e) => e.kind))).toEqual(new Set(["shot.completed"]));
  const first = (await ask({ room_id: "room:", since, kinds: ["shot.completed"], limit: 5 })).data;
  expect(first.events).toHaveLength(5);
  expect(first.cursor).toBeTruthy();
  const second = (await ask({ room_id: "room:", since, kinds: ["shot.completed"], limit: 5, cursor: first.cursor })).data;
  expect(second.events[0].id).toBe(shots[5].id);
  const zone2 = (await ask({ room_id: "room:", since, zones: [2], kinds: ["shot.completed"] })).data.events;
  expect(zone2.every((e) => e.zone === 2)).toBe(true);
  // Deterministic: the same instant gives the same ids.
  expect((await ask({ room_id: "room:", since })).data.events.map((e) => e.id)).toEqual(all.map((e) => e.id));
});

test("NeedsIntegration says which version and keeps the page working", () => {
  expect(PARITY_MIN_VERSION).toBe("3.18.0");
  const html = renderToStaticMarkup(createElement(NeedsIntegration, { feature: "Timer programs" }));
  expect(html).toContain("Needs integration 3.18");
  expect(html).toContain("Timer programs needs Crop Steering 3.18 or newer. Update the integration and the controller app together; the rest of this page keeps working.");
  const compact = renderToStaticMarkup(createElement(NeedsIntegration, { feature: "Timer programs", compact: true }));
  expect(compact).toContain("Needs integration 3.18");
  expect(compact).toContain('aria-label="About Needs integration 3.18"');
});
test("demo dashboard_create lists the dashboard it made; a room tablet takes one room", async () => {
  const c = demoController("?demo=1");
  const made = await callV2<{ url_path: string }>(c, "dashboard_create", { template: "room_tablet", rooms: ["room:"] });
  if (made.kind !== "ok") throw new Error("not ok");
  expect(made.data.url_path).toMatch(/^crop-steering-room_tablet-\d+$/);
  const list = await callV2<{ dashboards: { url_path: string; exists: boolean }[] }>(c, "dashboard_list", {});
  if (list.kind !== "ok") throw new Error("not ok");
  expect(list.data.dashboards).toContainEqual(expect.objectContaining({ url_path: made.data.url_path, exists: true }));
  const two = await callV2(c, "dashboard_create", { template: "room_tablet", rooms: ["room:", "room:room_b_"] });
  expect(two.kind === "error" && two.code).toBe("invalid");
});
