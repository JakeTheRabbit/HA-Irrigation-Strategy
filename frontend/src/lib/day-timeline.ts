import { ageText } from "./controller-health";
import { descriptor } from "./model";
import { smoothRecorded, type RecordedPoint } from "./planning-curve";
import type { RoomView, States } from "./types";

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
export interface DryDown {
  /** VWC percentage points per hour, positive while the zone dries. */
  rate: number;
  /** The fitted reading the projection starts from. */
  from: Reading;
  /** When VWC reaches the threshold at that rate. */
  at: number;
}
export interface NextShot {
  /** When the next shot is expected, or null when nothing honest can be said. */
  at: number | null;
  /** How `at` was worked out, or why there is none. */
  basis:
    | "dry-down"
    | "due"
    | "p1-interval"
    | "p0-wait"
    | "firing"
    | "held"
    | "night"
    | "late"
    | "settling"
    | "no-dry-down"
    | "no-reading"
    | "ramp-done"
    | "unknown";
  /** The fitted dry-down, drawn as the dashed rest-of-day line even when it misses lights-off. */
  fit?: DryDown;
}

/** Readings used for the dry-down: the last hour, from a quarter of an hour after the last shot
 * ended (the wet-up is still arriving before that), over at least 15 minutes. */
export const DRY_DOWN = {
  windowMs: 60 * 60_000,
  settleMs: 15 * 60_000,
  minSpanMs: 15 * 60_000,
  minPoints: 5,
  minRate: 0.1,
};

const numberOf = (state: string): number | null => {
  const text = state.trim();
  return text && Number.isFinite(Number(text)) ? Number(text) : null;
};

/** What a room's day timeline reads, where it exists: each zone's phase, valve and VWC probe, the
 * room's setpoints, and the controller's decision with its attributes. */
export function timelineEntities(room: RoomView, states: States) {
  const root = `sensor.crop_steering_${room.room.prefix}`;
  const exists = (id: string | null): id is string => !!id && !!states[id];
  const zones = room.zones.map((zone) => ({
    id: zone.id,
    phase: `${root}zone_${zone.id}_phase`,
    valve: zone.valveEntity,
    vwc: zone.vwc.entityId,
  }));
  const decision = `${root}current_decision`;
  const ids = [
    ...zones.flatMap((zone) => [zone.phase, zone.valve, zone.vwc]),
    ...room.settings.map((setting) => setting.entityId),
  ];
  return {
    zones,
    entityIds: [...new Set(ids.filter(exists))].sort(),
    attributeIds: exists(decision) ? [decision] : [],
  };
}

/** The grow-day `now` falls in: lights-on to the next lights-on, in the browser's time zone (as the
 * plan graph folds recorded days). Null without a usable photoperiod. */
