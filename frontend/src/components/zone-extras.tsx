import { useEffect, useState } from "react";
import { blockForDay, growDay, localDate } from "@/lib/grow-plan";
import type { StrategyDocument } from "@/lib/operator-types";
import { climateBands } from "@/lib/plan-reference";
import { growDay as lightsDay } from "@/lib/day-timeline";
import { Camera, Droplets } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ReviewDialog, time as clock } from "@/components/dashboard";
import { GaugeRow } from "@/components/hmi";
import { UiTip } from "@/components/info-tip";
import { Pill } from "@/components/mini-visuals";
import { gauge } from "@/lib/hmi";
import { descriptor, numeric } from "@/lib/model";
import { UI_COPY } from "@/lib/ste-copy";
import { climateReadings, hardwarePanelId, mappedDevices, rootZoneSensor } from "@/lib/zone-extras";
import type { Controller, Zone } from "@/lib/types";
import "./zone-extras.css";

/** Settings › Display › Room climate: air temperature, humidity, VPD and the dew point worked out from
 * the first two, as grey gauges (ISA-101). Only the sensors the room maps; none mapped, no panel. */
export function ClimatePanel({ controller, zone }: { controller: Controller; zone: number }) {
  const bands = usePlanBands(controller, zone);
  const readings = climateReadings(controller.states, controller.room.room, bands);
  if (!readings.length) return null;
  return (
    <section className="panel zone-extra" aria-labelledby="zone-climate-title" data-zone-climate>
      <div className="panel-heading">
        <h2 id="zone-climate-title" className="label-with-tip">
          Room climate <UiTip copyKey="room climate" />
        </h2>
      </div>
      <GaugeRow
        label="Room climate"
        gauges={readings.map((reading) => ({
          id: reading.key,
          model: gauge({
            label: reading.label,
            value: reading.value,
            unit: reading.unit,
            digits: reading.digits,
            band: reading.band,
          }),
        }))}
      />
    </section>
  );
}

/** With Settings › Display › Reference rows on: today's climate bands from the room's grow plan, for
 * this zone (its block's profile), the temperature band by the lights. None without a plan. */
function usePlanBands(controller: Controller, zone: number) {
  const on = controller.room.display.options.planner_reference_rows;
  const [plan, setPlan] = useState<StrategyDocument | null>(null);
  useEffect(() => {
    if (!on || !["live", "demo"].includes(controller.connection)) return;
    let current = true;
    controller
      .operator<StrategyDocument>("strategy_get")
      .then((doc) => current && setPlan(doc))
      .catch(() => current && setPlan(null));
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on, controller.roomId, controller.connection]);
  if (!on || !plan) return {};
  const assignment = plan.plan.zones.find((item) => item.zone_id === zone);
  if (!assignment) return {};
  const block = blockForDay(assignment, growDay(assignment.start_date, localDate()));
  const profile = plan.plan.profiles.find((item) => item.id === block?.profile_id);
  const prefix = controller.room.room.prefix;
  const day = lightsDay(
    numeric(controller.states[`number.crop_steering_${prefix}lights_on_hour`]),
    numeric(controller.states[`number.crop_steering_${prefix}lights_off_hour`]),
    Date.now(),
    controller.timeZone,
  );
  return climateBands(profile?.reference, day ? Date.now() < day.lightsOff : true);
}

/** Settings › Display › Root-zone temperature: the zone's mapped probe as one grey gauge. */
export function RootZonePanel({ controller, zone }: { controller: Controller; zone: Zone }) {
  const id = rootZoneSensor(controller.states, controller.room.room, zone.id);
  if (!id) return null;
  const entity = controller.states[id];
  const unit = String(entity?.attributes.unit_of_measurement || "°C");
  return (
    <section className="panel zone-extra" aria-labelledby="zone-root-title" data-zone-root>
      <div className="panel-heading">
        <h2 id="zone-root-title" className="label-with-tip">
          Root zone <UiTip copyKey="root-zone temperature" />
        </h2>
      </div>
      <GaugeRow
        label="Root zone"
        gauges={[
          {
            id: "root-temperature",
            model: gauge({ label: "Temperature", value: numeric(entity), unit }),
          },
        ]}
      />
    </section>
  );
}

