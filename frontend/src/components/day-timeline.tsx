import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { dailyLimit, Empty, number, time as clock } from "@/components/dashboard";
import { ageText, ageTone, readHeartbeat } from "@/lib/controller-health";
import {
  athenaDryback,
  bandStatus,
  CHART_LAYERS,
  dayScales,
  hourTicks,
  overnightDryback,
  parseChartPrefs,
  phaseColumns,
  placeBadges,
  placeMarkers,
  rangeText,
  runoffBand,
  smoothPath,
  steeringOf,
  valueAtTime,
  type Axis,
  type ChartLayer,
  type ChartPrefs,
  type Column,
  type Compare,
  type Dryback,
  type Readout,
  type Steering,
} from "@/lib/day-chart";
import {
  alignBands,
  appendLive,
  duration,
  earlierDays,
  earlierEntities,
  earlierTraces,
  growDay,
  joinRows,
  nextShot,
  NOT_REPORTING,
  phaseAt,
  phaseBands,
  readings,
  setpointChanges,
  setpointSteps,
  timelineEntities,
  typicalDay,
  unprojected,
  valveShots,
  zoneBlocks,
  type Block,
  type DayTrace,
  type GrowDay,
  type Level,
  type NextShot,
  type PhaseBand,
  type Reading,
  type SetpointChange,
  type Shot,
  type TargetKey,
  type TimelineRows,
  type TypicalPoint,
} from "@/lib/day-timeline";
import { budgetShare, DRYBACK_WINDOW_H, drybackTrend } from "@/lib/dryback";
import { jevAnswer, jevResult, readJev, type JevEntry } from "@/lib/jev";
import { descriptor, numeric } from "@/lib/model";
import {
  buildPlanningCurve,
  dryRates,
  projectFrom,
  smoothRecorded,
  type PlanningPhaseId,
} from "@/lib/planning-curve";
import { buildSetpointPreview } from "@/lib/setpoint-preview";
import { waitingText } from "@/lib/waiting-for";
import type { Controller, Setting, Zone } from "@/lib/types";
import { errorText } from "@/lib/utils";
import { dailyWater, estimateRuntime, flowInputs, waterParameters } from "@/lib/water-delivery";
import { plantAmount, useWaterView, zonePlants } from "@/lib/water-view";
import "./day-timeline.css";

/** Each phase as the zone views name it, and as its chart column says it where there is room. */
const PHASES: Record<string, { name: string; short: string; what: string }> = {
  P0: { name: "Morning dryback", short: "Dryback", what: "VWC falls after lights-on" },
  P1: { name: "Ramp-up", short: "Ramp", what: "the first shots after lights-on" },
  P2: { name: "Maintenance", short: "Maintenance", what: "shots through the lights-on hours" },
  P3: { name: "Overnight dryback", short: "Night", what: "dries back until lights-on" },
};
const HELD: Record<Block["kind"], string> = {
  cap: "daily budget spent",
  block: "blocked",
  hold: "held",
};
const NO_ESTIMATE: Partial<Record<NextShot["basis"], string>> = {
  late: "no shot expected before lights-off at the current dry-down",
  settling: "VWC is still settling after the last shot",
  "no-dry-down": "VWC is not falling measurably",
  "no-reading": "no live VWC reading",
  unknown: "not enough to go on",
};
const LAYERS_KEY = "crop-steering-timeline-layers";
/** The chart's choices remembered in this browser: what today is compared with, the layers
 * switched off, and where its readings show. */
function storedChart(): ChartPrefs {
  try {
    return parseChartPrefs(localStorage.getItem(LAYERS_KEY));
  } catch {
    return parseChartPrefs(null); // no storage: the defaults
  }
}
/** Remembers one of the chart's choices, keeping the others. */
function rememberChart(choice: Partial<ChartPrefs>) {
  try {
    localStorage.setItem(LAYERS_KEY, JSON.stringify({ ...storedChart(), ...choice }));
  } catch {
    /* The choice still applies on this page. */
  }
}
interface Change extends SetpointChange {
  label: string;
  unit: string;
  zoneId?: number;
}
interface Projection {
  points: (Reading & { phase: string })[];
  shots: { time: number; phase: string; size: number | null; emergency: boolean }[];
}
/** A setpoint as the controller resolves it, over one column of the day. */
type Steps = (key: TargetKey, span: { start: number; end: number }) => Level[];
interface Lane {
  zone: Zone;
  bands: PhaseBand[];
  columns: Column[];
  shots: Shot[];
  blocks: Block[];
  points: Reading[];
  /** Today's pore EC, in ten-minute medians. */
  ec: Reading[];
  changes: Change[];
  /** The room's own setpoint changes today, listed with the zone's events. */
  roomChanges: Change[];
  phase: string | null;
  next: NextShot;
  /** Why this zone is not being watered at all, if it is not. */
  stopped: string | null;
  litres: (seconds: number) => number | null;
  steps: Steps;
  projection: Projection | null;
  yesterday: DayTrace | null;
  past: DayTrace[];
  typical: TypicalPoint[];
  steering: Steering | null;
  /** The pore EC band the stage calls for, else the zone's EC target ±10 % (the steer's own band). */
  ecBand: { band: [number, number]; source: string } | null;
  dryback: { night: "tonight" | "last night"; value: Dryback } | null;
  jev: JevEntry[];
  /** The room publishes Jev's log: the chart keeps a lane for its decisions. */
  jevOn: boolean;
  plants: number | null;
  /** Why the rest of the zone's day is not projected, or what holds it back: for the details. */
  status: string | null;
  setupNote: string | null;
  rescue: number | null;
}
/** Earlier grow-days as loaded: per zone, each day's trace, yesterday first (null where there is
 * nothing to draw), and the room's setup revision as each day began. */
interface Earlier {
  key: string;
  traces: Map<number, (DayTrace | null)[]>;
  setup: (number | null)[];
  error: string;
}
/** Past grow-days do not change, so a zone's week is loaded once per grow-day and kept while the
 * page is open. */
const earlierLoads = new Map<string, Promise<TimelineRows>>();
/** Runs `tasks` two at a time; no more start once one has failed. */
export async function inPairs<T>(tasks: (() => Promise<T>)[]): Promise<T[]> {
  const results: T[] = [];
  let next = 0;
  const worker = async () => {
    while (next < tasks.length) {
      const index = next++;
      try {
        results[index] = await tasks[index]();
      } catch (error) {
        next = tasks.length;
        throw error;
      }
    }
  };
  await Promise.all([worker(), worker()]);
  return results;
}
/** The seven grow-days before today for one zone: one request per day, over the transport and within
 * the room that today's use, cut where each day's lights actually came on. Null while loading. */
function useEarlierDays(
  controller: Controller,
  zoneId: number,
  day: GrowDay | null,
  ready: boolean,
) {
  const { room, states } = controller;
  const ids = earlierEntities(room, states, zoneId);
  const hours = {
    on: numeric(states[`number.crop_steering_${room.room.prefix}lights_on_hour`]),
    off: numeric(states[`number.crop_steering_${room.room.prefix}lights_off_hour`]),
  };
  const key =
    day && ids.entityIds.length
      ? [controller.demo, room.room.id, day.start, hours.on, hours.off, ...ids.entityIds, "|"]
          .concat(ids.attributeIds)
          .join(" ")
      : "";
  const [earlier, setEarlier] = useState<Earlier | null>(null);
  const [attempt, setAttempt] = useState(0);
  const latest = useRef({ room, ids, day, hours });
  latest.current = { room, ids, day, hours };
  const load = controller.timeline;
  useEffect(() => {
    const { room, ids, day, hours } = latest.current;
    if (!key || !ready || !day) return;
    let current = true,
      retry: number | undefined;
    let pending = earlierLoads.get(key);
    if (!pending) {
      const windows = earlierDays(day, 7, () => hours);
      pending = inPairs(
        windows.map((window) => () => load({ ...ids, start: window.start, end: window.end })),
      ).then(joinRows);
      // A page left open for days keeps only its latest few.
      if (earlierLoads.size >= 8) earlierLoads.delete(earlierLoads.keys().next().value!);
      earlierLoads.set(key, pending);
      pending.catch(() => earlierLoads.delete(key));
    }
    pending.then(
      (rows) => {
        if (current)
          setEarlier({
            key,
            ...earlierTraces(rows, room, day, hours, ids.attributeIds[0]),
            error: "",
          });
      },
      (reason) => {
        if (!current) return;
        setEarlier({ key, traces: new Map(), setup: [], error: errorText(reason) });
        // A failed load is not kept: try again in a minute.
        retry = window.setTimeout(() => setAttempt((value) => value + 1), 60_000);
      },
    );
    return () => {
      current = false;
      window.clearTimeout(retry);
    };
  }, [key, ready, load, attempt]);
  return earlier?.key === key ? earlier : null;
}

