import { demoEnvelope } from "../parity-demo";
import type { States } from "../types";
import { demoId } from "./journal";

/** The demo's moisture-probe offsets on 3.18 (calibration.py probe_offset_set, G9), kept for the page's
 * life: OperatorDemo answers probe_offset_set, history_revert of its writes, and merges them into
 * calibration_get's `probe_user_offsets`. Like the integration: bounds, a preview that writes nothing,
 * a revision check, each write journalled (an event id Undo puts back, refused once the offset has
 * moved on), and the zone's value re-fused from its probes with the offsets (the median; the mean for
 * two). Unlike the integration, the demo keeps its own revision for offsets and the feed calibration
 * history keeps its own (CalibrationDemo): the integration has one revision for the whole calibration
 * document, so there a feed calibration check also makes an offset preview stale. The demo never shows
 * that case; the stale-revision path is exercised by an offset write instead. */

const OFFSET_LIMIT = 20;
const CURVE_ON_PERCENT = "This probe already converts to moisture. A curve only applies to raw readings.";
type Offsets = Record<string, { offset: number; curve: null; at: string; by: string }>;
interface Room {
  revision: number;
  offsets: Offsets;
}
const rooms = new Map<string, Room>();
const writes = new Map<string, { roomId: string; entityId: string; old: number; new: number; settled: boolean }>();

/** Forgets every offset: a new demo (another backend) starts with none. */
export function resetDemoProbeOffsets() {
  rooms.clear();
  writes.clear();
}
const room = (roomId: string) => {
  let found = rooms.get(roomId);
  if (!found) rooms.set(roomId, (found = { revision: 1, offsets: {} }));
  return found;
};
/** calibration_get's `probe_user_offsets` for the room. */
export const demoProbeOffsets = (roomId: string): Offsets => structuredClone(room(roomId).offsets);
/** Whether this Journal event is one of the demo's offset writes. */
export const isDemoOffsetWrite = (eventId: string) => writes.has(eventId);

const round3 = (value: number) => Math.round(value * 1000) / 1000;
const refuse = (code: string, message: string, extra: Record<string, unknown> = {}) => ({
  api: 2,
  ok: false,
  error: { code, message, ...extra },
});
const fail = (message: string) => refuse("invalid", message);

/** The zone whose combined moisture sensor names the probe, and the probes it uses. */
function zoneOf(states: States, roomId: string, entityId: string) {
  const prefix = roomId.replace(/^room:/, "");
  for (const [id, entity] of Object.entries(states)) {
    const match = new RegExp(`^sensor\\.crop_steering_${prefix}vwc_zone_(\\d+)$`).exec(id);
    if (!match) continue;
    const used = Array.isArray(entity.attributes.used) ? (entity.attributes.used as string[]) : [];
    const excluded = entity.attributes.excluded;
    const left = excluded && typeof excluded === "object" ? Object.keys(excluded) : [];
    if (used.includes(entityId) || left.includes(entityId)) return { fused: id, used };
  }
  return null;
}
const raw = (states: States, id: string) => {
  const value = Number(states[id]?.state);
  return Number.isFinite(value) ? value : null;
};
/** The zone's value with `offset` on this probe and every other probe's own: the median of the probes it
 * uses (the mean for two), or null without a reading. */
function fusedWith(states: States, offsets: Offsets, used: string[], entityId: string, offset: number) {
  const values = used
    .map((id) => {
      const value = raw(states, id);
      return value === null ? null : value + (id === entityId ? offset : (offsets[id]?.offset ?? 0));
    })
    .filter((value): value is number => value !== null)
    .sort((a, b) => a - b);
  if (!values.length) return null;
  const middle = Math.floor(values.length / 2);
  return round3(values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2);
}

