import { describe, expect, it } from "vitest";
import {
  LITRES_PER_US_GALLON,
  SIZING_BOUNDS,
  SIZING_UNITS,
  displayNumber,
  fromMetric,
  initialUnitSystem,
  metricNote,
  rememberedUnitSystem,
  reviewValue,
  sizingError,
  sizingLabel,
  toMetric,
  unitSystemFromHass,
} from "./units";

const gal = SIZING_UNITS.volume.us,
  litres = SIZING_UNITS.volume.metric,
  gph = SIZING_UNITS.flow.us,
  lph = SIZING_UNITS.flow.metric;

describe("sizing unit conversion", () => {
  it("uses the exact US gallon and never a rounded factor", () => {
    expect(LITRES_PER_US_GALLON).toBe(3.785411784);
    expect(gal.factor).toBe(3.785411784);
    expect(gph.factor).toBe(3.785411784);
    expect(litres.factor).toBe(1);
    expect(lph.factor).toBe(1);
  });
  it("converts what is typed to the metric value the draft holds, without display rounding", () => {
    expect(toMetric(1, gal)).toBe(3.785411784);
    expect(toMetric(5, gal)).toBe(18.92705892);
    expect(toMetric(0.5, gph)).toBe(1.892705892);
    expect(toMetric(2, gph)).toBe(7.570823568);
  });
  it("leaves metric entries exactly as typed", () => {
    expect(toMetric(8, litres)).toBe(8);
    expect(toMetric(0.1, litres)).toBe(0.1);
    expect(toMetric(2.35, lph)).toBe(2.35);
  });
  it("keeps an unfinished entry invalid instead of inventing a number", () => {
    expect(toMetric(NaN, gal)).toBeNaN();
    expect(toMetric(Infinity, gal)).toBeNaN();
    expect(fromMetric(NaN, gal)).toBeNaN();
  });
  it("shows a stored metric value in the chosen unit and round-trips it", () => {
    expect(fromMetric(3.785411784, gal)).toBeCloseTo(1, 12);
    expect(fromMetric(18.9, gal)).toBeCloseTo(4.9928518, 6);
    expect(fromMetric(6, litres)).toBe(6);
    expect(toMetric(fromMetric(18.92705892, gal), gal)).toBe(18.92705892);
  });
  it("rounds for display only, trimming trailing zeros", () => {
    expect(displayNumber(4.992851478)).toBe("4.993");
    expect(displayNumber(5)).toBe("5");
    expect(displayNumber(0.65)).toBe("0.65");
    expect(displayNumber(18.92705892, 2)).toBe("18.93");
    expect(displayNumber(NaN)).toBe("");
  });
});

describe("sizing field text", () => {
  it("names the unit being typed in each label", () => {
    expect(sizingLabel("substrate_volume", litres)).toBe("Pot volume · L per plant");
    expect(sizingLabel("substrate_volume", gal)).toBe("Pot volume · US gal per plant");
    expect(sizingLabel("dripper_flow_rate", lph)).toBe("Dripper flow · L/h each");
    expect(sizingLabel("dripper_flow_rate", gph)).toBe("Dripper flow · US GPH each");
  });
  it("shows the metric value that will be saved beside a non-metric entry only", () => {
    expect(metricNote(18.92705892, "substrate_volume", gal)).toBe(
      "= 18.927 L per plant, saved in litres",
    );
    expect(metricNote(1.892705892, "dripper_flow_rate", gph)).toBe(
      "= 1.893 L/h each, saved in litres per hour",
    );
    expect(metricNote(6, "substrate_volume", litres)).toBeNull();
    expect(metricNote(NaN, "substrate_volume", gal)).toBeNull();
  });
  it("reviews the metric value being saved, with the typed unit beside it when that differs", () => {
    expect(reviewValue(6, "substrate_volume", litres)).toBe("6 L");
    expect(reviewValue(18.92705892, "substrate_volume", gal)).toBe("18.927 L (5 US gal)");
    expect(reviewValue(7.570823568, "dripper_flow_rate", gph)).toBe("7.571 L/h (2 US GPH)");
    expect(reviewValue(4, "dripper_flow_rate", lph)).toBe("4 L/h");
  });
});

