import { describe, expect, it } from "vitest";
import { createDemo, demoHistory } from "./demo";
import { discoverRooms } from "./model";
import {
  chartDivisor,
  chartRows,
  describeLine,
  gateText,
  mergeWindow,
  rangeTicks,
  sourceGate,
  sparkPath,
  tankAxis,
  tankLine,
} from "./tank-history";
import type { EntityState } from "./types";

const HOUR = 3_600_000;
const now = Date.parse("2026-09-24T20:00:00Z");
const at = (hoursAgo: number) => new Date(now - hoursAgo * HOUR).toISOString();
const entity = (unit?: string): EntityState => ({
  entity_id: "sensor.x",
  state: "1",
  attributes: unit === undefined ? {} : { unit_of_measurement: unit },
});

describe("tank chart units", () => {
  it("charts EC in mS/cm and refuses a unit the card does not accept", () => {
    expect(chartDivisor("ec", entity("mS/cm"))).toBe(1);
    expect(chartDivisor("ec", entity("dS/m"))).toBe(1);
    expect(chartDivisor("ec", entity("µS/cm"))).toBe(1000);
    expect(chartDivisor("ec", entity("uS/cm"))).toBe(1000);
    expect(chartDivisor("ec", entity("ppm"))).toBeNull();
    expect(chartDivisor("ec", entity())).toBeNull();
    expect(chartDivisor("ph", entity("pH"))).toBe(1);
    expect(chartDivisor("ph", entity())).toBe(1);
    expect(chartDivisor("ph", entity("mV"))).toBeNull();
    // No current state to read a unit from: the history is charted as recorded.
    expect(chartDivisor("ec", undefined)).toBe(1);
  });
});

describe("tank lines", () => {
  const series = {
    points: [
      { time: at(40), value: 2500 }, // long before a 24 h window: replaced by the next
      { time: at(30), value: 3050 }, // still in force when the window opens
      { time: at(20), value: 3100 },
      { time: at(10), value: 2900 },
      { time: at(4), value: 3300 },
      { time: at(1), value: 3000 },
    ],
  };
  it("keeps the window, in chart units, with its latest, lowest and highest reading", () => {
    const line = tankLine(series, 24, now, 1000);
    expect(line.readings.map((reading) => reading.value)).toEqual([3.05, 3.1, 2.9, 3.3, 3]);
    expect(line.latest).toEqual({ time: now - HOUR, value: 3 });
    expect(line.lowest!.value).toBe(2.9);
    expect(line.highest!.value).toBe(3.3);
  });
  it("starts with the value in force when the window opens, as the recorder holds it", () => {
    expect(tankLine(series, 24, now, 1000).readings[0]).toEqual({
      time: now - 24 * HOUR,
      value: 3.05,
    });
    // A probe steady all window long still has its reading.
    const steady = tankLine({ points: [{ time: at(30), value: 6.05 }] }, 24, now, 1);
    expect(steady.readings).toEqual([{ time: now - 24 * HOUR, value: 6.05 }]);
    expect(steady.latest!.value).toBe(6.05);
    // Nothing is invented before a probe's first reading.
    expect(tankLine({ points: [{ time: at(3), value: 6 }] }, 24, now, 1).readings).toEqual([
      { time: now - 3 * HOUR, value: 6 },
    ]);
  });
  it("keeps the reading in force at the window's start when a refresh slides it", () => {
    const held = [
      {
        entityId: "sensor.tank_ph",
        label: "pH",
        points: [
          { time: at(30), value: 6.05 },
          { time: at(2), value: 6.1 },
        ],
      },
    ];
    const recent = [{ ...held[0], points: [{ time: at(0.5), value: 6.12 }] }];
    const merged = mergeWindow(held, recent, now - 24 * HOUR);
    expect(merged[0].points.map((point) => point.value)).toEqual([6.05, 6.1, 6.12]);
    expect(tankLine(merged[0], 24, now, 1).readings[0]).toEqual({
      time: now - 24 * HOUR,
      value: 6.05,
    });
  });
  it("breaks the drawn line at a long silence instead of bridging it", () => {
    const plot = tankLine(series, 24, now, 1000).plot;
    expect(plot.some((point) => point.value === null)).toBe(true);
  });
  it("thins a month of readings for drawing but summarises every one", () => {
    const points = Array.from({ length: 30 * 24 * 60 }, (_, index) => ({
      time: new Date(now - index * 60_000).toISOString(),
      value: index === 777 ? 9.9 : 3 + (index % 7) / 100,
    }));
    const line = tankLine({ points }, 720, now, 1);
    expect(line.readings).toHaveLength(points.length);
    expect(line.plot.length).toBeLessThanOrEqual(800);
    expect(line.highest!.value).toBe(9.9);
    expect(line.plot.some((point) => point.value === 9.9)).toBe(true);
  });
  it("describes a line for the text alternative", () => {
    expect(describeLine("EC", " mS/cm", tankLine(series, 24, now, 1000))).toBe(
      "EC latest 3.00, lowest 2.90, highest 3.30 mS/cm",
    );
    expect(describeLine("pH", "", tankLine({ points: [] }, 24, now, 1))).toBe(
      "pH: no recorded readings",
    );
    expect(describeLine("pH", "", null)).toBe("pH: no recorded readings");
  });
});

