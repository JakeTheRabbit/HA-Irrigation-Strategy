import { describe, expect, it } from "vitest";
import { fallbackReading, matchProbe } from "./probe-history";
import { readChoice, writeChoice, DEFAULT_CHOICE } from "./history-explorer";
import type { ProbeSnapshot } from "./comparison-types";
const probe = (entity_id: string, row_label = "Row A", position: number | null = 0): ProbeSnapshot => ({ entity_id, row_label, position, kind: "vwc" });
describe("historical probe identity", () => {
  it("maps a replaced entity to its recorded row, not another currently present probe", () => {
    expect(matchProbe(probe("sensor.new"), [probe("sensor.old"), probe("sensor.new", "Row B", 1)]).entityId).toBe("sensor.old");
  });
  it("uses the same entity, then recorded position, when there is no matching label", () => {
    expect(matchProbe(probe("sensor.same", "renamed"), [probe("sensor.same", "old")]).entityId).toBe("sensor.same");
    expect(matchProbe(probe("sensor.new", "new"), [probe("sensor.old", "old")]).entityId).toBe("sensor.old");
  });
  it("asks for an explicit choice when labels collide and refuses an unrelated override", () => {
    const old = [probe("sensor.a"), probe("sensor.b")];
    expect(matchProbe(probe("sensor.new"), old).entityId).toBeNull();
    expect(matchProbe(probe("sensor.new"), old, "sensor.b").entityId).toBe("sensor.b");
    expect(matchProbe(probe("sensor.new"), old, "sensor.outside").entityId).toBeNull();
  });
  it("keeps independent probe choices and explicit row matches in the address", () => {
    const choice = { ...DEFAULT_CHOICE, probeCompare: { "sensor.a": "last", "sensor.b": "grow_2" }, probeMatch: { "sensor.a": "sensor.old" } };
    expect(readChoice(writeChoice("#/zone/1", choice))).toEqual(choice);
    expect(readChoice("#/zone/1?pc=bad").probeCompare).toEqual({});
  });
});
describe("history fallback priority", () => {
  const hourly = { mean: 45, min: 40, max: 50 }, daily = { mean: 42, min: 30, max: 60 };
  it("prefers recorded values and fills only gaps from hourly statistics, then daily bands", () => {
    expect(fallbackReading(47, hourly, daily)).toMatchObject({ value: 47, source: "recorded history", min: null });
    expect(fallbackReading(null, hourly, daily)).toMatchObject({ value: 45, min: 40, max: 50, source: "hourly statistics" });
    expect(fallbackReading(null, undefined, daily)).toMatchObject({ value: 42, min: 30, max: 60, source: "daily summary" });
  });
  it("preserves a real zero but never invents a zero for missing history", () => {
    expect(fallbackReading(0, hourly, daily).value).toBe(0);
    expect(fallbackReading(null).value).toBeNull();
    expect(fallbackReading(null, { ...hourly, mean: NaN }, daily).source).toBe("daily summary");
  });
});
