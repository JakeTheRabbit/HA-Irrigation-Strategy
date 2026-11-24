import type { ReactNode } from "react";
import { ArrowRight, Clock, Pause, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, number, time as clock } from "@/components/dashboard";
import { FeedTankDrawing } from "@/components/zone-slab";
import { AlertCodeText } from "@/components/alert-code-text";
import { DayRail, EcLane, ecDomain, TargetTrack, VwcLane, vwcDomain, type SteeringTone } from "@/components/steering-lane";
import { StockBottle } from "@/components/stock-bottle";
import { NeedsAttention } from "@/components/needs-attention";
import { STOCK_STATES } from "@/lib/dosing";
import { formatEc, formatTemp, formatVolume } from "@/lib/display-units";
import {
  drinkLine,
  facilityView,
  roomAttention,
  tankReadingText,
  zoneHref,
  ZONE_MODE,
  type FacilityRoom,
  type FacilityZone,
  type ZoneSensor,
} from "@/lib/facility-view";
import { plantAmount } from "@/lib/water-view";
import type { AttentionLevel } from "@/lib/attention";
import type { Controller } from "@/lib/types";
import type { Page } from "@/lib/routes";
import { useNarrow } from "@/lib/use-narrow";
import { roomPhases, useSteeringDays, type RoomDay } from "@/lib/steering-day";
import "./all-zones.css";
import "./facility-steer.css";
import "@/components/zone-slab.css";

const perPlant = (ml: number) => {
  const { value, unit, digits } = plantAmount(ml);
  return `${number(value, digits)} ${unit}`;
};
/** The grow plan's stage, else the stage arc's name. */
const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const stageName = (r: FacilityRoom) => r.growDay?.stage || r.stage?.name || "";
/** EC to one decimal ("EC 3.0" beside "EC 2.7"): the unit only when it is not mS/cm. */
const ec = (ms: number) => formatEc(ms, 1).replace(/ mS\/cm$/, "");
const ordinal = (n: number) => {
  const tail = n % 100 >= 11 && n % 100 <= 13 ? "th" : (["th", "st", "nd", "rd"][n % 10] ?? "th");
  return `${n}${tail}`;
};
const queuedText = (place: number) => `Waiting for the pump — ${ordinal(place)} in line`;
/** The root zone's comfortable range; outside it the value is marked, never coloured alone. */
const ROOT_BAND: [number, number] = [19, 23];

type Open = (room: string, page: Page, zone?: number) => void;

/** Water the controller gave the room today: an estimate (shot time × the drippers' flow) unless a
 * zone has a meter, which reports how much of each shot arrived. */
const deliveredLabel = (r: FacilityRoom) =>
  r.zones.some((z) => z.flowRatio !== null) ? "Delivered today" : "Delivered today · estimated";

const mixText = (mix: NonNullable<FacilityRoom["mixFailed"]>) =>
  `${mix.title}${mix.at ? ` ${clock(mix.at)}` : ""}`;

/** "Low" / "High" when a value is outside its band, else null. */
const outside = (value: number | null, band: [number, number] | null | undefined) =>
  value !== null && band ? (value < band[0] ? "Low" : value > band[1] ? "High" : null) : null;

/** The facility as rooms on their own clocks: each room's photoperiod and phases as a rail, each
 * zone's moisture today under it on the same axis, its numbers beside it. A problem shows where it
 * is: on the zone's curve, the room or the tank, never in a separate list. */
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
  const phone = useNarrow(720);
  const days = useSteeringDays(
    controller,
    rooms.map((r) => ({ room: r.room, zones: r.zones.map((z) => z.zone) })),
  );
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
        <RoomCard
          key={r.room.id}
          r={r}
          offline={offline}
          open={open}
          day={days.get(r.room.id)}
          phone={phone}
          timeZone={controller.timeZone}
        />
      ))}
      <p className="muted facility-note">
        Water is the controller's estimate unless a meter is fitted; per plant is the zone's water
        over its plant count, not measured uptake. Safety controls in the header apply only to the
        selected room.
      </p>
    </div>
  );
}

