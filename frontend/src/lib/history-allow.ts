import { SUPPLY_SENSOR, zoneMeter } from "./flow-check";
import { explorerSensors } from "./history-explorer";
import { descriptor } from "./model";
import { roomProbeIds } from "./probes";
import { TANK_KEYS } from "./tank-level";
import type { RoomView, States } from "./types";

/** Every entity whose recorded history the dashboard reads for the selected room, the one list all
 * its history reads check: the room's own entities, its zones' probes and valves, and what its
 * descriptor maps for display (the tank and its probes, the pump, the main line, the lights), with
 * every sensor the history explorer offers and the flow meters the integration's supply maps to its
 * zones (History › Water & flow). Another room's entities are never in it. */
export function allowedHistoryIds(room: RoomView, states: States): Set<string> {
  const mapped = descriptor(states, room.room)?.attributes;
  const mappedIds = [
    ...Object.values(TANK_KEYS),
    "tank_ec_sensor",
    "tank_ph_sensor",
    "mainline",
    "light_entity",
  ].flatMap((key) => {
    const id = mapped?.[key];
    return typeof id === "string" && id ? [id] : [];
  });
  return new Set([
    ...room.entities.map((entity) => entity.entity_id),
    ...roomProbeIds(room.zones, states),
    ...room.zones.flatMap((zone) => (zone.valveEntity ? [zone.valveEntity] : [])),
    ...mappedIds,
    ...explorerSensors(room, states).map((sensor) => sensor.entityId),
    ...room.zones.flatMap((zone) => {
      const meter = zoneMeter(states[SUPPLY_SENSOR]?.attributes, "room:" + room.room.prefix, zone.id, mapped?.pump);
      return meter ? [meter] : [];
    }),
  ]);
}
