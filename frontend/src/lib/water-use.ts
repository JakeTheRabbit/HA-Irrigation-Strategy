import { addDays, daysBetween, validDate } from "./comparison";
import type { StrategyDocument, ZonePlan } from "./operator-types";

/** One reading of a zone's water-today counter (litres since its last reset), at the instant it
 * counts from. */
export interface CounterSample {
  time: number;
  value: number;
}
export interface WaterRecordRequest {
  entityIds: string[];
  start: number;
  end: number;
}
export interface WaterRecord {
  /** "statistics": Home Assistant's hourly long-term statistics, kept indefinitely. "history": its
   * recorded states, which reach back only as far as the recorder keeps them. */
  source: "statistics" | "history" | "demo";
  samples: Record<string, CounterSample[]>;
}

const clocks = new Map<string, Intl.DateTimeFormat>();
function localClock(time: number, timeZone: string) {
  let clock = clocks.get(timeZone);
  if (!clock) {
    clock = new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
    clocks.set(timeZone, clock);
  }
  const part: Record<string, string> = {};
  for (const { type, value } of clock.formatToParts(time)) part[type] = value;
  return {
    date: `${part.year}-${part.month}-${part.day}`,
    hour: Number(part.hour) + Number(part.minute) / 60,
  };
}

/** The grow-day `time` falls in, named by the local date of the lights-on that starts it. This is
 * the controller's own rule (_grow_day_start) on the local wall clock, so the grow-day that loses
 * or gains a daylight-saving hour is still one grow-day. */
export function growDayOf(time: number, lightsOn: number, timeZone: string): string {
  const { date, hour } = localClock(time, timeZone);
  return hour >= lightsOn ? date : addDays(date, -1);
}

/** Hourly long-term statistics rows (`recorder/statistics_during_period`, types ["state"]) as
 * readings. A row's state is the counter at the end of its hour, so it counts just before that
 * end: an hour that ends on lights-on still belongs to the grow-day it closes. */
export function statisticSamples(result: unknown): Record<string, CounterSample[]> {
  if (!result || typeof result !== "object")
    throw new Error("Home Assistant returned invalid statistics.");
  const instant = (value: unknown) =>
    typeof value === "number" ? value : typeof value === "string" ? Date.parse(value) : NaN;
  const samples: Record<string, CounterSample[]> = {};
  for (const [id, rows] of Object.entries(result as Record<string, unknown>)) {
    if (!Array.isArray(rows)) continue;
    samples[id] = rows.flatMap((row: { start?: unknown; end?: unknown; state?: unknown }) => {
      const end = row?.end !== undefined ? instant(row.end) : instant(row?.start) + 3_600_000;
      return typeof row?.state === "number" && Number.isFinite(row.state) && Number.isFinite(end)
        ? [{ time: end - 1, value: row.state }]
        : [];
    });
  }
  return samples;
}

/** Recorded states (`history/period`) as readings: numbers only, so an unavailable spell while
 * something restarts leaves no reading at all. */
export function historySamples(
  rows: Record<string, { state: string; time: number }[]>,
): Record<string, CounterSample[]> {
  return Object.fromEntries(
    Object.entries(rows).map(([id, list]) => [
      id,
      list.flatMap(({ state, time }) =>
        state.trim() && Number.isFinite(Number(state)) ? [{ time, value: Number(state) }] : [],
      ),
    ]),
  );
}

/** Litres per grow-day from readings of a counter that the controller resets once a grow-day, at
 * the P3→P0 change just after lights-on.
 * - A grow-day's total is the peak its counter reached after that reset. Until the reset the old
 *   counter keeps running: only what it gained after lights-on is added to the new day.
 * - A reset hidden between two readings (more water in the first hour than the whole day before)
 *   still starts the new count at the lights-on boundary.
 * - Only peaks count, so a reading that dips and comes back (a restart re-publishing the same
 *   value) changes nothing.
 * - A counter that sat at the day before's level all day (controller stopped) delivered nothing.
 * - A grow-day without readings is missing, never zero, and nothing carries across it. */
