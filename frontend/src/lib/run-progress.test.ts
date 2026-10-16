import { describe, expect, it } from "vitest";
import type { RunRecord } from "./comparison-types";
import type { JevStage } from "./jev";
import type { StrategyDocument } from "./operator-types";
import { currentRun, feedToday, runProgress } from "./run-progress";
import type { EntityState } from "./types";

const run = (over: Partial<RunRecord> = {}): RunRecord => ({
  id: "r",
  room_id: "room:",
  name: "Run",
  start_date: "2026-10-01",
  end_date: null,
  time_zone: "UTC",
  archived: false,
  captured_at: "2026-10-01T00:00:00Z",
  reference_source: "",
  lights: { on: 6, off: 18 },
  zones: [],
  ...over,
});
const plan = (start = "2026-10-01", profiles = ["a"]): Pick<StrategyDocument, "plan"> => ({
  plan: {
    schema_version: 1,
    name: "Plan",
    profiles: profiles.map((id) => ({
      id,
      name: id.toUpperCase(),
      vegetative: {},
      generative: {},
    })),
    zones: [
      {
        zone_id: 2,
        start_date: start,
        schedule: [
          { start_day: 15, end_day: 35, profile_id: profiles.at(-1)!, bias: 70 },
          { start_day: 1, end_day: 14, profile_id: profiles[0], bias: 20 },
        ],
      },
    ],
  },
});
const stage = (day: number, days: number): JevStage => ({
  day,
  days,
  name: "flower bulk",
  steering: "vegetative",
  stageDays: null,
  peak: null,
  poreEc: null,
  drybackPoints: null,
  runoffPct: null,
});

describe("current run", () => {
  it("is the latest started run that is not archived and not ended before today", () => {
    const runs = [
      run({ id: "old", start_date: "2026-06-01", end_date: "2026-08-01" }),
      run({ id: "now", start_date: "2026-09-01" }),
      run({ id: "hidden", start_date: "2026-09-10", archived: true }),
      run({ id: "later", start_date: "2026-11-01" }),
    ];
    expect(currentRun(runs, "2026-10-01")?.id).toBe("now");
    expect(currentRun(runs.slice(0, 1), "2026-10-01")).toBeNull();
    // A run whose end date is still ahead runs today.
    expect(currentRun([run({ end_date: "2026-10-20" })], "2026-10-20")?.id).toBe("r");
  });
});

describe("run progress", () => {
  it("counts days done and left from the grow plan's schedule, today counted as left", () => {
    const view = runProgress({
      run: run(),
      today: "2026-10-15",
      plan: plan(),
      zoneIds: [1, 2],
      stage: null,
    });
    expect(view).toMatchObject({ day: 15, days: 35, done: 14, left: 21, end: "2026-11-04" });
    expect(view.endFrom).toBe("plan");
    expect(view.phasesFrom).toBe("plan");
    expect(view.phases.map((p) => [p.first, p.last, p.label, p.short])).toEqual([
      [1, 14, "20% generative", "20% G"],
      [15, 35, "70% generative", "70% G"],
    ]);
    expect(view.phase?.first).toBe(15);
  });
  it("names each phase's profile when the plan has more than one, and moves a plan that starts later", () => {
    const view = runProgress({
      run: run(),
      today: "2026-10-05",
      plan: plan("2026-10-03", ["veg", "flower"]),
      zoneIds: [2],
      stage: null,
    });
    expect(view.phases.map((p) => [p.first, p.last, p.label])).toEqual([
      [3, 16, "VEG, 20% generative"],
      [17, 37, "FLOWER, 70% generative"],
    ]);
    expect(view.days).toBe(37);
  });
  it("takes the run's own end date over the plan's last day", () => {
    const view = runProgress({
      run: run({ end_date: "2026-10-10" }),
      today: "2026-10-10",
      plan: plan(),
      zoneIds: [2],
      stage: null,
    });
    expect(view).toMatchObject({ day: 10, days: 10, done: 9, left: 1, endFrom: "run" });
  });
  it("puts the stage arc on the run without a plan, with veg before flower day 1", () => {
    // Run day 30 is flower day 16 of 56: flower day 1 is run day 15.
    const view = runProgress({
      run: run(),
      today: "2026-10-30",
      plan: null,
      zoneIds: [1],
      stage: stage(16, 56),
    });
    expect(view.phasesFrom).toBe("stage");
    expect(view.days).toBe(14 + 56);
    expect(view.phases[0]).toEqual({ first: 1, last: 14, label: "Veg", short: "Veg" });
    expect(view.phases.map((p) => p.short)).toEqual(["Veg", "Stretch", "Bulk", "Finish"]);
    expect(view.phases.at(-1)!.last).toBe(70);
    expect(view.phase?.short).toBe("Stretch");
  });
  it("has no length without an end date, a plan or a flower length", () => {
    const view = runProgress({
      run: run(),
      today: "2026-10-03",
      plan: null,
      zoneIds: [],
      stage: null,
    });
    expect(view).toMatchObject({ day: 3, days: null, end: null, done: 2, left: null, phases: [] });
  });
  it("stops counting at the last day of a run that goes past it", () => {
    const view = runProgress({
      run: run(),
      today: "2026-11-10",
      plan: plan(),
      zoneIds: [2],
      stage: null,
    });
    expect(view).toMatchObject({ day: 41, days: 35, done: 35, left: 0, phase: null });
  });
});

describe("feed today", () => {
  const entity = (attributes: Record<string, unknown>) =>
    ({ entity_id: "sensor.crop_steering_dosing_config", state: "1", attributes }) as EntityState;
  it("reads the feed schedule's pick, its week and its feed EC", () => {
    expect(
      feedToday(
        entity({
          feed: { recipe: "Bloom", ec: 2.4, week: 3, weeks: 12, source: "schedule" },
          batch: { name: "Old" },
        }),
      ),
    ).toEqual({ recipe: "Bloom", ec: 2.4, week: 3, weeks: 12, source: "schedule" });
  });
  it("falls back to the batch recipe's name, and to nothing", () => {
    expect(
      feedToday(
        entity({ feed: { recipe: null, week: null, source: "batch" }, batch: { name: "Week 3" } }),
      ),
    ).toEqual({ recipe: "Week 3", ec: null, week: null, weeks: null, source: "batch" });
    expect(feedToday(entity({ batch: { name: "" } }))).toBeNull();
    expect(feedToday(undefined)).toBeNull();
  });
});
