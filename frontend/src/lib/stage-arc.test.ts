import { describe, expect, it } from "vitest";
import generated from "./generated/arcs.json";
import { ARC_ROWS, NOMINAL_FLOWER_DAYS, stageArc, stageNow, weekOf } from "./stage-arc";

describe("the stage arc", () => {
  it("is the generated default arc, the one the controller reads", () => {
    expect(generated.default_arc).toBe("slab_default");
    expect(ARC_ROWS).toBe(generated.arcs.slab_default.stages);
    const bulk = ARC_ROWS.find((row) => row.stage === "flower bulk")!;
    expect([bulk.flower_days, bulk.steering, bulk.dryback_points, bulk.pore_ec, bulk.runoff_pct]).toEqual(
      [[22, 42], "vegetative", [10, 15], [3.5, 6], [8, 16]],
    );
  });
  it("is the slab-guide arc on a 56-day flower, with its dryback in points", () => {
    expect(
      stageArc().map((stage) => [
        stage.name,
        stage.first,
        stage.last,
        stage.steering,
        stage.poreEc,
        stage.drybackPoints,
        stage.runoff,
      ]),
    ).toEqual([
      ["flower setting (stretch)", 1, 21, "generative", [5, 10], [15, 25], [1, 7]],
      ["flower bulk", 22, 42, "vegetative", [3.5, 6], [10, 15], [8, 16]],
      ["finish", 43, 56, "ripening", [3, 4], [20, 25], [1, 7]],
    ]);
  });
  it("keeps a longer cultivar in the bulk until its last two weeks, as the controller does", () => {
    const long = stageArc(70);
    expect(long.map((stage) => [stage.first, stage.last])).toEqual([
      [1, 21],
      [22, 56],
      [57, 70],
    ]);
    // A short flower has no bulk, and a bad length is the nominal one.
    expect(stageArc(30).map((stage) => [stage.name, stage.first, stage.last])).toEqual([
      ["flower setting (stretch)", 1, 21],
      ["finish", 22, 30],
    ]);
    expect(stageArc(Number.NaN).at(-1)!.last).toBe(NOMINAL_FLOWER_DAYS);
  });
  it("counts grow weeks of seven days from day 1", () => {
    expect([1, 7, 8, 37, 56].map(weekOf)).toEqual([1, 1, 2, 6, 8]);
  });
});

describe("today on the arc", () => {
  const now = new Date(2026, 8, 28, 16, 0).getTime();
  it("says the stage, the week, and the date the next stage starts", () => {
    const today = stageNow(stageArc(56), 37, now)!;
    expect([today.stage.name, today.week]).toEqual(["flower bulk", 6]);
    expect(today.next!.stage.name).toBe("finish");
    expect(today.next!.day).toBe(43);
    expect(today.next!.date).toBe(new Date(2026, 9, 4).getTime());
  });
  it("has no next stage in the finish, and no place outside flower", () => {
    expect(stageNow(stageArc(56), 50, now)!.next).toBeNull();
    expect(stageNow(stageArc(56), 57, now)).toBeNull();
    expect(stageNow(stageArc(56), null, now)).toBeNull();
    expect(stageNow(stageArc(56), 0, now)).toBeNull();
  });
});
