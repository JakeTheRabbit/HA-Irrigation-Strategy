import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { growPoints, growStats, yieldFigures, type GrowDay, type Harvest } from "./grows";
import type { RunRecord } from "./comparison-types";

const run = { start_date: "2026-01-01", end_date: "2026-01-02", zones: [{ zone_id: 1, plant_count: 10 }] } as RunRecord;
const day = (date: string, zone: number, litres: number): GrowDay => ({ date, zone, partial: false, backfilled: null,
  vwc: { peak: 60, trough: 50, mean: 55 }, ec: { min: 2, max: 4, mean: 3 }, litres,
  litres_per_plant: litres / 10, shots: { ramp: 2 }, rescues: 1 });

describe("grow comparison boundaries", () => {
  it("aligns dates by grow day and excludes other zones and days", () => {
    const rows = [day("2025-12-31", 1, 100), day("2026-01-01", 1, 10), day("2026-01-02", 1, 20), day("2026-01-02", 2, 90), day("2026-01-03", 1, 100)];
    expect(growPoints(run, rows, 1).map(p => p.day)).toEqual([1, 2]);
    const stats = growStats(run, rows, 1);
    expect(stats.litres).toBe(30);
    expect(stats.litresPerPlant).toBe(3);
    expect(stats.rescues).toBe(2);
  });
  it("keeps missing readings missing and computes yield from entered weights", () => {
    expect(growStats(run, [], 1).litres).toBeNull();
    const harvest = { room: { dry_weight_g: 2000, wet_weight_g: 10000, plants_harvested: 10, canopy_m2: 4 }, zones: {}, plants: [] } as unknown as Harvest;
    expect(yieldFigures(harvest, run, "room", 100)).toEqual({ dryG: 2000, wetG: 10000, gramsPerPlant: 200, gramsPerM2: 500, gramsPerLitre: 20, dryWetRatio: 0.2 });
    expect(yieldFigures(undefined, run, "room", 100).gramsPerLitre).toBeNull();
  });
});

describe("module graph", () => {
  it("grows.ts does not import comparison.ts, which imports it (no ESM cycle)", () => {
    const source = readFileSync(new URL("./grows.ts", import.meta.url), "utf8");
    expect(source).not.toMatch(/from "\.\/comparison"/);
  });
});
