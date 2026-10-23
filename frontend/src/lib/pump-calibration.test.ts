import { describe, expect, test, vi } from "vitest";
import { holdController } from "@/components/primitives/hold-button";
import {
  calibrationDue,
  canStartRun,
  estimateRate,
  nominalOf,
  primeActions,
  primeLabel,
  pumpMotion,
  rateSentence,
  runState,
  wearNote,
} from "./pump-calibration";

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
});

describe("prime and run wording", () => {
  test("the pump reads as running only once the prime was accepted", () => {
    expect(pumpMotion("Part B", { priming: true, primeOk: undefined, waiting: false })).toEqual({ active: false, text: "Part B" });
    expect(pumpMotion("Part B", { priming: true, primeOk: false, waiting: false })).toEqual({ active: false, text: "Part B" });
    expect(pumpMotion("Part B", { priming: true, primeOk: true, waiting: false })).toEqual({ active: true, text: "Part B is running" });
  });
  test("a run waiting for its report is worded as asked for", () => {
    expect(pumpMotion("Part B", { priming: false, primeOk: undefined, waiting: true })).toEqual({
      active: false,
      text: "Asked Part B to run 30 s",
    });
  });
  test("the prime button claims priming only once accepted, and drops it on refusal", () => {
    expect(primeLabel(false, undefined)).toBe("Hold to prime");
    expect(primeLabel(true, undefined)).toBe("Asking to prime… let go to stop");
    expect(primeLabel(true, true)).toBe("Priming… let go to stop");
    expect(primeLabel(true, false)).toBe("Hold to prime");
  });
});
