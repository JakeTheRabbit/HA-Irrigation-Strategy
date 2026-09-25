import type { EntityState } from "./types";

/** A controller that has not reported for this long is not running: the integration's own limit
 * (the engine-offline repair and a zone's "Controller not reporting"). A shot holds the
 * controller's loop, and a batch of them held it 8.2 minutes at the 25 Sep 2026 lights-on while it
 * watered. */
export const HEARTBEAT_STALE_MS = 10 * 60_000;
/** Data age turns amber, then red. */
export const AGE_AMBER_MS = 2 * 60_000;
export const AGE_RED_MS = 10 * 60_000;

export interface Heartbeat {
  /** "missing": no heartbeat entity. The controller posts it over REST, so after a Home Assistant
   * restart with the controller stopped it simply does not exist. "unreadable": no usable time. */
  health: "fresh" | "stale" | "missing" | "unreadable";
  /** When the controller last reported (epoch ms); null when unknown. */
  at: number | null;
  attributes: Record<string, unknown>;
}

const CONTROLLER_TIME =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})?$/;
/** The controller stamps `last_beat` with Python's naive local `datetime.now().isoformat()`. */
export function parseControllerTime(value: unknown): number | null {
  const parts = typeof value === "string" ? value.match(CONTROLLER_TIME) : null;
  if (!parts) return null;
  const [, year, month, day, hour, minute, second, fraction, zone] = parts;
  const ms = fraction ? Math.floor(Number(fraction) * 1000) : 0;
  const at = zone
    ? Date.parse(`${year}-${month}-${day}T${hour}:${minute}:${second}${zone}`) + ms
    : new Date(+year, +month - 1, +day, +hour, +minute, +second, ms).getTime();
  return Number.isFinite(at) ? at : null;
}

export function readHeartbeat(entity: EntityState | undefined, now: number): Heartbeat {
  if (!entity) return { health: "missing", at: null, attributes: {} };
  const attributes = entity.attributes ?? {};
  // Every beat changes last_beat, so Home Assistant restamps last_updated (UTC) on each post: the
  // clock the integration's own health check uses. The naive local last_beat is the fallback.
  const updated = entity.last_updated ? Date.parse(entity.last_updated) : NaN;
  const at = Number.isFinite(updated) ? updated : parseControllerTime(attributes.last_beat);
  if (at === null || ["unknown", "unavailable"].includes(entity.state))
    return { health: "unreadable", at: null, attributes };
  return { health: now - at > HEARTBEAT_STALE_MS ? "stale" : "fresh", at, attributes };
}

export function ageText(ms: number): string {
  const minutes = Math.floor(Math.max(0, ms) / 60_000);
  if (minutes < 1) return "<1 min";
  if (minutes < 120) return `${minutes} min`;
  return minutes < 2880 ? `${Math.floor(minutes / 60)} h` : `${Math.floor(minutes / 1440)} d`;
}
export function ageTone(ms: number | null): "fresh" | "amber" | "red" {
  return ms === null || ms > AGE_RED_MS ? "red" : ms > AGE_AMBER_MS ? "amber" : "fresh";
}

const FIRING: Record<string, string> = {
  P0: "Flushing",
  P1: "Refilling",
  P2: "Topping up",
  P3: "Emergency",
};
export const RESTING: Record<string, string> = {
  P0: "Drying back",
  P1: "Ramping",
  P2: "Optimal",
  P3: "Overnight dryback",
};
/** The controller's own zone label (`zone_status_label` in crop_steering_engine/core.py), rebuilt
 * from what it publishes beside the zone status sensor: the zone phase with its reason, and this
 * cycle's decision. The status sensor itself has a second writer, the integration's
 * fixed-threshold sensor, so on its own it flips between the two vocabularies. */
export function controllerZoneLabel(
  zoneId: number,
  phase: EntityState | undefined,
  decision: EntityState | undefined,
): string | null {
  if (!phase || !/^P[0-3]$/.test(phase.state)) return null;
  const reason = typeof phase.attributes.reason === "string" ? phase.attributes.reason : "";
  // Decision entries read "Z<zone> <phase> <reason or block>".
  const entry = (key: "fired" | "blocked") => {
    const list = decision?.attributes[key];
    const hit = Array.isArray(list)
      ? list.find(
          (item): item is string => typeof item === "string" && item.startsWith(`Z${zoneId} `),
        )
      : undefined;
    return hit === undefined ? null : hit.replace(/^Z\d+ \S+ /, "");
  };
  // A zone without a live probe copies a sibling or runs the blind schedule.
  if (/probe dead|no live probe|blind irrigation budget/i.test(reason))
    return "Probe dead — copying";
  const held = entry("blocked");
  if (held !== null && held !== reason) return `Blocked: ${held}`.slice(0, 80);
  if (reason.includes("BLOCK")) return "Blocked — EC/cap";
  return entry("fired") !== null ? FIRING[phase.state] : RESTING[phase.state];
}
