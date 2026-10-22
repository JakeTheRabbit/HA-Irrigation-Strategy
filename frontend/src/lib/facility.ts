import { buildRoom, roomStatus } from "./model";
import { tankTelemetry } from "./tank-telemetry";
import type { Room, States } from "./types";
/** Read every room from one snapshot. Rendering never selects a room or sends commands. */
export function facilityRooms(states: States, rooms: Room[], now = Date.now()) {
  return rooms.map((room) => ({
    room,
    view: buildRoom(states, room),
    status: roomStatus(states, room, now),
    tank: tankTelemetry(states, room, now),
  }));
}
/** One zone of one room as a key: the room tree's pick selection and the timeline's plant counts. A
 * room on its own is its id. */
export const pickKey = (roomId: string, zone: number) => `${roomId}:${zone}`;
/** What waters the zone (select zone_N_irrigation_mode: steering, timer, off); null without it. */
export function irrigationMode(states: States, room: Room, zone: number): string | null {
  const state = states[`select.crop_steering_${room.prefix}zone_${zone}_irrigation_mode`]?.state;
  return state && state !== "unavailable" && state !== "unknown" ? state : null;
}
