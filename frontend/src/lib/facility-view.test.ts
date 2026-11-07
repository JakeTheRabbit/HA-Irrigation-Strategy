import { describe, expect, test } from "vitest";
import { tankReadingText } from "./facility-view";

describe("tankReadingText", () => {
  test("the feed tank card prints Home Assistant's long floats rounded", () => {
    expect(
      tankReadingText({ ph: 6.15000009536743, ec: 3.06599998474121, temperature: 19.8333996337891 }),
    ).toEqual({ ph: "6.15", ec: "3.07", temperature: "19.8 °C" });
  });
  test("a missing reading stays missing", () => {
    expect(tankReadingText({ ph: null, ec: null, temperature: null })).toEqual({
      ph: null,
      ec: null,
      temperature: null,
    });
  });
});
