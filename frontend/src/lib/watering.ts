import { callV2 } from "./parity-api";
import type { CsEvent, TimelineSummary } from "./parity-types";
import type { TimelineBlock, TimelineRow } from "./shot-timeline";
import { dayKey, startOfDay } from "./time";
import type { Controller } from "./types";

/** The Watering timeline page (I1, P2): its address, day strip, filters and Skip this shot. Pure,
 * apart from the two service calls of a skip. */

export type WateringSpan = 12 | 24 | 48;
export interface WateringQuery {
  /** "2026-10-22"; "" for today. */
  date: string;
  span: WateringSpan;
  /** Room names or ids from a link; empty for every room. */
  rooms: string[];
  /** "flower", "veg"; empty for every stage. */
  stages: string[];
  problemsOnly: boolean;
  /** Narrows the rows to a room or zone ("z3", "f2"). */
  q: string;
}

const HOUR = 3_600_000;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const list = (text: string | null) => (text ? text.split(",").filter(Boolean) : []);

/** `#/plan/watering?date=2026-10-22&span=24&rooms=F1,F2&stages=flower&problems=1&q=z3`. */
export function wateringQuery(hash: string): WateringQuery {
  const query = new URLSearchParams(hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "");
  const date = query.get("date") ?? "";
  const span = Number(query.get("span"));
  return {
    date: DATE.test(date) ? date : "",
    span: span === 12 || span === 48 ? span : 24,
    rooms: list(query.get("rooms")),
    stages: list(query.get("stages")),
    problemsOnly: query.get("problems") === "1",
    q: query.get("q") ?? "",
  };
}

export function wateringHash(q: WateringQuery): string {
  const parts = [
    q.date && `date=${q.date}`,
    `span=${q.span}`,
    q.rooms.length && `rooms=${q.rooms.map(encodeURIComponent).join(",")}`,
    q.stages.length && `stages=${q.stages.map(encodeURIComponent).join(",")}`,
    q.problemsOnly && "problems=1",
    q.q && `q=${encodeURIComponent(q.q)}`,
  ].filter(Boolean);
  return `#/plan/watering?${parts.join("&")}`;
}

/** A phone shows half a day, a wider window a whole one. */
export const defaultSpan = (width: number): 12 | 24 => (width <= 720 ? 12 : 24);

/** The calendar date `days` after `date`. */
export function shiftDate(date: string, days: number): string {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}
/** The week the day strip shows: three days either side of `date`. */
export const stripDates = (date: string) => Array.from({ length: 7 }, (_, i) => shiftDate(date, i - 3));

/** Midnight of `date` on the zone's clock. */
export function dayStart(date: string, tz: string): number {
  // Noon UTC is that date somewhere between a day before and a day after on any zone's clock.
  let t = Date.parse(`${date}T12:00:00Z`);
  const seen = dayKey(t, tz);
  if (seen > date) t -= 24 * HOUR;
  else if (seen < date) t += 24 * HOUR;
  return startOfDay(t, tz);
}

/** The span drawn: 24 and 48 h from the date's midnight; 12 h from seven hours before the hour now on
 * today (07:00–19:00 at 14:10), else the date's 06:00–18:00. */
export function spanOf(
  q: WateringQuery,
  now: number,
  tz: string,
  today = dayKey(now, tz),
): { start: number; end: number } {
  const date = q.date || today;
  const midnight = dayStart(date, tz);
  if (q.span !== 12) return { start: midnight, end: midnight + q.span * HOUR };
  const start = date === today ? now - (now - startOfDay(now, tz)) % HOUR - 7 * HOUR : midnight + 6 * HOUR;
  return { start, end: start + 12 * HOUR };
}

/** The day's failed shots and warnings over these rooms. */
export function dayProblems(summary: TimelineSummary | null, date: string, rooms: string[]) {
  const day = summary?.days.find((d) => d.date === date);
  const counted = day?.rooms.filter((r) => rooms.includes(r.room_id)) ?? [];
  return {
    failed: counted.reduce((n, r) => n + r.failed, 0),
    warnings: counted.reduce((n, r) => n + r.warnings, 0),
  };
}

/** A day button's second line: "Done", "1 problem", "3 problems" (failed plus warnings), "Planned". */
export function dayChip(
  summary: TimelineSummary,
  date: string,
  rooms: string[],
  today: string,
): { label: string; tone: "done" | "problem" | "planned" } {
  const { failed, warnings } = dayProblems(summary, date, rooms);
  const n = failed + warnings;
  if (n) return { label: n === 1 ? "1 problem" : `${n} problems`, tone: "problem" };
  return date > today ? { label: "Planned", tone: "planned" } : { label: "Done", tone: "done" };
}

