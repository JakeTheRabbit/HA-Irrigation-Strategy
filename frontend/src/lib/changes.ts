import type { ApplyReceipt } from "@/components/review-apply";
import { formatEc, formatTemp, formatVolume } from "./display-units";
import { callV2, type V2Outcome } from "./parity-api";
import type { HistoryChange, HistoryRevertResult } from "./parity-types";
import { presetWords } from "./presets";
import { dayKey, dayLabel, startOfDay } from "./time";
import type { Controller, Room, States, WriteResult } from "./types";
import { revertEvents } from "./undo";
import { sameValue } from "./utils";

/** History › Changes (H4): who changed which setting, from what to what, why, and how it worked
 * out, from the Journal (`history_changes`, 3.18) or a 3.17 room's setpoint log
 * (`setpoint_log_get`), and putting one back. */

/** Who made a change, as its chip says it. The backend's `manual` is whoever was signed in: the
 * chip reads "You" for every person; the panel names them when the backend does (`user_name`). */
export const ACTOR_CHIP: Record<string, string> = {
  manual: "You",
  learner: "Learner",
  ai: "AI judge",
  timer: "Timer",
  plan: "Plan",
  mcp: "MCP",
  aigrow: "AiGrow",
  safety: "Safety",
  automation: "Automation",
  system: "Setup",
  engine: "Engine",
};
export const CHANGE_KINDS: readonly HistoryChange["kind"][] = ["setpoint", "plan", "recipe", "setup", "calibration", "alerts"];
export const KIND_LABEL: Record<HistoryChange["kind"], string> = {
  setpoint: "Setpoint",
  plan: "Plan",
  recipe: "Recipe",
  setup: "Setup",
  calibration: "Calibration",
  alerts: "Alerts",
};

export interface ChangeEntry {
  id: string;
  at: number;
  actor: string;
  chip: string;
  roomId: string;
  kind: HistoryChange["kind"];
  /** Where it applies: "F2 · Zone 2", "F2 · all zones", "All rooms". */
  scope: string;
  label: string;
  /** "" when the change has no value to show (a calibration record, a whole section). */
  before: string;
  after: string;
  reason: string | null;
  outcome: string | null;
  limits: string | null;
  revertible: boolean;
  /** The revert button's words, or why there is none. */
  revertLabel: string;
  zone: number | null;
  key: string | null;
  /** The setting's entity: the was/now bar and a 3.17 write-back. */
  entityId: string | null;
  oldValue: unknown;
  newValue: unknown;
  /** The Home Assistant user the backend names, if it does. */
  user: string | null;
  /** Journal: put back by `history_revert`. Log: a 3.17 setpoint log row, written back. */
  source: "journal" | "log";
}

/** A setting key and its values in grower words and display units, and a room's name. */
export interface ChangeWords {
  label(key: string): string;
  value(key: string, value: unknown, roomId?: string): string;
  room(roomId: string): string;
}

const decimals = (value: number) => {
  const text = String(value);
  return text.includes("e-") ? Number(text.split("e-")[1]) : (text.split(".")[1]?.length ?? 0);
};
/** A number in its unit, at its own precision, through the display units. */
export function valueText(value: number, unit: string): string {
  const digits = decimals(value);
  if (unit.startsWith("%")) return `${value}${unit}`;
  if (unit === "mS/cm") return formatEc(value, digits);
  if (unit === "L") return formatVolume(value, digits);
  if (unit === "°C") return formatTemp(value, digits);
  return unit ? `${value} ${unit}` : String(value);
}

