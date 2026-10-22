import { describe, expect, it } from "vitest";
import { budgetShare, recentReadings } from "./dryback";

const now = Date.parse("2026-09-25T03:00:00Z");
const at = (minutesAgo: number) => new Date(now - minutesAgo * 60_000).toISOString();

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
