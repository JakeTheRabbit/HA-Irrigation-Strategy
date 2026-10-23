import type { PillTone } from "@/components/mini-visuals";
import type { SetupRoom } from "./operator-types";
import type { EntityState, States, Zone } from "./types";
import { unreadableState } from "./utils";

/** Equipment › Probes: each probe behind a zone's moisture and pore EC, and whether to believe it.
 * The integration combines a zone's probes into one reading (calculations.py fuse_probes) and
 * publishes which it used and which it left out, and why; a probe it used can still be stuck. An
 * older integration publishes only the combined reading, which then stands in for its probes. */

/** The integration's own range (const.py PROBE_RANGE): a reading outside it cannot be real. Whether
 * a probe still reports is the integration's call (it reads when each one last reported, which the
 * page does not always see): its "not reporting", or a combined reading the zone no longer uses. */
export const PROBE_RANGE = { vwc: [0, 100], ec: [0, 20] } as const;
/** A reading unchanged this long is likely stuck. Pore EC sits still for hours overnight;
 * moisture keeps drying. The dashboard's own heuristic: neither the controller nor the integration
 * judges a probe stuck, so no hold or alert follows from it. */
export const STUCK_MS = { vwc: 3 * 3_600_000, ec: 6 * 3_600_000 } as const;

export type ProbeKind = "vwc" | "ec";
export type ProbeHealth =
  "ok" | "stale" | "stuck" | "out-of-range" | "no-reading" | "left-out" | "not-counted";
/** Each health as its pill's colour: amber to look at, red for a reading that cannot be used. */
export const PROBE_TONE: Record<ProbeHealth, PillTone> = {
  ok: "on",
  stale: "warn",
  stuck: "warn",
  "out-of-range": "off",
  "no-reading": "off",
  "left-out": "warn",
  "not-counted": "neutral",
};
/** The integration's reason for each probe's reading quality (calculations.py fuse_probes `quality`),
 * in words. */
export const READING_REASON: Record<string, string> = {
  fresh: "Fresh",
  stale: "Stale",
  out_of_range: "Out of range",
  excluded_outlier: "Far from the others",
  unknown_unit: "Unit not known",
};
export interface Probe {
  id: string;
  name: string;
  kind: ProbeKind;
  zone: number;
  value: number | null;
  unit: string;
  /** When it last reported, and when its reading last changed (epoch ms). */
  reported: number | null;
  changed: number | null;
  /** The zone's reading uses it; null from an older integration, which does not say. */
  used: boolean | null;
  /** The zone's setup names it primary: the controller says when it goes offline (CS-505). */
  primary: boolean;
  /** The integration's quality of its reading (good, suspect, bad) and why; null from an older
   * integration, which does not say. */
  quality: string | null;
  reason: string | null;
  health: ProbeHealth;
  /** The health in a few words. */
  text: string;
}

const readable = (state: string | undefined) => !unreadableState(state);
const stamp = (value: string | undefined) => {
  const time = value ? Date.parse(value) : NaN;
  return Number.isFinite(time) ? time : null;
};
const duration = (ms: number) => {
  const minutes = Math.round(ms / 60_000);
  return minutes < 90 ? `${minutes} min` : `${Math.round(minutes / 60)} h`;
};

/** How far to believe one probe, the integration's word first: why it left the probe out. */
export function probeHealth(input: {
  kind: ProbeKind;
  state: string | undefined;
  unit: string;
  reported: number | null;
  changed: number | null;
  /** The integration's reason for leaving it out; null when it used it or does not say. */
  excluded: string | null;
  /** It has stopped reporting, by the zone's own reading (a combined sensor standing in). */
  stale?: boolean;
  now: number;
}): { health: ProbeHealth; text: string } {
  const { kind, state, unit, reported, changed, excluded, stale, now } = input;
  const reason = excluded?.toLowerCase() ?? "";
  if (reason === "not counted") return { health: "not-counted", text: "Does not count" };
  const out = excluded ? ", left out of the zone's reading" : "";
  if (reason === "no reading" || !readable(state) || !Number.isFinite(Number(state)))
    return { health: "no-reading", text: `No reading${out}` };
  const value = Number(state);
  const [low, high] = PROBE_RANGE[kind];
  if (reason === "out of range" || value < low || value > high)
    return {
      health: "out-of-range",
      text: `Reads ${value}${unit ? ` ${unit}` : ""}: out of range${out}`,
    };
  if (reason === "not reporting" || stale)
    return {
      health: "stale",
      text: `${reported === null ? "Not reporting" : `Silent ${duration(now - reported)}`}${out}`,
    };
  if (excluded) return { health: "left-out", text: `Left out: ${excluded}` };
  if (changed !== null && now - changed > STUCK_MS[kind])
    return { health: "stuck", text: `Unchanged for ${duration(now - changed)}` };
  return { health: "ok", text: "OK" };
}

