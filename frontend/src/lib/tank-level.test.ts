import { describe, expect, it } from "vitest";
import type { TimelineRow, TimelineRows } from "./day-timeline";
import { createDemo } from "./demo";
import { buildRoom, discoverRooms } from "./model";
import { dosingConfigId } from "./dosing";
import { tankLevelId } from "./reservoir";
import { rangeTicks } from "./tank-history";
import {
  DEFAULT_LEVEL_HOURS,
  LEVEL_RANGES,
  levelAt,
  levelLines,
  levelSteps,
  recordedFills,
  recordWindows,
  shotGap,
  shotMarks,
  tankEntities,
  tankRecord,
  type TankIds,
} from "./tank-level";
import { fillTime } from "./tank-telemetry";
import type { States } from "./types";

const HOUR = 3_600_000;
const T0 = Date.parse("2026-10-03T00:00:00Z");
const at = (hours: number) => T0 + hours * HOUR;
const row = (state: string, hours: number, attributes?: Record<string, unknown>): TimelineRow => ({
  state,
  time: at(hours),
  ...(attributes ? { attributes } : {}),
});
const roomOf = (states: States, prefix = "") =>
  buildRoom(
    states,
    discoverRooms(states).find((item) => item.prefix === prefix)!,
  );

describe("what the tank chart reads", () => {
  const states = createDemo(Date.parse("2026-09-28T04:00:00Z"));
  it("reads the room's mapped tank and pump, its valves and its decision, no other room's", () => {
    const read = tankEntities(roomOf(states), states);
    expect(read.ids).toEqual({
      level: "sensor.demo_tank_level",
      pump: "switch.demo_pump",
      filling: "binary_sensor.demo_tank_filling",
      fill: "sensor.demo_tank_last_fill",
      decision: "sensor.crop_steering_current_decision",
      valves: [1, 2, 3].map((zone) => ({ zone, entityId: `switch.demo_valve_${zone}` })),
    });
    // The last-fill record and the decision with their attributes, the rest as bare states.
    expect(read.attributeIds).toEqual([
      "sensor.crop_steering_current_decision",
      "sensor.demo_tank_last_fill",
    ]);
    expect(read.entityIds).toEqual([
      "binary_sensor.demo_tank_filling",
      "sensor.demo_tank_level",
      "switch.demo_pump",
      "switch.demo_valve_1",
      "switch.demo_valve_2",
      "switch.demo_valve_3",
    ]);
    expect(tankEntities(roomOf(states, "room_b_"), states).ids).toMatchObject({
      level: "sensor.demo_room_b_tank_level",
      pump: "switch.demo_room_b_pump",
    });
  });
  it("leaves out what is not mapped, or that Home Assistant does not have", () => {
    const bare = structuredClone(states);
    const mapped = bare["sensor.crop_steering_engine_config"].attributes;
    delete mapped.water_level_sensor;
    mapped.pump = "";
    mapped.tank_fill_entity = "binary_sensor.not_in_home_assistant";
    delete bare["sensor.crop_steering_current_decision"];
    const read = tankEntities(roomOf(bare), bare);
    expect(read.ids).toMatchObject({
      level: null,
      pump: null,
      filling: null,
      decision: null,
      fill: "sensor.demo_tank_last_fill",
    });
    expect(read.entityIds).toEqual([
      "switch.demo_valve_1",
      "switch.demo_valve_2",
      "switch.demo_valve_3",
    ]);
    expect(read.attributeIds).toEqual(["sensor.demo_tank_last_fill"]);
  });
});

describe("the requests a range is read in", () => {
  const local = (day: number, hour: number) => new Date(2026, 9, day, hour).getTime();
  const now = local(3, 16);
  it("is whole grow-days, from the one the range starts in up to now", () => {
    expect(recordWindows(10, 22, 24, now)).toEqual([
      { start: local(2, 10), end: local(3, 10) },
      { start: local(3, 10), end: now },
    ]);
    for (const hours of [72, 168]) {
      const windows = recordWindows(10, 22, hours, now);
      expect(windows[0].start).toBeLessThanOrEqual(now - hours * HOUR);
      expect(windows[0].end).toBeGreaterThan(now - hours * HOUR);
      expect(windows.at(-1)!.end).toBe(now);
      windows.slice(1).forEach((window, index) => expect(window.start).toBe(windows[index].end));
      // The day timeline reads at most one grow-day a request.
      expect(windows.every((window) => window.end - window.start <= 26 * HOUR)).toBe(true);
    }
    expect(recordWindows(10, 22, 168, now)).toHaveLength(8);
  });
  it("offers 12 h, 24 h, 3 days and 7 days, opening on 24 h", () => {
    expect(LEVEL_RANGES.map((range) => range.hours)).toEqual([12, 24, 72, 168]);
    expect(DEFAULT_LEVEL_HOURS).toBe(24);
    // Half a day reads only the grow-days it reaches into.
    expect(recordWindows(10, 22, 12, now)).toEqual([
      { start: local(2, 10), end: local(3, 10) },
      { start: local(3, 10), end: now },
    ]);
    expect(recordWindows(10, 22, 4, now)).toEqual([{ start: local(3, 10), end: now }]);
  });
  it("marks half a day every three hours", () => {
    expect(rangeTicks(local(3, 4), local(3, 16), 12)).toEqual(
      [6, 9, 12, 15].map((hour) => local(3, hour)),
    );
  });
  it("is calendar days without a lights schedule", () => {
    expect(recordWindows(null, 22, 24, now)).toEqual([
      { start: local(2, 0), end: local(3, 0) },
      { start: local(3, 0), end: now },
    ]);
  });
});

