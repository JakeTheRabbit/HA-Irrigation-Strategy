import { addDays, dateInZone, viewerTimeZone, wallTime } from "./comparison";
import { ageText } from "./controller-health";
import { descriptor } from "./model";
import { smoothRecorded, type RecordedPoint } from "./planning-curve";
import { drybackId } from "./published";
import type { RoomView, States } from "./types";
import { growerWords } from "./words";

/** One recorded state of an entity: epoch ms, and attributes only where they were asked for. */
export interface TimelineRow {
  state: string;
  time: number;
  attributes?: Record<string, unknown>;
}
export type TimelineRows = Record<string, TimelineRow[]>;
/** One grow-day of recorder history: every state change of `entityIds`, and every change of
 * `attributeIds` with its attributes (the controller's decision, whose lists of fired and blocked
 * zones change while its state often does not). */
export interface TimelineRequest {
  entityIds: string[];
  attributeIds: string[];
  start: number;
  end: number;
}
export interface Span {
  start: number;
  end: number;
}
export interface GrowDay extends Span {
  lightsOff: number;
}
export interface PhaseBand extends Span {
  phase: string;
}
export interface Shot extends Span {
  /** The valve is still open at the end of the window. */
  open: boolean;
  /** The phase and rule the controller fired it for; null when it posted none (a hand-opened valve). */
  phase: string | null;
  reason: string | null;
}
export interface Block extends Span {
  /** "cap": the daily budget is spent. "block": the engine refused (high EC). "hold": a gate held a
   * shot the engine wanted (kill switch, dosing, feed water, plan, zone disabled...). */
  kind: "cap" | "block" | "hold";
  text: string;
  open: boolean;
}
export interface SetpointChange {
  entityId: string;
  time: number;
  from: number;
  to: number;
}
export interface Reading {
  time: number;
  value: number;
}
export interface Level extends Span {
  value: number;
}
export interface NextShot {
  /** When the next shot is expected, or null when nothing honest can be said. */
  at: number | null;
  /** How `at` was worked out, or why there is none. */
  basis:
    | "controller"
    | "due"
    | "p1-interval"
    | "p0-wait"
    | "firing"
    | "held"
    | "night"
    | "late"
    | "no-estimate"
    | "no-reading"
    | "ramp-done"
    | "unknown";
  /** Why the controller has no estimate ("no-estimate"). */
  reason?: string;
}

const numberOf = (state: string): number | null => {
  const text = state.trim();
  return text && Number.isFinite(Number(text)) ? Number(text) : null;
};

/** What a room's day timeline reads, where it exists: each zone's phase, valve, VWC and pore EC
 * probes, the room's setpoints, and the controller's decision with its attributes. With `zoneId`,
 * only that zone's (and the room's own setpoints). */
export function timelineEntities(room: RoomView, states: States, zoneId?: number) {
  const root = `sensor.crop_steering_${room.room.prefix}`;
  const exists = (id: string | null): id is string => !!id && !!states[id];
  const zones = room.zones
    .filter((zone) => zoneId === undefined || zone.id === zoneId)
    .map((zone) => ({
      id: zone.id,
      phase: `${root}zone_${zone.id}_phase`,
      valve: zone.valveEntity,
      vwc: zone.vwc.entityId,
      ec: zone.ec.entityId,
    }));
  const decision = `${root}current_decision`;
  const ids = [
    ...zones.flatMap((zone) => [zone.phase, zone.valve, zone.vwc, zone.ec]),
    ...room.settings
      .filter(
        (setting) =>
          zoneId === undefined || setting.zoneId === undefined || setting.zoneId === zoneId,
      )
      .map((setting) => setting.entityId),
  ];
  // One zone's: also the controller's dryback, with the peak it was measured from.
  const dryback = zoneId === undefined ? null : drybackId(room.room.prefix, zoneId);
  return {
    zones,
    entityIds: [...new Set(ids.filter(exists))].sort(),
    attributeIds: [decision, dryback].filter(exists),
  };
}

/** The grow-day `now` falls in: lights-on to the next lights-on, on the clock of `timeZone`
 * (Home Assistant's, as the controller keeps it; the browser's where that is unknown), as the plan
 * graph folds recorded days. Null without a usable photoperiod. */
