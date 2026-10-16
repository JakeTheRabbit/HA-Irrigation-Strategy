import { useState } from "react";
import { Droplets, Power, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ReviewDialog, Status } from "@/components/dashboard";
import { UiTip } from "@/components/info-tip";
import { UI_COPY } from "@/lib/ste-copy";
import { allZones, allZonesChanges } from "@/lib/all-zones";
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

/** The confirmation for switching the room on or off, wherever the switch is offered. */
function RoomDialog({
  controller,
  open,
  onOpenChange,
}: {
  controller: Controller;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { room } = controller;
  if (!room.roomActiveEntity) return null;
  const on = room.roomActive;
  const name = room.room.name;
  return (
    <ReviewDialog
      open={open}
      onOpenChange={onOpenChange}
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
          ? `Set ${name} to off only when no plants are in it. Off: the controller does not water the room and sends no alerts for it.`
          : "On within one day: the room continues from where it stopped. On after more than one day: the counters and the phase data reset."
      }
    />
  );
}

/** The confirmation for switching the room's watering (its engine switch) on or off. */
function WateringDialog({
  controller,
  open,
  onOpenChange,
}: {
  controller: Controller;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { engine, room } = controller.room;
  return (
    <ReviewDialog
      open={open}
      onOpenChange={onOpenChange}
      controller={controller}
      title="Review the kill switch"
      items={
        engine.entityId
          ? [
              {
                change: { entityId: engine.entityId, value: !engine.enabled },
                label: `${room.name} watering`,
                before: engine.enabled ? "On" : "Off",
                after: engine.enabled ? "Off" : "On",
              },
            ]
          : []
      }
      note={UI_COPY["review watering"].impact}
      warning={UI_COPY["review watering"].warning}
      caution={UI_COPY["review watering"].caution}
    />
  );
}

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
  return (
    <>
      <div className="room-power" role="group" aria-label={`${room.room.name} on or off`}>
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
      <RoomDialog controller={controller} open={review} onOpenChange={setReview} />
    </>
  );
}

/** Watering On/Off: the room's engine switch, with its state. */
export function WateringPower({ controller }: { controller: Controller }) {
  const [review, setReview] = useState(false);
  const { engine } = controller.room;
  return (
    <>
      <div className="split-row">
        <Status
          enabled={engine.enabled}
          label={
            engine.enabled === true
              ? "Watering on"
              : engine.enabled === false
                ? "Watering off"
                : undefined
          }
        />
        <Button
          variant="outline"
          disabled={
            !engine.entityId ||
            engine.enabled === null ||
            !["live", "demo"].includes(controller.connection)
          }
          onClick={() => setReview(true)}
        >
          {engine.enabled ? "Switch watering off…" : "Switch watering on…"}
        </Button>
      </div>
      <WateringDialog controller={controller} open={review} onOpenChange={setReview} />
    </>
  );
}

/** The selected room's two safety switches, in the header of every page: its watering and the
 * room itself, each through the same confirmation as in Settings. On a phone, icons with a dot. */
export function SafetySwitches({ controller }: { controller: Controller }) {
  const [review, setReview] = useState<"watering" | "room" | null>(null);
  const { room } = controller;
  if (!controller.roomId) return null;
  const watering = room.engine.enabled;
  const wateringState = watering === true ? "on" : watering === false ? "off" : "unknown";
  const wateringWords =
    watering === true ? "Watering on" : watering === false ? "Watering off" : "Watering unknown";
  const on = room.roomActive;
  return (
    <div className="safety-switches" role="group" aria-label={`${room.room.name} safety switches`}>
      <button
        type="button"
        className="safety-switch"
        data-safety="watering"
        data-state={wateringState}
        aria-label={
          watering === null
            ? `${wateringWords}: the switch is unavailable`
            : `${wateringWords}: ${watering ? "switch watering off…" : "switch watering on…"}`
        }
        title={
          watering === null
            ? "This room's watering switch is missing or unavailable in Home Assistant."
            : watering
              ? "The controller can water this room. Set the switch to off, and the controller gives no shots."
              : "The controller opens no valve in this room. Set the switch to on, and the controller can water again."
        }
        disabled={
          !room.engine.entityId ||
          watering === null ||
          !["live", "demo"].includes(controller.connection)
        }
        onClick={() => setReview("watering")}
      >
        <Droplets size={15} aria-hidden="true" />
        <span className="safety-switch-dot" aria-hidden="true" />
        <span className="safety-switch-text">{wateringWords}</span>
      </button>
      {room.roomActiveEntity && (
        <button
          type="button"
          className="safety-switch"
          data-safety="room"
          data-state={on ? "on" : "off"}
          aria-label={`${on ? "Room on" : "Room off"}: ${on ? "switch room off…" : "switch room on…"}`}
          title={
            on
              ? "Set the room to off when no plants are in it: no shots and no alerts."
              : "No plants in the room: no shots and no alerts. Set it to on for the next crop."
          }
          disabled={!writable(controller, room.roomActiveEntity)}
          onClick={() => setReview("room")}
        >
          <Power size={15} aria-hidden="true" />
          <span className="safety-switch-dot" aria-hidden="true" />
          <span className="safety-switch-text">{on ? "Room on" : "Room off"}</span>
        </button>
      )}
      <WateringDialog
        controller={controller}
        open={review === "watering"}
        onOpenChange={(open) => setReview(open ? "watering" : null)}
      />
      <RoomDialog
        controller={controller}
        open={review === "room"}
        onOpenChange={(open) => setReview(open ? "room" : null)}
      />
    </div>
  );
}

