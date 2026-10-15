import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { LoaderCircle, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, number, time as clock } from "@/components/dashboard";
import { inPairs } from "@/components/day-timeline";
import { appendLive, duration, joinRows, type Level, type TimelineRows } from "@/lib/day-timeline";
import { numeric } from "@/lib/model";
import { rangeTicks, tickLabel } from "@/lib/tank-history";
import {
  LEVEL_RANGES,
  levelAt,
  recordWindows,
  shotMarks,
  tankEntities,
  tankRecord,
  type Run,
  type TankIds,
  type TankRecord,
  type TankShot,
} from "@/lib/tank-level";
import { tankTelemetry } from "@/lib/tank-telemetry";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";
import { estimateRuntime, flowInputs, waterParameters } from "@/lib/water-delivery";
import "./day-timeline.css";
import "./tank-history.css";
import "./tank-level.css";

const HOUR = 3_600_000;
type Request = { entityIds: string[]; attributeIds: string[] };

/** The room's tank record over a range: its grow-days read two at a time, as the zone charts read
 * theirs, then kept current by live updates (the demo's states are one moment: it is generated
 * whole). A new grow-day, range or mapping reads it again. */
function useTankRecord(
  controller: Controller,
  request: Request,
  hours: number,
  now: number,
  enabled: boolean,
) {
  const { room, states } = controller;
  const windows = recordWindows(
    numeric(states[`number.crop_steering_${room.room.prefix}lights_on_hour`]),
    numeric(states[`number.crop_steering_${room.room.prefix}lights_off_hour`]),
    hours,
    now,
  );
  const key = enabled
    ? [room.room.id, hours, windows[0].start, windows.at(-1)!.start, ...request.entityIds, "|"]
        .concat(request.attributeIds)
        .join(" ")
    : "";
  const ready = controller.connection === "live" || controller.connection === "demo";
  const demo = controller.demo;
  const [data, setData] = useState<{ key: string; rows: TimelineRows; at: number } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const latest = useRef({ windows, request, states });
  latest.current = { windows, request, states };
  const load = controller.timeline;
  useEffect(() => {
    const { windows, request } = latest.current;
    if (!key || !ready) return;
    let current = true;
    setError("");
    const at = Date.now();
    const { entityIds, attributeIds } = request;
    inPairs(windows.map((window) => () => load({ entityIds, attributeIds, ...window })))
      .then(joinRows)
      .then(
        (rows) => {
          if (current)
            setData({
              key,
              rows: demo ? rows : appendLive(rows, latest.current.states, request),
              at,
            });
        },
        (reason) => {
          if (current) setError(errorText(reason));
        },
      );
    return () => {
      current = false;
    };
  }, [key, ready, attempt, load, demo]);
  useEffect(() => {
    if (demo) return;
    setData((held) => {
      if (!held || held.key !== key) return held;
      const rows = appendLive(held.rows, states, latest.current.request);
      return rows === held.rows ? held : { ...held, rows };
    });
  }, [states, key, demo]);
  const current = data?.key === key ? data : null;
  return {
    rows: current?.rows ?? null,
    at: current?.at ?? null,
    error,
    ready,
    retry: () => setAttempt((value) => value + 1),
  };
}

/** The tank's level over a range beside what moved it: each zone's shots on the line, the pump's
 * runs and the tank filling above it, each recorded fill across it. */
