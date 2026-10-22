/**
 * The feature registry: every on/off switch and setting of a room, in one place, grouped as the
 * Features page shows them (Settings > Features). The data is features.json, which
 * tests_ha/test_feature_registry.py checks against the entities a real Home Assistant creates: a
 * switch, select or number with no entry here fails that test, so no feature goes invisible.
 *
 * A new feature adds one entry to features.json. Keys are the entity key after the room prefix;
 * a zone key is written without its `zone_N_` part and has scope "zone" or "room+zone".
 */
import registry from "./features.json";
import restored from "./features-restore.json";
import type { Page } from "./routes";
import type { EntityState, States } from "./types";

export type Domain = "switch" | "select" | "number";
export type Scope = "room" | "zone" | "room+zone";
export type Value = boolean | number | string;
export interface Control {
  domain: Domain;
  key: string;
  scope: Scope;
  /** Null: a state, not a setting (watering on, a zone held), so never "changed" and never reset. */
  default: Value | null;
  /** The room's watering switch: the room's engine entity, which may be a helper. */
  engine?: boolean;
  /** The control's name where the setting words have none. */
  label?: string;
  /** Zone overrides exist only for zones set up with their own value. */
  zoneOptional?: boolean;
}
export interface Feature {
  id: string;
  group: string;
  label: string;
  help: string;
  master?: Control;
  settings: Control[];
  /** The page where this control also lives. */
  alsoOn?: string;
  /** The restore item (lost-features id) that brought the feature back. */
  restore?: string;
}
export interface Group {
  id: string;
  label: string;
  help: string;
}
export interface AppOption {
  key: string;
  label: string;
  default: string;
  secret?: boolean;
}

export const GROUPS: Group[] = registry.groups;
export const FEATURES: Feature[] = registry.features as unknown as Feature[];
export const INTERNAL: { domain: string; key: string; why: string }[] = registry.internal;
export const APP_OPTIONS: AppOption[] = registry.options;

const ROOT = "crop_steering_";

/** The entity id of a control in a room, for the room (zone null) or one zone. */
export function entityIdOf(prefix: string, control: Control, zone: number | null): string {
  return `${control.domain}.${ROOT}${prefix}${zone === null ? "" : `zone_${zone}_`}${control.key}`;
}

export function controlsOf(feature: Feature): Control[] {
  return [...(feature.master ? [feature.master] : []), ...feature.settings];
}

/** The registered control an entity id of this room is, or null. A refused hardware entity never
 * matches: its ids are not crop_steering_ keys. */
export function registeredControl(
  prefix: string,
  entityId: string,
): { feature: Feature; control: Control; zone: number | null } | null {
  const dot = entityId.indexOf(".");
  const domain = entityId.slice(0, dot);
  const rest = entityId.slice(dot + 1);
  if (!rest.startsWith(ROOT + prefix)) return null;
  const key = rest.slice((ROOT + prefix).length);
  const zoned = key.match(/^zone_(\d+)_(.+)$/);
  for (const feature of FEATURES)
    for (const control of controlsOf(feature)) {
      if (control.domain !== domain || control.engine) continue;
      if (zoned && control.key === zoned[2] && control.scope !== "room")
        return { feature, control, zone: Number(zoned[1]) };
      if (!zoned && control.key === key && control.scope !== "zone")
        return { feature, control, zone: null };
    }
  return null;
}

/** The value an entity holds, in the control's type; null when it has none. */
export function valueOf(control: Control, entity?: EntityState): Value | null {
  if (!entity || ["unavailable", "unknown", ""].includes(entity.state)) return null;
  if (control.domain === "switch") return entity.state === "on";
  if (control.domain === "number") {
    const n = Number(entity.state);
    return Number.isFinite(n) ? n : null;
  }
  return entity.state;
}

export function isDefault(control: Control, value: Value | null): boolean {
  if (value === null || control.default === null) return true;
  if (typeof value === "number" && typeof control.default === "number")
    return Math.abs(value - control.default) < 1e-6;
  return value === control.default;
}

export interface Cell {
  entityId: string;
  zone: number | null;
  value: Value | null;
  entity: EntityState;
}
export interface ControlRow {
  control: Control;
  room: Cell | null;
  zones: Cell[];
}
export interface FeatureRow {
  feature: Feature;
  master: ControlRow | null;
  settings: ControlRow[];
  changed: boolean;
}

/** Each feature with the room's entities it has. A feature with none (an older integration) is
 * left out. `engineEntity`: the room's watering switch, which may be a helper. */
