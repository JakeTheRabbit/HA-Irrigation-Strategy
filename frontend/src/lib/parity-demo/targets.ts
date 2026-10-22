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
    reason: detail,
    outcome: null,
    limits: null,
    revertible: detail === null,
    user_id: null,
    user_name: "Ben",
    entity_id: entityId,
  });
  return id;
}

/** Forgets every journalled write: a new demo (another backend) starts with none. */
export function resetDemoTargetWrites() {
  writes.clear();
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
