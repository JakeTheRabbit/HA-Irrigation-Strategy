import { useEffect, useState } from "react";
import { House, Menu, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ActivityPanel } from "@/components/activity-panel";
import { SafetySwitches } from "@/components/room-controls";
import { ageText, ageTone } from "@/lib/controller-health";
import { roomStatus } from "@/lib/model";
import type { Controller } from "@/lib/types";
import "./app-header.css";

/** The frame's top bar on every page: each room as a status dot and a short state (the selected one
 * pressed; another one opens it), how old the selected room's controller data is, the recent
 * records and refresh, and the room's two safety switches. */
export function AppHeader({
  controller,
  haMenu,
  openNavigation,
  selectRoom,
  openLog,
  refresh,
  refreshing,
}: {
  controller: Controller;
  /** Opens Home Assistant's own menu, when the dashboard runs inside it. */
  haMenu: (() => void) | null;
  openNavigation: () => void;
  selectRoom: (id: string) => void;
  openLog: () => void;
  refresh: () => void;
  refreshing: boolean;
}) {
  const [, tick] = useState(0);
  useEffect(() => {
    // Ages keep counting between snapshots, and a silent controller sends none.
    const timer = window.setInterval(() => tick((value) => value + 1), 15_000);
    return () => window.clearInterval(timer);
  }, []);
  const now = Date.now();
  const rooms = controller.rooms.map((room) => ({
    room,
    status: roomStatus(controller.states, room, now),
  }));
  const selected = rooms.find((item) => item.room.id === controller.roomId)?.status;
  const age = selected?.reportedAt == null ? null : now - selected.reportedAt;
  const { connection } = controller;
  return (
    <header className="topbar" data-connection={connection}>
      {haMenu && (
        <Button
          variant="ghost"
          size="icon"
          aria-label="Open Home Assistant menu"
          title="Home Assistant menu"
          onClick={haMenu}
        >
          <House size={20} />
        </Button>
      )}
      <Button
        className="mobile-menu"
        variant="ghost"
        size="icon"
        aria-label="Open navigation"
        onClick={openNavigation}
      >
        <Menu size={21} />
      </Button>
      <div className="room-chips" role="group" aria-label="Rooms">
        {rooms.map(({ room, status }) => {
          const current = room.id === controller.roomId;
          const roomAge = status.reportedAt === null ? null : now - status.reportedAt;
          return (
            <button
              type="button"
              key={room.id}
              className="room-chip"
              data-tone={status.tone}
              data-room={room.id}
              aria-pressed={current}
              title={`${room.name}: ${status.text}. ${status.detail}${
                roomAge === null ? "" : ` Data ${ageText(roomAge)} old.`
              }${current ? "" : " Select to open this room."}`}
              onClick={() => {
                if (!current) selectRoom(room.id);
              }}
            >
              <span className="room-chip-dot" aria-hidden="true" />
              <span className="room-chip-words">
                <span className="room-chip-name">{room.name}</span>
                <span className="room-chip-state">{status.text}</span>
              </span>
            </button>
          );
        })}
      </div>
      <div className="connection-info">
        {controller.demo && (
          <span
            className="demo-pill"
            title="Sample readings: try any setting safely. Changes stay in this tab, and no live equipment is connected."
          >
            Demo<span className="wide-only"> data</span>
          </span>
        )}
        <span
          className="data-age"
          data-age={connection === "offline" ? "red" : ageTone(age)}
          title="How old the selected room's latest controller report is"
        >
          {connection === "offline" ? (
            "Offline"
          ) : connection === "connecting" ? (
            "Connecting…"
          ) : age === null ? (
            "No controller data"
          ) : (
            <>
              <span className="wide-only">Data </span>
              {ageText(age)}
              <span className="wide-only"> old</span>
            </>
          )}
        </span>
        <ActivityPanel controller={controller} openLog={openLog} />
        <Button
          variant="ghost"
          size="icon"
          aria-label="Refresh controller data"
          disabled={refreshing || connection === "connecting"}
          onClick={refresh}
        >
          <RefreshCw size={17} className={refreshing ? "spin" : ""} />
        </Button>
        <SafetySwitches controller={controller} />
      </div>
    </header>
  );
}
