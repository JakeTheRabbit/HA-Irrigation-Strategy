import { describe, expect, it } from "vitest";
import {
  athenaDryback,
  axisRange,
  bandStatus,
  CHART_LAYERS,
  parseChartPrefs,
  dayScales,
  EC_AXIS,
  hourTicks,
  overnightDryback,
  phaseColumns,
  placeBadges,
  placeMarkers,
  rangeText,
  runoffBand,
  smoothPath,
  steeringOf,
  valueAtTime,
  VWC_AXIS,
} from "./day-chart";

const H = 3_600_000;

describe("today's stage", () => {
  it("steers as the zone's select says, else as the stage does", () => {
    expect(steeringOf("Vegetative", "generative")).toBe("vegetative");
    expect(steeringOf("Generative", null)).toBe("generative");
    expect(steeringOf("unavailable", "vegetative")).toBe("vegetative");
    expect(steeringOf(undefined, "generative")).toBe("generative");
    // The finish ripens with a generative dryback, its peak at or under field capacity.
    expect(steeringOf(null, "ripening")).toBe("generative");
    expect(steeringOf(null, null)).toBeNull();
    expect(steeringOf("Balanced", "something new")).toBeNull();
  });
  it("finds Athena's relative overnight dryback for the stage the controller names", () => {
    expect(athenaDryback("flower setting")).toEqual([40, 50]);
    expect(athenaDryback("Flower stretch")).toEqual([40, 50]);
    expect(athenaDryback("flower bulk")).toEqual([30, 40]);
    expect(athenaDryback("finish")).toEqual([40, 50]);
    expect(athenaDryback("established veg")).toEqual([25, 25]);
    expect(athenaDryback(null)).toBeNull();
    expect(athenaDryback("clone")).toBeNull();
  });
  it("says a range the short way", () => {
    expect(rangeText([3.5, 6])).toBe("3.5–6");
    expect(rangeText([30, 40], 0)).toBe("30–40");
    expect(rangeText([25, 25], 0)).toBe("25");
  });
  it("places a reading against the pore EC band", () => {
    expect(bandStatus(2.8, [3.5, 6])).toBe("below");
    expect(bandStatus(3.5, [3.5, 6])).toBe("in");
    expect(bandStatus(6.2, [3.5, 6])).toBe("above");
    expect(bandStatus(null, [3.5, 6])).toBeNull();
    expect(bandStatus(4, null)).toBeNull();
    expect(bandStatus(NaN, [3.5, 6])).toBeNull();
  });
});

describe("the VWC axis", () => {
  it("sits tight on the data and its targets, with gridlines every five points", () => {
    // A day between 28 and 37 % with a peak target of 36.5, a re-water at 30.5 and the rescue
    // floor at 20.7: never 14-91 %.
    const axis = axisRange([28, 31, 37], [36.5, 30.5, 20.7], VWC_AXIS)!;
    expect(axis.min).toBeCloseTo(18.7);
    expect(axis.max).toBeCloseTo(39);
    expect(axis.ticks).toEqual([20, 25, 30, 35]);
    expect(axis.step).toBe(5);
  });
  it("leaves a far-off reference off the axis instead of flattening the line", () => {
    const axis = axisRange([30, 38], [91, 14.6], VWC_AXIS)!;
    expect(axis.min).toBe(28);
    expect(axis.max).toBe(40);
    expect(axis.ticks).toEqual([30, 35, 40]);
  });
  it("draws a flat day on a sane minimum span, with finer gridlines", () => {
    const axis = axisRange([50.2, 50.4], [], VWC_AXIS)!;
    expect(axis.max - axis.min).toBeCloseTo(8);
    expect(axis.step).toBe(2);
    expect(axis.ticks).toEqual([48, 50, 52, 54]);
  });
  it("stays within 0 and 100 %", () => {
    expect(axisRange([0.5, 3], [], VWC_AXIS)!.min).toBe(0);
    expect(axisRange([97, 99.5], [], VWC_AXIS)!.max).toBe(100);
  });
  it("draws the references alone when there are no readings, and nothing without either", () => {
    expect(axisRange([], [40, 44], VWC_AXIS)).toMatchObject({ min: 38, max: 46 });
    expect(axisRange([], [], VWC_AXIS)).toBeNull();
    expect(axisRange([NaN], [null, undefined], VWC_AXIS)).toBeNull();
  });
  it("puts pore EC on its own axis around the readings and the stage's band", () => {
    const axis = axisRange([2.8, 3.3], [3.5, 6], EC_AXIS)!;
    expect(axis.min).toBeCloseTo(2.4);
    expect(axis.max).toBeCloseTo(6.4);
    expect(axis.ticks).toEqual([3, 4, 5, 6]);
    expect(axis.ticks.length).toBeLessThanOrEqual(5);
  });
});

