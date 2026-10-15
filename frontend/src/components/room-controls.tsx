import { useState } from "react";
import { Droplets, Power, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ReviewDialog, Status } from "@/components/dashboard";
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
          ? `Nothing growing in ${name}? Irrigation and alerts stop until you switch it back on.`
          : "Back on within a day, it carries on where it was. After longer, it starts a fresh run: daily counters and learned phase state reset."
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
      title="Review watering"
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
      note="Switching watering off also stops a running shot within a few seconds. It is not an emergency stop: use the installation's physical shut-off for that."
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
              ? "The controller may water this room. Switch it off to stop every shot."
              : "The controller opens no valve in this room. Switch it on to let it water."
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
              ? "Switch the room off when nothing is growing: no irrigation and no alerts."
              : "Nothing is growing: no irrigation and no alerts. Switch it on for the next crop."
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

/** Room-level Auto setpoints On/Off. Hidden when the controller has no such switch. With Jev's
 * Setpoints judge on the room, the switch is what lets Jev move each zone's P2 shot size and
 * re-water point, and it says so. */
export function AutoSetpointsControl({
  controller,
  jevManaged = false,
}: {
  controller: Controller;
  /** Jev's Setpoints judge runs on this room (a zone's Jev sensor says it manages its setpoints). */
  jevManaged?: boolean;
}) {
  const [review, setReview] = useState(false);
  const { entityId, enabled } = controller.room.autoSetpoints;
  if (!entityId) return null;
  const name = controller.room.room.name;
  const what = jevManaged ? "Jev manages the P2 shot size and re-water point" : "Auto setpoints";
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
                  ? "Jev leaves the setpoints alone"
                  : "Jev’s setpoints unavailable"
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
              ? "The engine still fires every shot. Jev stops moving each zone's P2 shot size and re-water point; they keep their current values until you change them."
              : "The engine still fires every shot. Jev may move each zone's P2 shot size and re-water point within its range, one small step a night; your own value stays the centre of that range."
            : enabled
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
