import { afterEach, describe, expect, it } from "vitest";
import {
  DISPLAY_DEFAULTS,
  DISPLAY_ROWS,
  UNIT_KEYS,
  demoDisplay,
  displayEntityId,
  readDisplay,
  storedUnit,
  unitExamples,
  unitMode,
} from "./display";
import { formatEc, getDisplayUnits, parseEc, readDisplayUnits, setDisplayUnits } from "./display-units";
import { createDemo } from "./demo";
import { demoParityStatus } from "./parity-demo/status";
import { buildRoom, discoverRooms } from "./model";
import type { EntityState } from "./types";

afterEach(() => setDisplayUnits({ ec: "mS/cm", temp: "C", volume: "auto", clock: "24" }));

const entity = (state: string, attributes: Record<string, unknown> = {}): EntityState => ({
  entity_id: displayEntityId("f2_"),
  state,
  attributes,
});

describe("room display options", () => {
  it("reads every option off without a store, as the dashboard always was", () => {
    expect(readDisplay(undefined)).toEqual({
      available: false,
      units: false,
      revision: 0,
      options: DISPLAY_DEFAULTS,
    });
    const panels = Object.entries(DISPLAY_DEFAULTS).filter(([key]) => !(UNIT_KEYS as readonly string[]).includes(key));
    expect(panels.every(([, v]) => v === false || v === "cards")).toBe(true);
  });
  it("reads an option the sensor carries, and the default for a missing or bad one", () => {
    const read = readDisplay(
      entity("3", { today_tank_readout: true, today_zone_layout: "grid", show_camera: "yes" }),
    );
    expect(read.available).toBe(true);
    expect(read.revision).toBe(3);
    expect(read.options).toEqual({ ...DISPLAY_DEFAULTS, today_tank_readout: true });
  });
  it("is unavailable while the sensor is unavailable", () => {
    expect(readDisplay(entity("unavailable")).available).toBe(false);
  });
  it("lists each row once, with STE help", () => {
    const keys = DISPLAY_ROWS.map((row) => row.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const row of DISPLAY_ROWS) {
      expect(!!row.entity || row.key in DISPLAY_DEFAULTS).toBe(true);
      expect(row.copy.tooltip.length).toBeGreaterThan(0);
    }
  });
  it("does not offer Zones as, which the room page no longer reads (the stored key stays)", () => {
    expect(DISPLAY_ROWS.some((row) => row.key === "today_zone_layout")).toBe(false);
    expect("today_zone_layout" in DISPLAY_DEFAULTS).toBe(true);
  });
  it("turns on the demo's options from ?display=", () => {
    const states = { [displayEntityId("f2_")]: entity("0", { ...DISPLAY_DEFAULTS }) };
    const on = demoDisplay(states, "today_tank_readout,nonsense");
    expect(on[displayEntityId("f2_")].attributes.today_tank_readout).toBe(true);
    expect(demoDisplay(states, null)).toBe(states);
    const all = readDisplay(demoDisplay(states, "all")[displayEntityId("f2_")]).options;
    expect(all.today_zone_layout).toBe("table");
  });
  it("turns on no unit from ?display=all (units are choices, not panels)", () => {
    const states = { [displayEntityId("f2_")]: entity("0", { ...DISPLAY_DEFAULTS }) };
    const all = readDisplay(demoDisplay(states, "all")[displayEntityId("f2_")]).options;
    expect([all.ec_unit, all.temp_unit, all.volume_unit, all.clock]).toEqual(["mS/cm", "C", "auto", 24]);
  });
});