describe("a zone's day scales", () => {
  // The owner's zone 3 at 02:10: today between 36 and 42 %, field capacity 43, the maintenance band
  // 38-40, the rescue floor 22; yesterday spiked to 78 % after a flush.
  const zone3 = {
    today: [36.4, 38, 41.8, 40.2, 36.3],
    projection: [36.1, 35.8],
    targets: [43, 38, 40, 22],
    ec: [3.9, 4.1, 4],
    ecBand: [3.5, 6] as [number, number],
  };
  it("fits today's readings and the zone's own targets, not yesterday's spike", () => {
    const { vwc } = dayScales(zone3);
    expect(vwc!.max).toBeLessThanOrEqual(46);
    expect(vwc!.min).toBeGreaterThanOrEqual(19);
    // Yesterday is not part of the scale at all: the same day with a 78 % yesterday draws the same.
    expect(Math.max(...vwc!.ticks)).toBeLessThan(50);
    expect(vwc!.ticks).toContain(40);
  });
  it("leaves a target far off today's readings off the scale", () => {
    const { vwc } = dayScales({ ...zone3, targets: [43, 38, 40, 10] });
    expect(vwc!.min).toBeGreaterThan(30);
  });
  it("puts pore EC on its own scale around the stage's band", () => {
    const { ec } = dayScales(zone3);
    expect(ec!.min).toBeLessThanOrEqual(3.5);
    expect(ec!.max).toBeGreaterThanOrEqual(6);
  });
  it("draws the runoff zone as a thin band beside field capacity", () => {
    expect(runoffBand(43, "vegetative")).toEqual([43, 46]);
    expect(runoffBand(43, "generative")).toEqual([40, 43]);
  });
});

describe("markers and badges", () => {
  it("puts each Jev decision on the first row that clears the one before", () => {
    const placed = placeMarkers(
      [
        { x: 10, item: "a" },
        { x: 14, item: "b" },
        { x: 40, item: "c" },
        { x: 18, item: "d" },
      ],
      10,
      2,
    );
    // No row left for "d": it shares the nearest mark, "b"'s.
    expect(placed.map(({ x, row, items }) => [x, row, items])).toEqual([
      [10, 0, ["a"]],
      [14, 1, ["b", "d"]],
      [40, 0, ["c"]],
    ]);
  });
  it("on one row, decisions too close to tell apart share one mark", () => {
    const placed = placeMarkers(
      [0, 5, 11, 30].map((x) => ({ x, item: x })),
      12,
      1,
    );
    expect(placed.map((marker) => marker.items)).toEqual([[0, 5, 11], [30]]);
    expect(placeMarkers([], 12, 1)).toEqual([]);
  });
  it("pushes a narrow phase's badge beside the one before it rather than dropping it", () => {
    // P0 and P1 are narrow early in the day; P2 and P3 have room.
    expect(placeBadges([45, 55, 150, 260], 18, 3, 36, 300)).toEqual([45, 66, 150, 260]);
    // The first stays inside the chart, and the last comes back in from its edge.
    expect(placeBadges([30, 290, 296], 18, 3, 36, 300)).toEqual([45, 270, 291]);
  });
});

describe("overnight dryback", () => {
  const off = 22 * H,
    end = 34 * H;
  const night = [
    { time: 19 * H, value: 70 }, // before the window: not the evening peak
    { time: 20.5 * H, value: 64 },
    { time: 21.5 * H, value: 62 },
    { time: 23 * H, value: 58 },
    { time: 28 * H, value: 51.2 },
    { time: 33.9 * H, value: 49.6 },
    { time: 35 * H, value: 44 }, // after lights-on: the next day
  ];
  it("is relative to the evening peak, as Athena's targets are", () => {
    const dryback = overnightDryback(night, off, end, 36 * H)!;
    expect(dryback.peak).toBe(64);
    expect(dryback.low).toBe(49.6);
    expect(dryback.drop).toBeCloseTo(14.4);
    expect(dryback.percent).toBeCloseTo(22.5);
    expect(dryback.complete).toBe(true);
  });
  it("so far, while the night is still on", () => {
    const dryback = overnightDryback(night, off, end, 28.5 * H)!;
    expect(dryback.low).toBe(51.2);
    expect(dryback.percent).toBeCloseTo(20);
    expect(dryback.complete).toBe(false);
  });
  it("needs readings on both sides of lights-off", () => {
    expect(overnightDryback(night.slice(0, 3), off, end, 30 * H)).toBeNull();
    expect(overnightDryback(night.slice(3), off, end, 30 * H)).toBeNull();
    expect(overnightDryback([], off, end, 30 * H)).toBeNull();
  });
});

