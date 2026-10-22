import { useEffect, useId, useState, type MouseEvent } from "react";
import { ArrowRight, ChevronDown, Pause, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Empty, number, type Page } from "@/components/dashboard";
import { RoomOffBanner } from "@/components/room-controls";
import { BrainCard } from "@/components/brain";
import { NeedsIntegration } from "@/components/needs-integration";
import { PlanAndFeed } from "@/components/run-progress";
import { PlantStressStrip } from "@/components/sensing";
import { ShotTimeline } from "@/components/shot-timeline";
import { DrinkBar } from "@/components/zone-gauges";
import { ZoneSlab } from "@/components/zone-slab";
import { zoneAttention, type AttentionLevel, type AttentionReason, type ZoneFacts } from "@/lib/attention";
import { growDay, type GrowDay } from "@/lib/day-timeline";
import { formatTemp, formatVolume } from "@/lib/display-units";
import { pickKey } from "@/lib/facility";
import { drinkLine, excludedProbes, isRescue, readingIssue, ZONE_MODE, zoneHref } from "@/lib/facility-view";
import type { GaugeModel } from "@/lib/hmi";
import { probeGaps } from "@/lib/hmi";
import { jevIds, parseJevSetpoints, readJev } from "@/lib/jev";
import { numeric, roomStatus, staleBanner } from "@/lib/model";
import { useParity } from "@/lib/parity-api";
import type { TimelineGetData } from "@/lib/parity-types";
import { buildSetpointPreview } from "@/lib/setpoint-preview";
import { toTimelineRows, type TimelineRow } from "@/lib/shot-timeline";
import { tankTelemetry } from "@/lib/tank-telemetry";
import { clock, hourTicks, startOfDay } from "@/lib/time";
import { eventTimes } from "@/lib/timeline";
import {
  drinkDelta,
  pausedText,
  roomView,
  targetText,
  type RoomView,
  type RoomZoneRow,
} from "@/lib/today-room";
import type { Controller, Notice, Zone } from "@/lib/types";
import { offerUndo } from "@/lib/undo";
import { useRecentHistory } from "@/lib/use-recent-moisture";
import { dailyWater } from "@/lib/water-delivery";
import { plantAmount, roomPlants } from "@/lib/water-view";
import "./today.css";

const H = 3_600_000;
const PHASE_NAMES: Record<string, string> = {
  P0: "Dryback",
  P1: "Ramp",
  P2: "Maintenance",
  P3: "Overnight",
};
const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const perPlant = (ml: number) => {
  const { value, unit, digits } = plantAmount(ml);
  return `${number(value, digits)} ${unit}`;
};