/** A zone's probes, moisture then pore EC: each one the integration names, or the combined sensor
 * itself where it names none. */
export function zoneProbes(zone: Zone, states: States, now: number): Probe[] {
  return (["vwc", "ec"] as const).flatMap((kind) => {
    const fused = zone[kind].entityId ? states[zone[kind].entityId!] : undefined;
    const used = Array.isArray(fused?.attributes.used)
      ? (fused!.attributes.used as unknown[]).filter((id): id is string => typeof id === "string")
      : null;
    const graded = fused?.attributes.quality;
    const grades =
      graded && typeof graded === "object" && !Array.isArray(graded)
        ? (graded as Record<string, { quality?: unknown; reason?: unknown }>)
        : {};
    const raw = fused?.attributes.excluded;
    const excluded =
      raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
    const ids =
      used === null
        ? zone[kind].entityId
          ? [zone[kind].entityId!]
          : []
        : [...used, ...Object.keys(excluded).filter((id) => !used.includes(id))];
    return ids.map((id): Probe => {
      const entity: EntityState | undefined = states[id];
      const reason =
        used !== null && !used.includes(id)
          ? typeof excluded[id] === "string" && excluded[id]
            ? String(excluded[id])
            : "left out"
          : null;
      const unit = String(entity?.attributes.unit_of_measurement ?? (kind === "vwc" ? "%" : ""));
      const reported =
        stamp((entity as { last_reported?: string } | undefined)?.last_reported) ??
        stamp(entity?.last_updated);
      const changed = stamp(entity?.last_changed);
      const value =
        entity && Number.isFinite(Number(entity.state)) && readable(entity.state)
          ? Number(entity.state)
          : null;
      return {
        id,
        name: String(entity?.attributes.friendly_name ?? id),
        kind,
        zone: zone.id,
        value,
        unit,
        reported,
        changed,
        used: used === null ? null : used.includes(id),
        primary: fused?.attributes.primary === id,
        quality: typeof grades[id]?.quality === "string" ? String(grades[id].quality) : null,
        reason: typeof grades[id]?.reason === "string" ? String(grades[id].reason) : null,
        ...probeHealth({
          kind,
          state: entity?.state,
          unit,
          reported,
          changed,
          excluded: reason,
          stale: used === null && zone[kind].value === null,
          now,
        }),
      };
    });
  });
}

/** How the zone's reading is made from its probes, in words (calculations.py fuse_probes publishes
 * the zone's choice as `method` and what it steered by as `steered_by`): Lowest or Highest with
 * fewer than three probes that agree steers on the median instead (CS-502). Null from an older
 * integration, which does not say. */
export function fusionMethod(fused: EntityState | undefined): string | null {
  const method = fused?.attributes.method;
  const steered = fused?.attributes.steered_by;
  if (typeof method !== "string" || typeof steered !== "string") return null;
  return method === steered
    ? `${steered.toLowerCase()} of its probes`
    : `${steered.toLowerCase()} of its probes: ${method} needs three that agree`;
}

/** Which EC the zone steers on, in words, when it has both pore and bulk EC probes (calculations.py
 * fuse_probes publishes `ec_type`; the two are never combined): bulk only while no pore probe
 * reports (CS-504). Null otherwise, and from an older integration. */
export function ecType(fused: EntityState | undefined): string | null {
  const type = fused?.attributes.ec_type;
  if (type === "pore") return "steers on its pore EC probes";
  if (type === "bulk") return "steers on its bulk EC probes: no pore EC probe is reporting";
  return null;
}

/** Every probe the room's combined sensors name: what the page watches and draws. */
export function roomProbeIds(zones: readonly Zone[], states: States): string[] {
  const ids = new Set<string>();
  for (const zone of zones)
    for (const kind of ["vwc", "ec"] as const) {
      const attributes = zone[kind].entityId ? states[zone[kind].entityId!]?.attributes : undefined;
      if (Array.isArray(attributes?.used))
        for (const id of attributes.used) if (typeof id === "string") ids.add(id);
      const excluded = attributes?.excluded;
      if (excluded && typeof excluded === "object" && !Array.isArray(excluded))
        for (const id of Object.keys(excluded)) ids.add(id);
    }
  return [...ids].filter((id) => /^sensor\.[a-z0-9_]+$/.test(id)).sort();
}

