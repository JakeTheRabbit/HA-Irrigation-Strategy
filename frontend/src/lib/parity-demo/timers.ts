import type { DemoHandler } from "../parity-demo";
import type { TimerProgram, TimerProgramListItem } from "../parity-types";
import { DEMO_TIMER_PROGRAM_ID, demoId } from "./journal";

/** The demo's timer programs (I3), kept as the integration keeps them (timers_api.py): one store a
 * room ({revision, programs}), a program checked and projected the way generated/timers.py does it,
 * with its words, a delete that is soft, a zone in one running program at most, and each save
 * journalled (`config.changed {store: timers, section: programs, old, new}`) so `history_revert`
 * puts it back, a deleted program under a new id (`renewed`). As the integration's envelope does, a
 * save is not read back (`readback: none`): the panel reads the list again.
 *
 * Room A plays F2: zone 3 waters by "Zone 3 day timer" (1 min every 45 min while its lights are on,
 * 10:00–22:00, as the Journal and the watering timeline have it), plus a night top-up draft that
 * does not run. Room B (lights 08:00–20:00) has none. Times are the viewer's clock. */

type Stored = TimerProgram & { created_at?: string; updated_at?: string; deleted_at?: string | null };
type Store = { revision: number; programs: Stored[] };
const LIGHTS: Record<string, [number, number]> = { "room:": [10, 22], "room:room_b_": [8, 20] };
const ZONES = 3;
const MIN = 60_000;
const NEXT_WITHIN = 8 * 24 * 60 * MIN;

let rooms: Record<string, Store> = seed();
/** Each journalled save: its room and the programs before and after it. */
const journal = new Map<string, { room: string; old: Stored[]; new: Stored[] }>();

function seed(): Record<string, Store> {
  const day: Stored = {
    id: DEMO_TIMER_PROGRAM_ID, room_id: "room:", name: "Zone 3 day timer", zones: [3], type: "recycle",
    duration_s: 60, interval_min: 45, frequency_per_day: null, start_at: null, window: { kind: "lights_on" },
    sync_time: null, active: true,
  };
  const night: Stored = {
    id: "01JDEMQT1MERZ0NE3N1GHT0000", room_id: "room:", name: "Zone 3 night top-up", zones: [3], type: "simple",
    duration_s: 90, interval_min: null, frequency_per_day: 2, start_at: null, window: { kind: "lights_off" },
    sync_time: null, active: false,
  };
  return { "room:": { revision: 1, programs: [day, night] }, "room:room_b_": { revision: 1, programs: [] } };
}
/** A new demo (another backend) starts from the seed. */
export function resetDemoTimers() {
  rooms = seed();
  journal.clear();
}

const live = (s: Store) => s.programs.filter((p) => !p.deleted_at);
const hhmm = (text: unknown) => {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(text));
  const v = m ? Number(m[1]) * 60 + Number(m[2]) : NaN;
  if (!(v >= 0 && v < 1440)) throw new Error(`time must be HH:MM, got '${String(text)}'`);
  return v;
};
const finite = (value: unknown, what: string) => {
  const v = Number(value);
  if (value === null || value === undefined || value === "" || !Number.isFinite(v)) throw new Error(what);
  return v;
};

/** Python's int(): a number truncated toward zero, a string of digits, a bool as 0/1; else throws. */
function pyInt(value: unknown, what: string): number {
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "number" && Number.isFinite(value)) return Math.trunc(value);
  if (typeof value === "string" && /^\s*[+-]?\d+\s*$/.test(value)) return Number(value);
  throw new Error(what);
}
/** Python truthiness, for `p.get("window") or {...}`. */
const falsy = (v: unknown) =>
  v === null || v === undefined || v === false || v === 0 || v === "" || (Array.isArray(v) && !v.length) ||
  (typeof v === "object" && !Array.isArray(v) && !Object.keys(v as object).length);
/** A window's start and length in minutes from midnight (timers._window). */
function span(w: TimerProgram["window"], lights: [number, number]): [number, number] {
  const [on, off] = lights;
  if (w.kind === "all") return [0, 1440];
  const [a, b] = w.kind === "lights_on" ? [on * 60, off * 60] : w.kind === "lights_off" ? [off * 60, on * 60] : [hhmm(w.from), hhmm(w.to)];
  return [a, (((b - a) % 1440) + 1440) % 1440 || 1440];
}

