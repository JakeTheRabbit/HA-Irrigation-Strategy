import {
  earlierDays,
  growDay,
  levels,
  valveShots,
  type Level,
  type Shot,
  type Span,
  type TimelineRow,
  type TimelineRows,
} from "./day-timeline";
import { descriptor } from "./model";
import { fillTime } from "./tank-telemetry";
import type { RoomView, States } from "./types";

/** The tank's level over time beside what moved it: the controller's shots, the pump's runs, the
 * tank filling and each recorded fill. Pure: the chart only draws what these functions return. */

const HOUR = 3_600_000;
export const LEVEL_RANGES = [
  { hours: 24, label: "24 h" },
  { hours: 72, label: "3 days" },
  { hours: 168, label: "7 days" },
] as const;

/** The room descriptor's keys for the tank and pump mapped in Rooms & setup. */
export const TANK_KEYS = {
  level: "water_level_sensor",
  pump: "pump",
  filling: "tank_fill_entity",
  fill: "tank_last_fill_sensor",
} as const;

export interface TankIds {
  level: string | null;
  pump: string | null;
  filling: string | null;
  fill: string | null;
  decision: string | null;
  valves: { zone: number; entityId: string }[];
}

/** What the chart reads, where Home Assistant has it: the mapped level, pump, filling status and
 * last-fill record, each zone's valve, and the controller's decision. The last-fill record and the
 * decision are read with their attributes (a date-and-time helper's timestamp, the shots the
 * controller fired). */
export function tankEntities(room: RoomView, states: States) {
  const mapped = descriptor(states, room.room)?.attributes ?? {};
  const exists = (id: unknown): id is string => typeof id === "string" && !!id && !!states[id];
  const pick = (key: string) => {
    const id = mapped[key];
    return exists(id) ? id : null;
  };
  const decision = `sensor.crop_steering_${room.room.prefix}current_decision`;
  const ids: TankIds = {
    level: pick(TANK_KEYS.level),
    pump: pick(TANK_KEYS.pump),
    filling: pick(TANK_KEYS.filling),
    fill: pick(TANK_KEYS.fill),
    decision: exists(decision) ? decision : null,
    valves: room.zones.flatMap((zone) =>
      exists(zone.valveEntity) ? [{ zone: zone.id, entityId: zone.valveEntity }] : [],
    ),
  };
  const present = (list: (string | null)[]) =>
    [...new Set(list.filter((id): id is string => !!id))].sort();
  return {
    ids,
    entityIds: present([ids.level, ids.pump, ids.filling, ...ids.valves.map((v) => v.entityId)]),
    attributeIds: present([ids.fill, ids.decision]),
  };
}

/** The requests a range is read in: whole grow-days (lights-on to lights-on) from the one the range
 * starts in up to now, as the zone charts read theirs; calendar days without a lights schedule. */
export function recordWindows(
  lightsOn: number | null,
  lightsOff: number | null,
  hours: number,
  now: number,
): Span[] {
  const lit = growDay(lightsOn, lightsOff, now);
  const schedule = lit ? { on: lightsOn, off: lightsOff } : { on: 0, off: 12 };
  const today = lit ?? growDay(0, 12, now)!;
  const from = now - hours * HOUR;
  const count = Math.max(0, Math.ceil((today.start - from) / (24 * HOUR)) + 1);
  const earlier = earlierDays(today, count, () => schedule).filter((day) => day.end > from);
  return [...earlier.reverse(), today].map((day) => ({
    start: day.start,
    end: Math.min(day.end, now),
  }));
}

/** A reading under 0 % or over 100 % is not a level: like no reading, it leaves a gap. */
const percent = (row: TimelineRow | undefined): number | null => {
  const value = row?.state.trim() ? Number(row.state) : NaN;
  return Number.isFinite(value) && value >= 0 && value <= 100 ? value : null;
};
/** How long a passing value Home Assistant records while it restarts lasts: well under a second. */
const PASSING_MS = 5_000;
/** The level over [from, to] as steps, as Home Assistant holds a state until it changes; an
 * unknown tank is a gap, never drawn empty. A passing value (held under 5 s, the readings either
 * side of it within a point of each other) is not the tank's level and is left out. */