/** Only the rooms (their own row and every zone) with a failed or warning block. */
export function keepProblems(rows: TimelineRow[]): TimelineRow[] {
  const bad = new Set(
    rows
      .filter((r) => r.blocks.some((b) => b.glyph === "failed" || b.glyph === "warning"))
      .map((r) => r.roomId),
  );
  return rows.filter((r) => bad.has(r.roomId));
}

/** Rows whose room or zone the search names: "z3" or "zone 3" a zone, else a room by name. */
export function matchQuery(rows: TimelineRow[], q: string): TimelineRow[] {
  const text = q.trim().toLowerCase();
  if (!text) return rows;
  const zone = /^z(?:one)?\s*(\d+)$/.exec(text);
  const names = new Map(rows.filter((r) => r.zone === null).map((r) => [r.roomId, r.label.toLowerCase()]));
  const keep = (r: TimelineRow) =>
    zone ? r.zone === Number(zone[1]) : (names.get(r.roomId) ?? "").includes(text);
  const rooms = new Set(rows.filter(keep).map((r) => r.roomId));
  return rows.filter((r) => (r.zone === null ? rooms.has(r.roomId) : keep(r)));
}

const WORD: Record<TimelineBlock["glyph"], string> = {
  done: "Done",
  planned: "Planned",
  expected: "Expected",
  failed: "Failed",
  warning: "Warning",
  queued: "Waiting for pump",
};
/** "Planned · waited 12 min for pump", "Watering now", "Skipped". */
export function statusLine(block: TimelineBlock): string {
  if (block.running) return "Watering now";
  if (block.skipped) return "Skipped";
  const wait = block.pumpWaitS ?? 0;
  return wait > 0 ? `${WORD[block.glyph]} · waited ${Math.max(1, Math.round(wait / 60))} min for pump` : WORD[block.glyph];
}

/** A Journal event the timeline draws, in a room it shows, inside its span. */
export function liveMatch(e: CsEvent, rooms: string[], span: { start: number; end: number }): boolean {
  if (!e.kind.startsWith("shot.") && !e.kind.startsWith("intent.")) return false;
  const t = Date.parse(e.ts);
  return rooms.includes(e.room_id) && t >= span.start && t < span.end;
}

/** Each room's timer store revision (timer_program_list `revisions`); null when it cannot be read. */
export async function loadRevisions(controller: Pick<Controller, "operator">): Promise<Record<string, number> | null> {
  const outcome = await callV2<{ revisions?: Record<string, number>; revision?: number | null }>(
    controller,
    "timer_program_list",
    {},
  );
  return outcome.kind === "ok" ? (outcome.data.revisions ?? {}) : null;
}

export type SkipResult =
  | { kind: "ok"; eventIds: string[]; verified: boolean }
  | { kind: "stale" }
  | { kind: "missing" }
  | { kind: "error"; message: string };

/** Skips one planned shot at the room's timer revision. A stale revision is answered, never retried. */
export async function skipShot(
  controller: Pick<Controller, "operator">,
  block: TimelineBlock,
  revisions: Record<string, number>,
): Promise<SkipResult> {
  const revision = revisions[block.roomId];
  if (revision === undefined) return { kind: "error", message: "Couldn't read the timers. Try again." };
  const outcome = await callV2(controller, "timer_skip", {
    room_id: block.roomId,
    zone: block.zone,
    at: new Date(block.start).toISOString(),
    expected_revision: revision,
  });
  if (outcome.kind === "ok")
    return { kind: "ok", eventIds: outcome.eventIds, verified: outcome.readback.status === "verified" };
  if (outcome.kind === "missing") return { kind: "missing" };
  if (outcome.code === "stale_revision") return { kind: "stale" };
  return { kind: "error", message: outcome.message };
}

/** What the page's body shows: the timeline (also whenever a room has no planned shots from the
 * controller, so its note shows), "No problems on this day." when Problems only hides every row of
 * a day that has blocks, else the empty state. `all` is before Problems only and the search. */
export function bodyState(rows: TimelineRow[], all: TimelineRow[], problemsOnly: boolean): "timeline" | "no-problems" | "empty" {
  if (all.some((r) => r.plannedUnavailable) || rows.some((r) => r.blocks.length)) return "timeline";
  return problemsOnly && all.some((r) => r.blocks.length) ? "no-problems" : "empty";
}

/** The phone's failed count opens the whole day: 12 h widens to 24 h. */
export const failedTap = (q: WateringQuery): WateringQuery => (q.span === 12 ? { ...q, span: 24 } : q);

/** The last answer, kept through a failed read only while the rooms and span are the same. */
export const keptData = <T extends { key: string }>(kept: T | null, key: string): T | null =>
  kept && kept.key === key ? kept : null;