describe("sizing bounds", () => {
  it("mirrors the metric limits the integration enforces", () => {
    expect(SIZING_BOUNDS).toEqual({
      substrate_volume: { min: 0.1, max: 200 },
      dripper_flow_rate: { min: 0.1, max: 50 },
    });
  });
  it("accepts everything the integration accepts, whatever unit it was typed in", () => {
    expect(sizingError(0.1, "substrate_volume", litres)).toBe("");
    expect(sizingError(200, "substrate_volume", gal)).toBe("");
    expect(sizingError(toMetric(5, gal), "substrate_volume", gal)).toBe("");
    expect(sizingError(50, "dripper_flow_rate", gph)).toBe("");
  });
  it("reports a metric bounds error in litres", () => {
    expect(sizingError(250, "substrate_volume", litres)).toBe("Pot volume must be 0.1–200 L.");
    expect(sizingError(0, "dripper_flow_rate", lph)).toBe("Dripper flow must be 0.1–50 L/h.");
  });
  it("reports a bounds error in the unit being typed, never outside the real limits", () => {
    // 0.1 L = 0.02642 US gal and 200 L = 52.8344 US gal: the shown range rounds inwards.
    expect(sizingError(toMetric(60, gal), "substrate_volume", gal)).toBe(
      "Pot volume must be 0.027–52.834 US gal (0.1–200 L).",
    );
    expect(sizingError(toMetric(20, gph), "dripper_flow_rate", gph)).toBe(
      "Dripper flow must be 0.027–13.208 US GPH (0.1–50 L/h).",
    );
    expect(sizingError(toMetric(0.027, gal), "substrate_volume", gal)).toBe("");
    expect(sizingError(toMetric(52.834, gal), "substrate_volume", gal)).toBe("");
  });
  it("asks for a number in the unit being typed when the entry is blank or not a number", () => {
    expect(sizingError(NaN, "substrate_volume", gal)).toBe("Enter the pot volume in US gal.");
    expect(sizingError(NaN, "dripper_flow_rate", lph)).toBe("Enter the dripper flow in L/h.");
  });
});

describe("default unit system", () => {
  it("reads the volume unit of an embedding Home Assistant", () => {
    expect(unitSystemFromHass({ config: { unit_system: { volume: "gal" } } })).toBe("us");
    expect(unitSystemFromHass({ config: { unit_system: { volume: "L" } } })).toBe("metric");
  });
  it("does not guess when Home Assistant's configuration is not readable", () => {
    expect(unitSystemFromHass(undefined)).toBeNull();
    expect(unitSystemFromHass({ kioskMode: true })).toBeNull();
    expect(unitSystemFromHass({ config: { unit_system: { volume: "fl. oz." } } })).toBeNull();
    expect(unitSystemFromHass({ config: null })).toBeNull();
  });
  it("accepts only known remembered choices", () => {
    expect(rememberedUnitSystem("us")).toBe("us");
    expect(rememberedUnitSystem("metric")).toBe("metric");
    expect(rememberedUnitSystem("imperial")).toBeNull();
    expect(rememberedUnitSystem(null)).toBeNull();
  });
  it("defaults from Home Assistant, then the remembered choice, then metric", () => {
    expect(initialUnitSystem("us", "metric")).toBe("us");
    expect(initialUnitSystem("metric", "us")).toBe("metric");
    expect(initialUnitSystem(null, "us")).toBe("us");
    expect(initialUnitSystem(null, "nonsense")).toBe("metric");
    expect(initialUnitSystem(null, null)).toBe("metric");
  });
});