export function growDay(
  lightsOn: number | null,
  lightsOff: number | null,
  now: number,
  timeZone = viewerTimeZone(),
): GrowDay | null {
  const hour = (value: number | null): value is number =>
    value !== null && value >= 0 && value < 24;
  if (!hour(lightsOn) || !hour(lightsOff) || lightsOn === lightsOff || !Number.isFinite(now))
    return null;
  const at = (day: string, offset: number, value: number) =>
    wallTime(addDays(day, offset), Math.round(value * 60), timeZone);
  const today = dateInZone(now, timeZone);
  const start = at(today, 0, lightsOn) > now ? at(today, -1, lightsOn) : at(today, 0, lightsOn);
  const first = dateInZone(start, timeZone);
  return {
    start,
    lightsOff: at(first, lightsOff > lightsOn ? 0 : 1, lightsOff),
    end: at(first, 1, lightsOn),
  };
}

/** Each phase a zone was in, clipped to [from, to]. Equal phases in a row join; a state that is not
 * a phase (unavailable while Home Assistant restarts) leaves a gap. */
export function phaseBands(rows: TimelineRow[] = [], from: number, to: number): PhaseBand[] {
  const bands: PhaseBand[] = [];
  rows.forEach((row, index) => {
    const start = Math.max(row.time, from),
      end = Math.min(rows[index + 1]?.time ?? to, to);
    if (!/^P[0-3]$/.test(row.state) || end <= start) return;
    const last = bands.at(-1);
    if (last?.phase === row.state && last.end === start) last.end = end;
    else bands.push({ phase: row.state, start, end });
  });
  return bands;
}
export const phaseAt = (bands: PhaseBand[], time: number): string | null =>
  bands.find((band) => band.start <= time && time < band.end)?.phase ?? null;

const ENTRY = /^Z(\d+) (\S+) (.*)$/;
/** This zone's entry ("Z<zone> <phase> <reason>") in one of the lists a decision row carries. */
function entry(row: TimelineRow, list: "fired" | "blocked", zoneId: number) {
  const items = row.attributes?.[list];
  if (!Array.isArray(items)) return null;
  for (const item of items) {
    const match = typeof item === "string" ? item.match(ENTRY) : null;
    if (match && Number(match[1]) === zoneId) return { phase: match[2], text: match[3].trim() };
  }
  return null;
}

/** Each time a zone's valve was open. The controller posts what it fired at the end of the loop
 * that fired it (after the valve closed, and before any other decision), so the first decision
 * row from the valve closing names the phase and rule. The recorded phase changes in that same
 * post, which is why a first P1 shot can sit at the end of the P0 band. */
export function valveShots(
  valve: TimelineRow[] = [],
  decisions: TimelineRow[] = [],
  zoneId: number,
  from: number,
  to: number,
): Shot[] {
  const shots: Shot[] = [];
  valve.forEach((row, index) => {
    const next = valve[index + 1];
    const start = Math.max(row.time, from),
      end = Math.min(next?.time ?? to, to);
    if (row.state !== "on" || end <= start) return;
    const last = shots.at(-1);
    if (last?.end === start) Object.assign(last, { end, open: !next });
    else shots.push({ start, end, open: !next, phase: null, reason: null });
  });
  for (const shot of shots) {
    const row = decisions.find((item) => item.time >= shot.end);
    const fired = row && row.time - shot.end <= 60 * 60_000 && entry(row, "fired", zoneId);
    if (fired) Object.assign(shot, { phase: fired.phase, reason: growerWords(fired.text) });
  }
  return shots;
}

/** The controller posts a phase change after the loop that made it, once that loop's shots are
 * done, so the first shots of a phase can sit before it in the record. A shot the controller named
 * with the phase recorded next, closed before that post, moves the phase's start back to it. */
export function alignBands(bands: PhaseBand[], shots: Shot[]): PhaseBand[] {
  const aligned = bands.map((band) => ({ ...band }));
  for (const shot of shots) {
    const index = aligned.findIndex((band) => band.start <= shot.start && shot.start < band.end);
    const band = aligned[index],
      next = aligned[index + 1];
    if (
      !band ||
      !next ||
      !shot.phase ||
      band.phase === shot.phase ||
      next.phase !== shot.phase ||
      band.end !== next.start ||
      shot.end > next.start ||
      next.start - shot.end > 60 * 60_000
    )
      continue;
    band.end = shot.start;
    next.start = shot.start;
  }
  return aligned.filter((band) => band.end > band.start);
}

