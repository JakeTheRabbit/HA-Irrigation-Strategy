import { type Feature, type ControlRow, type Cell } from "./features";
import type { Controller } from "./types";
import type { Page } from "./routes";
export type ConfigOwner =
  | "irrigation"
  | "equipment"
  | "dosing"
  | "probes"
  | "notifications"
  | "ai"
  | "preferences"
  | "history"
  | "zone"
  | "header";
const destinations: Record<ConfigOwner, { page: Page; label: string }> = {
  irrigation: { page: "plan/targets", label: "Irrigation" },
  equipment: { page: "equipment/setup", label: "Rooms & zones" },
  dosing: { page: "equipment/dosing", label: "Dosing settings" },
  probes: { page: "equipment/probes", label: "Probes" },
  notifications: { page: "settings/notifications", label: "Notifications" },
  ai: { page: "settings/ai", label: "Automation & AI" },
  preferences: { page: "settings", label: "Preferences" },
  history: { page: "history/grows", label: "Run records" },
  zone: { page: "zone", label: "Zone controls" },
  header: { page: "today", label: "room watering control in the header" },
};
export function ownerKey(feature: Feature): ConfigOwner {
  if (feature.id === "engine") return "header";
  if (["zone_enabled", "manual_override"].includes(feature.id)) return "zone";
  if (feature.id === "record_grow_days") return "history";
  if (feature.group === "ai") return "ai";
  if (feature.group === "alerts") return "notifications";
  if (feature.id === "ph_auto_correct") return "dosing";
  if (feature.id === "probe_methods") return "probes";
  if (
    feature.group === "phases" ||
    ["ec_stacking", "ec_targets", "photoperiod"].includes(feature.id)
  )
    return "irrigation";
  if (["water_today_view", "manual_hardware_enabled"].includes(feature.id)) return "preferences";
  return "equipment";
}
export const ownerOf = (feature: Feature) => destinations[ownerKey(feature)];
export function ownerHref(feature: Feature): string {
  // Query survives the router and identifies the capability for keyboard focus/scroll.
  return `#/${ownerOf(feature).page}?feature=${encodeURIComponent(feature.id)}`;
}
const existingFeatures = new Set([
  "engine",
  "room_active",
  "zone_enabled",
  "auto_setpoints",
  "steering_mode",
  "notify_predictions",
  "water_today_view",
  "manual_hardware_enabled",
]);

/** Every registry cell has one writer. Supplemental editors fill gaps in the existing forms. */
export function supplementalRow(
  feature: Feature,
  row: ControlRow,
  controller: Controller,
): ControlRow | null {
  if (existingFeatures.has(feature.id)) return null;
  const owned = new Set(controller.room.settings.map((s) => s.entityId));
  const keep = (cell: Cell | null) => {
    if (!cell) return null;
    // Setup owns zone sizing; retain room defaults for legacy controllers.
    if (feature.id === "sizing") return cell.zone === null ? cell : null;
    // Strategy's mode-dependent table is zone-only; room defaults are omitted from its
    // remainder. Keep those defaults here while the zone target stays in that table.
    if (
      cell.zone === null &&
      /^(vegetative|generative)_dryback_target$|^ec_target_(veg|gen)_p[012]$/.test(row.control.key)
    )
      return cell;
    return owned.has(cell.entityId) ? null : cell;
  };
  const room = keep(row.room),
    zones = row.zones.filter((c) => keep(c));
  return room || zones.length ? { ...row, room, zones } : null;
}
