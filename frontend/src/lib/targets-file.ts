// A room's targets as a file, to load into another room's draft (or the same room later).
// Settings are kept by name and zone number, not by entity id, so a file fits a room with another
// prefix. Both steering modes' targets go in, and each steering mode.
//
// Not everything is a target. Hardware sizing (pot size, plants, drippers) is set in Equipment and
// never written. Lights hours and the room's longest shot are written, so the file says what the
// room ran on, but never loaded: they belong to the room that has them. Loading only fills the
// draft; nothing is applied until it is reviewed.
import { suggestedDraft } from "./sensor-context";
import type { RoomView } from "./types";

export const TARGETS_FORMAT = "crop-steering-targets";
const VERSION = 1;
const ROOT = "crop_steering_";
const HARDWARE = new Set([
  "substrate_volume",
  "plant_count",
  "drippers_per_plant",
  "dripper_flow_rate",
]);
/** Written for reference, never loaded: settings of the room's own lights and plumbing. */
export const ROOM_OWN = new Set([
  "lights_on_hour",
  "lights_off_hour",
  "max_shot_duration",
  "maximum_shot_duration",
]);
const MODE = "steering_mode";

type Values = Record<string, number | string>;
export interface TargetsFile {
  format: typeof TARGETS_FORMAT;
  version: number;
  exported_at: string;
  room: string;
  room_settings: Values;
  zones: Record<string, { name: string; settings: Values }>;
}
/** One draft entry, as Targets keeps them. */
export interface TargetDraft {
  value: string;
  original: number | string | null;
  label: string;
  zone: string;
}
export interface LoadedTargets {
  drafts: Record<string, TargetDraft>;
  /** Settings the file has at the value this room already has. */
  same: number;
  /** The room's own settings the file has at other values, left as this room has them. */
  left: string[];
  /** Values moved to the nearest this room's setting takes (its step), from → to. */
  rounded: string[];
  /** Values this room cannot take, with why. */
  skipped: string[];
  /** Zones in the file this room does not have. */
  missingZones: string[];
  /** Said when the file and this room have a different number of zones; null when they match. */
  zoneMismatch: string | null;
}

/** A setting's name in the file: its entity id without the domain, the room and the zone. */
function split(entityId: string, prefix: string): { zone: number | null; key: string } | null {
  const rest = entityId.match(/^(?:number|select)\.(.*)$/)?.[1];
  if (!rest?.startsWith(ROOT + prefix)) return null;
  const key = rest.slice(ROOT.length + prefix.length);
  const zone = key.match(/^zone_(\d+)_(.+)$/);
  return zone ? { zone: Number(zone[1]), key: zone[2] } : { zone: null, key };
}

export function exportTargets(view: RoomView, exportedAt: string): string {
  const prefix = view.room.prefix;
  const file: TargetsFile = {
    format: TARGETS_FORMAT,
    version: VERSION,
    exported_at: exportedAt,
    room: view.room.name,
    room_settings: {},
    zones: {},
  };
  const place = (entityId: string, value: number | string | null) => {
    const name = split(entityId, prefix);
    if (!name || value === null || HARDWARE.has(name.key)) return;
    if (name.zone === null) {
      file.room_settings[name.key] = value;
      return;
    }
    const zone = view.zones.find((z) => z.id === name.zone);
    file.zones[name.zone] ||= { name: zone?.name ?? `Zone ${name.zone}`, settings: {} };
    file.zones[name.zone].settings[name.key] = value;
  };
  for (const setting of view.settings) place(setting.entityId, setting.value);
  for (const choice of view.choices) place(choice.entityId, choice.value);
  // A zone with no targets of its own still counts toward the zone-count check on import.
  for (const zone of view.zones) file.zones[zone.id] ||= { name: zone.name, settings: {} };
  return JSON.stringify(file, null, 2) + "\n";
}

const NOT_TARGETS = "That file isn’t a crop-steering targets file.";

function values(raw: unknown): Values | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const entries = Object.entries(raw as Record<string, unknown>);
  if (
    entries.some(([, v]) => typeof v !== "string" && !(typeof v === "number" && Number.isFinite(v)))
  )
    return null;
  return Object.fromEntries(entries) as Values;
}

