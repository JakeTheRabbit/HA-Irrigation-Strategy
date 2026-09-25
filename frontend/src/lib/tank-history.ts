import type { HistoryPoint } from "./comparison-types";
import { descriptor, numeric } from "./model";
import { mergeSeries, plotPoints, type SensorReading } from "./sensor-context";
import type { EntityState, Room, Series, States } from "./types";

/** Tank EC and pH over time, and the controller's source-water gate beside them.
 * Everything here is pure: the components only draw what these functions return. */
export type TankKey = "ec" | "ph";
export const TANK_RANGES = [
  { hours: 24, label: "24 h" },
  { hours: 168, label: "7 days" },
  { hours: 720, label: "30 days" },
] as const;
/** Probe noise stays small: an axis or sparkline is never less than this many units tall. */
export const MIN_SPAN: Record<TankKey, number> = { ec: 0.2, ph: 0.2 };
/** The gap plotPoints breaks a line at. A value is not carried further than this either. */
const HOLD_MS = 2 * 3_600_000;
/** The units the tank card accepts (tankTelemetry). EC charts in mS/cm: dS/m is the same
 * number, a µS/cm probe reads a thousand times higher. */
const EC_DIVISORS: Record<string, number> = {
  "ms/cm": 1,
  "ds/m": 1,
  "µs/cm": 1000,
  "μs/cm": 1000,
  "us/cm": 1000,
};

/** What a probe's recorded values are divided by to reach the chart's unit (dividing, unlike
 * multiplying by 0.001, adds no float noise); null when its unit cannot go on that axis. A probe
 * with no current state has no unit to read, so its history is charted as recorded. */
export function chartDivisor(key: TankKey, entity: EntityState | undefined): number | null {
  if (!entity) return 1;
  const unit = String(entity.attributes.unit_of_measurement ?? "").toLowerCase();
  if (key === "ph") return unit === "ph" || unit === "" ? 1 : null;
  return EC_DIVISORS[unit] ?? null;
}

export interface TankLine {
  /** Every recorded reading in the window, in chart units, oldest first. */
  readings: SensorReading[];
  /** Thinned for drawing: extremes survive, and a null breaks the line at each long silence. */
  plot: HistoryPoint[];
  latest: SensorReading | null;
  lowest: SensorReading | null;
  highest: SensorReading | null;
}
export function tankLine(
  series: Pick<Series, "points"> | undefined,
  hours: number,
  now: number,
  divisor: number,
  maximum = 800,
): TankLine {
  const start = now - hours * 3_600_000;
  const recorded = (series?.points ?? [])
    .map((point) => ({ time: Date.parse(point.time), value: point.value / divisor }))
    .filter((point) => Number.isFinite(point.value) && Number.isFinite(point.time))
    .filter((point) => point.time <= now)
    .sort((a, b) => a.time - b.time);
  const first = recorded.findIndex((point) => point.time >= start);
  const inside = first < 0 ? [] : recorded.slice(first);
  // The recorder holds a state until it changes: the last reading before the window is the
  // value in force at its start.
  const before = (first < 0 ? recorded : recorded.slice(0, first)).at(-1);
  const readings =
    before && inside[0]?.time !== start
      ? [{ time: start, value: before.value }, ...inside]
      : inside;
  let lowest: SensorReading | null = null,
    highest: SensorReading | null = null;
  // A loop, not Math.min(...): a month of a busy probe is far more readings than a call takes.
  for (const reading of readings) {
    if (!lowest || reading.value <= lowest.value) lowest = reading;
    if (!highest || reading.value >= highest.value) highest = reading;
  }
  return {
    readings,
    plot: plotPoints(readings, maximum),
    latest: readings.at(-1) ?? null,
    lowest,
    highest,
  };
}

/** mergeSeries (a recent slice into a loaded window), keeping the last reading before `since` as
 * well: it is the value in force at the window's start, which tankLine carries in. */
export function mergeWindow(held: Series[], recent: Series[], since: number): Series[] {
  return mergeSeries(held, recent, since).map((series, index) => {
    const before = held[index].points.filter((point) => Date.parse(point.time) < since).at(-1);
    return before ? { ...series, points: [before, ...series.points] } : series;
  });
}

