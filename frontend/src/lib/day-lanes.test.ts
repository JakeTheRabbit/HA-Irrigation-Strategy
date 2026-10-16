import { describe, expect, it } from "vitest";
import { onSpans } from "./day-lanes";

describe("day lanes", () => {
  it("draws a device's on spans inside the day, joined where they touch", () => {
    const rows = [
      { state: "off", time: 0 },
      { state: "on", time: 10 },
      { state: "open", time: 20 },
      { state: "off", time: 30 },
      { state: "on", time: 90 },
    ];
    expect(onSpans(rows, 5, 100)).toEqual([
      { start: 10, end: 30 },
      { start: 90, end: 100 },
    ]);
    expect(onSpans([], 0, 10)).toEqual([]);
  });
});
