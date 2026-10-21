import { ArrowRight, Pause, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Heading, Empty, number, time as clock } from "@/components/dashboard";
import { FeedTankDrawing, ZoneSlab } from "@/components/zone-slab";
import { StockBottle } from "@/components/stock-bottle";
import { STOCK_STATES } from "@/lib/dosing";
import {
  facilityView,
  ZONE_MODE,
  type FacilityRoom,
  type FacilityZone,
  type ZoneSensor,
} from "@/lib/facility-view";
import { plantAmount } from "@/lib/water-view";
import type { AttentionLevel } from "@/lib/attention";
import type { Controller } from "@/lib/types";
import type { Page } from "@/lib/routes";
import "./all-zones.css";
import "@/components/zone-slab.css";

const perPlant = (ml: number) => {
  const { value, unit, digits } = plantAmount(ml);
  return `${number(value, digits)} ${unit}`;
};
const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
/** The root zone's comfortable range; outside it the value is marked, never coloured alone. */
const ROOT_BAND: [number, number] = [19, 23];

/** A value against its band: "ok", "low" or "high", and how far out (▼0.4). */
function against(value: number | null, band: readonly [number, number] | null, digits = 1) {
  if (value === null || !band) return { state: "none" as const, delta: "" };
  if (value < band[0]) return { state: "low" as const, delta: ` ▼${number(band[0] - value, digits)}` };
  if (value > band[1]) return { state: "high" as const, delta: ` ▲${number(value - band[1], digits)}` };
  return { state: "ok" as const, delta: "" };
}

type Open = (room: string, page: Page, zone?: number) => void;

/** The facility as rooms, each room's zones, each zone's sensors. A problem shows where it is: on
 * the room, the zone, the sensor or the tank, never in a separate list. */