export interface ChartRow {
  time: number;
  ec: number | null;
  ph: number | null;
}
/** One row per moment either reading changed, carrying the value then in force for both, as Home
 * Assistant records a state until it changes. Inside a line's own span its breaks are explicit
 * nulls (plotPoints), and thinned points can sit hours apart, so it is carried to its next point;
 * past its last point it is carried at most two hours, so a probe that stopped is not drawn as
 * steady. */
export function chartRows(ec: HistoryPoint[], ph: HistoryPoint[]): ChartRow[] {
  const events = [
    ...ec.map((point) => ({ ...point, key: "ec" as const })),
    ...ph.map((point) => ({ ...point, key: "ph" as const })),
  ].sort((a, b) => a.time - b.time);
  const held: Record<TankKey, { value: number | null; time: number }> = {
    ec: { value: null, time: -Infinity },
    ph: { value: null, time: -Infinity },
  };
  const end: Record<TankKey, number> = {
    ec: ec.at(-1)?.time ?? -Infinity,
    ph: ph.at(-1)?.time ?? -Infinity,
  };
  const rows: ChartRow[] = [];
  for (const event of events) {
    held[event.key] = { value: event.value, time: event.time };
    const value = (key: TankKey) =>
      event.time <= end[key] || event.time - held[key].time <= HOLD_MS ? held[key].value : null;
    const row = { time: event.time, ec: value("ec"), ph: value("ph") };
    if (rows.at(-1)?.time === event.time) rows[rows.length - 1] = row;
    else rows.push(row);
  }
  return rows;
}

const INTERVALS = 4;
/** A value axis over the readings, at least `minSpan` tall, taking in a gate limit only when it
 * lies within one span of them: a far limit would flatten the trace, so it is listed under the
 * chart instead of drawn. Always four intervals, so the chart's two axes share its gridlines. */
export function tankAxis(readings: number[], limits: number[], minSpan: number) {
  let low = Infinity,
    high = -Infinity;
  for (const value of readings) {
    low = Math.min(low, value);
    high = Math.max(high, value);
  }
  if (low > high) return null;
  const reach = Math.max(high - low, minSpan);
  const shown = limits.filter((limit) => limit >= low - reach && limit <= high + reach);
  for (const limit of shown) {
    low = Math.min(low, limit);
    high = Math.max(high, limit);
  }
  const middle = (low + high) / 2,
    half = Math.max(high - low, minSpan) / 2;
  const pad = half * 0.16;
  low = Math.max(0, middle - half - pad);
  high = middle + half + pad;
  const clean = (value: number) => Number(value.toPrecision(12));
  const power = 10 ** Math.floor(Math.log10((high - low) / INTERVALS));
  // The first round step whose four intervals, from a multiple of it, cover the range.
  const step = [1, 2, 2.5, 5, 10, 20]
    .map((factor) => factor * power)
    .find((step) => Math.floor(low / step) * step + INTERVALS * step >= high)!;
  const min = Math.floor(low / step) * step;
  return {
    min: clean(min),
    max: clean(min + INTERVALS * step),
    ticks: Array.from({ length: INTERVALS + 1 }, (_, index) => clean(min + index * step)),
    limits: shown,
  };
}

export interface SourceGate {
  /** The limits the controller applies; a limit of 0, or none, is off. */
  min: number | null;
  max: number | null;
  /** The feed-water probe the controller checks against them. With none mapped, this half of the
   * gate is off whatever the limits say. */
  probe: string | null;
  /** The default room before its first save in Rooms & setup: until then the controller app's own
   * feed_<key>_sensor option, when set, names the probe instead, and the dashboard cannot see
   * app options. Once the room has a setup revision the descriptor's probe is the one in force. */
  option: boolean;
}
/** The room's source-water gate for EC or pH, as the controller reads it: feed_<key>_sensor from
 * the room's descriptor, and number.crop_steering_<prefix>irrigation_<key>_min / _max. */
export function sourceGate(states: States, room: Room, key: TankKey): SourceGate {
  const attributes = descriptor(states, room)?.attributes;
  const probe = attributes?.[`feed_${key}_sensor`];
  const limit = (end: "min" | "max") => {
    const value = numeric(states[`number.crop_steering_${room.prefix}irrigation_${key}_${end}`]);
    return value !== null && value > 0 ? value : null;
  };
  return {
    min: limit("min"),
    max: limit("max"),
    probe: typeof probe === "string" && probe ? probe : null,
    option: !room.prefix && !(Number(attributes?.setup_revision) >= 1),
  };
}
const trim = (value: number) => String(Number(value.toFixed(2)));
/** What the chart says about one half of the gate. Its lines are drawn only while it holds
 * irrigation on some probe (`active`); the text names which one. */