const blockKind = (text: string): Block["kind"] =>
  /daily-cap/i.test(text) ? "cap" : /\bBLOCK\b/.test(text) ? "block" : "hold";
/** What held a zone back: the entries the controller listed as blocked for it, one interval per
 * unbroken run of the same hold (numbers in the text, such as litres used, may change within it). */
export function zoneBlocks(
  decisions: TimelineRow[] = [],
  zoneId: number,
  from: number,
  to: number,
): Block[] {
  const blocks: Block[] = [];
  let current: { key: string; block: Block } | null = null;
  for (const row of decisions) {
    const held = entry(row, "blocked", zoneId);
    const kind = held && blockKind(held.text);
    const key = held ? `${kind}|${held.text.replace(/\d+(?:\.\d+)?/g, "#")}` : "";
    if (current && current.key === key) continue;
    if (current) Object.assign(current.block, { end: Math.min(row.time, to), open: false });
    current = null;
    if (held && kind && row.time < to) {
      current = {
        key,
        block: { kind, text: held.text, start: Math.max(row.time, from), end: to, open: true },
      };
      blocks.push(current.block);
    }
  }
  return blocks.filter((block) => block.end > block.start);
}

/** Every change of a numeric setpoint inside the window. The unavailable reading a restart
 * records between two equal values is not a change. */
export function setpointChanges(
  rows: TimelineRows,
  ids: string[],
  from: number,
  to: number,
): SetpointChange[] {
  const changes: SetpointChange[] = [];
  for (const entityId of ids) {
    let last: number | null = null;
    for (const row of rows[entityId] ?? []) {
      const value = numberOf(row.state);
      if (value === null) continue;
      if (last !== null && value !== last && row.time > from && row.time <= to)
        changes.push({ entityId, time: row.time, from: last, to: value });
      last = value;
    }
  }
  return changes.sort((a, b) => a.time - b.time);
}

export function readings(rows: TimelineRow[] = [], from: number, to: number): Reading[] {
  return rows.flatMap((row) => {
    const value = numberOf(row.state);
    return value !== null && row.time >= from && row.time <= to ? [{ time: row.time, value }] : [];
  });
}
/** A numeric entity's value over the window, as steps; unreadable stretches are gaps. */
export function levels(rows: TimelineRow[] = [], from: number, to: number): Level[] {
  const steps: Level[] = [];
  rows.forEach((row, index) => {
    const value = numberOf(row.state),
      start = Math.max(row.time, from),
      end = Math.min(rows[index + 1]?.time ?? to, to);
    if (value === null || end <= start) return;
    const last = steps.at(-1);
    if (last?.value === value && last.end === start) last.end = end;
    else steps.push({ value, start, end });
  });
  return steps;
}

/** A numeric entity's value in force at `time`: the last number recorded at or before it. A
 * restart's unavailable reading in between changes nothing. */
export function valueAt(rows: TimelineRow[] = [], time: number): number | null {
  let value: number | null = null;
  for (const row of rows) {
    if (row.time > time) break;
    value = numberOf(row.state) ?? value;
  }
  return value;
}

/** What the earlier grow-days are read from: each zone's VWC probe and valve, the lights hours
 * (a changed schedule moves a day's lights-on), the room switch (a room that was off has nothing to
 * compare) and, with its attributes, the room descriptor (its setup revision). */
export function earlierEntities(room: RoomView, states: States, zoneId?: number) {
  const root = `crop_steering_${room.room.prefix}`;
  const exists = (id: string | null | undefined): id is string => !!id && !!states[id];
  const ids = [
    ...room.zones
      .filter((zone) => zoneId === undefined || zone.id === zoneId)
      .flatMap((zone) => [zone.vwc.entityId, zone.valveEntity]),
    `number.${root}lights_on_hour`,
    `number.${root}lights_off_hour`,
    `switch.${root}room_active`,
  ];
  const config = descriptor(states, room.room)?.entity_id;
  return {
    entityIds: [...new Set(ids.filter(exists))].sort(),
    attributeIds: exists(config) ? [config] : [],
  };
}