export function AllZones({ controller, open }: { controller: Controller; open: Open }) {
  const fmt = (value: string | number) =>
    new Date(value).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: controller.timeZone,
    });
  const rooms = facilityView(controller, {
    clock: fmt,
    number: (value, digits = 1) => number(value, digits),
    perPlant,
  });
  const offline = controller.connection === "offline";
  return (
    <div className="facility">
      <Heading
        title="All rooms"
        description="Rooms, their zones and each zone's sensors. Tap a zone for its chart, targets and next action."
      />
      {offline && (
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
      {rooms.map((r) => (
        <RoomCard key={r.room.id} r={r} offline={offline} open={open} />
      ))}
      <p className="muted facility-note">
        Water is the controller's estimate unless a meter is fitted; per plant is the zone's water
        over its plant count, not measured uptake. Safety controls in the header apply only to the
        selected room.
      </p>
    </div>
  );
}

function RoomCard({ r, offline, open }: { r: FacilityRoom; offline: boolean; open: Open }) {
  const { room, view, status, stage, climate } = r;
  const stale = status.tone === "stale" || offline;
  const air = climate.find((c) => c.key === "temperature");
  const rh = climate.find((c) => c.key === "humidity");
  const vpd = climate.find((c) => c.key === "vpd");
  const day = stage?.day ?? null;
  const days = stage?.days ?? null;
  const run = day !== null && days !== null && days > 0;
  const pct = (d: number) => `${Math.max(0, Math.min(100, (d / days!) * 100))}%`;
  const problem = status.tone === "stopped" || status.tone === "off" || stale;
  return (
    <section
      className="facility-room panel"
      data-facility-room={room.id}
      data-problem={problem || undefined}
      aria-labelledby={`facility-${room.id}`}
    >
      <div className="facility-room-top">
        <div className="facility-room-main">
          <div className="facility-room-head">
            <button
              type="button"
              className="facility-room-name"
              onClick={() => open(room.id, "today")}
            >
              <span className="facility-room-dot" data-tone={status.tone} aria-hidden="true" />
              <h2 id={`facility-${room.id}`}>{room.name}</h2>
              <ArrowRight size={15} aria-hidden="true" />
            </button>
            <span className="facility-room-state">
              {stale ? "Last reported" : !view.roomActive ? "Room not in use" : status.text}
              {stage?.name ? ` · ${capital(stage.name)}` : ""}
            </span>
            {run && (
              <span className="facility-room-day">
                Day <strong>{day}</strong> of {days}
                <span className="muted"> · {Math.max(0, days! - day!)} days left</span>
              </span>
            )}
          </div>
          {problem && !stale && (
            <p className="facility-flag" data-level="critical" role="status">
              <TriangleAlert size={15} aria-hidden="true" /> {status.text}: {status.detail}
            </p>
          )}
          {run && (
            <div
              className="facility-run"
              role="img"
              aria-label={`Day ${day} of ${days}${stage?.name ? `, ${stage.name}` : ""}`}
            >
              {stage?.stageDays && (
                <span
                  className="facility-run-stage"
                  style={{
                    left: pct(stage.stageDays[0] - 1),
                    width: `calc(${pct(stage.stageDays[1])} - ${pct(stage.stageDays[0] - 1)})`,
                  }}
                />
              )}
              <span className="facility-run-done" style={{ width: pct(day!) }} />
              <span className="facility-run-today" style={{ left: pct(day!) }} />
            </div>
          )}
          <dl className="facility-room-facts">
            {r.waterL !== null && (
              <div className="facility-fact-lead">
                <dt>Drunk today</dt>
                <dd>
                  {r.litresPerPlant !== null ? (
                    <>
                      <strong>{number(r.litresPerPlant, 2)} L</strong> per plant ·{" "}
                      {number(r.waterL, 1)} L room
                    </>
                  ) : (
                    <>
                      <strong>{number(r.waterL, 1)} L</strong> room
                    </>
                  )}
                </dd>
              </div>
            )}
            {air?.value != null && (
              <div>
                <dt>Air</dt>
                <dd>
                  {number(air.value, 1)} {air.unit}
                </dd>
              </div>
            )}
            {rh?.value != null && (
              <div>
                <dt>RH</dt>
                <dd>{number(rh.value, 0)}%</dd>
              </div>
            )}
            {vpd?.value != null && (
              <div>
                <dt>VPD</dt>
                <dd>{number(vpd.value, 2)} kPa</dd>
              </div>
            )}
          </dl>
        </div>
        <TankCard r={r} open={open} />
      </div>
      <div className="facility-zones">
        {r.zones.map((z) => (
          <ZoneCard key={z.zone.id} r={r} z={z} stale={stale} open={open} />
        ))}
      </div>
      {r.stock.length > 0 && <StockRow r={r} open={open} />}
    </section>
  );
}

function ZoneCard({
  r,
  z,
  stale,
  open,
}: {
  r: FacilityRoom;
  z: FacilityZone;
  stale: boolean;
  open: Open;
}) {
  const { zone } = z;
  const mode = stale && z.mode !== "room-off" ? "offline" : z.mode;
  const level = z.attention.reduce<AttentionLevel | null>(
    (worst, reason) => (worst === "critical" || reason.level === "critical" ? "critical" : "warning"),
    null,
  );
  // Moisture is held between the re-water point and the peak only in P2; overnight (P3) it is
  // meant to dry back and is out of band only under the rescue floor; P0 and P1 are moving to it.
  const band: [number, number] | null =
    zone.phase === "P2" && z.rewater !== null && z.target !== null
      ? [z.rewater, z.target]
      : zone.phase === "P3" && z.rescue !== null
        ? [z.rescue, Number.POSITIVE_INFINITY]
        : null;
  const vwc = against(zone.vwc.value, band);
  const ec = against(zone.ec.value, r.stage?.poreEc ?? null);
  const root = against(z.rootTemp, ROOT_BAND);
  const phase = /^P[0-3]$/.test(zone.phase) ? zone.phase : null;
  return (
    <article
      className="facility-zone"
      data-facility-zone={`${r.room.id}/${zone.id}`}
      data-mode={mode}
      data-level={level ?? undefined}
    >
      <div className="facility-zone-top">
        <ZoneSlab
          vwc={zone.vwc.value}
          peak={z.peak}
          rewater={z.rewater}
          target={z.target}
          ec={zone.ec.value}
          ecBand={r.stage?.poreEc ?? null}
          level={level}
          label=""
        />
        <div className="facility-zone-head">
          <h3>
            <button type="button" onClick={() => open(r.room.id, "zone", zone.id)}>
              {zone.name}
              <ArrowRight size={14} aria-hidden="true" />
            </button>
          </h3>
          <span className="facility-zone-chips">
            <span className="facility-phase" data-phase={phase ?? undefined}>
              {phase ?? "–"}
            </span>
            <span className="facility-mode" data-mode={mode}>
              {mode === "paused" && <Pause size={12} aria-hidden="true" />}
              {ZONE_MODE[mode]}
            </span>
          </span>
          <span className="facility-zone-drink">
            {z.mlPerPlant !== null ? (
              <>
                <strong>{perPlant(z.mlPerPlant)}</strong> per plant
              </>
            ) : (
              <span className="muted">Per plant unknown</span>
            )}
            {z.waterL !== null && <span className="muted"> · {number(z.waterL, 1)} L zone</span>}
          </span>
        </div>
      </div>
      <dl className="facility-zone-readings">
        <div data-state={vwc.state}>
          <dt>VWC</dt>
          <dd>
            {zone.vwc.value === null ? "—" : `${number(zone.vwc.value)}%`}
            {vwc.delta}
          </dd>
        </div>
        <div>
          <dt>Dryback</dt>
          <dd>{z.drybackPoints === null ? "—" : `${number(z.drybackPoints)} pts`}</dd>
        </div>
        <div data-state={ec.state}>
          <dt>Pore EC</dt>
          <dd>
            {zone.ec.value === null ? "—" : number(zone.ec.value)}
            {ec.delta}
          </dd>
        </div>
        <div data-state={root.state}>
          <dt>Root</dt>
          <dd>
            {z.rootTemp === null ? "—" : `${number(z.rootTemp)}°`}
            {root.delta}
          </dd>
        </div>
      </dl>
      {z.attention.map((reason) => (
        <p key={reason.rule} className="facility-flag" data-level={reason.level}>
          <TriangleAlert size={14} aria-hidden="true" /> {reason.text}
        </p>
      ))}
      {z.sensors.length > 0 && (
        <ul className="facility-sensors" aria-label={`${zone.name} sensors`}>
          {z.sensors.map((sensor) => (
            <SensorRow key={sensor.key} sensor={sensor} />
          ))}
        </ul>
      )}
    </article>
  );
}

function SensorRow({ sensor }: { sensor: ZoneSensor }) {
  const bad = sensor.health !== "ok" && sensor.health !== "not-counted";
  return (
    <li className="facility-sensor" data-health={sensor.health}>
      <span className="facility-sensor-dot" aria-hidden="true" />
      <span className="facility-sensor-name" title={sensor.name}>
        {sensor.name}
      </span>
      <span className="facility-sensor-values">
        {sensor.vwc && <span>{sensor.vwc.value === null ? "—" : `${number(sensor.vwc.value)}%`}</span>}
        {sensor.ec && <span>EC {sensor.ec.value === null ? "—" : number(sensor.ec.value)}</span>}
      </span>
      {bad && <span className="facility-sensor-issue">{sensor.text}</span>}
    </li>
  );
}

function TankCard({ r, open }: { r: FacilityRoom; open: Open }) {
  const { tank, reservoir } = r;
  const level = tank.level.value;
  const held = reservoir.state === "held";
  return (
    <button
      type="button"
      className="facility-tank"
      data-held={held || undefined}
      onClick={() => open(r.room.id, "equipment/feed")}
      aria-label={`Open ${r.room.name} tank and feed`}
    >
      <FeedTankDrawing
        level={level}
        minimum={reservoir.minimum}
        full={tank.fill.on}
        low={held}
        label={level === null ? "Tank level unavailable" : `Tank ${number(level, 0)} % full`}
      />
      <span className="facility-tank-facts">
        <span className="facility-tank-title">Feed tank</span>
        <span className="facility-tank-level">
          {level === null ? tank.level.issue : <strong>{number(level, 0)}%</strong>}
          {reservoir.aboveMinimumL !== null && (
            <span className="muted"> · {number(reservoir.aboveMinimumL, 0)} L usable</span>
          )}
        </span>
        <span className="facility-tank-readings">
          <span>pH {tank.ph.value === null ? "—" : number(tank.ph.value, 2)}</span>
          <span>EC {tank.ec.value === null ? "—" : number(tank.ec.value, 2)}</span>
          {tank.temperature.value !== null && <span>{number(tank.temperature.value)}°</span>}
        </span>
        <span className="muted">
          Pump {tank.pump.on === null ? "unknown" : tank.pump.on ? "on" : "off"}
          {tank.lastFill.timestamp ? ` · filled ${clock(tank.lastFill.timestamp)}` : ""}
        </span>
        {held && (
          <span className="facility-flag" data-level="critical">
            <Pause size={13} aria-hidden="true" /> {reservoir.label}
          </span>
        )}
      </span>
    </button>
  );
}

function StockRow({ r, open }: { r: FacilityRoom; open: Open }) {
  const largest = Math.max(...r.stock.map((tank) => tank.capacity_l));
  return (
    <button
      type="button"
      className="facility-stock"
      onClick={() => open(r.room.id, "equipment/stock")}
      aria-label={`Open ${r.room.name} stock tanks`}
    >
      <span className="facility-stock-title">Stock</span>
      {r.stock.map((tank) => (
        <span key={tank.id} className="facility-stock-item" data-state={tank.state}>
          <StockBottle
            tank={tank}
            state={tank.state}
            scale={tank.capacity_l / largest}
            label={`${tank.name}: ${number(tank.level_l)} of ${number(tank.capacity_l)} L${
              STOCK_STATES[tank.state] ? `, ${STOCK_STATES[tank.state].toLowerCase()}` : ""
            }`}
          />
          <span className="facility-stock-name">{tank.name}</span>
          <span className="facility-stock-level">
            {number(tank.level_l)}/{number(tank.capacity_l)} L
          </span>
        </span>
      ))}
    </button>
  );
}
