import { describe, expect, it } from "vitest";
import { blockedSince, dailyRatios, leakIncidents, leakWatch, meterLitres, trendWord, zoneFlow, zoneMeter } from "./flow-check";
import type { CsEvent } from "./parity-types";

const H = 3_600_000;
const T0 = Date.UTC(2026, 9, 22, 8);
let n = 0;
const event = (kind: string, at: number, zone: number | null, data: Record<string, unknown>, code: string | null = null): CsEvent => ({
  v: 1,
  id: `e${n++}`,
  ts: new Date(at).toISOString(),
  room_id: "room:",
  zone,
  kind,
  outcome: "ok",
  code,
  source: { actor: "engine" },
  data,
});
const flow = (at: number, zone: number, ratio: number, asked = 1.2) =>
  event("flow.reconciled", at, zone, { ratio, commanded_l: asked, metered_l: Number((asked * ratio).toFixed(3)) });

describe("zoneFlow", () => {
  it("zoneFlow last three ratios 0.62 → low and 62%", () => {
    const events = [
      flow(T0, 2, 1),
      flow(T0 + H, 2, 0.98),
      flow(T0 + 2 * H, 2, 0.62),
      flow(T0 + 3 * H, 2, 0.62),
      flow(T0 + 4 * H, 2, 0.62),
      flow(T0 + 4 * H, 1, 1.4),
    ];
    const z = zoneFlow(events, 2);
    expect(z.verdict).toBe("low");
    expect(z.last3Pct).toBeCloseTo(62, 6);
    // Every shot given: the percentages are the mean of ratio × 100.
    expect(z.todayPct).toBeCloseTo(76.8, 6);
    expect(z.shots).toHaveLength(5);
    expect(z.shots[4]).toEqual({ at: T0 + 4 * H, askedL: 1.2, meteredL: 0.744 });
  });

  it("zoneFlow without reconciled events → no_meter", () => {
    const z = zoneFlow([event("shot.completed", T0, 2, { commanded_l: 1.2, metered_l: null })], 2);
    expect(z).toEqual({ last3Pct: null, todayPct: null, shots: [], verdict: "no_meter" });
  });

  it("uses the backend's 0.8 and 1.2 bounds, inclusive", () => {
    expect(zoneFlow([flow(T0, 1, 0.8)], 1).verdict).toBe("on_target");
    expect(zoneFlow([flow(T0, 1, 1.2)], 1).verdict).toBe("on_target");
    expect(zoneFlow([flow(T0, 1, 0.79)], 1).verdict).toBe("low");
    expect(zoneFlow([flow(T0, 1, 1.21)], 1).verdict).toBe("high");
  });

  it("counts today from the day start, the last three across days", () => {
    const events = [flow(T0 - 20 * H, 1, 0.5), flow(T0 - 19 * H, 1, 0.5), flow(T0 + H, 1, 1)];
    const z = zoneFlow(events, 1, T0);
    expect(z.shots).toHaveLength(1);
    expect(z.todayPct).toBe(100);
    expect(z.last3Pct).toBeCloseTo(66.667, 3);
    expect(zoneFlow(events, 1, T0 + 2 * H).todayPct).toBeNull();
  });

  it("times each shot from its shot.started, joined on the intent id", () => {
    const started = { ...event("shot.started", T0, 1, { commanded_l: 1.2 }), correlation: { intent_id: "i1" } };
    const done = { ...flow(T0 + 62_000, 1, 1), correlation: { intent_id: "i1" } };
    expect(zoneFlow([started, done, flow(T0 + H, 1, 1)], 1).shots.map((s) => s.at)).toEqual([T0, T0 + H]);
  });

  it("skips a reconciled event without a finite ratio", () => {
    expect(zoneFlow([event("flow.reconciled", T0, 1, { ratio: null, commanded_l: 1, metered_l: null })], 1).verdict).toBe("no_meter");
  });
});

describe("leakIncidents", () => {
  it("leakIncidents keeps only CS-319", () => {
    const alerts = [
      event("alert.raised", T0, null, { key: "flow_idle_sensor.m", title: "Room A: water flows with no zone on (CS-319)" }, "CS-319"),
      event("alert.raised", T0 + H, 2, { key: "flow_low__z2", title: "Less water than expected (CS-318)" }, "CS-318"),
      event("alert.cleared", T0 + 2 * H, null, { key: "flow_idle_sensor.m" }, "CS-319"),
      event("alert.raised", T0 + 3 * H, null, { key: "flow_idle_sensor.m", title: "Water again", litres: 0.3 }, "CS-319"),
    ];
    expect(leakIncidents(alerts)).toEqual([
      { at: T0, title: "Room A: water flows with no zone on (CS-319)", litres: null },
      { at: T0 + 3 * H, title: "Water again", litres: 0.3 },
    ]);
  });
});

