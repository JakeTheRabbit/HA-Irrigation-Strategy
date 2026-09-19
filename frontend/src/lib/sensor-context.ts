import { addDays, downsample, midnight, summarize } from "./comparison";
import type { HistoryPoint } from "./comparison-types";
import type { Series } from "./types";

/** Recorded probe behaviour beside the setpoints an operator types.
 * Everything here is pure: the component only draws what these functions return. */
export type SensorMetric = "vwc" | "ec";
export const SENSOR_WINDOWS = [24, 72, 168] as const;
export type SensorWindow = (typeof SENSOR_WINDOWS)[number];
export const DEFAULT_SENSOR_WINDOW: SensorWindow = 72;
export const windowLabel = (hours: number) =>
  hours % 24 === 0 && hours > 72 ? `${hours / 24} d` : `${hours} h`;

export interface SensorReading {
  value: number;
  time: number;
}
export interface SensorStats {
  /** Null when the live reading is stale or unavailable: never present it as "now". */
  current: SensorReading | null;
  /** Newest reading in the window, shown as "last recorded" beside a stale Now. */
  last: SensorReading;
  peak: SensorReading;
  trough: SensorReading;
  typicalDailyPeak: number | null;
  typicalDailyTrough: number | null;
  /** Local days behind the typical values. */
  days: number;
}
export interface WindowOptions {
  hours: number;
  now: number;
  timeZone: string;
  /** Freshness-gated live reading: a number is current, null is stale, undefined is "not supplied". */
  live?: number | null;
}

export function windowPoints(
  series: Pick<Series, "points"> | undefined,
  { hours, now, live }: WindowOptions,
): SensorReading[] {
  const start = now - hours * 3_600_000;
  const points = (series?.points ?? [])
    .map((point) => ({ value: point.value, time: Date.parse(point.time) }))
    .filter(
      (point) =>
        Number.isFinite(point.value) &&
        Number.isFinite(point.time) &&
        point.time >= start &&
        point.time <= now,
    )
    .sort((a, b) => a.time - b.time);
  // Recorder history trails the live state; a fresh reading completes the line up to "now".
  if (points.length && typeof live === "number" && Number.isFinite(live))
    points.push({ value: live, time: now });
  return points;
}
const median = (values: number[]): number | null => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};
export function sensorStats(
  series: Pick<Series, "points"> | undefined,
  options: WindowOptions,
): SensorStats | null {
  const points = windowPoints(series, options);
  if (!points.length) return null;
  const { hours, now, timeZone, live } = options;
  const start = now - hours * 3_600_000;
  // ">=" and "<=" resolve equal extremes to the most recent reading.
  const peak = points.reduce((best, point) => (point.value >= best.value ? point : best));
  const trough = points.reduce((best, point) => (point.value <= best.value ? point : best));
  const daily = summarize(points, timeZone);
  const fullDays = daily.filter(
    (day) =>
      midnight(day.date, timeZone) >= start && midnight(addDays(day.date, 1), timeZone) <= now,
  );
  // A rolling window opens part-way through its first day, whose extremes are usually cut off.
  const partialFirst = midnight(daily[0].date, timeZone) < start;
  const used = partialFirst && fullDays.length >= 2 ? daily.slice(1) : daily;
  return {
    current: live === null ? null : points.at(-1)!,
    last: windowPoints(series, { ...options, live: undefined }).at(-1)!,
    peak,
    trough,
    typicalDailyPeak: median(used.map((day) => day.max)),
    typicalDailyTrough: median(used.map((day) => day.min)),
    days: used.length,
  };
}

