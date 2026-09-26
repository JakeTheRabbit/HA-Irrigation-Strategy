import { useEffect, useRef, useState, type MouseEvent, type PointerEvent } from "react";
import { LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, number, time as clock } from "@/components/dashboard";
import { ageText, ageTone, readHeartbeat } from "@/lib/controller-health";
import {
  alignBands,
  appendLive,
  atHour,
  compareDays,
  duration,
  earlierDays,
  earlierEntities,
  earlierTraces,
  growDay,
  joinRows,
  morningDryback,
  nextShot,
  NOT_REPORTING,
  openSeconds,
  phaseAt,
  phaseBands,
  phaseTargets,
  reachedHour,
  readings,
  setpointChanges,
  setpointSteps,
  timelineEntities,
  typicalDay,
  unprojected,
  valveShots,
  zoneBlocks,
  type Block,
  type Comparison,
  type DayTrace,
  type GrowDay,
  type NextShot,
  type PhaseBand,
  type Reading,
  type SetpointChange,
  type Shot,
  type TargetStep,
  type TimelineRows,
  type TypicalPoint,
} from "@/lib/day-timeline";
import { descriptor, numeric } from "@/lib/model";
import {
  buildPlanningCurve,
  dryRates,
  projectFrom,
  smoothRecorded,
  type PlanningPhaseId,
} from "@/lib/planning-curve";
import { buildSetpointPreview } from "@/lib/setpoint-preview";
import { settingWords } from "@/lib/setting-words";
import type { Controller, Setting, Zone } from "@/lib/types";
import { errorText } from "@/lib/utils";
import { estimateRuntime, flowInputs, waterParameters } from "@/lib/water-delivery";
import "./day-timeline.css";

const PHASES: Record<string, string> = {
  P0: "P0 dryback",
  P1: "P1 ramp",
  P2: "P2 maintenance",
  P3: "P3 overnight",
};
const HELD: Record<Block["kind"], string> = {
  cap: "daily budget spent",
  block: "blocked",
  hold: "held",
};
// Each phase's target line, named as its setting is (setting-words).
const TARGETS: Record<string, string> = {
  P0: "Dries back to", // a level worked out from the dryback target, not the setting itself
  P1: settingWords("p1_target_vwc")!.short,
  P2: settingWords("p2_vwc_threshold")!.short,
  P3: settingWords("p3_emergency_vwc_threshold")!.short,
};
const MARKS = [
  ["key-shot", "Shot (valve open)"],
  ["key-expected", "Expected shot"],
  ["key-cap", "Blocked or budget spent"],
  ["key-hold", "Held by a gate"],
  ["key-change", "Setpoint change"],
  ["key-night", "Lights off"],
];
const NO_ESTIMATE: Partial<Record<NextShot["basis"], string>> = {
  firing: "a shot is running",
  late: "no P2 shot expected before lights-off at the current dry-down",
  settling: "VWC is still settling after the last shot",
  "no-dry-down": "VWC is not falling measurably",
  "no-reading": "no live VWC reading",
  "ramp-done": "the ramp is at its ceiling, P2 is next",
};
type Compare = "yesterday" | "typical" | "none";
/** What the chart draws besides today, remembered in this browser. `compared` is the comparison's
 * layer: yesterday's line, or the typical band. */
