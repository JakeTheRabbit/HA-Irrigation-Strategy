import type { PhaseBand, Reading } from "./day-timeline";

/** Pure helpers for the grow-day chart, drawn in the language of Athena's irrigation phase reference
 * chart: a light band on top, phase columns with P0-P3 badges, field capacity with the steering's runoff
 * zone, water content as one line with its shots on it, and pore EC as a second line in the steering's
 * colour. */

export type Steering = "vegetative" | "generative";

/** A zone's steering: its own steering select, else the stage's (the finish ripens generatively: its
 * peak sits at or below field capacity). Null when neither says. */
export function steeringOf(
  select: string | null | undefined,
  stage: string | null | undefined,
): Steering | null {
  for (const value of [select, stage]) {
    const word = (value ?? "").trim().toLowerCase();
    if (word.startsWith("veg")) return "vegetative";
    if (word.startsWith("gen") || word === "ripening") return "generative";
  }
  return null;
}

/** Athena's relative overnight dryback for the stage the controller names, % of the peak (Athena Pro
 * handbook, Irrigation Strategy Targets): stretch 40-50, bulk 30-40, finish 40-50, veg 25 after the
 * first. Null for a stage it does not name. */
export function athenaDryback(stage: string | null | undefined): [number, number] | null {
  const name = (stage ?? "").toLowerCase();
  if (/setting|stretch/.test(name)) return [40, 50];
  if (/bulk/.test(name)) return [30, 40];
  if (/finish|ripen/.test(name)) return [40, 50];
  if (/veg/.test(name)) return [25, 25];
  return null;
}

/** "3.5–6", "25". */
export function rangeText([low, high]: readonly [number, number], digits = 1): string {
  const show = (value: number) =>
    value.toLocaleString(undefined, { maximumFractionDigits: digits });
  return low === high ? show(low) : `${show(low)}–${show(high)}`;
}

/** Where a reading sits against a band. */
export function bandStatus(
  value: number | null,
  band: readonly [number, number] | null,
): "below" | "in" | "above" | null {
  if (value === null || !Number.isFinite(value) || !band) return null;
  return value < band[0] ? "below" : value > band[1] ? "above" : "in";
}

export interface Axis {
  min: number;
  max: number;
  step: number;
  ticks: number[];
}
export interface AxisOptions {
  /** Room left beyond the outermost value, in the axis's units. */
  pad: number;
  /** A reference (a target, field capacity, a band edge) this far beyond the data widens the axis; one
   * further off is left off the axis, so a far target never flattens the line. */
  reach: number;
  /** The narrowest axis, so a flat day is not drawn as a jagged one. */
  minSpan: number;
  /** Gridline steps to choose from, finest first. */
  steps: readonly number[];
  floor?: number;
  ceiling?: number;
  /** At most this many gridlines. */
  maxTicks?: number;
}
export const VWC_AXIS: AxisOptions = {
  pad: 2,
  reach: 12,
  minSpan: 8,
  steps: [1, 2, 5, 10, 20],
  floor: 0,
  ceiling: 100,
};
export const EC_AXIS: AxisOptions = {
  pad: 0.4,
  reach: 4,
  minSpan: 1.5,
  steps: [0.5, 1, 2, 5],
  floor: 0,
};

/** An axis tight to the data and the references near it, with round gridlines inside it. Null when
 * there is nothing to draw. */
export function axisRange(
  values: readonly number[],
  references: readonly (number | null | undefined)[],
  options: AxisOptions,
): Axis | null {
  const data = values.filter(Number.isFinite);
  const refs = references.filter(
    (value): value is number => typeof value === "number" && Number.isFinite(value),
  );
  if (!data.length && !refs.length) return null;
  const base = data.length ? data : refs;
  let low = Math.min(...base),
    high = Math.max(...base);
  for (const value of refs)
    if (value >= low - options.reach && value <= high + options.reach) {
      low = Math.min(low, value);
      high = Math.max(high, value);
    }
  let min = low - options.pad,
    max = high + options.pad;
  if (max - min < options.minSpan) {
    const middle = (min + max) / 2;
    min = middle - options.minSpan / 2;
    max = middle + options.minSpan / 2;
  }
  if (options.floor !== undefined && min < options.floor) {
    max += options.floor - min;
    min = options.floor;
  }
  if (options.ceiling !== undefined && max > options.ceiling) {
    min = Math.max(options.floor ?? -Infinity, min - (max - options.ceiling));
    max = options.ceiling;
  }
  const most = options.maxTicks ?? 5;
  const count = (step: number) => Math.floor(max / step) - Math.ceil(min / step) + 1;
  const step =
    options.steps.find((item) => count(item) <= most) ?? options.steps[options.steps.length - 1];
  const ticks: number[] = [];
  for (let tick = Math.ceil(min / step) * step; tick <= max + 1e-9; tick += step)
    ticks.push(Math.round(tick * 1000) / 1000);
  return { min, max, step, ticks };
}

