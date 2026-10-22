/** The zone page's history explorer: which sensors a room has, the range a grower picks, recorded
 * states reduced to a fixed time grid (so a month of many sensors stays a few hundred points each),
 * and the previous run laid over this one by grow day. Pure: the component fetches and draws. */
import { addDays, dateInZone, daysBetween, midnight, wallTime } from "./comparison";
import type { RunRecord } from "./comparison-types";
import { growDay, type TimelineRow } from "./day-timeline";
import { descriptor } from "./model";
import { getDisplayUnits } from "./display-units";
import { pagedQuery, type V2Outcome } from "./parity-api";
import type { CsEvent } from "./parity-types";
import type { SteCopy } from "./ste-copy";
import type { ProjectionIntent } from "./strategy-review";
import { clock, dayKey, dayLabel, startOfDay, wallHhmm } from "./time";
import type { Controller, RoomView, States } from "./types";

const DAY = 86_400_000;
const HOUR = 3_600_000;
const MIN = 60_000;
/** The longest range the explorer reads: one request per day, two at a time. */
export const MAX_RANGE_DAYS = 180;

export type Unit = "%" | "mS/cm" | "°C" | "°F" | "kPa" | "pH" | "ppm" | "µmol/m²/s";
export type SensorKind = "vwc" | "ec" | "climate" | "feed";
export interface ExplorerSensor {
  /** Stable for the URL: the entity id. */
  key: string;
  entityId: string;
  label: string;
  /** The checkbox group: a zone's name, "Room climate" or "Feed and tank". */
  group: string;
  kind: SensorKind;
  zone: number | null;
  unit: Unit;
  color: string;
}

/** Twelve hues that read on the light and the dark surface; greys stay for the frame (ISA-101). */
export const SERIES_COLORS = [
  "#1e88e5",
  "#e08a00",
  "#8e5cd9",
  "#d84f7a",
  "#00897b",
  "#7cb342",
  "#c0763a",
  "#3f7fbf",
  "#b04fb0",
  "#5c8f3a",
  "#d9534f",
  "#4a9fa8",
];

const CLIMATE: [string, string, Unit][] = [
  ["temperature_sensor", "Air temperature", "°C"],
  ["humidity_sensor", "Humidity", "%"],
  ["vpd_sensor", "VPD", "kPa"],
  // Mapped on Equipment › Setup for the dashboard only.
  ["co2_sensor", "CO2", "ppm"],
  ["ppfd_sensor", "PPFD", "µmol/m²/s"],
];
const FEED: [string, string, Unit][] = [
  ["feed_ec_sensor", "Feed EC", "mS/cm"],
  ["feed_ph_sensor", "Feed pH", "pH"],
  ["tank_ec_sensor", "Tank EC", "mS/cm"],
  ["tank_ph_sensor", "Tank pH", "pH"],
  ["tank_temperature_sensor", "Tank temperature", "°C"],
  ["water_level_sensor", "Tank level", "%"],
];

/** The unit a sensor reports, where the explorer knows it; else the kind's own. */
function unitOf(states: States, id: string, fallback: Unit): Unit {
  const unit = states[id]?.attributes.unit_of_measurement;
  return unit === "°F" && (fallback === "°C" || fallback === "°F") ? "°F" : fallback;
}

/** Every sensor of the room the explorer can draw, from the room's zones (their combined readings
 * and the probes behind them) and its descriptor (climate, feed and tank). A sensor Home Assistant
 * does not have is left out. */
export function explorerSensors(room: RoomView, states: States): ExplorerSensor[] {
  const list: Omit<ExplorerSensor, "color">[] = [];
  const seen = new Set<string>();
  const add = (sensor: Omit<ExplorerSensor, "color" | "key">) => {
    if (!states[sensor.entityId] || seen.has(sensor.entityId)) return;
    seen.add(sensor.entityId);
    list.push({ ...sensor, key: sensor.entityId });
  };
  for (const zone of room.zones)
    for (const kind of ["vwc", "ec"] as const) {
      const fused = zone[kind].entityId;
      if (!fused) continue;
      const type = states[fused]?.attributes.ec_type;
      add({
        entityId: fused,
        label: `${zone.name} ${kind === "vwc" ? "VWC" : type === "bulk" ? "bulk EC" : "pore EC"}`,
        group: zone.name,
        kind,
        zone: zone.id,
        unit: kind === "vwc" ? "%" : "mS/cm",
      });
      const attributes = states[fused]?.attributes ?? {};
      const probes = [
        ...(Array.isArray(attributes.used) ? attributes.used : []),
        ...(attributes.excluded && typeof attributes.excluded === "object"
          ? Object.keys(attributes.excluded)
          : []),
      ].filter((id): id is string => typeof id === "string" && id !== fused);
      for (const id of probes)
        add({
          entityId: id,
          label: String(states[id]?.attributes.friendly_name || id),
          group: zone.name,
          kind,
          zone: zone.id,
          unit: kind === "vwc" ? "%" : "mS/cm",
        });
    }
  const mapped = descriptor(states, room.room)?.attributes ?? {};
  // Each zone's root-zone temperature probe (Equipment › Setup), in the zone's own group.
  const roots = mapped.substrate_temperature_sensors;
  for (const zone of room.zones) {
    const id =
      roots && typeof roots === "object" ? (roots as Record<string, unknown>)[String(zone.id)] : null;
    if (typeof id === "string" && id)
      add({
        entityId: id,
        label: `${zone.name} root-zone temperature`,
        group: zone.name,
        kind: "climate",
        zone: zone.id,
        unit: unitOf(states, id, "°C"),
      });
  }
  for (const [table, group, kind] of [
    [CLIMATE, "Room climate", "climate"],
    [FEED, "Feed and tank", "feed"],
  ] as const)
    for (const [key, label, unit] of table) {
      const id = mapped[key];
      if (typeof id === "string" && id)
        add({ entityId: id, label, group, kind, zone: null, unit: unitOf(states, id, unit) });
    }
  return list.map((sensor, index) => ({
    ...sensor,
    color: SERIES_COLORS[index % SERIES_COLORS.length],
  }));
}

