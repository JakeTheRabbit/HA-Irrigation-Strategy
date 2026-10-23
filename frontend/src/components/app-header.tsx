import { useEffect, useState } from "react";
import { ArrowRight, House, Menu, RefreshCw, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ActivityPanel } from "@/components/activity-panel";
import { UiTip } from "@/components/info-tip";
import { BrainChip } from "@/components/brain";
import { SafetySwitches } from "@/components/room-controls";
import { CommandPalette } from "@/components/command-palette";
import type { PaletteEntry } from "@/lib/command-palette";
import { ageTone, updatedText } from "@/lib/controller-health";
import { roomStatus, staleBanner } from "@/lib/model";
import type { Controller } from "@/lib/types";
import "./app-header.css";

/** The frame's top bar on every page: how old the selected room's controller data is, the AI
 * assistant's state, Jump to… (the palette), the recent records and refresh, then the selected
 * room's name and its two safety switches. The room tree is the room picker, so no room chips.
 * A phone leads with the page's title over the data's age and the AI's state. */
export function AppHeader({
  controller,
  title,
  roomName,
  haMenu,
  openNavigation,
  jump,
  openLog,
  openBrain,
  refresh,
  refreshing,
}: {
  controller: Controller;
  /** The open page's title, the phone header's first line. */
  title: string;
  /** The selected room, named beside the switches that act on it. */
  roomName: string;
  /** Opens Home Assistant's own menu, when the dashboard runs inside it. */
  haMenu: (() => void) | null;
  openNavigation: () => void;
  /** Opens what the palette picked. */
  jump: (entry: PaletteEntry) => void;
  openLog: () => void;
  /** Opens the AI assistant page. */
  openBrain: () => void;
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
  const room = controller.rooms.find((item) => item.id === controller.roomId);
  const selected = room ? roomStatus(controller.states, room, now) : undefined;
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
      <div className="topbar-status">
        <span className="topbar-title">{title}</span>
        <span className="topbar-facts">
          {controller.demo && (
            <span
              className="demo-pill"
              title="Sample readings. The dashboard shows sample readings. Your changes stay in this browser tab. The dashboard connects to no live equipment."
            >
              Demo<span className="wide-only"> data</span>
            </span>
          )}
          <span
            className="data-age"
            data-age={connection === "offline" ? "red" : ageTone(age)}
            title="Age of the latest report. The time since the controller of the selected room sent its latest report."
          >
            {connection === "offline"
              ? "Offline"
              : connection === "connecting"
                ? "Connecting…"
                : age === null
                  ? "No controller data"
                  : updatedText(age)}
          </span>
          <span className="topbar-facts-dot" aria-hidden="true">
            ·
          </span>
          <BrainChip controller={controller} open={openBrain} />
        </span>
      </div>
      <div className="connection-info">
        <CommandPalette controller={controller} jump={jump} />
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
        <span
          className="header-safety-scope"
          title="Watering and stop controls apply only to this selected room"
        >
          {roomName}
        </span>
        <SafetySwitches controller={controller} />
      </div>
    </header>
  );
}

/** One full-width band under the header while the selected room's controller is not reporting:
 * the numbers on the page are its last report. It links to the probes, which say what reports. */
export function StaleBanner({
  controller,
  openProbes,
}: {
  controller: Controller;
  openProbes: () => void;
}) {
  const words = staleBanner(controller.states, controller.room.room);
  if (words === null) return null;
  return (
    <div className="stale-banner" role="status">
      <TriangleAlert size={16} aria-hidden="true" />
      <p>{words}</p>
      <button type="button" className="stale-banner-link" onClick={openProbes}>
        Probes <ArrowRight size={14} aria-hidden="true" />
      </button>
      <UiTip copyKey="probes" />
    </div>
  );
}