/** The `count` grow-days before `day`, latest first, each from its lights-on to the next day's.
 * `hours(time)` gives the lights hours in force at a time. A day starts at the last lights-on at
 * least half a day before the next one, at the hour in force as it came on: a changed schedule
 * or a clock change makes a day longer or shorter than 24 hours. */
export function earlierDays(
  day: GrowDay,
  count: number,
  hours: (time: number) => { on: number | null; off: number | null },
  timeZone = viewerTimeZone(),
): GrowDay[] {
  const days: GrowDay[] = [];
  for (let end = day.start; days.length < count;) {
    const middle = end - 12 * 3_600_000;
    const { on, off } = hours(middle);
    let earlier = growDay(on, off, middle, timeZone);
    // The schedule changed after this day's lights-on: it came on at the hour in force then.
    const then = earlier && hours(earlier.start);
    const moved = then && then.on !== on && growDay(then.on, then.off, middle, timeZone);
    if (moved && hours(moved.start).on === then.on) earlier = moved;
    if (!earlier) break;
    days.push({ start: earlier.start, lightsOff: Math.min(earlier.lightsOff, end), end });
    end = earlier.start;
  }
  return days;
}

/** Recorder rows from consecutive requests joined into one history per entity, in time order. */
export function joinRows(parts: readonly TimelineRows[]): TimelineRows {
  const rows: TimelineRows = {};
  for (const part of parts)
    for (const [id, list] of Object.entries(part)) (rows[id] ??= []).push(...list);
  for (const list of Object.values(rows)) list.sort((a, b) => a.time - b.time);
  return rows;
}

export interface DayTrace {
  day: GrowDay;
  /** The zone's VWC in ten-minute medians, by hours since that day's own lights-on. */
  points: RecordedPoint[];
  shots: Shot[];
  /** The room was switched off at some point that day: its line is still drawn, but it is kept
   * out of the typical day and the zone's dry-down rates. */
  roomOff?: boolean;
}
/** One earlier grow-day of a zone, to compare today with. Null when there is nothing to draw:
 * under two readings. A room switched off during it still draws its line, marked `roomOff`. */
export function dayTrace(
  rows: TimelineRows,
  ids: { vwc: string | null; valve: string | null; active: string | null },
  zoneId: number,
  day: GrowDay,
): DayTrace | null {
  const active = (ids.active && rows[ids.active]) || [];
  const off = active.some(
    (row, index) =>
      row.state === "off" &&
      row.time < day.end &&
      (active[index + 1]?.time ?? Infinity) > day.start,
  );
  const points = smoothRecorded(readings(ids.vwc ? rows[ids.vwc] : [], day.start, day.end)).map(
    (point) => ({ ...point, hour: (point.time - day.start) / 3_600_000 }),
  );
  if (points.length < 2) return null;
  const shots = ids.valve ? valveShots(rows[ids.valve], [], zoneId, day.start, day.end) : [];
  return off ? { day, points, shots, roomOff: true } : { day, points, shots };
}

/** The room's setup revision in force at `time`, from its descriptor's recorded attributes. A
 * restart can record the descriptor without them, which changes nothing. */
export function revisionAt(rows: TimelineRow[] = [], time: number): number | null {
  let revision: number | null = null;
  for (const row of rows) {
    if (row.time > time) break;
    const value = row.attributes?.setup_revision;
    if (typeof value === "number") revision = value;
  }
  return revision;
}

/** The week before `day` as the room lived it, from the rows of `earlierEntities`: each grow-day
 * cut at the lights-on recorded in force then (`hours` where none was recorded), every zone's
 * trace of each day (null where there is nothing to draw), and the setup revision as each day
 * began. */
