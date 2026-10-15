import { useEffect, useId, useState } from "react";
import { ArrowRight, Check, ChevronDown, ChevronRight, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, number, time as clock, type Page } from "@/components/dashboard";
import { RoomOffBanner } from "@/components/room-controls";
import {
  roomReference,
  zoneAttention,
  type AttentionReason,
  type ZoneFacts,
} from "@/lib/attention";
import { bandStatus, rangeText, steeringOf } from "@/lib/day-chart";
import { growDay, type GrowDay } from "@/lib/day-timeline";
import {
  attachOutcomes,
  jevChanges,
  jevChangeText,
  jevIds,
  outcomeText,
  parseJevSetpoints,
  readJev,
  type JevEntry,
} from "@/lib/jev";
import { numeric, readable, roomStatus } from "@/lib/model";
import { buildSetpointPreview } from "@/lib/setpoint-preview";
import { tankTelemetry } from "@/lib/tank-telemetry";
import { eventTimes } from "@/lib/timeline";
import type { Controller, EntityState, LogEvent, Metric, Notice, States, Zone } from "@/lib/types";
import { useRecentHistory } from "@/lib/use-recent-moisture";
import { waitingText } from "@/lib/waiting-for";
import { dailyWater } from "@/lib/water-delivery";
import { plantAmount, roomPlants } from "@/lib/water-view";
import "./today.css";

const H = 3_600_000;
const PHASE_NAMES: Record<string, string> = {
  P0: "Morning dryback",
  P1: "Ramp-up",
  P2: "Maintenance",
  P3: "Overnight dryback",
};
const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const perPlant = (ml: number) => {
  const { value, unit, digits } = plantAmount(ml);
  return `${number(value, digits)} ${unit}`;
};

/** Why a zone's reading is not usable: the controller's rule is a fresh, readable number. */
function readingIssue(metric: Metric, states: States): string | null {
  if (metric.value !== null) return null;
  const entity = metric.entityId ? states[metric.entityId] : undefined;
  if (!entity) return "not mapped";
  if (!readable(entity) || numeric(entity) === null) return "not reporting";
  return "not reporting lately";
}
/** The probes a zone's combined reading leaves out (the integration's fused sensor attributes). */
function excludedProbes(entity: EntityState | undefined, kind: "vwc" | "ec") {
  const excluded = entity?.attributes.excluded;
  return excluded && typeof excluded === "object" && !Array.isArray(excluded)
    ? Object.entries(excluded as Record<string, unknown>).map(([probe, reason]) => ({
        probe,
        reason: typeof reason === "string" && reason ? reason : "left out",
        kind,
      }))
    : [];
}
/** A shot in P3 is a rescue: the controller waters overnight only below the rescue floor. */
const isRescue = (event: LogEvent) =>
  event.zoneId !== undefined &&
  event.type === "water" &&
  /\bP3\b|rescue|emergency/i.test(event.message);

/** When the zone's last shot was, the short way: its time today, "yesterday 21:40", or its date. */
function shotWhen(stamp: string | null, day: GrowDay | null, now: number): string {
  if (!stamp) return "none recorded";
  const at = Date.parse(stamp);
  if (day && at >= day.start) return clock(at);
  if (now - at < 36 * H) return `yesterday ${clock(at)}`;
  return new Date(at).toLocaleDateString([], { month: "short", day: "numeric" });
}

/** What comes next for the zone, in a few words: the controller's own first condition, without the
 * reading the card already shows. */
