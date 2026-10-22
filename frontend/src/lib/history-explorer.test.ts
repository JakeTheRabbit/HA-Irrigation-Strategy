import { describe, expect, it, vi } from "vitest";
import type { RunRecord } from "./comparison-types";
import { createDemo } from "./demo";
import {
  alignGrid,
  alignToCurrent,
  chartNotes,
  chunks,
  DEFAULT_CHOICE,
  defaultExplorerSeries,
  drybackMarkers,
  explorerCsv,
  explorerSensors,
  explorerSeries,
  loadExplorerEvents,
  phaseLane,
  pickRuns,
  previousWindow,
  readChoice,
  readExplorerChoice,
  resolveRange,
  runDayAt,
  runDayStart,
  SeriesGrid,
  stepFor,
  writeChoice,
  writeExplorerChoice,
  type NoteReading,
} from "./history-explorer";
import type { CsEvent } from "./parity-types";
import type { ProjectionIntent } from "./strategy-review";
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

describe("H1 explorer: lanes, notes, CSV and the event read", () => {
  const T0 = Date.parse("2026-10-22T00:00:00Z");
  const at = (h: number, m = 0) => T0 + h * HOUR + m * MIN;
  const iso = (ms: number) => new Date(ms).toISOString();
  const event = (kind: string, ms: number, data: Record<string, unknown>, zone: number | null = null): CsEvent => ({
    v: 1,
    id: `${kind}-${ms}`,
    ts: iso(ms),
    room_id: "room:",
    zone,
    kind,
    outcome: "ok",
    code: null,
    source: { actor: "engine" },
    data,
  });

  it("phaseLane splits on phase.changed and marks projection planned", () => {
    const events = [
      event("phase.changed", at(6), { from: "P3", to: "P0", how: "lights on" }),
      event("phase.changed", at(7, 30), { from: "P0", to: "P1", how: "dryback reached" }, 1),
      event("phase.changed", at(10), { from: "P1", to: "P2", how: "field capacity reached" }, 1),
      // Another zone's change is not this lane's.
      event("phase.changed", at(9), { from: "P1", to: "P2", how: "field capacity reached" }, 2),
    ];
    const span = { start: at(0), end: at(24) };
    const now = at(14, 5);
    const projection: ProjectionIntent[] = [
      { zone: 1, at: iso(at(15)), duration_s: 60, source: "engine", expected: true },
      { zone: 1, at: iso(at(16, 30)), duration_s: 60, source: "timer", expected: false },
    ];
    const lane = phaseLane(events, span, projection, { now, zone: 1 });
    expect(lane).toEqual([
      { from: at(0), to: at(6), phase: "P3", planned: false },
      { from: at(6), to: at(7, 30), phase: "P0", planned: false },
      { from: at(7, 30), to: at(10), phase: "P1", planned: false },
      { from: at(10), to: now, phase: "P2", planned: false },
      { from: now, to: at(16, 31), phase: "P2", planned: true },
    ]);
    // No projection, no planned segment: the lane ends now.
    expect(phaseLane(events, span, null, { now, zone: 1 }).some((s) => s.planned)).toBe(false);
    expect(phaseLane(events, span, [], { now, zone: 1 }).at(-1)?.to).toBe(now);
  });

  it("chartNotes reports band excursion start once", () => {
    const points = [8, 9, 9.5, 9.6, 9.7, 9.8, 10, 10.2].map((h, i) => ({ t: at(h), v: [5.4, 5.8, 6.2, 6.5, 6.6, 6.4, 6.3, 6.6][i] }));
    const readings: NoteReading[] = [
      { key: "ec2", label: "Zone 2", entityId: "sensor.ec_2", points, band: [4.5, 6.0], kind: "value" },
      // Not selected: no note.
      { key: "ec3", label: "Zone 3", entityId: "sensor.ec_3", points, band: [4.5, 6.0], kind: "value" },
    ];
    const notes = chartNotes([], ["ec2"], readings, "UTC");
    expect(notes).toEqual([{ at: at(9, 30), series: "ec2", text: "Zone 2 over the band since 09:30" }]);
    // Out of the band from the range's first reading: it left before, so no start time is claimed.
    const early = [{ t: at(0), v: 3 }, { t: at(1), v: 3.1 }, { t: at(2), v: 4.6 }];
    expect(chartNotes([], ["ec2"], [{ ...readings[0], points: early }], "UTC")[0].text).toBe("Zone 2 under the band until 02:00");
    expect(chartNotes([], ["ec2"], [{ ...readings[0], points: early.slice(0, 2) }], "UTC")[0].text).toBe(
      "Zone 2 under the band all through this range",
    );
    // An excursion that ended says when; a refill on a level reads its rise; an alert on a series is
    // said once (the band note already says it).
    const back = [...points, { t: at(11), v: 5.5 }];
    const level: NoteReading = {
      key: "tank",
      label: "Tank",
      entityId: "sensor.tank",
      kind: "level",
      band: null,
      points: [
        { t: at(6), v: 40 },
        { t: at(6, 10), v: 41 },
        { t: at(6, 20), v: 74 },
        { t: at(7), v: 73 },
      ],
    };
    const alert = event("alert.raised", at(9, 40), { title: "Pore EC 6.6 is over the band", entity_id: "sensor.ec_2" }, 2);
    const other = event("alert.raised", at(6, 30), { title: "Tank low", entity_id: "sensor.tank" });
    expect(
      chartNotes([alert, other], ["ec2", "tank"], [{ ...readings[0], points: back }, level], "UTC"),
    ).toEqual([
      { at: at(6, 20), series: "tank", text: "Refilled 06:20 · 41% to 74%" },
      { at: at(6, 30), series: "tank", text: "Tank low" },
      { at: at(9, 30), series: "ec2", text: "Zone 2 over the band 09:30 to 11:00" },
    ]);
  });

  it("csv header counts selected series", () => {
    const csv = explorerCsv(
      [at(10), at(10, 5)],
      [
        { label: "Zone 1 VWC", unit: "%", values: [58.42, null] },
        { label: "Zone 1, pore EC", unit: "mS/cm", values: [5.3, 5.31] },
      ],
      "UTC",
    );
    const [head, first, second] = csv.trim().split("\n");
    expect(head).toBe('Time,Zone 1 VWC (%),"Zone 1, pore EC (mS/cm)"');
    expect(head.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/)).toHaveLength(3);
    expect(first).toBe("2026-10-22 10:00,58.42,5.3");
    expect(second).toBe("2026-10-22 10:05,,5.31");
  });

  it("7-day range uses pagedQuery", async () => {
    const query = vi.fn(async (_c: unknown, q: { since: string; until?: string }) => ({
      kind: "ok" as const,
      data: { events: [event("shot.completed", Date.parse(q.since) + HOUR, {}, 1)] },
      revision: null,
      readback: { status: "verified" as const, at: null },
      eventIds: [],
    }));
    const span = { start: at(0) - 7 * DAY, end: at(0) };
    const read = await loadExplorerEvents({ operator: vi.fn() } as never, "room:", span, query);
    expect(query).toHaveBeenCalledTimes(7);
    for (const [, q] of query.mock.calls)
      expect(q).toMatchObject({ room_id: "room:", kinds: ["phase.changed", "shot.completed", "alert.raised"] });
    expect(query.mock.calls[0][1].until).toBe(iso(span.end));
    expect(read).toMatchObject({ kind: "ok", truncated: false });
    if (read.kind === "ok") expect(read.events.map((e) => Date.parse(e.ts))).toEqual([...read.events.map((e) => Date.parse(e.ts))].sort((a, b) => a - b));
    // Over the cap: the newest whole days only, and it says so.
    const many = vi.fn(async (_c: unknown, q: { since: string }, max?: number) => ({
      kind: "ok" as const,
      data: { events: Array.from({ length: Math.min(max ?? 5000, 3) }, (_, i) => event("shot.completed", Date.parse(q.since) + i * MIN, {}, 1)) },
      revision: null,
      readback: { status: "verified" as const, at: null },
      eventIds: [],
    }));
    const capped = await loadExplorerEvents({ operator: vi.fn() } as never, "room:", span, many, 7);
    expect(capped).toMatchObject({ kind: "ok", truncated: true });
    if (capped.kind === "ok") expect(capped.events).toHaveLength(6);
  });
});