const VWC_KEYS = [
  "field_capacity",
  "p1_target_vwc",
  "p2_vwc_threshold",
  "p3_emergency_vwc_threshold",
] as const;
const EC_KEYS = ["maximum_ec", "ec_target_p0", "ec_target_p1", "ec_target_p2"] as const;
const DRYBACK = /^(?:vegetative_|generative_)?dryback_target$/;
const EC_TARGET = /^ec_target_(?:(?:veg|gen)_)?p[012]$/;
/** Shot sizes, timings, counts, volumes and feed limits say nothing about a probe reading. */
export function setpointMetric(param: string): SensorMetric | null {
  if ((VWC_KEYS as readonly string[]).includes(param) || DRYBACK.test(param)) return "vwc";
  if (param === "maximum_ec" || EC_TARGET.test(param)) return "ec";
  return null;
}
/** Parameter name of a zone or room number entity in exactly this room. */
export function setpointParam(entityId: string, prefix: string): string | null {
  const root = `number.crop_steering_${prefix}`;
  if (!entityId.startsWith(root)) return null;
  const key = entityId.slice(root.length);
  // A default-room prefix ("") also matches other rooms' ids ("f1_p1_target_vwc"); those
  // simply map to no metric.
  return key.replace(/^zone_\d+_/, "") || null;
}

export interface ReferenceLine {
  key: string;
  label: string;
  /** Compact label for phone-width charts. */
  short: string;
  metric: SensorMetric;
  /** Draft (effective) value; null while the typed draft is invalid. */
  value: number | null;
  /** Saved controller value, only when it differs from the draft. */
  saved: number | null;
  kind: "setpoint" | "derived" | "learned";
}
const LINE_LABELS: Record<string, [string, string]> = {
  field_capacity: ["Field capacity", "FC"],
  p1_target_vwc: ["P1 target", "P1"],
  p2_vwc_threshold: ["P2 threshold", "P2"],
  p3_emergency_vwc_threshold: ["P3 floor", "P3"],
  maximum_ec: ["Max EC", "Max"],
  ec_target_p0: ["P0 target", "P0"],
  ec_target_p1: ["P1 target", "P1"],
  ec_target_p2: ["P2 target", "P2"],
};
const usable = (value: number | undefined): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const differs = (a: number | null, b: number | null) =>
  b !== null && (a === null || Math.abs(a - b) > 1e-9);
/** Canonical planning parameters (mode already resolved) to horizontal chart lines. */
export function referenceLines({
  draft,
  saved,
  typicalDailyPeak,
  learnedPeak,
}: {
  draft: Record<string, number>;
  saved?: Record<string, number>;
  typicalDailyPeak: number | null;
  learnedPeak?: number | null;
}): ReferenceLine[] {
  const lines: ReferenceLine[] = [];
  for (const [metric, keys] of [
    ["vwc", VWC_KEYS],
    ["ec", EC_KEYS],
  ] as const)
    for (const key of keys) {
      const value = usable(draft[key]),
        before = usable(saved?.[key]);
      if (value === null && before === null) continue;
      lines.push({
        key,
        label: LINE_LABELS[key][0],
        short: LINE_LABELS[key][1],
        metric,
        value,
        saved: differs(value, before) ? before : null,
        kind: "setpoint",
      });
    }
  const floor = (parameters: Record<string, number> | undefined) => {
    const dryback = usable(parameters?.dryback_target);
    return typicalDailyPeak === null || dryback === null
      ? null
      : typicalDailyPeak * (1 - dryback / 100);
  };
  const draftFloor = floor(draft),
    savedFloor = floor(saved);
  if (draftFloor !== null || savedFloor !== null)
    lines.push({
      key: "dryback_floor",
      label: "Dryback floor",
      short: "Dryback",
      metric: "vwc",
      value: draftFloor,
      saved: differs(draftFloor, savedFloor) ? savedFloor : null,
      kind: "derived",
    });
  if (typeof learnedPeak === "number" && Number.isFinite(learnedPeak))
    lines.push({
      key: "learned_peak",
      label: "Learned peak",
      short: "Learned",
      metric: "vwc",
      value: learnedPeak,
      saved: null,
      kind: "learned",
    });
  // Line order is top-to-bottom reading order for the VWC setpoints; EC keeps phase order.
  return [
    ...lines.filter((line) => line.metric === "vwc"),
    ...lines.filter((line) => line.metric === "ec"),
  ];
}