/** A zone's day on its two axes. VWC fits today's readings, today's projected rest of the day and
 * the zone's own targets near them (field capacity, the maintenance band's edges, the rescue floor
 * overnight): an earlier day drawn for comparison is clipped to that scale and never widens it, so
 * yesterday's spike cannot squash today's line. Pore EC fits today's readings and the stage's band. */
export function dayScales(input: {
  today: readonly number[];
  projection?: readonly number[];
  targets: readonly (number | null | undefined)[];
  ec: readonly number[];
  ecBand: readonly [number, number] | null;
}): { vwc: Axis | null; ec: Axis | null } {
  return {
    vwc: axisRange([...input.today, ...(input.projection ?? [])], input.targets, VWC_AXIS),
    ec: axisRange(input.ec, input.ecBand ?? [], EC_AXIS),
  };
}

/** Points of VWC the runoff zone spans beside field capacity. */
export const RUNOFF_POINTS = 3;
/** The runoff zone drawn with field capacity, as a thin band: just above it while steering
 * vegetative (a shot past field capacity runs off), just under it while generative (Athena's
 * generative runoff starts a little below). */
export function runoffBand(fc: number, steering: Steering): [number, number] {
  return steering === "vegetative" ? [fc, fc + RUNOFF_POINTS] : [fc - RUNOFF_POINTS, fc];
}

export interface Marker<T> {
  x: number;
  /** 0 on the plot's top edge, then one row down for each marker it would have touched. */
  row: number;
  /** One item, or several that fell on the same spot. */
  items: T[];
}
/** Markers along one edge, left to right, each on the first row where it clears the one before by
 * `gap` pixels. Beyond `rows` rows a marker joins the nearest one already placed. */
export function placeMarkers<T>(
  items: readonly { x: number; item: T }[],
  gap: number,
  rows = 2,
): Marker<T>[] {
  const placed: Marker<T>[] = [];
  const last: (Marker<T> | undefined)[] = Array.from({ length: rows });
  for (const { x, item } of [...items].sort((a, b) => a.x - b.x)) {
    const row = last.findIndex((marker) => !marker || x - marker.x >= gap);
    if (row >= 0) {
      const marker = { x, row, items: [item] };
      placed.push(marker);
      last[row] = marker;
      continue;
    }
    const nearest = last.reduce((best, marker) =>
      marker && best && Math.abs(marker.x - x) < Math.abs(best.x - x) ? marker : best,
    )!;
    nearest.items.push(item);
  }
  return placed;
}

/** Badge centres along one row, each as near its own `centres` entry as the row allows: pushed right
 * just enough to clear the badge before it, then back left where the row runs out. A narrow phase
 * keeps its badge beside it instead of losing it. */
export function placeBadges(
  centres: readonly number[],
  size: number,
  gap: number,
  start: number,
  end: number,
): number[] {
  const step = size + gap;
  const placed = centres.map((centre) => Math.max(centre, start + size / 2));
  for (let i = 1; i < placed.length; i++) placed[i] = Math.max(placed[i], placed[i - 1] + step);
  for (let i = placed.length - 1; i >= 0; i--)
    placed[i] = Math.min(
      placed[i],
      i === placed.length - 1 ? end - size / 2 : placed[i + 1] - step,
    );
  return placed;
}

export interface Dryback {
  /** The evening peak: the highest reading in the last hours before lights-off. */
  peak: number;
  /** The lowest reading since lights-off. */
  low: number;
  /** (peak − low) / peak × 100, the relative dryback Athena's targets use. */
  percent: number;
  /** In points of the probe. */
  drop: number;
  /** The night is over: lights came back on. */
  complete: boolean;
}
/** How far a zone dried back overnight, relative to its evening peak, as Athena measures P3: from the
 * highest reading in the `window` before lights-off to the lowest reading after it, up to `now` (so far)
 * or the next lights-on (`end`). Null without readings on both sides of lights-off. */
export function overnightDryback(
  points: readonly Reading[],
  lightsOff: number,
  end: number,
  now: number,
  window = 2 * 3_600_000,
): Dryback | null {
  let peak = -Infinity,
    low = Infinity;
  const until = Math.min(end, now);
  for (const point of points) {
    if (point.time >= lightsOff - window && point.time <= lightsOff)
      peak = Math.max(peak, point.value);
    else if (point.time > lightsOff && point.time <= until) low = Math.min(low, point.value);
  }
  if (!Number.isFinite(peak) || !Number.isFinite(low) || peak <= 0) return null;
  const drop = Math.max(0, peak - low);
  return { peak, low, drop, percent: (drop / peak) * 100, complete: now >= end };
}

export interface Column {
  phase: string;
  start: number;
  end: number;
  /** Not reached yet: only expected. */
  future: boolean;
}
/** The day's phases as chart columns: what was recorded up to `now`, then what is expected. Equal
 * neighbours join; a sliver narrower than `minMs` (the minute of P3 a day starts with) joins the
 * column after it, so no divider sits on top of another. A stretch no phase was recorded for stays a
 * gap. */