export function earlierTraces(
  rows: TimelineRows,
  room: RoomView,
  day: GrowDay,
  hours: { on: number | null; off: number | null },
  config?: string,
  timeZone = viewerTimeZone(),
) {
  const root = `crop_steering_${room.room.prefix}`;
  const recorded = (key: "on" | "off", time: number) =>
    valueAt(rows[`number.${root}lights_${key}_hour`], time) ?? hours[key];
  const days = earlierDays(
    day,
    7,
    (time) => ({ on: recorded("on", time), off: recorded("off", time) }),
    timeZone,
  );
  const active = `switch.${root}room_active`;
  return {
    traces: new Map(
      room.zones.map((zone) => [
        zone.id,
        days.map((past) =>
          dayTrace(
            rows,
            { vwc: zone.vwc.entityId, valve: zone.valveEntity, active },
            zone.id,
            past,
          ),
        ),
      ]),
    ),
    setup: days.map((past) => revisionAt(config ? rows[config] : [], past.start)),
  };
}

/** VWC `hour` hours after lights-on: read between the readings either side when they are no more
 * than `within` hours apart, else the nearest one if it is within half of that. */
export function atHour(
  points: readonly RecordedPoint[],
  hour: number,
  within = 1 / 3,
): number | null {
  let low = 0,
    high = points.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (points[middle].hour < hour) low = middle + 1;
    else high = middle;
  }
  const [a, b] = [points[low - 1], points[low]];
  if (a && b && b.hour - a.hour <= within)
    return a.value + ((b.value - a.value) * (hour - a.hour)) / (b.hour - a.hour);
  const near = [a, b].find((point) => point && Math.abs(point.hour - hour) <= within / 2);
  return near ? near.value : null;
}

/** When VWC first rose to `level`, in hours since lights-on: the first reading at or above it after
 * one below it. A day that never went below it was there from its first reading; one that never
 * came up to it never reached it (null). */
export function reachedHour(points: readonly RecordedPoint[], level: number): number | null {
  let below = false;
  for (const point of points) {
    if (point.value < level) below = true;
    else if (below) return point.hour;
  }
  return below || !points.length ? null : points[0].hour;
}

/** Seconds the valve was open from lights-on (`start`) until `hour` hours later. */
export function openSeconds(shots: readonly Shot[], start: number, hour: number): number {
  const until = start + hour * 3_600_000;
  return (
    shots.reduce((sum, shot) => sum + Math.max(0, Math.min(shot.end, until) - shot.start), 0) / 1000
  );
}

const quantile = (sorted: readonly number[], q: number) => {
  const at = (sorted.length - 1) * q,
    below = Math.floor(at);
  return at === below
    ? sorted[below]
    : sorted[below] + (sorted[below + 1] - sorted[below]) * (at - below);
};
const middle = (values: number[]) =>
  values.length
    ? quantile(
        [...values].sort((a, b) => a - b),
        0.5,
      )
    : null;
export interface TypicalPoint {
  hour: number;
  low: number;
  median: number;
  high: number;
}
/** The typical day: every ten minutes after lights-on, the median VWC of the recorded days and
 * their middle half (25th to 75th percentile), wherever three or more of them were recorded. */
export function typicalDay(days: readonly (readonly RecordedPoint[])[]): TypicalPoint[] {
  const step = 1 / 6,
    last = Math.max(0, ...days.map((points) => points.at(-1)?.hour ?? 0));
  const typical: TypicalPoint[] = [];
  for (let index = 0; index * step <= last; index++) {
    const hour = index * step;
    const values = days.flatMap((points) => atHour(points, hour) ?? []).sort((a, b) => a - b);
    if (values.length >= 3)
      typical.push({
        hour,
        low: quantile(values, 0.25),
        median: quantile(values, 0.5),
        high: quantile(values, 0.75),
      });
  }
  return typical;
}

export interface Comparison {
  /** VWC now less theirs at the same hour since lights-on; null when they have no reading then. */
  vwc: number | null;
  /** When they reached the P1 target: the median day's time, null when the median day did not
   * reach it; and how many of them did. */
  reached: number | null;
  reachedBy: number;
  /** Valve-open seconds from lights-on to this hour since lights-on. */
  seconds: number;
}
/** Today against earlier grow-days at `hour` hours since lights-on: one day (yesterday) or the
 * median of several (the typical day). Null without a day to compare with. */
