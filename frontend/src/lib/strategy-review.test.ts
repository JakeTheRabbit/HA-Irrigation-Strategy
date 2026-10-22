import { describe, expect, test, vi } from "vitest";
import { buildPlanningCurve, projectDay } from "./planning-curve";
import type { SetpointCurveState } from "./setpoint-preview";
import {
  afternoon,
  appliedEventIds,
  estimatedIntents,
  growDayWindow,
  readProjection,
  targetRows,
  undoApply,
  type LastApply,
  type ProjectionIntent,
} from "./strategy-review";
import { fakeController } from "./test-helpers";
import type { Drafts } from "@/pages/strategy";
import type { States } from "./types";

const NZ = "Pacific/Auckland";
const REWATER = "number.crop_steering_zone_1_p2_vwc_threshold";
const PEAK = "number.crop_steering_zone_1_p1_target_vwc";
const REWATER_2 = "number.crop_steering_zone_2_p2_vwc_threshold";
const MODE = "select.crop_steering_zone_1_steering_mode";
const number = (id: string, state: string, unit = "%", step = 0.5) => ({
  entity_id: id,
  state,
  attributes: { unit_of_measurement: unit, step, min: 0, max: 100 },
});
const STATES: States = {
  [REWATER]: number(REWATER, "57"),
  [PEAK]: number(PEAK, "63"),
  [REWATER_2]: number(REWATER_2, "57"),
  [MODE]: {
    entity_id: MODE,
    state: "Vegetative",
    attributes: { options: ["Vegetative", "Generative"] },
  },
};
const draft = (value: string, original: number | string, zone = "Zone 1", label = "x") => ({
  value,
  original,
  label,
  zone,
});

describe("targetRows", () => {
  test("targetRows lists only changed keys with signed delta note", () => {
    const drafts: Drafts = {
      [REWATER]: draft("56", 57),
      // Back where the controller holds it: not a change.
      [PEAK]: draft("63", 62),
      [REWATER_2]: draft("58.5", 57, "Zone 2"),
      [MODE]: draft("Generative", "Vegetative"),
    };
    const remove = vi.fn();
    const rows = targetRows(drafts, STATES, 1, remove);
    expect(rows.map((r) => r.id)).toEqual([REWATER, REWATER_2, MODE]);
    expect(rows[0]).toMatchObject({
      label: "Re-water point",
      before: "57%",
      after: "56%",
      note: "-1.0 pts · P2 waters when VWC falls to this",
    });
    // Another zone's draft names its zone.
    expect(rows[1]).toMatchObject({
      label: "Zone 2 · Re-water point",
      before: "57%",
      after: "58.5%",
    });
    expect(rows[1].note).toMatch(/^\+1\.5 pts · /);
    expect(rows[2]).toMatchObject({ before: "Vegetative", after: "Generative" });
    rows[0].undo();
    expect(remove).toHaveBeenCalledWith(REWATER);
  });
});

/** Room A's day: lights 10:00–22:00 NZ on 22 Oct. */
const ON = Date.parse("2026-10-22T10:00:00+13:00");
const at = (h: number, m = 0) => ON + ((h - 10) * 60 + m) * 60_000;
const iso = (ms: number) => new Date(ms).toISOString();
const PARAMS = {
  p1_target_vwc: 66,
  p2_vwc_threshold: 60,
  p2_shot_size: 4,
  p1_initial_shot_size: 3,
  p1_shot_size_increment: 0.5,
  p1_maximum_shots: 6,
  p1_time_between_shots: 15,
  p0_maximum_wait_time: 60,
  p3_emergency_vwc_threshold: 45,
  p3_emergency_shot_size: 3,
  dryback_target: 15,
  substrate_volume: 6,
  dripper_flow_rate: 4,
  drippers_per_plant: 1,
};
const EDITED: SetpointCurveState = {
  parameters: { ...PARAMS, p2_vwc_threshold: 58 },
  lightsOn: 10,
  lightsOff: 22,
  mode: "Vegetative",
};

