import { describe, expect, it } from "vitest";
import type { RunRecord } from "./comparison-types";
import { createDemo } from "./demo";
import {
  alignGrid,
  alignToCurrent,
  chunks,
  DEFAULT_CHOICE,
  drybackMarkers,
  explorerSensors,
  pickRuns,
  previousWindow,
  readChoice,
  resolveRange,
  runDayAt,
  runDayStart,
  SeriesGrid,
  stepFor,
  writeChoice,
} from "./history-explorer";
import { buildRoom, discoverRooms } from "./model";

const MIN = 60_000,
  HOUR = 60 * MIN,
  DAY = 24 * HOUR;
const run = (over: Partial<RunRecord>): RunRecord => ({
  id: "r",
  room_id: "room",
  name: "Run",
  start_date: "2026-09-14",
  end_date: null,
  time_zone: "UTC",
  archived: false,
  captured_at: "2026-09-14T00:00:00Z",
  reference_source: "test",
  lights: { on: 10, off: 22 },
  zones: [],
  ...over,
});

describe("day of run", () => {
  const current = run({ name: "Now" });
  it("starts each grow day at lights-on, not at midnight", () => {
    expect(runDayStart(current, 1)).toBe(Date.parse("2026-09-14T10:00:00Z"));
    expect(runDayAt(current, Date.parse("2026-09-14T10:00:00Z"))).toBe(1);
    expect(runDayAt(current, Date.parse("2026-09-15T04:00:00Z"))).toBe(1.75);
    expect(runDayAt(current, Date.parse("2026-09-21T16:00:00Z"))).toBe(8.25);
    // Before the first lights-on of the run.
    expect(runDayAt(current, Date.parse("2026-09-14T04:00:00Z"))).toBe(0.75);
  });
  it("reads a run with no lights hours from midnight", () => {
    const dark = run({ lights: { on: null, off: null } });
    expect(runDayAt(dark, Date.parse("2026-09-15T12:00:00Z"))).toBe(2.5);
  });
  it("follows the run's own time zone across a clock change", () => {
    const sydney = run({ start_date: "2026-10-01", time_zone: "Australia/Sydney" });
    // Clocks go forward early on 4 Oct 2026: grow day 3, lights-on 3 Oct to 4 Oct, is 23 hours.
    const third = runDayStart(sydney, 3),
      fourth = runDayStart(sydney, 4);
    expect(fourth - third).toBe(23 * HOUR);
    expect(runDayStart(sydney, 5) - fourth).toBe(24 * HOUR);
    expect(runDayAt(sydney, third + 11.5 * HOUR)).toBeCloseTo(3.5, 10);
  });
  it("puts day N of the previous run on day N of this one, at the same part of the day", () => {
    // The previous run kept the lights on from 06:00: its day 8 starts at 06:00, this run's at 10:00.
    const previous = run({ start_date: "2026-06-08", lights: { on: 6, off: 18 } });
    const prevDay8 = Date.parse("2026-06-15T06:00:00Z");
    expect(alignToCurrent(current, previous, prevDay8)).toBe(Date.parse("2026-09-21T10:00:00Z"));
    expect(alignToCurrent(current, previous, prevDay8 + 6 * HOUR)).toBe(
      Date.parse("2026-09-21T16:00:00Z"),
    );
  });
  it("finds the previous run's span for the same grow days", () => {
    const previous = run({ start_date: "2026-06-08", end_date: "2026-08-02" });
    const now = Date.parse("2026-09-28T16:00:00Z");
    const window = previousWindow(current, previous, now - 7 * DAY, now, now)!;
    expect(window).toEqual({
      start: Date.parse("2026-06-15T16:00:00Z"),
      end: Date.parse("2026-06-22T16:00:00Z"),
      firstDay: 8,
      lastDay: 15,
    });
  });
  it("stops at the end of a short previous run, and has nothing before it began", () => {
    const short = run({ start_date: "2026-06-08", end_date: "2026-06-17" });
    const now = Date.parse("2026-09-28T16:00:00Z");
    // Days 8 to 15 of this run; the short run's last day, day 10, ends at lights-on of 18 June.
    expect(previousWindow(current, short, now - 7 * DAY, now, now)?.end).toBe(
      Date.parse("2026-06-18T10:00:00Z"),
    );
    const late = run({ start_date: "2026-06-08", end_date: "2026-06-12" });
    expect(previousWindow(current, late, now - 7 * DAY, now, now)).toBeNull();
    // A range before this run began has no grow day to compare.
    const early = Date.parse("2026-09-01T00:00:00Z");
    expect(previousWindow(current, short, early, early + DAY, now)).toBeNull();
  });
  it("moves a previous run's grid onto this run's grid", () => {
    const previous = run({ start_date: "2026-06-08", lights: { on: 6, off: 18 } });
    const start = Date.parse("2026-09-21T10:00:00Z");
    const from = new SeriesGrid(
      Date.parse("2026-06-15T06:00:00Z"),
      Date.parse("2026-06-15T12:00:00Z"),
      HOUR,
    );
    const moved = alignGrid(
      [1, 2, 3, 4, 5, 6],
      { grid: from, run: previous },
      {
        start,
        step: HOUR,
        length: 8,
        run: current,
      },
    );
    expect(moved).toEqual([1, 2, 3, 4, 5, 6, null, null]);
  });
  it("picks the run in progress and the latest finished one", () => {
    const runs = [
      run({ id: "a", start_date: "2026-01-01", end_date: "2026-03-01" }),
      run({ id: "b", start_date: "2026-04-01", end_date: "2026-06-01" }),
      run({ id: "c", start_date: "2026-07-01", end_date: "2026-08-01", archived: true }),
      run({ id: "d", start_date: "2026-09-01" }),
    ];
    const { current: now, previous } = pickRuns(runs);
    expect([now?.id, previous?.id]).toEqual(["d", "b"]);
    expect(pickRuns([run({ id: "only" })]).previous).toBeNull();
  });
});