export function growDayTotals(
  samples: CounterSample[],
  lightsOn: number,
  timeZone: string,
): Map<string, number> {
  const byDay = new Map<string, number[]>();
  for (const { time, value } of [...samples].sort((a, b) => a.time - b.time)) {
    if (!Number.isFinite(time) || !Number.isFinite(value) || value < 0) continue;
    const day = growDayOf(time, lightsOn, timeZone);
    const values = byDay.get(day);
    if (values) values.push(value);
    else byDay.set(day, [value]);
  }
  const totals = new Map<string, number>();
  let level: number | null = null;
  let previous = "";
  for (const [day, values] of byDay) {
    if (previous && addDays(previous, 1) !== day) level = null;
    let peak: number = level ?? values[0];
    let reset = -1;
    for (const [index, value] of values.entries()) {
      if (value < peak) {
        reset = index;
        break;
      }
      peak = value;
    }
    let total: number;
    if (reset >= 0) {
      const after = Math.max(...values.slice(reset));
      total = (level === null ? 0 : peak - level) + after;
      level = after;
    } else {
      // Starting on the day before's value means the counter has not reset: only its gain counts.
      total = level !== null && values[0] === level ? peak - level : peak;
      level = peak;
    }
    totals.set(day, round(total));
    previous = day;
  }
  return totals;
}

/** Grow-days from several readings of the same counter (the controller's sensor, then the
 * integration's mirror of it): the first series that has a grow-day supplies it. */