export type Preset = "today" | "growday" | "3d" | "7d" | "14d" | "30d" | "run" | "custom";
export const PRESETS: { id: Exclude<Preset, "custom">; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "growday", label: "Grow-day" },
  { id: "3d", label: "3 d" },
  { id: "7d", label: "7 d" },
  { id: "14d", label: "14 d" },
  { id: "30d", label: "30 d" },
  { id: "run", label: "This run" },
];
export interface Choice {
  preset: Preset;
  /** A custom range, epoch ms. */
  from: number | null;
  to: number | null;
  /** The ticked sensors' entity ids; null: the zone's own VWC and EC. */
  sensors: string[] | null;
  /** Sensor row -> off | last | recorded run ID. Missing preserves the old global overlay. */
  probeCompare?: Record<string, string>;
  /** Sensor row -> explicitly selected historical entity, when row matching is ambiguous. */
  probeMatch?: Record<string, string>;
  compare: boolean;
  /** The grow compared with: a run's id; null for the last grow before this one. */
  compareRun: string | null;
  shots: boolean;
  phases: boolean;
  /** Each grow day's peak and the low after it, on the zone's VWC (ranges of 14 d at most). */
  dryback: boolean;
}
export const DEFAULT_CHOICE: Choice = {
  preset: "growday",
  from: null,
  to: null,
  sensors: null,
  compare: false,
  compareRun: null,
  shots: true,
  phases: true,
  dryback: false,
};

/** The zone explorer's choice from the query of the page's hash (`#/history/explorer?zone=1&zr=7d&s=...`).
 * Its range keys are its own (`zr`, `zfrom`, `zto`): History › Explorer's room charts use `range`,
 * `from` and `to`. An address from before that has only `range` (one of these presets) is read once. */
export function readChoice(hash: string): Choice {
  const query = new URLSearchParams(hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "");
  const old = query.get("range") ?? "";
  const legacy = !query.has("zr") && (PRESETS.some((item) => item.id === old) || old === "custom");
  const range = query.get("zr") ?? (legacy ? old : "");
  const from = Date.parse(query.get("zfrom") ?? (legacy ? query.get("from") : null) ?? ""),
    to = Date.parse(query.get("zto") ?? (legacy ? query.get("to") : null) ?? "");
  const custom = range === "custom" && Number.isFinite(from) && Number.isFinite(to) && to > from;
  const preset = PRESETS.some((item) => item.id === range)
    ? (range as Preset)
    : custom
      ? "custom"
      : DEFAULT_CHOICE.preset;
  const sensors = query.get("s");
  return {
    preset,
    from: custom ? from : null,
    to: custom ? to : null,
    sensors:
      sensors === null ? null : sensors.split(",").filter((id) => /^[a-z_]+\.[a-z0-9_]+$/.test(id)),
    ...(query.has("pc") ? { probeCompare: readProbeChoice(query.get("pc")) } : {}),
    ...(query.has("pm") ? { probeMatch: readProbeChoice(query.get("pm")) } : {}),
    compare: query.get("compare") === "1",
    compareRun: /^[a-zA-Z0-9_-]{1,64}$/.test(query.get("vs") ?? "") ? query.get("vs") : null,
    shots: query.get("shots") !== "0",
    phases: query.get("phases") !== "0",
    dryback: query.get("dryback") === "1",
  };
}

/** The hash with the zone explorer's choice in its query; other query keys (the room explorer's
 * among them) stay. */
export function writeChoice(hash: string, choice: Choice): string {
  const [path, rest = ""] = hash.split("?");
  const query = new URLSearchParams(rest);
  for (const key of ["zr", "zfrom", "zto", "s", "compare", "vs", "shots", "phases", "dryback", "pc", "pm"])
    query.delete(key);
  query.set("zr", choice.preset);
  if (choice.preset === "custom" && choice.from !== null && choice.to !== null) {
    query.set("zfrom", new Date(choice.from).toISOString());
    query.set("zto", new Date(choice.to).toISOString());
  }
  if (choice.sensors) query.set("s", choice.sensors.join(","));
  if (Object.keys(choice.probeCompare ?? {}).length) query.set("pc", JSON.stringify(choice.probeCompare));
  if (Object.keys(choice.probeMatch ?? {}).length) query.set("pm", JSON.stringify(choice.probeMatch));
  if (choice.compare) query.set("compare", "1");
  if (choice.compare && choice.compareRun) query.set("vs", choice.compareRun);
  if (!choice.shots) query.set("shots", "0");
  if (!choice.phases) query.set("phases", "0");
  if (choice.dryback) query.set("dryback", "1");
  return `${path}?${query.toString().replaceAll("%2C", ",")}`;
}

/** Lights-on of a run's grow day `day` (1 is its start date), on the run's own clock; midnight
 * where the run recorded no lights hours. */
