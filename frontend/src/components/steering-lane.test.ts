import { describe, expect, it } from "vitest";
import { ecDomain, vwcDomain } from "./steering-lane";
import { extractAlertCodes } from "./alert-code-text";

describe("steering lane domains", () => {
  it("pads VWC domains to at least ten points inside 0..100", () => {
    expect(vwcDomain([])).toEqual([30, 80]);
    const [lo, hi] = vwcDomain([58, 62]);
    expect(hi - lo).toBeGreaterThanOrEqual(10);
    expect(lo).toBeGreaterThanOrEqual(0);
    expect(hi).toBeLessThanOrEqual(100);
  });

  it("computes a clean comparable pore EC domain across zones", () => {
    expect(ecDomain([])).toEqual([0, 6]);
    const [lo, hi] = ecDomain([2.5, 3.5, 4.1]);
    expect(lo).toBeGreaterThanOrEqual(0);
    expect(lo).toBeLessThanOrEqual(2.5);
    expect(hi).toBeGreaterThanOrEqual(4.1);
    expect(hi - lo).toBeGreaterThanOrEqual(1.5);
  });
});

describe("alert code extraction", () => {
  it("extracts unique CS-xxx codes from fault messages", () => {
    expect(extractAlertCodes("URGENT, the zone is dry (CS-207)")).toEqual(["CS-207"]);
    expect(extractAlertCodes("CS-710 and CS-207 and CS-710 again")).toEqual(["CS-710", "CS-207"]);
    expect(extractAlertCodes("No codes in this line")).toEqual([]);
  });
});
