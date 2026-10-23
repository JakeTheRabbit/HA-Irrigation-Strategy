import type { ApplyReceipt } from "@/components/review-apply";
import { callV2, type V2Outcome } from "./parity-api";
import type { Controller } from "./types";

/** Equipment › Probes & offsets: a moisture probe's own offset (G9), set by matching a handheld meter.
 * The integration keeps it (calibration.py probe_offset_set, store `probe_user_offsets`) and applies it
 * to the probe's reading before it fuses the zone's probes; the raw reading is kept. The panel never
 * re-does the fusion: what the zone reads before and after comes from the integration's own answer. */

/** calibration.py CURVE_ON_PERCENT, word for word. */
export const CURVE_ON_PERCENT = "This probe already converts to moisture. A curve only applies to raw readings.";
/** The units the integration reads as moisture (generated/defaults.py UNITS.vwc.convert). */
const MOISTURE_UNITS: Record<string, number> = { "%": 1, "m³/m³": 100, "m3/m3": 100 };
const normalise = (unit: string) => unit.toLowerCase().replace(/ /g, "");
/** probe_offsets.py is_permittivity. */
const isPermittivity = (unit: string) => /ε|epsilon|permittivity|dielectric/.test(unit.toLowerCase());

/** The offset that makes the probe read what the handheld meter reads at the same spot, in VWC points:
 * the integration's own rule (`handheld − raw`, rounded to 3 places). */
export function handheldOffset(rawPct: number, handheldPct: number): number {
  return Math.round((handheldPct - rawPct) * 1000) / 1000;
}

/** Why the probe cannot take a substrate curve, in the integration's words; null when it can (a probe
 * reporting permittivity). */
export function curveDisabledReason(probe: { unit: string }): string | null {
  if (normalise(probe.unit) in MOISTURE_UNITS) return CURVE_ON_PERCENT;
  if (isPermittivity(probe.unit)) return null;
  return (
    "A curve applies only to a probe that reports permittivity (unit ε, permittivity or dielectric). " +
    `This probe reports ${probe.unit ? `'${probe.unit}'` : "no unit"}.`
  );
}

/** A moisture probe's reading in percent, as the integration takes it; null for a unit it does not
 * read as moisture. */
export function moisturePct(value: number | null, unit: string): number | null {
  const scale = MOISTURE_UNITS[normalise(unit || "%")];
  return value === null || scale === undefined ? null : Math.round(value * scale * 1000) / 1000;
}

/** An offset in VWC points, signed, one decimal: "+3.0", "−1.2", "0.0". */
export function signedPoints(value: number): string {
  const text = Math.abs(value).toFixed(1);
  return text === "0.0" ? text : `${value > 0 ? "+" : "−"}${text}`;
}
const pct = (value: number) => `${value.toFixed(1)}%`;

export interface ProbeOffset {
  offset: number;
  curve: string | null;
}
/** Each probe's stored offset (absent: none), from calibration_get; null from an integration that keeps
 * none (older than 3.18), or one that cannot read its store (`offsets_error`): the probes then read
 * without the offsets it still lists. */
export function readOffsets(document: unknown): Record<string, ProbeOffset> | null {
  const read = document as { probe_user_offsets?: unknown; offsets_error?: unknown } | null;
  if (read?.offsets_error) return null;
  const section = read?.probe_user_offsets;
  if (!section || typeof section !== "object" || Array.isArray(section)) return null;
  return Object.fromEntries(
    Object.entries(section as Record<string, { offset?: unknown; curve?: unknown }>).map(([id, entry]) => [
      id,
      { offset: Number(entry?.offset) || 0, curve: typeof entry?.curve === "string" ? entry.curve : null },
    ]),
  );
}

/** Why the integration refuses to set an offset now, in its own words (calibration.py: the offsets or
 * the calibration history cannot be read); null when it can. */
export function offsetsBlocked(document: unknown): string | null {
  const read = document as { error?: unknown; offsets_error?: unknown } | null;
  const reason = read?.offsets_error || read?.error;
  return typeof reason === "string" && reason ? reason : null;
}

/** What probe_offset_set answers (calibration.py), with or without `preview`. */
export interface OffsetAnswer {
  offset: number;
  curve: string | null;
  corrected_now: number | null;
  fused_before: number | null;
  fused_after: number | null;
  excluded_after: Record<string, string>;
  revision: number;
  warning?: string;
}
type Refusal = Extract<V2Outcome<unknown>, { kind: "error" | "missing" }>;

/** The integration's own estimate of the change, writing nothing: the offset that matches the handheld
 * and the zone's value before and after, and the revision a write must name. */
export function previewOffset(
  controller: Pick<Controller, "operator">,
  roomId: string,
  entityId: string,
  handheld: number,
): Promise<V2Outcome<OffsetAnswer>> {
  return callV2<OffsetAnswer>(controller, "probe_offset_set", {
    room_id: roomId,
    entity_id: entityId,
    match_handheld: handheld,
    preview: true,
  });
}

/** Writes exactly the reviewed offset, then reads the calibration store back. "Written and read back"
 * only when the store holds that offset; the receipt line is the zone's value from the write's own
 * `fused_before`/`fused_after`. */
export async function applyOffset(
  controller: Pick<Controller, "operator">,
  request: {
    roomId: string;
    entityId: string;
    offset: number;
    revision: number;
    room: string;
    zone: string;
    probe: string;
    /** The offset it replaces; null when it is not known. */
    before?: number | null;
    now?: () => number;
  },
): Promise<ApplyReceipt | Refusal> {
  const now = request.now ?? Date.now;
  const written = await callV2<OffsetAnswer>(controller, "probe_offset_set", {
    room_id: request.roomId,
    entity_id: request.entityId,
    offset: request.offset,
    expected_revision: request.revision,
  });
  if (written.kind !== "ok") return written;
  const back = await callV2<unknown>(controller, "calibration_get", { room_id: request.roomId });
  const stored = back.kind === "ok" ? readOffsets(back.data) : null;
  const holds = stored ? (stored[request.entityId]?.offset ?? 0) : null;
  const { fused_before: before, fused_after: after, offset } = written.data;
  const row =
    before !== null && after !== null
      ? { id: request.entityId, label: `${request.room} ${request.zone} value`, before: pct(before), after: pct(after) }
      : {
          id: request.entityId,
          label: `${request.probe} offset`,
          before: request.before == null ? "—" : signedPoints(request.before),
          after: signedPoints(offset),
        };
  if (holds === null || Math.abs(holds - offset) > 1e-9)
    return {
      at: now(),
      ok: false,
      unconfirmed: true,
      failed: [{ id: row.id, holds: row.before }],
      summary: "",
      eventIds: written.eventIds,
    };
  return {
    at: now(),
    ok: true,
    failed: [],
    summary: `${row.label} ${row.before} → ${row.after}`,
    eventIds: written.eventIds,
    ...(written.eventIds.length ? {} : { undoUnavailable: true }),
  };
}