describe("the level as steps", () => {
  it("holds each reading until the next, from the one in force when the range opens", () => {
    const rows = [row("80", -5), row("78", 1), row("75.5", 2)];
    expect(levelSteps(rows, at(0), at(3))).toEqual([
      { value: 80, start: at(0), end: at(1) },
      { value: 78, start: at(1), end: at(2) },
      { value: 75.5, start: at(2), end: at(3) },
    ]);
    expect(levelSteps([], at(0), at(3))).toEqual([]);
    expect(levelSteps(undefined, at(0), at(3))).toEqual([]);
  });
  it("leaves a gap where there was no reading, or one that cannot be a level", () => {
    const rows = [
      row("60", 0),
      row("unavailable", 1),
      row("58", 2),
      row("140", 3),
      row("-2", 4),
      row("57", 5),
    ];
    const hours = (time: number) => (time - T0) / HOUR;
    expect(
      levelSteps(rows, at(0), at(6)).map((step) => [
        step.value,
        hours(step.start),
        hours(step.end),
      ]),
    ).toEqual([
      [60, 0, 1],
      [58, 2, 3],
      [57, 5, 6],
    ]);
  });
  it("leaves out the passing value Home Assistant records while it restarts", () => {
    // As recorded live: 41 % through a restart that read 100 for 0.4 s, then a fill to 99 %.
    const second = 1 / 3600;
    const rows = [
      row("41", 0),
      row("100", 1),
      row("41", 1 + 0.4 * second),
      row("0", 2),
      row("99", 3),
    ];
    expect(levelSteps(rows, at(0), at(4)).map((step) => step.value)).toEqual([41, 0, 99]);
    // A sensor reporting every second keeps every reading.
    const fast = [row("50", 0), row("48", second), row("46", 2 * second), row("44", 3 * second)];
    expect(levelSteps(fast, at(0), at(1)).map((step) => step.value)).toEqual([50, 48, 46, 44]);
  });
  it("reads the level in force at a time: the new one on a change, none in a gap", () => {
    const steps = levelSteps([row("80", 0), row("70", 1), row("unknown", 2)], at(0), at(3));
    expect(levelAt(steps, at(0.5))).toBe(80);
    expect(levelAt(steps, at(1))).toBe(70);
    expect(levelAt(steps, at(2.5))).toBeNull();
    expect(levelAt([], at(1))).toBeNull();
  });
});

describe("recorded fills", () => {
  const helper = (hours: number) => ({
    has_date: true,
    has_time: true,
    timestamp: at(hours) / 1000,
  });
  it("counts a newer time on the record, not a restart recording it again or a time moved back", () => {
    const id = "input_datetime.tank_filled_at";
    const rows = [
      row("2026-10-02 20:00:00", 0, helper(-4)), // in force as the range opens: an older fill
      row("2026-10-03 06:00:00", 6, helper(6)),
      row("2026-10-03 06:00:00", 9, helper(6)), // a restart records it again
      row("2026-10-03 05:00:00", 10, helper(5)), // moved back by hand
      row("unavailable", 11),
      row("2026-10-03 18:00:00", 18, helper(18)),
    ];
    expect(recordedFills(rows, id, at(0), at(24))).toEqual([at(6), at(18)]);
    expect(recordedFills(rows, id, at(12), at(24))).toEqual([at(18)]);
    expect(recordedFills([], id, at(0), at(24))).toEqual([]);
  });
  it("reads a timestamp sensor's dated state, and nothing from a time without a zone", () => {
    const rows = [
      row("2026-10-03T06:00:00+13:00", 0),
      row("2026-10-03 07:00:00", 1),
      row("2026-10-03T08:00:00Z", 2),
    ];
    expect(recordedFills(rows, "sensor.tank_last_fill", at(-24), at(24))).toEqual([
      Date.parse("2026-10-03T06:00:00+13:00"),
      Date.parse("2026-10-03T08:00:00Z"),
    ]);
  });
  it("reads a fill time as the tank card does", () => {
    const stamp = 1_790_000_000;
    const both = { has_date: true, has_time: true, timestamp: stamp };
    expect(fillTime("input_datetime.x", "2026-09-22 01:33:20", both)).toBe(stamp * 1000);
    expect(fillTime("input_datetime.x", "2026-09-22", { ...both, has_time: false })).toBeNull();
    expect(fillTime("input_datetime.x", "unknown", both)).toBeNull();
    expect(fillTime("input_datetime.x", "x", { ...both, timestamp: 1e20 })).toBeNull();
    expect(fillTime("sensor.x", "2026-10-03 06:00:00")).toBeNull();
    expect(fillTime("sensor.x", "2026-10-03T06:00:00Z")).toBe(Date.parse("2026-10-03T06:00:00Z"));
  });
});

