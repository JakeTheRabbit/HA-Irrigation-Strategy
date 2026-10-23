import { describe, expect, test, vi } from "vitest";
import { holdController } from "@/components/primitives/hold-button";
import {
  advanceOnReport,
  calibrationDue,
  calibrationLine,
  canStartRun,
  estimateRate,
  nominalOf,
  primeActions,
  primeLabel,
  pumpMotion,
  rateSentence,
  runGone,
  runState,
  wearNote,
} from "./pump-calibration";
import { PumpDemo } from "./pump-demo";
import type { States } from "./types";

const DAY = 86_400_000;
const NOW = Date.UTC(2026, 9, 22, 12);

describe("rateSentence", () => {
  test("rateSentence 300 vs 280 → +7%", () => {
    expect(rateSentence(300, 280)).toBe("300 mL/min — 7% above the catalogue figure.");
  });
  test("below, level and without a catalogue figure", () => {
    expect(rateSentence(250, 280)).toBe("250 mL/min — 11% below the catalogue figure.");
    expect(rateSentence(280.4, 280)).toBe("280.4 mL/min — the same as the catalogue figure.");
    expect(rateSentence(62.5, null)).toBe("62.5 mL/min. This pump has no catalogue figure to compare with.");
  });
});

describe("calibrationDue", () => {
  test("calibrationDue 69 days at every 60 → due", () => {
    expect(calibrationDue(NOW - 69 * DAY, 60, NOW)).toEqual({ days: 69, due: true });
  });
  test("22 days is not due; never calibrated is due", () => {
    expect(calibrationDue(NOW - 22.5 * DAY, 60, NOW)).toEqual({ days: 22, due: false });
    expect(calibrationDue(null, 60, NOW)).toEqual({ days: null, due: true });
  });
});

describe("wearNote", () => {
  test("wearNote down 12% since March", () => {
    const history = [
      { at: Date.UTC(2026, 9, 22), mlMin: 300 },
      { at: Date.UTC(2026, 2, 15), mlMin: 341 },
      { at: Date.UTC(2026, 6, 1), mlMin: 322 },
    ];
    expect(wearNote(history, "UTC")).toBe("Down 12% since March — tubing may be wearing.");
  });
  test("a steady or rising pump, or one calibration, has no note", () => {
    expect(wearNote([{ at: Date.UTC(2026, 2, 15), mlMin: 300 }, { at: Date.UTC(2026, 9, 1), mlMin: 290 }], "UTC")).toBeNull();
    expect(wearNote([{ at: Date.UTC(2026, 2, 15), mlMin: 300 }], "UTC")).toBeNull();
  });
});

describe("prime", () => {
  test("prime sends pump_stop on release", () => {
    const send = vi.fn(() => Promise.resolve());
    const hold = holdController({ mode: "while-held", maxSeconds: 30, ...primeActions(send, "room:", "part_b") });
    hold.press();
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenLastCalledWith("pump_prime", { room_id: "room:", pump: "part_b", seconds: 30 });
    hold.release("pointerup");
    expect(send.mock.calls).toEqual([
      ["pump_prime", { room_id: "room:", pump: "part_b", seconds: 30 }],
      ["pump_stop", { room_id: "room:", pump: "part_b" }],
    ]);
    // A second release sends nothing more.
    hold.release("blur");
    expect(send).toHaveBeenCalledTimes(2);
  });
});

describe("runState", () => {
  test("runState waits until ran_s is reported", () => {
    expect(runState(null)).toBe("waiting");
    expect(runState({})).toBe("waiting");
    expect(runState({ ran_s: null })).toBe("waiting");
    expect(runState({ ran_s: 30 })).toBe("ran");
    expect(runState({ ran_s: 0 })).toBe("ran");
  });
});

describe("helpers", () => {
  test("nominalOf reads the catalogue's dial table", () => {
    const catalog = { hea_p1: { name: "H.E. Anderson P1", nominal_ml_min: { "8": 272 } }, peristaltic: null };
    expect(nominalOf({ model: { catalog_id: "hea_p1", dial: 8 } }, catalog)).toBe(272);
    expect(nominalOf({ model: { catalog_id: "peristaltic", dial: null } }, catalog)).toBeNull();
    expect(nominalOf({}, catalog)).toBeNull();
  });
  test("estimateRate is the integration's sum, to 2 decimals", () => {
    expect(estimateRate(150, 30)).toBe(300);
    expect(estimateRate(100, 29)).toBe(206.9);
    expect(estimateRate(0, 30)).toBeNull();
    expect(estimateRate(150, 0)).toBeNull();
  });
});

describe("canStartRun", () => {
  test("offers Run when there is no run, or the last one ran 0 s", () => {
    expect(canStartRun(null, null)).toBe(true);
    expect(canStartRun("s1", null)).toBe(false);
    expect(canStartRun("s1", { ran_s: null })).toBe(false);
    expect(canStartRun("s1", { ran_s: 0 })).toBe(true);
    expect(canStartRun("s1", { ran_s: 30 })).toBe(false);
  });
  test("offers Run again over a reported run once the grower came back to step 3", () => {
    expect(canStartRun("s1", { ran_s: 30 }, true)).toBe(true);
    expect(canStartRun("s1", { ran_s: null }, true)).toBe(false);
  });
});