export function changeWords(states: States, rooms: Room[]): ChangeWords {
  const preset = presetWords(states, rooms);
  const unitOf = (key: string, roomId?: string) => {
    const order = [...rooms].sort((a, b) => Number(b.id === roomId) - Number(a.id === roomId));
    for (const room of order) {
      const root = `number.crop_steering_${room.prefix}`;
      const id = Object.keys(states).find(
        (entityId) =>
          entityId.startsWith(root) &&
          entityId.endsWith(key) &&
          /^(zone_\d+_)?$/.test(entityId.slice(root.length, entityId.length - key.length)),
      );
      const unit = id ? states[id].attributes.unit_of_measurement : undefined;
      if (typeof unit === "string") return unit;
    }
    return "";
  };
  return {
    label: preset.label,
    value: (key, value, roomId) => (typeof value === "number" ? valueText(value, unitOf(key, roomId)) : scalar(value)),
    room: (roomId) => rooms.find((room) => room.id === roomId)?.name ?? (roomId.replace(/^room:/, "").replace(/_$/, "") || roomId),
  };
}

const humanize = (text: string) => {
  const words = text.replaceAll("_", " ").replace(/\bp(\d)\b/g, "P$1").replace(/\bph\b/gi, "pH").replace(/\bec\b/gi, "EC");
  return words.charAt(0).toUpperCase() + words.slice(1);
};
const scalar = (value: unknown) =>
  value === null || value === undefined ? "none" : typeof value === "boolean" ? (value ? "on" : "off") : String(value);
const isScalar = (value: unknown) => value === null || ["string", "number", "boolean"].includes(typeof value);

/** The leaves that differ between two saved sections, as dotted paths. */
function leafDiff(old: unknown, next: unknown, path = ""): { path: string; old: unknown; new: unknown }[] {
  const objects = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object";
  if (!objects(old) || !objects(next))
    return JSON.stringify(old) === JSON.stringify(next) ? [] : [{ path, old, new: next }];
  const keys = [...new Set([...Object.keys(old), ...Object.keys(next)])];
  return keys.flatMap((key) => leafDiff(old[key], next[key], path ? `${path}.${key}` : key));
}

const SECTION_LABEL: Record<string, string> = {
  room: "Room setup",
  zones: "Zones",
  supply: "Water supply",
  presets: "Presets",
  programs: "Timer programs",
  probe_user_offsets: "Probe offsets",
  alert_rules: "Alert rules",
  dashboards: "Dashboards",
};
const PLAN_STATUS: Record<string, string> = {
  saved: "saved",
  armed: "armed",
  activated: "started",
  disarmed: "stopped",
  expired: "ended",
};
const VERDICT: Record<string, string> = {
  pass: "The check passed.",
  warn: "The check passed with a warning.",
  fail: "The check failed.",
  reverted: "Went back to the calibration before it.",
};
const LEFT_OUT = /left.?out|excluded/i;

