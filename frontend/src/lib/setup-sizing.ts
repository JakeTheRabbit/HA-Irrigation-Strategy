import type { SetupDocument, SetupRoom, SetupZone } from "./operator-types";
/** setup_read resolves live hydraulic entities; compare again before a room save can overwrite them. */
export function sizingChangedSince(original: SetupRoom, current: SetupRoom): boolean {
  const keys = [
    "plant_count",
    "substrate_volume",
    "drippers_per_plant",
    "dripper_flow_rate",
  ] as const;
  return original.zones.some((zone) => {
    const now = current.zones.find((z) => z.id === zone.id);
    return !now || keys.some((key) => now[key] !== zone[key]);
  });
}
/** A new zone, its sizing from the integration's one defaults table (`defaults`). An older
 * integration sends none: the sizing then starts blank for the grower to fill in, and the room
 * cannot be saved until it is (setup.tsx). */
export function newZone(id: number, defaults: SetupDocument["sizing_defaults"] = {}): SetupZone {
  return {
    id,
    name: "Zone " + id,
    active: true,
    valve: "",
    vwc_sensors: [],
    ec_sensors: [],
    plant_count: NaN,
    substrate_volume: NaN,
    drippers_per_plant: NaN,
    dripper_flow_rate: NaN,
    ...defaults,
  };
}
