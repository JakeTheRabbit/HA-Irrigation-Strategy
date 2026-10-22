import { afterEach, describe, expect, test, vi } from "vitest";
import {
  formatEc,
  formatTemp,
  formatVolume,
  getDisplayUnits,
  parseEc,
  readDisplayUnits,
  setDisplayUnits,
} from "./display-units";

afterEach(() => {
  setDisplayUnits({ ec: "mS/cm", temp: "C", volume: "auto", clock: "24" });
  vi.unstubAllGlobals();
});

describe("display units", () => {
  test("formatEc 2.4 → 1200 ppm (500 scale), 1680 ppm (700 scale)", () => {
    expect(formatEc(2.4, 1)).toBe("2.4 mS/cm");
    setDisplayUnits({ ec: "ppm500" });
    expect(formatEc(2.4, 1)).toBe("1200 ppm");
    setDisplayUnits({ ec: "ppm700" });
    expect(formatEc(2.4, 1)).toBe("1680 ppm");
  });
  test("formatTemp 21.4 C → 70.5 °F", () => {
    expect(formatTemp(21.4, 1)).toBe("21.4 °C");
    setDisplayUnits({ temp: "F" });
    expect(formatTemp(21.4, 1)).toBe("70.5 °F");
  });
  test("formatVolume 24.8 L → 6.6 gal", () => {
    setDisplayUnits({ volume: "L" });
    expect(formatVolume(24.8, 1)).toBe("24.8 L");
    setDisplayUnits({ volume: "gal" });
    expect(formatVolume(24.8, 1)).toBe("6.6 gal");
  });
  test("parseEc(formatEc(2.4, ppm500)) === 2.4", () => {
    setDisplayUnits({ ec: "ppm500" });
    expect(parseEc(formatEc(2.4, 1))).toBe(2.4);
    setDisplayUnits({ ec: "ppm700" });
    expect(parseEc(formatEc(2.4, 1))).toBe(2.4);
    setDisplayUnits({ ec: "mS/cm" });
    expect(parseEc("2.4")).toBe(2.4);
    expect(parseEc("")).toBeNull();
    expect(parseEc("high")).toBeNull();
  });
  test("volume auto follows Home Assistant's unit system, the same answer units.ts gives", () => {
    setDisplayUnits({ volume: "auto" });
    vi.stubGlobal("window", {
      parent: undefined,
      document: { querySelector: () => ({ hass: { config: { unit_system: { volume: "gal" } } } }) },
      location: { origin: "http://ha" },
    });
    expect(getDisplayUnits().volume).toBe("gal");
    vi.unstubAllGlobals();
    // Not embedded and nothing remembered: metric, as units.ts says.
    expect(getDisplayUnits().volume).toBe("L");
  });
  test("reads the room's display attributes; clock arrives as the integer 12 or 24", () => {
    expect(readDisplayUnits({ ec_unit: "ppm700", temp_unit: "F", volume_unit: "gal", clock: 12 }, null)).toEqual({
      ec: "ppm700",
      temp: "F",
      volume: "gal",
      clock: "12",
    });
    expect(readDisplayUnits({ ec_unit: "ppm500", volume_unit: "auto", clock: 24 }, null)).toMatchObject({
      volume: "auto",
      clock: "24",
    });
    // Unknown values fall back to the defaults.
    expect(readDisplayUnits({ ec_unit: "uS", temp_unit: "K", volume_unit: "ml", clock: 13 }, null)).toEqual({
      ec: "mS/cm",
      temp: "C",
      volume: "auto",
      clock: "24",
    });
  });
  test("an integration without the attributes (3.17) falls back to this browser's choice", () => {
    const stored = JSON.stringify({ ec: "ppm500", temp: "F", volume: "L", clock: "12" });
    expect(readDisplayUnits(undefined, stored)).toEqual({ ec: "ppm500", temp: "F", volume: "L", clock: "12" });
    expect(readDisplayUnits({}, "not json")).toEqual({ ec: "mS/cm", temp: "C", volume: "auto", clock: "24" });
    // A room attribute wins over the browser's choice.
    expect(readDisplayUnits({ ec_unit: "mS/cm" }, stored).ec).toBe("mS/cm");
  });
});
