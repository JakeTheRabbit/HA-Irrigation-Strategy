import { describe, expect, it } from "vitest";
import { driverPoints, nights } from "./dryback-drivers";

const H = 3_600_000;
describe("dryback drivers", () => {
  it("finds the whole nights in a range", () => {
    expect(nights([0, 24 * H, 48 * H], 6, 0, 40 * H)).toEqual([
      { start: 0, end: 6 * H },
      { start: 24 * H, end: 30 * H },
    ]);
  });
  it("gives a zone's rate in pp/h against the driver's mean, and skips a night with a shot", () => {
    const times = [0, 2, 4, 6, 24, 26, 28, 30].map((h) => h * H);
    const vwc = [60, 59, 58, 57, 60, 59, 61, 58];
    const vpd = [1, 1.2, 1.4, 1.4, 1, 1, 1, 1];
    const list = [
      { start: 0, end: 6 * H },
      { start: 24 * H, end: 30 * H },
    ];
    const [point, ...rest] = driverPoints(2, times, vwc, vpd, list);
    expect(rest).toEqual([]);
    expect(point.zone).toBe(2);
    expect(point.y).toBeCloseTo(0.5, 6);
    expect(point.x).toBeCloseTo(1.25, 6);
  });
});
