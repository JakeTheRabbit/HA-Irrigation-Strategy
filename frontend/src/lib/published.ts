import type { TimelineRow } from "./day-timeline";
import type { EntityState, States } from "./types";

/** What the controller publishes about a zone, read as it is: the numbers its own decisions used,
 * or why there are none. The dashboard does not work these out itself from recorded readings, so
 * the two can never disagree. */
const H = 3_600_000;
/** An estimate whose time is this far past while the controller still holds it is stale. */
const LATE_MS = 5 * 60_000;

const sensor = (prefix: string, name: string) => `sensor.crop_steering_${prefix}${name}`;
/** The relative dryback ((peak − VWC) / peak × 100) that decide() steers on. */
export const drybackId = (prefix: string, zone: number) =>
  sensor(prefix, `zone_${zone}_dryback_app`);
/** Hours to the next P2 top-up at the current dryback rate, published only while it can be worked out. */
export const nextIrrigationId = (prefix: string, zone: number) =>
  sensor(prefix, `prediction_zone_${zone}_next_irrigation_hours`);
/** The detected P1 wet-up ceiling (advisory), published once there is one. */
export const vmaxId = (prefix: string, zone: number) =>
  sensor(prefix, `zone_${zone}_vmax_detected`);

const finite = (value: unknown): number | null => {
  const n =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim()
        ? Number(value)
        : NaN;
  return Number.isFinite(n) ? n : null;
};
function read(entity: Pick<EntityState, "state"> | undefined, missing: string, unknown: string) {
  if (!entity) return { value: null, reason: missing };
  if (entity.state === "unavailable")
    return { value: null, reason: "the controller's sensor is unavailable" };
  const value = finite(entity.state);
  return value === null ? { value: null, reason: unknown } : { value, reason: null };
}

export interface PublishedDryback {
  /** % of the peak. */
  percent: number | null;
  /** The peak VWC it is measured from: the highest since the last lights-on. */
  peak: number | null;
  /** The same drop in VWC points. */
  points: number | null;
  /** Why there is no value. */
  reason: string | null;
}
function dryback(
  entity: { state: string; attributes?: Record<string, unknown> } | undefined,
  missing: string,
): PublishedDryback {
  const { value, reason } = read(entity, missing, "no peak since lights-on yet");
  const attributes = entity?.attributes ?? {};
  return {
    percent: value,
    peak: value === null ? null : finite(attributes.peak_vwc),
    points: value === null ? null : finite(attributes.dryback_points),
    reason,
  };
}
/** The zone's dryback now, as the controller publishes it. */
export function publishedDryback(states: States, prefix: string, zone: number): PublishedDryback {
  return dryback(
    states[drybackId(prefix, zone)],
    "the controller does not publish a dryback for this zone",
  );
}
/** The controller's dryback as recorded at `at` (last night's: at lights-on, before it starts over
 * from the new day's peak). */
export function recordedDryback(rows: TimelineRow[] | undefined, at: number): PublishedDryback {
  const row = (rows ?? []).filter((item) => item.time <= at).at(-1);
  return dryback(row, "the controller's dryback was not recorded at lights-on");
}

/** When the controller expects the zone's next P2 top-up, from the hours it published and when it
 * published them; `since` is when this P2 began. */
export function publishedNextIrrigation(
  states: States,
  prefix: string,
  zone: number,
  phase: string | null,
  since: number | null,
  now: number,
): { at: number | null; reason: string | null } {
  if (phase !== "P2")
    return { at: null, reason: "the controller estimates the next shot only in P2" };
  const entity = states[nextIrrigationId(prefix, zone)];
  const stamp = Date.parse(entity?.last_updated ?? entity?.last_changed ?? "");
  // The controller leaves its last estimate standing when it has none: one from an earlier P2 is not this one's.
  const none = "no estimate from the controller in this P2 yet";
  if (!entity || !Number.isFinite(stamp) || (since !== null && stamp < since))
    return { at: null, reason: none };
  const { value, reason } = read(entity, none, none);
  if (value === null) return { at: null, reason };
  const at = stamp + value * H;
  if (value <= 0) return { at: now, reason: null };
  if (at < now - LATE_MS) return { at: null, reason: "the controller's estimate is out of date" };
  return { at: Math.max(now, at), reason: null };
}

/** The zone's detected ramp ceiling (Vmax) and the controller's confidence in it, 0 to 1. */
export function publishedVmax(
  states: States,
  prefix: string,
  zone: number,
): { value: number | null; confidence: number | null; reason: string | null } {
  const entity = states[vmaxId(prefix, zone)];
  const { value, reason } = read(entity, "not detected yet", "not detected yet");
  return {
    value,
    confidence: value === null ? null : finite(entity?.attributes.confidence),
    reason,
  };
}
