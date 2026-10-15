import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { joinRows } from "./day-timeline";
import { createDemo, demoClock, demoDay } from "./demo";
import { OperatorDemo } from "./operator-demo";
import { RunDemo, demoHistoryWindow, demoTimeZone } from "./comparison-demo";
import { buildComparisonTarget } from "./comparison-target";
import {
  addDays,
  ageAt,
  boundedRange,
  comparisonRange,
  dateInZone,
  daysBetween,
} from "./comparison";
import { buildRoom, discoverRooms } from "./model";
import {
  initializeDemoLibrary,
  libraryKey,
  readLibrary,
  saveRecipe,
  removeRecipe,
  prepareRecipeDraft,
} from "./recipe-library";
import type { GrowPlan, StrategyDocument } from "./operator-types";
import { recordWindows, tankEntities, tankRecord } from "./tank-level";

const now = Date.parse("2026-09-08T01:00:00Z");
const timeZone = demoTimeZone();
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
describe("the demo keeps the clock", () => {
  const at = (hour: number) => new Date(2026, 8, 28, hour, 0).getTime();
  const phases = (states: ReturnType<typeof createDemo>) =>
    [1, 2, 3].map((zone) => states[`sensor.crop_steering_zone_${zone}_phase`].state);
  it("puts every zone in P3 with nothing firing from lights-off to lights-on, and back by day", () => {
    const night = demoClock(createDemo(at(2)), at(2));
    expect(phases(night)).toEqual(["P3", "P3", "P3"]);
    expect(night["sensor.crop_steering_current_decision"].attributes.fired).toEqual([]);
    expect(night["switch.demo_valve_1"].state).toBe("off");
    expect(night["sensor.crop_steering_zone_1_waiting_for_app"].state).toBe("P3");
    // Flower 1's lights run 8-20, so at 21:00 it is night there and still evening in Flower 2.
    const evening = demoClock(createDemo(at(21)), at(21));
    expect(evening["sensor.crop_steering_f1_zone_1_phase"].state).toBe("P3");
    expect(phases(evening)).toEqual(["P1", "P2", "P2"]);
    const day = demoClock(night, at(16));
    expect(phases(day)).toEqual(["P1", "P2", "P2"]);
    expect(day["sensor.crop_steering_current_decision"].attributes.fired).toEqual([
      "Z1 P1 ramp shot 3/6 (demo)",
    ]);
  });
  it("ends the night's activity records with the day's watering, and each zone's move to P3", () => {
    type Event = { timestamp: string; message: string; type: string };
    const log = (states: ReturnType<typeof createDemo>) =>
      states["sensor.crop_steering_activity_log"].attributes.events as Event[];
    const night = log(demoClock(createDemo(at(2)), at(2)));
    const lightsOff = new Date(2026, 8, 27, 22, 0).getTime();
    expect(night.every((event) => Date.parse(event.timestamp) < lightsOff)).toBe(true);
    expect(night.slice(0, 3).map((event) => event.message)).toEqual(
      Array(3).fill("P2 → P3: the day's watering is done (demo)."),
    );
    // No shot after the move to P3.
    const p3 = Math.min(...night.slice(0, 3).map((event) => Date.parse(event.timestamp)));
    expect(
      night.filter((event) => event.type === "water" && Date.parse(event.timestamp) > p3),
    ).toEqual([]);
    // By day, the demo's own records again.
    expect(log(demoClock(demoClock(createDemo(at(2)), at(2)), at(16)))).toEqual(
      log(createDemo(at(16))),
    );
  });
  it("leaves a change made in the demo alone until the lights next change", () => {
    const day = demoClock(createDemo(at(16)), at(16));
    const picked = {
      ...day,
      "sensor.crop_steering_zone_1_phase": {
        ...day["sensor.crop_steering_zone_1_phase"],
        state: "P2",
      },
    };
    expect(demoClock(picked, at(17))["sensor.crop_steering_zone_1_phase"].state).toBe("P2");
    expect(demoClock(picked, at(23))["sensor.crop_steering_zone_1_phase"].state).toBe("P3");
  });
});

describe("the demo's batch tank", () => {
  // Four in the afternoon, in whatever time zone the test runs: Flower 2's lights came on at 10.
  const at = new Date(2026, 8, 28, 16, 0).getTime();
  const HOUR = 3_600_000;
  const states = createDemo(at);
  const rooms = discoverRooms(states);
  const load = (hours: number, room = rooms[0]) => {
    const read = tankEntities(buildRoom(states, room), states);
    const lights = (key: string) =>
      Number(states[`number.crop_steering_${room.prefix}lights_${key}_hour`].state);
    const rows = joinRows(
      recordWindows(lights("on"), lights("off"), hours, at).map((window) =>
        demoDay(
          states,
          { entityIds: read.entityIds, attributeIds: read.attributeIds, ...window },
          at,
        ),
      ),
    );
    return { read, record: tankRecord(rows, read.ids, at - hours * HOUR, at) };
  };
  it("was filled to 100 % at its recorded last fill, and its card reads where the chart ends", () => {
    for (const room of rooms) {
      const { read, record } = load(24, room);
      expect(read.ids.level).toBe(`sensor.demo_${room.prefix}tank_level`);
      expect(record.level.at(-1)!.value).toBe(Number(states[read.ids.level!].state));
      const fill = Date.parse(states[read.ids.fill!].state);
      expect(record.fills.at(-1)).toBe(fill);
      expect(record.level.find((step) => step.start === fill)!.value).toBe(100);
      expect(record.filling.at(-1)).toEqual({ start: fill - 20 * 60_000, end: fill, open: false });
      expect(record.shots.length).toBeGreaterThan(10);
    }
    // The two rooms' tanks are two tanks.
    expect(states["sensor.demo_tank_level"].state).not.toBe(
      states["sensor.demo_f1_tank_level"].state,
    );
  });
  it("is filled to 100 % once or twice a day, as F2's is, after running down to 25 % or less", () => {
    const { record } = load(168);
    expect(record.fills.length).toBeGreaterThanOrEqual(7);
    expect(record.fills.length).toBeLessThanOrEqual(14);
    for (const fill of record.fills) {
      expect(record.level.find((step) => step.start === fill)!.value).toBe(100);
      const before = record.level.filter((step) => step.start < fill).at(-1);
      if (before) expect(before.value).toBeLessThanOrEqual(25);
    }
  });
  it("runs the pump through every shot, and only a fill raises the level", () => {
    const { record } = load(168);
    for (const shot of record.shots)
      expect(record.pump.some((run) => run.start <= shot.start && shot.end <= run.end)).toBe(true);
    record.level.forEach((step, index) => {
      expect(step.value).toBeGreaterThanOrEqual(0);
      expect(step.value).toBeLessThanOrEqual(100);
      if (index && step.value > record.level[index - 1].value)
        expect(record.fills).toContain(step.start);
    });
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
      expect(daysBetween(current.start_date, dateInZone(now, timeZone))).toBe(14);
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