/** timers.validate with the room's lights (as timers_api checks a program), the room's zones too. */
function validate(raw: Record<string, unknown>, room: string): Stored {
  const p = { ...raw } as Record<string, unknown>;
  if (!["one_off", "recycle", "simple"].includes(String(p.type))) throw new Error("type must be one of one_off, recycle, simple");
  const rawZones = falsy(p.zones) ? [] : p.zones;
  if (!Array.isArray(rawZones)) throw new Error("zones must be integers");
  const zones = [...new Set(rawZones.map((z) => pyInt(z, "zones must be integers")))];
  if (!zones.length) throw new Error("pick at least one zone");
  const duration = finite(p.duration_s, "duration must be a number of seconds");
  if (duration <= 0) throw new Error("duration must be greater than 0");
  const active = "active" in p ? p.active : true;
  if (typeof active !== "boolean") throw new Error("active must be true or false");
  const given = falsy(p.window) ? { kind: "all" } : p.window;
  if (typeof given !== "object" || Array.isArray(given)) throw new Error('window must be an object such as {"kind": "all"}');
  const window = { ...given } as TimerProgram["window"];
  if (!["all", "lights_on", "lights_off", "custom"].includes(window.kind))
    throw new Error("window kind must be one of all, lights_on, lights_off, custom");
  if (window.kind === "custom" && hhmm(window.from) === hhmm(window.to)) throw new Error("End must be after start");
  const sync = p.sync_time === null || p.sync_time === undefined ? null : String(p.sync_time);
  if (sync !== null) hhmm(p.sync_time);
  const out: Stored = {
    id: String(p.id ?? ""), room_id: room, name: String(p.name ?? "").trim() || "Timer", zones,
    type: p.type as TimerProgram["type"], duration_s: duration, active, window,
    interval_min: null, frequency_per_day: null, start_at: null, sync_time: sync,
  };
  if (out.type === "recycle") {
    out.interval_min = finite(p.interval_min, "interval must be a number of minutes");
    if (out.interval_min < 1) throw new Error("interval must be at least 1 minute");
    if (sync !== null) {
      const [from, length] = span(window, LIGHTS[room] ?? [12, 0]);
      if ((((hhmm(sync) - from) % 1440) + 1440) % 1440 >= length) throw new Error("sync time must be inside the window");
    }
  } else if (out.type === "simple") {
    const n = pyInt(p.frequency_per_day, "frequency must be a whole number per day");
    if (n < 1) throw new Error("frequency must be at least 1 per day");
    out.frequency_per_day = n;
  } else {
    if (!Number.isFinite(Date.parse(String(p.start_at)))) throw new Error("start_at must be an ISO datetime");
    out.start_at = String(p.start_at);
  }
  for (const zone of zones) {
    if (!Number.isInteger(zone)) throw new Error("zones must be integers");
    if (zone < 1 || zone > ZONES) throw new Error(`Zone ${zone} is not in this room`);
  }
  return out;
}

/** timers.project over [start, end) on the viewer's clock: each zone's shots, in time order. */
function project(p: Stored, room: string, start: number, end: number) {
  const out: { zone: number; at: string; duration_s: number }[] = [];
  if (!p.active) return out;
  const emit = (at: number) => {
    if (at >= start && at < end) for (const zone of p.zones) out.push({ zone, at: new Date(at).toISOString(), duration_s: p.duration_s });
  };
  if (p.type === "one_off") emit(Date.parse(String(p.start_at)));
  else {
    const [a, length] = span(p.window, LIGHTS[room] ?? [12, 0]);
    const offsets: number[] = [];
    // A sync time starts the shots there; one the lights moved out of the window starts the window.
    let first = p.type === "recycle" && p.sync_time ? (((hhmm(p.sync_time) - a) % 1440) + 1440) % 1440 : 0;
    if (first >= length) first = 0;
    if (p.type === "recycle") for (let t = first; t < length; t += p.interval_min!) offsets.push(t);
    else for (let i = 0; i < p.frequency_per_day!; i++) offsets.push((i * length) / p.frequency_per_day!);
    const day = new Date(start);
    day.setHours(0, 0, 0, 0);
    day.setDate(day.getDate() - 1);
    for (; day.getTime() <= end; day.setDate(day.getDate() + 1))
      for (const off of offsets) {
        const at = new Date(day);
        at.setMinutes(a + off);
        emit(at.getTime());
      }
  }
  return out.sort((x, y) => Date.parse(x.at) - Date.parse(y.at) || x.zone - y.zone);
}

