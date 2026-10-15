import { attachOutcomes, jevAnswer, jevResult, type JevEntry } from "./jev";
import type { LogEvent } from "./types";

/** History › Timeline: the controller's activity records and Jev's journal as one list, newest
 * first, each Jev outcome check on the decision it checks. Pure, so the merge is tested on its own. */

/** An activity record's time: an ISO stamp, or the controller's feed "HH:MM" on `reference`'s day
 * (the day before when that is still to come: the same wall-clock time, across a daylight-saving
 * change too). */
export function eventTime(stamp: string, reference: number): number | null {
  const clockOnly = stamp.match(/^(\d{1,2}):(\d{2})$/);
  if (!clockOnly) {
    const time = Date.parse(stamp);
    return Number.isFinite(time) ? time : null;
  }
  const date = new Date(reference);
  date.setHours(Number(clockOnly[1]), Number(clockOnly[2]), 0, 0);
  if (date.getTime() > reference + 5 * 60_000) date.setDate(date.getDate() - 1);
  return date.getTime();
}

/** Each record's time. The feed is newest first and says only "HH:MM": each line is read on the day
 * of the newer line before it, so a clock that goes forward down the list has crossed midnight. */
export function eventTimes(events: readonly LogEvent[], now: number): (number | null)[] {
  let newer = now;
  return events.map((event) => {
    const time = eventTime(event.timestamp, newer);
    if (time !== null && /^\d{1,2}:\d{2}$/.test(event.timestamp)) newer = time;
    return time;
  });
}

export type TimelineKind = "water" | "phase" | "setpoint" | "alert" | "jev" | "note";
export interface TimelineItem {
  key: string;
  /** Epoch ms; null when the record's time could not be read. */
  time: number | null;
  /** The zone it is about; null for the room. */
  zone: number | null;
  kind: TimelineKind;
  /** The controller's record, or Jev's entry: exactly one of the two. */
  event: LogEvent | null;
  jev: JevEntry | null;
  /** Jev's checks of this decision (worked or not), oldest first. */
  outcomes: JevEntry[];
}

/** A setpoint the controller logged as changed: a named setpoint and a new value. */
const SETPOINT_CHANGE =
  /\b(setpoint|threshold|shot size|dryback target|ec target)\b.*(→|->|\bto \d)/i;

export function eventKind(event: LogEvent): TimelineKind {
  if (event.type === "water") return "water";
  if (event.type === "phase") return "phase";
  if (event.type === "warning") return "alert";
  return SETPOINT_CHANGE.test(event.message) ? "setpoint" : "note";
}

/** Jev's Setpoints judge (its own changes, and the grower's that it noted) is a setpoint change, an
 * alert raised or triaged an alert; every other judge is Jev. */
export function jevKind(entry: JevEntry): TimelineKind {
  if (entry.judge === "setpoints") return "setpoint";
  if (entry.judge === "alerts" || /^CS-\d+/i.test(entry.action)) return "alert";
  return "jev";
}

/** One list, newest first. An outcome that names a decision on the list rides on it; one that does
 * not is a row of its own. A record without a readable time goes last, in its list's order. */
export function mergeTimeline(
  events: readonly LogEvent[],
  journal: readonly JevEntry[],
  now: number,
): TimelineItem[] {
  const times = eventTimes(events, now);
  const { rest, outcomes } = attachOutcomes(journal);
  const items: TimelineItem[] = [
    ...events.map((event, index) => ({
      key: `event:${event.id}`,
      time: times[index],
      zone: event.zoneId ?? null,
      kind: eventKind(event),
      event,
      jev: null,
      outcomes: [],
    })),
    ...rest.map((entry) => ({
      key: `jev:${entry.key}`,
      time: entry.time,
      zone: entry.zone,
      kind: jevKind(entry),
      event: null,
      jev: entry,
      outcomes: [...(outcomes.get(entry.key) ?? [])].reverse(),
    })),
  ];
  const order = new Map(items.map((item, index) => [item, index]));
  return items.sort((a, b) =>
    a.time !== null && b.time !== null
      ? b.time - a.time || order.get(a)! - order.get(b)!
      : a.time === null && b.time === null
        ? order.get(a)! - order.get(b)!
        : a.time === null
          ? 1
          : -1,
  );
}

