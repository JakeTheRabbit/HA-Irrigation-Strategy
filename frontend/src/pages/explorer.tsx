import { AskWhy } from "@/components/ask-why";
import { DayLanes } from "@/components/day-lanes";
import { HistoryExplorer, RoomExplorer } from "@/components/history-explorer";
import { OnThisDay } from "@/components/on-this-day";
import { RecordedBehaviour } from "@/components/recorded-behaviour";
import type { Controller } from "@/lib/types";
import "./explorer.css";

/** History › Explorer (mockup 09): the room's readings on stacked charts under its phase and shot
 * lanes, notes where something happened, one crosshair, the last run beside it and a CSV of what is
 * charted. A zone picked in the room list adds its probes, its targets and its other grows below.
 * Who changed which setting lives on History › Changes. */
export function Explorer({ controller, zone }: { controller: Controller; zone?: number }) {
  const { room } = controller;
  const picked = room.zones.find((item) => item.id === zone);
  return (
    <>
      <RoomExplorer key={controller.roomId} controller={controller} zone={picked?.id} />
      {room.display.options.show_equipment_lanes && <DayLanes controller={controller} mode="equipment" />}
      {room.display.options.show_room_day_lanes && <DayLanes controller={controller} mode="zones" />}
      {picked ? (
        <details className="explorer-zone" open data-zone-detail={picked.id}>
          <summary>{picked.name}: each probe, its targets and other grows</summary>
          <HistoryExplorer key={`${controller.roomId}-${picked.id}`} controller={controller} zone={picked} />
          <RecordedBehaviour key={`targets-${controller.roomId}-${picked.id}`} controller={controller} zone={picked} />
          <OnThisDay key={`on-this-day-${controller.roomId}-${picked.id}`} controller={controller} zone={picked} />
        </details>
      ) : (
        <p className="muted small explorer-zone-hint">
          Pick a zone in the room list to see each of its probes, its targets and its other grows.
        </p>
      )}
      <AskWhy controller={controller} zone={picked?.id} />
    </>
  );
}