/** One change row in words. */
function entryOf(change: HistoryChange, words: ChangeWords): ChangeEntry {
  const zone = change.scope?.startsWith("zone:") ? Number(change.scope.slice(5)) : null;
  const setting = change.kind === "setpoint" || (change.kind === "recipe" && change.key && !change.section);
  const where =
    change.scope === "site"
      ? null
      : zone !== null
        ? `Zone ${zone}`
        : setting
          ? "all zones"
          : "room";
  const scope = where === null ? "All rooms" : `${words.room(change.room_id)} · ${where}`;
  let label = change.key ? words.label(change.key) : humanize(change.section ?? change.kind);
  let before = "";
  let after = "";
  let reason = change.reason;
  let leftOut = false;
  if (setting && change.key) {
    before = words.value(change.key, change.old, change.room_id);
    after = words.value(change.key, change.new, change.room_id);
  } else if (change.kind === "plan") {
    label = "Grow plan";
    after = PLAN_STATUS[String(change.new)] ?? scalar(change.new);
    if (reason && (reason in PLAN_STATUS || reason === change.new)) reason = null;
  } else if (change.section === "calibration") {
    // Old and new are calibration record ids: nothing to show.
    label = `${humanize(change.key ?? "probe")} calibration`;
    reason = reason ? (VERDICT[reason] ?? reason) : null;
  } else if (change.section === "pump" && typeof change.new === "number") {
    label = `${humanize(change.key ?? "dosing")} pump rate`;
    before = typeof change.old === "number" ? valueText(change.old, "mL/min") : "";
    after = valueText(change.new, "mL/min");
  } else {
    const section = SECTION_LABEL[change.section ?? ""] ?? humanize(change.section ?? change.kind);
    const leaves = leafDiff(change.old, change.new);
    if (leaves.length === 1 && isScalar(leaves[0].old) && isScalar(leaves[0].new)) {
      const leaf = leaves[0].path.split(".").filter((part) => !/^\d+$/.test(part)).at(-1) ?? "";
      label = leaf ? `${section} · ${humanize(leaf)}` : section;
      before = change.old === null || change.old === undefined ? "" : scalar(leaves[0].old);
      after = scalar(leaves[0].new);
      leftOut = LEFT_OUT.test(after) && !LEFT_OUT.test(before);
    } else label = leaves.length > 1 ? `${section}: ${leaves.length} settings` : section;
  }
  if (!reason && change.detail === "put back") reason = "Put back from History.";
  const limits =
    change.limits && change.limits.min !== null && change.limits.max !== null && change.key
      ? `${change.limits.writer === "brain" ? "AI judge" : "learner"} may move it between ${words.value(change.key, change.limits.min, change.room_id)} and ${words.value(change.key, change.limits.max, change.room_id)}`
      : null;
  const revertLabel = !change.revertible
    ? change.kind === "plan"
      ? "Plan step. Edit the plan to change it."
      : "This change can't be put back"
    : leftOut
      ? "Put back in reading"
      : change.kind === "calibration"
        ? "Restore previous calibration"
        : before
          ? `Revert to ${before}`
          : "Put back the previous version";
  const prefix = change.room_id.replace(/^room:/, "");
  return {
    id: change.id,
    at: Date.parse(change.ts),
    actor: change.actor,
    chip: ACTOR_CHIP[change.actor] ?? humanize(change.actor ?? "unknown"),
    roomId: change.room_id,
    kind: change.kind,
    scope,
    label,
    before,
    after,
    reason,
    outcome: change.outcome,
    limits,
    revertible: change.revertible,
    revertLabel,
    zone,
    key: change.key ?? null,
    entityId:
      setting && change.key ? `number.crop_steering_${prefix}${zone !== null ? `zone_${zone}_` : ""}${change.key}` : null,
    oldValue: change.old,
    newValue: change.new,
    user: change.user_name ?? null,
    source: "journal",
  };
}

/** `history_changes` rows as entries, newest first. */
export function toEntries(changes: HistoryChange[], words: ChangeWords): ChangeEntry[] {
  return changes.map((change) => entryOf(change, words)).sort((a, b) => b.at - a.at);
}

/** A 3.17 room's setpoint log row (`setpoint_log_get`). */
export interface SetpointLogRow {
  at: string;
  entity_id: string;
  field: string;
  zone: number | null;
  old: unknown;
  new: unknown;
  who: string;
  reason?: string;
  expected?: string;
}
/** The log's `who` as the Journal's actor (the integration's setpoint_log.ACTORS). */
const LOG_ACTORS: Record<string, string> = {
  operator: "manual",
  home_assistant: "automation",
  learner: "learner",
  brain: "ai",
  safety: "safety",
};
/** A 3.17 room's setpoint log as entries, newest first: each a setting, written back by the panel. */
export function fromSetpointLog(rows: SetpointLogRow[], roomId: string, words: ChangeWords): ChangeEntry[] {
  return rows
    .map((row, index) => ({
      ...entryOf(
        {
          id: `log:${row.entity_id}:${row.at}:${index}`,
          room_id: roomId,
          ts: row.at,
          actor: (LOG_ACTORS[row.who] ?? "system") as HistoryChange["actor"],
          kind: "setpoint",
          key: row.field,
          scope: row.zone === null || row.zone === undefined ? "room" : `zone:${row.zone}`,
          old: row.old,
          new: row.new,
          reason: row.reason ?? null,
          outcome: null,
          limits: null,
          revertible: typeof row.old === "number" && typeof row.new === "number",
          user_id: null,
          user_name: null,
        },
        words,
      ),
      entityId: row.entity_id,
      source: "log" as const,
    }))
    .sort((a, b) => b.at - a.at);
}

