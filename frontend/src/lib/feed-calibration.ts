import { formatEc } from "./display-units";
import type { V2Outcome } from "./parity-api";
import { dayKey, daysBetween, shortDate } from "./time";
import type { States } from "./types";

/** Equipment › Feed pH/EC calibration: the wizard's arithmetic. The backend (calibration.py) decides
 * whether a point is steady and whether a calibration applies; these only show it. */

export type FeedKind = "ph" | "ec";
export type FeedProbe = "feed_ph" | "feed_ec";
export interface Reading {
  at: number;
  value: number;
}

/** The backend's window: a point is captured once the reading held still this long. */
export const WINDOW_MS = 30_000;
export const KIND_OF: Record<FeedProbe, FeedKind> = { feed_ph: "ph", feed_ec: "ec" };
export const NAME_OF: Record<FeedKind, string> = { ph: "pH", ec: "EC" };

/** How far the reading moved over the last `windowMs` (from the last reading), and its mean, as the
 * backend's `stable` measures it: the reading before the window counts from the window's start (a
 * probe reports a change, not a still value). `span` is NaN until the readings reach back a whole
 * window. `readings` oldest first. */
export function spanOver(readings: { at: number; value: number }[], windowMs = WINDOW_MS): { span: number; mean: number } {
  if (!readings.length) return { span: NaN, mean: NaN };
  const start = readings[readings.length - 1].at - windowMs;
  const held = readings.filter((r) => r.at <= start).slice(-1);
  const values = [...held, ...readings.filter((r) => r.at > start)].map((r) => r.value);
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  return { span: held.length ? Math.max(...values) - Math.min(...values) : NaN, mean };
}

/** calibration.py `_steady`: pH moved less than 0.02, EC less than 1 % of its mean; a reading that did
 * not move at all is steady. Display only: the server's `stable` on capture decides. */
export function looksSteady(r: { span: number; mean: number }, kind: FeedKind): boolean {
  const limit = kind === "ph" ? 0.02 : 0.01 * Math.abs(r.mean);
  return r.span < limit || r.span === 0;
}

/** calibration.py `steady_for`: how long back from the last reading it has stayed steady (ms). */
export function steadyFor(readings: Reading[], kind: FeedKind): number {
  if (!readings.length) return 0;
  const end = readings[readings.length - 1].at;
  let since = end;
  const values: number[] = [];
  for (let i = readings.length - 1; i >= 0; i--) {
    values.push(readings[i].value);
    const span = Math.max(...values) - Math.min(...values);
    if (!looksSteady({ span, mean: values.reduce((a, b) => a + b, 0) / values.length }, kind)) break;
    since = readings[i].at;
  }
  return end - since;
}

/** A number as its source gives it: never more digits than it has. */
const plain = (n: number) => String(Number(n.toFixed(6)));
/** An offset in the probe's unit: pH to 2 places, EC in the display unit. */
const amount = (value: number, kind: FeedKind) => (kind === "ph" ? `${value.toFixed(2)} pH` : formatEc(value, 2));

/** The result in a grower's words: how far off the probe reads at the anchor (pH 7, EC 0) and how
 * well it still responds. Health is the backend verdict (slope and offset): pass healthy, drifting
 * clean soon, fail replace, so the words never contradict the Pass/Drift/Fail mark beside them. */
export function verdictWords(
  result: { verdict: "pass" | "drifting" | "fail"; slope_pct: number; offset: number },
  kind: FeedKind,
): { headline: string; health: "healthy" | "clean_soon" | "replace" } {
  const { slope_pct: slopePct, offset } = result;
  const health = result.verdict === "pass" ? "healthy" : result.verdict === "drifting" ? "clean_soon" : "replace";
  const response = `Response ${plain(slopePct)}% — ${
    health === "healthy" ? "healthy" : health === "clean_soon" ? "clean or replace the probe soon" : "replace the probe"
  }.`;
  const off = Math.abs(offset) < 0.005 ? "" : `Probe reads ${amount(Math.abs(offset), kind)} ${offset < 0 ? "low" : "high"}. `;
  return { headline: off + response, health };
}

