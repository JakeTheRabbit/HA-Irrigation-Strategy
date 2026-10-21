import { LayoutGrid } from "lucide-react";
import { number } from "@/components/dashboard";
import { facilityRooms } from "@/lib/facility";
import type { Controller } from "@/lib/types";
import "./room-tree.css";

/** The menu's live room list: every room with its state, and under it every zone with its phase
 * and moisture. One click opens a room (in the section already open) or a zone's own page, so any
 * zone in the facility is one click away and the selected one is always marked. */
export function RoomTree({
  controller,
  allRooms,
  currentZone,
  openAll,
  openRoom,
  openZone,
}: {
  controller: Controller;
  /** The All rooms page is open. */
  allRooms: boolean;
  /** The zone whose page is open, if one is. */
  currentZone: number | null;
  openAll: () => void;
  openRoom: (room: string) => void;
  openZone: (room: string, zone: number) => void;
}) {
  const rooms = facilityRooms(controller.states, controller.rooms);
  return (
    <nav className="room-tree" aria-label="Rooms">
      <span className="room-tree-heading">Rooms</span>
      <button
        type="button"
        className="room-tree-row room-tree-all"
        aria-current={allRooms ? "page" : undefined}
        onClick={openAll}
      >
        <LayoutGrid size={16} aria-hidden="true" />
        <span className="room-tree-name">All rooms</span>
      </button>
      {rooms.map(({ room, view, status }) => {
        const selected = room.id === controller.roomId;
        return (
          <div className="room-tree-room" key={room.id} data-room={room.id}>
            <button
              type="button"
              className="room-tree-row"
              data-tone={status.tone}
              aria-current={selected && !allRooms && currentZone === null ? "page" : undefined}
              title={`${room.name}: ${status.text}. ${status.detail}`}
              onClick={() => openRoom(room.id)}
            >
              <span className="room-tree-dot" aria-hidden="true" />
              <span className="room-tree-name">{room.name}</span>
              <span className="room-tree-state">{status.text}</span>
            </button>
            {view.zones.map((zone) => {
              const flag = zone.stale ? "stale" : zone.enabled === false ? "paused" : null;
              return (
                <button
                  type="button"
                  key={zone.id}
                  className="room-tree-row room-tree-zone"
                  data-flag={flag ?? undefined}
                  aria-current={selected && currentZone === zone.id ? "page" : undefined}
                  title={
                    flag === "stale"
                      ? `${zone.name}: last reported reading`
                      : flag === "paused"
                        ? `${zone.name}: zone paused`
                        : zone.name
                  }
                  onClick={() => openZone(room.id, zone.id)}
                >
                  <span className="room-tree-phase" data-phase={zone.phase}>
                    {/^P[0-3]$/.test(zone.phase) ? zone.phase : "–"}
                  </span>
                  <span className="room-tree-name">{zone.name}</span>
                  <span className="room-tree-value">
                    {zone.vwc.value === null ? "—" : `${number(zone.vwc.value)}%`}
                  </span>
                  {flag && <span className="room-tree-flag" aria-hidden="true" />}
                </button>
              );
            })}
          </div>
        );
      })}
    </nav>
  );
}
