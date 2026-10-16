import { describe, expect, it } from "vitest";
import { climateReadings, dewPoint, mappedDevices, rootZoneSensor } from "./zone-extras";
import type { Room, States } from "./types";

const room = { id: "room:f2_", prefix: "f2_", name: "F2" } as Room;
const put = (attributes: Record<string, unknown>, extra: States = {}): States => ({
  "sensor.crop_steering_f2_engine_config": {
    entity_id: "sensor.crop_steering_f2_engine_config",
    state: "ready",
    attributes: { prefix: "f2_", ...attributes },
  },
  ...extra,
});
const sensor = (id: string, state: string, unit = ""): States => ({
  [id]: { entity_id: id, state, attributes: { unit_of_measurement: unit } },
});

describe("zone page extras", () => {
  it("works out the dew point by the Magnus formula", () => {
    expect(dewPoint(25, 60)!).toBeCloseTo(16.69, 1);
    expect(dewPoint(25, 0)).toBeNull();
    expect(dewPoint(null, 50)).toBeNull();
  });
  it("shows only the mapped climate sensors, and the dew point when both are mapped", () => {
    expect(climateReadings(put({}), room)).toEqual([]);
    const states = put(
      { temperature_sensor: "sensor.t", humidity_sensor: "sensor.h" },
      { ...sensor("sensor.t", "25", "°C"), ...sensor("sensor.h", "60", "%") },
    );
    const keys = climateReadings(states, room, { humidity: [55, 65] }).map((r) => [r.key, r.band]);
    expect(keys).toEqual([
      ["temperature", null],
      ["humidity", [55, 65]],
      ["dew_point", null],
    ]);
  });
  it("finds the zone's root-zone probe only when mapped and present", () => {
    const states = put(
      { substrate_temperature_sensors: { "1": "sensor.root1" } },
      sensor("sensor.root1", "21", "°C"),
    );
    expect(rootZoneSensor(states, room, 1)).toBe("sensor.root1");
    expect(rootZoneSensor(states, room, 2)).toBeNull();
  });
  it("lists the mapped devices of the zone with their state", () => {
    const states = put(
      { valves: { 1: "switch.v1" }, pump: "switch.pump", mainline: "" },
      { ...sensor("switch.v1", "on"), ...sensor("switch.pump", "off") },
    );
    expect(mappedDevices(states, room, 1).map((d) => [d.role, d.on])).toEqual([
      ["valve", true],
      ["pump", false],
    ]);
  });
});


it("shows DLI only from the room's optional mapped sensor and preserves its reported unit", () => {
  expect(climateReadings(put({}), room).some((r) => r.key === "dli")).toBe(false);
  const states = put({ dli_sensor: "sensor.daily_light" }, sensor("sensor.daily_light", "24.5", "mol/m²/day"));
  expect(climateReadings(states, room, { dli: [20, 30] })).toContainEqual({
    key: "dli", label: "DLI", value: 24.5, unit: "mol/m²/day", digits: 1, band: [20, 30],
  });
});