const refusal = (code: string, message: string, current?: number) => ({
  api: 2, ok: false, error: { code, message, ...(current === undefined ? {} : { current_revision: current }) },
});
const envelope = (room: unknown, now: number, data: Record<string, unknown>, status: string, eventIds: string[] = []) => ({
  api: 2, ok: true, room_id: typeof room === "string" ? room : null,
  revision: typeof data.revision === "number" ? data.revision : null,
  readback: { status, at: new Date(now).toISOString() }, event_ids: eventIds, data,
});
const message = (error: unknown) => (error instanceof Error ? error.message : String(error));

function listed(room: string, now: number): TimerProgramListItem[] {
  return live(rooms[room]).map((p) => {
    const next = project(p, room, now, now + NEXT_WITHIN)[0];
    return { ...structuredClone(p), room_id: room, next_at: next?.at ?? null, error: null, zones_in_timer_mode: room === "room:" ? p.zones.filter((z) => z === 3) : [] };
  });
}

/** A save at `expected_revision`: `change` edits a copy of the programs; refused when stale, or
 * when a zone ends up in two running programs. */
function save(data: Record<string, unknown>, now: number, change: (programs: Stored[], stamp: string) => Record<string, unknown>) {
  const room = String(data.room_id);
  const store = rooms[room];
  if (!store) return refusal("invalid", "Room is unknown or ambiguous");
  if (data.expected_revision !== store.revision)
    return refusal("stale_revision", "Timer programs changed elsewhere. Reload before saving.", store.revision);
  const programs = structuredClone(store.programs);
  let result: Record<string, unknown>;
  try {
    result = change(programs, new Date(now).toISOString());
    const owner = new Map<number, Stored>();
    for (const p of programs.filter((q) => q.active && !q.deleted_at))
      for (const zone of p.zones) {
        if (owner.has(zone)) throw new Error(`Zone ${zone} is already in timer '${owner.get(zone)!.name}'`);
        owner.set(zone, p);
      }
  } catch (error) {
    return refusal("invalid", message(error));
  }
  const eventId = demoId(now, `timers:${room}:${store.revision}:${journal.size}`);
  journal.set(eventId, { room, old: store.programs, new: programs });
  rooms[room] = { revision: store.revision + 1, programs };
  return { ...result, revision: store.revision + 1, eventId };
}

const shown = (list: Stored[]) =>
  JSON.stringify(
    list
      .filter((p) => !p.deleted_at)
      .map(({ created_at: _c, updated_at: _u, deleted_at: _d, ...p }) => p)
      .sort((a, b) => a.id.localeCompare(b.id)),
  );

