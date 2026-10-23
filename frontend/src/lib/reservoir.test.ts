import { describe, expect, it } from "vitest";
import { createDemo } from "./demo";
import { readStatus, dosingStatusId } from "./dosing";
import { batchLine, reservoirView, tankLevelId } from "./reservoir";
import type { States } from "./types";

const level = (state: string, attributes: Record<string, unknown> = {}): States => ({
  [tankLevelId("")]: {
    entity_id: tankLevelId(""),
    state,
    attributes: { unit_of_measurement: "%", minimum_pct: 8, ...attributes },
  },
});

describe("the reservoir minimum in words", () => {
  it("is off, and says how to arm it, for a room with no tank level mapped", () => {
    const view = reservoirView({}, "");
    expect(view.state).toBe("unmapped");
    expect(view.label).toBe("Off: no tank level mapped");
    expect(view.tone).toBe("neutral");
    expect(view.code).toBeNull();
  });
  it("allows watering above the minimum, with the litres left above it once learned", () => {
    const view = reservoirView(level("45", { litres_per_pct: 2 }), "");
    expect(view).toMatchObject({ state: "ok", label: "Watering allowed", tone: "on", code: null });
    expect(view.aboveMinimumL).toBe(74);
    expect(reservoirView(level("45"), "").aboveMinimumL).toBeNull();
  });
  it("holds at the minimum until 12 %, and on a low float, naming the code", () => {
    const held = reservoirView(level("10", { below_minimum: true, release_pct: 12 }), "");
    expect(held).toMatchObject({ state: "held", code: "CS-901", tone: "warn" });
    expect(held.detail).toContain("12 %");
    expect(reservoirView(level("40", { low: true }), "")).toMatchObject({
      state: "held",
      code: "CS-901",
    });
  });
  it("holds on a level it can't read or a sensor that looks stuck", () => {
    expect(reservoirView(level("unknown"), "")).toMatchObject({ state: "unknown", code: "CS-902" });
    const stuck = reservoirView(level("unknown", { stuck: true }), "");
    expect(stuck.detail).toContain("stuck");
  });
  it("stops a fill over the full mark while watering carries on", () => {
    const view = reservoirView(level("103", { over_full: true }), "");
    expect(view).toMatchObject({ state: "over", code: "CS-904" });
    expect(view.detail).toContain("The shots continue");
  });
  it("says the marks the controller publishes, never its own copy of them", () => {
    const marks = { release_pct: 15, over_pct: 105, over_release_pct: 95 };
    expect(reservoirView(level("10", { below_minimum: true, ...marks }), "").detail).toContain(
      "starts again by itself at 15 %",
    );
    const over = reservoirView(level("106", { over_full: true, ...marks }), "").detail;
    expect(over).toContain("at or over 105 %");
    expect(over).toContain("reads 95 % or less");
    // A controller from before it published them: no number the dashboard made up.
    const older = reservoirView(level("10", { below_minimum: true }), "");
    expect(older.detail).not.toMatch(/12 %/);
    expect(older.marks).toEqual({ minimum: 8, release: null, over: null, overRelease: null });
  });
  it("reads the room's own sensor by its prefix", () => {
    const states = createDemo(Date.parse("2026-09-28T04:00:00Z"));
    expect(reservoirView(states, "").state).toBe("ok");
    expect(reservoirView(states, "room_b_").state).toBe("unmapped");
  });
});

describe("the batch on the tank", () => {
  it("is absent with no batch dosing reported", () => {
    expect(batchLine(null)).toBeNull();
  });
  it("names the step running now and how far through the batch it is", () => {
    const status = readStatus({
      entity_id: dosingStatusId(""),
      state: "batch",
      attributes: { batch: { step: "fill", steps: [] } },
    })!;
    expect(batchLine(status)).toEqual({
      label: "Batch running: Fill the tank (step 3 of 8)",
      tone: "water",
    });
  });
  it("says how the last batch ended", () => {
    const status = readStatus({
      entity_id: dosingStatusId(""),
      state: "idle",
      attributes: { batch: { step: "idle", result: "stopped by hand", steps: [] } },
    })!;
    expect(batchLine(status)).toMatchObject({ label: "Last batch: Stopped by hand", tone: "warn" });
  });
});
