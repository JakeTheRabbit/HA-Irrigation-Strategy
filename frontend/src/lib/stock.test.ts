import { describe, expect, it } from "vitest";
import {
  batchesLeft,
  draftErrors,
  nextToRunOut,
  stockShare,
  stockTone,
  type StockTank,
  type StockTankDraft,
} from "./stock";
import { createDemo } from "./demo";
import { StockDemo } from "./stock-demo";

const draft = (change: Partial<StockTankDraft> = {}): StockTankDraft => ({
  name: "Bloom",
  capacity_l: 50,
  level_l: 50,
  dose_ml: 1800,
  dose_entity: null,
  low_l: 10,
  ...change,
});

describe("stock helpers", () => {
  it("counts whole batches left, and none for a tank that doses nothing", () => {
    expect(batchesLeft({ level_l: 9.9 }, 1800)).toBe(5);
    expect(batchesLeft({ level_l: 0.36 }, 120)).toBe(3); // not 2.9999
    expect(batchesLeft({ level_l: 9.9 }, 0)).toBeNull();
    expect(batchesLeft({ level_l: 9.9 }, undefined)).toBeNull();
  });

  it("is red at the low mark, amber within half as much again, and clamps the share", () => {
    expect(stockTone({ level_l: 10, low_l: 10 })).toBe("over");
    expect(stockTone({ level_l: 14.9, low_l: 10 })).toBe("high");
    expect(stockTone({ level_l: 15.1, low_l: 10 })).toBe("normal");
    expect(stockShare({ level_l: 60, capacity_l: 50 })).toBe(100);
    expect(stockShare({ level_l: 5, capacity_l: 0 })).toBe(0);
  });

  it("says what the integration would refuse before it is sent", () => {
    expect(draftErrors([draft()])).toEqual([]);
    expect(draftErrors([draft({ name: " " })])).toContain(
      "Each tank needs a name of 1 to 40 characters.",
    );
    expect(draftErrors([draft(), draft({ name: "bloom" })])).toContain(
      "Two tanks are called bloom.",
    );
    expect(draftErrors([draft({ level_l: 60 })]).join()).toMatch(/level must be between/);
    expect(draftErrors([draft({ dose_entity: "switch.pump" })]).join()).toMatch(/dose entity/);
    expect(draftErrors([draft({ capacity_l: Number.NaN })]).join()).toMatch(/capacity/);
  });
});

describe("the next tank to run out", () => {
  const tank = (id: string, level_l: number, dose_ml: number, capacity_l = 20): StockTank => ({
    id,
    name: id,
    capacity_l,
    level_l,
    dose_ml,
    dose_entity: null,
    low_l: 2,
    refilled_at: null,
    updated_at: "",
  });
  it("is the one with the fewest batches left at today's doses, the emptiest on a tie", () => {
    const tanks = [tank("A", 10, 500), tank("B", 3, 250), tank("C", 6, 500, 40)];
    expect(nextToRunOut(tanks, {})).toEqual({ tank: tanks[1], batches: 12 });
    // A dose entity's reading takes over from the fixed dose.
    expect(nextToRunOut(tanks, { A: 2500 })).toEqual({ tank: tanks[0], batches: 4 });
    expect(nextToRunOut([tank("A", 6, 500), tanks[2]], {})!.tank.id).toBe("C");
  });
  it("is nothing while no tank's dose is known", () => {
    expect(nextToRunOut([tank("A", 10, 0)], {})).toBeNull();
    expect(nextToRunOut([], {})).toBeNull();
  });
});