/** The Room page (mockup 03): the room's day and water, today's shots as a strip, and a row per zone
 * with its water against the room, its gauges against their targets, its sensors with their trouble
 * in place, and a paused zone's way back. Everything else is one tap deeper. */
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
    controller.timeZone,
  );
  // Today's readings from lights-on, and at least the last three hours (a morning keeps the night):
  // the attention rule needs them to tell how long a zone has been under its re-water point.
  const from = Math.min(day?.start ?? now - 12 * H, now - 3 * H);
  const history = useRecentHistory(
    controller,
    room.zones.map((zone) => zone.vwc.entityId).filter((id): id is string => !!id),
    Math.min(24, Math.ceil((now - from) / H) + 1),
  );
  const view = roomView(controller, now);
  const stage = readJev(states, prefix).room?.stage ?? null;
  const plants = roomPlants(controller);
  const facts: ZoneFacts[] = room.zones.map((zone) => {
    const saved = buildSetpointPreview(room, states, zone.id, {}).saved.parameters;
    const series = history?.find((item) => item.entityId === zone.vwc.entityId);
    const { clean: readings } = probeGaps(
      (series?.points ?? [])
        .map((point) => ({ time: Date.parse(point.time), value: point.value }))
        .filter((point) => Number.isFinite(point.time) && point.time >= from && point.time <= now),
    );
    if (zone.vwc.value !== null && readings.length && readings.at(-1)!.time < now - 60_000)
      readings.push({ time: now, value: zone.vwc.value });
    const stopped =
      !room.roomActive || zone.stale || room.engine.enabled === false || zone.enabled === false;
    return {
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
      mlPerPlant: dailyWater(zone, plants[zone.id] ?? null).mlPerPlant,
      rewater: saved.p2_vwc_threshold ?? null,
      // Until the readings arrive the rule cannot tell how long the zone has been under.
      readings: history ? readings : [],
      lastShot: zone.lastIrrigation.timestamp ? Date.parse(zone.lastIrrigation.timestamp) : null,
      jevPausedUntil: parseJevSetpoints(states[jevIds(prefix).zone(zone.id)])?.pausedUntil ?? null,
      watering: !stopped,
    };
  });
  const times = eventTimes(room.events, now);
  const rescues = room.events.flatMap((event, index) => {
    const time = isRescue(event) ? times[index] : null;
    return time === null ? [] : [{ zoneId: event.zoneId!, time }];
  });
  const attention = zoneAttention({
    now,
    zones: facts,
    poreEc: stage?.poreEc ?? null,
    notices: room.alerts,
    rescues,
    format: {
      clock: (time) => clock(time, controller.timeZone),
      number: (value, digits = 1) => number(value, digits),
      perPlant,
    },
  });
  if (!controller.roomId || !room.zones.length || !view)
    return (
      <>
        <h1 className="today-empty-title">Today</h1>
        <section className="panel">
          <Empty
            title="No zones found"
            detail="Connect Home Assistant in Settings. Zones are discovered from the controller entities available to your account."
            action={<Button onClick={() => navigate("settings")}>Open connection settings</Button>}
          />
        </section>
      </>
    );
  const drunk = view.rows.map((row) => row.drink?.ml ?? 0);
  const maxMl = Math.max(1, ...drunk, ...view.rows.map((row) => row.drink?.median ?? 0)) * 1.15;
  return (
    <div className="today" data-today>
      <RoomHead controller={controller} view={view} day={day} now={now} navigate={navigate} />
      <TodayStrip controller={controller} view={view} day={day} now={now} navigate={navigate} />
      {/* The header owns the run's day; the grow plan and today's feed stay here. */}
      <PlanAndFeed controller={controller} />
      <TankLine controller={controller} navigate={navigate} />
      <PlantStressStrip controller={controller} />
      <section className="today-zones" aria-label="Zones">
        {view.rows.map((row) => (
          <ZoneRow
            key={row.zone}
            controller={controller}
            row={row}
            // A paused zone's pause line says why it has no water: not again as a flag.
            reasons={(attention.get(row.zone) ?? []).filter(
              (reason) => !row.paused || (reason.rule !== "water" && reason.rule !== "not-watered"),
            )}
            maxMl={maxMl}
            now={now}
            open={() => navigate("zone", row.zone)}
            navigate={navigate}
          />
        ))}
      </section>
      <BrainCard controller={controller} navigate={navigate} showLastDecision={false} />
    </div>
  );
}

/** The room in two lines: its name, state, stage and plants, where the grow is (day, days left,
 * harvest, and the stage's end on its run bar); then today's water, the lights and the climate. A
 * room that is not watering says why and what to do; its open alerts open below. */
