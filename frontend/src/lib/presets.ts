import { receiptFromV2, type ApplyReceipt, type ReviewRow } from "@/components/review-apply";
import { formatEc } from "./display-units";
import { pickKey } from "./facility";
import type { V2Outcome } from "./parity-api";
import type { PresetMissing, PresetResult, PresetScope, PresetTarget } from "./parity-types";
import { settingWords } from "./setting-words";
import type { Room, States } from "./types";

/** Presets and copy-to-room (I4): a room's settings stored on the controller, and written to
 * another room (or a zone of it) through a preview diff, one apply with a read-back of every value,
 * and an Undo of the journalled writes. */

/** Every section a copy carries: what `preset_save` captures with scope "all". */
export const ALL_SECTIONS = ["targets", "phase_timing", "water_limits", "timers"] as const;

/** A setting key, a value of it and a copy target, in grower words. */
export interface PresetWords {
  label(key: string): string;
  value(key: string, value: unknown): string;
  target(target: PresetTarget): string;
}

/** A target as the room tree's pick key: the room id, or `pickKey(room, zone)`. */
export const targetKey = (t: PresetTarget) =>
  t.zone === undefined ? t.room_id : pickKey(t.room_id, t.zone);
/** A pick key back into the `{room_id, zone?}` the backend takes. Room ids hold a colon
 * ("room:f1_"), so a zone is only a trailing ":<number>" after one. */
export function parseTarget(key: string): PresetTarget {
  const zoned = /^(room:.*):(\d+)$/.exec(key);
  return zoned ? { room_id: zoned[1], zone: Number(zoned[2]) } : { room_id: key };
}

const KEY_LABELS: Record<string, string> = {
  timers: "Timer programs",
  timer: "Timer program",
  p2_mode: "P2 mode",
};
const decimals = (value: number) => String(value).split(".")[1]?.length ?? 0;

/** Words from the live states: a value takes the unit its setting's entity has in any room. */
export function presetWords(states: States, rooms: Room[]): PresetWords {
  const unitOf = (key: string) => {
    for (const room of rooms)
      for (const id of [
        `number.crop_steering_${room.prefix}${key}`,
        `number.crop_steering_${room.prefix}zone_1_${key}`,
      ]) {
        const unit = states[id]?.attributes.unit_of_measurement;
        if (typeof unit === "string") return unit;
      }
    return "";
  };
  const roomName = (id: string) =>
    rooms.find((room) => room.id === id)?.name ?? id.replace(/^room:/, "");
  return {
    label: (key) => {
      if (KEY_LABELS[key]) return KEY_LABELS[key];
      const words = settingWords(key);
      if (words) return words.label;
      const text = key.replaceAll("_", " ");
      return text.charAt(0).toUpperCase() + text.slice(1).replace(/\bp(\d)\b/g, "P$1");
    },
    value: (key, value) => {
      if (value === null || value === undefined) return "none";
      if (Array.isArray(value))
        return value.length ? `${value.length} program${value.length === 1 ? "" : "s"}` : "none";
      if (typeof value === "object") {
        const name = (value as { name?: unknown }).name;
        return typeof name === "string" && name ? name : "a program";
      }
      if (typeof value !== "number") return String(value);
      const unit = unitOf(key);
      if (unit === "%") return `${value}%`;
      if (unit === "mS/cm") return formatEc(value, decimals(value));
      return unit ? `${value} ${unit}` : String(value);
    },
    target: (t) =>
      t.zone === undefined ? roomName(t.room_id) : `${roomName(t.room_id)} zone ${t.zone}`,
  };
}

/** The preview's diff as Review & apply rows: the old value struck, the new one beside it. A row
 * names its target only when the copy writes more than one. A copy writes whole sections, so no
 * row can be taken out on its own. */
export function diffRows(diff: PresetResult["diff"], words: PresetWords): ReviewRow[] {
  const many = new Set(diff.map((d) => targetKey(d.target))).size > 1;
  return diff.map((d) => ({
    id: `${targetKey(d.target)}|${d.key}`,
    key: d.key,
    target: targetKey(d.target),
    label: many ? `${words.target(d.target)} · ${words.label(d.key)}` : words.label(d.key),
    before: words.value(d.key, d.old),
    after: words.value(d.key, d.new),
  }));
}