export function featureRows(
  states: States,
  prefix: string,
  zones: number[],
  engineEntity: string | null,
): FeatureRow[] {
  const cell = (control: Control, entityId: string, zone: number | null): Cell | null => {
    const entity = states[entityId];
    return entity ? { entityId, zone, value: valueOf(control, entity), entity } : null;
  };
  const row = (control: Control): ControlRow | null => {
    const room = control.engine
      ? engineEntity
        ? cell(control, engineEntity, null)
        : null
      : control.scope === "zone"
        ? null
        : cell(control, entityIdOf(prefix, control, null), null);
    const zoneCells =
      control.scope === "room"
        ? []
        : zones
            .map((z) => cell(control, entityIdOf(prefix, control, z), z))
            .filter((c): c is Cell => c !== null);
    return room || zoneCells.length ? { control, room, zones: zoneCells } : null;
  };
  return FEATURES.flatMap((feature) => {
    const master = feature.master ? row(feature.master) : null;
    const settings = feature.settings.map(row).filter((r): r is ControlRow => r !== null);
    if (!master && !settings.length) return [];
    const changed = [master, ...settings].some(
      (r) =>
        r !== null &&
        [r.room, ...r.zones].some((c) => c !== null && !isDefault(r.control, c.value)),
    );
    return [{ feature, master, settings, changed }];
  });
}

/** The writes that put a feature back to its defaults: only the values that differ. */
export function resetChanges(row: FeatureRow): { entityId: string; value: Value }[] {
  return [row.master, ...row.settings].flatMap((r) =>
    r === null || r.control.default === null
      ? []
      : [r.room, ...r.zones]
          .filter((c): c is Cell => c !== null && !isDefault(r.control, c.value))
          .map((c) => ({ entityId: c.entityId, value: r.control.default as Value })),
  );
}

export function matches(row: FeatureRow, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [row.feature.label, row.feature.help, ...controlsOf(row.feature).map((c) => c.key)].some(
    (text) => text.toLowerCase().includes(q),
  );
}

/** A number's limits from its entity, for a registered number the room's Targets do not list. */
export function numberLimits(
  entity?: EntityState,
): { min: number; max: number; step: number } | null {
  const { min, max, step } = entity?.attributes ?? {};
  if (
    ![min, max, step].every((v) => typeof v === "number" && Number.isFinite(v)) ||
    Number(min) > Number(max) ||
    Number(step) <= 0
  )
    return null;
  return { min: Number(min), max: Number(max), step: Number(step) };
}

/** Restored settings that live in a setup form, display store or history overlay, rather than an
 * HA switch/number/select. Their links open the existing controls; no pretend entity is written. */
export interface Placement {
  id: string;
  entity: string;
  label: string;
  help: string;
  group: string;
  page: Page;
  location: string;
}
export const RESTORED_MANIFEST = restored;
const PLACEMENT_PAGES: Record<string, { group: string; page: Page; location: string }> = {
  "AI-INSTRUCTIONS": {
    group: "ai",
    page: "settings/ai",
    location: "Settings > AI assistant > Instructions",
  },
  "LF-05": { group: "display", page: "zone", location: "Zone page" },
  "LF-97": { group: "display", page: "help", location: "Help > Rules" },
  "LF-124": { group: "display", page: "today", location: "Today" },
  "LF-169": { group: "safety", page: "zone", location: "Zone page" },
  "LF-65": { group: "equipment", page: "equipment/setup", location: "Equipment > Setup" },
  "LF-63": { group: "equipment", page: "equipment/setup", location: "Equipment > Setup" },
  "LF-91": { group: "equipment", page: "equipment/setup", location: "Equipment > Setup" },
  "LF-34": { group: "equipment", page: "equipment/setup", location: "Equipment > Setup" },
  "LF-54": { group: "equipment", page: "equipment/setup", location: "Equipment > Setup" },
  "NEW-03": {
    group: "history",
    page: "history/explorer",
    location: "History > Explorer > Sensor history",
  },
  "LF-87": { group: "history", page: "equipment/setup", location: "Equipment > Setup" },
  "LF-86": {
    group: "history",
    page: "history/explorer",
    location: "History > Explorer > Overlays",
  },
  "LF-165": {
    group: "feed",
    page: "equipment/dosing",
    location: "Equipment > Dosing > Dosing setup",
  },
};
export const PLACEMENTS: Placement[] = restored.flatMap((row) => {
  // Entity controls are in the main registry. App options already have their own section below it.
  if (/^(switch|number|select)\.crop_steering_/.test(row.entity) || row.scope === "app") return [];
  // "Zones as" stays stored, but the room page has no zone table to lay out: nothing to link to.
  if (row.entity.includes("(attribute today_zone_layout)")) return [];
  const target = row.entity.includes("display (attribute ")
    ? { group: "display", page: "settings" as Page, location: "Settings > Display" }
    : PLACEMENT_PAGES[row.id];
  return target
    ? [{ id: row.id, entity: row.entity, label: row.label, help: row.help, ...target }]
    : [];
});
export function placementsFor(group: string, query: string): Placement[] {
  const q = query.trim().toLowerCase();
  return PLACEMENTS.filter(
    (row) =>
      (group === "all" || row.group === group) &&
      (!q || `${row.label} ${row.help} ${row.location}`.toLowerCase().includes(q)),
  );
}
