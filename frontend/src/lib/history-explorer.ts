/** The zone page's history explorer: which sensors a room has, the range a grower picks, recorded
 * states reduced to a fixed time grid (so a month of many sensors stays a few hundred points each),
 * and the previous run laid over this one by grow day. Pure: the component fetches and draws. */
import { addDays, dateInZone, daysBetween, midnight, wallTime } from "./comparison";
import type { RunRecord } from "./comparison-types";
import { growDay, type TimelineRow } from "./day-timeline";
import { descriptor } from "./model";
import type { SteCopy } from "./ste-copy";
import type { RoomView, States } from "./types";

const DAY = 86_400_000;
const HOUR = 3_600_000;
/** The longest range the explorer reads: one request per day, two at a time. */
export const MAX_RANGE_DAYS = 180;

export type Unit = "%" | "mS/cm" | "°C" | "°F" | "kPa" | "pH";
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

export type Preset = "today" | "growday" | "3d" | "7d" | "14d" | "run" | "custom";
export const PRESETS: { id: Exclude<Preset, "custom">; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "growday", label: "Grow-day" },
  { id: "3d", label: "3 d" },
  { id: "7d", label: "7 d" },
  { id: "14d", label: "14 d" },
  { id: "run", label: "This run" },
];
export interface Choice {
  preset: Preset;
  /** A custom range, epoch ms. */
  from: number | null;
  to: number | null;
  /** The ticked sensors' entity ids; null: the zone's own VWC and EC. */
  sensors: string[] | null;
  compare: boolean;
  /** The grow compared with: a run's id; null for the last grow before this one. */
  compareRun: string | null;
  shots: boolean;
  phases: boolean;
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
};

/** The explorer's choice from the query of the page's hash (`#/zone/1?range=7d&s=...`). */
export function readChoice(hash: string): Choice {
  const query = new URLSearchParams(hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "");
  const range = query.get("range") ?? "";
  const from = Date.parse(query.get("from") ?? ""),
    to = Date.parse(query.get("to") ?? "");
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
    compare: query.get("compare") === "1",
    compareRun: /^[a-zA-Z0-9_-]{1,64}$/.test(query.get("vs") ?? "") ? query.get("vs") : null,
    shots: query.get("shots") !== "0",
    phases: query.get("phases") !== "0",
  };
}

/** The hash with the explorer's choice in its query; other query keys stay. */
export function writeChoice(hash: string, choice: Choice): string {
  const [path, rest = ""] = hash.split("?");
  const query = new URLSearchParams(rest);
  for (const key of ["range", "from", "to", "s", "compare", "vs", "shots", "phases"]) query.delete(key);
  query.set("range", choice.preset);
  if (choice.preset === "custom" && choice.from !== null && choice.to !== null) {
    query.set("from", new Date(choice.from).toISOString());
    query.set("to", new Date(choice.to).toISOString());
  }
  if (choice.sensors) query.set("s", choice.sensors.join(","));
  if (choice.compare) query.set("compare", "1");
  if (choice.compare && choice.compareRun) query.set("vs", choice.compareRun);
  if (!choice.shots) query.set("shots", "0");
  if (!choice.phases) query.set("phases", "0");
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
  sensors: {
    label: "Sensors",
    copy: {
      tooltip:
        "The sensors of this room. Each unit has its own axis. A sensor that Home Assistant does not have is not in the list.",
    } satisfies SteCopy,
  },
} as const;