describe("afternoon", () => {
  const intent = (ms: number, zone = 1): ProjectionIntent => ({
    zone,
    at: iso(ms),
    duration_s: 216,
    source: "engine",
    expected: true,
  });
  const SAVED_STATE: SetpointCurveState = { ...EDITED, parameters: PARAMS };
  const shotsIn = (state: SetpointCurveState) =>
    projectDay(buildPlanningCurve(state.parameters, 10, 22), state.parameters)!.shots.filter(
      (s) => s.hour >= 4 + 10 / 60 && s.hour < 12,
    );
  test("afternoon counts saved projection shots and edited preview shots in the window", () => {
    // projection_app: one before the window, two in it, one after lights-off.
    const saved = [intent(at(13)), intent(at(14, 30)), intent(at(16)), intent(at(22, 30))];
    // Smaller maintenance shots: more of them.
    const raised: SetpointCurveState = { ...EDITED, parameters: { ...PARAMS, p2_shot_size: 2 } };
    const result = afternoon(saved, raised, at(14, 10), at(22), {
      lightsOnAt: ON,
      baseline: SAVED_STATE,
    });
    expect(result.saved.shots).toBe(2);
    // 216 s on one 4 L/h dripper (a 4% shot of a 6 L pot), twice.
    expect(result.saved.lPerPlant).toBeCloseTo(2 * (216 / 3600) * 4, 6);
    // With edits is Saved plus only what the edit changes in the projection.
    const edited = shotsIn(raised),
      baseline = shotsIn(SAVED_STATE);
    expect(edited.length).toBeGreaterThan(baseline.length);
    expect(result.edited.shots).toBe(2 + edited.length - baseline.length);
    // Afternoon shots are maintenance shots of a 6 L pot: 2% edited, 4% saved.
    expect(result.edited.lPerPlant).toBeCloseTo(
      2 * (216 / 3600) * 4 + edited.length * 0.02 * 6 - baseline.length * 0.04 * 6,
      6,
    );
    // Fewer shots than the plan has never reads below none.
    const lowered = afternoon(saved, EDITED, at(14, 10), at(22), {
      lightsOnAt: ON,
      baseline: SAVED_STATE,
    });
    expect(lowered.edited.shots).toBeGreaterThanOrEqual(0);
    expect(lowered.edited.lPerPlant).toBeGreaterThanOrEqual(0);
  });
  test("with no edit, With edits is exactly Saved, whatever the projection says", () => {
    const saved = [intent(at(14, 30)), intent(at(16))];
    const result = afternoon(saved, SAVED_STATE, at(14, 10), at(22), {
      lightsOnAt: ON,
      baseline: SAVED_STATE,
    });
    expect(result.edited).toEqual(result.saved);
  });
  test("the saved estimate is the same day's projection, sized by the zone's drippers", () => {
    const intents = estimatedIntents(SAVED_STATE, 1, ON);
    const result = afternoon(intents, SAVED_STATE, at(14, 10), at(22), {
      lightsOnAt: ON,
      baseline: SAVED_STATE,
    });
    expect(result.saved.shots).toBe(shotsIn(SAVED_STATE).length);
    expect(result.saved.lPerPlant).toBeCloseTo(shotsIn(SAVED_STATE).length * 0.04 * 6, 6);
  });
  test("without sizing the litres are unknown, not invented", () => {
    const bare: SetpointCurveState = {
      ...EDITED,
      parameters: { ...EDITED.parameters, dripper_flow_rate: NaN },
    };
    const result = afternoon(
      [{ zone: 1, at: iso(at(15)), duration_s: 30, source: "timer", expected: false }],
      bare,
      at(14),
      at(22),
      { lightsOnAt: ON, baseline: bare },
    );
    expect(result.saved.shots).toBe(1);
    expect(result.saved.lPerPlant).toBeNaN();
  });
  test("reads projection_app for one zone, and nothing when it is absent or unavailable", () => {
    const id = "sensor.crop_steering_projection_app";
    const intents = [
      { zone: 1, at: iso(at(15)), duration_s: 30, source: "engine", expected: true },
      { zone: 2, at: iso(at(15)), duration_s: 30, source: "timer", expected: false },
    ];
    expect(
      readProjection({ [id]: { entity_id: id, state: "2", attributes: { intents } } }, "", 1),
    ).toHaveLength(1);
    expect(
      readProjection(
        { [id]: { entity_id: id, state: "unavailable", attributes: { intents } } },
        "",
        1,
      ),
    ).toBeNull();
    expect(readProjection({}, "", 1)).toBeNull();
  });
});

