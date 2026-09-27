import type { Change, Zone } from "./types";

/** A room's switch over its zones, as Home Assistant's entities card has its header toggle: on
 * while any zone is on, off once every zone is paused. */
export interface AllZones {
  /** Null when no zone's switch can be read. */
  checked: boolean | null;
  /** Zones switched on, of `known`: those whose switch reads on or off. */
  on: number;
  known: number;
}

export function allZones(zones: Zone[]): AllZones {
  const known = zones.filter((zone) => zone.enabledEntity && zone.enabled !== null);
  const on = known.filter((zone) => zone.enabled).length;
  return { checked: known.length ? on > 0 : null, on, known: known.length };
}

/** Switching it flips every zone to the same state, a zone paused on purpose included: one change
 * per zone that reads the other way, for the review. */
export function allZonesChanges(
  zones: Zone[],
  enabled: boolean,
): { change: Change; label: string; before: string; after: string }[] {
  return zones
    .filter((zone) => zone.enabledEntity && zone.enabled === !enabled)
    .map((zone) => ({
      change: { entityId: zone.enabledEntity!, value: enabled },
      label: `${zone.name} scheduling`,
      before: enabled ? "Paused" : "Enabled",
      after: enabled ? "Enabled" : "Paused",
    }));
}