export function runDayStart(run: RunRecord, day: number): number {
  const date = addDays(run.start_date, day - 1);
  const on = run.lights.on;
  return on !== null && on >= 0 && on < 24
    ? wallTime(date, Math.round(on * 60), run.time_zone)
    : midnight(date, run.time_zone);
}

/** Which grow day of a run `time` falls in, with the part of that day gone: 1.5 is halfway
 * through day 1, from its lights-on to the next. Before the run's first lights-on it is below 1. */
export function runDayAt(run: RunRecord, time: number): number {
  let day = Math.floor((time - runDayStart(run, 1)) / DAY) + 1;
  while (runDayStart(run, day) > time) day--;
  while (runDayStart(run, day + 1) <= time) day++;
  const start = runDayStart(run, day),
    end = runDayStart(run, day + 1);
  return day + (time - start) / (end - start);
}

/** The time a fractional grow day of a run starts at: the inverse of runDayAt. */
export function runTimeAt(run: RunRecord, age: number): number {
  const day = Math.floor(age);
  const start = runDayStart(run, day);
  return start + (age - day) * (runDayStart(run, day + 1) - start);
}

export interface PreviousWindow {
  start: number;
  end: number;
  /** The grow days of the current run the range covers, as the legend names them. */
  firstDay: number;
  lastDay: number;
}
/** The span of the previous run at the same grow days as [start, end) of the current one, aligned
 * on lights-on, not on the calendar. Null when the range is before the current run, or the
 * previous run never reached those days. */
export function previousWindow(
  current: RunRecord,
  previous: RunRecord,
  start: number,
  end: number,
  now: number,
): PreviousWindow | null {
  const from = Math.max(1, runDayAt(current, start)),
    to = runDayAt(current, end);
  if (to <= from) return null;
  // A finished run's last grow day ends at the lights-on after its end date.
  const last = previous.end_date
    ? runDayStart(previous, daysBetween(previous.start_date, previous.end_date) + 2)
    : now;
  const window = {
    start: runTimeAt(previous, from),
    end: Math.min(runTimeAt(previous, to), last, now),
  };
  if (window.end <= window.start) return null;
  return {
    ...window,
    firstDay: Math.floor(from),
    lastDay: Math.max(Math.floor(from), Math.ceil(to) - 1),
  };
}

/** A time of the previous run moved onto the current one: the same grow day, the same part of it. */
export function alignToCurrent(current: RunRecord, previous: RunRecord, time: number): number {
  return runTimeAt(current, runDayAt(previous, time));
}

/** The run in progress, and the latest finished one before it, as Compare runs picks them. */
export function pickRuns(runs: RunRecord[]): {
  current: RunRecord | null;
  previous: RunRecord | null;
} {
  const open = runs.filter((run) => !run.archived);
  const current = open.find((run) => !run.end_date) ?? open[0] ?? null;
  const previous =
    open
      .filter((run) => run.id !== current?.id && run.end_date)
      .sort((a, b) => b.start_date.localeCompare(a.start_date))[0] ?? null;
  return { current, previous };
}

export interface Span {
  start: number;
  end: number;
}
/** The span a choice shows, ending now for a preset. Null for a custom range that is not one. */
export function resolveRange(
  choice: Choice,
  context: {
    now: number;
    timeZone: string;
    lightsOn: number | null;
    lightsOff: number | null;
    run: RunRecord | null;
  },
): Span | null {
  const { now, timeZone } = context;
  const today = midnight(dateInZone(now, timeZone), timeZone);
  const back = (days: number) => ({ start: now - days * DAY, end: now });
  const capped = ({ start, end }: Span) => ({
    start: Math.max(start, end - MAX_RANGE_DAYS * DAY),
    end,
  });
  switch (choice.preset) {
    case "today":
      return { start: today, end: now };
    case "growday": {
      const day = growDay(context.lightsOn, context.lightsOff, now, timeZone);
      return { start: day?.start ?? today, end: now };
    }
    case "3d":
      return back(3);
    case "7d":
      return back(7);
    case "14d":
      return back(14);
    case "30d":
      return back(30);
    case "run":
      return context.run ? capped({ start: runDayStart(context.run, 1), end: now }) : back(14);
    case "custom": {
      if (choice.from === null || choice.to === null) return null;
      const end = Math.min(choice.to, now);
      return end > choice.from ? capped({ start: choice.from, end }) : null;
    }
  }
}

/** The day-sized requests a span is read in. */
export function chunks({ start, end }: Span): Span[] {
  const list: Span[] = [];
  for (let from = start; from < end; from += DAY)
    list.push({ start: from, end: Math.min(end, from + DAY) });
  return list;
}

const STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 180, 360, 720].map((minutes) => minutes * 60_000);
/** The grid's step: the shortest that keeps the span within `buckets` points. */
export function stepFor(span: number, buckets = 720): number {
  return STEPS.find((step) => span / step <= buckets) ?? Math.ceil(span / buckets / HOUR) * HOUR;
}

/** One sensor's recorded states on a fixed grid from `start`, one value per step: the mean of the
 * readings in it, else the state still held from before (Home Assistant records a change, not a
 * repeat). A state that is not a number (unavailable) is a gap until the next reading. Rows can
 * be added a day at a time, in any order. */