export function TankLevel({
  controller,
  onConfigure,
}: {
  controller: Controller;
  onConfigure: () => void;
}) {
  const [, tick] = useState(0);
  useEffect(() => {
    // The range ends now, and moves on between live updates.
    const timer = window.setInterval(() => tick((value) => value + 1), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const [hours, setHours] = useState<number>(LEVEL_RANGES[0].hours);
  const now = Date.now();
  const read = tankEntities(controller.room, controller.states);
  const { level } = tankTelemetry(controller.states, controller.room.room);
  const charted = !!read.ids.level && level.unit === "%";
  const record = useTankRecord(controller, read, hours, now, charted);
  const mapSensors = (
    <Button variant="outline" onClick={onConfigure}>
      <Settings2 size={16} /> Map sensors
    </Button>
  );
  return (
    <section
      className="panel tank-level day-timeline"
      aria-labelledby="tank-level-title"
      data-tank-level-chart
    >
      <div className="panel-heading">
        <h2 id="tank-level-title">Tank level and watering</h2>
        <div className="tank-history-range" role="group" aria-label="Tank level range">
          {LEVEL_RANGES.map((option) => (
            <button
              type="button"
              key={option.hours}
              aria-pressed={hours === option.hours}
              onClick={() => setHours(option.hours)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <div className="timeline-body">
        {!level.entityId ? (
          <Empty
            title="No tank level is mapped"
            detail="Map the tank’s level sensor, a percentage, in Rooms & setup to chart it here with the shots, pump runs and fills."
            action={mapSensors}
          />
        ) : !read.ids.level ? (
          <Empty
            title="The tank level sensor is missing"
            detail={`Home Assistant has no ${level.entityId}.`}
            action={mapSensors}
          />
        ) : !charted ? (
          <Empty
            title="The tank level is not charted"
            detail={`${level.entityId} reports in “${level.unit}”, not %.`}
            action={mapSensors}
          />
        ) : record.error ? (
          <Empty
            title="The tank’s history could not load"
            detail={record.error}
            action={
              <Button variant="outline" onClick={record.retry}>
                Retry
              </Button>
            }
          />
        ) : !record.rows || record.at === null ? (
          <div className="chart-placeholder" role="status">
            <LoaderCircle className="spin" />
            {record.ready ? "Loading the tank’s recorded history…" : "Waiting for Home Assistant…"}
          </div>
        ) : (
          <LevelRecord
            controller={controller}
            ids={read.ids}
            rows={record.rows}
            at={record.at}
            hours={hours}
            now={now}
            mapSensors={mapSensors}
          />
        )}
      </div>
    </section>
  );
}

interface Texts {
  when: (time: number) => string;
  shot: (shot: TankShot) => string;
  run: (run: Run, what: string) => string;
  fill: (time: number) => string;
}

/** The range drawn, its key and its events in words, and what the chart can and cannot say. */
function LevelRecord({
  controller,
  ids,
  rows,
  at,
  hours,
  now,
  mapSensors,
}: {
  controller: Controller;
  ids: TankIds;
  rows: TimelineRows;
  at: number;
  hours: number;
  now: number;
  mapSensors: ReactNode;
}) {
  const start = now - hours * HOUR;
  const record = tankRecord(rows, ids, start, now);
  const range = LEVEL_RANGES.find((option) => option.hours === hours)?.label ?? `${hours} h`;
  const zones = controller.room.zones;
  const flows = new Map(
    zones.map((zone) => [zone.id, flowInputs(waterParameters(controller, zone.id))]),
  );
  const when = (time: number) =>
    hours <= 24
      ? clock(time)
      : `${new Date(time).toLocaleDateString([], { weekday: "short" })} ${clock(time)}`;
  const texts: Texts = {
    when,
    shot: (shot) => {
      const flow = flows.get(shot.zone);
      const litres = flow
        ? (estimateRuntime(flow, (shot.end - shot.start) / 1000).requested?.zoneL ?? null)
        : null;
      return [
        `${when(shot.start)}–${shot.open ? "now" : clock(shot.end)} · ${zones.find((zone) => zone.id === shot.zone)?.name ?? `Zone ${shot.zone}`}`,
        `${shot.phase ? `${shot.phase} shot` : "Shot"} ${duration(shot.end - shot.start)}${shot.open ? " so far" : ""}${litres === null ? "" : `, ≈${number(litres)} L at the configured flow`}`,
        ...(shot.reason ? [shot.reason] : []),
      ].join("\n");
    },
    run: (run, what) =>
      `${when(run.start)}–${run.open ? "now" : clock(run.end)} · ${what} ${duration(run.end - run.start)}${run.open ? " so far" : ""}`,
    fill: (time) => `${when(time)} · Recorded fill`,
  };
  const events = [
    ...record.shots.map((shot) => ({ time: shot.start, text: texts.shot(shot) })),
    ...record.pump.map((run) => ({ time: run.start, text: texts.run(run, "Pump on") })),
    ...record.filling.map((run) => ({ time: run.start, text: texts.run(run, "Filling") })),
    ...record.fills.map((time) => ({ time, text: texts.fill(time) })),
  ].sort((a, b) => b.time - a.time);
  const values = record.level.map((step) => step.value);
  const counts = [
    `${record.shots.length} ${record.shots.length === 1 ? "shot" : "shots"}`,
    ...(ids.pump
      ? [`pump on ${duration(record.pump.reduce((sum, run) => sum + run.end - run.start, 0))}`]
      : []),
    ...(ids.fill
      ? [`${record.fills.length} recorded ${record.fills.length === 1 ? "fill" : "fills"}`]
      : []),
  ];
  const summary = `Tank level over the last ${range}: ${
    values.length
      ? `latest ${number(values.at(-1)!)}%, lowest ${number(Math.min(...values))}%, highest ${number(Math.max(...values))}%`
      : "no readings"
  }. ${counts.join(", ")}.`;
  const missing = [
    ids.pump ? null : "the pump",
    ids.filling ? null : "the tank filling status",
    ids.fill ? null : "the last recorded fill",
  ].filter((item): item is string => item !== null);
  const connected = ["live", "demo"].includes(controller.connection);
  return (
    <>
      <LevelChart
        record={record}
        ids={ids}
        start={start}
        end={now}
        hours={hours}
        summary={summary}
        texts={texts}
      />
      <div className="grow-foot">
        <ul className="grow-legend" aria-label="Chart key">
          <li title="What the mapped level sensor reported, held until its next reading">
            <i className="key-level" aria-hidden="true" />
            Tank level
          </li>
          {ids.valves.length > 0 && (
            <li title="A zone valve opening, on the level line where it opened">
              <i className="key-shot" aria-hidden="true" />
              Shot
            </li>
          )}
          {ids.pump && (
            <li title="The pump switch’s own report, not measured flow">
              <i className="key-pump" aria-hidden="true" />
              Pump on
            </li>
          )}
          {ids.filling && (
            <li title="The tank filling status mapped for this room">
              <i className="key-filling" aria-hidden="true" />
              Filling
            </li>
          )}
          {ids.fill && (
            <li title="A newer time on the last-fill record">
              <i className="key-fill" aria-hidden="true" />
              Recorded fill
            </li>
          )}
        </ul>
        <details className="timeline-events">
          <summary>{counts.join(" · ")}</summary>
          {events.length ? (
            <ol>
              {events.map((event, index) => (
                <li key={index}>{event.text.replaceAll("\n", " · ")}</li>
              ))}
            </ol>
          ) : (
            <p>Nothing recorded in this range.</p>
          )}
        </details>
      </div>
      {missing.length > 0 && (
        <p className="tank-history-note">
          Not drawn: {missing.join(", ")} (not mapped, or missing from Home Assistant).
          {mapSensors}
        </p>
      )}
      <p className="tank-level-note">
        Level is what the mapped sensor reports: this page cannot tell whether that sensor measures
        the water or works it out, for example from pump run time since the last fill. Shots are
        valve open times, with litres at the configured flow, not measured.
      </p>
      {!connected && (
        <p className="tank-history-note tank-history-stale" role="status">
          Disconnected: showing the history loaded at {clock(at)}.
        </p>
      )}
      <p className="tank-history-caption">
        {controller.demo ? "Generated demo history" : "Home Assistant recorder history"} · loaded{" "}
        {clock(at)}
        {connected && !controller.demo ? " · updates live" : ""}
      </p>
    </>
  );
}

interface Hit {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  /** Lower ranks win: the small marks first, with a wider touch target. */
  rank: number;
  text: (time: number) => string;
}
interface Tip {
  text: string;
  x: number;
  y: number;
  pinned: boolean;
}
const diamond = (cx: number, cy: number) =>
  `M${cx} ${cy - 4.5}L${cx + 4.5} ${cy}L${cx} ${cy + 4.5}L${cx - 4.5} ${cy}Z`;

/** The chart at the width it has: the pump and filling strips on top, the level under them with
 * its shots on it, each recorded fill a dashed line. Hover or tap says what is there. */
function LevelChart({
  record,
  ids,
  start,
  end,
  hours,
  summary,
  texts,
}: {
  record: TankRecord;
  ids: TankIds;
  start: number;
  end: number;
  hours: number;
  summary: string;
  texts: Texts;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [tip, setTip] = useState<Tip | null>(null);
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
  const L = 40,
    R = 12,
    STRIP = 8,
    ROW = 17;
  const strips = [
    ...(ids.pump ? [{ key: "pump", label: "Pump", what: "Pump on", runs: record.pump }] : []),
    ...(ids.filling || ids.fill
      ? [{ key: "filling", label: "Fill", what: "Filling", runs: record.filling }]
      : []),
  ];
  const fillRow = strips.findIndex((strip) => strip.key === "filling");
  const TOP = strips.length * ROW + 14,
    H = width < 420 ? 150 : 210;
  const bottom = TOP + H,
    height = bottom + 22;
  const plotW = Math.max(100, width - L - R);
  const x = (time: number) => L + Math.max(0, Math.min(1, (time - start) / (end - start))) * plotW;
  const timeAt = (px: number) => start + ((px - L) / plotW) * (end - start);
  const y = (value: number) => bottom - (value / 100) * H;
  const f = (value: number) => value.toFixed(1);
  // The level as steps, flat until its next reading; a gap where there was none.
  const runs: Level[][] = [];
  for (const step of record.level) {
    const run = runs.at(-1);
    if (run && run.at(-1)!.end === step.start) run.push(step);
    else runs.push([step]);
  }
  const line = runs
    .map(
      (run) =>
        `M${f(x(run[0].start))} ${f(y(run[0].value))}` +
        run
          .map((step, index) => `${index ? `V${f(y(step.value))}` : ""}H${f(x(step.end))}`)
          .join(""),
    )
    .join("");
  const area = runs
    .map(
      (run) =>
        `M${f(x(run[0].start))} ${f(bottom)}` +
        run.map((step) => `V${f(y(step.value))}H${f(x(step.end))}`).join("") +
        `V${f(bottom)}Z`,
    )
    .join("");
  // Shots too close to tell apart share a mark, on the line where the first one opened.
  const marks = shotMarks(record.shots, record.level, (8 / plotW) * (end - start)).map((mark) => ({
    ...mark,
    cx: x(mark.time),
    cy: mark.level === null ? bottom - 6 : y(mark.level),
  }));
  const ticks = rangeTicks(start, end, hours);
  const every = Math.max(1, Math.ceil((ticks.length * 58) / plotW));
  const inside = (list: Run[], time: number) =>
    list.some((run) => run.start <= time && time <= run.end);
  const hits: Hit[] = [
    ...marks.map((mark) => ({
      x0: mark.cx - 6,
      x1: mark.cx + 6,
      y0: mark.cy - 8,
      y1: mark.cy + 8,
      rank: 0,
      text: () =>
        [
          ...mark.shots.slice(0, 4).map(texts.shot),
          ...(mark.shots.length > 4 ? [`and ${mark.shots.length - 4} more shots`] : []),
        ].join("\n\n"),
    })),
    ...record.fills.map((time) => ({
      x0: x(time) - 6,
      x1: x(time) + 6,
      y0: 0,
      y1: bottom,
      rank: 1,
      text: () => texts.fill(time),
    })),
    ...strips.flatMap((strip, row) =>
      strip.runs.map((run) => ({
        x0: x(run.start) - 3,
        x1: Math.max(x(run.end), x(run.start) + 1) + 3,
        y0: row * ROW - 3,
        y1: row * ROW + STRIP + 3,
        rank: 2,
        text: () => texts.run(run, strip.what),
      })),
    ),
    {
      x0: L,
      x1: L + plotW,
      y0: TOP,
      y1: bottom,
      rank: 4,
      text: (time) => {
        const value = levelAt(record.level, time);
        return [
          `${texts.when(time)} · ${value === null ? "No level reading then" : `Tank level ${number(value)}%`}`,
          ...(inside(record.pump, time) ? ["Pump on"] : []),
          ...(inside(record.filling, time) ? ["Filling"] : []),
        ].join("\n");
      },
    },
  ];
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
  return (
    <div className="grow-chart" ref={box}>
      {width > 0 && (
        <svg
          className="grow-svg tank-level-svg"
          width={width}
          height={height}
          role="img"
          aria-label={summary}
          onPointerMove={(event) => {
            if (event.pointerType !== "mouse") return;
            const found = find(event);
            setTip((held) => (held?.pinned ? held : found && { ...found, pinned: false }));
          }}
          onPointerLeave={() => setTip((held) => (held?.pinned ? held : null))}
          onClick={(event) => {
            const found = find(event);
            setTip(found && { ...found, pinned: true });
          }}
        >
          {strips.map((strip, row) => (
            <g key={strip.key} data-strip={strip.key}>
              <text x={L - 6} y={row * ROW + STRIP + 1} className="axis-label" textAnchor="end">
                {strip.label}
              </text>
              <rect
                x={L}
                y={row * ROW}
                width={plotW}
                height={STRIP}
                rx={STRIP / 2}
                className="level-track"
              />
              {strip.runs.map((run) => (
                <rect
                  key={run.start}
                  x={x(run.start)}
                  y={row * ROW}
                  width={Math.max(1.5, x(run.end) - x(run.start))}
                  height={STRIP}
                  rx={1}
                  className="level-run"
                  data-run={strip.key}
                />
              ))}
            </g>
          ))}
          {[0, 25, 50, 75, 100].map((value) => (
            <g key={value}>
              <line x1={L} x2={L + plotW} y1={y(value)} y2={y(value)} className="grid" />
              <text x={L - 6} y={y(value) + 4} className="axis-label" textAnchor="end">
                {value}%
              </text>
            </g>
          ))}
          <path d={area} className="level-area" />
          {record.fills.map((time) => (
            <g key={time} data-fill={new Date(time).toISOString()}>
              <line
                x1={x(time)}
                x2={x(time)}
                y1={fillRow * ROW + STRIP + 2}
                y2={bottom}
                className="level-fill-line"
              />
              <path d={diamond(x(time), fillRow * ROW + STRIP / 2)} className="level-fill-mark" />
            </g>
          ))}
          <path d={line} className="level-line" data-layer="level" />
          {!record.level.length && (
            <text x={L + 8} y={TOP + H / 2} className="axis-label">
              No level readings in this range
            </text>
          )}
          <g data-layer="shots">
            {marks.map((mark) => (
              <circle
                key={mark.time}
                cx={mark.cx}
                cy={mark.cy}
                r={3 + Math.min(1.5, (mark.shots.length - 1) * 0.5)}
                className="shot-dot"
              />
            ))}
          </g>
          {ticks.map(
            (time, index) =>
              index % every === 0 && (
                <text
                  key={time}
                  x={x(time)}
                  y={height - 3}
                  className="axis-label"
                  textAnchor={x(time) > L + plotW - 28 ? "end" : "middle"}
                >
                  {tickLabel(time, hours)}
                </text>
              ),
          )}
        </svg>
      )}
      <div
        className="grow-tip"
        role="status"
        aria-live="polite"
        hidden={!tip}
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
    </div>
  );
}
