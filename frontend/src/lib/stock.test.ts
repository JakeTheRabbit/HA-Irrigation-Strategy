import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { StockBottle, bottleTop } from "@/components/stock-bottle";
import {
  batchEveryDays,
  batchesLeft,
  draftErrors,
  nextToRunOut,
  stockShare,
  stockOutlook,
  undoRefill,
  weeklyUse,
  type StockBatch,
  type StockDocument,
  type StockTank,
  type StockTankDraft,
} from "./stock";
import { createDemo } from "./demo";
import { StockDemo } from "./stock-demo";

const draft = (change: Partial<StockTankDraft> = {}): StockTankDraft => ({
  name: "Part B",
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

  it("clamps the share", () => {
    expect(stockShare({ level_l: 60, capacity_l: 50 })).toBe(100);
    expect(stockShare({ level_l: 5, capacity_l: 0 })).toBe(0);
  });

  it("says what the integration would refuse before it is sent", () => {
    expect(draftErrors([draft()])).toEqual([]);
    expect(draftErrors([draft({ name: " " })])).toContain(
      "Each tank needs a name of 1 to 40 characters.",
    );
    expect(draftErrors([draft(), draft({ name: "part b" })])).toContain(
      "Two tanks are called part b.",
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
    expect(doc.tanks.map((t) => t.name)).toEqual(["Silica", "Part B", "Part A", "Line cleaner"]);
    expect(stock.call("stock_get", { room_id: "room:room_b_" }).tanks.map((t) => t.id)).toEqual([
      "veg_base",
      "cleaner",
      "silica",
      "finisher",
      "part_a",
      "part_b",
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
    // The draws the demo's dosing history made before it began: Silica's hand dose the newest.
    expect(before.history[0]).toMatchObject({ source: "dose", draw_ml: { silica: 25 } });
    expect(before.history.filter((entry) => entry.source === "batch")).toHaveLength(8);
    // No revision needed: the key makes a repeat harmless, and an unknown tank is skipped.
    let doc = draw("r1", { part_b: 60, nope: 5 });
    expect(doc.revision).toBe(before.revision + 1);
    expect(doc.tanks.find((t) => t.id === "part_b")!.level_l).toBe(5.34);
    expect(doc.history[0]).toMatchObject({ source: "dose", key: "r1", draw_ml: { part_b: 60 } });
    expect(draw("r1", { part_b: 60 }).revision).toBe(doc.revision);
    expect(stock.call("stock_get", { room_id: room }).tanks[1].level_l).toBe(5.34);
    // A batch's dose; never below empty, and the draw says what was really taken.
    doc = draw("r2:part_b", { part_b: 9000 }, "batch");
    expect(doc.tanks[1].level_l).toBe(0);
    expect(doc.history[0]).toMatchObject({ source: "batch", draw_ml: { part_b: 5340 } });
    // Nothing the room has: nothing counted, so the key stays free.
    expect(draw("r3", { nope: 5 }).revision).toBe(doc.revision);
    expect(() => draw("r4", { part_b: -1 })).toThrow(/0 or more/);
    expect(() => draw("r4", { part_b: 1 }, "fill")).toThrow(/dose or batch/);
    // The integration's stock sensor follows: Part B empty and low, each tank with its pump.
    const sensor = states["sensor.crop_steering_stock_low"];
    expect(sensor.state).toBe("1");
    expect((sensor.attributes.tanks as Record<string, unknown>[])[1]).toMatchObject({
      id: "part_b",
      pump: "part_b",
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
    expect(doc.tanks.map((t) => t.id)).toEqual(["part_b", "part_a"]);
    expect(doc.low).toEqual(["part_b"]);
    doc = stock.call("stock_refill", {
      room_id: room,
      expected_revision: doc.revision,
      id: "part_b",
    });
    expect(doc.tanks[0].level_l).toBe(50);
    expect(doc.low).toEqual([]);
    doc = stock.call("stock_refill", {
      room_id: room,
      expected_revision: doc.revision,
      id: "part_b",
      level_l: 21.5,
    });
    expect(doc.tanks[0].level_l).toBe(21.5);
    doc = stock.call("stock_record_batch", { room_id: room, expected_revision: doc.revision });
    expect(doc.tanks.map((t) => t.level_l)).toEqual([19.7, 49.6]);
    expect(doc.history[0]).toMatchObject({
      source: "manual",
      draw_ml: { part_b: 1800, part_a: 400 },
    });
  });
});

describe("stock outlook (E5)", () => {
  const tank = (level_l: number, low_l: number) => ({ level_l, low_l });
  it("stockOutlook 5.4 L at 0.744 L/batch every 2.5 d → 7 batches, 18 days, belowLow", () => {
    expect(stockOutlook(tank(5.4, 6), 0.744, 2.5)).toEqual({
      batches: 7,
      daysLeft: 18,
      belowLow: true,
    });
    expect(stockOutlook(tank(12.9, 6), 0.744, 2.5)).toEqual({
      batches: 17,
      daysLeft: 43,
      belowLow: false,
    });
    // At the low mark is below it, as the integration counts it (stock.low_tanks).
    expect(stockOutlook(tank(6, 6), 0.744, 2.5).belowLow).toBe(true);
    // 0.29 L is 289.99999999999997 mL in floating point: still one whole 0.29 L batch.
    expect(stockOutlook(tank(0.29, 0), 0.29, 1).batches).toBe(1);
  });

  it("finds one batch every so many days from the batches the history logged", () => {
    const at = (day: number, minute = 0) =>
      new Date(Date.UTC(2026, 9, day, 8, minute)).toISOString();
    const row = (iso: string, source: StockBatch["source"]): StockBatch => ({
      at: iso,
      source,
      draw_ml: { a: 1 },
    });
    // A batch's per-pump draws a minute apart are one batch; hand doses and pump runs are not batches.
    const history = [
      row(at(6), "batch"),
      row(at(6, 1), "batch"),
      row(at(5), "dose"),
      row(at(3, 30), "fill"),
      row(at(1), "manual"),
      row(at(2), "pump"),
    ];
    expect(batchEveryDays(history)).toBeCloseTo(2.5, 2);
    expect(batchEveryDays([row(at(6), "batch")])).toBeNull();
    expect(batchEveryDays([])).toBeNull();
  });
});

describe("used per week (E5)", () => {
  const tz = "Pacific/Auckland";
  // Thu 22 Oct 2026, 12:00 in Auckland.
  const now = Date.UTC(2026, 9, 21, 23, 0);
  const row = (iso: string, draw_ml: Record<string, number>): StockBatch => ({
    at: iso,
    source: "batch",
    draw_ml,
  });
  it("weeklyUse marks current week partial", () => {
    const weeks = weeklyUse(
      [
        row("2026-10-21T20:00:00Z", { part_a: 744, part_b: 500 }), // Thu 22 Oct NZ
        row("2026-10-18T12:00:00Z", { part_a: 256 }), // Mon 19 Oct 01:00 NZ: this week
        row("2026-10-18T10:00:00Z", { part_a: 1000 }), // Sun 18 Oct 23:00 NZ: last week
        row("2026-10-01T01:00:00Z", { cal_mag: 300 }), // Thu 1 Oct NZ
      ],
      tz,
      now,
    );
    expect(weeks.map((w) => w.week)).toEqual([
      "2026-09-28",
      "2026-10-05",
      "2026-10-12",
      "2026-10-19",
    ]);
    expect(weeks.map((w) => w.partial)).toEqual([false, false, false, true]);
    expect(weeks[3].byTank).toEqual({ part_a: 1, part_b: 0.5 });
    expect(weeks[2].byTank).toEqual({ part_a: 1 });
    // A week with nothing drawn inside the history's span drew nothing.
    expect(weeks[1].byTank).toEqual({});
    expect(weeks[0].byTank).toEqual({ cal_mag: 0.3 });
    expect(weeklyUse([], tz, now)).toEqual([]);
  });
});

describe("refill undo (E5)", () => {
  const tanks: StockTank[] = [
    {
      id: "part_a",
      name: "Part A",
      capacity_l: 20,
      level_l: 12.9,
      dose_ml: 744,
      dose_entity: null,
      low_l: 6,
      refilled_at: null,
      updated_at: "u",
    },
    {
      id: "part_b",
      name: "Part B",
      capacity_l: 20,
      level_l: 20,
      dose_ml: 744,
      dose_entity: "number.dose_b",
      low_l: 6,
      refilled_at: "r",
      updated_at: "u",
    },
  ];
  const after = { revision: 7, tanks } as StockDocument;
  const fake = (answer: (data: Record<string, unknown>) => unknown) => {
    const calls: [string, Record<string, unknown>][] = [];
    return {
      calls,
      controller: {
        operator: async <T>(action: string, data: Record<string, unknown> = {}) => {
          calls.push([action, data]);
          return answer(data) as T;
        },
      },
    };
  };
  it("refill undo on 3.17 saves the prior level with the revision", async () => {
    const { calls, controller } = fake(() => ({
      revision: 8,
      tanks: [tanks[0], { ...tanks[1], level_l: 5.4 }],
    }));
    const doc = await undoRefill(controller, after, "part_b", 20, 5.4);
    expect(doc.revision).toBe(8);
    expect(calls).toEqual([
      [
        "stock_save",
        {
          expected_revision: 7,
          tanks: [
            {
              id: "part_a",
              name: "Part A",
              capacity_l: 20,
              dose_ml: 744,
              dose_entity: null,
              low_l: 6,
            },
            {
              id: "part_b",
              name: "Part B",
              capacity_l: 20,
              dose_ml: 744,
              dose_entity: "number.dose_b",
              low_l: 6,
              level_l: 5.4,
            },
          ],
        },
      ],
    ]);
    expect(JSON.stringify(calls)).not.toMatch(/client|proposal_token/);
  });

  it("puts nothing back once the tank has moved since the refill, and says when it was not read back", async () => {
    const moved = {
      revision: 9,
      tanks: [tanks[0], { ...tanks[1], level_l: 19.3 }],
    } as StockDocument;
    const { calls, controller } = fake(() => moved);
    await expect(undoRefill(controller, moved, "part_b", 20, 5.4)).rejects.toThrow(
      "Part B has changed since the refill. Nothing was put back.",
    );
    expect(calls).toEqual([]);
    const unread = fake(() => after);
    await expect(undoRefill(unread.controller, after, "part_b", 20, 5.4)).rejects.toThrow(
      /did not confirm/,
    );
  });
});

describe("stock bottle to scale (E5)", () => {
  const tank = { id: "ph", name: "pH down", level_l: 3.8, capacity_l: 5, low_l: 1.5 };
  const transform = (html: string) => /transform="([^"]+)"/.exec(html)?.[1];
  it("draws a tank by volume with capacityScale, and as before without it", () => {
    // A quarter of the largest tank's volume: the cube root of a quarter as tall and as wide.
    expect(
      transform(
        renderToStaticMarkup(
          createElement(StockBottle, { tank, state: "ok", capacityScale: 0.25, label: "x" }),
        ),
      ),
    ).toBe(`translate(20 60) scale(${Math.cbrt(0.25)}) translate(-20 -60)`);
    expect(
      transform(
        renderToStaticMarkup(
          createElement(StockBottle, { tank, state: "ok", scale: 0.6, label: "x" }),
        ),
      ),
    ).toBe("translate(20 60) scale(0.6) translate(-20 -60)");
    // The low mark at 1.5 of 5 L, on the full-size drawing: y = 60 - 0.3 × 42 = 47.4 of 62.
    expect(bottleTop(1.5, 5, 1)).toBeCloseTo((47.4 / 62) * 100, 6);
  });
});