export class SeriesGrid {
  readonly length: number;
  private sums: Float64Array;
  private counts: Uint32Array;
  /** The last row in each step: its time, and its value (NaN: not a number). */
  private lastTime: Float64Array;
  private lastValue: Float64Array;
  private carryTime = -Infinity;
  private carry = NaN;
  constructor(
    readonly start: number,
    readonly end: number,
    readonly step: number,
  ) {
    this.length = Math.max(1, Math.ceil((end - start) / step));
    this.sums = new Float64Array(this.length);
    this.counts = new Uint32Array(this.length);
    this.lastTime = new Float64Array(this.length).fill(-Infinity);
    this.lastValue = new Float64Array(this.length).fill(NaN);
  }
  add(rows: readonly TimelineRow[]) {
    for (const row of rows) {
      const text = row.state.trim();
      const value = text && Number.isFinite(Number(text)) ? Number(text) : NaN;
      if (row.time >= this.end) continue;
      if (row.time < this.start) {
        // The state held when the grid starts.
        if (row.time >= this.carryTime) {
          this.carryTime = row.time;
          this.carry = value;
        }
        continue;
      }
      const index = Math.floor((row.time - this.start) / this.step);
      if (!Number.isNaN(value)) {
        this.sums[index] += value;
        this.counts[index]++;
      }
      if (row.time >= this.lastTime[index]) {
        this.lastTime[index] = row.time;
        this.lastValue[index] = value;
      }
    }
  }
  values(): (number | null)[] {
    const out: (number | null)[] = new Array(this.length);
    let held = this.carry;
    for (let index = 0; index < this.length; index++) {
      if (this.lastTime[index] > -Infinity) {
        out[index] = this.counts[index]
          ? this.sums[index] / this.counts[index]
          : Number.isNaN(this.lastValue[index])
            ? null
            : this.lastValue[index];
        held = this.lastValue[index];
      } else out[index] = Number.isNaN(held) ? null : held;
    }
    return out;
  }
  timeAt(index: number): number {
    return this.start + index * this.step;
  }
}

/** The previous run's grid moved onto the current one, step by step through alignToCurrent; a
 * step or two that the move leaves empty (a longer day, a clock change) is filled from before. */
export function alignGrid(
  values: readonly (number | null)[],
  previous: { grid: Pick<SeriesGrid, "timeAt">; run: RunRecord },
  current: { start: number; step: number; length: number; run: RunRecord },
): (number | null)[] {
  const out: (number | null)[] = new Array(current.length).fill(null);
  const filled = new Uint8Array(current.length);
  values.forEach((value, index) => {
    const time = alignToCurrent(current.run, previous.run, previous.grid.timeAt(index));
    const target = Math.floor((time - current.start) / current.step);
    if (target < 0 || target >= current.length) return;
    out[target] = value;
    filled[target] = 1;
  });
  for (let index = 1; index < current.length; index++)
    if (!filled[index] && filled[index - 1] && (filled[index + 1] || filled[index + 2]))
      ((out[index] = out[index - 1]), (filled[index] = 1));
  return out;
}

/** The decimals a value of each unit is shown with. */
export const UNIT_DIGITS: Record<Unit, number> = {
  "%": 1,
  "mS/cm": 2,
  "°C": 1,
  "°F": 1,
  kPa: 2,
  pH: 2,
  ppm: 0,
  "µmol/m²/s": 0,
};

/** The explorer's help, in Simplified Technical English (ASD-STE100). */
export const EXPLORER_COPY = {
  explorer: {
    label: "History explorer",
    copy: {
      tooltip:
        "This chart shows the recorded values of the sensors that you select, for the time range that you select.",
      guidance:
        "Select a range. Then select the sensors. Move the pointer on the chart to see all the values at that time.",
    } satisfies SteCopy,
  },
  range: {
    label: "Time range",
    copy: {
      tooltip:
        "The time range of the chart. Grow-day starts at lights-on. This run starts at lights-on of the first day of the current run.",
      guidance: `For a custom range, set the start and the end. The maximum range is ${MAX_RANGE_DAYS} days.`,
    } satisfies SteCopy,
  },
  compare: {
    label: "Compare with previous run",
    copy: {
      tooltip:
        "This adds the data of the previous run as dashed lines. The chart aligns the two runs by grow day and lights-on, not by calendar date.",
      impact:
        "The chart shows day N of the previous run at the same position as day N of this run.",
    } satisfies SteCopy,
  },
  dryback: {
    label: "Dryback markers",
    copy: {
      tooltip:
        "This marks the peak VWC of each grow day and the lowest VWC after it, on the VWC of this zone. The label is the dryback as the controller calculates it: the drop as a percent of the peak.",
      impact: "The chart shows the markers only for a range of 14 days or less.",
      guidance: "Select the VWC of this zone to see the markers.",
    } satisfies SteCopy,
  },
  sensors: {
    label: "Sensors",
    copy: {
      tooltip:
        "The sensors of this room. Each unit has its own axis. A sensor that Home Assistant does not have is not in the list.",
    } satisfies SteCopy,
  },
} as const;

/** The longest range the dryback markers are drawn on: past it they are noise. */
export const DRYBACK_MARKER_DAYS = 14;
export interface DrybackMarker {
  /** The grow day's highest reading, and the lowest after it before the next lights-on. */
  peak: { t: number; value: number };
  low: { t: number; value: number };
  /** As the controller measures dryback: (peak − low) / peak × 100, percent of the peak. */
  percent: number;
}
/** Per grow day (from each lights-on, `starts`), the zone's peak VWC and the low after it, from the
 * explorer's grid of values (`times[i]` the time of `values[i]`). A day with under two readings, or
 * whose low is not under its peak, has none. */
