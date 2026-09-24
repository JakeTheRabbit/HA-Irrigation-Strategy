import { useEffect, useRef, useState, type MouseEvent, type PointerEvent } from "react";
import { LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, number, time as clock } from "@/components/dashboard";
import { ageText, ageTone } from "@/lib/controller-health";
import {
  alignBands,
  appendLive,
  duration,
  growDay,
  levels,
  nextShot,
  phaseAt,
  phaseBands,
  readings,
  setpointChanges,
  timelineEntities,
  valveShots,
  zoneBlocks,
  type Block,
  type GrowDay,
  type Level,
  type NextShot,
  type PhaseBand,
  type Reading,
  type SetpointChange,
  type Shot,
  type TimelineRows,
} from "@/lib/day-timeline";
import { numeric } from "@/lib/model";
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
const LEGEND = [
  ...Object.entries(PHASES).map(([phase, name]) => [`key-phase phase-${phase}`, name]),
  ["key-shot", "Shot (valve open)"],
  ["key-cap", "Blocked or budget spent"],
  ["key-hold", "Held by a gate"],
  ["key-change", "Setpoint change"],
  ["key-estimate", "Estimate"],
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
interface Change extends SetpointChange {
  label: string;
  unit: string;
  zoneId?: number;
}
interface Lane {
  zone: Zone;
  bands: PhaseBand[];
  shots: Shot[];
  blocks: Block[];
  points: Reading[];
  threshold: Level[];
  changes: Change[];
  phase: string | null;
  since: number | null;
  /** In P2, the threshold the estimate dries down to. */
  target: number | null;
  next: NextShot;
  /** Why this zone is not being watered at all, if it is not. */
  stopped: string | null;
  p1Shots: number;
  p1Max: number | null;
  budget: number | null;
  litres: (seconds: number) => number | null;
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

/** The selected room's grow-day on one time axis: lights, each zone's phases, every shot, what held
 * a zone back and every setpoint change, as recorded; then a dashed estimate of the rest of the day.
 * The day is downloaded once when the page opens; live updates extend it from there. */
export function DayTimeline({ controller }: { controller: Controller }) {
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
          <span className="timeline-age" data-age={ageTone(age)}>
            {controller.demo ? "Demo data · " : ""}
            {age === null ? "Nothing recorded yet" : `Newest reading ${ageText(age)} old`}
          </span>
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
        <Timeline controller={controller} entities={entities} day={day} rows={rows} now={now} />
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
}: {
  controller: Controller;
  entities: ReturnType<typeof timelineEntities>;
  day: GrowDay;
  rows: TimelineRows;
  now: number;
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
  const read = (zone: Zone, key: string) => {
    // Like the controller: the zone's own setpoint when it has one, else the room's.
    const own = states[`number.crop_steering_${room.room.prefix}zone_${zone.id}_${key}`];
    return numeric(own ?? states[`number.crop_steering_${room.room.prefix}${key}`]);
  };
  const lanes = room.zones.map((zone): Lane => {
    const ids = entities.zones.find((item) => item.id === zone.id);
    const shots = valveShots(ids?.valve ? rows[ids.valve] : [], decisions, zone.id, day.start, now);
    const bands = alignBands(phaseBands(ids && rows[ids.phase], day.start, now), shots);
    const blocks = zoneBlocks(decisions, zone.id, day.start, now);
    const points = ids?.vwc ? readings(rows[ids.vwc], day.start, now) : [];
    const own = `number.crop_steering_${room.room.prefix}zone_${zone.id}_p2_vwc_threshold`;
    const thresholdId = states[own]
      ? own
      : `number.crop_steering_${room.room.prefix}p2_vwc_threshold`;
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
        ? "the controller is not reporting"
        : room.engine.enabled === false
          ? "the engine is off"
          : zone.enabled === false
            ? "zone scheduling is paused"
            : null;
    const ramp = phase === "P1" ? phaseTarget("p1_target_vwc") : null;
    const ceiling = ramp === null ? null : Math.min(ramp, read(zone, "field_capacity") ?? Infinity);
    const held = blocks.at(-1)?.open ? blocks.at(-1)! : null;
    return {
      zone,
      bands,
      shots,
      blocks,
      points,
      threshold: planned ? [] : levels(rows[thresholdId], day.start, now),
      changes: changes.filter((change) => change.zoneId === zone.id),
      phase,
      since,
      target,
      stopped,
      next: stopped
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
          ),
      p1Shots: shots.filter((shot) => (shot.phase ?? phaseAt(bands, shot.start)) === "P1").length,
      p1Max: water.p1_maximum_shots,
      budget: water.max_daily_volume,
      litres: (seconds) => estimateRuntime(flowInputs(water), seconds).requested?.zoneL ?? null,
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
  return (
    <div className="timeline-body" ref={box}>
      {width > 0 && (
        <>
          <Axis day={day} now={now} plot={plot} x={x} changes={roomChanges} strip={strip} />
          {lanes.map((lane) => (
            <div className="timeline-zone" key={lane.zone.id} data-zone={lane.zone.id}>
              <p className="timeline-zone-line">
                <strong>{lane.zone.name}</strong> <span>{summary(lane, day, now)}</span>
              </p>
              <LaneChart lane={lane} day={day} now={now} plot={plot} x={x} strip={strip} />
            </div>
          ))}
        </>
      )}
      <p className="timeline-detail" aria-live="polite">
        {hover ?? picked ?? "Point at or tap a phase, shot, hold or setpoint mark for its details."}
      </p>
      <ul className="timeline-legend" aria-label="Timeline key">
        {LEGEND.map(([key, name]) => (
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
}: {
  lane: Lane;
  day: GrowDay;
  now: number;
  plot: number;
  x: (time: number) => number;
  strip: Strip;
}) {
  const { zone, next, points, target } = lane;
  const name = zone.name;
  const fit = next.fit;
  const fitEnd = fit ? Math.min(fit.at, day.lightsOff) : null;
  const edge =
    fit && fitEnd !== null
      ? fit.from.value - (fit.rate * (fitEnd - fit.from.time)) / 3_600_000
      : null;
  // VWC is drawn over the day's own range, never 0-100 %.
  const values = points.length
    ? [
        ...points.map((point) => point.value),
        ...lane.threshold.map((level) => level.value),
        ...(target === null ? [] : [target]),
        ...(edge === null ? [] : [edge]),
      ]
    : [];
  const low = Math.min(...values),
    high = Math.max(...values);
  const pad = Math.max(0.3, (high - low) * 0.12);
  const min = low - pad,
    max = high + pad;
  const top = 24,
    area = 40;
  const y = (value: number) => top + area - ((value - min) / (max - min)) * area;
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
  const vwcAt = (time: number) => {
    if (time > now)
      return fit
        ? `Estimate · ${name} · VWC ${number(fit.from.value)} % falling ${number(fit.rate, 2)} %/h since the last shot settled${target === null ? "" : `, toward the ${number(target)} % P2 threshold`}`
        : `${name} · no VWC estimate: ${NO_ESTIMATE[next.basis] ?? "not enough to go on"}`;
    const point = nearest(time);
    const phase = point && phaseAt(lane.bands, point.time);
    return point
      ? `${clock(point.time)} · ${name} · VWC ${number(point.value, 2)} %${phase ? ` in ${phase}` : ""}`
      : `${name} · no VWC readings recorded today`;
  };
  const mark = markAt(x);
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
    ...lane.changes.map((change) =>
      mark(change.time, change.time, 18, 32, 0, () => changeText(change)),
    ),
    ...lane.shots.map((shot) => mark(shot.start, shot.end, 64, 88, 0, () => shotText(shot, lane))),
    ...lane.blocks.map((block) =>
      mark(block.start, block.end, 64, 88, 1, () => blockText(block, lane)),
    ),
  ];
  const at = next.at;
  const off = x(day.lightsOff);
  return (
    <svg
      className="timeline-lane"
      width={plot + 48}
      height={88}
      aria-hidden="true"
      {...strip(marks)}
    >
      <rect x={off} y={0} width={plot - off} height={88} className="night" />
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
          {lane.threshold.map((level, index) => (
            <line
              key={index}
              x1={x(level.start)}
              x2={x(level.end)}
              y1={y(level.value)}
              y2={y(level.value)}
              className="threshold"
            />
          ))}
          {target !== null && now < day.lightsOff && (
            <line
              x1={x(now)}
              x2={off}
              y1={y(target)}
              y2={y(target)}
              className="threshold projected"
            />
          )}
          <path d={path(points, x, y)} className="vwc-line" />
          {fit && fitEnd !== null && edge !== null && (
            <line
              x1={x(fit.from.time)}
              y1={y(fit.from.value)}
              x2={x(fitEnd)}
              y2={y(edge)}
              className="estimate"
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
      <line x1={x(now)} x2={x(now)} y1={0} y2={88} className="now-line" />
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
function summary(lane: Lane, day: GrowDay, now: number): string {
  const phase =
    !lane.phase || lane.since === null
      ? "phase unavailable"
      : lane.since <= day.start
        ? `${lane.phase} since before ${clock(day.start)}`
        : `${lane.phase} for ${duration(now - lane.since)}`;
  const used = lane.zone.water.value;
  const water =
    used === null
      ? "water today unavailable"
      : lane.budget === null
        ? `${number(used)} L today`
        : `${number(used)} of ${number(lane.budget)} L`;
  return [
    phase,
    `P1 shots ${lane.p1Shots} / ${lane.p1Max ?? "?"}`,
    water,
    nextText(lane, day),
  ].join(" · ");
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