describe("display units in the room's display options", () => {
  it("old display entity reads units as mS/cm, C, L, 24", () => {
    const old = entity("3", { today_tank_readout: true });
    const read = readDisplay(old);
    expect(read.units).toBe(false);
    expect([read.options.ec_unit, read.options.temp_unit, read.options.volume_unit, read.options.clock]).toEqual([
      "mS/cm",
      "C",
      "auto",
      24,
    ]);
    setDisplayUnits(readDisplayUnits(old.attributes, null));
    // "auto" without Home Assistant's unit system or a sizing choice reads as litres.
    expect(getDisplayUnits()).toEqual({ ec: "mS/cm", temp: "C", volume: "L", clock: "24" });
  });
  it("reads the units a 3.18 sensor carries, and refuses a value it does not take", () => {
    const read = readDisplay(entity("4", { ec_unit: "ppm500", temp_unit: "F", volume_unit: "gal", clock: 12 }));
    expect(read.units).toBe(true);
    expect(read.options).toMatchObject({ ec_unit: "ppm500", temp_unit: "F", volume_unit: "gal", clock: 12 });
    const bad = readDisplay(entity("4", { ec_unit: "ppm", temp_unit: "C", volume_unit: "L", clock: "12" }));
    expect(bad.options).toMatchObject({ ec_unit: "mS/cm", clock: 24 });
  });
  it("unitExamples change after setDisplayUnits", () => {
    const states = createDemo(Date.UTC(2026, 9, 23, 3, 0));
    const room = buildRoom(states, discoverRooms(states)[0]);
    setDisplayUnits({ ec: "mS/cm", temp: "C", volume: "L", clock: "24" });
    const before = unitExamples(states, room);
    expect(before.ec).toMatch(/\d mS\/cm/);
    expect(before.temp).toMatch(/^Root zone \d+(\.\d+)? °C$/);
    expect(before.volume).toMatch(/\d L$/);
    expect(before.clock).toMatch(/ \d{2}:00$/);
    setDisplayUnits({ ec: "ppm500", temp: "F", volume: "gal", clock: "12" });
    const after = unitExamples(states, room);
    expect(after.ec).toMatch(/\d ppm/);
    expect(after.ec).not.toMatch(/mS\/cm/);
    expect(after.temp).toMatch(/°F/);
    expect(after.volume).toMatch(/\d gal$/);
    expect(after.clock).toMatch(/\d{1,2}:00 [ap]m/);
  });
  it("shows a reading with float noise at the source's precision", () => {
    const states = createDemo(Date.UTC(2026, 9, 23, 3, 0));
    const room = buildRoom(states, discoverRooms(states)[0]);
    const config = states[`sensor.crop_steering_${room.room.prefix}engine_config`].attributes;
    const root = (config.substrate_temperature_sensors as Record<string, string>)["1"];
    states[root] = { ...states[root], state: String(21.8 + 0.1) };
    setDisplayUnits({ temp: "C" });
    expect(unitExamples(states, room).temp).toBe("Root zone 21.9 °C");
  });
  it("shows a root zone that reads in °F, converted, rather than claiming no reading", () => {
    const states = createDemo(Date.UTC(2026, 9, 23, 3, 0));
    const room = buildRoom(states, discoverRooms(states)[0]);
    const config = states[`sensor.crop_steering_${room.room.prefix}engine_config`].attributes;
    const root = (config.substrate_temperature_sensors as Record<string, string>)["1"];
    states[root] = {
      ...states[root],
      state: "70.2",
      attributes: { ...states[root].attributes, unit_of_measurement: "°F" },
    };
    setDisplayUnits({ temp: "C" });
    expect(unitExamples(states, room).temp).toBe("Root zone 21.2 °C");
    setDisplayUnits({ temp: "F" });
    expect(unitExamples(states, room).temp).toBe("Root zone 70.2 °F");
  });
  it("unitMode saves in the room, in this browser on 3.17, and not at all offline or unavailable", () => {
    const room = entity("4", { ec_unit: "mS/cm", temp_unit: "C", volume_unit: "auto", clock: 24 });
    const old = entity("3", {});
    expect(unitMode(room, "live")).toBe("room");
    expect(unitMode(room, "demo")).toBe("room");
    expect(unitMode(old, "live")).toBe("local");
    // No display sensor at all: an integration older still.
    expect(unitMode(undefined, "live")).toBe("local");
    // Not loaded yet or gone: never this browser, which the room's units would later override.
    for (const connection of ["connecting", "offline"] as const) {
      expect(unitMode(undefined, connection)).toBe("offline");
      expect(unitMode(old, connection)).toBe("offline");
    }
    expect(unitMode(entity("unavailable", {}), "live")).toBe("unavailable");
  });
  it('storedUnit keeps "auto" as the room or this browser stores it', () => {
    const room = readDisplay(entity("4", { ec_unit: "mS/cm", temp_unit: "C", volume_unit: "auto", clock: 24 }));
    expect(storedUnit(room, null, "volume_unit")).toBe("auto");
    expect(storedUnit(readDisplay(entity("4", { ...room.options, volume_unit: "gal" })), null, "volume_unit")).toBe("gal");
    // 3.17: this browser's choice, unresolved.
    const old = readDisplay(entity("3", {}));
    expect(storedUnit(old, null, "volume_unit")).toBe("auto");
    expect(storedUnit(old, JSON.stringify({ volume: "gal", clock: "12" }), "volume_unit")).toBe("gal");
    expect(storedUnit(old, JSON.stringify({ volume: "gal", clock: "12" }), "clock")).toBe(12);
    expect(storedUnit(old, "{bad", "ec_unit")).toBe("mS/cm");
  });
  it("formatted ppm value parses back to the stored mS/cm", () => {
    for (const ec of ["ppm500", "ppm700"] as const) {
      setDisplayUnits({ ec });
      for (const ms of [0.8, 1.2, 2.4, 3.1]) expect(parseEc(formatEc(ms, 1))).toBe(ms);
    }
  });
});

describe("the demo's display store", () => {
  it("keeps the units on 3.18 and has none on 3.17", () => {
    const old = createDemo();
    expect(readDisplay(old[displayEntityId("")]).units).toBe(false);
    expect(readDisplay(demoParityStatus(old, Date.now())[displayEntityId("")]).units).toBe(true);
  });
});