export function drybackMarkers(
  times: readonly number[],
  values: readonly (number | null)[],
  starts: readonly number[],
): DrybackMarker[] {
  const markers: DrybackMarker[] = [];
  starts.forEach((start, index) => {
    const end = starts[index + 1] ?? Infinity;
    let peak: { t: number; value: number } | null = null;
    let at = -1;
    for (let i = 0; i < times.length; i++) {
      const value = values[i];
      if (times[i] < start || times[i] >= end || value === null) continue;
      if (!peak || value > peak.value) {
        peak = { t: times[i], value };
        at = i;
      }
    }
    if (!peak || peak.value <= 0) return;
    let low: { t: number; value: number } | null = null;
    for (let i = at + 1; i < times.length && times[i] < end; i++) {
      const value = values[i];
      // A reading of 0 or less is a probe gap, not a dry slab.
      if (value !== null && value > 0 && (!low || value < low.value)) low = { t: times[i], value };
    }
    if (!low || low.value >= peak.value) return;
    markers.push({ peak, low, percent: ((peak.value - low.value) / peak.value) * 100 });
  });
  return markers;
}


function readProbeChoice(text: string | null): Record<string, string> {
  try {
    const value = JSON.parse(text ?? "{}");
    if (!value || Array.isArray(value) || typeof value !== "object") return {};
    return Object.fromEntries(Object.entries(value).slice(0, 32).filter(([key, val]) =>
      /^sensor\.[a-z0-9_]+$/.test(key) && typeof val === "string" && val.length <= 200)) as Record<string, string>;
  } catch { return {}; }
}

// ---------------------------------------------------------------------------------------------
// History › Explorer (H1, mockup 09): the room's readings on stacked charts under a PHASE and a
// SHOTS lane, notes in place, one crosshair across them all.

/** The Journal kinds the explorer's lanes and notes read. */
export const EXPLORER_KINDS = ["phase.changed", "shot.completed", "alert.raised"] as const;
/** The most events one range reads; past it, only the newest whole days are shown. */
export const MAX_EXPLORER_EVENTS = 5000;
/** The explorer's own ranges: the four the mockup offers. */
export type ExplorerRange = "today" | "7d" | "run" | "custom";
export const EXPLORER_RANGES: { id: ExplorerRange; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "7d", label: "7 d" },
  { id: "run", label: "This run" },
  { id: "custom", label: "Custom" },
];

export interface ExplorerChoice {
  range: ExplorerRange;
  from: number | null;
  to: number | null;
  /** The ticked series' entity ids; null: the defaults. */
  series: string[] | null;
  /** Compare with the last run, at the same grow day. */
  last: boolean;
}
/** The explorer's choice from its page's hash (`#/history/explorer?range=7d&series=…&last=1`). */
export function readExplorerChoice(hash: string): ExplorerChoice {
  const query = new URLSearchParams(hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "");
  const from = Date.parse(query.get("from") ?? ""),
    to = Date.parse(query.get("to") ?? "");
  const custom = Number.isFinite(from) && Number.isFinite(to) && to > from;
  const asked = query.get("range");
  const known = EXPLORER_RANGES.find((r) => r.id === asked && r.id !== "custom")?.id;
  const range: ExplorerRange = asked === "custom" && custom ? "custom" : (known ?? "today");
  const series = query.get("series");
  return {
    range,
    from: range === "custom" ? from : null,
    to: range === "custom" ? to : null,
    series: series === null ? null : series.split(",").filter((id) => /^[a-z_]+\.[a-z0-9_]+$/.test(id)),
    last: query.get("last") === "1",
  };
}
/** The hash with the explorer's choice; other keys (the zone) stay. */
export function writeExplorerChoice(hash: string, choice: ExplorerChoice): string {
  const [path, rest = ""] = hash.split("?");
  const query = new URLSearchParams(rest);
  for (const key of ["range", "from", "to", "series", "last"]) query.delete(key);
  query.set("range", choice.range);
  if (choice.range === "custom" && choice.from !== null && choice.to !== null) {
    query.set("from", new Date(choice.from).toISOString());
    query.set("to", new Date(choice.to).toISOString());
  }
  if (choice.series) query.set("series", choice.series.join(","));
  if (choice.last) query.set("last", "1");
  return `${path}?${query.toString().replaceAll("%2C", ",")}`;
}

/** The span a choice reads (ending now, or a custom end), and the axis it is drawn on: Today's axis
 * runs to the next midnight so the rest of the day shows ahead. Null for an unusable custom range. */
export function explorerSpan(
  choice: ExplorerChoice,
  context: { now: number; timeZone: string; run: RunRecord | null },
): { data: Span; axis: Span } | null {
  const { now, timeZone } = context;
  if (choice.range === "today") {
    const start = startOfDay(now, timeZone);
    return { data: { start, end: now }, axis: { start, end: startOfDay(start + 36 * HOUR, timeZone) } };
  }
  const preset: Preset = choice.range;
  const data = resolveRange(
    { ...DEFAULT_CHOICE, preset, from: choice.from, to: choice.to },
    { now, timeZone, lightsOn: null, lightsOff: null, run: context.run },
  );
  return data ? { data, axis: data } : null;
}

