import type { DailyReading, HistoryPoint, RunRecord } from "./comparison-types";
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
export const daysBetween = (start: string, end: string) =>
  (Date.parse(end + "T00:00:00Z") - Date.parse(start + "T00:00:00Z")) / DAY;
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