function RoomCard({
  r,
  offline,
  open,
  day,
  phone,
  timeZone,
}: {
  r: FacilityRoom;
  offline: boolean;
  open: Open;
  day: RoomDay | undefined;
  phone: boolean;
  timeZone: string;
}) {
  const { room, view, status, climate, growDay } = r;
  const stale = status.tone === "stale" || offline;
  const air = climate.find((c) => c.key === "temperature");
  const rh = climate.find((c) => c.key === "humidity");
  const vpd = climate.find((c) => c.key === "vpd");
  const problem = status.tone === "stopped" || status.tone === "off" || stale;
  const drink = drinkLine(r.waterL, r.litresPerPlant);
  const now = Date.now();
  // One VWC scale and one pore EC scale for the room's lanes, so its zones compare by eye.
  const domain = vwcDomain(
    r.zones.flatMap((z) => [
      z.zone.vwc.value,
      ...(z.timer ? [] : [z.rewater, z.target]),
      ...(day?.zones?.get(z.zone.id)?.vwc.map((point) => point.value) ?? []),
    ]),
  );
  const ecDom = ecDomain([
    ...(r.stage?.poreEc ?? []),
    ...r.zones.flatMap((z) => [
      z.zone.ec.value,
      ...(day?.zones?.get(z.zone.id)?.ec.map((point) => point.value) ?? []),
    ]),
  ]);
  return (
    <section
      className="facility-room panel"
      data-facility-room={room.id}
      data-problem={problem || undefined}
      aria-labelledby={`facility-${room.id}`}
    >
      <header className="steer-room-head">
        <div className="facility-room-head">
          <button type="button" className="facility-room-name" onClick={() => open(room.id, "today")}>
            <span className="facility-room-dot" data-tone={status.tone} aria-hidden="true" />
            <h2 id={`facility-${room.id}`}>{room.name}</h2>
            <ArrowRight size={15} aria-hidden="true" />
          </button>
          <span className="facility-room-state">
            {stale ? "Last reported" : !view.roomActive ? "Room not in use" : status.text}
            {stageName(r) ? ` · ${capital(stageName(r))}` : ""}
          </span>
          {growDay && (
            <span className="facility-room-day">
              Day <strong>{growDay.day}</strong>
              {growDay.of !== null && (phone ? `/${growDay.of}` : ` of ${growDay.of}`)}
              {!phone && growDay.daysLeft !== null && (
                <span className="muted"> · {growDay.daysLeft} days left</span>
              )}
            </span>
          )}
        </div>
        <dl className="steer-room-facts">
          {drink && (
            <div>
              <dt>{deliveredLabel(r)}</dt>
              <dd>
                <DrinkText drink={drink} />
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
        <NeedsAttention
          items={roomAttention(r)}
          alerts={r.alertCount}
          open={(item) => open(room.id, item.page, item.zone)}
        />
        {problem && !stale && (
          <p className="facility-flag" data-level="critical" role="status">
            <TriangleAlert size={15} aria-hidden="true" /> {status.text}:{" "}
            <AlertCodeText text={status.detail} />
          </p>
        )}
      </header>
      <div className="steer-grid">
        {day && (
          <div className="steer-lane steer-rail">
            <DayRail
              span={day.span}
              lightsOn={day.day.start}
              lightsOff={day.day.lightsOff}
              phases={roomPhases(day.zones, day.day, now)}
              now={now}
              timeZone={timeZone}
            />
          </div>
        )}
        {r.zones.map((z) => (
          <ZoneRow
            key={z.zone.id}
            r={r}
            z={z}
            stale={stale}
            open={open}
            day={day}
            domain={domain}
            ecDom={ecDom}
            now={now}
          />
        ))}
      </div>
      {phone ? (
        <PhoneFeed r={r} open={open} />
      ) : (
        <div className="steer-supply">
          <TankCard r={r} open={open} />
          {r.stock.length > 0 && <StockRow r={r} open={open} />}
        </div>
      )}
    </section>
  );
}

function DrinkText({ drink }: { drink: NonNullable<ReturnType<typeof drinkLine>> }) {
  return drink.perPlant !== null ? (
    <>
      <strong>{drink.perPlant}</strong> per plant · {drink.room} room
    </>
  ) : (
    <>
      <strong>{drink.room}</strong> room
    </>
  );
}

/** A link to the zone's page (#/zone/N) that opens it in this zone's room. */
function ZoneLink({
  r,
  zone,
  open,
  children,
}: {
  r: FacilityRoom;
  zone: number;
  open: Open;
  children: ReactNode;
}) {
  return (
    <a
      href={zoneHref(window.location.search, r.room.id, zone)}
      onClick={(event) => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
          return;
        event.preventDefault();
        open(r.room.id, "zone", zone);
      }}
    >
      {children}
    </a>
  );
}

/** A sensor's own name inside its zone's row: "Zone 1 front" reads "Front". */
function sensorName(sensor: ZoneSensor, context: string[]) {
  let name = sensor.name;
  for (const word of context)
    if (name.toLowerCase().startsWith(word.toLowerCase())) name = name.slice(word.length).trim();
  return name ? name.charAt(0).toUpperCase() + name.slice(1) : "Sensor";
}

/** One zone on the room's clock: who it is and its VWC, today's moisture under the room's rail,
 * and its dryback, pore EC, water and root beside it. Its trouble sits on its curve. */
function ZoneRow({
  r,
  z,
  stale,
  open,
  day,
  domain,
  ecDom,
  now,
}: {
  r: FacilityRoom;
  z: FacilityZone;
  stale: boolean;
  open: Open;
  day: RoomDay | undefined;
  domain: [number, number];
  ecDom: [number, number];
  now: number;
}) {
  const { zone } = z;
  const mode = stale && z.mode !== "room-off" ? "offline" : z.mode;
  const level = z.attention.reduce<AttentionLevel | null>(
    (worst, reason) => (worst === "critical" || reason.level === "critical" ? "critical" : "warning"),
    null,
  );
  // A timer zone is not steered: no phase and no band.
  const phase = !z.timer && /^P[0-3]$/.test(zone.phase) ? zone.phase : null;
  const band: [number, number] | null =
    !z.timer && z.rewater !== null && z.target !== null ? [z.rewater, z.target] : null;
  const vwc = zone.vwc.value;
  // A reading says its state only when it is not plainly in range: held to the band in P2 only.
  const state = z.timer
    ? "Not held, timer"
    : phase === "P1" && band && vwc !== null && vwc < band[0]
      ? "Ramping"
      : phase === "P2"
        ? outside(vwc, band)
        : null;
  const poreEc = r.stage?.poreEc ?? null;
  const context = [r.room.name, zone.name];
  // A sensor the zone's open alert already names ("Back sensor silent 3 h…") is said once, there.
  const troubled = z.sensors.filter(
    (s) =>
      s.health !== "ok" &&
      s.health !== "not-counted" &&
      !z.problem?.toLowerCase().startsWith(`${sensorName(s, context).toLowerCase()} sensor`),
  );
  // Pore EC out of band shows on its number, a probe's trouble on its sensor line, the problem on
  // the curve.
  const others = z.attention.filter(
    (reason) => reason.rule !== "pore-ec" && reason.rule !== "probe" && reason.text !== z.problem,
  );
  const lane = day?.zones?.get(zone.id);
  const drybackBand = r.stage?.drybackPoints ?? null;
  return (
    <div
      className="steer-zone"
      data-facility-zone={`${r.room.id}/${zone.id}`}
      data-mode={mode}
      data-level={level ?? undefined}
      data-last-shot={z.lastShotHollow ? "hollow" : undefined}
    >
      <div className="steer-who facility-zone-head">
        <h3>
          <ZoneLink r={r} zone={zone.id} open={open}>
            {zone.name}
          </ZoneLink>
        </h3>
        {zone.cultivar && <span className="steer-cultivar">{zone.cultivar}</span>}
        <p className="steer-reading">
          <span className="steer-value">{vwc === null ? "—" : number(vwc, 0)}</span>
          <span className="steer-unit">% VWC</span>
        </p>
        <p className="steer-chips">
          {state && (
            <span
              className="steer-state"
              data-state={state === "Ramping" ? "ramp" : state.startsWith("Not") ? "free" : "off"}
            >
              {state}
            </span>
          )}
          <span className="facility-mode" data-mode={mode}>
            {mode === "paused" && <Pause size={12} aria-hidden="true" />}
            {mode === "paused"
              ? "Scheduling paused"
              : phase && mode !== "watering"
                ? `${phase}, ${ZONE_MODE[mode].toLowerCase()}`
                : ZONE_MODE[mode]}
          </span>
        </p>
      </div>
      <div className="steer-lane">
        {day ? (
          <>
            <VwcLane
              span={day.span}
              readings={lane ? lane.vwc : day.zones ? [] : null}
              shots={lane?.shots ?? []}
              band={band}
              bandText={band ? `VWC ${number(band[0], 0)}–${number(band[1], 0)}%` : null}
              domain={domain}
              lightsOn={day.day.start}
              lightsOff={day.day.lightsOff}
              now={now}
              abnormal={state === "Low" || state === "High"}
              flag={
                z.problem
                  ? {
                      level: z.problemIsAlert ? "critical" : "warning",
                      text: (
                        <span data-facility-problem>
                          <AlertCodeText text={z.problem} />
                        </span>
                      ),
                    }
                  : null
              }
            />
            <EcLane
              span={day.span}
              readings={lane ? lane.ec : day.zones ? [] : null}
              band={poreEc}
              bandText={poreEc ? `EC ${ec(poreEc[0])}–${ec(poreEc[1])}` : null}
              domain={ecDom}
              lightsOn={day.day.start}
              lightsOff={day.day.lightsOff}
              now={now}
              abnormal={outside(zone.ec.value, poreEc) !== null}
            />
          </>
        ) : (
          z.problem && (
            <p className="facility-flag" data-level={level ?? "warning"} data-facility-problem>
              <TriangleAlert size={14} aria-hidden="true" /> <AlertCodeText text={z.problem} />
            </p>
          )
        )}
        {(z.queued || z.lastShotText || others.length > 0 || troubled.length > 0) && (
          <ul className="steer-notes">
            {z.queued && (
              <li data-facility-queued>
                <Clock size={13} aria-hidden="true" /> {queuedText(z.queued.place)}
              </li>
            )}
            {z.lastShotText && <li data-facility-flow>{z.lastShotText}</li>}
            {others.map((reason) => (
              <li key={reason.rule} data-level={reason.level}>
                <TriangleAlert size={13} aria-hidden="true" /> <AlertCodeText text={reason.text} />
              </li>
            ))}
            {troubled.map((s) => (
              <li
                key={s.key}
                data-level={
                  s.health === "no-reading" || s.health === "out-of-range" ? "critical" : "warning"
                }
              >
                <TriangleAlert size={13} aria-hidden="true" /> {sensorName(s, context)} sensor:{" "}
                <AlertCodeText text={s.text} />
              </li>
            ))}
          </ul>
        )}
      </div>
      <dl className="steer-metrics">
        <Metric
          label="Dryback"
          value={z.drybackPoints === null ? "—" : number(z.drybackPoints, 0)}
          unit="pt"
          state={outside(z.drybackPoints, drybackBand)}
          target={drybackBand ? `target ${number(drybackBand[0], 0)}–${number(drybackBand[1], 0)}` : null}
          valueNum={z.drybackPoints}
          band={drybackBand}
          tone="vwc"
        />
        <Metric
          label="Pore EC"
          value={zone.ec.value === null ? "—" : ec(zone.ec.value)}
          unit=""
          state={outside(zone.ec.value, poreEc)}
          target={poreEc ? `target ${ec(poreEc[0])}–${ec(poreEc[1])}` : null}
          valueNum={zone.ec.value}
          band={poreEc}
          tone="ec"
        />
        <Metric
          label="Water today"
          value={z.mlPerPlant === null ? "—" : perPlant(z.mlPerPlant)}
          unit="/plant"
          target={`${zone.shots.value === null ? "—" : Math.round(zone.shots.value)} shots${
            z.waterL !== null ? `, ${formatVolume(z.waterL, 1)}` : ""
          }`}
        />
        <Metric
          label="Root"
          value={z.rootTemp === null ? "—" : formatTemp(z.rootTemp, 1)}
          unit=""
          state={outside(z.rootTemp, ROOT_BAND)}
          valueNum={z.rootTemp}
          band={ROOT_BAND}
          tone="neutral"
        />
      </dl>
    </div>
  );
}

function Metric({
  label,
  value,
  unit,
  state,
  target,
  valueNum,
  band,
  tone = "neutral",
}: {
  label: string;
  value: string;
  unit: string;
  state?: string | null;
  target?: string | null;
  valueNum?: number | null;
  band?: readonly [number, number] | null;
  tone?: SteeringTone;
}) {
  return (
    <div className="steer-metric" data-off={state ? "" : undefined}>
      <dt>{label}</dt>
      <dd>
        <span className="steer-metric-value">{value}</span>
        {unit && <small>{unit}</small>}
        {state && <span className="steer-metric-state"> {state}</span>}
      </dd>
      {band && (
        <dd className="steer-metric-track">
          <TargetTrack value={valueNum ?? null} band={band} tone={tone} abnormal={!!state} />
        </dd>
      )}
      {target && <dd className="steer-metric-target">{target}</dd>}
    </div>
  );
}

function TankCard({ r, open }: { r: FacilityRoom; open: Open }) {
  const { tank, reservoir } = r;
  const level = tank.level.value;
  const readings = tankReadingText({ ph: tank.ph.value, ec: tank.ec.value, temperature: tank.temperature.value });
  const held = reservoir.state === "held";
  return (
    <button
      type="button"
      className="facility-tank"
      data-held={held || undefined}
      onClick={() => open(r.room.id, "equipment/dosing")}
    >
      {/* The button's name is its text, so a screen reader hears the readings and the due flag. */}
      <span className="sr-only">Open {r.room.name} tank and feed: </span>
      <span aria-hidden="true">
        <FeedTankDrawing
          level={level}
          minimum={reservoir.minimum}
          full={tank.fill.on}
          low={held}
          label={level === null ? "Tank level unavailable" : `Tank ${number(level, 0)} % full`}
        />
      </span>
      <span className="facility-tank-facts">
        <span className="facility-tank-title">Feed tank</span>
        <span className="facility-tank-level">
          {level === null ? tank.level.issue : <strong>{number(level, 0)}%</strong>}
          {reservoir.aboveMinimumL !== null && (
            <span className="muted"> · {formatVolume(reservoir.aboveMinimumL, 0)} usable</span>
          )}
        </span>
        <span className="facility-tank-readings">
          {/* Spaces between the parts: the line may wrap before any reading, never inside one. */}
          <span>pH {readings.ph ?? "—"}</span>
          {r.feedCalibrationDue && (
            <>
              {" "}
              <span className="facility-due" data-facility-due>
                Calibration due
              </span>
            </>
          )}{" "}
          <span>
            <span aria-hidden="true">·</span> EC {readings.ec ?? "—"}
          </span>
          {tank.temperature.value !== null && (
            <>
              {" "}
              <span>
                <span aria-hidden="true">·</span> {readings.temperature}
              </span>
            </>
          )}
        </span>
        <span className="muted">
          Pump {tank.pump.on === null ? "unknown" : tank.pump.on ? "on" : "off"}
          {tank.lastFill.timestamp ? ` · filled ${clock(tank.lastFill.timestamp)}` : ""}
        </span>
        {r.mixFailed && (
          <span className="facility-flag" data-level="critical" data-facility-mix>
            <TriangleAlert size={13} aria-hidden="true" /> {mixText(r.mixFailed)}
          </span>
        )}
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

/** The phone's feed line: the tank's readings, the due flag and what stock is low, in one button. */
function PhoneFeed({ r, open }: { r: FacilityRoom; open: Open }) {
  const { room, tank } = r;
  const level = tank.level.value;
  const readings = tankReadingText({ ph: tank.ph.value, ec: tank.ec.value, temperature: tank.temperature.value });
  const low = r.stock.filter((t) => t.state !== "ok");
  return (
    <button
      type="button"
      className="facility-phone-feed"
      onClick={() => open(room.id, "equipment/dosing")}
    >
      {/* The button's name is its text: the readings, the due flag and what is low. */}
      <span className="sr-only">Open {room.name} tank and feed: </span>
      <span aria-hidden="true">
        <FeedTankDrawing
          level={level}
          minimum={r.reservoir.minimum}
          full={tank.fill.on}
          low={r.reservoir.state === "held"}
          label={level === null ? "Tank level unavailable" : `Tank ${number(level, 0)} % full`}
        />
      </span>
      <span className="facility-phone-feed-text">
        <strong>Feed {level === null ? "—" : `${number(level, 0)}%`}</strong>
        {r.reservoir.aboveMinimumL !== null && ` · ${formatVolume(r.reservoir.aboveMinimumL, 0)}`}
        {tank.ph.value !== null && (
          <>
            {" · "}
            <span className="facility-nowrap">pH {readings.ph}</span>
          </>
        )}
        {r.feedCalibrationDue && (
          <span className="facility-due" data-facility-due>
            Calibration due
          </span>
        )}
        {tank.ec.value !== null && (
          <>
            {" · "}
            <span className="facility-nowrap">EC {readings.ec}</span>
          </>
        )}
      </span>
      {r.mixFailed && (
        <span className="facility-flag" data-level="critical" data-facility-mix>
          <TriangleAlert size={13} aria-hidden="true" /> {mixText(r.mixFailed)}
        </span>
      )}
      {low.length > 0 && (
        <span className="facility-phone-low">
          {low.map((t) => `${t.name} ${STOCK_STATES[t.state].toLowerCase()}`).join(" · ")}
        </span>
      )}
    </button>
  );
}