/** "Timer programs (source room has no timer programs)": each setting a copy leaves out, and why. */
export function notCopiedLines(
  missing: PresetMissing[],
  words: PresetWords,
  skipped: string[] = [],
): string[] {
  return [
    ...missing.map(
      (m) =>
        `${words.label(m.key)} (${m.reason ?? `${words.target(m.target)} has no such setting`})`,
    ),
    // The source's settings with no reading: copy_config left them out.
    ...skipped.map((key) => `${words.label(key)} (no reading)`),
  ];
}

/** The settings `preset_save` left out because the source had no reading of them. */
export function skippedLine(skipped: string[], words: PresetWords): string {
  return skipped.length ? `Not saved: ${skipped.map(words.label).join(", ")} (no reading)` : "";
}

const isResult = (data: unknown): data is PresetResult =>
  !!data &&
  typeof data === "object" &&
  Array.isArray((data as PresetResult).diff) &&
  Array.isArray((data as PresetResult).applied);
const same = (a: PresetTarget, b: PresetTarget) => targetKey(a) === targetKey(b);

/** The receipt of a copy or preset apply. A refused row (`guard_refused`, whose answer still lists
 * every write) keeps its old value and the others are named as written and read back; a timer the
 * source has none of is not copied, never a failure. A row with no read-back, or a refusal that
 * matches no row, claims nothing. Every setting left out is named. Any other refusal, and an older
 * integration, pass through as they came. */
export function copyReceipt(
  outcome: V2Outcome<PresetResult>,
  rows: ReviewRow[],
  words: PresetWords,
  now: number,
): ApplyReceipt | Extract<V2Outcome<PresetResult>, { kind: "error" | "missing" }> {
  let data: PresetResult;
  let status: "verified" | "unverified";
  let eventIds: string[] = [];
  if (outcome.kind === "ok") {
    data = outcome.data;
    status = outcome.readback.status;
    eventIds = outcome.eventIds;
  } else if (
    outcome.kind === "error" &&
    outcome.code === "guard_refused" &&
    isResult(outcome.data)
  ) {
    data = outcome.data;
    // Each write carries its own read-back; the envelope's is only "refused".
    status = "verified";
  } else return outcome;
  const missing = data.missing ?? [];
  const applied = (data.applied ?? [])
    .filter(
      (a) =>
        !(
          a.readback === "refused" &&
          missing.some((m) => m.key === a.key && same(m.target, a.target))
        ),
    )
    .map((a) => ({ key: a.key, target: targetKey(a.target), readback: a.readback }));
  // A written row the answer does not account for may or may not have taken.
  if (rows.some((row) => !applied.some((a) => a.key === row.key && a.target === row.target)))
    status = "unverified";
  const notCopied = notCopiedLines(missing, words, data.skipped ?? []);
  const left = notCopied.length ? { notCopied } : {};
  // A write the reviewed rows did not show (the source changed since the preview), read back or
  // not: name each one and claim nothing.
  const many = new Set(applied.map((a) => a.target)).size > 1;
  const extra = applied.filter(
    (a) => !rows.some((row) => row.key === a.key && row.target === a.target),
  );
  if (extra.length)
    return {
      at: now,
      ok: false,
      unconfirmed: true,
      failed: rows.map((row) => ({ id: row.id, holds: row.before, label: row.label })),
      alsoWritten: extra.map(
        (a) =>
          (many
            ? `${words.target(parseTarget(a.target))} · ${words.label(a.key)}`
            : words.label(a.key)) + (a.readback === "verified" ? "" : " (not read back)"),
      ),
      summary: "",
      eventIds,
      ...left,
    };
  const receipt = receiptFromV2(
    { kind: "ok", data: { applied }, revision: null, readback: { status, at: null }, eventIds },
    rows,
    now,
  );
  const labelled = {
    ...receipt,
    failed: receipt.failed.map((f) => ({
      ...f,
      label: rows.find((row) => row.id === f.id)?.label,
    })),
    ...left,
  };
  // Values were written, but without their Journal events Undo here cannot put them back.
  const wrote = !receipt.unconfirmed && receipt.failed.length < rows.length;
  return wrote && !eventIds.length ? { ...labelled, undoUnavailable: true } : labelled;
}

/** A preset's scope in words. */
export const SCOPE_WORDS: Record<PresetScope, string> = {
  targets: "targets",
  timers: "timer programs",
  all: "targets, timing, water limits and timers",
};