describe("advanceOnReport", () => {
  const reported = { session_id: "s1", ran_s: 30 };
  test("moves on once, when our run is first reported", () => {
    expect(advanceOnReport(3, reported, null)).toBe(true);
    expect(advanceOnReport(3, { session_id: "s1", ran_s: null }, null)).toBe(false);
    expect(advanceOnReport(3, { session_id: "s1", ran_s: 0 }, null)).toBe(false);
    expect(advanceOnReport(4, reported, null)).toBe(false);
    expect(advanceOnReport(3, null, null)).toBe(false);
  });
  test("Back from step 4 stays on step 3 for the same run, a new run moves on again", () => {
    expect(advanceOnReport(3, reported, "s1")).toBe(false);
    expect(advanceOnReport(3, { session_id: "s2", ran_s: 30 }, "s1")).toBe(true);
  });
});

describe("calibrationLine", () => {
  test("a stored flow without history is calibrated, with no date", () => {
    expect(calibrationLine({ calibrations: [], calibrated_ml_min: 280 }, "UTC")).toBe("Calibrated · 280 mL/min, date not recorded");
    expect(calibrationLine({ calibrated_ml_min: 280 }, "UTC")).toBe("Calibrated · 280 mL/min, date not recorded");
  });
  test("no flow and no history is not calibrated", () => {
    expect(calibrationLine({ calibrations: [], calibrated_ml_min: null }, "UTC")).toBe("Not calibrated yet");
  });
  test("the newest calibration gives its date and flow", () => {
    const at = new Date(NOW).toISOString();
    const rec = { id: "c", pump: "p", run_s: 30, measured_ml: 150, ml_min: 300, previous_ml_min: null, at, by: null };
    expect(calibrationLine({ calibrations: [rec], calibrated_ml_min: 300 }, "UTC")).toMatch(/^Calibrated .+ · 300 mL\/min$/);
  });
});

describe("prime and run wording", () => {
  test("a prime is only asked for: the drawing never runs without the controller's word", () => {
    expect(pumpMotion("Part B", { priming: true, primeOk: undefined, waiting: false })).toBe("Part B");
    expect(pumpMotion("Part B", { priming: true, primeOk: false, waiting: false })).toBe("Part B");
    expect(pumpMotion("Part B", { priming: true, primeOk: true, waiting: false })).toBe("Asked Part B to prime");
  });
  test("a run waiting for its report is worded as asked for", () => {
    expect(pumpMotion("Part B", { priming: false, primeOk: undefined, waiting: true })).toBe("Asked Part B to run 30 s");
  });
  test("the prime button says the prime was asked for, and drops it on refusal", () => {
    expect(primeLabel("Part B", false, undefined)).toBe("Hold to prime");
    expect(primeLabel("Part B", true, undefined)).toBe("Asking to prime… let go to stop");
    expect(primeLabel("Part B", true, true)).toBe("Asked Part B to prime… let go to stop");
    expect(primeLabel("Part B", true, false)).toBe("Hold to prime");
  });
});

describe("runGone", () => {
  test("a read after the run opened that no longer shows its session ends the run", () => {
    expect(runGone("s1", null, true)).toBe(true);
    expect(runGone("s1", { session_id: "s2" }, true)).toBe(true);
    expect(runGone("s1", { session_id: "s1" }, true)).toBe(false);
  });
  test("a read from before the run opened, or no run, proves nothing", () => {
    expect(runGone("s1", null, false)).toBe(false);
    expect(runGone(null, null, true)).toBe(false);
  });
});

describe("demo pump_stop", () => {
  const pumps = [{ id: "part_b", name: "Part B", flow_entity: "number.part_b_flow" }];
  const states = {
    "sensor.crop_steering_dosing_config": { entity_id: "sensor.crop_steering_dosing_config", state: "ok", attributes: { pumps } },
  } as unknown as States;
  const doc = () => ({ room_id: "room:", config: { pumps: structuredClone(pumps) } }) as never;
  test("a stop before the controller takes the run closes the session, as the backend does", () => {
    const demo = new PumpDemo(() => states, () => {});
    demo.call("pump_calibrate", { room_id: "room:", pump: "part_b", seconds: 30 });
    expect(demo.decorate(doc()).config?.pumps[0].calibration_session?.session_id).toMatch(/^demo-pump-cal-/);
    const stop = demo.call("pump_stop", { room_id: "room:", pump: "part_b" }) as { data: { replaced: unknown } };
    expect(stop.data.replaced).toMatchObject({ action: "calibrate", pump: "part_b" });
    expect(demo.decorate(doc()).config?.pumps[0].calibration_session).toBeUndefined();
  });
  test("a prime or run asked for while the stop still waits for the controller is refused busy", () => {
    const demo = new PumpDemo(() => states, () => {});
    demo.call("pump_stop", { room_id: "room:", pump: "part_b" });
    const run = demo.call("pump_calibrate", { room_id: "room:", pump: "part_b", seconds: 30 }) as { ok: boolean; error: { code: string; message: string } };
    expect(run.ok).toBe(false);
    expect(run.error).toEqual({ code: "guard_refused", message: "Another dosing request is still waiting for the controller" });
    const prime = demo.call("pump_prime", { room_id: "room:", pump: "part_b", seconds: 30 }) as { ok: boolean };
    expect(prime.ok).toBe(false);
  });
});