function RoomHead({
  controller,
  view,
  day,
  now,
  navigate,
}: {
  controller: Controller;
  view: RoomView;
  day: GrowDay | null;
  now: number;
  navigate: (page: Page, zone?: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const { room, states, timeZone } = controller;
  const status = roomStatus(states, room.room, now);
  const banner = staleBanner(states, room.room, now) !== null;
  const r = view.room;
  const plants = Object.values(roomPlants(controller)).reduce<number>(
    (sum, count) => sum + (count ?? 0),
    0,
  );
  const grow = r.growDay;
  const stageName = grow?.stage || r.stage?.name || "";
  const harvest =
    grow?.daysLeft != null
      ? new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone }).format(
          now + grow.daysLeft * 86_400_000,
        )
      : null;
  const drink = drinkLine(r.waterL, r.litresPerPlant);
  const air = r.climate.find((c) => c.key === "temperature");
  const rh = r.climate.find((c) => c.key === "humidity");
  const vpd = r.climate.find((c) => c.key === "vpd");
  // The stock line below says what is low; the rest are the room's open alerts.
  const notices = room.alerts.filter((notice) => !notice.id.endsWith("-stock-low"));
  const alerts = notices.filter((notice) => notice.severity !== "info");
  const critical = notices.filter(
    (notice) => notice.severity === "critical" && notice.zoneId === undefined,
  );
  const pct = (value: number) => `${Math.min(100, Math.max(0, (value / grow!.of!) * 100))}%`;
  return (
    <section className="today-head" aria-labelledby="today-title">
      <div className="today-title">
        <span className="today-dot" data-tone={status.tone} title={status.detail} aria-hidden="true" />
        <h1 id="today-title">{room.room.name}</h1>
        <p className="today-sub" data-today-sub>
          <span className="today-state" data-tone={status.tone} title={status.detail}>
            {status.text}
          </span>
          {stageName && <span> · {capital(stageName)}</span>}
          {plants > 0 && (
            <span>
              {" "}
              · {plants} plants in {room.zones.length} zone{room.zones.length === 1 ? "" : "s"}
            </span>
          )}
        </p>
        {grow && (
          <p className="today-day" data-today-day>
            Day <strong>{grow.day}</strong>
            {grow.of !== null && ` of ${grow.of}`}
            {grow.daysLeft !== null && <span className="muted"> · {grow.daysLeft} days left</span>}
            {harvest && <span className="muted"> · harvest {harvest}</span>}
          </p>
        )}
      </div>
      {grow?.of != null && (
        <div className="today-run" data-today-run>
          <span className="today-run-track" aria-hidden="true">
            <span className="today-run-fill" style={{ width: pct(grow.day) }} />
            <span className="today-run-now" style={{ left: pct(grow.day) }} />
          </span>
          {view.stageEnd && (
            <span className="today-run-mark" style={{ left: pct(view.stageEnd.day) }}>
              {view.stageEnd.name} ends day {view.stageEnd.day}
            </span>
          )}
        </div>
      )}
      <dl className="today-facts" data-today-line>
        {drink && (
          <div className="today-fact-lead">
            <dt>Water today</dt>
            <dd>
              <strong>{drink.room}</strong> room
              {drink.perPlant && <span> · {drink.perPlant} per watered plant</span>}
            </dd>
          </div>
        )}
        {day && (
          <div title="The grow-day starts at one lights-on and ends at the next lights-on.">
            <dt>Lights</dt>
            <dd>
              {now < day.lightsOff ? "On" : "Off"} {clock(day.start, timeZone)} – {clock(day.lightsOff, timeZone)}
            </dd>
          </div>
        )}
        {air?.value != null && (
          <div className="today-fact-climate">
            <dt>Air (reading)</dt>
            <dd>{air.unit === "°F" ? `${number(air.value, 1)} °F` : formatTemp(air.value, 1)}</dd>
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
        {notices.length > 0 && (
          <div>
            <dt className="sr-only">Alerts</dt>
            <dd>
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
            </dd>
          </div>
        )}
      </dl>
      {!room.roomActive && <RoomOffBanner controller={controller} />}
      {/* A controller that is not reporting has the band under the header instead. */}
      {room.roomActive && status.tone === "stopped" && !banner && (
        <p className="today-stopped" role="status">
          <TriangleAlert size={16} aria-hidden="true" />
          <span>
            <strong>{status.text}.</strong> {status.detail}{" "}
            {status.action && (
              <button
                type="button"
                className="inline-action"
                onClick={() => navigate(status.action!.route as Page)}
              >
                {status.action.label}
              </button>
            )}
          </span>
        </p>
      )}
      {critical.map((notice) => (
        <NoticeLine key={notice.id} notice={notice} zones={room.zones} navigate={navigate} />
      ))}
      <ul className="today-alert-list" id={listId} hidden={!open}>
        {notices.map((notice) => (
          <li key={notice.id} data-severity={notice.severity}>
            <NoticeLine notice={notice} plain zones={room.zones} navigate={navigate} />
          </li>
        ))}
      </ul>
    </section>
  );
}
function NoticeLine({
  notice,
  plain = false,
  zones,
  navigate,
}: {
  notice: Notice;
  plain?: boolean;
  zones: Zone[];
  navigate: (page: Page, zone?: number) => void;
}) {
  // Each zone the notice is about opens its page (a merged notice names them all).
  const linked = (notice.zoneIds ?? []).flatMap((id) => zones.filter((zone) => zone.id === id));
  return (
    <p
      className={plain ? "today-notice" : "today-notice today-critical"}
      role={plain ? undefined : "alert"}
    >
      <strong>{notice.title}.</strong> {notice.detail}
      {linked.map((zone) => (
        <button
          key={zone.id}
          type="button"
          className="inline-action"
          data-notice-zone={zone.id}
          onClick={() => navigate("zone", zone.id)}
        >
          {zone.name}
        </button>
      ))}
    </p>
  );
}

/** Today's shots, a track per zone over the grow-day (lights-on to the next lights-on; midnight to
 * midnight while the lights are unknown): done, planned and the lights. The full timeline is one tap
 * away; an integration before 3.18 has no timeline and says so here. */
function TodayStrip({
  controller,
  view,
  day,
  now,
  navigate,
}: {
  controller: Controller;
  view: RoomView;
  day: GrowDay | null;
  now: number;
  navigate: (page: Page) => void;
}) {
  const { roomId, timeZone, room } = controller;
  const start = day?.start ?? startOfDay(now, timeZone);
  const end = day?.end ?? startOfDay(start + 36 * H, timeZone);
  const timeline = useParity<TimelineGetData>(
    controller,
    "timeline_get",
    { rooms: [roomId], start: new Date(start).toISOString(), end: new Date(end).toISOString() },
    [roomId, start],
  );
  const plants = Object.fromEntries(
    Object.entries(roomPlants(controller)).map(([zone, count]) => [pickKey(roomId, Number(zone)), count ?? 0]),
  );
  const grow = view.room.growDay;
  const all = timeline.data
    ? toTimelineRows(timeline.data, plants, [
        { id: roomId, name: room.room.name, stage: grow?.stage ?? "", day: grow?.day ?? null },
      ])
    : [];
  const head = all.find((row) => row.zone === null);
  // A track for every zone of the room, one with nothing today included.
  const rows: TimelineRow[] = head
    ? [
        head,
        ...room.zones.map(
          (zone): TimelineRow =>
            all.find((row) => row.zone === zone.id) ?? {
              key: pickKey(roomId, zone.id),
              roomId,
              zone: zone.id,
              label: `Zone ${zone.id}`,
              sublabel: "",
              blocks: [],
              lights: head.lights,
            },
        ),
      ]
    : [];
  // The ticks, less any the "now" label would sit on.
  const ticks = [...hourTicks(start, end, 6, timeZone), end].filter(
    (time) => !(now >= start && now < end) || Math.abs(time - now) > (end - start) * 0.12,
  );
  const at = (time: number) => `${(((time - start) / (end - start)) * 100).toFixed(2)}%`;
  return (
    <section className="panel today-strip" aria-labelledby="today-strip-title" data-today-strip>
      <div className="today-strip-head">
        <h2 id="today-strip-title">Today</h2>
        {timeline.state !== "missing" && (
          <ul className="today-strip-legend" aria-label="Legend">
            <li data-glyph="done">Shot done</li>
            <li data-glyph="planned">Planned</li>
            <li data-glyph="lights">Lights on</li>
          </ul>
        )}
        <button
          type="button"
          className="inline-action today-strip-open"
          onClick={() => navigate("plan/watering")}
        >
          Open full timeline <ArrowRight size={14} aria-hidden="true" />
        </button>
      </div>
      {timeline.state === "missing" ? (
        <NeedsIntegration compact feature="Today's watering strip" />
      ) : timeline.state === "error" ? (
        <p className="today-strip-note" role="status">
          Today's shots did not load: {timeline.error}
        </p>
      ) : rows.length ? (
        <div className="today-strip-body">
          <ul className="today-strip-labels" aria-hidden="true">
            {room.zones.map((zone) => (
              <li key={zone.id}>{zone.name}</li>
            ))}
          </ul>
          <ShotTimeline rows={rows} span={{ start, end }} now={now} mode="strip" timeZone={timeZone} />
          <div className="today-strip-axis" aria-hidden="true">
            {ticks.map((time, index) => (
              <span
                key={time}
                style={{ left: at(time) }}
                data-end={time === end || undefined}
                data-odd={index % 2 === 1 || undefined}
              >
                {time === end && !day ? "24:00" : clock(time, timeZone)}
              </span>
            ))}
            {now >= start && now < end && (
              <span className="today-strip-now" style={{ left: at(now) }}>
                now {clock(now, timeZone)}
              </span>
            )}
          </div>
        </div>
      ) : (
        <p className="today-strip-note">Loading today's shots…</p>
      )}
    </section>
  );
}

/** One gauge as its row reads it: the name and its target, a bar with the band and a tick, the value. */
function RoomGauge({ model, value }: { model: GaugeModel; value: string }) {
  const at = (v: number) =>
    `${(Math.min(1, Math.max(0, (v - model.min) / (model.max - model.min || 1))) * 100).toFixed(1)}%`;
  const target = targetText(model);
  return (
    <div className="today-gauge" data-state={model.state}>
      <span className="today-gauge-label">
        {model.label}
        {target && <small>{target}</small>}
      </span>
      <span className="mini-gauge-track" aria-hidden="true">
        {model.band && (
          <span
            className="mini-gauge-band"
            style={{ left: at(model.band[0]), width: `calc(${at(model.band[1])} - ${at(model.band[0])})` }}
          />
        )}
        {model.value !== null && <span className="mini-gauge-tick" style={{ left: at(model.value) }} />}
      </span>
      <span className="today-gauge-value">
        {value}
        {model.state === "abnormal" && <span className="sr-only">, {model.words}</span>}
      </span>
    </div>
  );
}

/** A zone's row: the slab with its sensors, its name and mode, its water against the room's median,
 * its gauges, its sensors (a silent one says when it was last heard and what the zone reads
 * without it), its problems, and a paused zone's way back with Undo. */
function ZoneRow({
  controller,
  row,
  reasons,
  maxMl,
  now,
  open,
  navigate,
}: {
  controller: Controller;
  row: RoomZoneRow;
  reasons: AttentionReason[];
  maxMl: number;
  now: number;
  open: () => void;
  navigate: (page: Page) => void;
}) {
  const { timeZone, roomId } = controller;
  const z = row.view;
  const { zone } = z;
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const level = reasons.reduce<AttentionLevel | null>(
    (worst, reason) => (worst === "critical" || reason.level === "critical" ? "critical" : "warning"),
    null,
  );
  const troubled = row.sensors.some((s) => s.health !== "ok" && s.health !== "not-counted");
  const phase = /^P[0-3]$/.test(zone.phase) ? zone.phase : null;
  const shots = zone.shots.value === null ? null : Math.round(zone.shots.value);
  const name = /^zone\b/i.test(zone.name) ? zone.name.charAt(0).toLowerCase() + zone.name.slice(1) : zone.name;
  // Problems in place: a probe's trouble is on its sensor, pore EC on its gauge, the zone's open
  // alert once.
  const flags = [
    ...(row.problem ? [{ key: "problem", level: level ?? "warning", text: row.problem }] : []),
    ...reasons
      .filter((reason) => reason.rule !== "probe" && reason.rule !== "pore-ec" && reason.text !== z.problem)
      .map((reason) => ({ key: reason.rule, level: reason.level, text: reason.text })),
  ];
  const write = async (on: boolean) => {
    const entityId = zone.enabledEntity!;
    const result = await controller.write([{ entityId, value: on }]);
    return result.applied.includes(entityId)
      ? null
      : (result.failed[0]?.reason ?? "The controller did not confirm the change.");
  };
  const resume = async () => {
    setBusy(true);
    setFailed(null);
    const refused = await write(true);
    setBusy(false);
    if (refused) {
      setFailed(`${zone.name} was not resumed: ${refused} Reload and check it before trying again.`);
      return;
    }
    offerUndo({
      message: `${zone.name} resumed. Written and read back ${clock(Date.now(), timeZone)}.`,
      undo: async () => {
        setBusy(true);
        const back = await write(false).finally(() => setBusy(false));
        if (back) throw new Error(`${zone.name} was not paused again: ${back}`);
        toast(`${zone.name} paused again. Written and read back ${clock(Date.now(), timeZone)}.`);
      },
    });
  };
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    // A modified click opens the zone in a new tab from its href.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    open();
  };
  const ecText = (value: number | null) => (value === null ? "—" : number(value, 1));
  return (
    <article
      className="today-zone"
      data-zone={zone.id}
      data-attention={level ?? (troubled ? "warning" : undefined)}
      data-mode={z.mode}
      aria-labelledby={`today-zone-${zone.id}`}
    >
      <ZoneSlab
        vwc={zone.vwc.value}
        peak={z.peak}
        rewater={z.rewater}
        target={z.target}
        ec={zone.ec.value}
        ecBand={row.gauges[2].band}
        level={level}
        label=""
        sensors={row.sensors.map((s) => ({ health: s.health, label: s.short }))}
      />
      <div className="today-zone-main">
        <h2 id={`today-zone-${zone.id}`}>
          <a href={zoneHref(window.location.search, roomId, zone.id)} className="today-zone-link" onClick={follow}>
            {zone.name}
            {zone.cultivar && <span className="zone-cultivar">{zone.cultivar}</span>}
            <ArrowRight size={16} aria-hidden="true" className="today-zone-go" />
          </a>
        </h2>
        <p className="today-zone-chips">
          {phase && (
            <span className="today-phase" data-phase={phase}>
              {phase} {PHASE_NAMES[phase]}
            </span>
          )}
          <span className="today-mode" data-mode={z.mode}>
            {z.mode === "paused" ? <Pause size={11} aria-hidden="true" /> : <i aria-hidden="true" />}
            {ZONE_MODE[z.mode]}
          </span>
        </p>
        <p className="today-water-label">Water per plant vs room median</p>
        <DrinkBar
          ml={row.drink?.ml ?? null}
          median={row.drink?.median ?? null}
          max={maxMl}
          text={
            <>
              <strong>{z.mlPerPlant === null ? "—" : perPlant(z.mlPerPlant)}</strong>
              {z.waterL !== null && <span> · {formatVolume(z.waterL, 1)}</span>}
              {shots !== null && (
                <span>
                  {" · "}
                  {zone.lastIrrigation.timestamp && shots > 0 ? (
                    // The count carries the last shot's time, machine-readable and on hover.
                    <time
                      dateTime={zone.lastIrrigation.timestamp}
                      data-last-irrigation={zone.id}
                      title={`Last shot ${clock(Date.parse(zone.lastIrrigation.timestamp), timeZone)}`}
                    >
                      {shots} shot{shots === 1 ? "" : "s"}
                    </time>
                  ) : shots === 0 ? (
                    "no shots"
                  ) : (
                    `${shots} shot${shots === 1 ? "" : "s"}`
                  )}
                </span>
              )}
            </>
          }
        />
        {row.drink && (
          <p className="today-drink-delta" data-today-delta>
            {drinkDelta(row.drink)}
          </p>
        )}
      </div>
      <div className="today-zone-gauges" role="group" aria-label={`${zone.name} readings`}>
        <RoomGauge model={row.gauges[0]} value={zone.vwc.value === null ? "—" : `${number(zone.vwc.value, 1)}%`} />
        <RoomGauge
          model={row.gauges[1]}
          value={z.drybackPoints === null ? "—" : `${number(z.drybackPoints, 1)} pt`}
        />
        <RoomGauge model={row.gauges[2]} value={ecText(zone.ec.value)} />
        {row.paused && zone.enabledEntity && (
          <div className="today-paused" data-today-paused>
            <p>{pausedText(row.paused, timeZone, now)}</p>
            <Button
              variant="outline"
              size="sm"
              disabled={busy || controller.connection === "offline"}
              onClick={() => void resume()}
            >
              Resume {name}
            </Button>
            {failed && (
              <p className="today-paused-failed" role="alert">
                {failed}
              </p>
            )}
          </div>
        )}
      </div>
      <div className="today-sensors">
        <h3>Sensors</h3>
        {row.sensors.length ? (
          <ul>
            {row.sensors.map((s) => (
              <li key={s.key} data-health={s.health} data-sensor={s.short}>
                <span className="today-sensor-name">
                  <i aria-hidden="true" />
                  {s.short}
                </span>
                <span className="today-sensor-reading">
                  {s.silent
                    ? s.silent.since
                    : s.health === "ok" || s.health === "not-counted"
                      ? [
                          s.vwc?.value != null ? `${number(s.vwc.value, 1)}%` : null,
                          s.ec?.value != null ? `EC ${ecText(s.ec.value)}` : null,
                        ]
                          .filter(Boolean)
                          .join(" · ") || "—"
                      : s.text}
                </span>
                {s.silent && (
                  <>
                    <p className="today-sensor-note">{s.silent.text}</p>
                    <button
                      type="button"
                      className="inline-action today-sensor-check"
                      onClick={() => navigate("equipment/probes")}
                    >
                      Check {s.short.toLowerCase()} probe <ArrowRight size={13} aria-hidden="true" />
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No sensors mapped</p>
        )}
      </div>
      {flags.length > 0 && (
        <div className="today-zone-flags">
          {flags.map((flag) => (
            <p key={flag.key} className="today-flag" data-level={flag.level} data-today-problem>
              <TriangleAlert size={15} aria-hidden="true" />
              <span>{flag.text}</span>
            </p>
          ))}
        </div>
      )}
    </article>
  );
}

/** Settings › Display › Tank readout: the feed tank's level, EC and pH as one grey fact of the
 * room's line, also while all is well (a value out of range still gets the tank line below). Null
 * when the room has none of them mapped and reading. */
function tankReadout(controller: Controller): string | null {
  const tank = tankTelemetry(controller.states, controller.room.room);
  const parts = [
    tank.level.value !== null && `${number(tank.level.value, 0)}%`,
    tank.ec.value !== null && `Feed EC ${number(tank.ec.value, 2)} mS/cm`,
    tank.ph.value !== null && `pH ${number(tank.ph.value, 1)}`,
  ].filter(Boolean);
  return parts.length ? `Tank ${parts.join(" · ")}` : null;
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
  const readout = room.display.options.today_tank_readout ? tankReadout(controller) : null;
  if (!problems.length && !readout) return null;
  return (
    <p className="today-tank" role="status" data-today-tank>
      {problems.length > 0 && <TriangleAlert size={16} aria-hidden="true" />}
      <span>{problems.length ? problems.join(" · ") : readout}</span>
      <button type="button" className="inline-action" onClick={() => navigate("equipment/stock")}>
        Equipment <ArrowRight size={14} aria-hidden="true" />
      </button>
    </p>
  );
}
