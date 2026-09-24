import { describe, expect, it } from "vitest";
import type { ScheduleBlock } from "./operator-types";
import {
  blockForDay,
  columnRange,
  dateForDay,
  growDay,
  interpolate,
  parseBalance,
  parsePlanImport,
  planErrors,
  rangeBlock,
  replaceRange,
  setpointRows,
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
  it("sets exactly the edited range and rejoins neighbours it now matches", () => {
    const spans = (blocks: ScheduleBlock[]) =>
      blocks.map((b) => [b.start_day, b.end_day, b.profile_id, b.bias]);
    const blocks = [
      { start_day: 1, end_day: 14, profile_id: "p", bias: 20 },
      { start_day: 15, end_day: 35, profile_id: "p", bias: 70 },
      { start_day: 36, end_day: 63, profile_id: "p", bias: 40 },
    ];
    const week = (bias: number, profile_id = "p") => ({
      start_day: 15,
      end_day: 21,
      profile_id,
      bias,
    });
    expect(spans(replaceRange(blocks, week(20)))).toEqual([
      [1, 21, "p", 20],
      [22, 35, "p", 70],
      [36, 63, "p", 40],
    ]);
    // Re-entering the balance a block already has leaves it whole.
    expect(spans(replaceRange(blocks, week(70)))).toEqual(spans(blocks));
    // Another profile is a different block even at the same balance.
    expect(spans(replaceRange(blocks, week(20, "q")))).toEqual([
      [1, 14, "p", 20],
      [15, 21, "q", 20],
      [22, 35, "p", 70],
      [36, 63, "p", 40],
    ]);
    const between = [
      { start_day: 1, end_day: 7, profile_id: "p", bias: 20 },
      { start_day: 8, end_day: 14, profile_id: "p", bias: 70 },
      { start_day: 15, end_day: 21, profile_id: "p", bias: 20 },
    ];
    expect(
      spans(replaceRange(between, { start_day: 8, end_day: 14, profile_id: "p", bias: 20 })),
    ).toEqual([[1, 21, "p", 20]]);
  });
  it("treats a week with a block boundary inside it as mixed, and one entry sets all seven days", () => {
    const schedule = [
      { start_day: 1, end_day: 14, profile_id: "p", bias: 20 },
      { start_day: 15, end_day: 15, profile_id: "p", bias: 70 },
      { start_day: 16, end_day: 16, profile_id: "p", bias: 90 },
      { start_day: 17, end_day: 35, profile_id: "p", bias: 70 },
    ];
    const zone = { zone_id: 1, start_date: "2026-09-01", schedule };
    const week3 = columnRange("week", 2);
    expect(week3).toEqual({ start: 15, end: 21 });
    expect(rangeBlock(zone, week3.start, week3.end)).toEqual({ block: schedule[1], mixed: true });
    expect(rangeBlock(zone, 22, 28)).toEqual({ block: schedule[3], mixed: false });
    expect(rangeBlock(zone, 36, 42)).toEqual({ block: undefined, mixed: false });
    expect(
      replaceRange(schedule, {
        start_day: week3.start,
        end_day: week3.end,
        profile_id: "p",
        bias: 45,
      }).map((b) => [b.start_day, b.end_day, b.bias]),
    ).toEqual([
      [1, 14, 20],
      [15, 21, 45],
      [22, 35, 70],
    ]);
    expect(columnRange("day", 15)).toEqual({ start: 16, end: 16 });
    expect(columnRange("week", 52)).toEqual({ start: 365, end: 366 });
  });
  it("accepts a whole-number balance and says why anything else is rejected", () => {
    expect(parseBalance("45")).toEqual({ value: 45 });
    expect(parseBalance(" 100 % ")).toEqual({ value: 100 });
    expect(parseBalance("0")).toEqual({ value: 0 });
    expect(parseBalance("45.0")).toEqual({ value: 45 });
    for (const text of ["", " ", "abc", "4e1", "+5", "50%%", "5 0"])
      expect(parseBalance(text)).toEqual({ error: "Enter a whole number from 0 to 100." });
    expect(parseBalance("45.5")).toEqual({
      error: "Use a whole number from 0 to 100, no decimals.",
    });
    expect(parseBalance("101")).toEqual({ error: "101 is outside 0–100." });
    expect(parseBalance("-1")).toEqual({ error: "-1 is outside 0–100." });
  });
  it("lists every blended setpoint with explicit units, from the same interpolation", () => {
    const both = {
      id: "b",
      name: "Both",
      vegetative: {
        dryback_target: 8,
        p1_target_vwc: 64,
        ec_target_p2: 3,
        p2_shot_size: 4,
        max_daily_volume: 20,
        p1_maximum_shots: 8,
      },
      generative: {
        dryback_target: 12,
        p1_target_vwc: 60,
        ec_target_p2: 4,
        p2_shot_size: 3,
        max_daily_volume: 20,
        p1_maximum_shots: 8,
      },
    };
    const limit = (step: number, unit: string) => ({
      value: null,
      min: 0,
      max: 100,
      step,
      unit,
      entity_ids: [],
    });
    const catalog = {
      p1_target_vwc: limit(0.5, "%"),
      p2_vwc_threshold: limit(0.5, "%"),
      dryback_target: limit(0.5, "% of peak"),
      ec_target_p2: limit(0.1, "mS/cm"),
      max_daily_volume: limit(0.5, "L"),
    };
    const rows = setpointRows(both, 45, catalog, 70);
    // Catalog order first, then keys only the profile has; a catalog key it lacks is skipped.
    expect(rows.map((r) => [r.key, r.unit])).toEqual([
      ["p1_target_vwc", "% VWC"],
      ["dryback_target", "% of peak"],
      ["ec_target_p2", "mS/cm"],
      ["max_daily_volume", "L"],
      ["p2_shot_size", "% of substrate"],
      ["p1_maximum_shots", "shots"],
    ]);
    const typed = interpolate(both, 45, catalog),
      saved = interpolate(both, 70, catalog);
    for (const row of rows) {
      expect(row.value).toBe(typed[row.key]);
      expect(row.now).toBe(saved[row.key]);
    }
    expect(rows[0]).toMatchObject({
      label: "P1 moisture target",
      vegetative: 64,
      generative: 60,
      value: 62,
      now: 61,
    });
    expect(setpointRows(both, null, catalog).every((r) => r.value === undefined)).toBe(true);
    expect(setpointRows(undefined, 50, catalog)).toEqual([]);
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
