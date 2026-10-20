import type { SetupRoom } from "./operator-types";
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
