import { describe, expect, it } from "vitest";
import { syncPlanZones } from "./sync-plan-zones";
import type { GrowPlan, ParameterLimit } from "./operator-types";
const plan: GrowPlan = {
  schema_version: 1,
  profiles: [
    {
      id: "zone-1-current",
      name: "Existing",
      vegetative: { p1_target_vwc: 64 },
      generative: { p1_target_vwc: 60 },
    },
  ],
  zones: [
    {
      zone_id: 1,
      start_date: "2026-09-01",
      schedule: [{ start_day: 1, end_day: 35, profile_id: "zone-1-current", bias: 75 }],
    },
  ],
};
const field = (value: number | null): ParameterLimit => ({
  value,
  min: 0,
  max: 100,
  step: 1,
  unit: "%",
  entity_ids: [],
});
describe("explicit local plan zone reconciliation", () => {
  it("preserves existing schedules and seeds added zones from finite catalog values at both endpoints", () => {
    const before = structuredClone(plan);
    const result = syncPlanZones(
      plan,
      [1, 4],
      { "4": { p1_target_vwc: field(67), p2_vwc_threshold: field(null) } },
      "2026-09-08",
    );
    expect(result.plan.zones[0]).toEqual(plan.zones[0]);
    expect(result.plan.profiles[0]).toEqual(plan.profiles[0]);
    expect(plan).toEqual(before);
    const added = result.plan.zones.find((z) => z.zone_id === 4)!;
    expect(added.start_date).toBe("2026-09-08");
    expect(added.schedule[0]).toMatchObject({ start_day: 1, end_day: 84, bias: 50 });
    const profile = result.plan.profiles.find((p) => p.id === added.schedule[0].profile_id)!;
    expect(profile.vegetative).toEqual({ p1_target_vwc: 67 });
    expect(profile.generative).toEqual(profile.vegetative);
    expect(result.added).toEqual([4]);
  });
  it("removes archived assignments while retaining profiles for export and creates unique profile IDs on restoration", () => {
    const archived = syncPlanZones(plan, [], {}, "2026-09-08");
    expect(archived.plan.zones).toEqual([]);
    expect(archived.plan.profiles).toEqual(plan.profiles);
    expect(archived.removed).toEqual([1]);
    const restored = syncPlanZones(
      archived.plan,
      [1],
      { "1": { p1_target_vwc: field(66) } },
      "2026-09-08",
    );
    expect(restored.plan.profiles.map((p) => p.id)).toEqual(["zone-1-current", "zone-1-current-2"]);
  });
  it("does not invent endpoints when catalog values are unavailable", () => {
    const result = syncPlanZones(plan, [1, 2], {}, "2026-09-08");
    expect(result.unseeded).toEqual([2]);
    expect(result.plan.profiles.at(-1)?.vegetative).toEqual({});
    expect(result.plan.profiles.at(-1)?.generative).toEqual({});
  });
});