/** Settings › Display › Room camera: the room's mapped camera, a still image Home Assistant renews
 * every 30 s while this page is in view (none while the tab is hidden). */
export function CameraCard({ controller }: { controller: Controller }) {
  const id = descriptor(controller.states, controller.room.room)?.attributes.camera_entity;
  const entity = typeof id === "string" && id ? controller.states[id] : undefined;
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") setTick((value) => value + 1);
    }, 30_000);
    return () => window.clearInterval(timer);
  }, []);
  if (!entity) return null;
  const picture = entity.attributes.entity_picture;
  const src =
    typeof picture === "string" && picture
      ? picture.startsWith("data:")
        ? picture
        : `${picture}${picture.includes("?") ? "&" : "?"}_=${tick}`
      : null;
  const name = String(entity.attributes.friendly_name || entity.entity_id);
  return (
    <section className="panel zone-extra zone-camera" aria-labelledby="zone-camera-title" data-zone-camera>
      <div className="panel-heading">
        <h2 id="zone-camera-title" className="label-with-tip">
          <Camera size={16} aria-hidden="true" /> Camera <UiTip copyKey="room camera" />
        </h2>
      </div>
      {src ? (
        <img src={src} alt={`${name}, still image`} loading="lazy" />
      ) : (
        <p className="small muted">The camera does not supply an image now.</p>
      )}
    </section>
  );
}

/** The room's Hardware panel switch (switch.crop_steering_<prefix>manual_hardware_enabled) ON: the
 * zone's Test shot, run by the controller through every safety check of a shot, and what the mapped
 * valves, pump and lights read now. Nothing here opens or closes a device directly. */
export function HardwarePanel({ controller, zone }: { controller: Controller; zone: Zone }) {
  const [review, setReview] = useState(false);
  const [sent, setSent] = useState("");
  const panel = controller.states[hardwarePanelId(controller.room.room.prefix)];
  if (panel?.state !== "on") return null;
  const devices = mappedDevices(controller.states, controller.room.room, zone.id);
  const connected = ["live", "demo"].includes(controller.connection);
  const copy = UI_COPY["test shot"];
  return (
    <section className="panel zone-extra" aria-labelledby="zone-hardware-title" data-zone-hardware>
      <div className="panel-heading">
        <h2 id="zone-hardware-title" className="label-with-tip">
          Hardware <UiTip copyKey="hardware panel" />
        </h2>
        <Button
          variant="outline"
          size="sm"
          disabled={!connected || controller.admin === false}
          onClick={() => setReview(true)}
        >
          <Droplets size={15} aria-hidden="true" /> Test shot
        </Button>
      </div>
      {sent && (
        <p className="small muted" role="status">
          Test shot asked at {clock(sent)}. The controller runs it when Watering is on.
        </p>
      )}
      <ul className="zone-devices" aria-label="Mapped devices">
        {devices.map((device) => (
          <li key={device.entityId} data-device={device.role}>
            <span>{device.label}</span>
            <Pill
              dot
              tone={device.on === true ? "on" : device.on === false ? "neutral" : "unknown"}
              title={device.entityId}
            >
              {device.on === true ? "On" : device.on === false ? "Off" : "Unknown"}
            </Pill>
            <span className="small muted">{device.since ? `since ${clock(device.since)}` : ""}</span>
          </li>
        ))}
      </ul>
      <ReviewDialog
        open={review}
        onOpenChange={setReview}
        controller={controller}
        title="Review the test shot"
        items={[
          {
            change: { entityId: `button.crop_steering_${controller.room.room.prefix}zone_${zone.id}_test_shot`, value: true },
            label: `${zone.name} test shot`,
            before: "No shot",
            after: "10 s shot",
          },
        ]}
        note={copy.tooltip}
        caution={copy.caution}
        run={async () => {
          const result = await controller.operator<{ requested: string | null }>("test_shot", {
            room_id: "room:" + controller.room.room.prefix,
            zone: zone.id,
          });
          setSent(result.requested || new Date().toISOString());
        }}
      />
    </section>
  );
}
