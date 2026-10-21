import { ArrowRight, Pause } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Heading, Empty, number, time as clock } from "@/components/dashboard";
import { FeedTankDrawing, ZoneSlab } from "@/components/zone-slab";
import { StockBottle } from "@/components/stock-bottle";
import { STOCK_STATES } from "@/lib/dosing";
import { facilityView, type FacilityRoom, type FacilityZone } from "@/lib/facility-view";
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
const RANK: Record<AttentionLevel, number> = { critical: 0, warning: 1 };
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

/** The facility at a glance: what needs the grower first, then each room as its run, its climate
 * and its zones drawn as slabs (water = moisture, dashed line = today's peak, specks = pore EC),
 * then each room's feed tank and stock. Each value appears once; a zone's detail is one tap away. */
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
  const attention = rooms
    .flatMap((r) => [
      ...r.zones.flatMap((z) =>
        z.attention.map((reason) => ({
          key: `${r.room.id}/${z.zone.id}/${reason.rule}`,
          where: `${r.room.name} · ${z.zone.name}`,
          text: reason.text,
          level: reason.level,
          go: () => open(r.room.id, "zone", z.zone.id),
        })),
      ),
      ...(r.reservoir.state === "held"
        ? [
            {
              key: `${r.room.id}/tank`,
              where: `${r.room.name} · feed tank`,
              text: r.reservoir.label,
              level: "critical" as AttentionLevel,
              go: () => open(r.room.id, "equipment/feed"),
            },
          ]
        : []),
    ])
    .sort((a, b) => RANK[a.level] - RANK[b.level]);
  return (
    <div className="facility">
      <Heading
        title="All rooms"
        description="Every room at a glance. Tap a zone for its chart, targets and next action."
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
      {attention.length > 0 && (
        <section className="facility-attention panel" aria-labelledby="facility-attention">
          <h2 id="facility-attention">Needs attention</h2>
          <ul>
            {attention.map((item) => (
              <li key={item.key}>
                <button type="button" data-level={item.level} onClick={item.go}>
                  <span className="facility-attention-dot" aria-hidden="true" />
                  <strong>{item.where}</strong>
                  <span>{item.text}</span>
                  <ArrowRight size={15} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {rooms.map((r) => (
        <RoomCard key={r.room.id} r={r} offline={offline} open={open} />
      ))}
      {rooms.length > 0 && (
        <section className="facility-water" aria-labelledby="facility-water">
          <h2 id="facility-water" className="facility-section-title">
            Water &amp; feed
          </h2>
          <div className="facility-tanks">
            {rooms.map((r) => (
              <TankCard key={r.room.id} r={r} open={open} />
            ))}
          </div>
          {rooms
            .filter((r) => r.stock.length > 0)
            .map((r) => {
              const largest = Math.max(...r.stock.map((tank) => tank.capacity_l));
              return (
                <button
                  type="button"
                  key={r.room.id}
                  className="facility-stock panel"
                  onClick={() => open(r.room.id, "equipment/stock")}
                  aria-label={`Open ${r.room.name} stock tanks`}
                >
                  <span className="facility-tank-title">{r.room.name} stock tanks</span>
                  <span className="facility-stock-bottles">
                    {r.stock.map((tank) => (
                      <span key={tank.id} className="facility-stock-item">
                        <StockBottle
                          tank={tank}
                          state={tank.state}
                          scale={tank.capacity_l / largest}
                          label={`${tank.name}: ${number(tank.level_l)} of ${number(tank.capacity_l)} L${
                            STOCK_STATES[tank.state] ? `, ${STOCK_STATES[tank.state].toLowerCase()}` : ""
                          }`}
                        />
                        <span className="facility-stock-name">{tank.name}</span>
                        <span className="facility-stock-level" data-state={tank.state}>
                          {number(tank.level_l)} / {number(tank.capacity_l)} L
                        </span>
                      </span>
                    ))}
                  </span>
                </button>
              );
            })}
        </section>
      )}
      <p className="muted facility-note">
        Water totals are controller-reported estimates unless backed by a meter; per-plant values
        are averages, not measured uptake. Safety controls in the header apply only to the selected
        room.
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
  return (
    <section
      className="facility-room panel"
      data-facility-room={room.id}
      aria-labelledby={`facility-${room.id}`}
    >
      <div className="facility-room-head">
        <button type="button" className="facility-room-name" onClick={() => open(room.id, "today")}>
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
      {(air?.value != null || rh?.value != null || vpd?.value != null || r.waterL !== null) && (
        <p className="facility-room-facts">
          {air?.value != null && (
            <span>
              Air{" "}
              <strong>
                {number(air.value, 1)} {air.unit}
              </strong>
            </span>
          )}
          {rh?.value != null && (
            <span>
              RH <strong>{number(rh.value, 0)}%</strong>
            </span>
          )}
          {vpd?.value != null && (
            <span>
              VPD <strong>{number(vpd.value, 2)} kPa</strong>
            </span>
          )}
          {r.waterL !== null && (
            <span>
              Water today <strong>{number(r.waterL, 1)} L</strong>
              {r.litresPerPlant !== null && <> · {number(r.litresPerPlant, 2)} L per plant</>}
            </span>
          )}
        </p>
      )}
      {(status.tone === "stopped" || status.tone === "off") && !stale && view.roomActive && (
        <p className="facility-room-status" role="status">
          {status.text} · {status.detail}
        </p>
      )}
      <div className="facility-slabs">
        {r.zones.map((z) => (
          <ZoneTile key={z.zone.id} r={r} z={z} stale={stale} open={open} />
        ))}
      </div>
    </section>
  );
}

function ZoneTile({
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
  const summary = [
    `${zone.name}${phase ? ` ${phase}` : ""}`,
    zone.vwc.value === null ? "VWC unavailable" : `VWC ${number(zone.vwc.value)} %`,
    z.drybackPoints !== null ? `${number(z.drybackPoints)} points under today's peak` : null,
    zone.ec.value === null ? null : `pore EC ${number(zone.ec.value)}`,
    z.rootTemp === null ? null : `root zone ${number(z.rootTemp)} ${z.rootUnit}`,
    ...z.attention.map((reason) => reason.text),
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <button
      type="button"
      className="facility-zone"
      data-facility-zone={`${r.room.id}/${zone.id}`}
      data-stale={stale || zone.stale || undefined}
      onClick={() => open(r.room.id, "zone", zone.id)}
      aria-label={`Open ${summary}`}
    >
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
      <span className="facility-zone-name">
        <span className="facility-phase" data-phase={phase ?? undefined}>
          {phase ?? "–"}
        </span>
        {zone.name}
        {zone.enabled === false && <Pause size={12} aria-hidden="true" />}
      </span>
      <span className="facility-zone-value" data-state={vwc.state}>
        {zone.vwc.value === null ? "—" : `${number(zone.vwc.value)}%`}
        {vwc.delta}
      </span>
      {zone.ec.value !== null && (
        <span className="facility-zone-sub" data-state={ec.state}>
          EC {number(zone.ec.value)}
          {ec.delta}
        </span>
      )}
      {z.rootTemp !== null && (
        <span className="facility-zone-sub" data-state={root.state}>
          {number(z.rootTemp)}°{root.delta}
        </span>
      )}
    </button>
  );
}

function TankCard({ r, open }: { r: FacilityRoom; open: Open }) {
  const { tank, reservoir } = r;
  const level = tank.level.value;
  const held = reservoir.state === "held";
  return (
    <button
      type="button"
      className="facility-tank panel"
      data-held={held || undefined}
      onClick={() => open(r.room.id, "equipment/feed")}
      aria-label={`Open ${r.room.name} tank and feed`}
    >
      <span className="facility-tank-title">{r.room.name} feed tank</span>
      <span className="facility-tank-body">
        <FeedTankDrawing
          level={level}
          minimum={reservoir.minimum}
          full={tank.fill.on}
          low={held}
          label={level === null ? "Tank level unavailable" : `Tank ${number(level, 0)} % full`}
        />
        <span className="facility-tank-facts">
          <span className="facility-tank-level">
            {level === null ? tank.level.issue : <strong>{number(level, 0)}%</strong>}
            {reservoir.aboveMinimumL !== null && (
              <span className="muted"> · {number(reservoir.aboveMinimumL, 0)} L above minimum</span>
            )}
          </span>
          <span className="facility-tank-readings">
            <span>pH {tank.ph.value === null ? "—" : number(tank.ph.value, 2)}</span>
            <span>
              EC {tank.ec.value === null ? "—" : `${number(tank.ec.value, 2)} ${tank.ec.unit}`}
            </span>
            {tank.temperature.value !== null && (
              <span>
                {number(tank.temperature.value)} {tank.temperature.unit}
              </span>
            )}
          </span>
          <span className="muted">
            Pump {tank.pump.on === null ? "unknown" : tank.pump.on ? "on" : "off"}
            {tank.lastFill.timestamp ? ` · filled ${clock(tank.lastFill.timestamp)}` : ""}
          </span>
        </span>
      </span>
      {held && (
        <span className="facility-tank-held" role="status">
          <Pause size={14} aria-hidden="true" /> {reservoir.label}
        </span>
      )}
    </button>
  );
}