/** The page's address: `#/history/changes?since=&until=&actor=&kind=&room=&id=`. `room` is a room
 * id or a room tree pick key (`room:f1_:2`, a zone). */
export interface ChangesQuery {
  since: string;
  until?: string;
  actor?: string;
  kind?: string;
  room?: string;
  id?: string;
}
const QUERY_KEYS = ["since", "until", "actor", "kind", "room", "id"] as const;
export function changesQuery(hash: string): ChangesQuery {
  const params = new URLSearchParams(hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "");
  const out: ChangesQuery = { since: params.get("since") ?? "" };
  for (const key of QUERY_KEYS.slice(1)) {
    const value = params.get(key);
    if (value) out[key] = value;
  }
  return out;
}
export function changesHash(query: ChangesQuery): string {
  const params = new URLSearchParams();
  for (const key of QUERY_KEYS) if (query[key]) params.set(key, query[key]!);
  const text = params.toString();
  return `#/history/changes${text ? `?${text}` : ""}`;
}

/** Entries by the room's calendar day, newest first: "Today · Thu 22 Oct", "Yesterday · Wed 21 Oct",
 * then "Mon 19 Oct". */
export function groupByDay(entries: ChangeEntry[], tz: string, now: number): { key: string; title: string; entries: ChangeEntry[] }[] {
  const today = dayKey(now, tz);
  const yesterday = dayKey(startOfDay(now, tz) - 1, tz);
  const days = new Map<string, { key: string; title: string; entries: ChangeEntry[] }>();
  for (const entry of [...entries].sort((a, b) => b.at - a.at)) {
    const key = dayKey(entry.at, tz);
    let day = days.get(key);
    if (!day) {
      const label = dayLabel(entry.at, tz);
      day = { key, title: key === today ? `Today · ${label}` : key === yesterday ? `Yesterday · ${label}` : label, entries: [] };
      days.set(key, day);
    }
    day.entries.push(entry);
  }
  return [...days.values()];
}

/** The backend judges only the learner's and the AI judge's changes (changes.py WRITERS). */
const JUDGED = new Set(["learner", "ai"]);
/** "What happened next": the backend's judgement, or why there is none. */
export function nextText(entry: ChangeEntry): string {
  if (entry.outcome) return entry.outcome;
  if (!JUDGED.has(entry.actor)) return "Only learner and AI judge changes are judged afterwards.";
  return "Not judged yet.";
}

/** The setting's value now, in words, when it has moved since the change; else null. */
export function liveValue(entry: ChangeEntry, states: States, words: ChangeWords): string | null {
  const entity = entry.entityId ? states[entry.entityId] : undefined;
  const value = entity && entity.state.trim() !== "" ? Number(entity.state) : NaN;
  if (!entity || !entry.key || typeof entry.newValue !== "number" || !Number.isFinite(value)) return null;
  const step = Number(entity.attributes?.step);
  return sameValue(entity.state, entry.newValue, Number.isFinite(step) ? step : undefined) ? null : words.value(entry.key, value, entry.roomId);
}

const WEEK_MS = 7 * 86_400_000;
/** The week before what is shown: up to `since`, or up to the oldest row shown when the read was
 * cut short at the newest rows. */
export function olderRange(shown: ChangeEntry[], since: number, truncated: boolean): { since: number; until: number } {
  const oldest = shown.reduce((min, e) => Math.min(min, e.at), Infinity);
  return { since: since - WEEK_MS, until: truncated && Number.isFinite(oldest) ? oldest : since };
}

/** Older rows appended to the shown ones, each once, newest first. */
export function mergeEntries(shown: ChangeEntry[], older: ChangeEntry[]): ChangeEntry[] {
  const ids = new Set(shown.map((e) => e.id));
  return [...shown, ...older.filter((e) => !ids.has(e.id))].sort((a, b) => b.at - a.at);
}

