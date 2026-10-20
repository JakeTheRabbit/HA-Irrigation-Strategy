import type { Room, States } from "./types";
import { descriptor } from "./model";

export interface TankReading {
  entityId: string | null;
  value: number | null;
  unit: string;
  issue: string | null;
}

/** When a last-fill entity's state says the tank was filled (epoch ms): a date-and-time helper's
 * timestamp attribute, or a timestamp sensor's dated, time-zone-aware state. Null otherwise. */
export function fillTime(
  entityId: string,
  state: string,
  attributes?: Record<string, unknown>,
): number | null {
  const raw = state || "";
  const time =
    entityId.startsWith("input_datetime.") &&
    attributes?.has_date === true &&
    attributes?.has_time === true &&
    typeof attributes.timestamp === "number" &&
    !["unknown", "unavailable", ""].includes(raw)
      ? attributes.timestamp * 1000
      : /^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/i.test(raw)
        ? Date.parse(raw)
        : NaN;
  return time > 0 && Number.isFinite(new Date(time).getTime()) ? time : null;
}

export function tankTelemetry(states: States, room: Room, now = Date.now()) {
  const config = descriptor(states, room)?.attributes || {};
  const mapped = (key: string) =>
    typeof config[key] === "string" && config[key] ? String(config[key]) : null;
  const reading = (key: string, units: string[], min = -Infinity, max = Infinity): TankReading => {
    const entityId = mapped(key),
      entity = entityId ? states[entityId] : undefined;
    const unit = String(entity?.attributes.unit_of_measurement || "");
    const value = entity?.state.trim() ? Number(entity.state) : NaN;
    const issue = !entityId
      ? "Not mapped"
      : !Number.isFinite(value)
        ? "Unavailable"
        : !units.includes(unit.toLowerCase())
          ? "Check units"
          : value < min || value > max
            ? "Out of range"
            : null;
    return { entityId, value: issue ? null : value, unit, issue };
  };
  const binary = (key: string) => {
    const entityId = mapped(key),
      state = entityId ? states[entityId]?.state : undefined;
    return {
      entityId,
      on: state === "on" ? true : state === "off" ? false : null,
      issue: !entityId ? "Not mapped" : !["on", "off"].includes(state || "") ? "Unavailable" : null,
    };
  };
  const fillId = mapped("tank_last_fill_sensor");
  const fillEntity = fillId ? states[fillId] : undefined;
  const time = fillId ? fillTime(fillId, fillEntity?.state ?? "", fillEntity?.attributes) : null;
  const fillIssue = !fillId
    ? "Not mapped"
    : time === null
      ? "Unavailable"
      : time > now
        ? "Future timestamp"
        : null;
  return {
    level: reading("water_level_sensor", ["%"], 0, 100),
    ec: reading("tank_ec_sensor", ["ms/cm", "ds/m", "µs/cm", "μs/cm", "us/cm"], 0),
    ph: reading("tank_ph_sensor", ["ph", ""], 0, 14),
    temperature: reading("tank_temperature_sensor", ["°c", "°f", "k"]),
    pump: binary("pump"),
    fill: binary("tank_fill_entity"),
    lastFill: {
      entityId: fillId,
      timestamp: fillIssue || time === null ? null : new Date(time).toISOString(),
      issue: fillIssue,
    },
  };
}
