import { describe, expect, it } from "vitest";
import { batchesLeft, draftErrors, stockShare, stockTone, type StockTankDraft } from "./stock";
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
    expect(draftErrors([draft(), draft({ name: "bloom" })])).toContain("Two tanks are called bloom.");
    expect(draftErrors([draft({ level_l: 60 })]).join()).toMatch(/level must be between/);
    expect(draftErrors([draft({ dose_entity: "switch.pump" })]).join()).toMatch(/dose entity/);
    expect(draftErrors([draft({ capacity_l: Number.NaN })]).join()).toMatch(/capacity/);
  });
});

describe("demo stock services", () => {
  const room = "room:";
  const demo = () => new StockDemo(() => ({}));

  it("starts with sample tanks and refuses a stale revision", () => {
    const stock = demo();
    const doc = stock.call("stock_get", { room_id: room });
    expect(doc.tanks.length).toBeGreaterThan(0);
    expect(() =>
      stock.call("stock_refill", { room_id: room, expected_revision: 99, id: doc.tanks[0].id }),
    ).toThrow(/changed elsewhere/);
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
    doc = stock.call("stock_refill", { room_id: room, expected_revision: doc.revision, id: "bloom" });
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
    expect(doc.history[0]).toMatchObject({ source: "manual", draw_ml: { bloom: 1800, part_a: 400 } });
  });
});