describe("chart rows", () => {
  it("carries each reading's value until it changes, as the recorder does", () => {
    const rows = chartRows(
      [
        { time: 0, value: 3 },
        { time: 20, value: 3.2 },
      ],
      [
        { time: 10, value: 6 },
        { time: 20, value: 6.1 },
      ],
    );
    expect(rows).toEqual([
      { time: 0, ec: 3, ph: null },
      { time: 10, ec: 3, ph: 6 },
      { time: 20, ec: 3.2, ph: 6.1 },
    ]);
  });
  it("carries nothing across a break or more than two hours past a reading", () => {
    const rows = chartRows(
      [
        { time: 0, value: 3 },
        { time: 1, value: null },
      ],
      [
        { time: 5, value: 6 },
        { time: 3 * HOUR, value: 6.2 },
      ],
    );
    expect(rows.map((row) => row.ec)).toEqual([3, null, null, null]);
    const late = chartRows([{ time: 0, value: 3 }], [{ time: 2 * HOUR + 1, value: 6 }]);
    expect(late.at(-1)).toEqual({ time: 2 * HOUR + 1, ec: null, ph: 6 });
  });
  it("carries a thinned line to its next point, however far, without a false break", () => {
    // A month thinned to 800 points leaves hours between neighbours; only a null is a gap.
    const rows = chartRows(
      [
        { time: 0, value: 3 },
        { time: 4 * HOUR, value: 3.1 },
      ],
      [{ time: 3 * HOUR, value: 6 }],
    );
    expect(rows).toEqual([
      { time: 0, ec: 3, ph: null },
      { time: 3 * HOUR, ec: 3, ph: 6 },
      { time: 4 * HOUR, ec: 3.1, ph: 6 },
    ]);
  });
});

describe("tank axis", () => {
  it("takes in a nearby gate limit and leaves a far one to the list", () => {
    const axis = tankAxis([3.05, 3.1, 3.32], [1, 3.5], 0.2)!;
    expect(axis.limits).toEqual([3.5]);
    expect(axis.min).toBeLessThanOrEqual(3.05);
    expect(axis.max).toBeGreaterThanOrEqual(3.5);
    expect(axis.min).toBeGreaterThan(1);
  });
  it("always has five evenly spaced ticks, so two axes share their gridlines", () => {
    for (const [values, limits] of [
      [[3.05, 3.32], [3.5]],
      [
        [5.6, 6.1],
        [5.5, 6.5],
      ],
      [[0.8, 0.81], []],
      [[1200, 1850], []],
    ]) {
      const axis = tankAxis(values, limits, 0.2)!;
      expect(axis.ticks).toHaveLength(5);
      expect(axis.ticks[0]).toBe(axis.min);
      expect(axis.ticks[4]).toBe(axis.max);
      const steps = axis.ticks.slice(1).map((tick, index) => tick - axis.ticks[index]);
      for (const step of steps) expect(step).toBeCloseTo(steps[0], 9);
      expect(axis.min).toBeLessThanOrEqual(Math.min(...values, ...axis.limits));
      expect(axis.max).toBeGreaterThanOrEqual(Math.max(...values, ...axis.limits));
    }
  });
  it("keeps probe noise small and never goes below zero", () => {
    const axis = tankAxis([6.01, 6.02], [], 0.2)!;
    expect(axis.max - axis.min).toBeGreaterThanOrEqual(0.2);
    expect(tankAxis([0.02, 0.05], [], 0.2)!.min).toBe(0);
    expect(tankAxis([], [3.5], 0.2)).toBeNull();
  });
});