describe("a range of the tank's record", () => {
  const ids: TankIds = {
    level: "sensor.tank_level",
    pump: "switch.pump",
    filling: "switch.fill_valve",
    fill: "input_datetime.tank_filled_at",
    decision: "sensor.crop_steering_current_decision",
    valves: [
      { zone: 1, entityId: "switch.valve_1" },
      { zone: 2, entityId: "switch.valve_2" },
    ],
  };
  const helper = (hours: number) => ({
    has_date: true,
    has_time: true,
    timestamp: at(hours) / 1000,
  });
  // Three days, each: filling from 05:30, the fill recorded at 06:00, then zone 1 and zone 2
  // watered one after the other at 08:00 with the pump running through both.
  const rows: TimelineRows = {};
  const add = (id: string, list: TimelineRow[]) => (rows[id] = [...(rows[id] ?? []), ...list]);
  add(ids.fill!, [row("2026-10-02 06:00:00", 0, helper(-18))]);
  add(ids.decision!, [row("Holding — all zones in band", 0, { fired: [], blocked: [] })]);
  for (const day of [0, 24, 48]) {
    add(ids.filling!, [row("on", day + 5.5), row("off", day + 6)]);
    add(ids.fill!, [row("filled", day + 6, helper(day + 6))]);
    add(ids.level!, [row("30", day), row("95", day + 6), row("90", day + 8.15)]);
    add(ids.pump!, [row("on", day + 7.99), row("off", day + 8.15)]);
    add("switch.valve_1", [row("on", day + 8), row("off", day + 8.05)]);
    add("switch.valve_2", [row("on", day + 8.08), row("off", day + 8.13)]);
    add(ids.decision!, [
      row("Z1 P2 top-up", day + 8.06, { fired: ["Z1 P2 top-up"], blocked: [] }),
      row("Z2 P2 top-up", day + 8.14, { fired: ["Z2 P2 top-up"], blocked: [] }),
    ]);
  }
  for (const list of Object.values(rows)) list.sort((a, b) => a.time - b.time);
  it("keeps the range: the last day, or all three", () => {
    const day = tankRecord(rows, ids, at(48), at(72));
    expect(day.fills).toEqual([at(54)]);
    expect(day.filling).toEqual([{ start: at(53.5), end: at(54), open: false }]);
    expect(day.pump).toEqual([{ start: at(55.99), end: at(56.15), open: false }]);
    expect(day.shots.map((shot) => [shot.zone, shot.phase, shot.reason])).toEqual([
      [1, "P2", "top-up"],
      [2, "P2", "top-up"],
    ]);
    // The level in force as the range opens is the first step.
    expect(day.level[0]).toEqual({ value: 30, start: at(48), end: at(54) });
    const all = tankRecord(rows, ids, at(0), at(72));
    expect(all.fills).toEqual([at(6), at(30), at(54)]);
    expect(all.shots).toHaveLength(6);
    expect(all.pump).toHaveLength(3);
    expect(all.filling).toHaveLength(3);
  });
  it("puts each shot on the level line where it opened, close ones on one mark", () => {
    const record = tankRecord(rows, ids, at(48), at(72));
    const [mark, ...rest] = shotMarks(record.shots, record.level, HOUR / 2);
    expect(rest).toEqual([]);
    expect(mark.shots.map((shot) => shot.zone)).toEqual([1, 2]);
    // Zone 1 opened after the morning's fill, at 95 %.
    expect(mark).toMatchObject({ time: at(56), level: 95 });
    expect(shotMarks(record.shots, record.level, 60_000)).toHaveLength(2);
    // With no level recorded, a shot sits on none.
    expect(shotMarks(record.shots, [], 60_000).map((each) => each.level)).toEqual([null, null]);
  });
  it("lines each marker up with the history event it stands for, over half a day", () => {
    const record = tankRecord(rows, ids, at(50), at(62));
    // The valve opening times, the pump's and the filling's own on and off, the fill's time.
    expect(record.shots.map((shot) => [shot.zone, shot.start, shot.end])).toEqual([
      [1, at(56), at(56.05)],
      [2, at(56.08), at(56.13)],
    ]);
    expect(record.pump).toEqual([{ start: at(55.99), end: at(56.15), open: false }]);
    expect(record.filling).toEqual([{ start: at(53.5), end: at(54), open: false }]);
    expect(record.fills).toEqual([at(54)]);
    expect(record.level).toEqual([
      { value: 30, start: at(50), end: at(54) },
      { value: 95, start: at(54), end: at(56.15) },
      { value: 90, start: at(56.15), end: at(62) },
    ]);
    // Each shot's mark sits where its valve opened, on the level then in force.
    expect(shotMarks(record.shots, record.level, 60_000)).toMatchObject([
      { time: at(56), level: 95 },
      { time: at(56.08), level: 95 },
    ]);
    // Half a day with nothing in it keeps only the level carried in.
    expect(tankRecord(rows, ids, at(60), at(72))).toEqual({
      level: [{ value: 90, start: at(60), end: at(72) }],
      shots: [],
      pump: [],
      filling: [],
      fills: [],
    });
  });
  it("groups a week's shots by the hour, and nearer ranges only as close as the chart can tell", () => {
    expect(shotGap(168, 60_000)).toBe(HOUR);
    expect(shotGap(168, 2 * HOUR)).toBe(2 * HOUR);
    expect(shotGap(72, 60_000)).toBe(60_000);
    expect(shotGap(12, 60_000)).toBe(60_000);
    const week = tankRecord(rows, ids, at(0), at(72));
    const marks = shotMarks(week.shots, week.level, shotGap(168, 60_000));
    expect(marks.map((mark) => [mark.time, mark.shots.length])).toEqual([
      [at(8), 2],
      [at(32), 2],
      [at(56), 2],
    ]);
  });
  it("draws nothing it has no record or mapping for, without failing", () => {
    const empty = { level: [], shots: [], pump: [], filling: [], fills: [] };
    expect(tankRecord({}, ids, at(0), at(72))).toEqual(empty);
    const unmapped: TankIds = {
      level: null,
      pump: null,
      filling: null,
      fill: null,
      decision: null,
      valves: [],
    };
    expect(tankRecord(rows, unmapped, at(0), at(72))).toEqual(empty);
    // A valve without the controller's decision still has its shots, unnamed.
    const shots = tankRecord(rows, { ...ids, decision: null }, at(48), at(72)).shots;
    expect(shots.map((shot) => [shot.zone, shot.phase])).toEqual([
      [1, null],
      [2, null],
    ]);
  });
});