export function readTargets(text: string): TargetsFile {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new Error(NOT_TARGETS);
  }
  const file = raw as Partial<TargetsFile> | null;
  if (!file || typeof file !== "object" || file.format !== TARGETS_FORMAT)
    throw new Error(NOT_TARGETS);
  if (file.version !== VERSION)
    throw new Error("This targets file is from a newer version. Update, then try again.");
  const roomSettings = values(file.room_settings);
  const zones = file.zones;
  if (!roomSettings || !zones || typeof zones !== "object" || Array.isArray(zones))
    throw new Error(NOT_TARGETS);
  const checked: TargetsFile["zones"] = {};
  for (const [id, zone] of Object.entries(zones)) {
    const settings = values((zone as { settings?: unknown })?.settings);
    if (!/^\d+$/.test(id) || !settings) throw new Error(NOT_TARGETS);
    const name = (zone as { name?: unknown }).name;
    checked[id] = { name: typeof name === "string" && name.trim() ? name : `Zone ${id}`, settings };
  }
  return {
    format: TARGETS_FORMAT,
    version: VERSION,
    exported_at: typeof file.exported_at === "string" ? file.exported_at : "",
    room: typeof file.room === "string" ? file.room : "",
    room_settings: roomSettings,
    zones: checked,
  };
}

const zones = (count: number) => `${count} ${count === 1 ? "zone" : "zones"}`;

/** The file's targets as a draft for this room: only what differs from the room now. */
export function loadTargets(file: TargetsFile, view: RoomView): LoadedTargets {
  const prefix = view.room.prefix;
  const fileZones = Object.keys(file.zones).length;
  const result: LoadedTargets = {
    drafts: {},
    same: 0,
    left: [],
    rounded: [],
    skipped: [],
    missingZones: [],
    zoneMismatch:
      fileZones === view.zones.length
        ? null
        : `The file has ${zones(fileZones)} and this room has ${zones(view.zones.length)}: ${
            fileZones > view.zones.length
              ? "the extra zones are not loaded"
              : "zones not in the file keep their targets"
          }.`,
  };
  const take = (zone: number | null, settings: Values) => {
    const where =
      zone === null
        ? "Room settings"
        : (view.zones.find((z) => z.id === zone)?.name ?? `Zone ${zone}`);
    const middle = zone === null ? "" : `zone_${zone}_`;
    for (const [key, value] of Object.entries(settings)) {
      if (HARDWARE.has(key)) continue;
      if (key === MODE) {
        const id = `select.${ROOT}${prefix}${middle}${MODE}`;
        const choice = view.choices.find((c) => c.entityId === id);
        if (!choice) continue;
        if (typeof value !== "string" || !choice.options.includes(value)) {
          result.skipped.push(`${where} · ${choice.label}: “${value}” isn’t a mode here`);
          continue;
        }
        if (value === choice.value) result.same++;
        else
          result.drafts[id] = { value, original: choice.value, label: choice.label, zone: where };
        continue;
      }
      const id = `number.${ROOT}${prefix}${middle}${key}`;
      const setting = view.settings.find((s) => s.entityId === id);
      if (!setting) continue;
      if (ROOM_OWN.has(key)) {
        // Said only where the file's room differs: the same lights hours need no mention.
        if (Number(value) !== setting.value && !result.left.includes(setting.label))
          result.left.push(setting.label);
        continue;
      }
      // A file's value can sit between this room's steps: the nearest the setting takes, said;
      // outside its limits, skipped.
      const wanted = typeof value === "number" ? value : Number(value);
      const taken = suggestedDraft(wanted, setting);
      if (taken === null) {
        result.skipped.push(
          `${where} · ${setting.label} ${value}: this room takes ${setting.min} to ${setting.max}`,
        );
        continue;
      }
      if (taken !== wanted) result.rounded.push(`${where} · ${setting.label} ${wanted} → ${taken}`);
      if (taken === setting.value) result.same++;
      else
        result.drafts[id] = {
          value: String(taken),
          original: setting.value,
          label: setting.label,
          zone: where,
        };
    }
  };
  take(null, file.room_settings);
  for (const [id, zone] of Object.entries(file.zones)) {
    if (view.zones.some((z) => z.id === Number(id))) take(Number(id), zone.settings);
    else
      result.missingZones.push(
        zone.name === `Zone ${id}` ? zone.name : `Zone ${id} (${zone.name})`,
      );
  }
  return result;
}

export function targetsFileName(room: string, date: string): string {
  const slug =
    room
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "room";
  return `crop-steering-targets-${slug}-${date}.json`;
}