/** "Thu 22 Oct, 00:00 to now", or a custom range's two ends. */
export function explorerRangeText(span: Span, now: number, timeZone: string): string {
  const end = span.end >= now - 60_000 ? "now" : `${dayLabel(span.end, timeZone)}, ${clock(span.end, timeZone)}`;
  return `${dayLabel(span.start, timeZone)}, ${clock(span.start, timeZone)} to ${end}`;
}

type EventRead = (
  controller: Pick<Controller, "operator">,
  q: { room_id: string; since: string; until?: string; kinds?: string[] },
  max?: number,
) => Promise<V2Outcome<{ events: CsEvent[] }>>;
export type ExplorerEvents =
  | { kind: "ok"; events: CsEvent[]; truncated: boolean }
  | { kind: "missing" }
  | { kind: "error"; message: string };
/** How many days are read at once. */
const DAYS_AT_ONCE = 4;
/** The room's phase changes, completed shots and alerts over `span`, oldest first (pagedQuery with
 * `kinds`; journal_query answers oldest first). Days are read four at a time from the newest back,
 * until `max` events: past it, only the newest `max` are kept (`truncated`), the day that overflows
 * read again in halves, newest half first, to find them. `missing` on 3.17. */
export async function loadExplorerEvents(
  controller: Pick<Controller, "operator">,
  roomId: string,
  span: Span,
  query: EventRead = pagedQuery,
  max = MAX_EXPLORER_EVENTS,
): Promise<ExplorerEvents> {
  const read = (window: Span, limit: number) =>
    query(
      controller,
      {
        room_id: roomId,
        since: new Date(window.start).toISOString(),
        until: new Date(window.end).toISOString(),
        kinds: [...EXPLORER_KINDS],
      },
      limit,
    );
  type Read = { events: CsEvent[] } | { kind: "missing" } | { kind: "error"; message: string };
  /** The newest `need` events of `window`, oldest first. */
  const newest = async (window: Span, need: number): Promise<Read> => {
    const short = window.end - window.start <= HOUR;
    const first = await read(window, short ? Number.MAX_SAFE_INTEGER : need + 1);
    if (first.kind !== "ok") return first.kind === "missing" ? first : { kind: "error", message: first.message };
    if (first.data.events.length <= need) return { events: first.data.events };
    if (short) return { events: first.data.events.slice(-need) };
    const middle = window.start + Math.floor((window.end - window.start) / 2);
    const later = await newest({ start: middle, end: window.end }, need);
    if (!("events" in later) || later.events.length >= need) return later;
    const earlier = await newest({ start: window.start, end: middle }, need - later.events.length);
    return "events" in earlier ? { events: [...earlier.events, ...later.events] } : earlier;
  };
  const days: Span[] = [];
  for (let end = span.end; end > span.start; end -= DAY) days.push({ start: Math.max(span.start, end - DAY), end });
  const kept: CsEvent[][] = [];
  let total = 0;
  for (let i = 0; i < days.length; i += DAYS_AT_ONCE) {
    const batch = days.slice(i, i + DAYS_AT_ONCE);
    const reads = await Promise.all(batch.map((day) => read(day, max + 1)));
    for (const [j, answer] of reads.entries()) {
      if (answer.kind === "missing") return { kind: "missing" };
      if (answer.kind === "error") return { kind: "error", message: answer.message };
      const need = max - total;
      if (answer.data.events.length <= need) {
        kept.push(answer.data.events);
        total += answer.data.events.length;
        continue;
      }
      const last = await newest(batch[j], need);
      if (!("events" in last)) return last.kind === "missing" ? last : { kind: "error", message: last.message };
      kept.push(last.events);
      return { kind: "ok", events: kept.reverse().flat(), truncated: true };
    }
  }
  return { kind: "ok", events: kept.reverse().flat(), truncated: false };
}

export interface PhaseSegment {
  from: number;
  to: number;
  phase: string;
  planned: boolean;
}
const PHASE = /^P[0-3]$/;
/** One zone's phases over `span`, from the Journal's `phase.changed` (a room-wide one counts for every
 * zone): the phase held at the span's start is the first change's `from`. Recorded segments end now.
 * Planned: only from projected shots that carry their phase, each phase to the end of its shot. The
 * controller's projection does not carry one yet, so today there is no planned segment: none is
 * guessed. */
export function phaseLane(
  events: readonly CsEvent[],
  span: Span,
  projection: readonly (ProjectionIntent & { phase?: unknown })[] | null,
  options: { now: number; zone?: number | null },
): PhaseSegment[] {
  const { now } = options;
  const changes = events
    .filter(
      (e) =>
        e.kind === "phase.changed" &&
        (e.zone === null || options.zone == null || e.zone === options.zone) &&
        Number.isFinite(Date.parse(e.ts)),
    )
    .map((e) => ({ t: Date.parse(e.ts), from: String(e.data.from ?? ""), to: String(e.data.to ?? "") }))
    .sort((a, b) => a.t - b.t);
  const before = changes.filter((c) => c.t <= span.start).at(-1);
  let phase: string | null = before?.to ?? changes.find((c) => c.t > span.start)?.from ?? null;
  let cursor = span.start;
  const end = Math.min(now, span.end);
  const lane: PhaseSegment[] = [];
  const push = (to: number) => {
    const from = cursor;
    cursor = Math.max(cursor, to);
    if (!phase || !PHASE.test(phase) || to <= from) return;
    const last = lane.at(-1);
    if (last && last.phase === phase && last.to === from) last.to = to;
    else lane.push({ from, to, phase, planned: false });
  };
  for (const change of changes) {
    if (change.t <= span.start || change.t >= end) continue;
    push(change.t);
    phase = change.to;
  }
  push(end);
  const ahead = (projection ?? [])
    .filter((i) => (options.zone == null || i.zone === options.zone) && typeof i.phase === "string" && PHASE.test(i.phase))
    .map((i) => ({ end: Date.parse(i.at) + (Number(i.duration_s) || 0) * 1000, phase: i.phase as string }))
    .filter((i) => Number.isFinite(i.end) && i.end > end)
    .sort((a, b) => a.end - b.end);
  for (const intent of ahead) {
    const last = lane.at(-1);
    const from = last?.planned ? last.to : end;
    const to = Math.min(span.end, intent.end);
    if (to <= from) continue;
    if (last?.planned && last.phase === intent.phase) last.to = to;
    else lane.push({ from, to, phase: intent.phase, planned: true });
  }
  return lane;
}

