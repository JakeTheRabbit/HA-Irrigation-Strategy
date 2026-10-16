import { descriptor, numeric } from "./model";
import type { Room, States } from "./types";

/** The room's Hardware panel switch: off until an administrator sets it to on. */
export const hardwarePanelId = (prefix: string) =>
  `switch.crop_steering_${prefix}manual_hardware_enabled`;

/** Dew point (°C) from air temperature (°C) and relative humidity (%), by the Magnus formula
 * (b = 17.62, c = 243.12 °C). Null outside 0–100 % or without both readings. */
export function dewPoint(celsius: number | null, rh: number | null): number | null {
  if (celsius === null || rh === null || !(rh > 0) || rh > 100) return null;
  const gamma = Math.log(rh / 100) + (17.62 * celsius) / (243.12 + celsius);
  return (243.12 * gamma) / (17.62 - gamma);
}

export interface ClimateReading {
  key: "temperature" | "humidity" | "vpd" | "dew_point";
  label: string;
  value: number | null;
  unit: string;
  digits: number;
  /** The band the grow plan gives it today (Plan › Grow planner reference rows), else null. */
  band: [number, number] | null;
}

const toCelsius = (value: number | null, unit: unknown) =>
  value === null ? null : unit === "°F" ? ((value - 32) * 5) / 9 : value;

/** The room's mapped climate sensors as readings, and the dew point when both temperature and
 * humidity are mapped. Empty when the room maps none of them. */
export function climateReadings(
  states: States,
  room: Room,
  bands: Partial<Record<ClimateReading["key"], [number, number]>> = {},
): ClimateReading[] {
  const mapped = descriptor(states, room)?.attributes ?? {};
  const entity = (key: string) =>
    typeof mapped[key] === "string" && mapped[key] ? states[String(mapped[key])] : undefined;
  const air = entity("temperature_sensor"),
    humidity = entity("humidity_sensor"),
    vpd = entity("vpd_sensor");
  const unit = String(air?.attributes.unit_of_measurement || "°C");
  const list: ClimateReading[] = [];
  const add = (reading: Omit<ClimateReading, "band">) =>
    list.push({ ...reading, band: bands[reading.key] ?? null });
  if (air) add({ key: "temperature", label: "Air temperature", value: numeric(air), unit, digits: 1 });
  if (humidity) add({ key: "humidity", label: "Humidity", value: numeric(humidity), unit: "%", digits: 0 });
  if (vpd) add({ key: "vpd", label: "VPD", value: numeric(vpd), unit: " kPa", digits: 2 });
  if (air && humidity) {
    const dew = dewPoint(toCelsius(numeric(air), unit), numeric(humidity));
    add({
      key: "dew_point",
      label: "Dew point",
      value: dew === null ? null : unit === "°F" ? (dew * 9) / 5 + 32 : dew,
      unit,
      digits: 1,
    });
  }
  return list;
}

/** The zone's mapped root-zone temperature probe (Equipment › Setup), else null. */
export function rootZoneSensor(states: States, room: Room, zone: number): string | null {
  const map = descriptor(states, room)?.attributes.substrate_temperature_sensors;
  const id = map && typeof map === "object" ? (map as Record<string, unknown>)[String(zone)] : null;
  return typeof id === "string" && id && states[id] ? id : null;
}

export interface MappedDevice {
  role: "valve" | "pump" | "mainline" | "lights" | "tank_fill";
  label: string;
  entityId: string;
  on: boolean | null;
  since: string | null;
}
/** What the zone's water passes through and the room's lights, as the room maps them: each one's
 * state now and since when. Read only. */
export function mappedDevices(states: States, room: Room, zone: number): MappedDevice[] {
  const map = descriptor(states, room)?.attributes ?? {};
  const valves = map.valves && typeof map.valves === "object" ? (map.valves as Record<string, unknown>) : {};
  const rows: [MappedDevice["role"], string, unknown][] = [
    ["valve", "Zone valve", valves[String(zone)]],
    ["pump", "Pump", map.pump],
    ["mainline", "Main line", map.mainline],
    ["lights", "Lights", map.light_entity],
    ["tank_fill", "Tank fill", map.tank_fill_entity],
  ];
  return rows.flatMap(([role, label, id]) => {
    if (typeof id !== "string" || !id) return [];
    const entity = states[id];
    const state = entity?.state;
    return [
      {
        role,
        label,
        entityId: id,
        on: state === "on" || state === "open" ? true : state === "off" || state === "closed" ? false : null,
        since: entity?.last_changed ?? null,
      },
    ];
  });
}
