import { describe, expect, it } from "vitest";
import { budgetShare, drybackTrend, recentReadings } from "./dryback";

const now = Date.parse("2026-09-25T03:00:00Z");
const at = (minutesAgo: number) => new Date(now - minutesAgo * 60_000).toISOString();
/** A reading every 5 minutes from `from` minutes ago, `perHour` points lost per hour. */
const drying = (from: number, start: number, perHour: number) =>
  Array.from({ length: from / 5 + 1 }, (_, i) => ({
    time: at(from - i * 5),
    value: start - (perHour * (i * 5)) / 60,
  }));

describe("drybackTrend", () => {
  it("measures points per hour over the last two hours when no shot fell in them", () => {
    const trend = drybackTrend(drying(180, 40, 0.8), null, null, now);
    expect(trend.rate).toBeCloseTo(0.8, 6);
    expect(trend.reason).toBeNull();
    expect(trend.recent[0].time).toBe(now - 2 * 3_600_000);
  });

  it("ignores the wet-up: only readings from five minutes after the last shot count", () => {
    // Drying at 0.5 until a shot 40 minutes ago lifts it 6 points; since then 1.2 an hour.
    const before = drying(180, 40, 0.5).filter((p) => Date.parse(p.time) < now - 40 * 60_000);
    const after = Array.from({ length: 9 }, (_, i) => ({
      time: at(40 - i * 5),
      value: 45 - (1.2 * (i * 5)) / 60,
    }));
    const trend = drybackTrend([...before, ...after], at(40), null, now);
    expect(trend.rate).toBeCloseTo(1.2, 6);
    // The sparkline still shows the whole window, shot included.
    expect(trend.recent.length).toBeGreaterThan(after.length);
  });

  it("carries the held value in and closes the window with the live reading", () => {
    // The recorder only stores changes: one reading 3 h ago, nothing since, live 38.
    const trend = drybackTrend([{ time: at(180), value: 40 }], null, 38, now);
    expect(trend.recent.map((p) => p.value)).toEqual([40, 38]);
    expect(trend.rate).toBeCloseTo(1, 6);
  });

  it("says why when the last shot was too recent to measure", () => {
    const trend = drybackTrend(drying(60, 40, 1), at(12), 39, now);
    expect(trend.rate).toBeNull();
    expect(trend.reason).toMatch(/12 minutes ago/);
  });

  it("reports a rising line as a negative rate", () => {
    const trend = drybackTrend(drying(60, 30, -2), null, null, now);
    expect(trend.rate).toBeCloseTo(-2, 6);
  });

  it("has no rate without history, and no -0 for a flat line", () => {
    expect(drybackTrend([], null, 40, now).rate).toBeNull();
    expect(drybackTrend([], null, 40, now).reason).toMatch(/No moisture history/);
    expect(Object.is(drybackTrend(drying(60, 40, 0), null, null, now).rate, 0)).toBe(true);
  });
});

describe("recentReadings", () => {
  it("keeps the window, carries the held value in and ends at the live reading", () => {
    const history = [
      { time: at(500), value: 1 },
      { time: at(400), value: 2 },
      { time: at(120), value: 3 },
      { time: "not a time", value: 9 },
    ];
    expect(recentReadings(history, 6, 4, now)).toEqual([
      { time: now - 6 * 3_600_000, value: 2 },
      { time: now - 120 * 60_000, value: 3 },
      { time: now, value: 4 },
    ]);
    // Without a live reading the line ends at the last recorded one.
    expect(recentReadings(history, 1, null, now)).toEqual([{ time: now - 3_600_000, value: 3 }]);
  });
});

describe("budgetShare", () => {
  it("is the share of the daily limit, and null without a usable limit", () => {
    expect(budgetShare(59.4, 120)).toBeCloseTo(49.5, 6);
    expect(budgetShare(130, 120)).toBeCloseTo(108.33, 2);
    expect(budgetShare(10, null)).toBeNull();
    expect(budgetShare(null, 120)).toBeNull();
    expect(budgetShare(10, 0)).toBeNull();
  });
});