export function mergeDays(...series: Map<string, number>[]): Map<string, number> {
  const merged = new Map<string, number>();
  for (const days of series)
    for (const [day, litres] of days) if (!merged.has(day)) merged.set(day, litres);
  return new Map([...merged].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
}

export interface DayRange {
  first: string;
  last: string;
  litres: number;
  /** Grow-days in the range, and how many of them have no readings. */
  days: number;
  missing: number;
}
export function sumDays(days: Map<string, number>, first: string, last: string): DayRange {
  let litres = 0,
    count = 0,
    missing = 0;
  for (let day = first; day <= last; day = addDays(day, 1)) {
    count++;
    const value = days.get(day);
    if (value === undefined) missing++;
    else litres += value;
  }
  return { first, last, litres: round(litres), days: count, missing };
}

/** Dry grow-days in a row that separate one grow from the next. */
export const DRY_GAP = 5;
/** Where no grow plan says when the grow started: the first grow-day with water in any zone after
 * the latest run of at least DRY_GAP grow-days without any. `afterDry` is null when the record
 * begins inside the grow, so the start can only be "on or before" this day. Null when nothing is
 * recorded, or when the room has had no water for longer than a DRY_GAP (no grow in progress). */
export function inferStart(
  zones: Map<string, number>[],
  today: string,
  dry = DRY_GAP,
): { date: string; afterDry: number | null } | null {
  let first: string | null = null;
  const watered = new Set<string>();
  for (const days of zones)
    for (const [day, litres] of days) {
      if (day > today) continue;
      if (first === null || day < first) first = day;
      if (litres > 0) watered.add(day);
    }
  const sorted = [...watered].sort();
  if (!first || !sorted.length || daysBetween(sorted.at(-1)!, today) > dry) return null;
  for (let index = sorted.length - 1; index > 0; index--) {
    const gap = daysBetween(sorted[index - 1], sorted[index]) - 1;
    if (gap >= dry) return { date: sorted[index], afterDry: gap };
  }
  const before = daysBetween(first, sorted[0]);
  return { date: sorted[0], afterDry: before >= dry ? before : null };
}

/** A plan's length in grow-days: its last scheduled day. */
export function planDays(zone: ZonePlan | undefined): number | null {
  const ends = (zone?.schedule ?? []).map((block) => block.end_day).filter(Number.isInteger);
  return ends.length ? Math.max(...ends) : null;
}

export interface GrowStart {
  date: string;
  /** "plan": an armed (or running) grow plan. "draft": a saved draft that is not armed.
   * "inferred": from the water record. "records": the record begins inside the grow. */
  source: "plan" | "draft" | "inferred" | "records";
  planDays: number | null;
  afterDry: number | null;
}
const COMMITTED = new Set(["armed", "active", "disarming", "error"]);
/** A zone's grow start: the grow plan's start date when the plan is armed or has been saved; the
 * inferred start otherwise. A draft never saved (revision 0) is the integration's placeholder,
 * dated the day it was created, not the grow's start. A start in the future is a plan for the
 * next grow. */
export function resolveStart(
  document: Pick<StrategyDocument, "status" | "revision" | "plan"> | null,
  zoneId: number,
  today: string,
  inferred: { date: string; afterDry: number | null } | null,
): GrowStart | null {
  const zone = document?.plan?.zones?.find((item) => item.zone_id === zoneId);
  if (document && zone && validDate(zone.start_date) && zone.start_date <= today) {
    if (COMMITTED.has(document.status))
      return { date: zone.start_date, source: "plan", planDays: planDays(zone), afterDry: null };
    if (document.revision > 0)
      return { date: zone.start_date, source: "draft", planDays: planDays(zone), afterDry: null };
  }
  return inferred
    ? {
        date: inferred.date,
        source: inferred.afterDry === null ? "records" : "inferred",
        planDays: null,
        afterDry: inferred.afterDry,
      }
    : null;
}

export interface WeekTotal extends DayRange {
  week: number;
}
/** Litres per grow week: sevens of grow-days from the grow start, the current week so far last. */
export function growWeeks(days: Map<string, number>, start: string, today: string): WeekTotal[] {
  const weeks: WeekTotal[] = [];
  for (let first = start, week = 1; first <= today; first = addDays(first, 7), week++) {
    const end = addDays(first, 6);
    weeks.push({ week, ...sumDays(days, first, end < today ? end : today) });
  }
  return weeks;
}

export interface ZoneWaterUse {
  today: { day: string; litres: number | null };
  /** Grow-day number of today, from the grow start (day 1). */
  growDay: number | null;
  /** The current grow week (from the start), else the last 7 grow-days; today included. */
  week: DayRange & { growWeek: number | null };
  /** From the grow start, or from the first recorded grow-day when the record begins later. */
  sinceStart: (DayRange & { recordsBegin: boolean }) | null;
  /** Litres a day over the last 7 full grow-days that have readings, never before the start. */
  average: (DayRange & { perDay: number }) | null;
  /** Used so far + average × grow-days left in the plan; null without a plan length. */
  estimate: { total: number; daysLeft: number; planDays: number } | null;
  /** The average as litres a week, where the plan length is unknown. */
  perWeek: number | null;
  weeks: WeekTotal[];
}
export function zoneWaterUse(
  days: Map<string, number>,
  today: string,
  start: GrowStart | null,
): ZoneWaterUse {
  const growDay = start ? daysBetween(start.date, today) + 1 : null;
  const weekFirst =
    start && growDay ? addDays(start.date, Math.floor((growDay - 1) / 7) * 7) : addDays(today, -6);
  const recorded = [...days.keys()].filter((day) => day <= today).sort()[0];
  const from = start && recorded ? (recorded > start.date ? recorded : start.date) : null;
  const sinceStart =
    start && from ? { ...sumDays(days, from, today), recordsBegin: from !== start.date } : null;
  const averageFirst = [addDays(today, -7), start?.date ?? ""].sort().at(-1)!;
  const recent = averageFirst < today ? sumDays(days, averageFirst, addDays(today, -1)) : null;
  const counted = recent ? recent.days - recent.missing : 0;
  const average = recent && counted ? { ...recent, perDay: recent.litres / counted } : null;
  const plan = start?.planDays ?? null;
  const daysLeft = plan !== null && growDay !== null ? Math.max(0, plan - growDay) : null;
  return {
    today: { day: today, litres: days.get(today) ?? null },
    growDay,
    week: {
      ...sumDays(days, weekFirst, today),
      growWeek: growDay ? Math.floor((growDay - 1) / 7) + 1 : null,
    },
    sinceStart,
    average,
    estimate:
      average && sinceStart && daysLeft !== null && plan !== null
        ? { total: round(sinceStart.litres + average.perDay * daysLeft), daysLeft, planDays: plan }
        : null,
    perWeek: average && daysLeft === null ? round(average.perDay * 7) : null,
    weeks: start ? growWeeks(days, start.date, today) : [],
  };
}

function round(value: number) {
  return Math.round(value * 100) / 100;
}
