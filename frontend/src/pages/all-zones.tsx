import { ArrowRight, Pause, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, number, time as clock } from "@/components/dashboard";
import { FeedTankDrawing, ZoneSlab } from "@/components/zone-slab";
import { DrinkBar, MiniGauge, ShotDots } from "@/components/zone-gauges";
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
      {/* The menu already marks All rooms: the heading is for screen readers only. */}
      <h1 className="sr-only">All rooms</h1>
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
  const drunk = r.zones
    .map((z) => z.mlPerPlant)
    .filter((ml): ml is number => ml !== null)
    .sort((x, y) => x - y);
  const median = drunk.length ? drunk[Math.floor(drunk.length / 2)] : null;
  const maxMl = Math.max(1, ...drunk) * 1.15;
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
      </div>
      <div className="facility-supply">
        <TankCard r={r} open={open} />
        {r.stock.length > 0 && <StockRow r={r} open={open} />}
      </div>
      <div className="facility-zones">
        {r.zones.map((z) => (
          <ZoneCard
            key={z.zone.id}
            r={r}
            z={z}
            stale={stale}
            open={open}
            median={median}
            maxMl={maxMl}
          />
        ))}
      </div>
    </section>
  );
}

/** A sensor's own name inside its zone's card: "Zone 1 front" reads "Front". */
function sensorName(sensor: ZoneSensor, context: string[]) {
  let name = sensor.name;
  for (const word of context)
    if (name.toLowerCase().startsWith(word.toLowerCase())) name = name.slice(word.length).trim();
  return name ? name.charAt(0).toUpperCase() + name.slice(1) : "Sensor";
}

function ZoneCard({
  r,
  z,
  stale,
  open,
  median,
  maxMl,
}: {
  r: FacilityRoom;
  z: FacilityZone;
  stale: boolean;
  open: Open;
  /** The room's median water per plant today, and the bar's end, for the zone's drink bar. */
  median: number | null;
  maxMl: number;
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
  const poreEc = r.stage?.poreEc ?? null;
  const phase = /^P[0-3]$/.test(zone.phase) ? zone.phase : null;
  const context = [r.room.name, zone.name];
  const troubled = z.sensors.filter((s) => s.health !== "ok" && s.health !== "not-counted");
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
          ecBand={poreEc}
          level={level}
          label=""
          sensors={z.sensors.map((s) => ({
            health: s.health,
            label: `${sensorName(s, context)}: ${
              s.vwc?.value == null ? "—" : `${number(s.vwc.value)}%`
            }${s.ec?.value == null ? "" : `, EC ${number(s.ec.value)}`}${
              s.health === "ok" ? "" : ` (${s.text})`
            }`,
          }))}
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
          <ShotDots shots={zone.shots.value === null ? null : Math.round(zone.shots.value)} />
        </div>
      </div>
      <DrinkBar
        ml={z.mlPerPlant}
        median={median}
        max={maxMl}
        text={
          z.mlPerPlant !== null ? (
            <>
              <strong>{perPlant(z.mlPerPlant)}</strong> per plant
              {z.waterL !== null && <span className="muted"> · {number(z.waterL, 1)} L today</span>}
            </>
          ) : (
            <span className="muted">Per plant unknown</span>
          )
        }
      />
      <div className="facility-gauges">
        <MiniGauge label="VWC" value={zone.vwc.value} unit="%" band={band} scale={[20, 80]} />
        <MiniGauge
          label="Dryback"
          value={z.drybackPoints}
          unit=" pt"
          band={r.stage?.drybackPoints ?? null}
          scale={[0, 20]}
        />
        <MiniGauge
          label="Pore EC"
          value={zone.ec.value}
          band={poreEc}
          scale={poreEc ? [0, poreEc[1] * 1.6] : [0, 10]}
        />
        <MiniGauge label="Root" value={z.rootTemp} unit="°" band={ROOT_BAND} scale={[14, 30]} />
      </div>
      {z.attention
        // Pore EC out of band shows on its gauge, and a probe's trouble on its sensor.
        .filter((reason) => reason.rule !== "pore-ec" && reason.rule !== "probe")
        .map((reason) => (
          <p key={reason.rule} className="facility-flag" data-level={reason.level}>
            <TriangleAlert size={14} aria-hidden="true" /> {reason.text}
          </p>
        ))}
      {troubled.map((s) => (
        <p
          key={s.key}
          className="facility-flag"
          data-level={s.health === "no-reading" || s.health === "out-of-range" ? "critical" : "warning"}
        >
          <TriangleAlert size={14} aria-hidden="true" /> {sensorName(s, context)} sensor: {s.text}
        </p>
      ))}
    </article>
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
      onClick={() => open(r.room.id, "equipment/dosing")}
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
            scale={Math.max(0.6, tank.capacity_l / largest)}
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
