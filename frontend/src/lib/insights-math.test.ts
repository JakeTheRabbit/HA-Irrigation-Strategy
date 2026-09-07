import { describe, it, expect } from "vitest";
import { calibrateDripper, previewShot } from "./insights-math";
describe("local irrigation calculations", () => {
  it("converts a measured per-dripper catch into L/hour", () => {
    expect(calibrateDripper(200, 3)).toBe(4);
    expect(calibrateDripper(100, 1)).toBe(6);
  });
  it("does not turn missing, non-positive or invalid measurements into a flow", () => {
    expect(calibrateDripper(0, 3)).toBeNull();
    expect(calibrateDripper(100, 0)).toBeNull();
    expect(calibrateDripper(NaN, 2)).toBeNull();
  });
  it("keeps substrate percentage, zone litres and emitter duration distinct", () => {
    const result = previewShot({
      substrateL: 6,
      plants: 36,
      drippersPerPlant: 2,
      flowLph: 4,
      shotPercent: 5,
    });
    expect(result).toMatchObject({
      zoneSubstrateL: 216,
      totalDrippers: 72,
      volumeL: 10.8,
      volumeMlPerPlant: 300,
    });
    expect(result!.durationSeconds).toBeCloseTo(135);
  });
  it("plant count scales zone volume but not duration with the same emitters per plant", () => {
    const a = previewShot({
      substrateL: 6,
      plants: 1,
      drippersPerPlant: 2,
      flowLph: 4,
      shotPercent: 5,
    })!;
    const b = previewShot({
      substrateL: 6,
      plants: 40,
      drippersPerPlant: 2,
      flowLph: 4,
      shotPercent: 5,
    })!;
    expect(b.volumeL).toBe(a.volumeL * 40);
    expect(b.durationSeconds).toBe(a.durationSeconds);
  });
  it("requires known positive hydraulic settings and whole counts", () => {
    expect(
      previewShot({ substrateL: 6, plants: 36, drippersPerPlant: 0, flowLph: 4, shotPercent: 5 }),
    ).toBeNull();
    expect(
      previewShot({ substrateL: 6, plants: 1.5, drippersPerPlant: 2, flowLph: 4, shotPercent: 5 }),
    ).toBeNull();
  });
});