export function gateText(
  gate: SourceGate,
  key: TankKey,
  tankProbe: string | null,
): { active: boolean; text: string } {
  const name = key === "ec" ? "EC" : "pH",
    unit = key === "ec" ? " mS/cm" : "";
  const range =
    gate.min !== null && gate.max !== null
      ? `${trim(gate.min)}–${trim(gate.max)}${unit}`
      : gate.min !== null
        ? `at least ${trim(gate.min)}${unit}`
        : gate.max !== null
          ? `at most ${trim(gate.max)}${unit}`
          : null;
  // Limits set with no probe to check them on hold nothing: say so, so they are not taken as on.
  // Where the controller app's own option may name a probe, say only what is mapped here.
  if (!gate.probe)
    return {
      active: false,
      text: gate.option
        ? `${range ? `${range[0].toUpperCase()}${range.slice(1)} is set, but no` : "No"} feed-water ${name} probe is mapped here.`
        : `Off: no feed-water ${name} probe is mapped${range ? `, so ${range} is not applied` : ""}.`,
    };
  if (!range) return { active: false, text: `Off: no ${name} limits are set.` };
  return {
    active: true,
    text:
      gate.probe === tankProbe
        ? `${range}. Irrigation is held while this probe reads outside the gate or stops reporting.`
        : `${range}, checked on ${gate.probe}${tankProbe ? ", not on this tank probe" : ""}.`,
  };
}

/** Text alternative for one line: its latest, lowest and highest reading. */
export function describeLine(name: string, unit: string, line: TankLine | null): string {
  if (!line?.latest) return `${name}: no recorded readings`;
  const show = (reading: SensorReading | null) => (reading ? reading.value.toFixed(2) : "—");
  return `${name} latest ${show(line.latest)}, lowest ${show(line.lowest)}, highest ${show(line.highest)}${unit}`;
}

/** Local-time ticks: every six hours across a day, daily across a week, every five days across a
 * month. */
export function rangeTicks(start: number, end: number, hours: number): number[] {
  const days = hours <= 24 ? 0 : hours <= 168 ? 1 : 5;
  const at = new Date(start);
  at.setMinutes(0, 0, 0);
  at.setHours(days ? 0 : Math.floor(at.getHours() / 6) * 6);
  // The first tick is the first boundary inside the window; calendar stepping keeps date ticks
  // on local midnight across daylight-saving changes.
  if (at.getTime() < start) {
    if (days) at.setDate(at.getDate() + 1);
    else at.setHours(at.getHours() + 6);
  }
  const ticks: number[] = [];
  while (at.getTime() <= end) {
    ticks.push(at.getTime());
    if (days) at.setDate(at.getDate() + days);
    else at.setHours(at.getHours() + 6);
  }
  return ticks;
}
export function tickLabel(time: number, hours: number): string {
  const date = new Date(time);
  return hours <= 24
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : hours <= 168
      ? date.toLocaleDateString([], { weekday: "short", day: "numeric" })
      : date.toLocaleDateString([], { day: "numeric", month: "short" });
}

/** A sparkline in a width × height box: the window across, the readings (at least `minSpan` of
 * them) up. A null breaks the line. Empty without readings. */
export function sparkPath(
  points: HistoryPoint[],
  start: number,
  end: number,
  width: number,
  height: number,
  minSpan: number,
): string {
  let low = Infinity,
    high = -Infinity;
  for (const point of points)
    if (point.value !== null) {
      low = Math.min(low, point.value);
      high = Math.max(high, point.value);
    }
  if (low > high || end <= start) return "";
  const pad = Math.max(0, minSpan - (high - low)) / 2;
  const span = high - low + 2 * pad || 1;
  let open = false;
  return points
    .map((point) => {
      if (point.value === null) {
        open = false;
        return "";
      }
      const x = ((point.time - start) / (end - start)) * width;
      // One unit inside the box top and bottom, so the stroke is never clipped.
      const y = 1 + (1 - (point.value - (low - pad)) / span) * (height - 2);
      const move = open ? "L" : "M";
      open = true;
      return `${move}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join("");
}