export function levelSteps(rows: TimelineRow[] = [], from: number, to: number): Level[] {
  const kept = rows.filter((row, index) => {
    const before = percent(rows[index - 1]),
      here = percent(row),
      after = percent(rows[index + 1]);
    return !(
      before !== null &&
      here !== null &&
      after !== null &&
      rows[index + 1].time - row.time < PASSING_MS &&
      Math.abs(after - before) <= 1 &&
      Math.abs(here - before) > 1
    );
  });
  return levels(
    kept.map((row) => (percent(row) === null ? { ...row, state: "" } : row)),
    from,
    to,
  );
}

/** The level in force at `time`, or null where none was recorded; on a change, the new reading. */
export function levelAt(steps: readonly Level[], time: number): number | null {
  for (let index = steps.length - 1; index >= 0; index--)
    if (steps[index].start <= time && time <= steps[index].end) return steps[index].value;
  return null;
}

export interface TankShot extends Shot {
  zone: number;
}
/** Every zone's shots in the window, read as the zone Today chart reads them: each time its valve
 * was open, named with the phase and rule the controller posted for it. Oldest first. */
export function tankShots(rows: TimelineRows, ids: TankIds, from: number, to: number): TankShot[] {
  const decisions = ids.decision ? rows[ids.decision] : [];
  return ids.valves
    .flatMap(({ zone, entityId }) =>
      valveShots(rows[entityId], decisions, zone, from, to).map((shot) => ({ ...shot, zone })),
    )
    .sort((a, b) => a.start - b.start);
}

export interface Run extends Span {
  /** Still on at the end of the window. */
  open: boolean;
}
/** Each time a switch reported on in the window (the pump, the tank filling): its own report, not
 * measured flow. */
export function onRuns(rows: TimelineRow[] | undefined, from: number, to: number): Run[] {
  return valveShots(rows, [], 0, from, to).map(({ start, end, open }) => ({ start, end, open }));
}

/** Each fill the last-fill record names in the window: a time newer than any it named before, as
 * the integration counts batches. A restart recording the same time again, or a time moved back,
 * is not a fill. */
export function recordedFills(
  rows: TimelineRow[] = [],
  entityId: string,
  from: number,
  to: number,
): number[] {
  const fills: number[] = [];
  let newest = -Infinity;
  for (const row of rows) {
    const time = fillTime(entityId, row.state, row.attributes);
    if (time === null || time <= newest) continue;
    newest = time;
    if (time >= from && time <= to) fills.push(time);
  }
  return fills;
}

export interface TankRecord {
  level: Level[];
  shots: TankShot[];
  pump: Run[];
  filling: Run[];
  fills: number[];
}
/** Everything the chart draws over [from, to], from the rows of tankEntities. */
export function tankRecord(rows: TimelineRows, ids: TankIds, from: number, to: number): TankRecord {
  return {
    level: ids.level ? levelSteps(rows[ids.level], from, to) : [],
    shots: tankShots(rows, ids, from, to),
    pump: ids.pump ? onRuns(rows[ids.pump], from, to) : [],
    filling: ids.filling ? onRuns(rows[ids.filling], from, to) : [],
    fills: ids.fill ? recordedFills(rows[ids.fill], ids.fill, from, to) : [],
  };
}

export interface ShotMark {
  time: number;
  /** The level in force as the first of its shots started: where the mark sits on the line. */
  level: number | null;
  shots: TankShot[];
}
/** The shots as marks on the level line, oldest first: a shot that started within `gapMs` of a
 * mark's first shot joins it, as the chart cannot tell them apart. */
export function shotMarks(
  shots: readonly TankShot[],
  level: readonly Level[],
  gapMs: number,
): ShotMark[] {
  const marks: ShotMark[] = [];
  for (const shot of shots) {
    const last = marks.at(-1);
    if (last && shot.start - last.time < gapMs) last.shots.push(shot);
    else marks.push({ time: shot.start, level: levelAt(level, shot.start), shots: [shot] });
  }
  return marks;
}