export function formatReading(value: number, metric: SensorMetric, unit = true): string {
  return metric === "vwc"
    ? `${value.toFixed(1)}${unit ? "%" : ""}`
    : `${value.toFixed(2)}${unit ? " mS/cm" : ""}`;
}
/** Advisory margins: VWC in percentage points, pore EC in mS/cm. */
const MARGIN: Record<SensorMetric, number> = { vwc: 1.5, ec: 0.5 };
export interface FieldHint {
  text: string;
  /** Gentle, advisory only. Saving is never blocked by it. */
  warning: string | null;
}
/** `stats` must belong to the metric returned by setpointMetric(param). */
export function fieldHint(
  param: string,
  value: number | null,
  stats: SensorStats | null,
  hours: number,
): FieldHint | null {
  const metric = setpointMetric(param);
  if (!metric || !stats) return null;
  const show = (reading: number) => formatReading(reading, metric);
  const span = windowLabel(hours);
  const typed = value !== null && Number.isFinite(value) ? value : null;
  if (DRYBACK.test(param)) {
    if (stats.typicalDailyPeak === null) return null;
    const floor = typed === null ? null : stats.typicalDailyPeak * (1 - typed / 100);
    return {
      text: `Typical peak ${show(stats.typicalDailyPeak)} → dryback floor ${floor === null ? "—" : show(floor)} · ${span} trough ${show(stats.trough.value)}`,
      warning:
        floor !== null && floor < stats.trough.value - MARGIN.vwc
          ? `dryback floor ${show(floor)} is below anything this probe has read in ${span} (trough ${show(stats.trough.value)})`
          : null,
    };
  }
  const range = `${formatReading(stats.trough.value, metric, false)}–${show(stats.peak.value)}`;
  const text = [
    stats.current
      ? `Now ${show(stats.current.value)}`
      : `Now stale (last recorded ${show(stats.last.value)})`,
    `${span} range ${range}`,
    ...(stats.typicalDailyPeak === null ? [] : [`typical peak ${show(stats.typicalDailyPeak)}`]),
  ].join(" · ");
  const above = `above anything this probe has read in ${span} (peak ${show(stats.peak.value)})`;
  const below = `below anything this probe has read in ${span} (trough ${show(stats.trough.value)})`;
  const tooHigh = typed !== null && typed > stats.peak.value + MARGIN[metric];
  const tooLow = typed !== null && typed < stats.trough.value - MARGIN[metric];
  let warning: string | null = null;
  if (param === "p1_target_vwc" || param === "field_capacity") warning = tooHigh ? above : null;
  else if (param === "p3_emergency_vwc_threshold")
    warning = tooHigh
      ? above
      : typed !== null && typed > stats.trough.value
        ? `this probe read below this floor in ${span} (trough ${show(stats.trough.value)}), so emergency shots would have fired`
        : null;
  else if (param === "maximum_ec")
    warning =
      typed !== null && typed < stats.peak.value
        ? `this probe read above this limit in ${span} (peak ${show(stats.peak.value)})`
        : null;
  else warning = tooHigh ? above : tooLow ? below : null;
  return { text, warning };
}

/** Value axis over readings AND setpoints, so a distant target is visibly distant. */
export function valueScale(values: number[]): { min: number; max: number; ticks: number[] } {
  const finite = values.filter((value) => Number.isFinite(value));
  let low = finite.length ? Math.min(...finite) : 0,
    high = finite.length ? Math.max(...finite) : 1;
  if (high - low < 1e-9) {
    const pad = Math.max(Math.abs(high) * 0.1, 0.5);
    low -= pad;
    high += pad;
  }
  const pad = (high - low) * 0.08;
  low = Math.max(0, low - pad);
  high += pad;
  const rough = (high - low) / 5;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? 10 * power;
  const clean = (value: number) => Number(value.toPrecision(12));
  const min = clean(Math.max(0, Math.floor(low / step) * step)),
    max = clean(Math.ceil(high / step) * step);
  const ticks: number[] = [];
  for (let tick = min; tick <= max + step / 1e6; tick += step) ticks.push(clean(tick));
  return { min, max, ticks };
}
/** Every setpoint shares the value axis with the readings, with one exception: the Max EC
 * safety limit normally sits several times above anything the probe reads and would crush
 * the EC trace into a sliver. It joins the axis only while it is within one span of
 * everything else; beyond that the chart pins it to the top edge, labelled with its value. */