describe("the minimum and refill reminder lines", () => {
  const states = createDemo(Date.parse("2026-09-28T04:00:00Z"));
  it("draws the controller's minimum in a room whose tank level it reads", () => {
    expect(levelLines(states, "", "sensor.demo_tank_level")).toEqual([
      expect.objectContaining({ key: "minimum", value: 8, label: "Minimum 8 %" }),
    ]);
    // With no minimum published, the controller's own 8 %.
    const bare = structuredClone(states);
    delete bare[tankLevelId("")].attributes.minimum_pct;
    expect(levelLines(bare, "", null).map((line) => line.value)).toEqual([8]);
  });
  it("draws the refill reminder where the dosing setup reads it on the level charted", () => {
    // Flower 1: no level for the controller's minimum, a person reminded to refill at 20 %.
    expect(levelLines(states, "f1_", "sensor.demo_f1_tank_level")).toEqual([
      expect.objectContaining({ key: "remind", value: 20, label: "Refill reminder 20 %" }),
    ]);
    // Read on another entity, or switched off, the reminder is not this line.
    expect(levelLines(states, "f1_", "sensor.another_level")).toEqual([]);
    const off = structuredClone(states);
    (off[dosingConfigId("f1_")].attributes.batch as Record<string, unknown>).remind_pct = 0;
    expect(levelLines(off, "f1_", "sensor.demo_f1_tank_level")).toEqual([]);
  });
  it("draws neither in a room with nothing set, nor from a dosing setup from before them", () => {
    expect(levelLines({}, "", "sensor.tank_level")).toEqual([]);
    const old: States = {
      [dosingConfigId("")]: {
        entity_id: dosingConfigId(""),
        state: "1",
        attributes: { batch: { fill_valve: null, recipe: [] } },
      },
    };
    expect(levelLines(old, "", "sensor.tank_level")).toEqual([]);
  });
});
