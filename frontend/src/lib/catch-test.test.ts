import { describe, expect, it } from "vitest";
import { calibrateDripper, catchTest } from "./catch-test";

describe("catch-test arithmetic", () => {
  it("converts a measured per-dripper catch into L/hour", () => {
    expect(calibrateDripper(200, 3)).toBe(4);
    expect(calibrateDripper(100, 1)).toBe(6);
  });
  it("does not turn missing, non-positive or invalid measurements into a flow", () => {
    expect(calibrateDripper(0, 3)).toBeNull();
    expect(calibrateDripper(100, 0)).toBeNull();
    expect(calibrateDripper(NaN, 2)).toBeNull();
  });
});

describe("catch test entered in seconds", () => {
  it("works out litres per hour for one dripper", () => {
    expect(catchTest(200, 180)).toEqual({ flow: 4, error: null });
    expect(catchTest(100, 60)).toEqual({ flow: 6, error: null });
    expect(catchTest(33, 60)).toEqual({ flow: 1.98, error: null });
  });
  it("gives the flow to two decimals, which is all a timed catch can resolve", () => {
    expect(catchTest(100, 47)).toEqual({ flow: 7.66, error: null });
  });
  it("accepts results on the limits the integration accepts", () => {
    expect(catchTest(1, 36).flow).toBe(0.1);
    expect(catchTest(500, 36).flow).toBe(50);
  });
  it("rejects a zero or negative run time", () => {
    expect(catchTest(200, 0)).toEqual({
      flow: null,
      error: "Run time must be more than 0 seconds.",
      field: "seconds",
    });
    expect(catchTest(200, -30).error).toBe("Run time must be more than 0 seconds.");
  });
  it("rejects a zero or negative catch", () => {
    expect(catchTest(0, 60)).toEqual({
      flow: null,
      error: "Water caught must be more than 0 mL.",
      field: "ml",
    });
    expect(catchTest(-5, 60).error).toBe("Water caught must be more than 0 mL.");
  });
  it("rejects values that are not finite numbers", () => {
    const error = "Enter the run time in seconds and the water caught in mL as numbers.";
    expect(catchTest(NaN, 60)).toEqual({ flow: null, error, field: "ml" });
    expect(catchTest(200, Infinity)).toEqual({ flow: null, error, field: "seconds" });
    expect(catchTest(Infinity, 60).error).toBe(error);
  });
  it("rejects a result outside 0.1–50 L/h and says which way it is out", () => {
    expect(catchTest(1, 3600)).toEqual({
      flow: null,
      error:
        "That works out to 0.001 L/h, below the 0.1 L/h minimum for a dripper. Check the seconds and the mL.",
      field: "both",
    });
    expect(catchTest(5000, 60)).toEqual({
      flow: null,
      error:
        "That works out to 300 L/h, above the 50 L/h maximum for a dripper. Enter what one dripper delivered, not the whole zone.",
      field: "both",
    });
  });
});
