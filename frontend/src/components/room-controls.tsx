import { useState } from "react";
import { Power, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ReviewDialog, Status } from "@/components/dashboard";
import {
  autoFrozenReason,
  autoHoldText,
  autoStateLabel,
  autoStatusText,
  type AutoSetpointStatus,
} from "@/lib/auto-setpoints";
import type { Controller } from "@/lib/types";
import "./room-controls.css";

const writable = (controller: Controller, entityId: string | null) =>
  !!entityId &&
  ["on", "off"].includes(controller.states[entityId]?.state ?? "") &&
  ["live", "demo"].includes(controller.connection);

/** Room On/Off. Hidden when the controller has no room switch (the room is then on).
 * Writes go through the shared review dialog: turn_on/turn_off, then readback. */
export function RoomPower({
  controller,
  showStatus = true,
}: {
  controller: Controller;
  showStatus?: boolean;
}) {
  const [review, setReview] = useState(false);
  const { room } = controller;
  if (!room.roomActiveEntity) return null;
  const on = room.roomActive;
  const name = room.room.name;
  return (
    <>
      <div className="room-power" role="group" aria-label={`${name} on or off`}>
        {showStatus && <Status enabled={on ? true : null} label={on ? "Room on" : "Room off"} />}
        <Button
          variant="outline"
          size="sm"
          disabled={!writable(controller, room.roomActiveEntity)}
          onClick={() => setReview(true)}
        >
          <Power size={15} />
          {on ? "Switch room off…" : "Switch room on…"}
        </Button>
      </div>
      <ReviewDialog
        open={review}
        onOpenChange={setReview}
        controller={controller}
        title={on ? `Switch ${name} off?` : `Switch ${name} on?`}
        items={[
          {
            change: { entityId: room.roomActiveEntity, value: !on },
            label: `${name} room status`,
            before: on ? "On" : "Off",
            after: on ? "Off" : "On",
          },
        ]}
        note={
          on
            ? `Nothing growing in ${name}? Irrigation and alerts stop until you switch it back on.`
            : "Back on within a day, it carries on where it was. After longer, it starts a fresh run: daily counters and learned phase state reset."
        }
      />
    </>
  );
}

/** Calm, page-independent reminder that the selected room is off. */
export function RoomOffBanner({ controller }: { controller: Controller }) {
  if (!controller.roomId || controller.room.roomActive) return null;
  return (
    <div className="room-off-banner" role="status">
      <Power size={18} aria-hidden="true" />
      <div>
        <strong>Room off – no irrigation, no alerts</strong>
        <p>
          Nothing is growing in {controller.room.room.name}. Readings are still shown, but the
          engine will not water this room or raise alerts for it.
        </p>
      </div>
      <RoomPower controller={controller} showStatus={false} />
    </div>
  );
}

/** Room-level Auto setpoints On/Off. Hidden when the controller has no such switch. */
export function AutoSetpointsControl({ controller }: { controller: Controller }) {
  const [review, setReview] = useState(false);
  const { entityId, enabled } = controller.room.autoSetpoints;
  if (!entityId) return null;
  const name = controller.room.room.name;
  return (
    <>
      <div className="room-power" role="group" aria-label={`${name} auto setpoints`}>
        <Status
          enabled={enabled === true ? true : null}
          label={
            enabled === true
              ? "Auto setpoints on"
              : enabled === false
                ? "Auto setpoints off"
                : "Auto setpoints unavailable"
          }
        />
        <Button
          variant="outline"
          size="sm"
          disabled={!writable(controller, entityId)}
          onClick={() => setReview(true)}
        >
          <Sparkles size={15} />
          {enabled ? "Turn auto off…" : "Turn auto on…"}
        </Button>
      </div>
      <ReviewDialog
        open={review}
        onOpenChange={setReview}
        controller={controller}
        title={enabled ? "Turn auto setpoints off?" : "Turn auto setpoints on?"}
        items={[
          {
            change: { entityId, value: !enabled },
            label: `${name} auto setpoints`,
            before: enabled ? "On" : "Off",
            after: enabled ? "Off" : "On",
          },
        ]}
        note={
          enabled
            ? "The engine still fires every shot. Managed setpoints will no longer be rewritten automatically; they keep their current values until you change them."
            : "The engine still fires every shot. Managed setpoints will be rewritten automatically from what the probes do, so manual edits to those fields will be overwritten."
        }
      />
    </>
  );
}

const STATE_CLASS: Record<AutoSetpointStatus["state"], string> = {
  tracking: "status-good",
  learning: "status-good",
  frozen: "status-paused",
  off: "status-neutral",
  unavailable: "status-neutral",
};
/** Per-zone supervisor status: state (and why it is frozen), learned peak, last change, Jev. */
export function AutoZoneChip({ status, name }: { status: AutoSetpointStatus; name?: string }) {
  const hold = autoHoldText(status),
    reason = autoFrozenReason(status);
  return (
    <div className="auto-chip" data-auto-state={status.state} title={autoStatusText(status)}>
      <Badge variant="outline" className={STATE_CLASS[status.state]}>
        <span className="status-dot" />
        {name ? `${name} · ` : ""}Auto · {autoStateLabel(status.state)}
      </Badge>
      {reason && (
        <span>
          Frozen because <b>{reason}</b>
        </span>
      )}
      <span>
        Learned peak{" "}
        <b>{status.learnedPeak === null ? "not yet known" : `${status.learnedPeak.toFixed(1)}%`}</b>
        {hold ? ` (${hold})` : ""}
      </span>
      <span>
        Last change <b>{status.lastChange ?? "none yet"}</b>
      </span>
      <span>
        Jev: <b>{status.jev ?? "not reported"}</b>
      </span>
    </div>
  );
}
export function AutoBadge() {
  return (
    <Badge variant="outline" className="auto-badge" title="Managed by auto setpoints">
      <Sparkles aria-hidden="true" />
      Auto
    </Badge>
  );
}
