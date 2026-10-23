import type { ComparedRun, DailyReading, HistoryPoint, RunRecord } from "./comparison-types";
import { formatEc, formatVolume } from "./display-units";
import { yieldFigures, type GrowDay, type Harvest, type HarvestsDocument } from "./grows";
import type { Stage } from "./stage-arc";
import { dayLabel, daysBetween } from "./time";
export { daysBetween };
const DAY = 86_400_000;
const formatters = new Map<string, Intl.DateTimeFormat>();
function formatter(zone: string) {
  let value = formatters.get(zone);
  if (!value) {
    value = new Intl.DateTimeFormat("en-CA", {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    if (formatters.size > 20) formatters.clear();
    formatters.set(zone, value);
  }
  return value;
}
export function dateInZone(time: number, zone: string): string {
  const parts = formatter(zone).formatToParts(time);
  return ["year", "month", "day"].map((key) => parts.find((p) => p.type === key)!.value).join("-");
}
export function validDate(value: string): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value + "T00:00:00Z").toISOString().slice(0, 10) === value
  );
}
export function addDays(value: string, days: number): string {
  if (!validDate(value) || !Number.isInteger(days)) throw new Error("Invalid calendar date.");
  return new Date(Date.parse(value + "T00:00:00Z") + days * DAY).toISOString().slice(0, 10);
}
const midnightCache = new Map<string, number>();
/** First instant of a local date: accommodates 23/25-hour days and midnight offset changes. */
export function midnight(value: string, zone: string): number {
  if (!validDate(value)) throw new Error("Use a valid calendar date.");
  const key = zone + value;
  const cached = midnightCache.get(key);
  if (cached !== undefined) return cached;
  const guess = Date.parse(value + "T00:00:00Z");
  let lo = guess - 2 * DAY,
    hi = guess + 2 * DAY;
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (dateInZone(mid, zone) < value) lo = mid + 1;
    else hi = mid;
  }
  if (dateInZone(lo, zone) !== value)
    throw new Error("This date does not exist in the selected time zone.");
  if (midnightCache.size > 1000) midnightCache.clear();
  midnightCache.set(key, lo);
  return lo;
}
/** The browser's own time zone: the fallback where Home Assistant's is unknown. */
export const viewerTimeZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const clocks = new Map<string, Intl.DateTimeFormat>();
/** How far `zone`'s wall clock is ahead of UTC at `time`, in ms. */
function zoneOffset(time: number, zone: string): number {
  let clock = clocks.get(zone);
  if (!clock) {
    clock = new Intl.DateTimeFormat("en-CA", {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
    if (clocks.size > 20) clocks.clear();
    clocks.set(zone, clock);
  }
  const part: Record<string, number> = {};
  for (const { type, value } of clock.formatToParts(time)) part[type] = Number(value);
  const wall = Date.UTC(part.year, part.month - 1, part.day, part.hour, part.minute);
  return wall - Math.floor(time / 60_000) * 60_000;
}
/** The instant `zone`'s wall clock reads `minutes` past midnight on `value`, as the browser's
 * `new Date(y, m, d, 0, minutes)` reads its own zone: a time a clock change repeats is its first
 * occurrence, and one it skips is read on the clock before the change (02:30 becomes 03:30). */
export function wallTime(value: string, minutes: number, zone: string): number {
  const wall = Date.parse(value + "T00:00:00Z") + minutes * 60_000;
  const before = wall - zoneOffset(wall - DAY, zone);
  const after = wall - zoneOffset(wall + DAY, zone);
  const reads = (time: number) => time + zoneOffset(time, zone) === wall;
  const valid = [before, after].filter(reads);
  return valid.length ? Math.min(...valid) : before;
}
export function ageAt(time: number, runStart: string, zone: string): number {
  const day = dateInZone(time, zone);
  const start = midnight(day, zone),
    end = midnight(addDays(day, 1), zone);
  return daysBetween(runStart, day) + (time - start) / (end - start);
}
export function timeAtAge(age: number, runStart: string, zone: string): number {
  const whole = Math.floor(age),
    day = addDays(runStart, whole);
  const start = midnight(day, zone),
    end = midnight(addDays(day, 1), zone);
  return start + (age - whole) * (end - start);
}
export function boundedRange(startDate: string, endDate: string, zone: string, now: number) {
  if (
    !validDate(startDate) ||
    !validDate(endDate) ||
    daysBetween(startDate, endDate) < 0 ||
    daysBetween(startDate, endDate) > 365
  )
    throw new Error("Choose 1–366 inclusive calendar days.");
  const start = midnight(startDate, zone),
    end = Math.min(now, midnight(addDays(endDate, 1), zone));
  if (end <= start) throw new Error("This range has no elapsed time yet.");
  return { start, end };
}
export function comparisonRange(
  current: RunRecord,
  previous: RunRecord,
  start: number,
  end: number,
  now: number,
) {
  const firstAge = Math.max(0, ageAt(start, current.start_date, current.time_zone));
  const lastAge = Math.min(366, ageAt(end, current.start_date, current.time_zone));
  const previousEnd = previous.end_date
    ? midnight(addDays(previous.end_date, 1), previous.time_zone)
    : now;
  const from = timeAtAge(firstAge, previous.start_date, previous.time_zone);
  const to = Math.min(
    timeAtAge(lastAge, previous.start_date, previous.time_zone),
    previousEnd,
    now,
  );
  return to > from ? { start: from, end: to } : null;
}
/** Preserve explicit unavailable intervals and never connect readings >30 minutes apart. */
export function downsample(
  input: HistoryPoint[],
  maximum = 1600,
  gapMs = 30 * 60_000,
): HistoryPoint[] {
  const points = [
    ...new Map(
      input
        .filter((p) => Number.isFinite(p.time))
        .map((p) => [
          p.time,
          { time: p.time, value: p.value !== null && Number.isFinite(p.value) ? p.value : null },
        ]),
    ).values(),
  ].sort((a, b) => a.time - b.time);
  const gaps: HistoryPoint[] = [];
  for (const p of points) {
    const last = gaps.at(-1);
    if (last && p.time - last.time > gapMs) gaps.push({ time: last.time + 1, value: null });
    gaps.push(p);
  }
  if (gaps.length <= maximum) return gaps;
  const size = Math.ceil(gaps.length / Math.max(1, Math.floor(maximum / 4)));
  const out: HistoryPoint[] = [];
  for (let i = 0; i < gaps.length; i += size) {
    const group = gaps.slice(i, i + size);
    if (group.some((p) => p.value === null)) {
      out.push({ time: group[0].time, value: null }, { time: group.at(-1)!.time, value: null });
    } else {
      const min = group.reduce((a, b) => (a.value! < b.value! ? a : b)),
        max = group.reduce((a, b) => (a.value! > b.value! ? a : b));
      out.push(
        ...[...new Map([group[0], min, max, group.at(-1)!].map((p) => [p.time, p])).values()].sort(
          (a, b) => a.time - b.time,
        ),
      );
    }
  }
  return out;
}
export function summarize(points: HistoryPoint[], zone: string): DailyReading[] {
  const groups = new Map<string, DailyReading>();
  for (const point of points) {
    if (point.value === null || !Number.isFinite(point.value)) continue;
    const day = dateInZone(point.time, zone),
      row = groups.get(day);
    if (row) {
      row.records++;
      row.min = Math.min(row.min, point.value);
      row.max = Math.max(row.max, point.value);
    } else groups.set(day, { date: day, records: 1, min: point.value, max: point.value });
  }
  return [...groups.values()].sort((a, b) => a.date.localeCompare(b.date));
}
export function mergeDaily(rows: DailyReading[], monthly = false): DailyReading[] {
  const groups = new Map<string, DailyReading>();
  for (const value of rows) {
    const key = monthly ? value.date.slice(0, 7) : value.date,
      row = groups.get(key);
    if (row) {
      row.records += value.records;
      row.min = Math.min(row.min, value.min);
      row.max = Math.max(row.max, value.max);
    } else groups.set(key, { ...value, date: key });
  }
  return [...groups.values()].sort((a, b) => a.date.localeCompare(b.date));
}
/** Daily long-term statistics rows (`recorder/statistics_during_period`, period "day", types min
 * and max) as daily ranges. A day is named by the local date of its middle in `timeZone`, so a
 * server whose midnight is a few hours off still names the same day. A sensor Home Assistant keeps
 * no statistics for has no rows. */
export function dailyStatistics(result: unknown, timeZone: string): Record<string, DailyReading[]> {
  if (!result || typeof result !== "object")
    throw new Error("Home Assistant returned invalid statistics.");
  const instant = (value: unknown) =>
    typeof value === "number" ? value : typeof value === "string" ? Date.parse(value) : NaN;
  return Object.fromEntries(
    Object.entries(result as Record<string, unknown>).map(([id, rows]) => [
      id,
      mergeDaily(
        (Array.isArray(rows) ? rows : []).flatMap(
          (row: { start?: unknown; min?: unknown; max?: unknown } | null) => {
            const start = instant(row?.start);
            const { min, max } = row ?? {};
            return Number.isFinite(start) &&
              typeof min === "number" &&
              typeof max === "number" &&
              Number.isFinite(min) &&
              Number.isFinite(max)
              ? [{ date: dateInZone(start + DAY / 2, timeZone), records: 1, min, max }]
              : [];
          },
        ),
      ),
    ]),
  );
}

/** The smallest gap each Compare runs chart speaks about: VWC points, dryback points, mS/cm and
 * litres per plant a day. A smaller gap is noise between grows, so the chart says nothing. */
export const CALLOUT_FLOOR = { vwc: 0.5, dryback: 0.5, pore_ec: 0.2, water: 0.02 } as const;
export type CalloutMetric = keyof typeof CALLOUT_FLOOR;
/** Fewer days than this in common is not a comparison. */
const CALLOUT_MIN_DAYS = 3;

/** "flower setting (stretch)" reads "stretch", "flower bulk" reads "bulk". */
export const stageWord = (name: string) =>
  /\(([^)]+)\)/.exec(name)?.[1] ?? name.replace(/^flower /i, "");
/** Decimals of the readings themselves (at most 3): a gap is never shown finer than its source. */
function sourceDigits(values: number[]) {
  return Math.min(3, Math.max(0, ...values.map((v) => (String(v).split(".")[1] ?? "").length)));
}
const average = (values: number[]) => values.reduce((a, b) => a + b, 0) / values.length;

/** One callout for a Compare runs chart: the biggest gap, stage by stage, between the reference run
 * (this run, else the first) and each other run, over the grow days both have. Null when no gap
 * reaches the metric's floor. The box is the days the gap was measured over. */
export function runCallout(
  metric: CalloutMetric,
  runs: ComparedRun[],
  stages: Stage[],
): { text: string; box: { fromDay: number; toDay: number } } | null {
  const reference = runs.find((r) => r.current) ?? runs[0];
  if (!reference) return null;
  const refDays = new Map((reference.days[metric] ?? []).map((d) => [d.day, d.value]));
  let best: {
    run: ComparedRun;
    delta: number;
    share: number | null;
    from: number;
    to: number;
    days: number;
    digits: number;
  } | null = null;
  for (const run of runs) {
    if (run === reference) continue;
    for (const stage of stages) {
      const common = (run.days[metric] ?? []).filter(
        (d) => d.day >= stage.first && d.day <= stage.last && refDays.has(d.day),
      );
      if (common.length < CALLOUT_MIN_DAYS) continue;
      const theirs = common.map((d) => d.value),
        ours = common.map((d) => refDays.get(d.day)!);
      const delta = average(theirs) - average(ours),
        base = average(ours);
      if (Math.abs(delta) + 1e-9 < CALLOUT_FLOOR[metric]) continue;
      if (best && Math.abs(delta) <= Math.abs(best.delta)) continue;
      const days = common.map((d) => d.day);
      best = {
        run,
        delta,
        share: base > 0 ? Math.abs(delta) / base : null,
        from: Math.min(...days),
        to: Math.max(...days),
        days: days.length,
        digits: Math.max(
          run.digits?.[metric] ?? sourceDigits(theirs),
          reference.digits?.[metric] ?? sourceDigits(ours),
        ),
      };
    }
  }
  if (!best) return null;
  const { run, delta, share, from, to, days, digits } = best;
  const ref = reference.current ? "this run" : reference.name;
  const Ref = reference.current ? "This run" : reference.name;
  // Run days, not stage names: no flip date is recorded, so a stage on run days would be a guess.
  const span = days === to - from + 1 ? `on run days ${from}–${to}` : `on ${days} of run days ${from}–${to}`;
  const size = Math.abs(delta).toFixed(digits);
  const pts = size === "1" ? "pt" : "pts";
  // The reference run's side of the gap, for the sentences it is the subject of.
  const ourDelta = -delta;
  const text =
    metric === "vwc"
      ? `${run.name} sat ${size} ${pts} ${delta > 0 ? "wetter" : "drier"} than ${ref} ${span}.`
      : metric === "dryback"
        ? `${Ref} dries back ${size} ${pts} ${ourDelta > 0 ? "more" : "less"} than ${run.name} ${span}.`
        : metric === "pore_ec"
          ? `${Ref} is ${formatEc(Math.abs(delta), digits)} ${ourDelta > 0 ? "higher" : "lower"} than ${run.name} ${span}.`
          : `${run.name} gave ${formatVolume(Math.abs(delta), digits)}${
              share === null ? "" : ` (${Math.round(share * 100)}%)`
            } ${delta > 0 ? "more" : "less"} water a plant a day than ${ref} ${span}.`;
  return { text, box: { fromDay: from, toDay: to } };
}

/** A run's whole-room daily values from the room's grow-day summaries (crop_steering.grow_days_get):
 * each grow day's zones averaged, a missing reading left out (never zero). */
export function comparedRun(run: RunRecord, growDays: GrowDay[], current: boolean): ComparedRun {
  const pick: Record<CalloutMetric, (d: GrowDay) => number | null | undefined> = {
    vwc: (d) => d.vwc?.mean,
    dryback: (d) => d.p0?.drop_pts,
    pore_ec: (d) => d.ec?.mean,
    water: (d) => d.litres_per_plant,
  };
  const inRun = growDays.filter(
    (d) => d.date >= run.start_date && (!run.end_date || d.date <= run.end_date),
  );
  const dates = [...new Set(inRun.map((d) => d.date))].sort();
  const days: ComparedRun["days"] = {};
  const digits: NonNullable<ComparedRun["digits"]> = {};
  for (const metric of Object.keys(pick) as CalloutMetric[]) {
    const out: { day: number; value: number }[] = [];
    const raw: number[] = [];
    for (const date of dates) {
      const values = inRun
        .filter((d) => d.date === date)
        .map(pick[metric])
        .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
      raw.push(...values);
      if (values.length) out.push({ day: daysBetween(run.start_date, date) + 1, value: average(values) });
    }
    if (out.length) {
      days[metric] = out;
      digits[metric] = sourceDigits(raw);
    }
  }
  return { id: run.id, name: run.name, current, days, digits };
}

/** A calendar date ("2026-08-10") as "Mon 10 Aug". */
export const dateLabel = (date: string) => dayLabel(Date.parse(date + "T12:00:00Z"), "UTC");
/** A weight in grams as kg, to the gram and no finer: 38400 reads "38.4 kg". */
export const kgText = (grams: number) => `${Number((grams / 1000).toFixed(3))} kg`;
/** A dry weight typed in kg, as grams: a decimal point or comma, to the gram. Null for anything
 * else, including "1,234", which could be a thousands comma. */
export function parseDryKg(text: string): number | null {
  const t = text.trim();
  if (!/^\d+([.,]\d{1,3})?$/.test(t) || /^\d{1,3},\d{3}$/.test(t)) return null;
  return Math.round(Number(t.replace(",", ".")) * 1000);
}

/** What a run's card says it ended with: its harvest as recorded (dry weight in kg and g/m² only
 * where entered), else that none is; a run in progress, its planned harvest date if the plan has one.
 * `missing` asks for the Add harvest result button. */
export function runResult(
  run: RunRecord,
  harvest: Harvest | undefined,
  harvestDue: string | null,
): { text: string; missing: boolean } {
  if (!harvest && !run.end_date)
    return {
      text: harvestDue ? `Growing · harvest due ${dateLabel(harvestDue)}` : "Growing · no harvest date planned",
      missing: false,
    };
  if (!harvest) return { text: "No harvest result recorded", missing: true };
  const figures = yieldFigures(harvest, run, "room", null);
  const parts = [
    harvest.harvest_date
      ? `Harvested ${dateLabel(harvest.harvest_date)}`
      : run.end_date
        ? `Ended ${dateLabel(run.end_date)}`
        : "Harvested",
  ];
  if (figures.dryG !== null) parts.push(`${kgText(figures.dryG)} dry`);
  if (figures.gramsPerM2 !== null) parts.push(`${Math.round(figures.gramsPerM2)} g/m²`);
  return { text: parts.join(" · "), missing: false };
}

/** The harvest result Compare runs saves: the dry weight the grower entered and nothing else, so no
 * harvest date is stored that was never entered or reviewed. */
export function harvestResult(dryG: number): Harvest {
  return {
    harvest_date: null,
    room: { dry_weight_g: dryG, wet_weight_g: null, plants_harvested: null, canopy_m2: null },
    zones: {},
    plants: [],
    quality: null,
    notes: null,
    lab: { thc_pct: null, terpenes: {} },
  };
}
/** An undo of a harvest result counts only when the harvests the service answered with no longer
 * hold that run. */
export function harvestCleared(answer: HarvestsDocument, runId: string): void {
  if (answer.harvests[runId] != null)
    throw new Error("The harvest result is still stored. Reload and check before trying again.");
}