/** What the zone's setup stores of its probes (setup_api.py PROBE_CHOICE): for each reading, the
 * probes that do not count and the one that is primary. */
export interface ProbeChoice {
  unused: string[];
  primary: string;
}
/** A zone's choice as the page shows it, keyed `zone:kind`: only where the integration names the
 * zone's probes (an older one does not, and has nothing to choose). */
export function probeChoices(probes: readonly Probe[]): Record<string, ProbeChoice> {
  const choices: Record<string, ProbeChoice> = {};
  for (const probe of probes) {
    if (probe.used === null) continue;
    const choice = (choices[`${probe.zone}:${probe.kind}`] ??= { unused: [], primary: "" });
    if (probe.health === "not-counted") choice.unused.push(probe.id);
    if (probe.primary) choice.primary = probe.id;
  }
  return choices;
}
/** The save the picker sends: each zone's id, whether it is active, and its choice, nothing else,
 * so the integration takes it while the room waters. */
export function probeChoicePayload(room: SetupRoom, choices: Record<string, ProbeChoice>) {
  return {
    entry_id: room.entry_id,
    expected_revision: room.revision,
    zones: room.zones.map((zone) => ({
      id: zone.id,
      active: zone.active,
      ...Object.fromEntries(
        (["vwc", "ec"] as const).flatMap((kind) => {
          const choice = choices[`${zone.id}:${kind}`];
          return choice
            ? [
                [`${kind}_unused`, choice.unused],
                [`${kind}_primary`, choice.primary],
              ]
            : [];
        }),
      ),
    })),
  };
}

/** The probe's health in a word or two, for its pill: "Silent 3 h", "Stuck 4 h", "Out of range". */
export function healthChip(probe: Probe, now: number): string {
  switch (probe.health) {
    case "stale":
      return probe.reported === null ? "Not reporting" : `Silent ${duration(now - probe.reported)}`;
    case "stuck":
      return probe.changed === null ? "Stuck" : `Stuck ${duration(now - probe.changed)}`;
    case "out-of-range":
      return "Out of range";
    case "no-reading":
      return "No reading";
    case "left-out":
      return "Left out";
    case "not-counted":
      return "Does not count";
    default:
      return "OK";
  }
}

/** A moisture probe whose reading points at where it sits (out of range, or far from the zone's other
 * probes): moving it is the fix, not an offset. */
export const placementProblem = (probe: Probe) =>
  probe.kind === "vwc" && (probe.health === "out-of-range" || probe.reason === "excluded_outlier");

/** One row of Probes & offsets: a moisture probe, and the pore EC probe on its side of the slab (by
 * "front"/"back" in their names, else by order). */
export interface ProbeRow {
  side: string;
  vwc: Probe;
  ec: Probe | null;
}
const sideOf = (probe: Probe) => /\b(front|back)\b/i.exec(probe.name)?.[1].toLowerCase() ?? null;
export function probeRows(probes: readonly Probe[]): ProbeRow[] {
  const moisture = probes.filter((probe) => probe.kind === "vwc");
  const ec = probes.filter((probe) => probe.kind === "ec");
  return moisture.map((vwc, index) => {
    const side = sideOf(vwc);
    return {
      side: side ? side[0].toUpperCase() + side.slice(1) : moisture.length > 1 ? vwc.name : "Probe",
      vwc,
      ec: (side ? ec.find((probe) => sideOf(probe) === side) : undefined) ?? ec[index] ?? null,
    };
  });
}

/** Every probe on Probes & offsets, moisture and the pore EC beside it, each once: how many, how many
 * are healthy, and how many the zone values use. */
export function probeCounts(rows: readonly ProbeRow[]) {
  const probes = [...new Map(rows.flatMap((row) => [row.vwc, ...(row.ec ? [row.ec] : [])]).map((probe) => [probe.id, probe])).values()];
  return {
    total: probes.length,
    healthy: probes.filter((probe) => probe.health === "ok").length,
    used: probes.filter((probe) => probe.used !== false && probe.health !== "not-counted").length,
  };
}