/** Every zone of the room at once, in the zones' heading, as Home Assistant's entities card has
 * its header toggle: on while any zone is on. Switching it reviews switching every zone the same
 * way, a zone paused on purpose included; each zone keeps its own switch in its details. */
export function AllZonesSwitch({ controller }: { controller: Controller }) {
  const { zones } = controller.room;
  const state = allZones(zones);
  const enable = state.checked === false;
  const items = allZonesChanges(zones, enable);
  const connected = ["live", "demo"].includes(controller.connection);
  // The review keeps what it was opened with: its own writes move the zones under it.
  const [review, setReview] = useState(false);
  const [opened, setOpened] = useState({ enable, items });
  return (
    <span className="all-zones" data-all-zones={state.checked ?? "unknown"}>
      <span className="all-zones-count">
        {state.checked === null ? "Zones unavailable" : `${state.on} of ${state.known} zones on`}
      </span>
      <button
        type="button"
        role="switch"
        className="switch"
        aria-checked={state.checked === true}
        aria-label={`Every zone in ${controller.room.room.name}`}
        disabled={!connected || !items.length}
        onClick={() => {
          setOpened({ enable, items });
          setReview(true);
        }}
      >
        <span className="switch-thumb" aria-hidden="true" />
      </button>
      <UiTip copyKey="every zone in {x}" values={[controller.room.room.name]} />
      <ReviewDialog
        open={review}
        onOpenChange={setReview}
        controller={controller}
        title={opened.enable ? "Switch every zone on" : "Pause every zone"}
        items={opened.items}
        note={
          opened.enable
            ? "Every zone is switched on, including any you had paused. The controller waters them from its next check."
            : "Paused, a zone gets no water, not even a rescue shot. Switch them back on here, or one at a time from each zone."
        }
      />
    </span>
  );
}

/** Calm reminder that the selected room is off. */
export function RoomOffBanner({ controller }: { controller: Controller }) {
  if (!controller.roomId || controller.room.roomActive) return null;
  return (
    <div className="room-off-banner" role="status">
      <Power size={18} aria-hidden="true" />
      <div>
        <strong>Room off – no shots, no alerts</strong>
        <p>
          No plants are in {controller.room.room.name}. The dashboard still shows the readings, but
          the controller does not water this room or send alerts for it.
        </p>
      </div>
      <RoomPower controller={controller} showStatus={false} />
    </div>
  );
}

/** Room-level Auto setpoints On/Off. Hidden when the controller has no such switch. With the AI assistant's
 * Setpoints judge on the room, the switch is what lets the AI assistant move each zone's P2 shot size and
 * re-water point, and it says so. */
export function AutoSetpointsControl({
  controller,
  jevManaged = false,
}: {
  controller: Controller;
  /** The AI assistant's Setpoints judge runs on this room (a zone's AI assistant sensor says it manages its setpoints). */
  jevManaged?: boolean;
}) {
  const [review, setReview] = useState(false);
  const { entityId, enabled } = controller.room.autoSetpoints;
  if (!entityId) return null;
  const name = controller.room.room.name;
  const what = jevManaged ? "AI assistant: P2 shot size, re-water point" : "Auto setpoints";
  return (
    <>
      <div className="room-power" role="group" aria-label={`${name} auto setpoints`}>
        <Status
          enabled={enabled === true ? true : null}
          label={
            jevManaged
              ? enabled === true
                ? what
                : enabled === false
                  ? "The AI assistant does not change the setpoints"
                  : "AI assistant setpoints unavailable"
              : enabled === true
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
          jevManaged
            ? enabled
              ? "The controller continues to give every shot. The AI assistant stops changes to the P2 shot size and the re-water point of each zone. They keep their current values until you change them."
              : "The controller continues to give every shot. The AI assistant can change the P2 shot size and the re-water point of each zone inside its range, one small step each night. Your own value stays the centre of that range."
            : enabled
              ? "The controller continues to give every shot. The controller stops changes to the managed setpoints. They keep their current values until you change them."
              : "The controller continues to give every shot. The controller changes the managed setpoints from the probe readings, and it replaces a value that you set by hand."
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
/** Per-zone supervisor status: state (and why it is frozen), learned peak, last change, the AI assistant. */
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
        AI assistant: <b>{status.jev ?? "not reported"}</b>
      </span>
    </div>
  );
}
export function AutoBadge() {
  return (
    <Badge
      variant="outline"
      className="auto-badge"
      title="Managed by auto setpoints. Auto setpoints can change this setting."
    >
      <Sparkles aria-hidden="true" />
      Auto
    </Badge>
  );
}
