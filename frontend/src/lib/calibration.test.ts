import { describe, expect, it } from "vitest";
import { CalibrationDemo, evaluate, type CalibrationResult } from "./calibration";

const points = (...pairs: [number, number][]) =>
  pairs.map(([reference, reading]) => ({ reference, reading }));

describe("evaluate", () => {
  // The same cases as tests/test_calibration.py: the form shows what the integration will store.
  it.each([
    ["ph", [7, 7], [4, 4], 100, 0, "pass"],
    ["ph", [7, 7.05], [4, 4.1], 98.3, 0.05, "pass"],
    ["ph", [4, 4.2], [7, 7.2], 100, 0.2, "drifting"],
    ["ph", [7, 7], [4, 4.5], 83.3, 0, "fail"],
    ["ec", [1.413, 1.5], [12.88, 12], 91.6, 0.206, "drifting"],
    ["ec", [0, 0], [2.77, 2.8], 101.1, 0, "pass"],
  ] as const)("%s %j %j", (kind, a, b, slope, offset, verdict) => {
    const result = evaluate(kind, points([...a], [...b])) as CalibrationResult;
    expect([result.slope_pct, result.offset, result.verdict]).toEqual([slope, offset, verdict]);
  });
  it("refuses points it cannot use", () => {
    expect(evaluate("ph", points([7, 7]))).toEqual({
      error: "A two-point calibration needs exactly two points",
    });
    expect(evaluate("ph", points([7, 7], [6.5, 6.5]))).toEqual({
      error: "The two reference solutions must be at least 1 apart",
    });
    expect(evaluate("ph", points([7, 7], [15, 15]))).toEqual({
      error: "Reference must be a number from 0 to 14",
    });
    expect(evaluate("ec", points([1, Number.NaN], [3, 3]))).toEqual({
      error: "Reading must be a number from 0 to 20",
    });
  });
});

describe("CalibrationDemo", () => {
  const states = {
    "sensor.crop_steering_engine_config": {
      entity_id: "sensor.crop_steering_engine_config",
      state: "ok",
      attributes: { prefix: "", feed_ph_sensor: "sensor.ph", feed_ec_sensor: "" },
      last_changed: "",
      last_updated: "",
    },
  };
  it("records a check newest first and refuses a stale revision", () => {
    const demo = new CalibrationDemo(
      () => states,
      () => Date.UTC(2026, 9, 1),
    );
    const first = demo.call("calibration_get", { room_id: "room:" });
    expect(first.sensors).toEqual({ feed_ph: "sensor.ph", feed_ec: null });
    expect(first.records.map((r) => r.verdict)).toEqual(["drifting"]);
    const saved = demo.call("calibration_record", {
      room_id: "room:",
      expected_revision: first.revision,
      probe: "feed_ph",
      points: points([7, 7], [4, 4]),
    });
    expect(saved.revision).toBe(first.revision + 1);
    expect(saved.records[0]).toMatchObject({ verdict: "pass", entity_id: "sensor.ph" });
    expect(() =>
      demo.call("calibration_record", {
        room_id: "room:",
        expected_revision: first.revision,
        probe: "feed_ph",
        points: points([7, 7], [4, 4]),
      }),
    ).toThrow("changed elsewhere");
  });
});