describe("demo stock services", () => {
  const room = "room:";
  const demo = () => new StockDemo(() => ({}));

  it("starts with a tank per dosing pump, named after its nutrient, and refuses a stale revision", () => {
    const stock = demo();
    const doc = stock.call("stock_get", { room_id: room });
    expect(doc.tanks.map((t) => t.name)).toEqual(["Balance", "Bloom", "Core", "Cleanse"]);
    expect(stock.call("stock_get", { room_id: "room:f1_" }).tanks.map((t) => t.id)).toEqual([
      "grow",
      "cleanse",
      "balance",
      "fade",
      "core",
      "bloom",
    ]);
    expect(() =>
      stock.call("stock_refill", { room_id: room, expected_revision: 99, id: doc.tanks[0].id }),
    ).toThrow(/changed elsewhere/);
  });

  it("draws what the controller dosed, once per key, and says so on its sensor", () => {
    let states = createDemo(new Date(2026, 8, 28, 16).getTime());
    const stock = new StockDemo(
      () => states,
      (next) => (states = next),
    );
    const draw = (key: string, draws: Record<string, unknown>, source = "dose") =>
      stock.call("stock_draw", { room_id: room, key, draws, source });
    const before = stock.call("stock_get", { room_id: room });
    // The draws the demo's dosing history made before it began: Balance's hand dose the newest.
    expect(before.history[0]).toMatchObject({ source: "dose", draw_ml: { balance: 25 } });
    expect(before.history.filter((entry) => entry.source === "batch")).toHaveLength(8);
    // No revision needed: the key makes a repeat harmless, and an unknown tank is skipped.
    let doc = draw("r1", { bloom: 60, nope: 5 });
    expect(doc.revision).toBe(before.revision + 1);
    expect(doc.tanks.find((t) => t.id === "bloom")!.level_l).toBe(5.34);
    expect(doc.history[0]).toMatchObject({ source: "dose", key: "r1", draw_ml: { bloom: 60 } });
    expect(draw("r1", { bloom: 60 }).revision).toBe(doc.revision);
    expect(stock.call("stock_get", { room_id: room }).tanks[1].level_l).toBe(5.34);
    // A batch's dose; never below empty, and the draw says what was really taken.
    doc = draw("r2:bloom", { bloom: 9000 }, "batch");
    expect(doc.tanks[1].level_l).toBe(0);
    expect(doc.history[0]).toMatchObject({ source: "batch", draw_ml: { bloom: 5340 } });
    // Nothing the room has: nothing counted, so the key stays free.
    expect(draw("r3", { nope: 5 }).revision).toBe(doc.revision);
    expect(() => draw("r4", { bloom: -1 })).toThrow(/0 or more/);
    expect(() => draw("r4", { bloom: 1 }, "fill")).toThrow(/dose or batch/);
    // The integration's stock sensor follows: Bloom empty and low, each tank with its pump.
    const sensor = states["sensor.crop_steering_stock_low"];
    expect(sensor.state).toBe("1");
    expect((sensor.attributes.tanks as Record<string, unknown>[])[1]).toMatchObject({
      id: "bloom",
      pump: "bloom",
      level_l: 0,
      percent: 0,
      low: true,
      batches_left: 0,
    });
  });

  it("saves, refills, sets a level and records a batch like the integration", () => {
    const stock = demo();
    let doc = stock.call("stock_get", { room_id: room });
    doc = stock.call("stock_save", {
      room_id: room,
      expected_revision: doc.revision,
      tanks: [draft({ level_l: 8 }), draft({ name: "Part A!", dose_ml: 400 })],
    });
    expect(doc.tanks.map((t) => t.id)).toEqual(["bloom", "part_a"]);
    expect(doc.low).toEqual(["bloom"]);
    doc = stock.call("stock_refill", {
      room_id: room,
      expected_revision: doc.revision,
      id: "bloom",
    });
    expect(doc.tanks[0].level_l).toBe(50);
    expect(doc.low).toEqual([]);
    doc = stock.call("stock_refill", {
      room_id: room,
      expected_revision: doc.revision,
      id: "bloom",
      level_l: 21.5,
    });
    expect(doc.tanks[0].level_l).toBe(21.5);
    doc = stock.call("stock_record_batch", { room_id: room, expected_revision: doc.revision });
    expect(doc.tanks.map((t) => t.level_l)).toEqual([19.7, 49.6]);
    expect(doc.history[0]).toMatchObject({
      source: "manual",
      draw_ml: { bloom: 1800, part_a: 400 },
    });
  });
});