/** Whether Capture can be pressed: the probe has a reading and it looks steady. A probe holding one
 * value reports no change, so the time since its last change never counts as offline: only a missing
 * reading (the raw sensor or calibration_status `raw: null`) does, as the backend's capture refuses. */
export function captureState(
  reading: boolean,
  steady: boolean,
  opts: { buffer: string; kind: FeedKind } = { buffer: "", kind: "ph" },
): { enabled: boolean; label: string; reason: string | null } {
  const label = `Capture ${opts.buffer} point`.replace("  ", " ");
  if (!reading) return { enabled: false, label, reason: `No reading from the feed ${NAME_OF[opts.kind]} probe. Check it's plugged in.` };
  if (!steady) return { enabled: false, label: `${label} · waiting for stable`, reason: null };
  return { enabled: true, label, reason: null };
}

/** What a refused capture, commit or start means for the wizard. An expired session (`invalid`, the
 * backend's EXPIRED words) starts a new session from buffer 1. */
export function refusalView(outcome: Extract<V2Outcome<unknown>, { kind: "error" | "missing" }>): {
  kind: "expired" | "moving" | "missing" | "other";
  text: string;
} {
  if (outcome.kind === "missing") return { kind: "missing", text: "This integration has no guided calibration." };
  if (outcome.code === "invalid" && /session expired/i.test(outcome.message))
    return { kind: "expired", text: "Your last calibration session expired. Start again from buffer 1." };
  const data = outcome.data as { stable?: unknown } | undefined;
  if (outcome.code === "guard_refused" && data?.stable === false)
    return { kind: "moving", text: "Reading still moving — calibration may be off." };
  return { kind: "other", text: outcome.message };
}

/** The result step's reminder of each point captured with "Capture anyway" while still moving. */
export function forcedLine(forced: boolean[] | undefined, buffers: string[]): string | null {
  const which = (forced ?? []).flatMap((f, i) => (f ? [`${i + 1} (${buffers[i]})`] : []));
  if (!which.length) return null;
  return which.length === 1
    ? `Buffer ${which[0]} was captured while the reading was still moving.`
    : `Buffers ${which.join(" and ")} were captured while the reading was still moving.`;
}

/** The open session this browser started, so the wizard can resume it. */
export interface StoredSession {
  session_id: string;
  expires_at: string;
  step: number;
  room_id: string;
  probe: FeedProbe;
  kind: FeedKind;
  solutions: number[];
  raw_entity_id: string;
  temperature_entity_id: string | null;
  dosing_paused: boolean;
  /** The raw reading captured at each buffer, null until captured. */
  points: (number | null)[];
  /** Each point captured with "Capture anyway" while the reading was still moving. */
  forced?: boolean[];
}
export const SESSION_KEY = "crop-steering.cal-session";
type Storage = Pick<globalThis.Storage, "getItem" | "setItem" | "removeItem">;
const browserStorage = (): Storage | null => {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
};

/** sessionStorage `crop-steering.cal-session`: {session_id, expires_at, step} and what the wizard
 * needs to carry on. Any failure reads as no session. */
export function sessionStore(storage: Storage | null = browserStorage()) {
  const get = (): StoredSession | null => {
    try {
      const value: unknown = JSON.parse(storage?.getItem(SESSION_KEY) ?? "null");
      const s = value as StoredSession | null;
      return s && typeof s.session_id === "string" && typeof s.expires_at === "string" && typeof s.step === "number" ? s : null;
    } catch {
      return null;
    }
  };
  return {
    get,
    set(session: StoredSession) {
      try {
        storage?.setItem(SESSION_KEY, JSON.stringify(session));
      } catch {
        /* Private mode: the wizard simply cannot resume. */
      }
    },
    clear() {
      try {
        storage?.removeItem(SESSION_KEY);
      } catch {
        /* As above. */
      }
    },
    /** The room's stored session while its `expires_at` is in the future. */
    resumable(roomId: string, now: number): StoredSession | null {
      const s = get();
      return s && s.room_id === roomId && Date.parse(s.expires_at) > now ? s : null;
    },
  };
}

