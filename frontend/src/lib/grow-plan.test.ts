import { describe, expect, it } from "vitest";
import {
  blockForDay,
  dateForDay,
  growDay,
  interpolate,
  parsePlanImport,
  planErrors,
  replaceRange,
} from "./grow-plan";
const profile = {
  id: "p",
  name: "Profile",
  vegetative: { p1_target_vwc: 70 },
  generative: { p1_target_vwc: 55 },
};
describe("grow planner", () => {
  it("splits a single day without changing neighboring weeks", () => {
    const blocks = replaceRange([{ start_day: 1, end_day: 28, profile_id: "p", bias: 20 }], {
      start_day: 8,
      end_day: 8,
      profile_id: "p",
      bias: 70,
    });
    expect(blocks.map((x) => [x.start_day, x.end_day, x.bias])).toEqual([
      [1, 7, 20],
      [8, 8, 70],
      [9, 28, 20],
    ]);
    expect(blockForDay({ zone_id: 1, start_date: "2026-09-01", schedule: blocks }, 9)?.bias).toBe(
      20,
    );
  });
  it("calculates calendar days across month and leap boundaries", () => {
    expect(dateForDay("2028-02-28", 3)).toBe("2028-03-01");
    expect(growDay("2026-09-30", "2026-10-01")).toBe(2);
  });
  it("interpolates real endpoints and respects discovered quantization", () => {
    expect(
      interpolate(profile, 50, {
        p1_target_vwc: { value: 65, min: 10, max: 90, step: 1, unit: "%", entity_ids: [] },
      }).p1_target_vwc,
    ).toBe(63);
    expect(interpolate(profile, 101)).toEqual({});
  });
  it("rejects overlaps, gaps, missing profiles and out-of-bounds targets", () => {
    const plan = {
      schema_version: 1 as const,
      profiles: [profile],
      zones: [
        {
          zone_id: 1,
          start_date: "2026-09-01",
          schedule: [{ start_day: 2, end_day: 9, profile_id: "p", bias: 50 }],
        },
      ],
    };
    expect(planErrors(plan, {}).join()).toContain("unscheduled gap");
    expect(planErrors(plan, {}).join()).toContain("limits");
  });
  it("accepts portable plans and rejects malformed imports", () => {
    expect(
      parsePlanImport(JSON.stringify({ schema_version: 1, profiles: [profile], zones: [] }))
        .profiles[0].id,
    ).toBe("p");
    expect(() => parsePlanImport('{"schema_version":2}')).toThrow();
    expect(() => parsePlanImport('{"schema_version":1,"profiles":[],"zones":[{}]}')).toThrow();
  });
});