export function compareDays(
  days: readonly DayTrace[],
  hour: number,
  vwc: number | null,
  target: number | null,
): Comparison | null {
  if (!days.length) return null;
  const then = middle(days.flatMap((trace) => atHour(trace.points, hour) ?? []));
  // A day that never reached the target counts as the latest of all.
  const reached =
    target === null ? [] : days.map((trace) => reachedHour(trace.points, target) ?? Infinity);
  const median = middle(reached);
  return {
    vwc: vwc === null || then === null ? null : vwc - then,
    reached: median !== null && Number.isFinite(median) ? median : null,
    reachedBy: reached.filter(Number.isFinite).length,
    seconds: middle(days.map((trace) => openSeconds(trace.shots, trace.day.start, hour)))!,
  };
}

export type TargetKey =
  | "dryback_target"
  | "p1_target_vwc"
  | "p2_vwc_threshold"
  | "p3_emergency_vwc_threshold"
  | "field_capacity";
const PHASE_TARGET: Record<string, TargetKey> = {
  P0: "dryback_target",
  P1: "p1_target_vwc",
  P2: "p2_vwc_threshold",
  P3: "p3_emergency_vwc_threshold",
};
export interface TargetStep extends Level {
  phase: string;
}
/** Auto setpoints' planned stop of the maintenance shots (the zone's p2_stop, local "HH:MM") on the
 * grow day: the first such time after lights-on, or null without one. */
export function maintenanceStop(stop: string | null, day: Span): number | null {
  const match = stop && /^(\d\d):(\d\d)$/.exec(stop);
  if (!match) return null;
  const on = new Date(day.start);
  const minutes = (+match[1] * 60 + +match[2] - on.getHours() * 60 - on.getMinutes() + 1440) % 1440;
  return day.start + minutes * 60_000;
}
/** The maintenance band's segments from that stop on are `stopped`: their floor is no trigger the day
 * waters at, only a top-up under it. A segment set within the minute before the stop still counts. */
export function stoppedSegments<T extends Span>(
  segments: readonly T[],
  stop: number | null,
): (T & { stopped: boolean })[] {
  return segments.map((segment) => ({
    ...segment,
    stopped: stop !== null && segment.start >= stop - 60_000,
  }));
}
/** What the controller aims at in each phase, as steps along `bands` (the recorded phases, then the
 * projected ones): in P0 the dryback target as a VWC level below the highest reading since P0
 * began, in P1 the P1 target, in P2 the P2 threshold, in P3 the emergency floor. `setpoint` gives
 * one setpoint over a span as steps: where it was changed, or a plan's value. */
export function phaseTargets(
  bands: readonly PhaseBand[],
  setpoint: (key: TargetKey, span: Span) => Level[],
  points: readonly Reading[],
): TargetStep[] {
  let since = -Infinity;
  return bands.flatMap((band, index) => {
    // P0's peak counts from when the phase began, through a recorded band and its projected rest.
    const before = bands[index - 1];
    if (band.phase === "P0" && !(before?.phase === "P0" && before.end === band.start))
      since = band.start;
    return setpoint(PHASE_TARGET[band.phase], band).flatMap((level) => {
      if (band.phase !== "P0") return [{ ...level, phase: band.phase }];
      const peak = Math.max(
        ...points
          .filter((point) => point.time >= since && point.time <= level.end)
          .map((point) => point.value),
      );
      return Number.isFinite(peak)
        ? [{ ...level, value: peak * (1 - level.value / 100), phase: "P0" }]
        : [];
    });
  });
}

/** A target setpoint over a span as steps, resolved as the controller resolves it: while a plan is
 * armed, its snapshot's value (in `parameters`, from buildSetpointPreview); otherwise the number
 * `entity` names (the zone's own, else the room's) as recorded, so a value changed today steps
 * where it changed. The value in force now where nothing was recorded. */
export function setpointSteps(
  rows: TimelineRows,
  parameters: Record<string, number>,
  entity: (key: TargetKey) => string | null,
  planned: boolean,
) {
  return (key: TargetKey, span: Span): Level[] => {
    const value = parameters[key];
    if (!Number.isFinite(value)) return [];
    const id = planned ? null : entity(key);
    const steps = id ? levels(rows[id], span.start, span.end) : [];
    return steps.length ? steps : [{ value, start: span.start, end: span.end }];
  };
}

export const NOT_REPORTING = "the controller is not reporting";
/** Why the rest of a zone's day is not projected, or null when it is. A zone the controller is not
 * watering has no future to claim; one it has stopped reporting on says only when it last did. */