describe("downsampling", () => {
  const start = 0;
  const rows = (list: [number, string][]) => list.map(([time, state]) => ({ time, state }));
  it("keeps a month of minute readings to a few hundred points", () => {
    const span = 30 * DAY;
    const step = stepFor(span);
    expect(step).toBe(HOUR);
    const grid = new SeriesGrid(start, span, step);
    for (const day of chunks({ start, end: span })) {
      const list: [number, string][] = [];
      for (let time = day.start; time < day.end; time += MIN) list.push([time, String(time % 7)]);
      grid.add(rows(list));
    }
    const values = grid.values();
    expect(values).toHaveLength(720);
    expect(values.every((value) => value !== null && value >= 0 && value <= 6)).toBe(true);
  });
  it("chooses a short step for a short range", () => {
    expect(stepFor(DAY)).toBe(2 * MIN);
    expect(stepFor(6 * HOUR)).toBe(MIN);
    expect(stepFor(14 * DAY)).toBe(30 * MIN);
    expect(stepFor(400 * DAY)).toBe(14 * HOUR);
  });
  it("averages a step, holds a state that did not change, and leaves a gap while unavailable", () => {
    const grid = new SeriesGrid(start, 6 * HOUR, HOUR);
    grid.add(
      rows([
        [-HOUR, "50"], // held from before the range
        [HOUR + 10 * MIN, "60"],
        [HOUR + 20 * MIN, "62"],
        [3 * HOUR + 5 * MIN, "unavailable"],
        [4 * HOUR + 30 * MIN, "58"],
      ]),
    );
    expect(grid.values()).toEqual([50, 61, 62, null, 58, 58]);
  });
  it("reads days that arrive out of order", () => {
    const grid = new SeriesGrid(start, 4 * HOUR, 2 * HOUR);
    grid.add(rows([[3 * HOUR, "unavailable"]]));
    grid.add(
      rows([
        [HOUR, "40"],
        [2.5 * HOUR, "41"],
      ]),
    );
    // The later row of a step decides what is held after it, whichever day arrived first.
    expect(grid.values()).toEqual([40, 41]);
  });
  it("splits a range into days", () => {
    expect(chunks({ start: 0, end: 2.5 * DAY })).toEqual([
      { start: 0, end: DAY },
      { start: DAY, end: 2 * DAY },
      { start: 2 * DAY, end: 2.5 * DAY },
    ]);
  });
});