describe("phase columns", () => {
  const band = (phase: string, start: number, end: number) => ({
    phase,
    start: start * H,
    end: end * H,
  });
  it("joins what was recorded with what is expected, the current phase as one column", () => {
    const columns = phaseColumns(
      [band("P0", 0, 1.5), band("P1", 1.5, 3.5), band("P2", 3.5, 6)],
      [band("P2", 6, 12), band("P3", 12, 24)],
      6 * H,
      30 * 60_000,
    );
    expect(
      columns.map((column) => [column.phase, column.start / H, column.end / H, column.future]),
    ).toEqual([
      ["P0", 0, 1.5, false],
      ["P1", 1.5, 3.5, false],
      ["P2", 3.5, 12, false],
      ["P3", 12, 24, true],
    ]);
  });
  it("folds the minute of P3 a day starts with into the phase after it", () => {
    const columns = phaseColumns(
      [band("P3", 0, 0.02), band("P0", 0.02, 1.5), band("P1", 1.5, 2)],
      [],
      2 * H,
      30 * 60_000,
    );
    expect(columns.map((column) => [column.phase, column.start / H])).toEqual([
      ["P0", 0],
      ["P1", 1.5],
    ]);
  });
  it("keeps a gap where no phase was recorded", () => {
    const columns = phaseColumns([band("P1", 1, 3), band("P2", 5, 6)], [], 6 * H, 30 * 60_000);
    expect(columns.map((column) => [column.phase, column.start / H, column.end / H])).toEqual([
      ["P1", 1, 3],
      ["P2", 5, 6],
    ]);
  });
});

describe("the clock and the lines", () => {
  it("ticks every few hours from lights-on, as far apart as a label needs", () => {
    const start = Date.UTC(2026, 8, 28, 10);
    expect(hourTicks(start, start + 24 * H, 290, 52).map((tick) => (tick - start) / H)).toEqual([
      0, 6, 12, 18,
    ]);
    expect(hourTicks(start, start + 24 * H, 1000, 52).map((tick) => (tick - start) / H)).toEqual([
      0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22,
    ]);
  });
  it("reads between readings close together, and not across a gap", () => {
    const points = [
      { time: 0, value: 10 },
      { time: 10 * 60_000, value: 20 },
      { time: 3 * H, value: 40 },
    ];
    expect(valueAtTime(points, 5 * 60_000)).toBe(15);
    expect(valueAtTime(points, H)).toBeNull();
    expect(valueAtTime(points, 3 * H + 60_000)).toBe(40);
    expect(valueAtTime(points, H, 4 * H)).toBeCloseTo(20 + (20 * 50) / 170);
  });
  it("draws pore EC as a smooth line, broken where readings stop", () => {
    const d = smoothPath(
      [
        { time: 0, value: 1 },
        { time: 10, value: 2 },
        { time: 20, value: 1 },
        { time: 100, value: 3 },
      ],
      (time) => time,
      (value) => value * 10,
      50,
    );
    expect(d.match(/M/g)).toHaveLength(2);
    expect(d.match(/C/g)).toHaveLength(2);
    expect(d.startsWith("M0.0 10.0C")).toBe(true);
  });
});

describe("the chart's choices remembered in a browser", () => {
  it("defaults: yesterday, every layer, readings under the chart", () => {
    for (const stored of [null, "", "not json", "null", "42", '"text"', "[]"])
      expect(parseChartPrefs(stored)).toEqual({ compare: "yesterday", hidden: [], readout: "below" });
  });
  it("keeps what was chosen, drops what it does not know", () => {
    expect(
      parseChartPrefs(
        JSON.stringify({ compare: "typical", hidden: ["ec", "jev", "nonsense", 7], readout: "over" }),
      ),
    ).toEqual({ compare: "typical", hidden: ["ec", "jev"], readout: "over" });
    // An older browser stored the comparison alone.
    expect(parseChartPrefs(JSON.stringify({ compare: "none" }))).toEqual({
      compare: "none",
      hidden: [],
      readout: "below",
    });
    expect(parseChartPrefs(JSON.stringify({ hidden: "ec", readout: "sideways" }))).toEqual({
      compare: "yesterday",
      hidden: [],
      readout: "below",
    });
  });
  it("every key entry is a layer that can be switched off, in the key's order", () => {
    expect(parseChartPrefs(JSON.stringify({ hidden: [...CHART_LAYERS].reverse() })).hidden).toEqual([
      ...CHART_LAYERS,
    ]);
  });
});