describe("source-water gate", () => {
  const states = createDemo(now);
  const [f2, f1] = discoverRooms(states);
  it("reads the room's limits and feed-water probe as the controller does", () => {
    expect(sourceGate(states, f2, "ec")).toEqual({
      min: 2.3,
      max: 3.5,
      probe: "sensor.demo_tank_ec",
      option: false,
    });
    expect(sourceGate(states, f2, "ph")).toEqual({
      min: 5.5,
      max: 6.5,
      probe: "sensor.demo_tank_ph",
      option: false,
    });
    expect(sourceGate(states, f1, "ec").probe).toBeNull();
  });
  it("leaves the probe to the controller app's option only in an unsaved default room", () => {
    // The controller takes the descriptor's feed probe once the room has a setup revision;
    // before that, in the default room only, its app's own option comes first.
    const copy = createDemo(now);
    delete copy["sensor.crop_steering_engine_config"].attributes.setup_revision;
    delete copy["sensor.crop_steering_f1_engine_config"].attributes.setup_revision;
    expect(sourceGate(copy, f2, "ec").option).toBe(true);
    expect(sourceGate(copy, f1, "ec").option).toBe(false);
    expect(sourceGate(states, f2, "ec").option).toBe(false);
  });
  it("treats a limit of 0 or a missing limit as off", () => {
    const copy = createDemo(now);
    copy["number.crop_steering_irrigation_ec_min"].state = "0";
    delete copy["number.crop_steering_irrigation_ec_max"];
    expect(sourceGate(copy, f2, "ec")).toMatchObject({ min: null, max: null });
  });
  it("names the probe the gate checks, and never draws a gate that holds nothing", () => {
    const gate = { min: 1, max: 3.5, probe: "sensor.tank_ec", option: false };
    expect(gateText(gate, "ec", "sensor.tank_ec")).toEqual({
      active: true,
      text: "1–3.5 mS/cm. Irrigation is held while this probe reads outside the gate or stops reporting.",
    });
    expect(gateText(gate, "ec", "sensor.other").text).toBe(
      "1–3.5 mS/cm, checked on sensor.tank_ec, not on this tank probe.",
    );
    expect(gateText({ ...gate, min: null }, "ph", "sensor.tank_ec").text).toMatch(/^at most 3.5\./);
    expect(gateText({ ...gate, max: null }, "ph", null).text).toBe(
      "at least 1, checked on sensor.tank_ec.",
    );
    // Limits set with no probe to check them on are named as not applied, not left to look on.
    expect(gateText({ ...gate, probe: null }, "ec", "sensor.tank_ec")).toEqual({
      active: false,
      text: "Off: no feed-water EC probe is mapped, so 1–3.5 mS/cm is not applied.",
    });
    expect(gateText({ min: null, max: null, probe: null, option: false }, "ph", null)).toEqual({
      active: false,
      text: "Off: no feed-water pH probe is mapped.",
    });
    expect(
      gateText({ min: null, max: null, probe: "sensor.tank_ec", option: false }, "ec", null),
    ).toEqual({ active: false, text: "Off: no EC limits are set." });
    // Where the app's own option may name a probe, only what is mapped here is stated.
    expect(gateText({ ...gate, probe: null, option: true }, "ec", "sensor.tank_ec")).toEqual({
      active: false,
      text: "1–3.5 mS/cm is set, but no feed-water EC probe is mapped here.",
    });
    expect(gateText({ ...gate, max: null, probe: null, option: true }, "ph", null).text).toBe(
      "At least 1 is set, but no feed-water pH probe is mapped here.",
    );
  });
});