describe("range and address", () => {
  it("keeps the choice in the hash query and reads it back", () => {
    const choice = {
      ...DEFAULT_CHOICE,
      preset: "custom" as const,
      from: Date.parse("2026-09-01T00:00:00Z"),
      to: Date.parse("2026-09-03T12:00:00Z"),
      sensors: ["sensor.crop_steering_vwc_zone_1", "sensor.demo_vpd"],
      compare: true,
      shots: false,
    };
    const hash = writeChoice("#/zone/1?code=CS-1", choice);
    expect(hash.startsWith("#/zone/1?code=CS-1&range=custom")).toBe(true);
    expect(readChoice(hash)).toEqual(choice);
    expect(readChoice("#/zone/1")).toEqual(DEFAULT_CHOICE);
    expect(readChoice("#/zone/1?range=7d").preset).toBe("7d");
    // A custom range that is not one falls back to the default.
    expect(readChoice("#/zone/1?range=custom&from=x").preset).toBe(DEFAULT_CHOICE.preset);
  });
  it("resolves each preset", () => {
    const now = Date.parse("2026-09-28T16:00:00Z");
    const context = { now, timeZone: "UTC", lightsOn: 10, lightsOff: 22, run: run({}) };
    const span = (preset: string) =>
      resolveRange({ ...DEFAULT_CHOICE, preset: preset as never }, context);
    expect(span("today")).toEqual({ start: Date.parse("2026-09-28T00:00:00Z"), end: now });
    expect(span("growday")).toEqual({ start: Date.parse("2026-09-28T10:00:00Z"), end: now });
    expect(span("7d")).toEqual({ start: now - 7 * DAY, end: now });
    expect(span("run")).toEqual({ start: Date.parse("2026-09-14T10:00:00Z"), end: now });
    expect(
      resolveRange({ ...DEFAULT_CHOICE, preset: "custom", from: now, to: now - DAY }, context),
    ).toBeNull();
  });
});

describe("the room's sensors", () => {
  it("lists every zone reading, probe, climate and tank sensor the room maps, once each", () => {
    const states = createDemo(Date.parse("2026-09-28T16:00:00"));
    const room = buildRoom(states, discoverRooms(states)[0]);
    const sensors = explorerSensors(room, states);
    const ids = sensors.map((sensor) => sensor.entityId);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toContain(room.zones[0].vwc.entityId);
    expect(ids).toContain("sensor.demo_z1_front_vwc");
    expect(ids).toContain("sensor.demo_vpd");
    expect(ids).toContain("sensor.demo_tank_ph");
    expect(sensors.find((sensor) => sensor.entityId === "sensor.demo_vpd")?.unit).toBe("kPa");
    expect(new Set(sensors.map((sensor) => sensor.group))).toEqual(
      new Set([...room.zones.map((zone) => zone.name), "Room climate", "Feed and tank"]),
    );
    // A sensor Home Assistant does not have is left out.
    const { ["sensor.demo_vpd"]: _gone, ...rest } = states;
    expect(
      explorerSensors(room, rest).some((sensor) => sensor.entityId === "sensor.demo_vpd"),
    ).toBe(false);
  });
});

describe("the 30 d range and the dryback markers", () => {
  it("offers 30 d, kept in the address with the dryback overlay", () => {
    const choice = readChoice("#/zone/1?range=30d&dryback=1");
    expect(choice.preset).toBe("30d");
    expect(choice.dryback).toBe(true);
    expect(readChoice("#/zone/1").dryback).toBe(false);
    expect(writeChoice("#/zone/1", { ...choice, dryback: false })).not.toContain("dryback");
    const now = Date.parse("2026-09-28T16:00:00Z");
    const span = resolveRange(choice, {
      now,
      timeZone: "UTC",
      lightsOn: 6,
      lightsOff: 18,
      run: null,
    })!;
    expect(span.end - span.start).toBe(30 * DAY);
  });
  it("marks each grow day's peak and the low after it, in percent of the peak", () => {
    const H = 3_600_000;
    const times = [0, 2, 4, 10, 20, 24, 26, 30, 44].map((h) => h * H);
    const values = [40, 60, 58, 55, 48, 50, 62, 59, 49.6];
    const markers = drybackMarkers(times, values, [0, 24 * H]);
    expect(markers.map((m) => [m.peak.value, m.low.value])).toEqual([
      [60, 48],
      [62, 49.6],
    ]);
    expect(markers[0].percent).toBeCloseTo(20, 6);
    expect(drybackMarkers(times, values.map(() => null), [0])).toEqual([]);
  });
});
