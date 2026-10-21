import { useState } from "react";
import { ArrowRight, Droplets } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Heading, Empty, number } from "@/components/dashboard";
import { Pill } from "@/components/mini-visuals";
import { facilityRooms } from "@/lib/facility";
import { dailyWater, waterParameters } from "@/lib/water-delivery";
import { waitingText } from "@/lib/waiting-for";
import type { Controller } from "@/lib/types";
import type { Page } from "@/lib/routes";
import "./all-zones.css";
const PHASE: Record<string, string> = {
  P0: "Morning dryback",
  P1: "Ramp",
  P2: "Maintenance",
  P3: "Overnight dryback",
};
export function AllZones({
  controller,
  open,
}: {
  controller: Controller;
  open: (room: string, page: Page, zone?: number) => void;
}) {
  const [filter, setFilter] = useState("all");
  const rooms = facilityRooms(controller.states, controller.rooms);
  const clock = (value: string | number) =>
    new Date(value).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: controller.timeZone,
    });
  return (
    <div className="facility">
      <Heading
        title="All rooms"
        description="Every room and zone in one view. Tap a zone for its chart, targets and next action."
        action={
          <label className="facility-filter">
            Show room
            <select
              aria-label="Filter rooms"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="all">All rooms</option>
              {rooms.map((r) => (
                <option key={r.room.id} value={r.room.id}>
                  {r.room.name}
                </option>
              ))}
            </select>
          </label>
        }
      />
      {controller.connection === "offline" && (
        <p className="warning-banner" role="status">
          Connection unavailable. These are the last received readings.
        </p>
      )}
      {!rooms.length && (
        <section className="panel">
          <Empty
            title="No rooms discovered"
            detail="Connect Home Assistant or configure your first room in Equipment."
            action={
              <Button onClick={() => open(controller.roomId, "equipment/setup")}>Open setup</Button>
            }
          />
        </section>
      )}
      {rooms
        .filter((r) => filter === "all" || r.room.id === filter)
        .map(({ room, view, status, tank }) => {
          const scoped = { ...controller, room: view, roomId: room.id };
          const stale = status.tone === "stale" || controller.connection === "offline";
          // The room's water today: the zones' delivered litres added up, and per plant over the
          // plants of the zones that report both.
          let roomL = 0;
          let counted = 0;
          let plantsCounted = 0;
          let litresCounted = 0;
          for (const zone of view.zones) {
            const plants = waterParameters(scoped, zone.id).plant_count;
            const water = dailyWater(zone, plants);
            if (water.zoneL === null) continue;
            roomL += water.zoneL;
            counted += 1;
            if (plants !== null && plants > 0) {
              plantsCounted += plants;
              litresCounted += water.zoneL;
            }
          }
          return (
            <section
              className="facility-room"
              data-facility-room={room.id}
              key={room.id}
              aria-labelledby={"facility-" + room.prefix}
            >
              <div className="facility-room-heading">
                <div>
                  <h2 id={"facility-" + room.prefix}>{room.name}</h2>
                  <Pill
                    tone={
                      stale
                        ? "warn"
                        : !view.roomActive
                          ? "neutral"
                          : view.engine.enabled
                            ? "on"
                            : "warn"
                    }
                  >
                    {stale
                      ? "Last reported"
                      : !view.roomActive
                        ? "Room not in use"
                        : view.engine.enabled
                          ? "Watering enabled"
                          : "Watering paused"}
                  </Pill>
                  <span className="muted">{view.zones.length} zones</span>
                  {counted > 0 && (
                    <span
                      className="facility-room-water"
                      title={
                        counted < view.zones.length
                          ? `${view.zones.length - counted} zones report no delivery yet and are left out.`
                          : "Delivered today across the room's zones."
                      }
                    >
                      Water today <strong>{number(roomL, 1)} L</strong>
                      {plantsCounted > 0 && (
                        <> · {number(litresCounted / plantsCounted, 2)} L per plant</>
                      )}
                    </span>
                  )}
                </div>
                <Button variant="ghost" onClick={() => open(room.id, "today")}>
                  Room overview <ArrowRight size={16} />
                </Button>
              </div>
              {status.tone !== "watering" && (
                <p className="facility-room-status" role="status">
                  {status.text} · {status.detail}
                </p>
              )}
              <div className="facility-zone-grid">
                {view.zones.map((zone) => {
                  const water = dailyWater(zone, waterParameters(scoped, zone.id).plant_count);
                  const waiting =
                    stale || !view.roomActive || !view.engine.enabled || zone.enabled === false
                      ? null
                      : zone.waiting;
                  const next = stale
                    ? "Controller not reporting"
                    : !view.roomActive
                      ? "Room not in use"
                      : view.engine.enabled === false
                        ? "Watering paused"
                        : view.engine.enabled === null
                          ? "Watering state unavailable"
                          : zone.enabled === false
                            ? "Zone paused"
                            : zone.enabled === null
                              ? "Zone enable state unavailable"
                              : waiting
                                ? waitingText(waiting, { number: (n) => number(n), clock })
                                : zone.status || "No next action reported";
                  return (
                    <article
                      className="panel facility-zone"
                      data-facility-zone={`${room.id}/${zone.id}`}
                      key={zone.id}
                    >
                      <div className="facility-zone-title">
                        <h3>
                          <button onClick={() => open(room.id, "zone", zone.id)}>
                            {zone.name}
                            <ArrowRight size={15} />
                          </button>
                        </h3>
                        <Pill tone={zone.enabled === false || zone.stale ? "warn" : "neutral"}>
                          {zone.stale
                            ? "Last reported"
                            : zone.enabled === false
                              ? "Zone paused"
                              : PHASE[zone.phase]
                                ? `${zone.phase} · ${PHASE[zone.phase]}`
                                : "Phase unavailable"}
                        </Pill>
                      </div>
                      {zone.cultivar && <p className="muted">{zone.cultivar}</p>}
                      <dl className="facility-readings">
                        <div>
                          <dt>VWC{stale ? " · last known" : ""}</dt>
                          <dd>
                            {number(zone.vwc.value)}
                            <small>{zone.vwc.value === null ? "" : " %"}</small>
                          </dd>
                        </div>
                        <div>
                          <dt>Pore EC{stale ? " · last known" : ""}</dt>
                          <dd>
                            {number(zone.ec.value, 2)}
                            <small>
                              {zone.ec.value === null ? "" : ` ${zone.ec.unit || "mS/cm"}`}
                            </small>
                          </dd>
                        </div>
                      </dl>
                      <div
                        className="facility-phases"
                        aria-label={`Phase ${PHASE[zone.phase] ? zone.phase : "unavailable"}`}
                      >
                        {["P0", "P1", "P2", "P3"].map((p) => (
                          <span key={p} data-current={p === zone.phase && !stale}>
                            {p}
                          </span>
                        ))}
                      </div>
                      <p className="facility-next">{next}</p>
                      <dl className="facility-facts">
                        <div>
                          <dt>Delivered today · zone</dt>
                          <dd>
                            {water.zoneL === null ? "Unavailable" : `${number(water.zoneL, 2)} L`}
                          </dd>
                        </div>
                        <div>
                          <dt>Average per plant</dt>
                          <dd>
                            {water.mlPerPlant === null
                              ? "Count unavailable"
                              : `${number(water.mlPerPlant / 1000, 2)} L`}
                          </dd>
                        </div>
                        <div>
                          <dt>Last irrigation</dt>
                          <dd>
                            {zone.lastIrrigation.timestamp ? (
                              <time dateTime={zone.lastIrrigation.timestamp}>
                                {new Date(zone.lastIrrigation.timestamp).toLocaleString([], {
                                  month: "short",
                                  day: "numeric",
                                  hour: "2-digit",
                                  minute: "2-digit",
                                  timeZone: controller.timeZone,
                                })}
                              </time>
                            ) : (
                              zone.lastIrrigation.issue || "Not reported"
                            )}
                          </dd>
                        </div>
                      </dl>
                    </article>
                  );
                })}
              </div>
              <button
                className="facility-supply panel"
                onClick={() => open(room.id, "equipment/feed")}
                aria-label={`Open ${room.name} tank and feed`}
              >
                <Droplets size={20} />
                <strong>Feed supply</strong>
                <span>
                  Tank{" "}
                  {tank.level.value === null ? tank.level.issue : `${number(tank.level.value, 0)}%`}
                </span>
                <span>
                  Pump {tank.pump.on === null ? tank.pump.issue : tank.pump.on ? "on" : "off"}
                </span>
                <span>
                  Feed EC{" "}
                  {tank.ec.value === null
                    ? tank.ec.issue
                    : `${number(tank.ec.value, 2)} ${tank.ec.unit}`}
                </span>
                <span>pH {tank.ph.value === null ? tank.ph.issue : number(tank.ph.value, 2)}</span>
                <span>
                  Temperature{" "}
                  {tank.temperature.value === null
                    ? tank.temperature.issue
                    : `${number(tank.temperature.value)} ${tank.temperature.unit}`}
                </span>
                <span>
                  Last fill{" "}
                  {tank.lastFill.timestamp
                    ? new Date(tank.lastFill.timestamp).toLocaleString([], {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                        timeZone: controller.timeZone,
                      })
                    : tank.lastFill.issue}
                </span>
                <ArrowRight size={16} />
              </button>
            </section>
          );
        })}
      <p className="muted facility-note">
        Delivery totals are controller-reported estimates unless backed by a configured meter.
        Per-plant values are averages using the current plant count, not measured uptake. Safety
        controls in the header apply only to the selected room.
      </p>
    </div>
  );
}
