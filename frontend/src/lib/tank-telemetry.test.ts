import { describe, expect, it } from "vitest";
import { createDemo } from "./demo";
import { tankTelemetry } from "./tank-telemetry";
const room = { id: "room:", name: "Flower 2", prefix: "" };
const now = Date.parse("2026-09-08T08:00:00Z");
describe("room tank telemetry", () => {
  it("finds renamed HA descriptors by room prefix", () => {
    const states = createDemo(now);
    states["sensor.crop_steering_system_engine_config"] = {
      ...states["sensor.crop_steering_engine_config"],
      entity_id: "sensor.crop_steering_system_engine_config",
    };
    delete states["sensor.crop_steering_engine_config"];
    expect(tankTelemetry(states, room, now).pump.on).toBe(true);
  });
  it("uses a full native datetime helper's epoch timestamp, not browser timezone", () => {
    const states = createDemo(now);
    states["sensor.crop_steering_engine_config"].attributes.tank_last_fill_sensor =
      "input_datetime.filled";
    states["input_datetime.filled"] = {
      entity_id: "input_datetime.filled",
      state: "2026-09-08 18:00:00",
      attributes: { has_date: true, has_time: true, timestamp: (now - 7200000) / 1000 },
    };
    expect(tankTelemetry(states, room, now).lastFill.timestamp).toBe("2026-09-08T06:00:00.000Z");
    states["input_datetime.filled"].attributes.has_date = false;
    expect(tankTelemetry(states, room, now).lastFill.timestamp).toBeNull();
  });
  it("reads isolated mappings, including pump and recorded fill", () => {
    const states = createDemo(now);
    const tank = tankTelemetry(states, room, now);
    expect(tank.level.value).toBe(42);
    expect(tank.pump.on).toBe(true);
    expect(tank.lastFill.timestamp).toBe("2026-09-08T06:00:00.000Z");
    expect(tankTelemetry(states, { ...room, prefix: "f1_" }, now).level.value).toBe(72);
  });
  it("does not guess feed, ambient temperature or other-room mappings", () => {
    const states = createDemo(now);
    states["sensor.crop_steering_engine_config"].attributes = {
      feed_ec_sensor: "sensor.demo_tank_ec",
      temperature_sensor: "sensor.demo_tank_temperature",
    };
    const tank = tankTelemetry(states, room, now);
    expect(tank.ec.issue).toBe("Not mapped");
    expect(tank.temperature.value).toBeNull();
    expect(tank.pump.on).toBeNull();
    expect(tank.lastFill.timestamp).toBeNull();
  });
  it.each(["unknown", "unavailable", "", "NaN", "101", "-1"])(
    "does not draw an invalid tank percentage: %s",
    (state) => {
      const states = createDemo(now);
      states["sensor.demo_tank_level"].state = state;
      expect(tankTelemetry(states, room, now).level.value).toBeNull();
    },
  );
  it("requires percentage units and keeps temperature source units", () => {
    const states = createDemo(now);
    states["sensor.demo_tank_level"].attributes.unit_of_measurement = "L";
    states["sensor.demo_tank_temperature"].attributes.unit_of_measurement = "°F";
    expect(tankTelemetry(states, room, now).level.issue).toBe("Check units");
    expect(tankTelemetry(states, room, now).temperature.unit).toBe("°F");
  });
  it.each(["unavailable", "2026-09-08", "2026-09-08T06:00:00", "2027-01-01T00:00:00Z"])(
    "never substitutes last_changed for invalid fill timestamp: %s",
    (state) => {
      const states = createDemo(now);
      states["sensor.demo_tank_last_fill"].state = state;
      expect(tankTelemetry(states, room, now).lastFill.timestamp).toBeNull();
    },
  );
  it("distinguishes unknown from off", () => {
    const states = createDemo(now);
    states["switch.demo_pump"].state = "unavailable";
    expect(tankTelemetry(states, room, now).pump.on).toBeNull();
    expect(tankTelemetry(states, room, now).fill.on).toBe(false);
  });
});