describe("time ticks", () => {
  it.each([
    [24, 6 * HOUR],
    [168, 24 * HOUR],
    [720, 5 * 24 * HOUR],
  ])("marks %s hours on local boundaries inside the window", (hours, spacing) => {
    const start = now - hours * HOUR;
    const ticks = rangeTicks(start, now, hours);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    expect(ticks.length).toBeLessThanOrEqual(7);
    for (const tick of ticks) {
      expect(tick).toBeGreaterThanOrEqual(start);
      expect(tick).toBeLessThanOrEqual(now);
      const date = new Date(tick);
      expect(date.getMinutes()).toBe(0);
      expect(date.getHours() % (hours <= 24 ? 6 : 24)).toBe(0);
    }
    // The first boundary inside the window, then the step (an hour either way at a DST change).
    expect(ticks[0] - start).toBeLessThanOrEqual(hours <= 24 ? spacing : 25 * HOUR);
    for (let index = 1; index < ticks.length; index++)
      expect(Math.abs(ticks[index] - ticks[index - 1] - spacing)).toBeLessThanOrEqual(HOUR);
  });
});

describe("sparkline", () => {
  it("fits the window across and the readings up, breaking at a gap", () => {
    const path = sparkPath(
      [
        { time: 0, value: 3 },
        { time: 50, value: 3.4 },
        { time: 60, value: null },
        { time: 100, value: 3.2 },
      ],
      0,
      100,
      64,
      20,
      0.2,
    );
    expect(path).toBe("M0.0,19.0L32.0,1.0M64.0,10.0");
  });
  it("draws a steady reading level in the middle and nothing without readings", () => {
    expect(
      sparkPath(
        [
          { time: 0, value: 6 },
          { time: 10, value: 6 },
        ],
        0,
        10,
        64,
        20,
        0.2,
      ),
    ).toBe("M0.0,10.0L64.0,10.0");
    expect(sparkPath([{ time: 0, value: null }], 0, 10, 64, 20, 0.2)).toBe("");
  });
});

describe("demo tank history", () => {
  const states = createDemo(now);
  const ids = ["sensor.demo_tank_ec", "sensor.demo_tank_ph"];
  const fill = Date.parse(states["sensor.demo_tank_last_fill"].state);
  const around = (points: { time: string; value: number }[], time: number) => [
    points.filter((point) => Date.parse(point.time) < time).at(-1)!.value,
    points.find((point) => Date.parse(point.time) > time)!.value,
  ];
  it("drifts slowly and steps at each refill, ending at the live reading", () => {
    const [ec, ph] = demoHistory(states, ids, 24, now);
    expect(ec.points.at(-1)!.value).toBeCloseTo(3.06, 2);
    expect(ph.points.at(-1)!.value).toBeCloseTo(5.66, 2);
    const [ecBefore, ecAfter] = around(ec.points, fill);
    const [phBefore, phAfter] = around(ph.points, fill);
    expect(ecBefore - ecAfter).toBeGreaterThan(0.15);
    expect(phBefore - phAfter).toBeGreaterThan(0.3);
    // Between refills, a slow drift: no five-minute sample moves far.
    const steps = ec.points
      .slice(1)
      .map((point, index) => Math.abs(point.value - ec.points[index].value));
    expect(steps.filter((step) => step > 0.05)).toHaveLength(1);
  });
  it("shows every three-day batch across a month, in few enough points to chart", () => {
    const [ec] = demoHistory(states, ids, 720, now);
    expect(ec.points.length).toBeLessThanOrEqual(1000);
    const drops = ec.points
      .slice(1)
      .filter((point, index) => ec.points[index].value - point.value > 0.15);
    expect(drops.length).toBeGreaterThanOrEqual(9);
    expect(drops.length).toBeLessThanOrEqual(10);
  });
  it("is deterministic for a fixed clock and differs between rooms", () => {
    expect(demoHistory(states, ids, 24, now)).toEqual(demoHistory(states, ids, 24, now));
    const [f1] = demoHistory(states, ["sensor.demo_f1_tank_ec"], 24, now);
    expect(f1.points.at(-1)!.value).toBeCloseTo(2.8, 2);
  });
});