export function unprojected(
  stopped: string | null,
  reportedAt: number | null,
  now: number,
): string | null {
  if (stopped !== NOT_REPORTING) return stopped && `not watering: ${stopped}`;
  return `no projection: ${reportedAt === null ? "no report from the controller" : `last report ${ageText(now - reportedAt)} ago`}`;
}

/** When a zone should fire next, only as far as the engine's own rules say: P0 ends by its
 * maximum wait, P1 fires every interval until the ramp ceiling, and in P2 the controller publishes
 * its own estimate of the top-up (`estimate`, published.ts), which is shown as it is. Nothing is
 * estimated while a shot runs, a hold is open, or after lights-off. */
export function nextShot(
  zone: {
    phase: string | null;
    /** When the current phase began. */
    since: number | null;
    held: Block | null;
    /** Today's last shot, if any. */
    lastShot: Shot | null;
    /** The live VWC, null when the probe is unavailable or stale. */
    vwc: number | null;
    /** The controller's P2 estimate (publishedNextIrrigation), or why it has none. */
    estimate: { at: number | null; reason: string | null };
    ceiling: number | null;
    /** Minutes between P1 shots, and the P0 maximum wait. */
    interval: number | null;
    maxWait: number | null;
  },
  day: GrowDay,
  now: number,
): NextShot {
  const { phase, lastShot } = zone;
  if (lastShot?.open) return { at: null, basis: "firing" };
  if (zone.held) return { at: null, basis: "held" };
  if (phase === "P3" || now >= day.lightsOff) return { at: null, basis: "night" };
  if (phase === "P0")
    return zone.since !== null && zone.maxWait !== null
      ? { at: Math.max(now, zone.since + zone.maxWait * 60_000), basis: "p0-wait" }
      : { at: null, basis: "unknown" };
  if (zone.vwc === null) return { at: null, basis: "no-reading" };
  if (phase === "P1") {
    if (zone.ceiling !== null && zone.vwc >= zone.ceiling) return { at: null, basis: "ramp-done" };
    if (zone.interval === null) return { at: null, basis: "unknown" };
    const at = lastShot ? lastShot.end + zone.interval * 60_000 : now;
    return { at: Math.max(now, at), basis: "p1-interval" };
  }
  if (phase !== "P2") return { at: null, basis: "unknown" };
  const { at, reason } = zone.estimate;
  if (at === null) return { at: null, basis: "no-estimate", reason: reason ?? undefined };
  if (at <= now) return { at: now, basis: "due" };
  return at < day.lightsOff ? { at, basis: "controller" } : { at: null, basis: "late" };
}

const sameAttributes = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
/** Live states appended to a loaded day, so the day is downloaded once: a row for each entity whose
 * state (and, for `attributeIds`, attributes) changed after its last row. Returns `rows` itself when
 * nothing did. */
export function appendLive(
  rows: TimelineRows,
  states: States,
  request: Pick<TimelineRequest, "entityIds" | "attributeIds">,
): TimelineRows {
  let next: TimelineRows | null = null;
  for (const id of [...request.entityIds, ...request.attributeIds]) {
    const entity = states[id],
      detailed = request.attributeIds.includes(id);
    if (!entity) continue;
    const time = Date.parse(
      (detailed ? entity.last_updated : entity.last_changed) ?? entity.last_updated ?? "",
    );
    const held = (next ?? rows)[id] ?? [],
      last = held.at(-1);
    if (!Number.isFinite(time) || (last && time <= last.time)) continue;
    if (
      last?.state === entity.state &&
      (!detailed || sameAttributes(last.attributes, entity.attributes))
    )
      continue;
    next ??= { ...rows };
    next[id] = [
      ...held,
      { state: entity.state, time, ...(detailed ? { attributes: entity.attributes } : {}) },
    ];
  }
  return next ?? rows;
}

/** "1 h 12 min", "45 min", "2 min 25 s", "40 s". */
export function duration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 10) return seconds % 60 ? `${minutes} min ${seconds % 60} s` : `${minutes} min`;
  const rounded = Math.round(seconds / 60);
  return rounded < 60
    ? `${rounded} min`
    : `${Math.floor(rounded / 60)} h${rounded % 60 ? ` ${rounded % 60} min` : ""}`;
}