/** A series a note can be about: its readings and, where one is saved, its band. A `level` series
 * (a tank) also says when it was refilled. */
export interface NoteReading {
  key: string;
  label: string;
  entityId: string;
  points: { t: number; v: number }[];
  band: readonly [number, number] | null;
  kind: "value" | "level";
}
export interface ChartNote {
  at: number;
  series: string;
  text: string;
}
const trimmed = (value: number) => String(Number(value.toFixed(1)));
/** The notes the explorer writes on its charts, only from what was recorded: a selected series that
 * left its saved band (once, where it left: "Zone 2 over the band since 09:40"), a tank level that
 * rose 10 points or more and held for two readings, from its first higher reading ("Refilled 06:10 ·
 * 40% to 74%"; a reading of 0 or less is a dropout, not a level), and an alert
 * raised on a selected series' sensor, unless a band note within 30 min already says it. */
export function chartNotes(
  events: readonly CsEvent[],
  series: readonly string[],
  readings: readonly NoteReading[],
  timeZone = "UTC",
): ChartNote[] {
  const notes: ChartNote[] = [];
  const time = (t: number) => clock(t, timeZone);
  for (const reading of readings) {
    if (!series.includes(reading.key)) continue;
    const points = reading.points.filter((p) => Number.isFinite(p.v));
    const band = reading.band;
    if (band)
      for (let i = 0; i < points.length; i++) {
        const sideOf = (v: number) => (v > band[1] ? "over" : v < band[0] ? "under" : null);
        const side = sideOf(points[i].v);
        if (!side) continue;
        let j = i;
        while (j + 1 < points.length && sideOf(points[j + 1].v) === side) j++;
        const back = points[j + 1];
        // Out of the band from the first reading: it left before the range, so say only when it came back.
        const when =
          i === 0
            ? back
              ? `until ${time(back.t)}`
              : "all through this range"
            : back
              ? `${time(points[i].t)} to ${time(back.t)}`
              : `since ${time(points[i].t)}`;
        notes.push({ at: points[i].t, series: reading.key, text: `${reading.label} ${side} the band ${when}` });
        i = j;
      }
    if (reading.kind === "level") {
      // A level of 0 or less is a probe dropout: a gap, so its recovery is not a refill.
      const points = reading.points.filter((p) => Number.isFinite(p.v) && p.v > 0);
      const rises = (k: number) =>
        points[k + 1].v - points[k].v > 1 && points[k + 1].t - points[k].t <= 15 * MIN;
      for (let i = 0; i + 1 < points.length; i++) {
        if (!rises(i)) continue;
        // The rise goes on while the level holds or climbs, up to 15 min after its last gain.
        let j = i + 1,
          top = j;
        while (j + 1 < points.length && points[j + 1].v >= points[j].v && points[j + 1].t - points[top].t <= 15 * MIN) {
          j++;
          if (points[j].v > points[top].v) top = j;
        }
        // It holds: the two readings after the top stay at least 10 points over the start.
        const held = [points[top + 1], points[top + 2]].every((p) => p && p.v - points[i].v >= 10);
        if (points[top].v - points[i].v >= 10 && held)
          notes.push({
            at: points[i + 1].t,
            series: reading.key,
            text: `Refilled ${time(points[i + 1].t)} · ${trimmed(points[i].v)}% to ${trimmed(points[top].v)}%`,
          });
        i = top - 1;
      }
    }
  }
  const banded = (key: string, t: number) =>
    notes.some((n) => n.series === key && n.text.includes(" the band ") && Math.abs(n.at - t) <= 30 * MIN);
  for (const e of events) {
    if (e.kind !== "alert.raised") continue;
    const reading = readings.find((r) => r.entityId === e.data.entity_id && series.includes(r.key));
    const t = Date.parse(e.ts);
    const title = typeof e.data.title === "string" ? e.data.title : "";
    if (reading && title && Number.isFinite(t) && !banded(reading.key, t))
      notes.push({ at: t, series: reading.key, text: title });
  }
  return notes.sort((a, b) => a.at - b.at);
}

/** Values in the units the legend shows them in (Settings › Display): EC in ppm when chosen, °C as
 * °F; storage stays mS/cm and °C. Values are not rounded past the conversion's own float noise. */