interface Layers {
  projected: boolean;
  compared: boolean;
  targets: boolean;
  compare: Compare;
}
const LAYERS_KEY = "crop-steering-timeline-layers";
function storedLayers(): Layers {
  let saved: Partial<Layers> | null = null;
  try {
    saved = JSON.parse(localStorage.getItem(LAYERS_KEY) ?? "null");
  } catch {
    /* no storage: the defaults */
  }
  return {
    projected: saved?.projected !== false,
    compared: saved?.compared !== false,
    targets: saved?.targets !== false,
    compare:
      saved?.compare === "typical" || saved?.compare === "none" ? saved.compare : "yesterday",
  };
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
interface Lane {
  zone: Zone;
  bands: PhaseBand[];
  shots: Shot[];
  blocks: Block[];
  points: Reading[];
  changes: Change[];
  phase: string | null;
  since: number | null;
  /** In P2, the threshold the estimate dries down to. */
  target: number | null;
  next: NextShot;
  /** Why this zone is not being watered at all, if it is not. */
  stopped: string | null;
  p1Shots: number;
  litres: (seconds: number) => number | null;
  /** What the controller aims at, phase by phase: as recorded, then along the projection. */
  targets: TargetStep[];
  projection: Projection | null;
  /** The grow-day before today, and every earlier one there is to compare (latest first). */
  yesterday: DayTrace | null;
  past: DayTrace[];
  typical: TypicalPoint[];
  comparison: Comparison | null;
  /** The P1 target, and when today first reached it (hours since lights-on). */
  level: number | null;
  reached: number | null;
  /** Valve-open seconds today, until now. */
  seconds: number;
  dryback: number | null;
  drybackTarget: number | null;
  /** Rooms & setup was saved after the day compared with began. */
  setupNote: string | null;
  /** What the lane line ends with: why the zone is not watered, or held, or how old the last report
   * is. */
  status: string | null;
}
interface Mark {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  /** Lower ranks win: thin marks (shots, setpoint changes) first, with a wider touch target. */
  rank: number;
  text: (time: number) => string;
}
/** Earlier grow-days as loaded: per zone, each day's trace, yesterday first (null where there is
 * nothing to compare), and the room's setup revision as each day began. */
interface Earlier {
  key: string;
  traces: Map<number, (DayTrace | null)[]>;
  setup: (number | null)[];
  error: string;
}
/** Past grow-days do not change, so a room's week is loaded once per grow-day and kept while the
 * page is open. */
const earlierLoads = new Map<string, Promise<TimelineRows>>();
/** Runs `tasks` two at a time; no more start once one has failed. */
async function inPairs<T>(tasks: (() => Promise<T>)[]): Promise<T[]> {
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
/** The seven grow-days before today: one request per day, over the transport and within the room
 * that today's use, cut where each day's lights actually came on. Null while loading. */
function useEarlierDays(controller: Controller, day: GrowDay | null, ready: boolean) {
  const { room, states } = controller;
  const ids = earlierEntities(room, states);
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
      // A page left open for days keeps only its latest few weeks.
      if (earlierLoads.size >= 4) earlierLoads.delete(earlierLoads.keys().next().value!);
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

/** The selected room's grow-day on one time axis: lights, each zone's phases, every shot, what held
 * a zone back and every setpoint change, as recorded; then the rest of the day as projected, the
 * target for each phase, and yesterday's day (or a typical one) to compare with. Today is downloaded
 * once when the page opens and live updates extend it; the earlier days are downloaded once. */
export function DayTimeline({ controller }: { controller: Controller }) {
  const [, tick] = useState(0);
  useEffect(() => {
    // The clock moves between live updates, and a quiet controller sends none.
    const timer = window.setInterval(() => tick((value) => value + 1), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const [layers, setLayers] = useState(storedLayers);
  const change = (next: Partial<Layers>) => {
    const merged = { ...layers, ...next };
    setLayers(merged);
    try {
      localStorage.setItem(LAYERS_KEY, JSON.stringify(merged));
    } catch {
      /* The choice still applies on this page. */
    }
  };
  const { room, states } = controller;
  const now = Date.now();
  const prefix = room.room.prefix;
  const day = growDay(
    numeric(states[`number.crop_steering_${prefix}lights_on_hour`]),
    numeric(states[`number.crop_steering_${prefix}lights_off_hour`]),
    now,
  );
  const entities = timelineEntities(room, states);
  const key = day
    ? [room.room.id, day.start, ...entities.entityIds, "|", ...entities.attributeIds].join(" ")
    : "";
  const ready = controller.connection === "live" || controller.connection === "demo";
  const demo = controller.demo;
  const [data, setData] = useState<{ key: string; rows: TimelineRows } | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const latest = useRef({ states, entities, day });
  latest.current = { states, entities, day };
  const load = controller.timeline;
  const earlier = useEarlierDays(controller, day, ready);
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
  return (
    <section className="panel day-timeline" data-day-timeline aria-labelledby="day-timeline-title">
      <div className="panel-heading">
        <h2 id="day-timeline-title">Today’s grow day</h2>
        {rows && (
          <div className="timeline-heading-side">
            <label htmlFor="day-timeline-compare" className="timeline-compare">
              Compare with
            </label>
            <select
              id="day-timeline-compare"
              value={layers.compare}
              onChange={(event) => change({ compare: event.target.value as Compare })}
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
      ) : !room.zones.length ? (
        <Empty
          title="No zones discovered"
          detail="The grow day appears once the room’s zones are configured."
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
      ) : !rows ? (
        <div className="chart-placeholder" role="status">
          <LoaderCircle className="spin" />
          Loading today’s recorded history…
        </div>
      ) : (
        <Timeline
          controller={controller}
          entities={entities}
          day={day}
          rows={rows}
          now={now}
          earlier={earlier}
          layers={layers}
          change={change}
        />
      )}
    </section>
  );
}

function Timeline({
  controller,
  entities,
  day,
  rows,
  now,
  earlier,
  layers,
  change,
}: {
  controller: Controller;
  entities: ReturnType<typeof timelineEntities>;
  day: GrowDay;
  rows: TimelineRows;
  now: number;
  earlier: Earlier | null;
  layers: Layers;
  change: (next: Partial<Layers>) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const [hover, setHover] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const { room, states } = controller;
  const decisions = rows[entities.attributeIds[0]] ?? [];
  const settings = new Map(room.settings.map((setting) => [setting.entityId, setting]));
  const changes = setpointChanges(rows, [...settings.keys()], day.start, now).map(
    (change): Change => {
      const setting = settings.get(change.entityId) as Setting;
      return { ...change, label: setting.label, unit: setting.unit, zoneId: setting.zoneId };
    },
  );
  const settingId = (zone: Zone, key: string) => {
    // Like the controller: the zone's own setpoint when it has one, else the room's.
    const own = `number.crop_steering_${room.room.prefix}zone_${zone.id}_${key}`;
    return states[own] ? own : `number.crop_steering_${room.room.prefix}${key}`;
  };
  const read = (zone: Zone, key: string) => numeric(states[settingId(zone, key)]);
  const hourOf = (time: number) => (time - day.start) / 3_600_000;
  const length = hourOf(day.end),
    photoperiod = hourOf(day.lightsOff);
  const beat = readHeartbeat(states[`sensor.crop_steering_${room.room.prefix}ai_heartbeat`], now);
  const revision = descriptor(states, room.room)?.attributes.setup_revision;
  const lanes = room.zones.map((zone): Lane => {
    const ids = entities.zones.find((item) => item.id === zone.id);
    const shots = valveShots(ids?.valve ? rows[ids.valve] : [], decisions, zone.id, day.start, now);
    const bands = alignBands(phaseBands(ids && rows[ids.phase], day.start, now), shots);
    const blocks = zoneBlocks(decisions, zone.id, day.start, now);
    const points = ids?.vwc ? readings(rows[ids.vwc], day.start, now) : [];
    const water = waterParameters(controller, zone.id);
    // The phase now is the band that reaches now: none while the sensor is unreadable.
    const last = bands.at(-1);
    const phase = last && last.end >= now ? last.phase : null;
    const since = phase ? last!.start : null;
    const planned = room.strategy.engaged;
    // The zone's target (model.ts) is what the controller compares with in its phase, the plan's
    // while one runs; a plan's timing is its own, so P0 and P1 are not estimated under one.
    const phaseTarget = (key: string) =>
      zone.phase === phase ? zone.target.value : read(zone, key);
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
    const ceiling = ramp === null ? null : Math.min(ramp, read(zone, "field_capacity") ?? Infinity);
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
            maxWait: planned ? null : read(zone, "p0_maximum_wait_time"),
          },
          day,
          now,
        );
    // Targets resolve as the controller's do: the zone's setpoint, else the room's, else the plan's
    // snapshot while one is armed. The dryback target is the steering mode's.
    const preview = buildSetpointPreview(room, states, zone.id, {}).saved;
    const parameters = preview.parameters;
    const setpoint = setpointSteps(
      rows,
      parameters,
      (key) =>
        key !== "dryback_target"
          ? settingId(zone, key)
          : preview.mode && settingId(zone, `${preview.mode.toLowerCase()}_dryback_target`),
      planned,
    );
    const traces = earlier?.traces.get(zone.id) ?? [];
    const yesterday = traces[0] ?? null;
    const past = traces.filter((trace): trace is DayTrace => trace !== null);
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
              rates: dryRates(
                [today, ...past.slice(0, 3).map((trace) => trace.points)],
                photoperiod,
              ),
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
    // Past targets follow the recorded phases, later ones the projected.
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
    const compared =
      layers.compare === "typical"
        ? past.length >= 3
          ? past
          : []
        : layers.compare === "yesterday" && yesterday
          ? [yesterday]
          : [];
    const level = Number.isFinite(parameters.p1_target_vwc) ? parameters.p1_target_vwc : null;
    const hour = hourOf(now);
    const moved = earlier?.setup.filter(
      (value, index) =>
        typeof revision === "number" &&
        value !== null &&
        value !== revision &&
        traces[index] &&
        compared.includes(traces[index]!),
    ).length;
    return {
      zone,
      bands,
      shots,
      blocks,
      points,
      changes: changes.filter((change) => change.zoneId === zone.id),
      phase,
      since,
      target,
      stopped,
      next,
      p1Shots,
      litres: (seconds) => estimateRuntime(flowInputs(water), seconds).requested?.zoneL ?? null,
      targets: phaseTargets(
        [...bands, ...ahead.filter((band) => band.end > band.start)],
        setpoint,
        [...points, ...(projection?.points ?? [])],
      ),
      projection,
      yesterday,
      past,
      typical:
        layers.compare === "typical" && past.length >= 3
          ? typicalDay(past.map((trace) => trace.points))
          : [],
      comparison: compareDays(compared, hour, zone.vwc.value, level),
      level,
      reached: level === null ? null : reachedHour(today, level),
      seconds: openSeconds(shots, day.start, hour),
      dryback: p0 ? morningDryback(points, p0) : null,
      drybackTarget: Number.isFinite(parameters.dryback_target) ? parameters.dryback_target : null,
      setupNote: !moved
        ? null
        : layers.compare === "yesterday"
          ? "Rooms & setup saved since yesterday: its probe may have differed"
          : `${moved} of ${compared.length} days before the last Rooms & setup save`,
      status:
        unprojected(stopped, beat.at, now) ??
        (next.basis === "held" && held
          ? `${HELD[held.kind]}: ${held.text}`
          : next.basis === "night"
            ? `overnight: emergency shots only until ${clock(day.end)}`
            : null),
    };
  });
  const roomChanges = changes.filter((change) => change.zoneId === undefined);
  const plot = Math.max(160, width - 48);
  const x = (time: number) =>
    Math.max(0, Math.min(plot, ((time - day.start) / (day.end - day.start)) * plot));
  const timeAt = (px: number) => day.start + (px / plot) * (day.end - day.start);
  const events = [
    ...lanes.flatMap((lane) => laneEvents(lane, day)),
    ...roomChanges.map((change) => ({ time: change.time, text: changeText(change) })),
  ].sort((a, b) => a.time - b.time);
  const strip = (marks: Mark[]) => pointer(marks, setHover, setPicked, timeAt);
  const typicalDays = Math.max(0, ...lanes.map((lane) => lane.past.length));
  const toggle = (key: "projected" | "compared" | "targets", icon: string, name: string) => (
    <li>
      <button
        type="button"
        className="timeline-toggle"
        aria-pressed={layers[key]}
        onClick={() => change({ [key]: !layers[key] })}
      >
        <i className={icon} aria-hidden="true" />
        {name}
      </button>
    </li>
  );
  return (
    <div className="timeline-body" ref={box}>
      {width > 0 && (
        <>
          <Axis day={day} now={now} plot={plot} x={x} changes={roomChanges} strip={strip} />
          {lanes.map((lane) => {
            const line = tracking(lane, day, now, layers.compare, earlier);
            return (
              <div className="timeline-zone" key={lane.zone.id} data-zone={lane.zone.id}>
                <p className="timeline-zone-line" title={`${lane.zone.name} ${line}`}>
                  <strong>{lane.zone.name}</strong> <span>{line}</span>
                </p>
                <LaneChart
                  lane={lane}
                  day={day}
                  now={now}
                  plot={plot}
                  x={x}
                  strip={strip}
                  layers={layers}
                />
              </div>
            );
          })}
        </>
      )}
      <p className="timeline-detail" aria-live="polite">
        {hover ??
          picked ??
          "Point at or tap the chart for details. A projection is an estimate: the controller waters by the probe."}
      </p>
      <ul className="timeline-legend" aria-label="Timeline key">
        {Object.entries(PHASES).map(([phase, name]) => (
          <li key={phase}>
            <i className={`key-phase phase-${phase}`} aria-hidden="true" />
            {name}
          </li>
        ))}
        <li>
          <i className="key-today" aria-hidden="true" />
          Today
        </li>
        {toggle("projected", "key-projected", "Projected (estimate)")}
        {layers.compare === "yesterday" && toggle("compared", "key-yesterday", "Yesterday")}
        {layers.compare === "typical" &&
          toggle(
            "compared",
            "key-typical",
            typicalDays >= 3 ? `Typical (${typicalDays} days)` : "Typical (too few days)",
          )}
        {toggle("targets", "key-target", "Target for the phase")}
        {MARKS.map(([key, name]) => (
          <li key={key}>
            <i className={key} aria-hidden="true" />
            {name}
          </li>
        ))}
      </ul>
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
  );
}

/** Pointer handlers for one strip: pointing shows a mark's details, tapping or clicking keeps them,
 * so nothing is available on hover alone. */
function pointer(
  marks: Mark[],
  onHover: (text: string | null) => void,
  onPick: (text: string | null) => void,
  timeAt: (px: number) => number,
) {
  const find = (event: PointerEvent<SVGSVGElement> | MouseEvent<SVGSVGElement>) => {
    const frame = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - frame.left,
      py = event.clientY - frame.top;
    const hit = marks
      .filter((mark) => {
        const pad = mark.rank === 0 ? Math.max(0, 7 - (mark.x1 - mark.x0) / 2) : 0;
        return px >= mark.x0 - pad && px <= mark.x1 + pad && py >= mark.y0 && py <= mark.y1;
      })
      .sort((a, b) => a.rank - b.rank || a.x1 - a.x0 - (b.x1 - b.x0))[0];
    return hit ? hit.text(timeAt(px)) : null;
  };
  return {
    onPointerMove: (event: PointerEvent<SVGSVGElement>) => {
      if (event.pointerType === "mouse") onHover(find(event));
    },
    onPointerLeave: () => onHover(null),
    onClick: (event: MouseEvent<SVGSVGElement>) => onPick(find(event)),
  };
}
type Strip = (marks: Mark[]) => ReturnType<typeof pointer>;
/** A pointer target over [from, to] and the rows y0 to y1 of a strip. */
const markAt =
  (x: (time: number) => number) =>
  (from: number, to: number, y0: number, y1: number, rank: number, text: Mark["text"]): Mark => ({
    x0: x(from),
    x1: x(to),
    y0,
    y1,
    rank,
    text,
  });
/** A phase as a coloured band, labelled where the label fits; an expected one is dashed, and
 * one whose end nobody knows is not coloured as any phase. */
function Band(props: {
  x0: number;
  x1: number;
  phase: string;
  label: string;
  expected?: "known" | "open";
}) {
  const { x0, x1, label, expected } = props;
  const kind = !expected ? "" : expected === "open" ? " projected open" : " projected";
  return (
    <g>
      <rect
        x={x0}
        y={2}
        width={Math.max(1, x1 - x0)}
        height={16}
        className={`phase phase-${props.phase}${kind}`}
      />
      {x1 - x0 >= label.length * 8 + 8 && (
        <text x={(x0 + x1) / 2} y={14} className={`phase-label${kind}`}>
          {label}
        </text>
      )}
    </g>
  );
}

function Axis({
  day,
  now,
  plot,
  x,
  changes,
  strip,
}: {
  day: GrowDay;
  now: number;
  plot: number;
  x: (time: number) => number;
  changes: Change[];
  strip: Strip;
}) {
  // Steps wide enough that the clock labels never touch.
  const label = clock(day.start).length * 7 + 14;
  const step = [1, 2, 3, 4, 6, 8, 12].find((hours) => (plot * hours) / 24 >= label) ?? 12;
  const ticks: number[] = [];
  for (let time = day.start; time <= day.end; time += step * 3_600_000) ticks.push(time);
  const off = x(day.lightsOff);
  const height = changes.length ? 52 : 36;
  const mark = markAt(x);
  const marks = [
    mark(
      day.start,
      day.lightsOff,
      16,
      34,
      2,
      () => `${clock(day.start)}–${clock(day.lightsOff)} · lights on`,
    ),
    mark(
      day.lightsOff,
      day.end,
      16,
      34,
      2,
      () => `${clock(day.lightsOff)}–${clock(day.end)} · lights off`,
    ),
    ...changes.map((change) => mark(change.time, change.time, 36, 52, 0, () => changeText(change))),
  ];
  return (
    <svg
      className="timeline-axis"
      width={plot + 48}
      height={height}
      aria-hidden="true"
      {...strip(marks)}
    >
      <defs>
        <pattern
          id="day-timeline-hatch"
          width="6"
          height="6"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <rect width="6" height="6" className="hatch-ground" />
          <line x1="0" y1="0" x2="0" y2="6" className="hatch-line" />
        </pattern>
      </defs>
      {ticks.map((time, index) => (
        <text
          key={time}
          x={x(time)}
          y={12}
          className="timeline-tick"
          textAnchor={index === 0 ? "start" : time + step * 3_600_000 > day.end ? "end" : "middle"}
        >
          {clock(time)}
        </text>
      ))}
      <rect x={0} y={18} width={off} height={14} className="lights-on" />
      <rect x={off} y={18} width={plot - off} height={14} className="lights-off" />
      {off > 76 && (
        <text x={4} y={29} className="lights-label">
          Lights on
        </text>
      )}
      {plot - off > 76 && (
        <text x={off + 4} y={29} className="lights-label off">
          Lights off
        </text>
      )}
      <text x={plot + 6} y={29} className="timeline-gutter">
        Lights
      </text>
      {changes.map((change, index) => (
        <path key={index} d={diamond(x(change.time), 44)} className="setpoint-mark" />
      ))}
      {!!changes.length && (
        <text x={plot + 6} y={48} className="timeline-gutter">
          Room
        </text>
      )}
      <line x1={x(now)} x2={x(now)} y1={16} y2={height} className="now-line" />
    </svg>
  );
}

function LaneChart({
  lane,
  day,
  now,
  plot,
  x,
  strip,
  layers,
}: {
  lane: Lane;
  day: GrowDay;
  now: number;
  plot: number;
  x: (time: number) => number;
  strip: Strip;
  layers: Layers;
}) {
  const { zone, next, points, target } = lane;
  const name = zone.name;
  const hourOf = (time: number) => (time - day.start) / 3_600_000;
  // Earlier days sit on today's axis by hours since their own lights-on.
  const aligned = (trace: DayTrace, time: number) => day.start + time - trace.day.start;
  const yesterday = layers.compared && layers.compare === "yesterday" ? lane.yesterday : null;
  const typical =
    layers.compared && layers.compare === "typical"
      ? lane.typical.filter((point) => point.hour <= hourOf(day.end))
      : [];
  const projection = layers.projected ? lane.projection : null;
  const targets = layers.targets ? lane.targets : [];
  const before = (yesterday?.points ?? [])
    .filter((point) => point.hour <= hourOf(day.end))
    .map((point) => ({ time: day.start + point.hour * 3_600_000, value: point.value }));
  const earlierShots = yesterday
    ? yesterday.shots.filter((shot) => aligned(yesterday, shot.start) < day.end)
    : [];
  // VWC is drawn over the range of what is plotted, never 0-100 %. A target within one span of it
  // widens the range; one further off is drawn at the edge it is beyond, and says so.
  const values = points.length
    ? [
        ...points.map((point) => point.value),
        ...before.map((point) => point.value),
        ...typical.flatMap((point) => [point.low, point.high]),
        ...(projection?.points.map((point) => point.value) ?? []),
        ...(next.basis === "dry-down" && target !== null ? [target] : []),
      ]
    : [];
  const lowest = Math.min(...values),
    highest = Math.max(...values),
    spread = Math.max(1, highest - lowest);
  const near = targets
    .map((step) => step.value)
    .filter((value) => value >= lowest - spread && value <= highest + spread);
  const low = Math.min(lowest, ...near),
    high = Math.max(highest, ...near);
  const pad = Math.max(0.3, (high - low) * 0.12);
  const min = low - pad,
    max = high + pad;
  const top = 24,
    area = 40;
  const y = (value: number) =>
    top + area - ((Math.min(max, Math.max(min, value)) - min) / (max - min)) * area;
  const start = Math.max(now, day.start);
  // What is known of the rest of the day: P2 lasts until lights-off and P3 from there. P0 and P1
  // end when their own conditions are met, at a time nobody knows, so they are drawn as open.
  const projected: (PhaseBand & { label: string; text: string; open?: boolean })[] = [];
  if (now < day.lightsOff && lane.phase && lane.phase !== "P3")
    projected.push(
      lane.phase === "P2"
        ? {
            phase: "P2",
            start,
            end: day.lightsOff,
            label: "P2",
            text: "P2 maintenance until lights-off",
          }
        : {
            phase: lane.phase,
            start,
            end: day.lightsOff,
            label: `${lane.phase}→P2`,
            open: true,
            text:
              lane.phase === "P1"
                ? "the P1 ramp until it completes, then P2 maintenance until lights-off"
                : `P0 dryback until it ends${next.basis === "p0-wait" && next.at !== null ? ` (by ${clock(next.at)} at the latest)` : ""}, then the P1 ramp and P2 maintenance until lights-off`,
          },
    );
  projected.push({
    phase: "P3",
    start: Math.max(start, day.lightsOff),
    end: day.end,
    label: "P3",
    text: "P3 overnight from lights-off to the next lights-on",
  });
  const nearest = (time: number) =>
    points.reduce<Reading | null>(
      (best, point) =>
        !best || Math.abs(point.time - time) < Math.abs(best.time - time) ? point : best,
      null,
    );
  const projectedAt = (time: number) => {
    const list = projection?.points ?? [];
    const after = list.findIndex((point) => point.time >= time);
    if (after < 0) return null;
    const a = list[Math.max(0, after - 1)],
      b = list[after];
    return b.time === a.time
      ? b.value
      : a.value + ((b.value - a.value) * (time - a.time)) / (b.time - a.time);
  };
  const targetAt = (time: number) =>
    targets.find((step) => step.start <= time && time < step.end) ?? null;
  // What the other layers say at a moment: the text alternative for each of them.
  const beside = (time: number) => {
    const hour = hourOf(time);
    const parts: string[] = [];
    if (yesterday) {
      const value = atHour(yesterday.points, hour);
      parts.push(
        `yesterday at ${clock(time)}: ${value === null ? "not recorded" : `${number(value)} %`}`,
      );
    }
    if (layers.compared && layers.compare === "typical") {
      const point = typical.find((item) => Math.abs(item.hour - hour) <= 1 / 12);
      parts.push(
        point
          ? `typical at ${clock(time)}: ${number(point.median)} % (middle half ${number(point.low)}–${number(point.high)} %, ${lane.past.length} days)`
          : `typical at ${clock(time)}: not enough recorded days`,
      );
    }
    const step = targetAt(time);
    if (step)
      parts.push(`${TARGETS[step.phase]} ${number(step.value)} %, what the controller aims at`);
    return parts.map((part) => ` · ${part}`).join("");
  };
  const vwcAt = (time: number) => {
    if (time > now) {
      const value = projectedAt(time);
      return value !== null
        ? `≈${clock(time)} · ${name} · projected VWC ≈${number(value)} %, an estimate: the controller waters by the probe${beside(time)}`
        : `${name} · no projection: ${lane.status ?? NO_ESTIMATE[next.basis] ?? "not enough to go on"}${beside(time)}`;
    }
    const point = nearest(time);
    const phase = point && phaseAt(lane.bands, point.time);
    return point
      ? `${clock(point.time)} · ${name} · VWC ${number(point.value, 2)} %${phase ? ` in ${phase}` : ""}${beside(point.time)}`
      : `${name} · no VWC readings recorded today`;
  };
  const mark = markAt(x);
  // Yesterday's own lights-off, and the end of a grow-day shorter than today's (a clock change or
  // a moved schedule), where they fall on today's axis.
  const edges: { time: number; text: string }[] = [];
  if (yesterday) {
    const { start: began, lightsOff, end } = yesterday.day;
    if (Math.abs(lightsOff - began - (day.lightsOff - day.start)) >= 60_000)
      edges.push({
        time: aligned(yesterday, lightsOff),
        text: `Yesterday’s lights went off here, ${duration(lightsOff - began)} after its lights-on`,
      });
    if (end - began < day.end - day.start - 60_000)
      edges.push({
        time: aligned(yesterday, end),
        text: `Yesterday’s grow-day ended here: it was ${duration(end - began)} long`,
      });
  }
  const labels = targetLabels(targets, x, plot);
  const marks = [
    ...lane.bands.map((band) =>
      mark(
        band.start,
        band.end,
        0,
        20,
        2,
        () =>
          `${clock(band.start)}–${band.end >= now ? "now" : clock(band.end)} · ${name} · ${PHASES[band.phase]} (${duration(band.end - band.start)})`,
      ),
    ),
    ...projected.map((band) =>
      mark(
        band.start,
        band.end,
        0,
        20,
        3,
        () => `${clock(band.start)}–${clock(band.end)} · ${name} · expected: ${band.text}`,
      ),
    ),
    mark(day.start, day.end, 20, 66, 4, vwcAt),
    ...edges.map((edge) => mark(edge.time, edge.time, top, top + area, 0, () => edge.text)),
    ...lane.changes.map((change) =>
      mark(change.time, change.time, 18, 32, 0, () => changeText(change)),
    ),
    ...lane.shots.map((shot) => mark(shot.start, shot.end, 64, 88, 0, () => shotText(shot, lane))),
    ...lane.blocks.map((block) =>
      mark(block.start, block.end, 64, 88, 1, () => blockText(block, lane)),
    ),
    ...(projection?.shots ?? []).map((shot) =>
      mark(
        shot.time,
        shot.time,
        64,
        88,
        0,
        () =>
          `≈${clock(shot.time)} · ${name} · expected ${shot.emergency ? "P3 emergency" : shot.phase} shot${shot.size === null ? "" : ` of ${number(shot.size, 2)} % of the substrate`}, an estimate`,
      ),
    ),
    ...earlierShots.map((shot) =>
      mark(aligned(yesterday!, shot.start), aligned(yesterday!, shot.end), 88, 96, 0, () =>
        [
          `Yesterday ${clock(shot.start)}–${clock(shot.end)}`,
          name,
          `shot ${duration(shot.end - shot.start)}`,
          ...(lane.litres((shot.end - shot.start) / 1000) === null
            ? []
            : [`≈${number(lane.litres((shot.end - shot.start) / 1000))} L at the configured flow`]),
        ].join(" · "),
      ),
    ),
    ...(next.at === null
      ? []
      : [
          mark(
            next.at,
            next.at,
            20,
            88,
            0,
            () => `≈${clock(next.at!)} · ${name} · ${nextText(lane, day)}`,
          ),
        ]),
  ];
  const at = next.at;
  const off = x(day.lightsOff);
  const band = typicalBand(typical, (hour) => x(day.start + hour * 3_600_000), y);
  return (
    <svg
      className="timeline-lane"
      width={plot + 48}
      height={96}
      aria-hidden="true"
      {...strip(marks)}
    >
      <rect x={off} y={0} width={plot - off} height={96} className="night" />
      {lane.bands.map((band, index) => (
        <Band
          key={index}
          x0={x(band.start)}
          x1={x(band.end)}
          phase={band.phase}
          label={band.phase}
        />
      ))}
      {projected.map((band, index) => (
        <Band
          key={`p${index}`}
          x0={x(band.start)}
          x1={x(band.end)}
          phase={band.phase}
          label={band.label}
          expected={band.open ? "open" : "known"}
        />
      ))}
      {values.length ? (
        <>
          {!!typical.length && (
            <g data-layer="typical">
              <path d={band.area} className="typical-band" />
              <path d={band.median} className="typical-line" />
            </g>
          )}
          {!!before.length && (
            <g data-layer="yesterday">
              <path d={path(before, x, y)} className="yesterday-line" />
              {edges.map((edge, index) => (
                <line
                  key={index}
                  x1={x(edge.time)}
                  x2={x(edge.time)}
                  y1={top}
                  y2={top + area}
                  className="yesterday-edge"
                />
              ))}
            </g>
          )}
          {!!targets.length && (
            <g data-layer="targets">
              <path d={steps(targets, x, y)} className="target-step" />
              {labels.map((label, index) => (
                <text
                  key={index}
                  x={label.x}
                  y={y(label.value) - 4 < top + 8 ? y(label.value) + 13 : y(label.value) - 4}
                  className="target-label"
                >
                  {label.value < min
                    ? `${label.text} ↓`
                    : label.value > max
                      ? `${label.text} ↑`
                      : label.text}
                </text>
              ))}
            </g>
          )}
          <path d={path(points, x, y)} className="vwc-line" />
          {projection && (
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
          {next.basis === "dry-down" && at !== null && target !== null && (
            <>
              <circle cx={x(at)} cy={y(target)} r={3.5} className="estimate-point" />
              <text
                x={x(at)}
                y={top + 11}
                className="estimate-label"
                textAnchor={x(at) > plot - 40 ? "end" : "middle"}
              >
                ≈{clock(at)}
              </text>
            </>
          )}
          <text x={plot + 6} y={top + 10} className="timeline-gutter">
            {number(max)}%
          </text>
          <text x={plot + 6} y={top + area} className="timeline-gutter">
            {number(min)}%
          </text>
        </>
      ) : (
        <text x={4} y={top + 24} className="timeline-gutter">
          No VWC readings today
        </text>
      )}
      {lane.changes.map((change, index) => (
        <path key={index} d={diamond(x(change.time), 25)} className="setpoint-mark" />
      ))}
      {lane.blocks.map((block, index) => (
        <rect
          key={index}
          x={x(block.start)}
          y={70.5}
          width={Math.max(2, x(block.end) - x(block.start))}
          height={13}
          className={block.kind === "hold" ? "hold" : "cap"}
        />
      ))}
      {lane.shots.map((shot, index) => (
        <rect
          key={index}
          x={x(shot.start)}
          y={68}
          width={Math.max(2, x(shot.end) - x(shot.start))}
          height={18}
          className="shot"
        />
      ))}
      {projection && (
        <g data-layer="expected">
          {projection.shots.map((shot, index) => (
            <line
              key={index}
              x1={x(shot.time)}
              x2={x(shot.time)}
              y1={68}
              y2={86}
              className={shot.emergency ? "expected-shot emergency" : "expected-shot"}
            />
          ))}
        </g>
      )}
      {yesterday && (
        <g data-layer="yesterday-shots">
          {earlierShots.map((shot, index) => (
            <rect
              key={index}
              x={x(aligned(yesterday, shot.start))}
              y={89}
              width={Math.max(
                2,
                x(aligned(yesterday, shot.end)) - x(aligned(yesterday, shot.start)),
              )}
              height={6}
              className="yesterday-shot"
            />
          ))}
        </g>
      )}
      {at !== null && next.basis !== "dry-down" && at <= day.end && (
        <>
          <line x1={x(at)} x2={x(at)} y1={66} y2={88} className="estimate" />
          <text
            x={x(at) + (x(at) > plot - 48 ? -4 : 4)}
            y={82}
            className="estimate-label"
            textAnchor={x(at) > plot - 48 ? "end" : "start"}
          >
            ≈{clock(at)}
          </text>
        </>
      )}
      <line x1={x(now)} x2={x(now)} y1={0} y2={96} className="now-line" />
    </svg>
  );
}

const diamond = (cx: number, cy: number) =>
  `M${cx} ${cy - 5}L${cx + 5} ${cy}L${cx} ${cy + 5}L${cx - 5} ${cy}Z`;
/** The recorded VWC as one path, broken where readings stop for more than 20 minutes. */
function path(points: Reading[], x: (time: number) => number, y: (value: number) => number) {
  return points
    .map((point, index) => {
      const gap = index === 0 || point.time - points[index - 1].time > 20 * 60_000;
      return `${gap ? "M" : "L"}${x(point.time).toFixed(1)} ${y(point.value).toFixed(1)}`;
    })
    .join("");
}
/** The targets as one stepped line, joined where one step starts as the last ends. */
function steps(targets: TargetStep[], x: (time: number) => number, y: (value: number) => number) {
  return targets
    .map((step, index) => {
      const joined = index > 0 && targets[index - 1].end === step.start;
      return `${joined ? "L" : "M"}${x(step.start).toFixed(1)} ${y(step.value).toFixed(1)}H${x(step.end).toFixed(1)}`;
    })
    .join("");
}
/** A label at the start of each target step, where it fits without touching the one before. */
function targetLabels(targets: TargetStep[], x: (time: number) => number, plot: number) {
  const labels: { x: number; value: number; text: string }[] = [];
  let free = 0;
  for (const step of targets) {
    const text = `${TARGETS[step.phase]} ${number(step.value)}%`;
    const width = text.length * 6.6 + 12;
    const left = Math.max(x(step.start) + 3, free);
    // A label may run on past a short step, but P0's lower dryback level only where it fits.
    const room = step.phase === "P0" ? width : 24;
    if (x(step.end) - x(step.start) < room || left > x(step.end) - 12 || left + width > plot)
      continue;
    labels.push({ x: left, value: step.value, text });
    free = left + width + 8;
  }
  return labels;
}
/** The typical day's middle half as a band and its median as a line, broken where too few days
 * were recorded. */
function typicalBand(
  typical: TypicalPoint[],
  x: (hour: number) => number,
  y: (value: number) => number,
) {
  const runs: TypicalPoint[][] = [];
  typical.forEach((point, index) => {
    if (index && point.hour - typical[index - 1].hour < 0.2) runs.at(-1)!.push(point);
    else runs.push([point]);
  });
  const line = (run: TypicalPoint[], key: "low" | "median" | "high") =>
    run.map((point) => `${x(point.hour).toFixed(1)} ${y(point[key]).toFixed(1)}`);
  return {
    area: runs
      .map((run) => `M${[...line(run, "high"), ...line([...run].reverse(), "low")].join("L")}Z`)
      .join(""),
    median: runs.map((run) => `M${line(run, "median").join("L")}`).join(""),
  };
}

function nextText(lane: Lane, day: GrowDay): string {
  const { next } = lane;
  if (lane.stopped) return `not watering: ${lane.stopped}`;
  const held = lane.blocks.at(-1);
  if (next.basis === "held" && held) return `${HELD[held.kind]}: ${held.text}`;
  if (next.basis === "night") return `overnight: emergency shots only until ${clock(day.end)}`;
  if (next.at !== null)
    switch (next.basis) {
      case "dry-down":
        return `next shot ≈ ${clock(next.at)} (estimate)`;
      case "due":
        return `next shot due now (VWC at or under ${number(lane.target)} %)`;
      case "p1-interval":
        return `next shot ≈ ${clock(next.at)} (P1 interval)`;
      case "p0-wait":
        return `P1 starts, with a shot, by ${clock(next.at)} at the latest`;
    }
  return `no estimate: ${NO_ESTIMATE[next.basis] ?? "not enough to go on"}`;
}
const signed = (value: number, digits = 1) => {
  const shown = number(Math.abs(value), digits);
  return Number(shown) === 0 ? "±0" : `${value > 0 ? "+" : "−"}${shown}`;
};
/** The lane's line: how today is tracking, in numbers, against yesterday or the typical day. */
function tracking(
  lane: Lane,
  day: GrowDay,
  now: number,
  compare: Compare,
  earlier: Earlier | null,
): string {
  const who = compare === "typical" ? "typical" : "yesterday";
  const at = (hour: number) => clock(day.start + hour * 3_600_000);
  const vwc = lane.zone.vwc.value;
  const parts = [
    lane.phase ?? "phase unavailable",
    vwc === null ? "VWC now unavailable" : `${number(vwc)}% now`,
  ];
  const then = compare === "none" ? null : lane.comparison;
  if (compare !== "none")
    parts.push(
      !earlier
        ? "loading earlier days…"
        : earlier.error
          ? "earlier days did not load"
          : !then
            ? compare === "typical"
              ? "too few recorded days for a typical one"
              : "no recorded day to compare"
            : then.vwc === null
              ? `${who} at ${clock(now)} not recorded`
              : `${signed(then.vwc)} pts vs ${who} at ${clock(now)}`,
    );
  // Against today's P1 target on both days: a supervisor can move it overnight.
  if (lane.level !== null) {
    const target = `${TARGETS.P1} ${number(lane.level)}%`;
    const missed =
      who === "yesterday" ? " (yesterday did not reach it)" : " (not reached on a typical day)";
    if (lane.reached !== null) {
      const gap = then?.reached == null ? null : Math.round((lane.reached - then.reached) * 60);
      parts.push(
        `${target} reached ${at(lane.reached)}${
          !then
            ? ""
            : gap === null
              ? missed
              : gap === 0
                ? ` (same time as ${who})`
                : ` (${Math.abs(gap)} min ${gap > 0 ? "later" : "earlier"}${who === "typical" ? " than typical" : ""})`
        }`,
      );
    } else
      parts.push(
        `${target} ${lane.phase === "P0" || lane.phase === "P1" ? "not reached yet" : "not reached today"}${!then ? "" : then.reached !== null ? ` (${who} ${at(then.reached)})` : missed}`,
      );
  }
  const litres = (seconds: number) => (seconds > 0 ? lane.litres(seconds) : 0);
  const used = litres(lane.seconds),
    before = then && litres(then.seconds);
  parts.push(
    used !== null
      ? `≈${number(used)} L so far${before != null ? ` (${signed(used - before)} L)` : ""}`
      : `${duration(lane.seconds * 1000)} of watering so far${then ? ` (${signed((lane.seconds - then.seconds) / 60, 0)} min)` : ""}`,
  );
  if (lane.dryback !== null && lane.drybackTarget !== null)
    parts.push(`P0 dryback ${number(lane.dryback)}% of ${number(lane.drybackTarget)}%`);
  return [...parts, lane.setupNote, lane.status].filter(Boolean).join(" · ");
}
function changeText(change: Change): string {
  const unit = change.unit ? ` ${change.unit}` : "";
  const zone = change.zoneId === undefined ? "Room" : `Zone ${change.zoneId}`;
  return `${clock(change.time)} · ${zone} · ${change.label} ${number(change.from, 2)} → ${number(change.to, 2)}${unit}`;
}
function shotText(shot: Shot, lane: Lane): string {
  const litres = lane.litres((shot.end - shot.start) / 1000);
  return [
    `${clock(shot.start)}–${shot.open ? "now" : clock(shot.end)}`,
    lane.zone.name,
    `${shot.phase ? `${shot.phase} shot` : "shot"} ${duration(shot.end - shot.start)}${shot.open ? " so far" : ""}`,
    ...(litres === null ? [] : [`≈${number(litres)} L at the configured flow`]),
    ...(shot.reason ? [shot.reason] : []),
  ].join(" · ");
}
function blockText(block: Block, lane: Lane): string {
  return `${clock(block.start)}–${block.open ? "now" : clock(block.end)} · ${lane.zone.name} · ${HELD[block.kind]} for ${duration(block.end - block.start)}: ${block.text}`;
}
function laneEvents(lane: Lane, day: GrowDay) {
  const name = lane.zone.name;
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
    ...lane.shots.map((shot) => ({ time: shot.start, text: shotText(shot, lane) })),
    ...lane.blocks.map((block) => ({ time: block.start, text: blockText(block, lane) })),
    ...lane.changes.map((change) => ({ time: change.time, text: changeText(change) })),
  ];
}
