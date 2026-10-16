import { describe, expect, it } from "vitest";
import { dayDeltas } from "./day-deltas";
import type { DayTrace } from "./day-timeline";

const H = 3_600_000;
const START = Date.UTC(2026, 8, 28, 6);
const day = { start: START - 24 * H, lightsOff: START - 6 * H, end: START };
const yesterday: DayTrace = {
  day: day as DayTrace["day"],
  points: [
    { time: day.start + 0 * H, hour: 0, value: 25 },
    { time: day.start + 1 * H, hour: 1, value: 27 },
    { time: day.start + 2 * H, hour: 2, value: 29 },
    { time: day.start + 3 * H, hour: 3, value: 30 },
  ],
  shots: [{ start: day.start + 0.5 * H, end: day.start + 0.5 * H + 100_000, open: false, phase: "P1", reason: null }],
};

describe("day deltas", () => {
  it("compares VWC, the time the target was reached and the water, at this hour", () => {
    const chips = dayDeltas({
      points: [
        { time: START, value: 24 },
        { time: START + 1.5 * H, value: 28.5 },
        { time: START + 3 * H, value: 31 },
      ],
      shots: [{ start: START + 0.5 * H, end: START + 0.5 * H + 150_000, open: false, phase: "P1", reason: null }],
      start: START,
      now: START + 3 * H,
      compared: [yesterday],
      against: "yesterday",
      vwc: 31,
      target: 28,
    });
    expect(chips.map((c) => c.text)).toEqual([
      "VWC +1.0 pp vs yesterday",
      "Target 30 min earlier",
      "Water +50%",
    ]);
    expect(chips.map((c) => c.abnormal)).toEqual([false, false, true]);
  });
  it("says nothing without a day to compare with", () => {
    expect(
      dayDeltas({
        points: [],
        shots: [],
        start: START,
        now: START + H,
        compared: [],
        against: "yesterday",
        vwc: 30,
        target: 28,
      }),
    ).toEqual([]);
  });
});