export function growDay(
  lightsOn: number | null,
  lightsOff: number | null,
  now: number,
): GrowDay | null {
  const hour = (value: number | null): value is number =>
    value !== null && value >= 0 && value < 24;
  if (!hour(lightsOn) || !hour(lightsOff) || lightsOn === lightsOff || !Number.isFinite(now))
    return null;
  const at = (day: Date, offset: number, value: number) =>
    new Date(
      day.getFullYear(),
      day.getMonth(),
      day.getDate() + offset,
      0,
      Math.round(value * 60),
    ).getTime();
  const today = new Date(now);
  const start = at(today, 0, lightsOn) > now ? at(today, -1, lightsOn) : at(today, 0, lightsOn);
  const first = new Date(start);
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
    if (fired) Object.assign(shot, { phase: fired.phase, reason: fired.text });
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
export function earlierEntities(room: RoomView, states: States) {
  const root = `crop_steering_${room.room.prefix}`;
  const exists = (id: string | null | undefined): id is string => !!id && !!states[id];
  const ids = [
    ...room.zones.flatMap((zone) => [zone.vwc.entityId, zone.valveEntity]),
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
): GrowDay[] {
  const days: GrowDay[] = [];
  for (let end = day.start; days.length < count;) {
    const middle = end - 12 * 3_600_000;
    const { on, off } = hours(middle);
    let earlier = growDay(on, off, middle);
    // The schedule changed after this day's lights-on: it came on at the hour in force then.
    const then = earlier && hours(earlier.start);
    const moved = then && then.on !== on && growDay(then.on, then.off, middle);
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
}
/** One earlier grow-day of a zone, to compare today with. Null when there is nothing to compare:
 * under two readings, or the room was switched off during it. */
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
  if (off || points.length < 2) return null;
  const shots = ids.valve ? valveShots(rows[ids.valve], [], zoneId, day.start, day.end) : [];
  return { day, points, shots };
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
 * trace of each day (null where there is nothing to compare), and the setup revision as each day
 * began. */
export function earlierTraces(
  rows: TimelineRows,
  room: RoomView,
  day: GrowDay,
  hours: { on: number | null; off: number | null },
  config?: string,
) {
  const root = `crop_steering_${room.room.prefix}`;
  const recorded = (key: "on" | "off", time: number) =>
    valueAt(rows[`number.${root}lights_${key}_hour`], time) ?? hours[key];
  const days = earlierDays(day, 7, (time) => ({
    on: recorded("on", time),
    off: recorded("off", time),
  }));
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

/** How far P0 dried the zone, as the engine measures dryback: (peak − VWC) / peak × 100, the peak
 * being the highest reading since P0 began, at its furthest over the band. */
export function morningDryback(points: readonly Reading[], band: Span): number | null {
  let peak = -Infinity,
    dryback: number | null = null;
  for (const point of points) {
    if (point.time < band.start || point.time > band.end) continue;
    peak = Math.max(peak, point.value);
    if (peak > 0) dryback = Math.max(dryback ?? 0, ((peak - point.value) / peak) * 100);
  }
  return dryback;
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
  "dryback_target" | "p1_target_vwc" | "p2_vwc_threshold" | "p3_emergency_vwc_threshold";
const PHASE_TARGET: Record<string, TargetKey> = {
  P0: "dryback_target",
  P1: "p1_target_vwc",
  P2: "p2_vwc_threshold",
  P3: "p3_emergency_vwc_threshold",
};
export interface TargetStep extends Level {
  phase: string;
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

/** A least-squares line through the readings taken since `since`: when does VWC reach `threshold`?
 * Null without enough recent data to say (fewer than five readings, under 15 minutes of them) or
 * when VWC is not falling measurably. */
export function dryDown(
  points: Reading[],
  threshold: number,
  since: number,
  now: number,
): DryDown | null {
  const recent = points.filter((point) => point.time >= since && point.time <= now);
  const first = recent[0],
    last = recent.at(-1);
  if (
    !first ||
    !last ||
    recent.length < DRY_DOWN.minPoints ||
    last.time - first.time < DRY_DOWN.minSpanMs
  )
    return null;
  const meanT = recent.reduce((sum, point) => sum + point.time - first.time, 0) / recent.length;
  const meanV = recent.reduce((sum, point) => sum + point.value, 0) / recent.length;
  let covariance = 0,
    variance = 0;
  for (const point of recent) {
    const dt = point.time - first.time - meanT;
    covariance += dt * (point.value - meanV);
    variance += dt * dt;
  }
  const slope = covariance / variance; // points per ms
  const rate = -slope * 3_600_000;
  if (!(rate >= DRY_DOWN.minRate)) return null;
  const value = meanV + slope * (last.time - first.time - meanT);
  const at = last.time + (Math.max(0, value - threshold) / rate) * 3_600_000;
  return { rate, from: { time: last.time, value }, at: Math.max(now, at) };
}

/** When a zone should fire next, only as far as the engine's own rules and today's data say:
 * P0 ends by its maximum wait, P1 fires every interval until the ramp ceiling, P2 tops up when
 * VWC dries to the threshold. Nothing is estimated while a shot runs, a hold is open, after
 * lights-off, or from too little data. */
export function nextShot(
  zone: {
    phase: string | null;
    /** When the current phase began. */
    since: number | null;
    held: Block | null;
    /** Today's last shot, if any. */
    lastShot: Shot | null;
    points: Reading[];
    /** The live VWC, null when the probe is unavailable or stale. */
    vwc: number | null;
    threshold: number | null;
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
  if (phase !== "P2" || zone.threshold === null) return { at: null, basis: "unknown" };
  if (zone.vwc <= zone.threshold) return { at: now, basis: "due" };
  const since = Math.max(
    now - DRY_DOWN.windowMs,
    lastShot ? lastShot.end + DRY_DOWN.settleMs : -Infinity,
  );
  if (now - since < DRY_DOWN.minSpanMs) return { at: null, basis: "settling" };
  const fit = dryDown(zone.points, zone.threshold, since, now);
  if (!fit) return { at: null, basis: "no-dry-down" };
  return fit.at < day.lightsOff
    ? { at: fit.at, basis: "dry-down", fit }
    : { at: null, basis: "late", fit };
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