export function chartScale(readings: number[], lines: ReferenceLine[]) {
  const values = (items: ReferenceLine[]) =>
    items.flatMap((line) => [line.value, line.saved].filter((v): v is number => v !== null));
  const core = [...readings, ...values(lines.filter((line) => line.key !== "maximum_ec"))];
  const low = Math.min(...core),
    high = Math.max(...core);
  const span = Math.max(high - low, 1e-9);
  const near = values(lines.filter((line) => line.key === "maximum_ec")).filter(
    (value) => !core.length || (value <= high + span && value >= low - span),
  );
  const scale = valueScale([...core, ...near]);
  return { scale, offScale: (value: number) => value > scale.max || value < scale.min };
}
/** Pushes crowded labels apart, preserving input order, inside [top, bottom]. */
export function spreadLabels(
  positions: number[],
  minGap: number,
  top: number,
  bottom: number,
): number[] {
  const order = positions.map((y, index) => ({ y, index })).sort((a, b) => a.y - b.y);
  const placed = order.map((item) => Math.min(bottom, Math.max(top, item.y)));
  for (let i = 1; i < placed.length; i++) placed[i] = Math.max(placed[i], placed[i - 1] + minGap);
  if (placed.length && placed.at(-1)! > bottom) {
    placed[placed.length - 1] = bottom;
    for (let i = placed.length - 2; i >= 0; i--)
      placed[i] = Math.min(placed[i], placed[i + 1] - minGap);
  }
  const result: number[] = [];
  order.forEach((item, i) => (result[item.index] = placed[i]));
  return result;
}
/** Local-time axis ticks: clock times for a day, dates for longer windows. */
export function timeTicks(
  start: number,
  end: number,
  hours: number,
): { time: number; label: string }[] {
  const stepHours = hours <= 24 ? 6 : 24;
  const first = new Date(start);
  first.setMinutes(0, 0, 0);
  first.setHours(hours <= 24 ? Math.ceil(first.getHours() / stepHours) * stepHours : 0);
  const ticks: { time: number; label: string }[] = [];
  // Calendar stepping keeps date ticks on local midnight across daylight-saving changes.
  for (let at = first; at.getTime() <= end && ticks.length < 8;) {
    if (at.getTime() >= start)
      ticks.push({
        time: at.getTime(),
        label:
          hours <= 24
            ? at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
            : at.toLocaleDateString([], { weekday: "short", day: "numeric" }),
      });
    at = new Date(at);
    if (hours <= 24) at.setHours(at.getHours() + stepHours);
    else at.setDate(at.getDate() + 1);
  }
  return ticks;
}

/** Recorder rows are state changes, so quiet spells are normal; only a long silence is a gap. */
const GAP_MS = 2 * 3_600_000;
/** Chart-sized line: extremes survive thinning and a null breaks the line at each gap. */
export function plotPoints(points: SensorReading[], maximum = 800): HistoryPoint[] {
  return downsample(points, maximum, GAP_MS);
}
/** Index of the reading closest in time, for the hover crosshair; -1 without readings. */
export function nearestReading(points: readonly { time: number }[], time: number): number {
  if (!points.length) return -1;
  let low = 0,
    high = points.length - 1;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (points[middle].time < time) low = middle + 1;
    else high = middle;
  }
  return low > 0 && time - points[low - 1].time <= points[low].time - time ? low - 1 : low;
}

export type LoadResult<T> = { ok: true; value: T } | { ok: false; error: unknown };
/** Race guard: of overlapping loads (zone or window changed, 60 s refresh), only the
 * most recently started one may deliver; cancel() silences everything in flight. */
export function latestOnly<T>() {
  let token = 0;
  return {
    run(load: () => Promise<T>, deliver: (result: LoadResult<T>) => void) {
      const mine = ++token;
      load().then(
        (value) => {
          if (mine === token) deliver({ ok: true, value });
        },
        (error: unknown) => {
          if (mine === token) deliver({ ok: false, error });
        },
      );
    },
    cancel() {
      token++;
    },
  };
}