function nextWords(zone: Zone, stopped: string | null, rescue: number | null): string {
  if (stopped) return `not watering: ${stopped}`;
  if (zone.waiting) {
    // Under the re-water point already: the controller fires at its next check.
    const topup = zone.waiting.conditions.find((item) => item.rule === "p2_topup");
    if (
      typeof topup?.now === "number" &&
      typeof topup.value === "number" &&
      topup.now < topup.value
    )
      return "shot due now";
    const text = waitingText(zone.waiting, { number: (value) => number(value), clock });
    const first = text
      .split(" · ")[0]
      .replace(/\s*\([^)]*\)/g, "")
      .trim();
    if (first) return first;
  }
  if (zone.phase === "P3")
    return rescue === null ? "no shots until lights-on" : `rescue only under ${number(rescue)}%`;
  if (zone.phase === "P0") return "waits for its morning dryback";
  if (zone.phase === "P1") return "ramp shots to its peak";
  if (zone.phase === "P2") return "shot when it dries to its re-water point";
  return "not known yet";
}

interface Card {
  zone: Zone;
  facts: ZoneFacts;
  peak: number | null;
  rescue: number | null;
  readings: { time: number; value: number }[];
  water: ReturnType<typeof dailyWater>;
  stopped: string | null;
}

/** Today: is the room OK, which zone needs a person and why, where each zone is in its day and what
 * comes next, and what Jev changed. Everything else is one tap deeper. */