/** probe_offset_set, as the integration answers it (a v2 envelope). */
export function answerProbeOffset(
  data: Record<string, unknown>,
  states: States,
  updateStates: (states: States) => void,
  now: number,
) {
  const roomId = String(data.room_id);
  const entityId = String(data.entity_id);
  const preview = data.preview === true;
  const zone = zoneOf(states, roomId, entityId);
  if (!zone) return fail("That is not a moisture probe of this room");
  if (!("offset" in data || "curve" in data || "match_handheld" in data))
    return fail("Give an offset, a curve or a handheld reading to match");
  if ("match_handheld" in data && "offset" in data) return fail("Give an offset or a handheld reading to match, not both");
  const store = room(roomId);
  if (!preview && data.expected_revision !== store.revision)
    return refuse("stale_revision", "Calibration history changed elsewhere. Reload before saving.", {
      current_revision: store.revision,
    });
  // The demo's probes read percent: no curve applies.
  if ("curve" in data && data.curve !== null && data.curve !== "none") return fail(CURVE_ON_PERCENT);
  const old = store.offsets[entityId]?.offset ?? 0;
  let offset = old;
  if ("offset" in data) {
    offset = Number(data.offset);
    if (!Number.isFinite(offset) || Math.abs(offset) > OFFSET_LIMIT)
      return fail(`Offset must be a number from -${OFFSET_LIMIT} to ${OFFSET_LIMIT}`);
  }
  const reading = raw(states, entityId);
  if ("match_handheld" in data) {
    const handheld = Number(data.match_handheld);
    if (!Number.isFinite(handheld) || handheld < 0 || handheld > 100) return fail("Handheld must be a number from 0 to 100");
    if (reading === null) return fail("The probe has no reading to match");
    offset = round3(handheld - reading);
    if (Math.abs(offset) > OFFSET_LIMIT)
      return fail(
        `The probe reads ${reading} and the handheld ${handheld}: ${Math.abs(offset)} apart, more than the ${OFFSET_LIMIT} an offset may be`,
      );
  }
  const corrected = reading === null ? null : round3(reading + offset);
  if (corrected !== null && (corrected < 0 || corrected > 100))
    return fail(`The probe would read ${corrected}, outside 0 to 100`);
  const answer = {
    offset,
    curve: null,
    corrected_now: corrected,
    fused_before: fusedWith(states, store.offsets, zone.used, entityId, old),
    fused_after: fusedWith(states, store.offsets, zone.used, entityId, offset),
    excluded_after: {},
  };
  if (preview) return demoEnvelope({ ...answer, preview: true, revision: store.revision }, now, roomId);
  const eventId = write(store, roomId, entityId, old, offset, now);
  reFuseZone(states, updateStates, zone.fused, answer.fused_after, now);
  return { ...demoEnvelope({ ...answer, revision: store.revision }, now, roomId), event_ids: [eventId] };
}

function write(store: Room, roomId: string, entityId: string, old: number, offset: number, now: number) {
  store.revision += 1;
  if (offset === 0) delete store.offsets[entityId];
  else store.offsets[entityId] = { offset, curve: null, at: new Date(now).toISOString(), by: "demo-user" };
  const eventId = demoId(now, `offset:${roomId}:${entityId}:${store.revision}`);
  writes.set(eventId, { roomId, entityId, old, new: offset, settled: false });
  return eventId;
}
/** The zone sensor re-fuses once the controller holds the offset. */
function reFuseZone(states: States, updateStates: (states: States) => void, fused: string, value: number | null, now: number) {
  if (value === null) return;
  const stamp = new Date(now).toISOString();
  updateStates({ ...states, [fused]: { ...states[fused], state: value.toFixed(1), last_updated: stamp, last_changed: stamp } });
}

/** history_revert of an offset write: the old offset back, journalled; refused once the probe's offset
 * is no longer the one written, and a second time. */
export function revertProbeOffset(eventId: string, states: States, updateStates: (states: States) => void, now: number) {
  const change = writes.get(eventId)!;
  const store = room(change.roomId);
  if (change.settled) return fail("This change can't be put back");
  if ((store.offsets[change.entityId]?.offset ?? 0) !== change.new)
    return refuse("stale_revision", "The probe offsets have changed since. Reload and check them before trying again.");
  const zone = zoneOf(states, change.roomId, change.entityId);
  const newId = write(store, change.roomId, change.entityId, change.new, change.old, now);
  writes.set(eventId, { ...change, settled: true });
  if (zone) reFuseZone(states, updateStates, zone.fused, fusedWith(states, store.offsets, zone.used, change.entityId, change.old), now);
  return demoEnvelope({ reverted_event_id: eventId, new_event_id: newId, readback: "verified" }, now, change.roomId);
}
