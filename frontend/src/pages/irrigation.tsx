import { useCallback, useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Heading, type Page } from "@/components/dashboard";
import { featureOf, roomOnlyFeature, useHashFeature } from "@/lib/feature-focus";
import type { Controller } from "@/lib/types";
import { Strategy, type Drafts } from "./strategy";
import { GrowPlanner } from "./grow-planner";
import "./irrigation.css";

export function Irrigation({
  controller,
  drafts,
  setDrafts,
  onDirtyChange,
  zoneId,
  initialView = "current",
  navigate,
}: {
  controller: Controller;
  drafts: Drafts;
  setDrafts: React.Dispatch<React.SetStateAction<Drafts>>;
  onDirtyChange: (dirty: boolean) => void;
  zoneId?: number;
  initialView?: "current" | "calendar";
  navigate: (page: Page) => void;
}) {
  const [view, setView] = useState(initialView);
  const [zone, setZone] = useState(zoneId ?? controller.room.zones[0]?.id ?? 1);
  const [roomScope, setRoomScope] = useState(() =>
    roomOnlyFeature(featureOf(window.location.hash)),
  );
  // A `?feature=` link opens the room for a room-only feature, the zone for any other.
  const feature = useHashFeature();
  useEffect(() => {
    if (!feature) return;
    setRoomScope(roomOnlyFeature(feature));
    if (roomOnlyFeature(feature)) setView("current");
  }, [feature]);
  const [canvas, setCanvas] = useState<HTMLDivElement | null>(null);
  const [reviewSlot, setReviewSlot] = useState<HTMLDivElement | null>(null);
  const [scheduleDirty, setScheduleDirty] = useState(false);
  const [canonicalDirty, setCanonicalDirty] = useState(false);
  useEffect(() => setView(initialView), [initialView]);
  useEffect(() => {
    if (zoneId !== undefined) setZone(zoneId);
  }, [zoneId]);
  useEffect(() => {
    setZone((current) =>
      controller.room.zones.some((item) => item.id === current)
        ? current
        : (controller.room.zones[0]?.id ?? current),
    );
  }, [controller.room.zones]);
  useLayoutEffect(() => {
    onDirtyChange(scheduleDirty || canonicalDirty);
    return () => onDirtyChange(false);
  }, [scheduleDirty, canonicalDirty, onDirtyChange]);
  // A single visible canvas receives the active editor's validated planning component.
  // Both editor instances stay mounted: changing context must never discard a local draft.
  const currentCurve = useCallback(
    (curve: ReactNode) => (canvas && view === "current" ? createPortal(curve, canvas) : null),
    [canvas, view],
  );
  // Current day's Review & apply bar spans the canvas and the table.
  const currentReview = useCallback(
    (bar: ReactNode) => (reviewSlot && view === "current" ? createPortal(bar, reviewSlot) : null),
    [reviewSlot, view],
  );
  const calendarCurve = useCallback(
    (curve: ReactNode) => (canvas && view === "calendar" ? createPortal(curve, canvas) : null),
    [canvas, view],
  );
  const engaged = controller.room.strategy.engaged;
  const source = engaged
    ? "armed schedule"
    : controller.room.autoSetpoints.enabled === true
      ? "automatic setpoints"
      : controller.room.autoSetpoints.enabled === false
        ? "manual room targets"
        : "current room targets · automation state unavailable";
  return (
    <div className="irrigation-workspace" data-view={view}>
      <Heading
        title="Irrigation"
        description="Review current targets and plan future grow days for the same zone."
      />
      <div className="irrigation-context">
        <label htmlFor="irrigation-zone">Zone</label>
        <select
          id="irrigation-zone"
          value={roomScope && view === "current" ? "room" : zone}
          onChange={(event) => {
            const room = event.target.value === "room";
            setRoomScope(room);
            if (room) setView("current");
            else setZone(Number(event.target.value));
          }}
        >
          {controller.room.zones.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
          <option value="room">Room lights &amp; shared targets</option>
        </select>
        <nav className="zone-switcher" aria-label="Irrigation views">
          <button
            type="button"
            aria-current={view === "current" ? "page" : undefined}
            onClick={() => setView("current")}
          >
            Current day{Object.keys(drafts).length ? ` (${Object.keys(drafts).length})` : ""}
          </button>
          <button
            type="button"
            aria-current={view === "calendar" ? "page" : undefined}
            onClick={() => {
              setView("calendar");
              setRoomScope(false);
            }}
          >
            Calendar{scheduleDirty ? " · unsaved" : ""}
          </button>
        </nav>
      </div>
      <p className="irrigation-source" role="status">
        <strong>Target source: {source}.</strong>{" "}
        {view === "calendar"
          ? "Calendar edits are schedule drafts. Save, review and arm through the schedule controls."
          : engaged
            ? "The schedule owns current targets; current-day editing is locked."
            : "Current-day edits are local drafts until reviewed and applied."}
      </p>
      <div className="irrigation-body">
        <div
          className="irrigation-canvas"
          ref={setCanvas}
          aria-label="Selected zone VWC and EC planning canvas"
        />
        <div hidden={view !== "current"}>
          <Strategy
            controller={controller}
            drafts={drafts}
            setDrafts={setDrafts}
            selectedZone={roomScope ? "room" : zone}
            navigate={navigate}
            embedded
            active={view === "current"}
            renderCurve={currentCurve}
            renderReview={currentReview}
            onCanonicalDirtyChange={setCanonicalDirty}
          />
        </div>
        <div hidden={view !== "calendar"}>
          <GrowPlanner
            controller={controller}
            onDirtyChange={setScheduleDirty}
            selectedZone={zone}
            onZoneChange={setZone}
            embedded
            active={view === "calendar"}
            renderCurve={calendarCurve}
          />
        </div>
      </div>
      <div className="irrigation-review" ref={setReviewSlot} />
    </div>
  );
}
