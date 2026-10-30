import { describe, expect, it } from "vitest";
import type { RunRecord } from "./comparison-types";
import { currentRun, feedToday } from "./run-progress";
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