describe("H1 explorer: series chips", () => {
  it("groups a room's series by zone, feed, tank and room, and opens on eight", () => {
    const states = createDemo(Date.parse("2026-09-28T16:00:00"));
    const room = buildRoom(states, discoverRooms(states)[0]);
    const series = explorerSeries(room, explorerSensors(room, states));
    const zone1 = series.filter((s) => s.group === "zone:1").map((s) => s.chip);
    expect(zone1).toEqual(["VWC", "Pore EC", "Root temp"]);
    expect(series.filter((s) => s.group === "feed").map((s) => s.chip)).toEqual(["EC", "pH"]);
    expect(series.find((s) => s.chart === "Tank level")?.chip).toBe("Level");
    // One colour per zone on every chart.
    expect(new Set(series.filter((s) => s.zone === 2).map((s) => s.color)).size).toBe(1);
    expect(defaultExplorerSeries(series)).toHaveLength(8);
  });
  it("keeps the range, the series and the comparison in the address", () => {
    const hash = writeExplorerChoice("#/history/explorer?zone=2", {
      range: "7d",
      from: null,
      to: null,
      series: ["sensor.a_b", "sensor.c"],
      last: true,
    });
    expect(hash).toBe("#/history/explorer?zone=2&range=7d&series=sensor.a_b,sensor.c&last=1");
    expect(readExplorerChoice(hash)).toEqual({ range: "7d", from: null, to: null, series: ["sensor.a_b", "sensor.c"], last: true });
    expect(readExplorerChoice("#/history/explorer?range=3d").range).toBe("today");
    expect(readExplorerChoice("#/history/explorer?range=custom").range).toBe("today");
  });
});