/** Jev did something or tried to: acted, raised an alert, was refused, or an outcome of its own. */
export const jevActed = (entry: JevEntry) =>
  !["no action", "waiting", "unknown"].includes(entry.result);

export type TimelineType = "all" | "water" | "phase" | "setpoint" | "alert" | "jev";
export interface TimelineFilter {
  zone: "all" | "room" | number;
  type: TimelineType;
  /** Every Jev decision; otherwise only the ones that acted or tried to. */
  allJev: boolean;
  query: string;
}
export const NO_FILTER: TimelineFilter = { zone: "all", type: "all", allJev: false, query: "" };

/** A setpoint the grower changed, which Jev's Setpoints judge only noted (its range follows it):
 * the answer to "who changed this, me or Jev?". */
export const byHand = (entry: JevEntry) =>
  entry.judge === "setpoints" && /\bby hand\b/i.test(entry.verdict);

/** The row in words, for search and the CSV: the controller's message, the grower's change, or
 * Jev's answer and ask. */
export function timelineText(item: TimelineItem): string {
  if (item.event) return item.event.message;
  const entry = item.jev!;
  const action = entry.action.replaceAll("->", "→");
  if (byHand(entry)) return `By hand · ${entry.title}: ${action}`;
  const said =
    entry.kind === "outcome" ? `after “${entry.verdict || "an earlier call"}”` : jevAnswer(entry);
  return `Jev · ${entry.title}: ${said}${action ? ` → ${action}` : ""}`;
}

/** What code did with a Jev row, and how its outcome checks came out. Empty for a controller record. */
export function timelineResult(item: TimelineItem): string {
  if (!item.jev) return "";
  if (byHand(item.jev)) return "Noted by Jev";
  const checks = item.outcomes.map((outcome) =>
    outcome.result === "worked" ? "worked" : "did not work",
  );
  return [jevResult(item.jev).label, ...checks].join("; ");
}

export function filterTimeline(
  items: readonly TimelineItem[],
  filter: TimelineFilter,
): TimelineItem[] {
  const query = filter.query.trim().toLowerCase();
  return items.filter(
    (item) =>
      (filter.zone === "all" ||
        (filter.zone === "room" ? item.zone === null : item.zone === filter.zone)) &&
      (filter.type === "all" || item.kind === filter.type) &&
      (!item.jev || filter.allJev || jevActed(item.jev)) &&
      (!query || `${timelineText(item)} ${item.jev?.reason ?? ""}`.toLowerCase().includes(query)),
  );
}

/** The rows as CSV: time as the local wall clock, zone, type, the row in words and Jev's result. A
 * cell that a spreadsheet would run as a formula starts with a quote. */
export function timelineCsv(items: readonly TimelineItem[], room: string): string {
  const cell = (value: string) => `"${value.replace(/^[=+@-]/, "'$&").replaceAll('"', '""')}"`;
  const two = (value: number) => String(value).padStart(2, "0");
  const stamp = (time: number | null) => {
    if (time === null) return "";
    const date = new Date(time);
    return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())} ${two(date.getHours())}:${two(date.getMinutes())}:${two(date.getSeconds())}`;
  };
  return [
    ["Timestamp", "Room", "Zone", "Type", "Message", "Result"],
    ...items.map((item) => [
      stamp(item.time),
      room,
      item.zone === null ? "Room" : String(item.zone),
      item.kind,
      timelineText(item),
      timelineResult(item),
    ]),
  ]
    .map((row) => row.map(cell).join(","))
    .join("\r\n");
}