export function phaseColumns(
  recorded: readonly PhaseBand[],
  ahead: readonly PhaseBand[],
  now: number,
  minMs: number,
): Column[] {
  const parts: Column[] = [
    ...recorded
      .map((band) => ({ ...band, end: Math.min(band.end, now), future: false }))
      .filter((band) => band.end > band.start),
    ...ahead
      .map((band) => ({ ...band, start: Math.max(band.start, now), future: true }))
      .filter((band) => band.end > band.start),
  ];
  const columns: Column[] = [];
  for (const part of parts) {
    const last = columns.at(-1);
    if (last && last.phase === part.phase && part.start - last.end < 60_000) {
      last.end = Math.max(last.end, part.end);
      last.future &&= part.future;
    } else columns.push({ ...part });
  }
  for (let index = 0; index < columns.length; index++) {
    const column = columns[index],
      next = columns[index + 1];
    if (column.end - column.start >= minMs) continue;
    if (next && next.start - column.end < 60_000) {
      next.start = column.start;
      columns.splice(index--, 1);
    } else if (index > 0 && column.start - columns[index - 1].end < 60_000) {
      columns[index - 1].end = column.end;
      columns.splice(index--, 1);
    }
  }
  return columns;
}

/** Clock ticks every few hours from the day's start, as far apart as a label needs. */
export function hourTicks(start: number, end: number, width: number, label: number): number[] {
  const hours = (end - start) / 3_600_000;
  const step = [1, 2, 3, 4, 6, 8, 12].find((each) => (width * each) / hours >= label) ?? 12;
  const ticks: number[] = [];
  for (let time = start; time <= end - step * 1_800_000; time += step * 3_600_000) ticks.push(time);
  return ticks;
}

/** A smooth line through the readings (a Catmull-Rom spline as cubic Béziers), broken where they stop
 * for longer than `gapMs`. */
export function smoothPath(
  points: readonly Reading[],
  x: (time: number) => number,
  y: (value: number) => number,
  gapMs = 40 * 60_000,
): string {
  const runs: Reading[][] = [];
  points.forEach((point, index) => {
    if (index && point.time - points[index - 1].time <= gapMs) runs.at(-1)!.push(point);
    else runs.push([point]);
  });
  const f = (value: number) => value.toFixed(1);
  return runs
    .map((run) => {
      const xy = run.map((point) => [x(point.time), y(point.value)] as const);
      let d = `M${f(xy[0][0])} ${f(xy[0][1])}`;
      for (let i = 1; i < xy.length; i++) {
        const p0 = xy[Math.max(0, i - 2)],
          p1 = xy[i - 1],
          p2 = xy[i],
          p3 = xy[Math.min(xy.length - 1, i + 1)];
        const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
        const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
        d += `C${f(c1[0])} ${f(c1[1])} ${f(c2[0])} ${f(c2[1])} ${f(p2[0])} ${f(p2[1])}`;
      }
      return d;
    })
    .join("");
}

/** What the chart compares today with. */
export type Compare = "yesterday" | "typical" | "none";
/** The chart's layers, one per entry in its key, each of which can be switched off. */
export const CHART_LAYERS = [
  "vwc",
  "ec",
  "shots",
  "fc",
  "band",
  "rescue",
  "jev",
  "compare",
] as const;
export type ChartLayer = (typeof CHART_LAYERS)[number];
/** Where a reading of the chart shows: in a line under it, or floating over it by the pointer. */
export type Readout = "below" | "over";
export interface ChartPrefs {
  compare: Compare;
  hidden: ChartLayer[];
  readout: Readout;
}
/** The chart's choices as remembered in a browser, from what was stored (anything unreadable or
 * unknown falls back to the defaults: compare with yesterday, every layer shown, readings below). */
export function parseChartPrefs(stored: string | null): ChartPrefs {
  let saved: Record<string, unknown> = {};
  try {
    const value: unknown = JSON.parse(stored ?? "null");
    if (value && typeof value === "object") saved = value as Record<string, unknown>;
  } catch {
    /* unreadable: the defaults */
  }
  return {
    compare: saved.compare === "typical" || saved.compare === "none" ? saved.compare : "yesterday",
    hidden: Array.isArray(saved.hidden)
      ? CHART_LAYERS.filter((layer) => (saved.hidden as unknown[]).includes(layer))
      : [],
    readout: saved.readout === "over" ? "over" : "below",
  };
}

/** The reading at `time`, read between the readings either side when they are close enough. */
export function valueAtTime(
  points: readonly Reading[],
  time: number,
  within = 30 * 60_000,
): number | null {
  let after = points.findIndex((point) => point.time >= time);
  if (after < 0) after = points.length;
  const a = points[after - 1],
    b = points[after];
  if (a && b && b.time - a.time <= within)
    return b.time === a.time
      ? b.value
      : a.value + ((b.value - a.value) * (time - a.time)) / (b.time - a.time);
  const near = [a, b].find((point) => point && Math.abs(point.time - time) <= within / 2);
  return near ? near.value : null;
}