export function inDisplayUnits(
  unit: Unit,
  values: readonly (number | null)[],
): { unit: string; values: (number | null)[] } {
  const { ec, temp } = getDisplayUnits();
  const map = (convert: (v: number) => number) =>
    values.map((v) => (v === null ? null : Number(convert(v).toPrecision(12))));
  if (unit === "mS/cm" && ec !== "mS/cm") return { unit: "ppm", values: map((v) => v * (ec === "ppm500" ? 500 : 700)) };
  if (unit === "°C" && temp === "F") return { unit: "°F", values: map((v) => (v * 9) / 5 + 32) };
  return { unit, values: [...values] };
}

const csvField = (text: string) => (/[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text);
/** The selected series as a table: one row per grid step on the room's clock, one column per series
 * ("Zone 1 VWC (%)"), values as recorded (no rounding), blank where there is no reading. */
export function explorerCsv(
  times: readonly number[],
  columns: readonly { label: string; unit: string; values: readonly (number | null)[] }[],
  timeZone: string,
): string {
  const head = ["Time", ...columns.map((c) => `${c.label} (${c.unit})`)].map(csvField).join(",");
  const rows = times.map((t, i) =>
    [
      `${dayKey(t, timeZone)} ${wallHhmm(t, timeZone)}`,
      ...columns.map((c) => (c.values[i] == null ? "" : String(c.values[i]))),
    ]
      .map(csvField)
      .join(","),
  );
  return [head, ...rows].join("\n") + "\n";
}

/** One series the explorer can chart: a chip in its group (a zone, Feed, Tank, Room) and a line on
 * the chart of its measure. */
export interface ExplorerSeries {
  key: string;
  entityId: string;
  /** The chip group: "zone:1", "feed", "tank", "room". */
  group: string;
  /** The group's name, which is also the line's name on its chart: "Zone 1", "Feed". */
  groupLabel: string;
  chip: string;
  /** The chart it is drawn on, and that chart's title. */
  chart: string;
  chartTitle: string;
  unit: Unit;
  color: string;
  zone: number | null;
  kind: SensorKind;
}
/** Zones keep one colour on every chart; Feed, Tank and the room have their own. */
const ZONE_COLORS = ["#1e88e5", "#d84f7a", "#5c8f3a", "#8e5cd9", "#e08a00", "#00897b"];
const GROUP_COLORS: Record<string, string> = { feed: "#3a9aa5", tank: "#3f7fbf", room: "#c0763a" };
const OTHER: Record<string, { group: "feed" | "tank" | "room"; chip: string }> = {
  "Feed EC": { group: "feed", chip: "EC" },
  "Feed pH": { group: "feed", chip: "pH" },
  "Tank level": { group: "tank", chip: "Level" },
  "Tank EC": { group: "tank", chip: "EC" },
  "Tank pH": { group: "tank", chip: "pH" },
  "Tank temperature": { group: "tank", chip: "Temp" },
  "Air temperature": { group: "room", chip: "Air temp" },
  Humidity: { group: "room", chip: "Humidity" },
  VPD: { group: "room", chip: "VPD" },
  CO2: { group: "room", chip: "CO2" },
  PPFD: { group: "room", chip: "PPFD" },
};
const GROUP_NAMES = { feed: "Feed", tank: "Tank", room: "Room" } as const;
/** The room's series in chip order: each zone's combined VWC, EC and root temperature, then the
 * feed, the tank and the room's climate. A probe of its own is left to the zone's probe detail. */
export function explorerSeries(room: RoomView, sensors: readonly ExplorerSensor[]): ExplorerSeries[] {
  const list: ExplorerSeries[] = [];
  room.zones.forEach((zone, index) => {
    const color = ZONE_COLORS[index % ZONE_COLORS.length];
    for (const sensor of sensors.filter((s) => s.zone === zone.id)) {
      const fused = sensor.entityId === zone.vwc.entityId || sensor.entityId === zone.ec.entityId;
      const root = sensor.kind === "climate";
      if (!fused && !root) continue;
      const ec = sensor.kind === "ec" ? (sensor.label.includes("bulk EC") ? "Bulk EC" : "Pore EC") : null;
      const chip = root ? "Root temp" : ec ?? "VWC";
      list.push({
        key: sensor.entityId,
        entityId: sensor.entityId,
        group: `zone:${zone.id}`,
        groupLabel: zone.name,
        chip,
        chart: root ? "root" : sensor.kind,
        chartTitle: root ? "Root temp" : chip,
        unit: sensor.unit,
        color,
        zone: zone.id,
        kind: sensor.kind,
      });
    }
  });
  for (const [label, { group, chip }] of Object.entries(OTHER))
    for (const sensor of sensors)
      if (sensor.zone === null && sensor.label === label)
        list.push({
          key: sensor.entityId,
          entityId: sensor.entityId,
          group,
          groupLabel: GROUP_NAMES[group],
          chip,
          chart: sensor.label,
          chartTitle: sensor.label,
          unit: sensor.unit,
          color: GROUP_COLORS[group],
          zone: null,
          kind: sensor.kind,
        });
  // A room whose zones mix pore and bulk EC titles that chart plainly "EC".
  const ecTitles = new Set(list.filter((s) => s.chart === "ec").map((s) => s.chartTitle));
  if (ecTitles.size > 1) for (const s of list) if (s.chart === "ec") s.chartTitle = "EC";
  return list;
}
/** What the explorer opens with: every zone's VWC and EC, the feed EC and the tank level. */
export function defaultExplorerSeries(series: readonly ExplorerSeries[]): string[] {
  return series
    .filter((s) => s.chart === "vwc" || s.chart === "ec" || s.chart === "Feed EC" || s.chart === "Tank level")
    .map((s) => s.key);
}
