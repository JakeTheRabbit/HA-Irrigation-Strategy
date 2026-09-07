import { describe, expect, it } from "vitest";
import { buildComparisonTarget } from "./comparison-target";
import { midnight, ageAt } from "./comparison";

const parameters = {
  field_capacity: 70,
  dryback_target: 20,
  p1_target_vwc: 65,
  p2_vwc_threshold: 58,
  p0_maximum_wait_time: 60,
  p1_time_between_shots: 15,
  p1_maximum_shots: 4,
  ec_target_p0: 3,
  ec_target_p1: 3.5,
  ec_target_p2: 4,
  p3_emergency_vwc_threshold: 38,
};
const input = {
  parameters,
  lightsOn: 10,
  lightsOff: 22,
  timeZone: "UTC",
  runStartDate: "2026-08-01",
  start: Date.parse("2026-08-01T00:00:00Z"),
  end: Date.parse("2026-08-03T00:00:00Z"),
  now: Date.parse("2026-08-03T00:00:00Z"),
};

describe("configured daily references over recorded time", () => {
  it("clips a continuous overnight dryback and EC connection across midnight", () => {
    const start = Date.parse("2026-08-02T00:00:00Z"),
      end = Date.parse("2026-08-02T03:00:00Z");
    const out = buildComparisonTarget({ ...input, start, end, now: end });
    expect(out.vwc.some((point) => point.value === null)).toBe(false);
    expect(out.ec.some((point) => point.value === null)).toBe(false);
    expect(out.vwc[0]).toMatchObject({ time: start, value: 58 - (2 * 2) / 12 });
    expect(out.vwc.at(-1)?.value).toBeCloseTo(58 - (2 * 5) / 12);
    expect(out.ec[0].value).toBeCloseTo(4 - 2 / 12);
    expect(out.ec.at(-1)?.value).toBeCloseTo(4 - 5 / 12);
  });
  it("retains an explicit gap when a daytime EC phase reference is absent", () => {
    const { ec_target_p1, ...partial } = parameters;
    const out = buildComparisonTarget({ ...input, parameters: partial });
    expect(out.ec.some((point) => point.value === null)).toBe(true);
    expect(
      out.ec.some((point) => point.value !== null && new Date(point.time).getUTCHours() < 10),
    ).toBe(true);
  });
  it("repeats continuous day/night references at local lights-on while keeping the floor separate", () => {
    const out = buildComparisonTarget(input);
    expect(
      out.vwc
        .filter((p) => p.value === 56 && new Date(p.time).getUTCHours() === 10)
        .map((p) => new Date(p.time).toISOString()),
    ).toEqual(["2026-08-01T10:00:00.000Z", "2026-08-02T10:00:00.000Z"]);
    expect(out.ec.some((p) => p.value === null)).toBe(false);
    expect(out.vwc.some((p) => p.value === null)).toBe(false);
    expect(out.floor.filter((p) => p.value !== null).every((p) => p.value === 38)).toBe(true);
    expect(out.vwc.every((p) => p.time >= input.start && p.time <= input.end)).toBe(true);
    expect(
      out.ec.filter((p) => p.value !== null).some((p) => new Date(p.time).getUTCHours() < 10),
    ).toBe(true);
  });
  it("includes the previous lights-on cycle when the selected day starts overnight", () => {
    const out = buildComparisonTarget({
      ...input,
      lightsOn: 20,
      lightsOff: 8,
      end: Date.parse("2026-08-02T00:00:00Z"),
    });
    expect(
      out.ec
        .filter((p) => p.value !== null)
        .some((p) => p.time === input.start && p.value! > 3.5 && p.value! < 4),
    ).toBe(true);
    expect(
      out.floor.filter((p) => p.value !== null).map((p) => new Date(p.time).getUTCHours()),
    ).toContain(8);
    expect(
      out.vwc.filter((p) => p.value !== null).some((p) => new Date(p.time).getUTCHours() === 20),
    ).toBe(true);
  });
  it("clips a current partial phase at now, interpolating only the illustration", () => {
    const now = Date.parse("2026-08-01T10:30:00Z");
    const out = buildComparisonTarget({ ...input, now });
    expect(Math.max(...out.vwc.map((p) => p.time))).toBe(now);
    expect(out.vwc.filter((p) => p.value !== null).at(-1)?.value).toBe(56);
    expect([...out.vwc, ...out.ec, ...out.floor].every((p) => p.time <= now)).toBe(true);
  });
  it("anchors consecutive cycles to wall-clock light hours over NZ spring DST", () => {
    const zone = "Pacific/Auckland",
      start = midnight("2026-09-26", zone),
      end = midnight("2026-09-29", zone);
    const out = buildComparisonTarget({
      ...input,
      timeZone: zone,
      runStartDate: "2026-09-26",
      start,
      end,
      now: end,
    });
    const anchors = out.vwc.filter(
      (p) =>
        p.value === 56 &&
        new Intl.DateTimeFormat("en-GB", {
          timeZone: zone,
          hour: "2-digit",
          minute: "2-digit",
          hourCycle: "h23",
        }).format(p.time) === "10:00",
    );
    expect(anchors.slice(0, 2).map((p) => new Date(p.time).toISOString())).toEqual([
      "2026-09-25T22:00:00.000Z",
      "2026-09-26T21:00:00.000Z",
    ]);
    expect((anchors[1].time - anchors[0].time) / 3600000).toBe(23);
    expect(anchors[1].age).toBe(ageAt(anchors[1].time, "2026-09-26", zone));
  });
  it("keeps the P0 wait in actual elapsed minutes across a DST clock jump", () => {
    const zone = "Pacific/Auckland",
      start = midnight("2026-09-27", zone),
      end = midnight("2026-09-28", zone);
    const out = buildComparisonTarget({
      ...input,
      timeZone: zone,
      lightsOn: 1.5,
      lightsOff: 13.5,
      runStartDate: "2026-09-27",
      start,
      end,
      now: end,
    });
    const p0Start = out.ec.find((p) => p.time === Date.parse("2026-09-26T13:30:00Z"))!;
    const p0End = out.ec.find((p) => p.time === Date.parse("2026-09-26T14:30:00Z"))!;
    expect(p0Start.value).toBe(3);
    expect(p0End.value).toBe(3.25);
    expect(p0End.time - p0Start.time).toBe(3600000);
  });
  it("preserves the 25-hour cycle on NZ autumn DST", () => {
    const zone = "Pacific/Auckland",
      start = midnight("2026-04-04", zone),
      end = midnight("2026-04-07", zone);
    const out = buildComparisonTarget({
      ...input,
      timeZone: zone,
      runStartDate: "2026-04-04",
      start,
      end,
      now: end,
    });
    const anchors = out.vwc.filter(
      (p) =>
        p.value === 56 &&
        new Intl.DateTimeFormat("en-GB", {
          timeZone: zone,
          hour: "2-digit",
          minute: "2-digit",
          hourCycle: "h23",
        }).format(p.time) === "10:00",
    );
    expect((anchors[1].time - anchors[0].time) / 3600000).toBe(25);
  });
  it("omits a nonexistent light-hour cycle rather than inventing an anchor", () => {
    const zone = "Pacific/Auckland",
      start = midnight("2026-09-27", zone),
      end = midnight("2026-09-28", zone);
    const out = buildComparisonTarget({
      ...input,
      timeZone: zone,
      lightsOn: 2.5,
      lightsOff: 14.5,
      runStartDate: "2026-09-27",
      start,
      end,
      now: end,
    });
    expect(out.warnings.some((w) => w.includes("does not exist"))).toBe(true);
    expect(out.vwc).toEqual([]);
  });
  it("does not fill missing EC/VWC or missing phase timing from defaults", () => {
    const empty = buildComparisonTarget({ ...input, parameters: {} });
    expect(empty.vwc).toEqual([]);
    expect(empty.ec).toEqual([]);
    expect(empty.floor).toEqual([]);
    const missing = buildComparisonTarget({
      ...input,
      parameters: { p1_target_vwc: 65, ec_target_p2: 4, p3_emergency_vwc_threshold: 38 },
    });
    expect(missing.vwc).toEqual([]);
    expect(missing.ec).toEqual([]);
    expect(missing.floor.length).toBeGreaterThan(0);
  });
  it.each([
    { lightsOn: NaN },
    { lightsOff: 10 },
    { lightsOn: 24 },
    { timeZone: "Not/A_Zone" },
    { runStartDate: "2026-02-30" },
  ])("rejects invalid timing %o with empty references", (invalid) => {
    const out = buildComparisonTarget({ ...input, ...invalid });
    expect(out.vwc).toEqual([]);
    expect(out.ec).toEqual([]);
    expect(out.floor).toEqual([]);
    expect(out.warnings.length).toBeGreaterThan(0);
  });
  it("bounds a complete 366-day run and refuses longer ranges", () => {
    const start = Date.parse("2024-01-01T00:00:00Z"),
      end = Date.parse("2025-01-01T00:00:00Z");
    const out = buildComparisonTarget({
      ...input,
      start,
      end,
      now: end,
      runStartDate: "2024-01-01",
    });
    const count = out.vwc.length + out.ec.length + out.floor.length;
    expect(count).toBeGreaterThan(3000);
    expect(count).toBeLessThan(30000);
    expect(
      buildComparisonTarget({ ...input, start, end: end + 86400000, now: end + 86400000 }).vwc,
    ).toEqual([]);
  });
});