export function Today({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: (page: Page, zone?: number) => void;
}) {
  const [, tick] = useState(0);
  useEffect(() => {
    // The clock moves between live updates, and a quiet controller sends none.
    const timer = window.setInterval(() => tick((value) => value + 1), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const { room, states } = controller;
  const now = Date.now();
  const prefix = room.room.prefix;
  const day = growDay(
    numeric(states[`number.crop_steering_${prefix}lights_on_hour`]),
    numeric(states[`number.crop_steering_${prefix}lights_off_hour`]),
    now,
  );
  // Today's readings from lights-on, and at least the last three hours (a morning keeps the night).
  const from = Math.min(day?.start ?? now - 12 * H, now - 3 * H);
  const history = useRecentHistory(
    controller,
    room.zones.map((zone) => zone.vwc.entityId).filter((id): id is string => !!id),
    Math.min(24, Math.ceil((now - from) / H) + 1),
  );
  const jev = readJev(states, prefix);
  const stage = jev.room?.stage ?? null;
  const plants = roomPlants(controller);
  const cards: Card[] = room.zones.map((zone) => {
    const saved = buildSetpointPreview(room, states, zone.id, {}).saved.parameters;
    const water = dailyWater(zone, plants[zone.id] ?? null);
    const series = history?.find((item) => item.entityId === zone.vwc.entityId);
    const readings = (series?.points ?? [])
      .map((point) => ({ time: Date.parse(point.time), value: point.value }))
      .filter((point) => Number.isFinite(point.time) && point.time >= from && point.time <= now);
    if (zone.vwc.value !== null && readings.length && readings.at(-1)!.time < now - 60_000)
      readings.push({ time: now, value: zone.vwc.value });
    const stopped = !room.roomActive
      ? "the room is off"
      : zone.stale
        ? "the controller is not reporting"
        : room.engine.enabled === false
          ? "watering is switched off"
          : zone.enabled === false
            ? "zone scheduling is paused"
            : null;
    const last = zone.lastIrrigation.timestamp ? Date.parse(zone.lastIrrigation.timestamp) : null;
    return {
      zone,
      peak: saved.p1_target_vwc ?? null,
      rescue: saved.p3_emergency_vwc_threshold ?? null,
      readings,
      water,
      stopped,
      facts: {
        id: zone.id,
        name: zone.name,
        phase: zone.phase,
        vwc: zone.vwc.value,
        ec: zone.ec.value,
        vwcIssue: readingIssue(zone.vwc, states),
        ecIssue: readingIssue(zone.ec, states),
        excluded: [
          ...excludedProbes(zone.vwc.entityId ? states[zone.vwc.entityId] : undefined, "vwc"),
          ...excludedProbes(zone.ec.entityId ? states[zone.ec.entityId] : undefined, "ec"),
        ],
        mlPerPlant: water.mlPerPlant,
        rewater: saved.p2_vwc_threshold ?? null,
        // Until the readings arrive the rule cannot tell how long the zone has been under.
        readings: history ? readings : [],
        lastShot: last,
        jevPausedUntil:
          parseJevSetpoints(states[jevIds(prefix).zone(zone.id)])?.pausedUntil ?? null,
        watering: !stopped,
      },
    };
  });
  const times = eventTimes(room.events, now);
  const rescues = room.events.flatMap((event, index) => {
    const time = isRescue(event) ? times[index] : null;
    return time === null ? [] : [{ zoneId: event.zoneId!, time }];
  });
  const attention = zoneAttention({
    now,
    zones: cards.map((card) => card.facts),
    poreEc: stage?.poreEc ?? null,
    notices: room.alerts,
    rescues,
    format: { clock, number: (value, digits = 1) => number(value, digits), perPlant },
  });
  if (!controller.roomId || !room.zones.length)
    return (
      <>
        <h1 className="today-empty-title">Today</h1>
        <section className="panel">
          <Empty
            title="No zones discovered"
            detail="Connect Home Assistant in Settings. Zones are discovered from the controller entities available to your account."
            action={<Button onClick={() => navigate("settings")}>Open connection settings</Button>}
          />
        </section>
      </>
    );
  return (
    <div className="today" data-today>
      <TodayStatus controller={controller} day={day} now={now} navigate={navigate} />
      <TankLine controller={controller} navigate={navigate} />
      <section className="today-zones" aria-label="Zones">
        {cards.map((card) => (
          <ZoneCard
            key={card.zone.id}
            card={card}
            cards={cards}
            day={day}
            now={now}
            band={stage?.poreEc ?? null}
            reasons={attention.get(card.zone.id) ?? []}
            open={() => navigate("zone", card.zone.id)}
          />
        ))}
      </section>
      {jev.log && (
        <JevToday
          controller={controller}
          entries={jev.log.entries}
          day={day}
          openHistory={() => navigate("history/timeline")}
        />
      )}
    </div>
  );
}

/** One line for the room: watering, the stage and its day of flower, steering, lights, the phase now
 * and the open alerts. A room that is not watering says why and what to do. */
function TodayStatus({
  controller,
  day,
  now,
  navigate,
}: {
  controller: Controller;
  day: GrowDay | null;
  now: number;
  navigate: (page: Page) => void;
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const { room, states } = controller;
  const status = roomStatus(states, room.room, now);
  const stage = readJev(states, room.room.prefix).room?.stage ?? null;
  const steering = stage
    ? steeringOf(null, stage.steering)
    : steeringOf(states[`select.crop_steering_${room.room.prefix}steering_mode`]?.state, null);
  const phases = [...new Set(room.zones.map((zone) => zone.phase))].filter((phase) =>
    /^P[0-3]$/.test(phase),
  );
  // The stock line below says what is low; the rest are the room's open alerts.
  const notices = room.alerts.filter((notice) => !notice.id.endsWith("-stock-low"));
  const alerts = notices.filter((notice) => notice.severity !== "info");
  const critical = notices.filter(
    (notice) => notice.severity === "critical" && notice.zoneId === undefined,
  );
  const watering = room.engine.enabled;
  return (
    <section className="today-head" aria-labelledby="today-title">
      <div className="today-title">
        <h1 id="today-title">{room.room.name} today</h1>
        <span className="today-state" data-tone={status.tone} title={status.detail}>
          {status.text}
        </span>
      </div>
      <p className="today-line" data-today-line>
        <span className="today-fact" data-watering={watering === null ? "unknown" : watering}>
          <i aria-hidden="true" />
          {watering === true
            ? "Watering on"
            : watering === false
              ? "Watering off"
              : "Watering unknown"}
        </span>
        {stage && (
          <span className="today-fact">
            <strong>{capital(stage.name)}</strong>
            {stage.day !== null &&
              ` · day ${stage.day}${stage.days !== null ? ` of ${stage.days}` : ""}`}
          </span>
        )}
        {steering && (
          <span className="today-fact today-steering" data-steering={steering}>
            {capital(steering)}
          </span>
        )}
        {stage?.poreEc && <span className="today-fact">Pore EC {rangeText(stage.poreEc)}</span>}
        {day && (
          <span
            className="today-fact"
            title={`Lights on ${clock(day.start)}–${clock(day.lightsOff)}: the grow-day runs from one lights-on to the next.`}
          >
            {now < day.lightsOff
              ? `Lights on until ${clock(day.lightsOff)}`
              : `Lights off until ${clock(day.end)}`}
          </span>
        )}
        {phases.length > 0 && (
          <span className="today-fact">
            Now{" "}
            {phases.length === 1
              ? `${phases[0]} ${PHASE_NAMES[phases[0]].toLowerCase()}`
              : phases.join(" and ")}
          </span>
        )}
        {notices.length > 0 && (
          <button
            type="button"
            className="today-alerts"
            data-severity={
              alerts.some((notice) => notice.severity === "critical")
                ? "critical"
                : alerts.length
                  ? "warning"
                  : "info"
            }
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen(!open)}
          >
            {alerts.length > 0 ? (
              <>
                <TriangleAlert size={14} aria-hidden="true" />
                {alerts.length} {alerts.length === 1 ? "alert" : "alerts"}
              </>
            ) : (
              // Only notes (a grow plan in control, a shot running): no alert, but worth a look.
              <>
                No alerts · {notices.length} {notices.length === 1 ? "note" : "notes"}
              </>
            )}
            <ChevronDown size={14} aria-hidden="true" className="today-alerts-chevron" />
          </button>
        )}
        {notices.length === 0 && <span className="today-fact muted">No alerts</span>}
      </p>
      {!room.roomActive && <RoomOffBanner controller={controller} />}
      {room.roomActive && (status.tone === "stopped" || status.tone === "stale") && (
        <p className="today-stopped" role="status">
          <TriangleAlert size={16} aria-hidden="true" />
          <span>
            <strong>{status.text}.</strong> {status.detail}{" "}
            {status.action && (
              <button type="button" className="inline-action" onClick={() => navigate("settings")}>
                {status.action.label}
              </button>
            )}
          </span>
        </p>
      )}
      {critical.map((notice) => (
        <NoticeLine key={notice.id} notice={notice} />
      ))}
      <ul className="today-alert-list" id={listId} hidden={!open}>
        {notices.map((notice) => (
          <li key={notice.id} data-severity={notice.severity}>
            <NoticeLine notice={notice} plain />
          </li>
        ))}
      </ul>
    </section>
  );
}
function NoticeLine({ notice, plain = false }: { notice: Notice; plain?: boolean }) {
  return (
    <p
      className={plain ? "today-notice" : "today-notice today-critical"}
      role={plain ? undefined : "alert"}
    >
      <strong>{notice.title}.</strong> {notice.detail}
    </p>
  );
}

/** The feed and stock tanks, only when something is low or out of range: one line. */
function TankLine({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: (page: Page) => void;
}) {
  const { room, states } = controller;
  const problems: string[] = [];
  const stock = states[`sensor.crop_steering_${room.room.prefix}stock_low`]?.attributes.tanks;
  for (const tank of Array.isArray(stock) ? stock : [])
    if (tank && typeof tank === "object" && (tank as { low?: unknown }).low === true) {
      const { name, level_l, batches_left } = tank as {
        name?: string;
        level_l?: number;
        batches_left?: number | null;
      };
      problems.push(
        `${name ?? "A stock tank"} low: ${number(level_l ?? null)} L` +
          (typeof batches_left === "number"
            ? `, about ${batches_left} batch${batches_left === 1 ? "" : "es"} left`
            : ""),
      );
    }
  const tank = tankTelemetry(states, room.room);
  if (tank.level.value !== null && tank.level.value < 10)
    problems.push(`Feed tank nearly empty: ${number(tank.level.value, 0)}%`);
  // The source-water gate holds every shot while the feed reads outside its limits.
  const descriptor = Object.values(states).find(
    (entity) =>
      /^sensor\.crop_steering_.*engine_config$/.test(entity.entity_id) &&
      entity.attributes.prefix === room.room.prefix,
  );
  for (const [key, label, unit] of [
    ["ec", "Feed EC", " mS/cm"],
    ["ph", "Feed pH", ""],
  ] as const) {
    const probe = descriptor?.attributes[`feed_${key}_sensor`];
    const value = typeof probe === "string" && probe ? numeric(states[probe]) : null;
    const limit = (end: "min" | "max") =>
      numeric(states[`number.crop_steering_${room.room.prefix}irrigation_${key}_${end}`]);
    const low = limit("min"),
      high = limit("max");
    if (value === null) continue;
    if ((low && value < low) || (high && value > high))
      problems.push(
        `${label} ${number(value, 2)}${unit} is outside ${number(low ?? 0)}–${number(high ?? 0)}: shots wait`,
      );
  }
  if (!problems.length) return null;
  return (
    <p className="today-tank" role="status" data-today-tank>
      <TriangleAlert size={16} aria-hidden="true" />
      <span>{problems.join(" · ")}</span>
      <button type="button" className="inline-action" onClick={() => navigate("equipment/stock")}>
        Equipment <ArrowRight size={14} aria-hidden="true" />
      </button>
    </p>
  );
}

/** Where moisture sits between the rescue floor, the re-water point and the peak target. */
function MoistureBar({
  value,
  rescue,
  rewater,
  peak,
}: {
  value: number | null;
  rescue: number | null;
  rewater: number | null;
  peak: number | null;
}) {
  const known = [value, rescue, rewater, peak].filter((item): item is number => item !== null);
  if (value === null || known.length < 2) return null;
  const lo = Math.max(0, Math.min(...known) - 4),
    hi = Math.min(100, Math.max(...known) + 4);
  const at = (level: number) => `${((level - lo) / (hi - lo)) * 100}%`;
  const marks = [
    { key: "rescue", level: rescue, label: "rescue" },
    { key: "rewater", level: rewater, label: "re-water" },
    { key: "peak", level: peak, label: "peak" },
  ].filter((mark): mark is { key: string; level: number; label: string } => mark.level !== null);
  const words = marks.map((mark) => `${mark.label} ${number(mark.level)}%`).join(", ");
  return (
    <div className="moisture-bar">
      <div
        className="moisture-track"
        role="img"
        aria-label={`Moisture ${number(value)}%: ${words}`}
      >
        {rewater !== null && peak !== null && peak > rewater && (
          <span
            className="moisture-band"
            style={{ left: at(rewater), width: `calc(${at(peak)} - ${at(rewater)})` }}
          />
        )}
        {marks.map((mark) => (
          <span
            key={mark.key}
            className="moisture-mark"
            data-mark={mark.key}
            style={{ left: at(mark.level) }}
          />
        ))}
        <span className="moisture-now" style={{ left: at(Math.max(lo, Math.min(hi, value))) }} />
      </div>
      <p className="moisture-legend" aria-hidden="true">
        {marks.map((mark) => (
          <span key={mark.key} data-mark={mark.key}>
            {mark.label} {number(mark.level)}
          </span>
        ))}
      </p>
    </div>
  );
}

/** Today's moisture as one line, no axes: its shape, not its numbers. */
function DaySpark({ points, name }: { points: { time: number; value: number }[]; name: string }) {
  if (points.length < 2)
    return <span className="today-spark today-spark-empty" aria-hidden="true" />;
  const t0 = points[0].time,
    span = points.at(-1)!.time - t0 || 1;
  const values = points.map((point) => point.value);
  const lo = Math.min(...values),
    hi = Math.max(...values);
  const x = (time: number) => ((time - t0) / span) * 100;
  const y = (value: number) => (hi === lo ? 20 : 37 - ((value - lo) / (hi - lo)) * 34);
  const d = points
    .map(
      (point, index) =>
        `${index ? "L" : "M"}${x(point.time).toFixed(2)} ${y(point.value).toFixed(2)}`,
    )
    .join("");
  const last = points.at(-1)!;
  return (
    <svg
      className="today-spark"
      viewBox="0 0 100 40"
      preserveAspectRatio="none"
      role="img"
      aria-label={`${name} moisture today, ${number(lo)} to ${number(hi)}%`}
    >
      <path d={d} vectorEffect="non-scaling-stroke" />
      {/* A round dot however the line is stretched: a zero-length stroke with round caps. */}
      <path
        className="today-spark-now"
        d={`M${x(last.time).toFixed(2)} ${y(last.value).toFixed(2)}h0`}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function ZoneCard({
  card,
  cards,
  day,
  now,
  band,
  reasons,
  open,
}: {
  card: Card;
  cards: Card[];
  day: GrowDay | null;
  now: number;
  band: [number, number] | null;
  reasons: AttentionReason[];
  open: () => void;
}) {
  const { zone, facts, water } = card;
  const top = reasons[0];
  const ec = bandStatus(zone.ec.value, band);
  const reference = roomReference(
    cards.map((item) => item.facts),
    zone.id,
  );
  const share =
    reference && water.mlPerPlant !== null && reference.ml > 0
      ? water.mlPerPlant / reference.ml
      : null;
  const next = nextWords(zone, card.stopped, card.rescue);
  const title = [
    `Open ${zone.name}`,
    ...reasons.map(
      (reason) => `${reason.level === "critical" ? "Needs you now" : "Check"}: ${reason.text}`,
    ),
  ].join("\n");
  return (
    <article
      className="today-zone"
      data-zone={zone.id}
      data-attention={top?.level}
      aria-labelledby={`today-zone-${zone.id}`}
    >
      <header className="today-zone-head">
        <h2 id={`today-zone-${zone.id}`}>
          <a
            href={`#/zone/${zone.id}`}
            className="today-zone-link"
            title={title}
            onClick={(event) => {
              event.preventDefault();
              open();
            }}
          >
            {zone.name}
            <ChevronRight size={17} aria-hidden="true" className="today-zone-go" />
          </a>
        </h2>
        {/^P[0-3]$/.test(zone.phase) ? (
          <span className="pill" data-phase={zone.phase}>
            {zone.phase} · {PHASE_NAMES[zone.phase]}
          </span>
        ) : (
          <span className="pill" data-tone="unknown">
            Phase unavailable
          </span>
        )}
      </header>
      {top && (
        <p className="today-flag" data-level={top.level}>
          <TriangleAlert size={15} aria-hidden="true" />
          <span>
            {top.text}
            {reasons.length > 1 && (
              <span className="today-flag-more"> +{reasons.length - 1} more</span>
            )}
          </span>
        </p>
      )}
      <div className="today-moisture">
        <p className="today-vwc">
          <span className="sr-only">Moisture </span>
          <strong>{zone.vwc.value === null ? "—" : number(zone.vwc.value)}</strong>
          {zone.vwc.value !== null && <span className="unit">%</span>}
        </p>
        <DaySpark points={card.readings} name={zone.name} />
      </div>
      <MoistureBar
        value={zone.vwc.value}
        rescue={card.rescue}
        rewater={facts.rewater}
        peak={card.peak}
      />
      <dl className="today-zone-facts">
        <div>
          <dt>Pore EC</dt>
          <dd>
            {zone.ec.value === null ? "—" : number(zone.ec.value, 2)}
            {band && ec && ec !== "in" && top?.rule !== "pore-ec" && (
              <span className="today-chip" data-status={ec}>
                {ec} {rangeText(band)}
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt>Water</dt>
          <dd>
            {water.mlPerPlant !== null ? (
              <>
                {perPlant(water.mlPerPlant)}/plant
                {share !== null && (
                  <span className="muted">
                    {" · "}
                    {share >= 0.9 && share <= 1.1
                      ? `≈ ${reference!.name ?? "the room"}`
                      : `${number(share)}× ${reference!.name ?? "the room"}`}
                  </span>
                )}
              </>
            ) : water.zoneL !== null ? (
              <>
                {number(water.zoneL)} L<span className="muted"> · plant count not set</span>
              </>
            ) : (
              "—"
            )}
          </dd>
        </div>
        <div>
          <dt>Last shot</dt>
          <dd>
            {zone.lastIrrigation.timestamp ? (
              <time dateTime={zone.lastIrrigation.timestamp} data-last-irrigation={zone.id}>
                {shotWhen(zone.lastIrrigation.timestamp, day, now)}
              </time>
            ) : (
              shotWhen(zone.lastIrrigation.timestamp, day, now)
            )}
            {zone.shots.value !== null && (
              <span className="muted">
                {" · "}
                {number(zone.shots.value, 0)} today
              </span>
            )}
          </dd>
        </div>
        <div className="today-next" data-stopped={card.stopped ? "" : undefined}>
          <dt>Next</dt>
          <dd>{next}</dd>
        </div>
      </dl>
    </article>
  );
}

/** What Jev changed today: only what moved something, newest first, three at most. */
function JevToday({
  controller,
  entries,
  day,
  openHistory,
}: {
  controller: Controller;
  entries: JevEntry[];
  day: GrowDay | null;
  openHistory: () => void;
}) {
  const { room, states } = controller;
  const since = day?.start ?? Date.now() - 24 * H;
  const changes = jevChanges(entries, since);
  const { outcomes } = attachOutcomes(entries);
  const names = new Map(room.zones.map((zone) => [zone.id, zone.name]));
  const managed = room.zones.some(
    (zone) => parseJevSetpoints(states[jevIds(room.room.prefix).zone(zone.id)])?.managed,
  );
  const check =
    day && managed
      ? ` · Jev’s next setpoint check tonight ${clock(day.lightsOff)}–${clock(day.lightsOff + 3 * H)}`
      : "";
  return (
    <section className="panel today-jev" aria-labelledby="today-jev-title" data-jev-today>
      <div className="panel-heading">
        <h2 id="today-jev-title">What Jev changed today</h2>
        <Button variant="ghost" size="sm" onClick={openHistory}>
          History <ArrowRight size={15} aria-hidden="true" />
        </Button>
      </div>
      {changes.length ? (
        <ol className="today-jev-list">
          {changes.slice(0, 3).map((entry) => {
            const checked = outcomes.get(entry.key)?.at(-1);
            return (
              <li key={entry.key}>
                <time dateTime={new Date(entry.time!).toISOString()}>{clock(entry.time)}</time>
                <span className="today-jev-zone">
                  {entry.zone === null ? "Room" : (names.get(entry.zone) ?? `Zone ${entry.zone}`)}
                </span>
                <span className="today-jev-what">
                  <strong>{entry.title}</strong> → {jevChangeText(entry)}
                </span>
                {checked && (
                  <span
                    className="today-jev-outcome"
                    data-worked={checked.result === "worked"}
                    title={outcomeText(checked)}
                  >
                    {checked.result === "worked" ? (
                      <Check size={14} aria-hidden="true" />
                    ) : (
                      <X size={14} aria-hidden="true" />
                    )}
                    <span className="sr-only">{outcomeText(checked)}</span>
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="today-jev-none">Nothing changed today{check}</p>
      )}
    </section>
  );
}