/** How many entries each value of a field has. */
export function countBy<K extends "actor" | "kind">(entries: ChangeEntry[], field: K): Map<string, number> {
  const out = new Map<string, number>();
  for (const entry of entries) out.set(entry[field], (out.get(entry[field]) ?? 0) + 1);
  return out;
}

type Refusal = Extract<V2Outcome<unknown>, { kind: "error" | "missing" }>;
type Writer = Pick<Controller, "operator" | "write">;
const summaryOf = (entry: ChangeEntry) =>
  entry.before ? `${entry.label} ${entry.after} → ${entry.before}` : entry.label;
const stale = (what: string): Refusal => ({
  kind: "error",
  code: "stale_revision",
  message: `${what} has changed since this change. Reload the history and check it before trying again.`,
});

/** Puts one change back. 3.18: `history_revert`, a receipt only when the controller read it back,
 * with the put-back's own event for Undo. 3.17: the old value written again with read-back, only
 * while the setting still holds the change's value. */
export async function revertChange(
  controller: Writer,
  states: States,
  entry: ChangeEntry,
  now: () => number = Date.now,
): Promise<ApplyReceipt | Refusal> {
  if (entry.source === "log") {
    if (!entry.entityId || typeof entry.oldValue !== "number" || typeof entry.newValue !== "number")
      return { kind: "error", code: "invalid", message: "This change can't be put back" };
    if (!sameValue(states[entry.entityId]?.state, entry.newValue)) return stale(entry.label);
    const result: WriteResult = await controller.write([{ entityId: entry.entityId, value: entry.oldValue }]);
    const failed = result.failed[0];
    if (!failed) return { at: now(), ok: true, failed: [], summary: summaryOf(entry), eventIds: [] };
    if (/did not confirm|unconfirmed/i.test(failed.reason))
      return { at: now(), ok: false, failed: [], notConfirmed: [entry.id], summary: "", eventIds: [] };
    return { at: now(), ok: false, failed: [{ id: entry.id, holds: entry.after, label: entry.label }], summary: "", eventIds: [] };
  }
  const outcome = await callV2<HistoryRevertResult>(controller, "history_revert", { event_id: entry.id });
  if (outcome.kind !== "ok") return outcome;
  if (outcome.readback.status !== "verified")
    return { at: now(), ok: false, unconfirmed: true, failed: [], summary: "", eventIds: [] };
  const id = outcome.data?.new_event_id;
  const at = outcome.readback.at ? Date.parse(outcome.readback.at) : NaN;
  return {
    at: Number.isFinite(at) ? at : now(),
    ok: true,
    failed: [],
    summary: summaryOf(entry),
    eventIds: id ? [id] : [],
    ...(id ? {} : { undoUnavailable: true }),
  };
}

/** Undo of a put-back. 3.18: `revertEvents` of the put-back's event. 3.17: the change's value
 * written again, only while the setting still holds the value put back. Throws with the reason. */
export async function undoRevert(controller: Writer, states: States, entry: ChangeEntry, receipt: ApplyReceipt): Promise<void> {
  if (entry.source === "journal") {
    await revertEvents(controller, receipt.eventIds);
    return;
  }
  if (!entry.entityId || typeof entry.newValue !== "number" || typeof entry.oldValue !== "number")
    throw new Error("This change can't be put back");
  if (!sameValue(states[entry.entityId]?.state, entry.oldValue))
    throw new Error(`${entry.label} has changed since. Reload and check it before trying again.`);
  const result = await controller.write([{ entityId: entry.entityId, value: entry.newValue }]);
  if (result.failed.length)
    throw new Error(
      /did not confirm|unconfirmed/i.test(result.failed[0].reason)
        ? "The controller did not confirm the value. Reload and check it before trying again."
        : `Not written back: ${result.failed[0].reason}`,
    );
}