/** One zone's grow-day in the language of Athena's irrigation phase reference chart: today in
 * numbers, then what the zone did today (its phases, shots and pore EC), where it is now against
 * today's stage, and what comes next. Today is downloaded once when the page opens and live updates
 * extend it; the earlier days (yesterday, the typical day, last night's dryback) are downloaded once. */
export function ZoneDay({ controller, zone }: { controller: Controller; zone: Zone }) {
  const [, tick] = useState(0);
  useEffect(() => {
    // The clock moves between live updates, and a quiet controller sends none.
    const timer = window.setInterval(() => tick((value) => value + 1), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const [compare, setCompare] = useState(() => storedChart().compare);
  const choose = (next: Compare) => {
    setCompare(next);
    rememberChart({ compare: next });
  };
  const { room, states } = controller;
  const now = Date.now();
  const prefix = room.room.prefix;
  const day = growDay(
    numeric(states[`number.crop_steering_${prefix}lights_on_hour`]),
    numeric(states[`number.crop_steering_${prefix}lights_off_hour`]),
    now,
  );
  const entities = timelineEntities(room, states, zone.id);
  const key = day
    ? [room.room.id, zone.id, day.start, ...entities.entityIds, "|", ...entities.attributeIds].join(
        " ",
      )
    : "";
  const ready = controller.connection === "live" || controller.connection === "demo";
  const demo = controller.demo;
  const [data, setData] = useState<{ key: string; rows: TimelineRows } | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const latest = useRef({ states, entities, day });
  latest.current = { states, entities, day };
  const load = controller.timeline;
  const earlier = useEarlierDays(controller, zone.id, day, ready);
  useEffect(() => {
    const { entities: ids, day: today } = latest.current;
    if (!key || !ready || !today || !ids.entityIds.length) return;
    let current = true;
    setError("");
    const request = { ...ids, start: today.start, end: Date.now() };
    load(request).then(
      (rows) => {
        if (current)
          setData({ key, rows: demo ? rows : appendLive(rows, latest.current.states, request) });
      },
      (reason) => {
        if (current) setError(errorText(reason));
      },
    );
    return () => {
      current = false;
    };
  }, [key, ready, retry, load, demo]);
  useEffect(() => {
    // The demo's states are one fixed moment, not a clock: its day is generated whole.
    if (demo) return;
    setData((held) => {
      if (!held || held.key !== key) return held;
      const rows = appendLive(held.rows, states, latest.current.entities);
      return rows === held.rows ? held : { key, rows };
    });
  }, [states, key, demo]);
  const rows = data?.key === key ? data.rows : null;
  const newest = rows
    ? Math.max(...Object.values(rows).map((list) => list.at(-1)?.time ?? -Infinity))
    : -Infinity;
  const age = Number.isFinite(newest) ? now - newest : null;
  const lane =
    rows && day ? buildLane(controller, zone, entities, day, rows, now, earlier, compare) : null;
  const stage = readJev(states, prefix).room?.stage ?? null;
  const athena = athenaDryback(stage?.name);
  return (
    <div className="day-timeline zone-day" data-day-timeline data-zone={zone.id}>
      <ZoneNumbers controller={controller} zone={zone} lane={lane} day={day} athena={athena} />
      <section className="panel zone-day-chart" aria-labelledby={`zone-day-${zone.id}`}>
        <div className="panel-heading">
          <h2 id={`zone-day-${zone.id}`}>Today</h2>
          {rows && (
            <div className="timeline-heading-side">
              <label htmlFor="day-timeline-compare" className="timeline-compare">
                Compare with
              </label>
              <select
                id="day-timeline-compare"
                value={compare}
                onChange={(event) => choose(event.target.value as Compare)}
              >
                <option value="yesterday">Yesterday</option>
                <option value="typical">Typical (median of 7 days)</option>
                <option value="none">None</option>
              </select>
              <span className="timeline-age" data-age={ageTone(age)}>
                {controller.demo ? "Demo data · " : ""}
                {age === null ? "Nothing recorded yet" : `Newest reading ${ageText(age)} old`}
              </span>
            </div>
          )}
        </div>
        {!ready && !rows ? (
          <div className="chart-placeholder" role="status">
            <LoaderCircle className="spin" />
            Waiting for Home Assistant…
          </div>
        ) : !day ? (
          <Empty
            title="No lights schedule"
            detail="Set this room’s lights-on and lights-off hours to draw its grow day."
          />
        ) : error ? (
          <Empty
            title="The grow day could not load"
            detail={error}
            action={
              <Button variant="outline" onClick={() => setRetry((value) => value + 1)}>
                Retry
              </Button>
            }
          />
        ) : !lane ? (
          <div className="chart-placeholder" role="status">
            <LoaderCircle className="spin" />
            Loading today’s recorded history…
          </div>
        ) : (
          <DayChart lane={lane} day={day} now={now} compare={compare} />
        )}
      </section>
    </div>
  );
}

/** Today's lane for one zone: its phases, shots, holds, readings and targets, what is expected for
 * the rest of the day, and what it is compared with. */
function buildLane(
  controller: Controller,
  zone: Zone,
  entities: ReturnType<typeof timelineEntities>,
  day: GrowDay,
  rows: TimelineRows,
  now: number,
  earlier: Earlier | null,
  compare: Compare,
): Lane {
  const { room, states } = controller;
  const root = `crop_steering_${room.room.prefix}`;
  const jev = readJev(states, room.room.prefix);
  const stage = jev.room?.stage ?? null;
  const decisions = rows[entities.attributeIds[0]] ?? [];
  const settings = new Map(room.settings.map((setting) => [setting.entityId, setting]));
  const changes = setpointChanges(rows, [...settings.keys()], day.start, now).map(
    (change): Change => {
      const setting = settings.get(change.entityId) as Setting;
      return { ...change, label: setting.label, unit: setting.unit, zoneId: setting.zoneId };
    },
  );
  const settingId = (key: string) => {
    // Like the controller: the zone's own setpoint when it has one, else the room's.
    const own = `number.${root}zone_${zone.id}_${key}`;
    return states[own] ? own : `number.${root}${key}`;
  };
  const read = (key: string) => numeric(states[settingId(key)]);
  const hourOf = (time: number) => (time - day.start) / 3_600_000;
  const length = hourOf(day.end),
    photoperiod = hourOf(day.lightsOff);
  const beat = readHeartbeat(states[`sensor.${root}ai_heartbeat`], now);
  const revision = descriptor(states, room.room)?.attributes.setup_revision;
  const ids = entities.zones.find((item) => item.id === zone.id);
  const shots = valveShots(ids?.valve ? rows[ids.valve] : [], decisions, zone.id, day.start, now);
  const bands = alignBands(phaseBands(ids && rows[ids.phase], day.start, now), shots);
  const blocks = zoneBlocks(decisions, zone.id, day.start, now);
  const points = ids?.vwc ? readings(rows[ids.vwc], day.start, now) : [];
  const ec = smoothRecorded(ids?.ec ? readings(rows[ids.ec], day.start, now) : []);
  const water = waterParameters(controller, zone.id);
  // The phase now is the band that reaches now: none while the sensor is unreadable.
  const last = bands.at(-1);
  const phase = last && last.end >= now ? last.phase : null;
  const since = phase ? last!.start : null;
  const planned = room.strategy.engaged;
  // The zone's target (model.ts) is what the controller compares with in its phase, the plan's
  // while one runs; a plan's timing is its own, so P0 and P1 are not estimated under one.
  const phaseTarget = (key: string) => (zone.phase === phase ? zone.target.value : read(key));
  const target = phase === "P2" ? phaseTarget("p2_vwc_threshold") : null;
  const stopped = !room.roomActive
    ? "the room is off"
    : zone.stale
      ? NOT_REPORTING
      : room.engine.enabled === false
        ? "watering is switched off"
        : zone.enabled === false
          ? "zone scheduling is paused"
          : null;
  const ramp = phase === "P1" ? phaseTarget("p1_target_vwc") : null;
  const ceiling = ramp === null ? null : Math.min(ramp, read("field_capacity") ?? Infinity);
  const held = blocks.at(-1)?.open ? blocks.at(-1)! : null;
  const p1Shots = shots.filter(
    (shot) => (shot.phase ?? phaseAt(bands, shot.start)) === "P1",
  ).length;
  const next: NextShot = stopped
    ? { at: null, basis: "unknown" }
    : nextShot(
        {
          phase,
          since,
          held,
          lastShot: shots.at(-1) ?? null,
          points,
          vwc: zone.vwc.value,
          threshold: target,
          ceiling,
          interval: planned ? null : water.p1_time_between_shots,
          maxWait: planned ? null : read("p0_maximum_wait_time"),
        },
        day,
        now,
      );
  // Targets resolve as the controller's do: the zone's setpoint, else the room's, else the plan's
  // snapshot while one is armed. The dryback target is the steering mode's.
  const preview = buildSetpointPreview(room, states, zone.id, {}).saved;
  const parameters = preview.parameters;
  const steps = setpointSteps(
    rows,
    parameters,
    (key) =>
      key !== "dryback_target"
        ? settingId(key)
        : preview.mode && settingId(`${preview.mode.toLowerCase()}_dryback_target`),
    planned,
  );
  const traces = earlier?.traces.get(zone.id) ?? [];
  // Yesterday is drawn whatever happened; a day the room spent partly switched off is kept out
  // of the typical day and the dry-down rates.
  const yesterday = traces[0] ?? null;
  const past = traces.filter((trace): trace is DayTrace => trace !== null && !trace.roomOff);
  const today = smoothRecorded(points).map((point) => ({ ...point, hour: hourOf(point.time) }));
  // The rest of the day from the latest reading, on the zone's own dry-down (today and the three
  // grow-days before), by the rules the plan graph's projected day runs. Nothing is claimed for
  // a zone the controller is not watering.
  const newest = points.at(-1);
  const p0 = bands.find((band) => band.phase === "P0");
  const peak = p0 && points.filter((point) => point.time >= p0.start).map((point) => point.value);
  const projected =
    stopped || !phase || !newest || zone.vwc.value === null
      ? null
      : projectFrom(
          buildPlanningCurve(parameters, 0, photoperiod),
          parameters,
          {
            hour: hourOf(newest.time),
            phase: phase as PlanningPhaseId,
            since: hourOf(since!),
            value: newest.value,
            p1Shots,
            lastShot: shots.length ? hourOf(shots.at(-1)!.end) : null,
            peak: phase === "P0" && peak?.length ? Math.max(...peak) : null,
          },
          {
            rates: dryRates([today, ...past.slice(0, 3).map((trace) => trace.points)], photoperiod),
            retention: zone.auto?.gain ?? null,
            end: length,
          },
        );
  const time = (hour: number) => day.start + hour * 3_600_000;
  const projection = projected && {
    points: projected.points.map((point) => ({ ...point, time: time(point.hour) })),
    shots: projected.shots.map((shot) => ({
      time: time(shot.hour),
      phase: shot.phase,
      size: shot.size,
      emergency: !!shot.emergency,
    })),
  };
  // What is expected for the rest of the day: the projection's phases; without one, only what is
  // certain (P2 lasts until lights-off, and lights-off moves every zone to P3).
  const ahead: PhaseBand[] = [];
  for (const point of projection?.points ?? []) {
    const at = Math.max(point.time, now),
      band = ahead.at(-1);
    if (band?.phase === point.phase) band.end = at;
    else {
      if (band) band.end = at;
      ahead.push({ phase: point.phase, start: at, end: at });
    }
  }
  if (!projection) {
    if (phase === "P2" && now < day.lightsOff)
      ahead.push({ phase: "P2", start: now, end: day.lightsOff });
    ahead.push({ phase: "P3", start: Math.max(now, day.lightsOff), end: day.end });
  } else if (ahead.length) ahead.at(-1)!.end = Math.max(ahead.at(-1)!.end, day.end);
  const columns = phaseColumns(bands, ahead, now, 30 * 60_000);
  const compared =
    compare === "typical"
      ? past.length >= 3
        ? past
        : []
      : compare === "yesterday" && yesterday
        ? [yesterday]
        : [];
  const moved = earlier?.setup.filter(
    (value, index) =>
      typeof revision === "number" &&
      value !== null &&
      value !== revision &&
      traces[index] &&
      compared.includes(traces[index]!),
  ).length;
  const choice = states[`select.${root}zone_${zone.id}_steering_mode`]?.state;
  const steering = steeringOf(choice, stage?.steering);
  const ecTarget = zone.ecTarget.value;
  // Last night's dryback runs from yesterday's evening into today; tonight's from today's.
  const tonight = now >= day.lightsOff;
  const night = tonight
    ? overnightDryback(points, day.lightsOff, day.end, now)
    : yesterday && overnightDryback(yesterday.points, yesterday.day.lightsOff, day.start, now);
  return {
    zone,
    bands,
    columns,
    shots,
    blocks,
    points,
    ec,
    changes: changes.filter((change) => change.zoneId === zone.id),
    roomChanges: changes.filter((change) => change.zoneId === undefined),
    phase,
    next,
    stopped,
    litres: (seconds) => estimateRuntime(flowInputs(water), seconds).requested?.zoneL ?? null,
    steps,
    projection,
    yesterday,
    past,
    typical:
      compare === "typical" && past.length >= 3
        ? typicalDay(past.map((trace) => trace.points))
        : [],
    steering,
    ecBand: stage?.poreEc
      ? { band: stage.poreEc, source: `the pore EC band for ${stage.name}` }
      : ecTarget !== null && ecTarget > 0
        ? {
            band: [ecTarget * 0.9, ecTarget * 1.1],
            source: `the zone’s EC target ${number(ecTarget, 2)} ±10 %`,
          }
        : null,
    dryback: night ? { night: tonight ? "tonight" : "last night", value: night } : null,
    jev: (jev.log?.entries ?? []).filter(
      (entry) =>
        entry.kind === "decision" &&
        entry.zone === zone.id &&
        entry.time !== null &&
        entry.time >= day.start &&
        entry.time <= Math.min(now, day.end),
    ),
    jevOn: !!jev.log,
    plants: zonePlants(controller, zone.id),
    status:
      unprojected(stopped, beat.at, now) ??
      (next.basis === "held" && held ? `${HELD[held.kind]}: ${held.text}` : null),
    setupNote: !moved
      ? null
      : compare === "yesterday"
        ? "Rooms & setup saved since yesterday: its probe may have differed"
        : `${moved} of ${compared.length} days before the last Rooms & setup save`,
    rescue: read("p3_emergency_vwc_threshold"),
  };
}

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** Today in numbers: moisture, pore EC against the stage's band, water today and each plant's
 * share, shots and the last one, the overnight dryback against Athena's target, and what comes
 * next. Readings are live; the lane adds what only today's record knows. */
function ZoneNumbers({
  controller,
  zone,
  lane,
  day,
  athena,
}: {
  controller: Controller;
  zone: Zone;
  lane: Lane | null;
  day: GrowDay | null;
  athena: [number, number] | null;
}) {
  const stage = readJev(controller.states, controller.room.room.prefix).room?.stage ?? null;
  const band = lane?.ecBand?.band ?? stage?.poreEc ?? null;
  const ec = bandStatus(zone.ec.value, band);
  const water = dailyWater(zone, zonePlants(controller, zone.id));
  const each = water.mlPerPlant === null ? null : plantAmount(water.mlPerPlant);
  const { view } = useWaterView();
  // Routine shots stop at the zone's daily limit: amber from 80 %.
  const limit = dailyLimit(controller, zone.id);
  const share = budgetShare(water.zoneL, limit);
  const lastShot = zone.lastIrrigation.timestamp ?? null;
  const next = lane && day ? nextWords(lane, day) : null;
  const dryback = lane?.dryback;
  // How fast it dries since the last shot settled, from today's readings.
  const rate = lane
    ? drybackTrend(
        lane.points.map((point) => ({
          time: new Date(point.time).toISOString(),
          value: point.value,
        })),
        lastShot,
        zone.vwc.value,
        Date.now(),
      ).rate
    : null;
  return (
    <div className="zone-numbers-wrap">
      <dl className="zone-numbers" aria-label={`${zone.name} today in numbers`}>
        <div>
          <dt>Moisture</dt>
          <dd>
            {number(zone.vwc.value)}
            {zone.vwc.value !== null && <span className="unit">%</span>}
          </dd>
          {rate !== null && (
            <dd
              className="zone-sub"
              title={`VWC points lost per hour since the last shot settled, over up to the last ${DRYBACK_WINDOW_H} hours`}
            >
              {Math.abs(rate) < 0.05
                ? "steady"
                : `${rate > 0 ? "drying" : "wetting"} ${number(Math.abs(rate), Math.abs(rate) < 1 ? 2 : 1)} pts/h`}
            </dd>
          )}
        </div>
        <div data-status={ec ?? undefined}>
          <dt>Pore EC</dt>
          <dd>{number(zone.ec.value, 2)}</dd>
          {band && (
            <dd
              className="zone-sub"
              title={lane?.ecBand ? `Against ${lane.ecBand.source}` : undefined}
            >
              {ec === "in" ? "in" : (ec ?? "band")} {rangeText(band)}
            </dd>
          )}
        </div>
        <div data-status={share !== null && share >= 80 ? "above" : undefined}>
          <dt>Water today</dt>
          {/* The room's choice (Settings › Appearance) leads; the other reading sits under it. */}
          {view === "plant" && each ? (
            <>
              <dd>
                {number(each.value, each.digits)}
                <span className="unit"> {each.unit}/plant</span>
              </dd>
              <dd className="zone-sub">{number(water.zoneL)} L in the zone</dd>
            </>
          ) : (
            <>
              <dd>
                {number(water.zoneL)}
                {water.zoneL !== null && <span className="unit"> L</span>}
              </dd>
              {each && (
                <dd className="zone-sub">
                  {number(each.value, each.digits)} {each.unit}/plant
                </dd>
              )}
            </>
          )}
          {share !== null && (
            <dd
              className="zone-sub"
              title="Routine shots stop at the zone's daily water limit; ramp, rescue and watchdog shots and high-EC flushes can go past it"
            >
              {number(share, 0)}% of the {number(limit)} L limit
            </dd>
          )}
        </div>
        <div>
          <dt>Shots</dt>
          <dd>{zone.shots.value === null ? "—" : number(zone.shots.value, 0)}</dd>
          {lastShot !== null && <dd className="zone-sub">last {clock(lastShot)}</dd>}
        </div>
        <div
          title={
            dryback
              ? `From the evening peak of ${number(dryback.value.peak)}% (the highest reading in the 2 h before lights-off) to the low of ${number(dryback.value.low)}%: ${number(dryback.value.drop)} points. Athena’s dryback targets are this share of the peak.`
              : "Needs readings on both sides of lights-off."
          }
        >
          <dt>{dryback?.night === "tonight" ? "Dryback tonight" : "Last night’s dryback"}</dt>
          <dd>
            {dryback ? number(dryback.value.percent) : "—"}
            {dryback && <span className="unit">% of peak</span>}
          </dd>
          {athena && (
            <dd
              className="zone-sub"
              title="Athena’s relative dryback target for this stage; the zone’s own P3 target is under Targets"
            >
              Athena {rangeText(athena, 0)}%
            </dd>
          )}
        </div>
      </dl>
      {next && (
        <p className="zone-next" title={next.detail} data-tone={next.tone}>
          <strong>Next:</strong> {next.text}
        </p>
      )}
    </div>
  );
}

/** The chart at the width it has, with its key and today's events. */
function DayChart({
  lane,
  day,
  now,
  compare,
}: {
  lane: Lane;
  day: GrowDay;
  now: number;
  compare: Compare;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [tip, setTip] = useState<Tip | null>(null);
  // The layers switched off from the key, and where readings show: remembered in this browser.
  const [hiddenLayers, setHidden] = useState(() => storedChart().hidden);
  const [readout, setReadout] = useState(() => storedChart().readout);
  const hidden = new Set(hiddenLayers);
  const toggle = (layer: ChartLayer) => {
    const next = CHART_LAYERS.filter((item) => (item === layer) !== hidden.has(item));
    setHidden(next);
    rememberChart({ hidden: next });
  };
  const place = (next: Readout) => {
    setReadout(next);
    rememberChart({ readout: next });
  };
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!tip?.pinned) return;
    // A tapped detail stays until the next tap outside this chart.
    const away = (event: globalThis.PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setTip(null);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [tip?.pinned]);
  const events = [
    ...laneEvents(lane, day),
    ...lane.roomChanges.map((change) => ({ time: change.time, text: changeText(change) })),
  ].sort((a, b) => a.time - b.time);
  const typicalDays = lane.past.length;
  return (
    <div className="timeline-body">
      <div className="grow-chart" ref={box}>
        {width > 0 && (
          <Chart
            lane={lane}
            day={day}
            now={now}
            width={width}
            compare={compare}
            hidden={hidden}
            cursor={tip?.x ?? null}
            onTip={setTip}
          />
        )}
        {readout === "over" && (
          <div
            className="grow-tip"
            role="status"
            aria-live="polite"
            hidden={!tip}
            data-side={tip && tip.x > width / 2 ? "left" : "right"}
            style={
              tip
                ? tip.x > width / 2
                  ? { right: Math.max(0, width - tip.x + 10), top: Math.max(0, tip.y - 8) }
                  : { left: tip.x + 10, top: Math.max(0, tip.y - 8) }
                : undefined
            }
          >
            {tip?.text}
          </div>
        )}
      </div>
      {readout === "below" && <ReadoutLine tip={tip} />}
      <div className="grow-foot">
        <Legend
          steering={lane.steering}
          jev={lane.jevOn}
          compare={
            compare === "yesterday"
              ? "Yesterday"
              : compare === "typical"
                ? typicalDays >= 3
                  ? `Typical day (${typicalDays} days)`
                  : "Typical day (too few days)"
                : null
          }
          hidden={hidden}
          onToggle={toggle}
        />
        <label className="grow-readout-choice">
          Readings
          <select value={readout} onChange={(event) => place(event.target.value as Readout)}>
            <option value="below">Under the chart</option>
            <option value="over">On the chart</option>
          </select>
        </label>
        <details className="timeline-events">
          <summary>Today’s events ({events.length})</summary>
          {events.length ? (
            <ol>
              {events.map((event, index) => (
                <li key={index}>{event.text}</li>
              ))}
            </ol>
          ) : (
            <p>Nothing recorded yet today.</p>
          )}
        </details>
      </div>
    </div>
  );
}

/** The chart's key: every entry switches its layer on and off. */
function Legend({
  steering,
  jev,
  compare,
  hidden,
  onToggle,
}: {
  steering: Steering | null;
  jev: boolean;
  compare: string | null;
  hidden: ReadonlySet<ChartLayer>;
  onToggle: (layer: ChartLayer) => void;
}) {
  const kind: Steering = steering ?? "vegetative";
  const entry = (layer: ChartLayer, title: string | undefined, children: ReactNode) => (
    <li>
      <button
        type="button"
        title={title}
        aria-pressed={!hidden.has(layer)}
        data-layer-toggle={layer}
        onClick={() => onToggle(layer)}
      >
        {children}
      </button>
    </li>
  );
  return (
    <ul className="grow-legend" aria-label="Chart key">
      {entry(
        "vwc",
        "Solid: recorded today. Dashed: what is expected for the rest of the day, an estimate.",
        <>
          <i className="key-vwc" aria-hidden="true" />
          VWC
        </>,
      )}
      {entry(
        "ec",
        "Right-hand axis, mS/cm. Green while steering vegetative, purple while generative.",
        <>
          <i className="key-ec" data-steering={kind} aria-hidden="true" />
          Pore EC
        </>,
      )}
      {entry(
        "shots",
        undefined,
        <>
          <i className="key-shot" aria-hidden="true" />
          Shot
          <i className="key-held" aria-hidden="true" />
          held
        </>,
      )}
      {entry(
        "fc",
        "Field capacity, with a thin runoff band: just above it for vegetative steering, just under it for generative.",
        <>
          <i className="key-fc" aria-hidden="true" />
          <i className="key-runoff" data-steering={kind} aria-hidden="true" />
          FC · runoff
        </>,
      )}
      {entry(
        "band",
        "From the maintenance trigger (P2 re-waters under it) up to the peak target, over the ramp and maintenance hours.",
        <>
          <i className="key-band" aria-hidden="true" />
          Maintenance band
        </>,
      )}
      {entry(
        "rescue",
        "Overnight, the controller waters only below this level.",
        <>
          <i className="key-rescue" aria-hidden="true" />
          Rescue floor
        </>,
      )}
      {jev &&
        entry(
          "jev",
          "Filled: code acted on it. Outline: advice, no action, or refused.",
          <>
            <i className="key-jev" aria-hidden="true" />
            Jev decision
          </>,
        )}
      {compare &&
        entry(
          "compare",
          "Drawn on today’s scale: an earlier day beyond it runs off the edge.",
          <>
            <i className="key-compare" aria-hidden="true" />
            {compare}
          </>,
        )}
    </ul>
  );
}

/** The chart's reading under it, so it never covers what it reads: the moment first, then the
 * rest on one line. */
function ReadoutLine({ tip }: { tip: Tip | null }) {
  const lines = tip?.text.split("\n").filter(Boolean) ?? [];
  return (
    <p
      className="grow-readout"
      role="status"
      aria-live="polite"
      data-empty={lines.length ? undefined : true}
    >
      {lines.length ? (
        <>
          <strong>{lines[0]}</strong>
          {lines.length > 1 && ` · ${lines.slice(1).join(" · ")}`}
        </>
      ) : (
        "Point at the chart, or tap it, to read it here."
      )}
    </p>
  );
}

interface Hit {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  /** Lower ranks win: small marks (shots, decisions) first, with a wider touch target. */
  rank: number;
  text: (time: number) => string;
}
interface Tip {
  text: string;
  x: number;
  y: number;
  pinned: boolean;
}

/** The chart: light band, Jev's decisions, phase columns, field capacity with the runoff zone, the
 * maintenance band, the rescue floor, VWC with its shots, and pore EC on the right. */
function Chart({
  lane,
  day,
  now,
  width,
  compare: chosen,
  hidden,
  cursor,
  onTip,
}: {
  lane: Lane;
  day: GrowDay;
  now: number;
  width: number;
  compare: Compare;
  /** Layers switched off from the key: not drawn, not pointed at, not read out. */
  hidden: ReadonlySet<ChartLayer>;
  /** Where the reading is taken, in pixels across the chart: a bar runs up the plot there. */
  cursor: number | null;
  onTip: (tip: Tip | null | ((held: Tip | null) => Tip | null)) => void;
}) {
  const show = (layer: ChartLayer) => !hidden.has(layer);
  const compare: Compare = show("compare") ? chosen : "none";
  const { zone, points, steps } = lane;
  const name = zone.name;
  const narrow = width < 420;
  const jevLane = lane.jevOn;
  // Left: VWC. Right: pore EC. Top: the light band, then Jev's lane. Bottom: phases, then the clock.
  const L = 38,
    R = 34,
    TOP = jevLane ? 27 : 15,
    H = narrow ? 170 : 250;
  const plotW = Math.max(100, width - L - R);
  const bottom = TOP + H;
  const height = bottom + 39;
  const x = (time: number) =>
    L + Math.max(0, Math.min(1, (time - day.start) / (day.end - day.start))) * plotW;
  const timeAt = (px: number) => day.start + ((px - L) / plotW) * (day.end - day.start);
  const hourOf = (time: number) => (time - day.start) / 3_600_000;
  // Earlier days sit on today's axis by hours since their own lights-on.
  const yesterday = compare === "yesterday" ? lane.yesterday : null;
  const before = (yesterday?.points ?? [])
    .filter((point) => point.hour <= hourOf(day.end))
    .map((point) => ({ time: day.start + point.hour * 3_600_000, value: point.value }));
  const typical = compare === "typical" ? lane.typical : [];
  const projection = lane.projection;
  // The references: field capacity all day, the maintenance band over the ramp and maintenance
  // hours, and the rescue floor overnight.
  const fc = steps("field_capacity", day);
  const band = lane.columns
    .filter((column) => column.phase === "P1" || column.phase === "P2")
    .flatMap((column) => bandSegments(steps, column));
  const rescue = lane.columns
    .filter((column) => column.phase === "P3" && column.end - column.start >= 30 * 60_000)
    .flatMap((column) =>
      steps("p3_emergency_vwc_threshold", column).map((level) => ({ ...level, column })),
    );
  // Fitted to today and the zone's own targets: yesterday and the typical day run off the edge
  // rather than widen the scale.
  const { vwc: vwcAxis, ec: ecAxis } = dayScales({
    today: points.map((point) => point.value),
    projection: projection?.points.map((point) => point.value),
    targets: [
      ...fc.map((level) => level.value),
      ...band.flatMap((segment) => [segment.low, segment.high]),
      ...rescue.map((level) => level.value),
    ],
    ec: lane.ec.map((point) => point.value),
    ecBand: lane.ecBand?.band ?? null,
  });
  const scale = (axis: Axis | null) => (value: number) =>
    axis
      ? bottom -
        ((Math.min(axis.max, Math.max(axis.min, value)) - axis.min) / (axis.max - axis.min)) * H
      : bottom;
  const y = scale(vwcAxis),
    yEc = scale(ecAxis);
  // Unclamped, for what the plot's clip cuts at its edge instead of flattening along it.
  const yOpen = (value: number) =>
    vwcAxis ? bottom - ((value - vwcAxis.min) / (vwcAxis.max - vwcAxis.min)) * H : bottom;
  const onAxis = (value: number | null | undefined): value is number =>
    typeof value === "number" && !!vwcAxis && value >= vwcAxis.min && value <= vwcAxis.max;
  const off = x(day.lightsOff),
    nowX = x(now);
  const id = `grow-${zone.id}`;
  // Each shot is a dot on the VWC line where the valve opened, sized by how long it ran.
  const longest = Math.max(1, ...lane.shots.map((shot) => shot.end - shot.start));
  const onLine = (time: number) => {
    const value = valueAtTime(points, time) ?? valueAtTime(points, time, 3 * 3_600_000);
    return value === null ? bottom - 6 : y(value);
  };
  const shotDots = lane.shots.map((shot) => ({
    shot,
    cx: x(shot.start),
    cy: onLine(shot.start),
    r: 2.3 + 1.7 * Math.sqrt((shot.end - shot.start) / longest),
  }));
  const heldRings = lane.blocks.map((block) => ({
    block,
    cx: x(block.start),
    cy: onLine(block.start),
  }));
  const expected = (projection?.shots ?? []).map((shot) => {
    const at = projection!.points.find((point) => point.time >= shot.time);
    return { shot, cx: x(shot.time), cy: at ? y(at.value) : bottom - 6 };
  });
  // Jev's decisions in their own lane above the plot; ones too close to tell apart share a mark.
  const markers = placeMarkers(
    lane.jev.map((entry) => ({ x: x(entry.time!), item: entry })),
    12,
    1,
  );
  const JEV_Y = 17.5;
  const ticks = hourTicks(day.start, day.end, plotW, narrow ? 50 : 58);
  const fcNow = fc.at(-1)?.value ?? null;
  const rescueNow = rescue.at(-1) ?? null;
  // A phase badge under each column, a narrow phase's pushed beside it rather than dropped; its name
  // beside it where there is room.
  const BADGE = 18;
  const centres = placeBadges(
    lane.columns.map((column) => (x(column.start) + x(column.end)) / 2),
    BADGE,
    3,
    L,
    L + plotW,
  );
  const badges = lane.columns.map((column, index) => {
    const word = PHASES[column.phase]?.short ?? "";
    const wordW = word.length * 7;
    const nextLeft = index + 1 < centres.length ? centres[index + 1] - BADGE / 2 : L + plotW;
    let cx = centres[index];
    const room = Math.min(x(column.end), nextLeft) - (cx + BADGE / 2 + 5);
    const labelled = room >= wordW + 4 && x(column.end) - x(column.start) >= BADGE + wordW + 12;
    // A labelled badge and its name sit together in the middle of their column.
    if (labelled) cx = Math.max(x(column.start) + BADGE / 2 + 2, cx - (wordW + 5) / 2);
    return { column, cx, word: labelled ? word : "" };
  });
  // What the pointer is on, in order: the small marks first, then the columns, then the lines.
  // A layer switched off is not there to point at.
  const hits: Hit[] = [
    ...(show("shots") ? shotDots : []).map(({ shot, cx, cy }) => ({
      x0: cx - 6,
      x1: cx + 6,
      y0: cy - 8,
      y1: cy + 8,
      rank: 0,
      text: () => shotText(shot, lane),
    })),
    ...(show("shots") ? heldRings : []).map(({ block, cx, cy }) => ({
      x0: cx - 6,
      x1: cx + 6,
      y0: cy - 8,
      y1: cy + 8,
      rank: 0,
      text: () => blockText(block, lane),
    })),
    ...(show("jev") ? markers : []).map((marker) => ({
      x0: marker.x - 8,
      x1: marker.x + 8,
      y0: JEV_Y - 9,
      y1: JEV_Y + 9,
      rank: 0,
      text: () => marker.items.map((entry) => jevText(entry, lane)).join("\n\n"),
    })),
    ...(show("vwc") ? expected : []).map(({ shot, cx, cy }) => ({
      x0: cx - 5,
      x1: cx + 5,
      y0: cy - 7,
      y1: cy + 7,
      rank: 1,
      text: () =>
        `≈${clock(shot.time)} · ${name} · expected\n${shot.emergency ? "P3 rescue" : shot.phase} shot${shot.size === null ? "" : ` of ${number(shot.size, 2)}% of the substrate`}, an estimate`,
    })),
    ...badges.map(({ column, cx }) => ({
      x0: Math.min(cx - BADGE / 2, x(column.start)),
      x1: Math.max(cx + BADGE / 2, x(column.end)),
      y0: bottom + 2,
      y1: bottom + 24,
      rank: 2,
      text: () => columnText(column, lane, day, now),
    })),
    {
      x0: L,
      x1: L + plotW,
      y0: 0,
      y1: 10,
      rank: 3,
      text: (at) =>
        at < day.lightsOff
          ? `${clock(day.start)}–${clock(day.lightsOff)} · lights on`
          : `${clock(day.lightsOff)}–${clock(day.end)} · lights off`,
    },
    {
      x0: L,
      x1: L + plotW,
      y0: TOP,
      y1: bottom,
      rank: 4,
      text: (at) =>
        readingText(lane, at, now, day.start, before, typical, fc, band, rescue, compare, show),
    },
  ];
  // Where the bar crosses each line that is drawn: the readings it takes.
  const cursorAt = cursor !== null && cursor >= L && cursor <= L + plotW ? timeAt(cursor) : null;
  const cursorDots: { cy: number; series: string }[] = [];
  if (cursorAt !== null) {
    const vwcThen =
      cursorAt <= now
        ? valueAtTime(points, cursorAt)
        : valueAtTime(projection?.points ?? [], cursorAt, 24 * 3_600_000);
    if (show("vwc") && onAxis(vwcThen)) cursorDots.push({ cy: y(vwcThen), series: "vwc" });
    const ecThen = cursorAt <= now ? valueAtTime(lane.ec, cursorAt, 40 * 60_000) : null;
    if (show("ec") && ecAxis && ecThen !== null)
      cursorDots.push({ cy: yEc(ecThen), series: "ec" });
    const beforeThen = before.length ? valueAtTime(before, cursorAt) : null;
    if (onAxis(beforeThen)) cursorDots.push({ cy: y(beforeThen), series: "yesterday" });
  }
  const find = (event: PointerEvent<SVGSVGElement> | MouseEvent<SVGSVGElement>) => {
    const frame = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - frame.left,
      py = event.clientY - frame.top;
    const hit = hits
      .filter((mark) => px >= mark.x0 && px <= mark.x1 && py >= mark.y0 && py <= mark.y1)
      .sort(
        (a, b) =>
          a.rank - b.rank || Math.abs(a.x0 + a.x1 - 2 * px) - Math.abs(b.x0 + b.x1 - 2 * px),
      )[0];
    return hit ? { text: hit.text(timeAt(px)), x: px, y: py } : null;
  };
  const gradient = (at: number) => ((at - L) / plotW) * 100;
  const fade = Math.min(4, (18 / plotW) * 100);
  const flat = (levels: Level[]) =>
    levels
      .filter((level) => onAxis(level.value))
      .map(
        (level) =>
          `M${x(level.start).toFixed(1)} ${y(level.value).toFixed(1)}H${x(level.end).toFixed(1)}`,
      )
      .join("");
  return (
    <svg
      className="grow-svg"
      width={width}
      height={height}
      aria-hidden="true"
      onPointerMove={(event) => {
        if (event.pointerType !== "mouse") return;
        const found = find(event);
        onTip((held) => (held?.pinned ? held : found && { ...found, pinned: false }));
      }}
      onPointerLeave={() => onTip((held) => (held?.pinned ? held : null))}
      onClick={(event) => {
        const found = find(event);
        onTip(found && { ...found, pinned: true });
      }}
    >
      <defs>
        <linearGradient id={`${id}-light`} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" className="light-day" />
          <stop offset={`${Math.max(0, gradient(off) - fade)}%`} className="light-day" />
          <stop offset={`${Math.min(100, gradient(off) + fade)}%`} className="light-night" />
          <stop offset="100%" className="light-night" />
        </linearGradient>
        <clipPath id={`${id}-plot`}>
          <rect x={L} y={TOP} width={plotW} height={H} />
        </clipPath>
      </defs>
      <rect x={L} y={0} width={plotW} height={8} rx={4} fill={`url(#${id}-light)`} />
      <text x={L - 6} y={10} className="axis-title" textAnchor="end">
        VWC
      </text>
      {vwcAxis?.ticks.map((tick) => (
        <g key={tick}>
          <line x1={L} x2={L + plotW} y1={y(tick)} y2={y(tick)} className="grid" />
          <text x={L - 6} y={y(tick) + 4} className="axis-label" textAnchor="end">
            {number(tick, 1)}%
          </text>
        </g>
      ))}
      {show("ec") && ecAxis && lane.ec.length > 0 && (
        <g className="ec-axis" data-steering={lane.steering ?? undefined}>
          <text x={L + plotW + 7} y={10} className="axis-title">
            EC
          </text>
          {lane.ecBand && (
            <rect
              x={L + plotW + 2}
              y={yEc(lane.ecBand.band[1])}
              width={4}
              height={Math.max(2, yEc(lane.ecBand.band[0]) - yEc(lane.ecBand.band[1]))}
              rx={2}
              className="ec-band"
            />
          )}
          {ecAxis.ticks.map((tick) => (
            <text key={tick} x={L + plotW + 9} y={yEc(tick) + 4} className="axis-label">
              {number(tick, 1)}
            </text>
          ))}
        </g>
      )}
      <g clipPath={`url(#${id}-plot)`}>
        {show("fc") && onAxis(fcNow) && lane.steering && (
          <g data-layer="runoff" data-steering={lane.steering}>
            {fc.map((level, index) => {
              const [low, high] = runoffBand(level.value, lane.steering!);
              return (
                <rect
                  key={index}
                  x={x(level.start)}
                  width={x(level.end) - x(level.start)}
                  y={yOpen(high)}
                  height={Math.max(0, yOpen(low) - yOpen(high))}
                  className="runoff-zone"
                />
              );
            })}
          </g>
        )}
        {show("band") && band.length > 0 && (
          <g data-layer="maintenance">
            {band.map((segment, index) => (
              <rect
                key={index}
                x={x(segment.start)}
                width={x(segment.end) - x(segment.start)}
                y={y(segment.high)}
                height={Math.max(1, y(segment.low) - y(segment.high))}
                className="maintenance-band"
              />
            ))}
          </g>
        )}
        {typical.length > 0 && (
          <g data-layer="typical">
            <path
              d={typicalArea(typical, (hour) => x(day.start + hour * 3_600_000), yOpen)}
              className="typical-band"
            />
          </g>
        )}
        {lane.columns.slice(1).map((column, index) => (
          <line
            key={index}
            x1={x(column.start)}
            x2={x(column.start)}
            y1={TOP}
            y2={bottom}
            className="phase-divider"
          />
        ))}
        {show("fc") && onAxis(fcNow) && (
          <path data-layer="fc" d={flat(fc)} className="fc-line" />
        )}
        {show("rescue") && rescue.some((level) => onAxis(level.value)) && (
          <path data-layer="rescue" d={flat(rescue)} className="rescue-line" />
        )}
        {before.length > 0 && (
          <path data-layer="yesterday" d={linePath(before, x, yOpen)} className="yesterday-line" />
        )}
        {show("ec") && lane.ec.length > 1 && ecAxis && (
          <path
            data-layer="ec"
            data-steering={lane.steering ?? undefined}
            d={smoothPath(lane.ec, x, yEc)}
            className="ec-line"
          />
        )}
        {show("vwc") && projection && (
          <path
            data-layer="projected"
            d={projection.points
              .map(
                (point, index) =>
                  `${index ? "L" : "M"}${x(point.time).toFixed(1)} ${y(point.value).toFixed(1)}`,
              )
              .join("")}
            className="projection"
          />
        )}
        {show("vwc") && <path d={linePath(points, x, y)} className="vwc-line" data-layer="vwc" />}
      </g>
      {show("fc") && fcNow !== null && vwcAxis && (
        <text
          x={L + plotW - 4}
          y={
            onAxis(fcNow)
              ? y(fcNow) - 4 < TOP + 10
                ? y(fcNow) + 13
                : y(fcNow) - 4
              : fcNow > vwcAxis.max
                ? TOP + 12
                : bottom - 4
          }
          className="ref-label fc"
          textAnchor="end"
        >
          FC {number(fcNow)}%{onAxis(fcNow) ? "" : fcNow > vwcAxis.max ? " ↑" : " ↓"}
        </text>
      )}
      {show("rescue") && rescueNow && vwcAxis && (
        <text
          x={Math.max(x(rescueNow.column.start) + 4, L + 4)}
          y={onAxis(rescueNow.value) ? y(rescueNow.value) - 4 : bottom - 4}
          className="ref-label rescue"
        >
          Rescue {number(rescueNow.value)}%{onAxis(rescueNow.value) ? "" : " ↓"}
        </text>
      )}
      {!points.length && (
        <text x={L + 8} y={TOP + H / 2} className="axis-label">
          No VWC readings today
        </text>
      )}
      <g data-layer="expected">
        {(show("vwc") ? expected : []).map(({ shot, cx, cy }, index) => (
          <circle
            key={index}
            cx={cx}
            cy={cy}
            r={2.6}
            className={shot.emergency ? "expected-shot emergency" : "expected-shot"}
          />
        ))}
      </g>
      {show("shots") && (
        <g data-layer="shots">
          {shotDots.map(({ cx, cy, r }, index) => (
            <circle key={index} cx={cx} cy={cy} r={r} className="shot-dot" />
          ))}
          {heldRings.map(({ block, cx, cy }, index) => (
            <circle
              key={`h${index}`}
              cx={cx}
              cy={cy}
              r={4}
              className="held-ring"
              data-kind={block.kind}
            />
          ))}
        </g>
      )}
      {cursorAt !== null && (
        <g className="grow-cursor" data-layer="cursor">
          <line x1={cursor!} x2={cursor!} y1={TOP} y2={bottom} className="cursor-bar" />
          {cursorDots.map(({ cy, series }) => (
            <circle
              key={series}
              cx={cursor!}
              cy={cy}
              r={3.5}
              className="cursor-dot"
              data-series={series}
              data-steering={series === "ec" ? (lane.steering ?? undefined) : undefined}
            />
          ))}
        </g>
      )}
      {show("jev") && markers.length > 0 && (
        <g data-layer="jev">
          {markers.map((marker, index) => (
            <path
              key={index}
              d={diamond(marker.x, JEV_Y)}
              className="jev-mark"
              data-acted={marker.items.some((entry) => jevResult(entry).acted) || undefined}
            />
          ))}
        </g>
      )}
      <line x1={nowX} x2={nowX} y1={0} y2={bottom} className="now-line" />
      <path d={`M${nowX - 4} 9L${nowX + 4} 9L${nowX} 14Z`} className="now-mark" />
      {badges.map(({ column, cx, word }, index) => (
        <g key={index} className="phase-badge" data-future={column.future || undefined}>
          <circle cx={cx} cy={bottom + 12} r={BADGE / 2} />
          <text x={cx} y={bottom + 16} textAnchor="middle" className="badge-text">
            {column.phase}
          </text>
          {word && (
            <text x={cx + BADGE / 2 + 5} y={bottom + 16} className="badge-word">
              {word}
            </text>
          )}
        </g>
      ))}
      {ticks.map((tick, index) => (
        <text
          key={tick}
          x={x(tick)}
          y={height - 3}
          className="axis-label"
          textAnchor={index === 0 ? "start" : "middle"}
        >
          {hourLabel(tick)}
        </text>
      ))}
    </svg>
  );
}

/** A phase column in words: when, which phase, what it is. */
function columnText(column: Column, lane: Lane, day: GrowDay, now: number): string {
  const phase = PHASES[column.phase];
  const end = column.end >= day.end ? clock(day.end) : clock(column.end);
  const lasted = column.future
    ? "expected"
    : column.end > now
      ? `${duration(now - column.start)} so far`
      : duration(column.end - column.start);
  return [
    `${clock(column.start)}–${end} · ${lane.zone.name} · ${lasted}`,
    `${column.phase} ${phase?.name.toLowerCase() ?? ""}${phase ? `: ${phase.what}` : ""}`,
  ].join("\n");
}

/** A clock hour short enough for an axis: "4 PM", "16". */
const hourLabel = (time: number) =>
  new Date(time)
    .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    .replace(/:00(?=\D|$)/, "");
const diamond = (cx: number, cy: number) =>
  `M${cx} ${cy - 5}L${cx + 5} ${cy}L${cx} ${cy + 5}L${cx - 5} ${cy}Z`;
/** The recorded VWC as one path, broken where readings stop for more than 20 minutes. */
function linePath(points: Reading[], x: (time: number) => number, y: (value: number) => number) {
  return points
    .map((point, index) => {
      const gap = index === 0 || point.time - points[index - 1].time > 20 * 60_000;
      return `${gap ? "M" : "L"}${x(point.time).toFixed(1)} ${y(point.value).toFixed(1)}`;
    })
    .join("");
}
/** The maintenance band over one ramp or maintenance column: from the maintenance trigger up to the
 * peak target, stepping where either setpoint changed. */
function bandSegments(steps: Steps, column: Column) {
  const high = steps("p1_target_vwc", column),
    low = steps("p2_vwc_threshold", column);
  const cuts = [...new Set([...high, ...low].flatMap((level) => [level.start, level.end]))].sort(
    (a, b) => a - b,
  );
  const at = (levels: Level[], time: number) =>
    levels.find((level) => level.start <= time && time < level.end)?.value;
  return cuts.slice(0, -1).flatMap((start, index) => {
    const end = cuts[index + 1],
      middle = (start + end) / 2;
    const a = at(high, middle),
      b = at(low, middle);
    return a === undefined || b === undefined
      ? []
      : [{ start, end, high: Math.max(a, b), low: Math.min(a, b) }];
  });
}
/** The typical day's middle half as one area, broken where too few days were recorded. */
function typicalArea(
  typical: TypicalPoint[],
  x: (hour: number) => number,
  y: (value: number) => number,
) {
  const runs: TypicalPoint[][] = [];
  typical.forEach((point, index) => {
    if (index && point.hour - typical[index - 1].hour < 0.2) runs.at(-1)!.push(point);
    else runs.push([point]);
  });
  const line = (run: TypicalPoint[], key: "low" | "high") =>
    run.map((point) => `${x(point.hour).toFixed(1)} ${y(point[key]).toFixed(1)}`);
  return runs
    .map((run) => `M${[...line(run, "high"), ...line([...run].reverse(), "low")].join("L")}Z`)
    .join("");
}

/** What the chart says at a moment, one fact a line: VWC (recorded or expected), pore EC, the
 * comparison, and what the controller aims at then. */
function readingText(
  lane: Lane,
  at: number,
  now: number,
  dayStart: number,
  before: Reading[],
  typical: TypicalPoint[],
  fc: Level[],
  band: { start: number; end: number; high: number; low: number }[],
  rescue: Level[],
  compare: Compare,
  show: (layer: ChartLayer) => boolean,
): string {
  const name = lane.zone.name;
  const lines: string[] = [];
  const inside = <T extends { start: number; end: number }>(list: T[]) =>
    list.find((item) => item.start <= at && at < item.end);
  if (at > now) {
    // The projection is a line from point to point, however far apart they are.
    const value = valueAtTime(lane.projection?.points ?? [], at, 24 * 3_600_000);
    lines.push(`≈${clock(at)} · ${name} · expected`);
    if (show("vwc"))
      lines.push(
        value !== null
          ? `VWC ≈${number(value)}%, an estimate: the controller waters by the probe`
          : `No projection: ${lane.status ?? NO_ESTIMATE[lane.next.basis] ?? "not enough to go on"}`,
      );
  } else {
    const value = valueAtTime(lane.points, at);
    const phase = phaseAt(lane.bands, at);
    const ec = valueAtTime(lane.ec, at, 40 * 60_000);
    lines.push(`${clock(at)} · ${name}${phase ? ` · ${phase}` : ""}`);
    const readings = [
      ...(show("vwc") ? [value === null ? "No VWC reading then" : `VWC ${number(value, 1)}%`] : []),
      ...(show("ec") && ec !== null ? [`pore EC ${number(ec, 2)}`] : []),
    ];
    if (readings.length) lines.push(readings.join(" · "));
  }
  if (compare === "yesterday" && lane.yesterday) {
    const value = valueAtTime(before, at);
    lines.push(`Yesterday ${value === null ? "not recorded" : `${number(value)}%`}`);
    if (lane.setupNote) lines.push(lane.setupNote);
  }
  if (compare === "typical") {
    const hour = (at - dayStart) / 3_600_000;
    const point = typical.find((item) => Math.abs(item.hour - hour) <= 1 / 12);
    if (point)
      lines.push(
        `Typical ${number(point.median)}% (middle half ${number(point.low)}–${number(point.high)}%)`,
      );
  }
  const maintenance = show("band") ? inside(band) : undefined;
  if (maintenance)
    lines.push(
      `Maintenance band ${number(maintenance.low)}–${number(maintenance.high)}%: re-waters under ${number(maintenance.low)}%`,
    );
  const floor = show("rescue") ? inside(rescue) : undefined;
  if (floor) lines.push(`Rescue shot only under ${number(floor.value)}%`);
  const capacity = show("fc") ? inside(fc) : undefined;
  if (capacity) lines.push(`Field capacity ${number(capacity.value)}%`);
  return lines.join("\n");
}

/** What comes next for the zone, in a few words, and its detail. */
function nextWords(lane: Lane, day: GrowDay): { text: string; detail: string; tone?: "warn" } {
  const { next, zone } = lane;
  if (lane.stopped)
    return { text: `not watering: ${lane.stopped}`, detail: lane.status ?? "", tone: "warn" };
  const held = lane.blocks.at(-1);
  if (next.basis === "held" && held)
    return {
      text: `${HELD[held.kind]}: ${held.text}`,
      detail: blockText(held, lane),
      tone: "warn",
    };
  if (next.basis === "firing") return { text: "a shot is running now", detail: "" };
  // The controller's own conditions, for the phase this lane is in; the estimate beside them.
  const conditions =
    zone.waiting && zone.phase === lane.phase
      ? waitingText(zone.waiting, {
          number: (value) => number(value),
          clock,
          shotEstimate: next.basis === "dry-down" ? next.at : null,
        })
      : "";
  const first = conditions.split(" · ")[0];
  const estimate =
    next.at === null
      ? null
      : next.basis === "dry-down"
        ? `shot ≈ ${clock(next.at)}`
        : next.basis === "due"
          ? "shot due now"
          : next.basis === "p1-interval"
            ? `ramp shot ≈ ${clock(next.at)}`
            : next.basis === "p0-wait"
              ? `ramp starts by ${clock(next.at)}`
              : null;
  if (first) {
    // Beside the controller's own condition, the estimate needs no second "shot".
    const when =
      next.at === null || first.includes(clock(next.at))
        ? ""
        : next.basis === "due"
          ? " · due now"
          : next.basis === "dry-down"
            ? ` · ≈ ${clock(next.at)}`
            : "";
    return { text: `${first}${when}`, detail: `What the controller waits for: ${conditions}` };
  }
  if (next.basis === "night" || lane.phase === "P3")
    return {
      text:
        lane.rescue !== null
          ? `rescue shot only if VWC < ${number(lane.rescue)}% · P0 at ${clock(day.end)}`
          : `overnight, no shots until ${clock(day.end)}`,
      detail: "Overnight the controller waters only to rescue a zone that dries below its floor.",
    };
  if (estimate) return { text: estimate, detail: "An estimate from today’s readings." };
  if (next.basis === "ramp-done")
    return { text: "hand-over to P2 maintenance", detail: "The ramp is at its ceiling." };
  if (next.basis === "late")
    return { text: "no more shots before lights-off", detail: NO_ESTIMATE.late! };
  return {
    text: "no estimate yet",
    detail: NO_ESTIMATE[next.basis] ?? "not enough to go on",
  };
}
function changeText(change: Change): string {
  const unit = change.unit ? ` ${change.unit}` : "";
  const zone = change.zoneId === undefined ? "Room" : `Zone ${change.zoneId}`;
  return `${clock(change.time)} · ${zone} · ${change.label} ${number(change.from, 2)} → ${number(change.to, 2)}${unit}`;
}
/** A shot, one fact a line (the events list joins them). */
function shotText(shot: Shot, lane: Lane): string {
  const litres = lane.litres((shot.end - shot.start) / 1000);
  return [
    `${clock(shot.start)}–${shot.open ? "now" : clock(shot.end)} · ${lane.zone.name}`,
    `${shot.phase ? `${shot.phase} shot` : "Shot"} ${duration(shot.end - shot.start)}${shot.open ? " so far" : ""}${litres === null ? "" : `, ≈${number(litres)} L at the configured flow`}`,
    ...(shot.reason ? [shot.reason] : []),
  ].join("\n");
}
function blockText(block: Block, lane: Lane): string {
  return [
    `${clock(block.start)}–${block.open ? "now" : clock(block.end)} · ${lane.zone.name}`,
    `${capital(HELD[block.kind])} for ${duration(block.end - block.start)}: ${block.text}`,
  ].join("\n");
}
/** A decision Jev made: who, what it answered, what it asked for and what code did. */
function jevText(entry: JevEntry, lane: Lane): string {
  const result = jevResult(entry).label;
  const agreed =
    entry.agreed === true
      ? " (both phrasings agreed)"
      : entry.agreed === false
        ? " (the two phrasings disagreed)"
        : "";
  return [
    `${clock(entry.time)} · ${lane.zone.name} · Jev: ${entry.title}`,
    `${jevAnswer(entry)}${agreed}`,
    ...(entry.action ? [`Asked to ${entry.action}`] : []),
    entry.reason ? `${result}: ${entry.reason}` : result,
  ].join("\n");
}
function laneEvents(lane: Lane, day: GrowDay) {
  const name = lane.zone.name;
  const line = (text: string) => text.replaceAll("\n", " · ");
  return [
    ...lane.bands.flatMap((band, index) =>
      band.start > day.start
        ? [
            {
              time: band.start,
              text: `${clock(band.start)} · ${name} · ${lane.bands[index - 1]?.phase ?? "no phase"} → ${band.phase}`,
            },
          ]
        : [],
    ),
    ...lane.shots.map((shot) => ({ time: shot.start, text: line(shotText(shot, lane)) })),
    ...lane.blocks.map((block) => ({ time: block.start, text: line(blockText(block, lane)) })),
    ...lane.changes.map((change) => ({ time: change.time, text: changeText(change) })),
    ...lane.jev.map((entry) => ({ time: entry.time!, text: line(jevText(entry, lane)) })),
  ];
}
