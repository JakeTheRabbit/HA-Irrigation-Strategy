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
