import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createDemo } from "./demo";
import { OperatorDemo } from "./operator-demo";
import { RunDemo, demoHistoryWindow } from "./comparison-demo";
import { buildComparisonTarget } from "./comparison-target";
import {
  addDays,
  ageAt,
  boundedRange,
  comparisonRange,
  dateInZone,
  daysBetween,
} from "./comparison";
import { discoverRooms } from "./model";
import {
  initializeDemoLibrary,
  libraryKey,
  readLibrary,
  saveRecipe,
  removeRecipe,
  prepareRecipeDraft,
} from "./recipe-library";
import type { GrowPlan, StrategyDocument } from "./operator-types";

const now = Date.parse("2026-09-08T01:00:00Z");
const timeZone = "Pacific/Auckland";
beforeEach(() => vi.spyOn(Date, "now").mockReturnValue(now));
afterEach(() => vi.restoreAllMocks());
class MemoryStorage {
  data = new Map<string, string>();
  writes = 0;
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.writes++;
    this.data.set(key, value);
  }
}
async function demoPlan(roomId = "room:") {
  const states = createDemo(now);
  const demo = new OperatorDemo(
    () => states,
    () => {},
  );
  return demo.call<StrategyDocument>("strategy_get", { room_id: roomId });
}
describe("isolated example recipes", () => {
  it("seeds two labelled valid examples atomically only into a new demo room key", async () => {
    const storage = new MemoryStorage();
    const doc = await demoPlan();
    const original = structuredClone(doc.plan);
    const scope = { roomId: "room:", demo: true };
    const seeded = initializeDemoLibrary(storage, scope, doc.plan, now);
    expect(storage.writes).toBe(1);
    expect(seeded.recipes.map((recipe) => recipe.name)).toEqual([
      "Demo • steady schedule",
      "Demo • week-by-week changes",
    ]);
    expect(doc.plan).toEqual(original);
    for (const recipe of seeded.recipes) {
      expect(recipe.notes).toMatch(/Synthetic interface example/);
      expect(recipe.sourceUrl).toBe("");
      const prepared = prepareRecipeDraft(recipe.plan, doc.plan, doc.catalog, [1, 2, 3]);
      expect(prepared.zones.map((zone) => zone.start_date)).toEqual(
        doc.plan.zones.map((zone) => zone.start_date),
      );
    }
    expect(seeded.recipes[0].plan.zones[0].schedule).toHaveLength(1);
    expect(seeded.recipes[1].plan.zones[0].schedule).toHaveLength(12);
    expect(
      new Set(seeded.recipes[1].plan.zones[0].schedule.map((block) => block.bias)).size,
    ).toBeGreaterThan(1);
    expect(readLibrary(storage, { ...scope, demo: false }).recipes).toEqual([]);
    expect(readLibrary(storage, { ...scope, roomId: "room:f1_" }).recipes).toEqual([]);
    const again = initializeDemoLibrary(storage, scope, {} as GrowPlan, now);
    expect(again.raw).toBe(seeded.raw);
    expect(storage.writes).toBe(1);
  });
  it("leaves live and previously saved demo libraries byte-for-byte untouched", async () => {
    const storage = new MemoryStorage();
    const doc = await demoPlan();
    for (const demo of [false, true]) {
      const scope = { roomId: "room:", demo };
      const saved = saveRecipe(storage, readLibrary(storage, scope), {
        name: "My existing plan",
        plan: doc.plan,
      });
      const writes = storage.writes;
      expect(initializeDemoLibrary(storage, scope, doc.plan, now).raw).toBe(saved.raw);
      expect(storage.writes).toBe(writes);
    }
    expect(
      initializeDemoLibrary(storage, { roomId: "room:new_", demo: false }, {} as GrowPlan).recipes,
    ).toEqual([]);
    expect(storage.getItem(libraryKey({ roomId: "room:new_", demo: false }))).toBeNull();
  });
  it("preserves deliberate empty libraries and corrupt stored data", async () => {
    const storage = new MemoryStorage();
    const doc = await demoPlan();
    const scope = { roomId: "room:", demo: true };
    let saved = initializeDemoLibrary(storage, scope, doc.plan, now);
    for (const recipe of saved.recipes) saved = removeRecipe(storage, saved, recipe.id);
    expect(initializeDemoLibrary(storage, scope, doc.plan, now).raw).toBe(saved.raw);
    expect(readLibrary(storage, scope).recipes).toEqual([]);
    storage.setItem(libraryKey(scope), "{broken");
    const writes = storage.writes;
    expect(initializeDemoLibrary(storage, scope, doc.plan, now).error).toBeTruthy();
    expect(storage.getItem(libraryKey(scope))).toBe("{broken");
    expect(storage.writes).toBe(writes);
  });
  it("preserves storage errors and rejects a concurrent write during initial seeding", async () => {
    const doc = await demoPlan();
    const scope = { roomId: "room:", demo: true };
    const blocked = {
      getItem() {
        throw new Error("blocked");
      },
      setItem() {
        throw new Error("must not write");
      },
    };
    expect(initializeDemoLibrary(blocked, scope, doc.plan, now).error).toMatch(/blocked/);
    let reads = 0,
      writes = 0;
    const concurrent = {
      getItem() {
        return reads++ ? "other-tab-data" : null;
      },
      setItem() {
        writes++;
      },
    };
    expect(() => initializeDemoLibrary(concurrent, scope, doc.plan, now)).toThrow(
      /changed in another tab/,
    );
    expect(writes).toBe(0);
  });
});
describe("synthetic current and previous run examples", () => {
  it("seeds bounded room-scoped current, previous and archived records without replacing later edits", () => {
    const states = createDemo(now),
      demo = new RunDemo(
        () => states,
        () => now,
      );
    const documents = discoverRooms(states).map((room) =>
      demo.call("runs_get", { room_id: room.id }),
    );
    for (const document of documents) {
      expect(document.runs).toHaveLength(3);
      const [current, previous, archived] = document.runs;
      expect(daysBetween(current.start_date, dateInZone(now, timeZone))).toBe(35);
      expect(daysBetween(previous.start_date, previous.end_date!)).toBe(55);
      expect(archived.archived).toBe(true);
      expect(
        document.runs.every(
          (run) => run.name.startsWith("Demo •") && run.reference_source.includes("Synthetic"),
        ),
      ).toBe(true);
      expect(new Set(document.runs.map((run) => run.room_id))).toEqual(new Set([document.room_id]));
      const prefix = document.room_id === "room:" ? "" : "f1_";
      expect(current.zones[0].vwc_sensor).toBe(`sensor.crop_steering_${prefix}vwc_zone_1`);
      expect(current.lights.on).toBe(prefix ? 8 : 10);
      demo.call("runs_archive", {
        room_id: document.room_id,
        expected_revision: 0,
        id: current.id,
        archived: true,
      });
      expect(demo.call("runs_get", { room_id: document.room_id }).runs[0].archived).toBe(true);
    }
    expect(documents[0].runs[0].id).not.toBe(documents[1].runs[0].id);
    const reset = new RunDemo(
      () => createDemo(now),
      () => now,
    );
    expect(reset.call("runs_get", { room_id: "room:" }).runs[0].archived).toBe(false);
  });
  it.each(["day", "week", "month", "run"])(
    "provides measured and reference example curves for %s at matched grow age",
    async (period) => {
      const states = createDemo(now),
        demo = new RunDemo(
          () => states,
          () => now,
        );
      const [current, previous] = demo.call("runs_get", { room_id: "room:" }).runs;
      const today = dateInZone(now, timeZone);
      const first =
        period === "day"
          ? today
          : period === "week"
            ? addDays(today, -6)
            : period === "month"
              ? today.slice(0, 8) + "01"
              : current.start_date;
      const range = boundedRange(first, today, timeZone, now);
      const comparator = comparisonRange(current, previous, range.start, range.end, now)!;
      expect(ageAt(comparator.end, previous.start_date, timeZone)).toBeCloseTo(
        ageAt(range.end, current.start_date, timeZone),
      );
      for (const bounds of [range, comparator]) {
        const history = await demoHistoryWindow({
          entityIds: [current.zones[0].vwc_sensor!, current.zones[0].ec_sensor!],
          start: new Date(bounds.start).toISOString(),
          end: new Date(bounds.end).toISOString(),
          timeZone,
        });
        expect(history.warnings[0]).toMatch(/generated example data/);
        for (const series of history.series) {
          expect(series.points.length).toBeLessThanOrEqual(1600);
          expect(series.points.filter((point) => point.value !== null).length).toBeGreaterThan(1);
          expect(series.daily.length).toBeGreaterThan(0);
          expect(series.points.every((point) => point.time < bounds.end)).toBe(true);
        }
      }
      const reference = buildComparisonTarget({
        parameters: current.zones[0].parameters,
        lightsOn: current.lights.on!,
        lightsOff: current.lights.off!,
        start: range.start,
        end: range.end,
        now,
        timeZone,
        runStartDate: current.start_date,
      });
      expect(reference.vwc.filter((point) => point.value !== null).length).toBeGreaterThan(1);
      expect(reference.ec.filter((point) => point.value !== null).length).toBeGreaterThan(1);
    },
  );
  it("uses distinct synthetic readings for the two rooms and demonstrates explicit gaps", async () => {
    const ids = ["sensor.crop_steering_vwc_zone_1", "sensor.crop_steering_f1_vwc_zone_1"];
    const history = await demoHistoryWindow({
      entityIds: ids,
      start: new Date(now - 30 * 86400_000).toISOString(),
      end: new Date(now).toISOString(),
      timeZone,
    });
    expect(history.series[0].points[0].value).not.toBe(history.series[1].points[0].value);
    expect(
      history.series.every((series) => series.points.some((point) => point.value === null)),
    ).toBe(true);
  });
});