/** calibration.py `due()`: the probe's newest record that did not fail (applied or not: a failed
 * check does not reset the clock), and when it goes due, `at` + `due_days` whole days at that exact
 * time. A record without `due_days` never goes due (ruling R6): `dueAt` null. Records newest first. */
export function dueState(
  records: { probe?: string; verdict?: string; at: string; due_days?: number }[] | undefined,
  probe: FeedProbe,
): { at: number; dueAt: number | null } | null {
  const latest = records?.find((r) => r.probe === probe && r.verdict !== "fail");
  if (!latest) return null;
  const at = Date.parse(latest.at);
  if (!Number.isFinite(at)) return null;
  const days = latest.due_days;
  return { at, dueAt: typeof days === "number" && Number.isFinite(days) ? at + days * 86_400_000 : null };
}
/** The due line: "Overdue since 13 Oct" from the due time on (as binary_sensor …calibration_due
 * turns on), else the zone's calendar days to go. */
export function dueLine(dueAt: number, now: number, tz: string): { text: string; overdue: boolean } {
  if (now >= dueAt) return { text: `Overdue since ${shortDate(dueAt, tz)}`, overdue: true };
  const left = daysBetween(dayKey(now, tz), dayKey(dueAt, tz));
  return { text: left <= 0 ? "Due today" : `Due in ${left} ${left === 1 ? "day" : "days"}`, overdue: false };
}

/** Whether calibration_get holds record `recordId` as the one applied. */
export function isApplied(doc: { records?: { id: string; probe?: string; applied?: boolean }[] } | null | undefined, recordId: string): boolean {
  return !!doc?.records?.some((r) => r.id === recordId && r.applied === true);
}

/** A reading or buffer in the probe's unit: pH as "4.00 pH"-less digits, EC in the display unit. */
export function feedValue(value: number, kind: FeedKind, digits: number): string {
  return kind === "ph" ? value.toFixed(Math.max(0, digits)) : formatEc(value, digits);
}
/** A buffer's name: pH buffers by their two places ("7.00"), EC ones in the display unit. */
export const bufferName = (reference: number, kind: FeedKind) =>
  kind === "ph" ? reference.toFixed(2) : formatEc(reference, Math.max(2, (String(reference).split(".")[1] ?? "").length));
/** How many decimals a state's text carries. */
export const digitsOf = (text: string | undefined) => (text?.split(".")[1] ?? "").replace(/\D.*$/, "").length;

/** The room's corrected sensor (sensor.crop_steering_<prefix>feed_ph_corrected) in the second buffer,
 * once it uses this calibration: ticked within 0.1 of the buffer (the backend's offset pass). Null
 * until it reads this calibration. `digits`: the raw probe's. */
export function proofLine(
  states: States,
  prefix: string,
  probe: FeedProbe,
  reference: number,
  result: { slope_pct: number; offset: number },
  digits: number,
): { text: string; ok: boolean } | null {
  const entity = states[`sensor.crop_steering_${prefix}${probe}_corrected`];
  const value = Number(entity?.state);
  const a = entity?.attributes ?? {};
  if (!entity || entity.state === "" || !Number.isFinite(value) || a.slope_pct !== result.slope_pct || a.offset !== result.offset)
    return null;
  const kind = KIND_OF[probe];
  const buffer = kind === "ph" ? `pH ${bufferName(reference, kind)}` : bufferName(reference, kind);
  return {
    text: `Now reads ${feedValue(value, kind, digits)} in ${buffer} buffer`,
    ok: Math.abs(value - reference) <= 0.1,
  };
}