export const handlers: DemoHandler[] = [
  {
    action: "timer_program_list",
    answer: (data, now) => {
      if (typeof data.room_id === "string") {
        const store = rooms[data.room_id];
        if (!store) return refusal("invalid", "Room is unknown or ambiguous");
        return { programs: listed(data.room_id, now), revision: store.revision, error: null };
      }
      const ids = Object.keys(rooms).sort();
      return {
        programs: ids.flatMap((room) => listed(room, now)),
        revision: null,
        revisions: Object.fromEntries(ids.map((room) => [room, rooms[room].revision])),
        errors: {},
      };
    },
  },
  {
    action: "timer_program_preview",
    answer: (data, now) => {
      const room = String(data.room_id);
      try {
        const hours = Number(data.hours ?? 24);
        if (!(hours >= 1 && hours <= 48)) throw new Error("hours must be from 1 to 48");
        const shots = project(validate(data.program as Record<string, unknown>, room), room, now, now + hours * 60 * MIN);
        return { preview: shots, shots: shots.length, total_s: shots.reduce((sum, s) => sum + s.duration_s, 0) };
      } catch (error) {
        return refusal("invalid", message(error));
      }
    },
  },
  {
    action: "timer_program_set",
    answer: (data, now) => {
      const out = save(data, now, (programs, stamp) => {
        const sent = (data.program ?? {}) as Record<string, unknown>;
        const checked = validate(sent, String(data.room_id));
        const at = programs.findIndex((p) => p.id === sent.id && !p.deleted_at);
        if (sent.id && at < 0) throw new Error(`No timer program ${String(sent.id)} in this room`);
        if (at < 0) programs.push({ ...checked, id: demoId(now, `program:${stamp}`), created_at: stamp, updated_at: stamp });
        else programs[at] = { ...checked, created_at: programs[at].created_at, updated_at: stamp };
        return { program: structuredClone(at < 0 ? programs.at(-1)! : programs[at]) };
      });
      if (!("eventId" in out)) return out;
      const { eventId, ...result } = out;
      return envelope(data.room_id, now, { ...result, preview: [] }, "none", [eventId as string]);
    },
  },
  {
    action: "timer_program_delete",
    answer: (data, now) => {
      const out = save(data, now, (programs, stamp) => {
        const program = programs.find((p) => p.id === data.id && !p.deleted_at);
        if (!program) throw new Error(`No timer program ${String(data.id)} in this room`);
        Object.assign(program, { active: false, deleted_at: stamp, updated_at: stamp });
        return { program: structuredClone(program) };
      });
      if (!("eventId" in out)) return out;
      const { eventId, ...result } = out;
      return envelope(data.room_id, now, result, "none", [eventId as string]);
    },
  },
  {
    action: "history_revert",
    match: (data) => journal.has(String(data.event_id)),
    answer: (data, now) => {
      const change = journal.get(String(data.event_id))!;
      const store = rooms[change.room];
      if (shown(store.programs) !== shown(change.new))
        return refusal("stale_revision", "The timer programs has changed since this change; reload the history", store.revision);
      const alive = new Set(change.new.filter((p) => !p.deleted_at).map((p) => p.id));
      const renewed: { name: string; old_id: string; id: string }[] = [];
      const stamp = new Date(now).toISOString();
      const programs: Stored[] = [
        ...store.programs.filter((p) => p.deleted_at),
        ...change.old
          .filter((p) => !p.deleted_at)
          .map((p) => {
            if (alive.has(p.id)) return structuredClone(p);
            const id = demoId(now, `renewed:${p.id}:${journal.size}`);
            renewed.push({ name: p.name, old_id: p.id, id });
            return { ...structuredClone(p), id, created_at: stamp, updated_at: stamp };
          }),
      ];
      // What the change added is deleted again.
      for (const p of store.programs)
        if (!p.deleted_at && !change.old.some((o) => o.id === p.id && !o.deleted_at))
          programs.push({ ...p, active: false, deleted_at: stamp, updated_at: stamp });
      const newId = demoId(now, `revert:${String(data.event_id)}`);
      journal.set(newId, { room: change.room, old: store.programs, new: programs });
      rooms[change.room] = { revision: store.revision + 1, programs };
      return envelope(
        change.room,
        now,
        { reverted_event_id: data.event_id, new_event_id: newId, readback: "verified", renewed },
        "verified",
        [newId],
      );
    },
  },
];

/** A program as a copy carries it (presets.timer_value): without where and when it was stored. */
const shape = ({ id: _i, room_id: _r, created_at: _c, updated_at: _u, deleted_at: _d, ...rest }: Stored) => rest;
/** A room's programs as a copy reads them, in a stable order; null for a room the demo has none of. */
export function demoTimerShapes(room: string): Record<string, unknown>[] | null {
  const store = rooms[room];
  return store ? live(store).map(shape).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))) : null;
}
/** A copy's write of a room's programs: each live one ends and the copied ones run in their place,
 * journalled as one save so `history_revert` puts the room's own back. -> its event id. */
export function copyDemoTimers(room: string, shapes: Record<string, unknown>[], now: number): string | null {
  const store = rooms[room];
  if (!store) return null;
  const out = save({ room_id: room, expected_revision: store.revision }, now, (programs, stamp) => {
    for (const p of programs.filter((q) => !q.deleted_at)) Object.assign(p, { active: false, deleted_at: stamp, updated_at: stamp });
    shapes.forEach((s, i) =>
      programs.push({ ...(structuredClone(s) as Omit<Stored, "id" | "room_id">), id: demoId(now, `copied:${room}:${i}`), room_id: room, created_at: stamp, updated_at: stamp }),
    );
    return {};
  });
  return "eventId" in out ? (out.eventId as string) : null;
}