describe("the rest of the page's sums", () => {
  it("blockedSince is the first shot of the last run of short shots", () => {
    const z = zoneFlow([flow(T0, 2, 0.7), flow(T0 + H, 2, 1), flow(T0 + 2 * H, 2, 0.6), flow(T0 + 3 * H, 2, 0.5)], 2);
    expect(blockedSince(z.shots)).toBe(T0 + 2 * H);
    expect(blockedSince(zoneFlow([flow(T0, 2, 1)], 2).shots)).toBeNull();
  });

  it("dailyRatios gives each of the last days its mean, null when none, and trendWord reads them", () => {
    const tz = "UTC";
    const days = dailyRatios([flow(T0 - 24 * H, 1, 1), flow(T0, 1, 1), flow(T0 + H, 1, 0.5)], 1, T0 + 2 * H, tz, 3);
    expect(days).toEqual([null, 1, 0.75]);
    expect(trendWord(days)).toBe("fell today");
    expect(trendWord([1, 0.98, 1.01])).toBe("steady");
    expect(trendWord([1, 1, 1.3])).toBe("rose today");
    expect(trendWord([null, null, 1])).toBe("today only");
  });

  it("meterLitres reads litres, m³ and gallons, and nothing else", () => {
    expect(meterLitres("12.5", "L")).toBe(12.5);
    expect(meterLitres("0.5", "m³")).toBe(500);
    expect(meterLitres("1", "gal")).toBeCloseTo(3.785411784, 9);
    expect(meterLitres("100", "pulses")).toBeNull();
    expect(meterLitres("unavailable", "L")).toBeNull();
  });

  it("leakWatch counts the meter's rise with every valve shut, and the time it watched", () => {
    const start = T0;
    const valves = [
      [
        { state: "off", time: start },
        { state: "on", time: start + 2 * H },
        { state: "off", time: start + 2 * H + 60_000 },
      ],
    ];
    const meter = [
      { state: "100", time: start },
      { state: "100", time: start + H },
      // The shot's own water, reported just after the valve shut: not a leak.
      { state: "101.2", time: start + 2 * H + 120_000 },
      { state: "101.5", time: start + 3 * H },
      { state: "101.5", time: start + 4 * H },
    ];
    const watch = leakWatch(valves, meter, "L", start, start + 4 * H);
    expect(watch.litres).toBeCloseTo(0.3, 9);
    expect(watch.valveOpen).toEqual([{ start: start + 2 * H, end: start + 2 * H + 60_000 }]);
    expect(watch.meterFlow).toEqual([
      { start: start + H, end: start + 2 * H + 120_000 },
      { start: start + 2 * H + 120_000, end: start + 3 * H },
    ]);
    // Four hours less the minute the valve was open and the five after it.
    expect(watch.watchedMs).toBe(4 * H - 6 * 60_000);
    expect(leakWatch(valves, meter, "pulses", start, start + 4 * H).litres).toBeNull();
  });
});

describe("zoneMeter", () => {
  const supply = {
    zone_meters: { "room:f2_": { "3": "sensor.z3" } },
    irrigation_pumps: [
      { entity_id: "switch.p1", max_concurrent_zones: 1, flow_meter: "sensor.p1_meter" },
      { entity_id: "switch.p2", max_concurrent_zones: 1, flow_meter: null },
    ],
  };
  it("takes the zone's own meter, else its pump's, else none", () => {
    expect(zoneMeter(supply, "room:f2_", 3, "switch.p2")).toBe("sensor.z3");
    expect(zoneMeter(supply, "room:f2_", 1, "switch.p1")).toBe("sensor.p1_meter");
    expect(zoneMeter(supply, "room:f2_", 1, "switch.p2")).toBeNull();
    expect(zoneMeter(supply, "room:f2_", 1, "switch.other")).toBeNull();
    expect(zoneMeter({ ...supply, irrigation_pumps: [supply.irrigation_pumps[0]] }, "room:f2_", 1, null)).toBe("sensor.p1_meter");
    expect(zoneMeter(null, "room:f2_", 1, null)).toBeNull();
  });
});
