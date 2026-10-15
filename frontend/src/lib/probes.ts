import type { PillTone } from "@/components/mini-visuals";
import type { EntityState, States, Zone } from "./types";

/** Equipment › Probes: each probe behind a zone's moisture and pore EC, and whether to believe it.
 * The integration combines a zone's probes into one reading (calculations.py fuse_probes) and
 * publishes which it used and which it left out, and why; a probe it used can still be stuck. An
 * older integration publishes only the combined reading, which then stands in for its probes. */

/** The integration's own range (const.py PROBE_RANGE): a reading outside it cannot be real. Whether
 * a probe still reports is the integration's call (it reads when each one last reported, which the
 * page does not always see): its "not reporting", or a combined reading the zone no longer uses. */
export const PROBE_RANGE = { vwc: [0, 100], ec: [0, 20] } as const;
/** A reading unchanged this long is likely stuck. Pore EC sits still for hours overnight;
 * moisture keeps drying. */
export const STUCK_MS = { vwc: 3 * 3_600_000, ec: 6 * 3_600_000 } as const;

export type ProbeKind = "vwc" | "ec";
export type ProbeHealth = "ok" | "stale" | "stuck" | "out-of-range" | "no-reading" | "left-out";
/** Each health as its pill's colour: amber to look at, red for a reading that cannot be used. */
export const PROBE_TONE: Record<ProbeHealth, PillTone> = {
  ok: "on",
  stale: "warn",
  stuck: "warn",
  "out-of-range": "off",
  "no-reading": "off",
  "left-out": "warn",
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
  health: ProbeHealth;
  /** The health in a few words. */
  text: string;
}

const readable = (state: string | undefined) =>
  !!state && !["unavailable", "unknown", "none", ""].includes(state.toLowerCase());
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