describe("growDayWindow", () => {
  test("from now to lights-off while the lights are on", () => {
    expect(growDayWindow(at(14, 10), 10, 22, NZ)).toEqual({
      from: at(14, 10),
      to: at(22),
      lightsOnAt: ON,
      ahead: false,
    });
  });
  test("the next lights-on window while they are off", () => {
    const next = growDayWindow(at(23), 10, 22, NZ)!;
    expect(next.ahead).toBe(true);
    expect(next.from).toBe(next.lightsOnAt);
    expect(next.to - next.from).toBe(12 * 3_600_000);
    expect(next.from).toBe(ON + 24 * 3_600_000);
  });
  test("lights on overnight: the window that started yesterday", () => {
    const morning = growDayWindow(Date.parse("2026-10-22T02:00:00+13:00"), 20, 8, NZ)!;
    expect(morning).toMatchObject({
      ahead: false,
      to: Date.parse("2026-10-22T08:00:00+13:00"),
      lightsOnAt: Date.parse("2026-10-21T20:00:00+13:00"),
    });
  });
});

describe("apply and undo", () => {
  const changeOf = (entityId: string, value: number) => ({ entityId, value });
  const change = (over: Record<string, unknown>) => ({
    id: "01B",
    kind: "setpoint",
    key: "p2_vwc_threshold",
    scope: "zone:1",
    ts: iso(at(14, 2)),
    actor: "manual",
    old: 57,
    new: 56,
    ...over,
  });
  const answer = (changes: unknown[]) => ({
    api: 2,
    ok: true,
    data: { changes },
    readback: { status: "verified" },
    event_ids: [],
  });
  test("finds the base target.changed events the apply journalled", async () => {
    const since = at(14);
    const operator = vi.fn(async (_action: string, _data?: Record<string, unknown>) =>
      answer([
        // Newest first. A learner's or the AI's same value in the window is not this apply's...
        change({ id: "01F", actor: "learner" }),
        change({ id: "01G", actor: "brain" }),
        // ...nor is a put-back, one from another value, before the apply, or of another zone.
        change({ id: "01H", detail: "put back" }),
        change({ id: "01E", old: 58 }),
        change({ id: "01D", new: 55 }),
        change({ id: "01C", scope: "zone:2" }),
        change({ id: "01B" }),
        change({ id: "01A", ts: iso(at(13)) }),
      ]),
    );
    const found = await appliedEventIds(
      fakeController({ operator }),
      "room:",
      "",
      [changeOf(REWATER, 56)],
      [changeOf(REWATER, 57)],
      since,
    );
    expect(found).toEqual({ backend: "3.18", ids: ["01B"] });
    const [action, data] = operator.mock.calls[0];
    expect(action).toBe("history_changes");
    expect(data).toMatchObject({
      room_id: "room:",
      since: iso(since),
      zone: 1,
      key: "p2_vwc_threshold",
      kinds: ["setpoint"],
    });
    expect(data).not.toHaveProperty("client");
    expect(data).not.toHaveProperty("proposal_token");
  });
  test("a learner's same-value write alone is never taken for this apply", async () => {
    const operator = vi.fn(async () => answer([change({ id: "01F", actor: "learner" })]));
    const found = await appliedEventIds(
      fakeController({ operator }),
      "room:",
      "",
      [changeOf(REWATER, 56)],
      [changeOf(REWATER, 57)],
      at(14),
    );
    expect(found).toEqual({ backend: "3.18", ids: [] });
  });
  test("a room-wide target asks without a zone", async () => {
    const PEAK_ROOM = "number.crop_steering_p1_target_vwc";
    const operator = vi.fn(async (_action: string, _data?: Record<string, unknown>) =>
      answer([change({ id: "01R", key: "p1_target_vwc", scope: "room", old: 62, new: 63 })]),
    );
    const found = await appliedEventIds(
      fakeController({ operator }),
      "room:",
      "",
      [changeOf(PEAK_ROOM, 63)],
      [changeOf(PEAK_ROOM, 62)],
      at(14),
    );
    expect(found.ids).toEqual(["01R"]);
    expect(operator.mock.calls[0][1]).not.toHaveProperty("zone");
  });
  test("a 3.17 integration has no Journal to look in", async () => {
    const operator = vi.fn(async () => {
      throw new Error("Action crop_steering.history_changes not found");
    });
    expect(
      await appliedEventIds(
        fakeController({ operator }),
        "room:",
        "",
        [changeOf(REWATER, 56)],
        [changeOf(REWATER, 57)],
        at(14),
      ),
    ).toEqual({ backend: "3.17", ids: [] });
  });

  const last17: LastApply = {
    at: at(14, 2),
    backend: "3.17",
    eventIds: [],
    before: [changeOf(REWATER, 57)],
    after: [changeOf(REWATER, 56)],
  };
  test("undo of last apply restores before values on 3.17", async () => {
    const applyChanges = vi.fn(async () => ({ applied: [REWATER], failed: [] }));
    const states = { ...STATES, [REWATER]: number(REWATER, "56") };
    await undoApply(last17, { controller: fakeController({}), states, write: applyChanges });
    expect(applyChanges).toHaveBeenCalledWith([changeOf(REWATER, 57)]);
  });
  test("undo on 3.17 refuses a value that moved since the apply, and writes nothing", async () => {
    const applyChanges = vi.fn(async () => ({ applied: [REWATER], failed: [] }));
    const states = { ...STATES, [REWATER]: number(REWATER, "55") };
    await expect(
      undoApply(last17, { controller: fakeController({}), states, write: applyChanges }),
    ).rejects.toThrow("This value has changed since you applied it. Nothing was undone.");
    expect(applyChanges).not.toHaveBeenCalled();
  });
  test("undo on 3.17 refuses a previous value that was not a number, and writes nothing", async () => {
    const write = vi.fn();
    const states = { ...STATES, [REWATER]: number(REWATER, "56") };
    await expect(
      undoApply(
        { ...last17, before: [changeOf(REWATER, NaN)] },
        { controller: fakeController({}), states, write },
      ),
    ).rejects.toThrow("The previous value is not known. Nothing was undone.");
    expect(write).not.toHaveBeenCalled();
  });
  test("undo on 3.17 within the entity's step is not stale", async () => {
    const applyChanges = vi.fn(async () => ({ applied: [REWATER], failed: [] }));
    const states = { ...STATES, [REWATER]: number(REWATER, "56.2") };
    await undoApply(last17, { controller: fakeController({}), states, write: applyChanges });
    expect(applyChanges).toHaveBeenCalledOnce();
  });
  test("undo on 3.17 that the controller refuses part way says how many went back", async () => {
    const both: LastApply = {
      ...last17,
      before: [changeOf(REWATER, 57), changeOf(PEAK, 62)],
      after: [changeOf(REWATER, 56), changeOf(PEAK, 63)],
    };
    const write = vi.fn(async () => ({
      applied: [REWATER],
      failed: [{ entityId: PEAK, reason: "Readback did not confirm" }],
    }));
    const states = { ...STATES, [REWATER]: number(REWATER, "56") };
    await expect(
      undoApply(both, { controller: fakeController({}), states, write }),
    ).rejects.toMatchObject({
      message: "1 of 2 put back: Readback did not confirm",
      reverted: 1,
    });
  });
  test("undo on 3.18 reverts the base events, and shows a refusal as it is", async () => {
    const last: LastApply = { ...last17, backend: "3.18", eventIds: ["01B"] };
    const operator = vi.fn(async () => ({
      api: 2,
      ok: true,
      data: {},
      readback: { status: "verified" },
      event_ids: [],
    }));
    const write = vi.fn();
    await undoApply(last, { controller: fakeController({ operator }), states: STATES, write });
    expect(operator).toHaveBeenCalledWith("history_revert", { event_id: "01B", api: 2 });
    expect(write).not.toHaveBeenCalled();
    const refuse = vi.fn(async () => ({
      api: 2,
      ok: false,
      error: { code: "invalid", message: "Keep or undo the AI change first" },
    }));
    await expect(
      undoApply(last, { controller: fakeController({ operator: refuse }), states: STATES, write }),
    ).rejects.toThrow("Keep or undo the AI change first");
    expect(write).not.toHaveBeenCalled();
  });
  test("undo on 3.18 without the change's record refuses, and never re-writes", async () => {
    const last: LastApply = { ...last17, backend: "3.18", eventIds: [] };
    const write = vi.fn();
    await expect(
      undoApply(last, { controller: fakeController({}), states: STATES, write }),
    ).rejects.toThrow(
      "The controller has no record of this change to put back. Nothing was undone.",
    );
    expect(write).not.toHaveBeenCalled();
  });
});
