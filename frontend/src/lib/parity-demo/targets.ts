import type { HistoryChange } from "../parity-types";
import { demoId } from "./journal";

/** The demo's own setpoint writes on 3.18, as the integration journals them: each panel write of a
 * `number.crop_steering_*` target is a manual `target.changed` (a base write, so revertible) that
 * `history_changes` lists and `history_revert` puts back (operator-demo writes the old value). They
 * last the page's life. */
type Write = HistoryChange & { entity_id: string };
const writes = new Map<string, Write>();

/** Journals one write; returns its event id. */
export function journalDemoTargetWrite(
  roomId: string,
  prefix: string,
  entityId: string,
  old: number | null,
  value: number,
  now: number,
  detail: string | null = null,
  extra: Partial<HistoryChange> = {},
): string | null {
  const root = `number.crop_steering_${prefix}`;
  // Writing the value it already holds is no change: the integration journals none.
  if (!entityId.startsWith(root) || old === value) return null;
  const rest = entityId.slice(root.length);
  const zone = rest.match(/^zone_(\d+)_/)?.[1];
  const id = demoId(now, `target:${entityId}:${value}:${writes.size}`);
  writes.set(id, {
    id,
    room_id: roomId,
    ts: new Date(now).toISOString(),
    actor: "manual",
    kind: "setpoint",
    key: rest.replace(/^zone_\d+_/, ""),
    scope: zone ? `zone:${zone}` : "room",
    old,
    new: value,
    reason: null,
    outcome: null,
    limits: null,
    // A put-back is a base write too: the integration puts it back in turn (Undo of a revert).
    revertible: true,
    user_id: null,
    user_name: "Ben",
    detail,
    ...extra,
    entity_id: entityId,
  });
  return id;
}

/** Forgets every journalled write: a new demo (another backend) starts with none. */
export function resetDemoTargetWrites() {
  writes.clear();
  seeded = false;
  setpointLog = null;
}

const HOUR = 3_600_000;
const TOO_SOON = "Too soon to judge — check after the next lights-on.";
/** Room A's changes of the last ten days (History › Changes), each ending at what the room holds
 * now, so putting one back writes its old value: who, which setting, how far it moved, why. */
const SEEDS: { hoursAgo: number; key: string; zone: number | null; by: number; extra: Partial<HistoryChange> }[] = [
  { hoursAgo: 1, key: "p2_shot_size", zone: 2, by: -0.5, extra: { actor: "manual", reason: "Pore EC is over its band, so each P2 shot gives more water to wash it down." } },
  {
    hoursAgo: 3, key: "generative_dryback_target", zone: 3, by: 1,
    extra: { actor: "ai", user_name: null, reason: "Zone 3 got less water than asked this morning. Eased the overnight dryback so it does not run dry.", outcome: TOO_SOON, limits: { writer: "brain", min: 5, max: 25, step_scope: "zone" } },
  },
  {
    hoursAgo: 26, key: "field_capacity", zone: 1, by: 1,
    extra: { actor: "learner", user_name: null, reason: "The last five P1 ramps peaked between 69.1 and 69.4%, never at 71%.", outcome: "Dryback came back to target.", limits: { writer: "learner", min: 50, max: 80, step_scope: "zone" } },
  },
  { hoursAgo: 30, key: "max_shot_duration", zone: null, by: 30, extra: { actor: "mcp", user_name: null, reason: "Claude found shots running past the dripper flow test. You previewed the change and approved it." } },
  { hoursAgo: 50, key: "max_daily_volume", zone: 1, by: -4, extra: { actor: "aigrow", user_name: null, reason: "Weekly review: Zone 1 hit the cap on 2 of the last 7 days." } },
  { hoursAgo: 9 * 24, key: "p1_target_vwc", zone: 1, by: -1, extra: { actor: "manual", reason: "Start of week 6: P1 fills a point higher." } },
];
let seeded = false;
/** Journals Room A's seeded changes once, from the room's values now. */
export function seedDemoChanges(states: Record<string, { state: string } | undefined>, now: number) {
  if (seeded) return;
  seeded = true;
  for (const seed of SEEDS) {
    const entityId = `number.crop_steering_${seed.zone === null ? "" : `zone_${seed.zone}_`}${seed.key}`;
    const value = Number(states[entityId]?.state);
    if (!Number.isFinite(value)) continue;
    const old = Number((value + seed.by).toFixed(2));
    journalDemoTargetWrite("room:", "", entityId, old, value, now - seed.hoursAgo * HOUR, null, seed.extra);
  }
}

let setpointLog: Record<string, unknown>[] | null = null;
/** Room A's seeded changes as a 3.17 setpoint log (`setpoint_log_get`), from the room's values when
 * first read: its setting writes, each with the log's `who`. */
export function demoSetpointLog(states: Record<string, { state: string } | undefined>, now: number) {
  const who: Record<string, string> = { manual: "operator", learner: "learner", ai: "brain" };
  setpointLog ??= SEEDS.flatMap((seed) => {
    const entityId = `number.crop_steering_${seed.zone === null ? "" : `zone_${seed.zone}_`}${seed.key}`;
    const value = Number(states[entityId]?.state);
    if (!Number.isFinite(value)) return [];
    return [{
      at: new Date(now - seed.hoursAgo * HOUR).toISOString(),
      entity_id: entityId,
      field: seed.key,
      zone: seed.zone,
      old: Number((value + seed.by).toFixed(2)),
      new: value,
      who: who[seed.extra.actor ?? ""] ?? "home_assistant",
      ...(seed.extra.reason ? { reason: seed.extra.reason } : {}),
    }];
  }).reverse();
  return structuredClone(setpointLog);
}

/** The rooms' journalled writes, newest first. */
export function demoTargetChanges(rooms: string[]): HistoryChange[] {
  return [...writes.values()]
    .filter((w) => rooms.includes(w.room_id))
    .map(({ entity_id: _entity, ...change }) => change)
    .sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
}

/** The write an event id journalled, if the demo made it. */
export const demoTargetWrite = (eventId: string): Write | undefined => writes.get(eventId);

/** Marks a write as put back: it cannot be put back twice. */
export function settleDemoTargetWrite(eventId: string) {
  const write = writes.get(eventId);
  if (write) writes.set(eventId, { ...write, revertible: false });
}
