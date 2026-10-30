import { useProbeComparisons } from "@/lib/probe-history";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Check, CircleAlert, Download, LoaderCircle, Plus, SlidersHorizontal } from "lucide-react";
import {
  Area,
  Brush,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { InfoTip } from "@/components/info-tip";
import { NeedsIntegration } from "@/components/needs-integration";
import { ShotTimeline } from "@/components/shot-timeline";
import type { RunRecord, RunsDocument } from "@/lib/comparison-types";
import { growDay, phaseBands, valveShots, type TimelineRequest, type TimelineRow, type TimelineRows } from "@/lib/day-timeline";
import { formatEc, formatTemp } from "@/lib/display-units";

import {
  alignGrid,
  chartNotes,
  chunks,
  defaultExplorerSeries,
  EXPLORER_COPY,
  EXPLORER_RANGES,
  explorerCsv,
  explorerRangeText,
  explorerSensors,
  explorerSeries,
  explorerSpan,
  inDisplayUnits,
  loadExplorerEvents,
  phaseLane,
  pickRuns,
  PRESETS,
  previousWindow,
  readChoice,
  readExplorerChoice,
  resolveRange,
  runDayAt,
  SeriesGrid,
  stepFor,
  UNIT_DIGITS,
  writeChoice,
  writeExplorerChoice,
  type ChartNote,
  type Choice,
  type ExplorerChoice,
  type ExplorerEvents,
  type ExplorerSensor,
  type ExplorerSeries,
  type NoteReading,
  type PhaseSegment,
  type PreviousWindow,
  type Span,
  type Unit,
} from "@/lib/history-explorer";
import { numeric } from "@/lib/model";
import { demoExplorerTimeline } from "@/lib/parity-demo/history";
import type { TimelineBlock as ShotBlock, TimelineRow as ShotRow } from "@/lib/shot-timeline";
import { readProjection } from "@/lib/strategy-review";
import { levelLines } from "@/lib/tank-level";
import { clock, dayKey, dayLabel, hourTicks, startOfDay } from "@/lib/time";
import { roomView } from "@/lib/today-room";
import { tableShotLog } from "@/lib/zone-shot-log";
import type { GrowDay } from "@/lib/grows";
import type { Controller, States, Zone } from "@/lib/types";
import { errorText } from "@/lib/utils";
import { useNarrow } from "@/lib/use-narrow";
import "./history-explorer.css";

const PHASE_FILL: Record<string, string> = {
  P0: "#6b7580",
  P1: "#2f6fb5",
  P2: "#6450b0",
  P3: "#34405a",
};

interface Loaded {
  key: string;
  values: Map<string, (number | null)[]>;
  rows: Map<string, TimelineRow[]>;
}
/** Recorded history of `ids` over `span` on a grid of `step`, a day at a time, two at a time. A
 * sensor ticked later is read alone; a new range reads everything again. `raw` keeps the rows of
 * a few event entities (valves, phase) as they are. */
export function useGrids(
  controller: Controller,
  ids: string[],
  raw: string[],
  span: Span | null,
  step: number,
  /** Where the rows come from: Home Assistant's recorder (the default), or the demo's own day. */
  read: (request: TimelineRequest) => Promise<TimelineRows> = controller.timeline,
) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [busy, setBusy] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState("");
  const [loads, setLoads] = useState(0);
  const cache = useRef<Loaded | null>(null);
  const spanKey = span ? `${span.start}|${span.end}|${step}|${controller.roomId}` : "";
  const idKey = [...ids, "|", ...raw].join(",");
  useEffect(() => {
    if (!span) return;
    if (cache.current?.key !== spanKey)
      cache.current = { key: spanKey, values: new Map(), rows: new Map() };
    const held = cache.current;
    const wanted = [...new Set(ids)].filter((id) => !held.values.has(id));
    const events = [...new Set(raw)].filter((id) => !held.rows.has(id));
    setLoaded({ ...held });
    if (!wanted.length && !events.length) return;
    let cancelled = false;
    const grids = new Map(wanted.map((id) => [id, new SeriesGrid(span.start, span.end, step)]));
    const rows = new Map(events.map((id) => [id, [] as TimelineRow[]]));
    const days = chunks(span);
    let next = 0,
      done = 0,
      failure = "";
    setBusy({ done: 0, total: days.length });
    setError("");
    const worker = async () => {
      while (next < days.length && !cancelled && !failure) {
        const day = days[next++];
        try {
          const result = await read({
            entityIds: [...new Set([...wanted, ...events])],
            attributeIds: [],
            ...day,
          });
          if (cancelled) return;
          for (const [id, grid] of grids) grid.add(result[id] ?? []);
          for (const [id, list] of rows) list.push(...(result[id] ?? []));
          setBusy({ done: ++done, total: days.length });
        } catch (problem) {
          failure = errorText(problem);
        }
      }
    };
    void Promise.all([worker(), worker()]).then(() => {
      if (cancelled) return;
      if (failure) setError(failure);
      else {
        for (const [id, grid] of grids) held.values.set(id, grid.values());
        for (const [id, list] of rows)
          held.rows.set(
            id,
            [...new Map(list.map((row) => [row.time, row])).values()].sort(
              (a, b) => a.time - b.time,
            ),
          );
        setLoaded({ ...held });
        setLoads((count) => count + 1);
      }
      setBusy(null);
    });
    return () => {
      cancelled = true;
      setBusy(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spanKey, idKey, controller.connection]);
  return {
    values: loaded?.key === spanKey ? loaded.values : new Map<string, (number | null)[]>(),
    rows: loaded?.key === spanKey ? loaded.rows : new Map<string, TimelineRow[]>(),
    busy,
    error,
    loads,
  };
}

/** History’s recorded zone explorer: a range, any sensor of the room, the zone's phases and the
 * room's shots, and the previous run at the same grow days. */
export function HistoryExplorer({ controller, zone }: { controller: Controller; zone: Zone }) {
  const { room, states, timeZone } = controller;
  const [choice, setChoiceState] = useState<Choice>(() =>
    readChoice(typeof window === "undefined" ? "" : window.location.hash),
  );
  const [now, setNow] = useState(() => Date.now());
  const [runs, setRuns] = useState<RunRecord[] | null>(null);
  const [sheet, setSheet] = useState(false);
  const narrow = useNarrow();
  const connected = ["live", "demo"].includes(controller.connection);
  function setChoice(next: Partial<Choice>) {
    const merged = { ...choice, ...next };
    if (next.preset || next.from !== undefined) setNow(Date.now());
    setChoiceState(merged);
    try {
      window.history.replaceState(null, "", writeChoice(window.location.hash, merged));
    } catch {
      /* A sandboxed frame keeps the choice in the page only. */
    }
  }
  useEffect(() => {
    if (!connected) return;
    let current = true;
    controller
      .operator<RunsDocument>("runs_get")
      .then((doc) => current && setRuns(doc.runs))
      .catch(() => current && setRuns([]));
    return () => {
      current = false;
    };
  }, [controller.roomId, connected]);
  const sensors = useMemo(
    () => explorerSensors(room, states),
    // The list changes with the room's mapping, not with every reading.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [room.room.id, Object.keys(states).length, room.zones.map((z) => z.vwc.entityId).join()],
  );
  const own = [zone.vwc.entityId, zone.ec.entityId].filter(
    (id): id is string => !!id && sensors.some((sensor) => sensor.entityId === id),
  );
  const ticked = (choice.sensors ?? own).filter((id) =>
    sensors.some((sensor) => sensor.entityId === id),
  );
  const visible = sensors.filter((sensor) => ticked.includes(sensor.entityId));
  const { current: run, previous: last } = pickRuns(runs ?? []);
  // The grow compared with: the one picked, else the last one before this grow.
  const previous =
    (choice.compareRun &&
      (runs ?? []).find((r) => r.id === choice.compareRun && r.id !== run?.id)) ||
    last;
  const others = (runs ?? []).filter((r) => !r.archived && r.id !== run?.id);
  const prefix = room.room.prefix;
  const hour = (key: string) => numeric(states[`number.crop_steering_${prefix}lights_${key}_hour`]);
  const span = resolveRange(choice, {
    now,
    timeZone,
    lightsOn: hour("on"),
    lightsOff: hour("off"),
    run,
  });
  const step = span ? stepFor(span.end - span.start) : 60_000;
  // Shots of each zone that has a ticked sensor, and of this zone; this zone's phases.
  const shotZones = room.zones.filter(
    (item) => item.id === zone.id || visible.some((sensor) => sensor.zone === item.id),
  );
  const phaseId = `sensor.crop_steering_${prefix}zone_${zone.id}_phase`;
  const events = [
    ...(choice.shots
      ? shotZones.flatMap((item) => (item.valveEntity ? [item.valveEntity] : []))
      : []),
    ...(choice.phases && states[phaseId] ? [phaseId] : []),
  ];
  const recorded = useGrids(controller, ticked, events, connected ? span : null, step);
  // The previous run at the same grow days, on the ids it recorded for a zone's readings.
  const previousSpan =
    choice.compare && span && run && previous
      ? previousWindow(run, previous, span.start, span.end, now)
      : null;
  const comparisons = useProbeComparisons(
    controller,
    visible,
    sensors,
    choice,
    run,
    last,
    runs ?? [],
    span,
    step,
  );
  const before = {
    busy: comparisons.busy ? { done: comparisons.rows.size, total: visible.length } : null,
    error: "",
    loads: comparisons.rows,
    values: new Map(),
  };
  const summaries: GrowDay[] = [];
  const comparing =
    choice.compare || Object.values(choice.probeCompare ?? {}).some((id) => id !== "off");
  const grid = span ? new SeriesGrid(span.start, span.end, step) : null;
  const data = useMemo(() => {
    if (!grid || !span) return [];
    const rows: Record<string, number | null>[] = Array.from(
      { length: grid.length },
      (_, index) => ({
        t: grid.timeAt(index),
      }),
    );
    visible.forEach((sensor, index) => {
      const values = recorded.values.get(sensor.entityId);
      if (values) values.forEach((value, at) => (rows[at][`s${index}`] = value));
      const overlay = comparisons.rows.get(sensor.entityId);
      if (overlay)
        overlay.values.forEach((value, at) => {
          rows[at][`p${index}`] = value;
          rows[at][`pl${index}`] = overlay.low[at];
          rows[at][`ph${index}`] = overlay.high[at];
        });
    });
    return rows;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    // The loaded maps fill in place: their load counts say when.
    recorded.values,
    recorded.loads,
    comparisons.rows,
    summaries,
    previousSpan?.start,
    comparing,
    run?.id,
    previous?.id,
    visible.map((s) => s.entityId).join(),
    span?.start,
    span?.end,
    step,
  ]);
  const bands =
    span && choice.phases ? phaseBands(recorded.rows.get(phaseId), span.start, span.end) : [];
  const shots =
    span && choice.shots
      ? shotZones.flatMap((item) => {
          const color =
            visible.find((sensor) => sensor.zone === item.id)?.color ?? "var(--muted-foreground)";
          const seen = new Set<number>();
          return valveShots(
            item.valveEntity ? recorded.rows.get(item.valveEntity) : [],
            [],
            item.id,
            span.start,
            span.end,
          ).flatMap((shot) => {
            const slot = Math.floor((shot.start - span.start) / step);
            if (seen.has(slot)) return [];
            seen.add(slot);
            return [{ t: shot.start, y: 0.03, zone: item.name, color }];
          });
        })
      : [];
  const units = [...new Set(visible.map((sensor) => sensor.unit))];
  const hasPrevious = data.some((row) =>
    Object.keys(row).some((key) => key[0] === "p" && row[key] !== null),
  );
  const format = useMemo(() => tickFormat(span, timeZone), [span?.start, span?.end, timeZone]);
  const controls = (
    <Controls
      choice={choice}
      setChoice={setChoice}
      sensors={sensors}
      ticked={ticked}
      span={span}
      runName={run?.name ?? null}
      hasPrevious={!!previous}
      others={others}
      matches={comparisons.rows}
    />
  );
  const compareNote = !choice.compare
    ? null
    : runs === null
      ? "Reading the runs of this room…"
      : !run || !previous
        ? "No previous run is recorded for this room. Record runs in History › Compare runs."
        : !previousSpan
          ? "The previous run has no data for these grow days."
          : before.busy
            ? null
            : before.error
              ? `The previous run did not load: ${before.error}`
              : !hasPrevious
                ? `No recorded data in run ${previous.name} for days ${previousSpan.firstDay}–${previousSpan.lastDay}.`
                : null;
  return (
    <section
      className="panel history-explorer"
      aria-labelledby="history-explorer-title"
      data-history-explorer
      data-range-start={span?.start}
      data-range-end={span?.end}
      data-explorer-loads={recorded.loads}
      data-explorer-series={visible.length}
      data-compare-days={
        previousSpan ? `${previousSpan.firstDay}-${previousSpan.lastDay}` : undefined
      }
      data-compare-start={previousSpan?.start}
    >
      <div className="panel-heading">
        <div>
          <div className="label-with-tip">
            <h2 id="history-explorer-title">History explorer</h2>
            <InfoTip label={EXPLORER_COPY.explorer.label} copy={EXPLORER_COPY.explorer.copy} />
          </div>
          <p>{span ? rangeText(span, timeZone) : "Set a valid range"}</p>
        </div>
        {narrow && (
          <Button variant="outline" size="sm" onClick={() => setSheet(true)}>
            <SlidersHorizontal size={15} aria-hidden="true" /> Range and sensors
          </Button>
        )}
      </div>
      {narrow ? (
        <Sheet open={sheet} onOpenChange={setSheet}>
          <SheetContent side="bottom" className="history-explorer-sheet">
            <SheetHeader>
              <SheetTitle>Range and sensors</SheetTitle>
              <SheetDescription>The chart changes when you change a setting.</SheetDescription>
            </SheetHeader>
            {controls}
          </SheetContent>
        </Sheet>
      ) : null}
      <div className="history-explorer-body">
        {!narrow && controls}
        <div className="history-explorer-chart">
          {!connected ? (
            <p className="muted small">Recorded history loads while Home Assistant is connected.</p>
          ) : !span ? (
            <p className="muted small">The end of the range must be after its start.</p>
          ) : (
            <>
              <Legend
                visible={visible}
                units={units}
                previous={
                  comparing && hasPrevious && Object.keys(choice.probeCompare ?? {}).length
                    ? "Probe comparisons — grows and sources listed below"
                    : choice.compare && hasPrevious && previous && previousSpan
                      ? `Run ${previous.name}, days ${previousSpan.firstDay}–${previousSpan.lastDay}`
                      : null
                }
                shots={shots.length > 0}
                phases={bands.length > 0}
              />
              {comparisons.rows.size > 0 && (
                <ul className="history-explorer-sources" aria-label="Compared probe sources">
                  {[...comparisons.rows].map(([id, overlay]) => (
                    <li key={id} data-probe-source={id}>
                      {sensors.find((sensor) => sensor.entityId === id)?.label}: {overlay.grow.name}{" "}
                      — {overlay.error || overlay.sources.join("; ")}
                      {overlay.sources.some((source) => source !== "recorded history") &&
                        " (min/max band)"}
                    </li>
                  ))}
                </ul>
              )}
              {compareNote && (
                <p className="history-explorer-note" role="status" data-compare-note>
                  {compareNote}
                </p>
              )}
              {recorded.error ? (
                <p className="history-explorer-note" role="alert">
                  History did not load: {recorded.error}
                </p>
              ) : !visible.length ? (
                <p className="muted small">Select one or more sensors to show their history.</p>
              ) : (
                <div
                  className="history-explorer-scroll"
                  role="group"
                  tabIndex={0}
                  aria-label={`History chart: ${visible.map((sensor) => sensor.label).join(", ")}, ${span ? rangeText(span, timeZone) : ""}${choice.compare && hasPrevious && previous ? `, with run ${previous.name} as dashed lines` : ""}. Use the arrow keys to move along the chart.`}
                >
                  <div className="history-explorer-plot">
                    {(recorded.busy || before.busy) && (
                      <div className="history-explorer-busy" role="status">
                        <LoaderCircle className="spin" size={16} aria-hidden="true" />
                        Loading day {(recorded.busy ?? before.busy)!.done + 1} of{" "}
                        {(recorded.busy ?? before.busy)!.total}
                      </div>
                    )}
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={data} margin={{ top: 22, right: 4, bottom: 4, left: 4 }}>
                        <CartesianGrid
                          strokeDasharray="3 5"
                          vertical={false}
                          stroke="var(--border)"
                        />
                        <XAxis
                          dataKey="t"
                          type="number"
                          scale="time"
                          domain={["dataMin", "dataMax"]}
                          tickFormatter={format}
                          minTickGap={60}
                          tickLine={false}
                          axisLine={false}
                          stroke="var(--muted-foreground)"
                        />
                        {units.map((unit, index) => (
                          <YAxis
                            key={unit}
                            yAxisId={`axis-${index}`}
                            orientation={index % 2 ? "right" : "left"}
                            domain={["auto", "auto"]}
                            width={42}
                            tickCount={5}
                            tickFormatter={(value) =>
                              Number(value).toFixed(UNIT_DIGITS[unit] > 1 ? 1 : 0)
                            }
                            tickLine={false}
                            axisLine={false}
                            stroke="var(--muted-foreground)"
                            label={{
                              value: unit,
                              position: "top",
                              offset: 8,
                              fill: "var(--muted-foreground)",
                              fontSize: 12,
                            }}
                          />
                        ))}
                        <YAxis yAxisId="events" hide domain={[0, 1]} />
                        {bands.map((band) => (
                          <ReferenceArea
                            key={`${band.phase}-${band.start}`}
                            yAxisId="events"
                            x1={band.start}
                            x2={band.end}
                            y1={0}
                            y2={1}
                            fill={PHASE_FILL[band.phase]}
                            fillOpacity={0.1}
                            stroke="none"
                            ifOverflow="hidden"
                          />
                        ))}
                        <Tooltip
                          content={(props) => (
                            <ExplorerTooltip
                              row={props.active ? (props.payload?.[0]?.payload as Row) : undefined}
                              visible={visible}
                              compare={comparing && hasPrevious}
                              bands={bands}
                              timeZone={timeZone}
                            />
                          )}
                        />
                        {visible.map((sensor, index) => (
                          <Line
                            key={sensor.entityId}
                            dataKey={`s${index}`}
                            name={sensor.label}
                            yAxisId={`axis-${units.indexOf(sensor.unit)}`}
                            type="linear"
                            stroke={sensor.color}
                            strokeWidth={1.8}
                            dot={false}
                            connectNulls={false}
                            isAnimationActive={false}
                          />
                        ))}
                        {comparing &&
                          visible.map((sensor, index) => (
                            <Line
                              key={`previous-${sensor.entityId}`}
                              dataKey={`p${index}`}
                              name={`${sensor.label} (previous run)`}
                              yAxisId={`axis-${units.indexOf(sensor.unit)}`}
                              type="linear"
                              stroke={sensor.color}
                              strokeOpacity={0.55}
                              strokeDasharray="5 4"
                              strokeWidth={1.5}
                              dot={false}
                              connectNulls={false}
                              isAnimationActive={false}
                              className="history-explorer-previous"
                            />
                          ))}
                        {comparing &&
                          visible.map((sensor, index) => (
                            <Area
                              key={`band-${sensor.entityId}`}
                              dataKey={(row: Row) =>
                                row[`pl${index}`] == null || row[`ph${index}`] == null
                                  ? null
                                  : [row[`pl${index}`], row[`ph${index}`]]
                              }
                              yAxisId={`axis-${units.indexOf(sensor.unit)}`}
                              stroke="none"
                              fill={sensor.color}
                              fillOpacity={0.12}
                              connectNulls={false}
                              isAnimationActive={false}
                              name={`${sensor.label} historical min/max`}
                            />
                          ))}
                        {shots.length > 0 && (
                          <Scatter
                            data={shots}
                            dataKey="y"
                            yAxisId="events"
                            name="Shots"
                            isAnimationActive={false}
                            shape={(props: {
                              cx?: number;
                              cy?: number;
                              payload?: { color: string };
                            }) => (
                              <path
                                d={`M${(props.cx ?? 0) - 4},${(props.cy ?? 0) + 3}L${props.cx},${(props.cy ?? 0) - 5}L${(props.cx ?? 0) + 4},${(props.cy ?? 0) + 3}Z`}
                                fill={props.payload?.color}
                                className="history-explorer-shot"
                              />
                            )}
                          />
                        )}
                        {data.length > 60 && (
                          <Brush
                            dataKey="t"
                            height={22}
                            travellerWidth={8}
                            stroke="var(--muted-foreground)"
                            fill="var(--surface)"
                            tickFormatter={format}
                          />
                        )}
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

type Row = Record<string, number | null>;

function Controls({
  choice,
  setChoice,
  sensors,
  ticked,
  span,
  runName,
  hasPrevious,
  others = [],
  matches,
}: {
  choice: Choice;
  setChoice: (next: Partial<Choice>) => void;
  sensors: ExplorerSensor[];
  ticked: string[];
  span: Span | null;
  runName: string | null;
  hasPrevious: boolean;
  /** The grows that can be compared with (every run but this one). */
  others?: RunRecord[];
  matches: ReturnType<typeof useProbeComparisons>["rows"];
}) {
  const [from, setFrom] = useState(() => localInput(choice.from ?? span?.start ?? Date.now()));
  const [to, setTo] = useState(() => localInput(choice.to ?? span?.end ?? Date.now()));
  const [custom, setCustom] = useState(choice.preset === "custom");
  const groups = [...new Set(sensors.map((sensor) => sensor.group))];
  const toggle = (ids: string[], on: boolean) =>
    setChoice({
      sensors: on ? [...new Set([...ticked, ...ids])] : ticked.filter((id) => !ids.includes(id)),
    });
  const kind = (k: ExplorerSensor["kind"]) =>
    sensors.filter((sensor) => sensor.kind === k).map((sensor) => sensor.entityId);
  const all = (ids: string[]) => ids.length > 0 && ids.every((id) => ticked.includes(id));
  return (
    <div className="history-explorer-controls">
      <fieldset className="history-explorer-range">
        <legend>
          <span className="label-with-tip">
            Range <InfoTip label={EXPLORER_COPY.range.label} copy={EXPLORER_COPY.range.copy} />
          </span>
        </legend>
        <div className="history-toggle" role="group" aria-label="Range">
          {PRESETS.map((preset) => (
            <button
              type="button"
              key={preset.id}
              aria-pressed={choice.preset === preset.id}
              data-preset={preset.id}
              title={
                preset.id === "run" && runName
                  ? `From lights-on of the first day of ${runName}`
                  : undefined
              }
              onClick={() => {
                setCustom(false);
                setChoice({ preset: preset.id, from: null, to: null });
              }}
            >
              {preset.label}
            </button>
          ))}
          <button
            type="button"
            aria-pressed={choice.preset === "custom" || custom}
            aria-expanded={custom}
            data-preset="custom"
            onClick={() => setCustom((open) => !open)}
          >
            Custom
          </button>
        </div>
        {custom && (
          <form
            className="history-explorer-custom"
            onSubmit={(event) => {
              event.preventDefault();
              const start = Date.parse(from),
                end = Date.parse(to);
              if (Number.isFinite(start) && Number.isFinite(end) && end > start)
                setChoice({ preset: "custom", from: start, to: end });
            }}
          >
            <label>
              From
              <input
                type="datetime-local"
                value={from}
                max={to}
                onChange={(event) => setFrom(event.target.value)}
                required
              />
            </label>
            <label>
              To
              <input
                type="datetime-local"
                value={to}
                min={from}
                onChange={(event) => setTo(event.target.value)}
                required
              />
            </label>
            <Button
              type="submit"
              size="sm"
              variant="outline"
              disabled={!(Date.parse(to) > Date.parse(from))}
            >
              Show
            </Button>
          </form>
        )}
      </fieldset>
      <fieldset className="history-explorer-options">
        <legend>Overlays</legend>
        <label className="history-explorer-check">
          <input
            type="checkbox"
            checked={choice.compare}
            onChange={(event) => setChoice({ compare: event.target.checked })}
            data-compare-toggle
          />
          Compare with previous run
          <InfoTip label={EXPLORER_COPY.compare.label} copy={EXPLORER_COPY.compare.copy} />
        </label>
        {choice.compare && others.length > 0 && (
          <label className="history-explorer-check">
            Grow
            <select
              aria-label="Grow to compare with"
              value={choice.compareRun ?? ""}
              onChange={(event) => setChoice({ compareRun: event.target.value || null })}
              data-compare-grow
            >
              <option value="">Last grow</option>
              {others.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {!hasPrevious && choice.compare && <span className="muted small">No previous run</span>}
        <label className="history-explorer-check">
          <input
            type="checkbox"
            checked={choice.shots}
            onChange={(event) => setChoice({ shots: event.target.checked })}
          />
          Shots
        </label>
        <label className="history-explorer-check">
          <input
            type="checkbox"
            checked={choice.phases}
            onChange={(event) => setChoice({ phases: event.target.checked })}
          />
          Phase bands
        </label>
      </fieldset>
      <fieldset className="history-explorer-sensors">
        <legend>
          <span className="label-with-tip">
            Sensors{" "}
            <InfoTip label={EXPLORER_COPY.sensors.label} copy={EXPLORER_COPY.sensors.copy} />
          </span>
        </legend>
        <div className="history-explorer-quick" role="group" aria-label="Select by type">
          {(["vwc", "ec"] as const).map((k) => (
            <button
              type="button"
              key={k}
              aria-pressed={all(kind(k))}
              disabled={!kind(k).length}
              onClick={() => toggle(kind(k), !all(kind(k)))}
            >
              All {k === "vwc" ? "VWC" : "EC"}
            </button>
          ))}
          <button
            type="button"
            disabled={!ticked.length}
            onClick={() => setChoice({ sensors: [] })}
          >
            Clear
          </button>
        </div>
        {groups.map((group) => (
          <div className="history-explorer-group" key={group} role="group" aria-label={group}>
            <p className="history-explorer-group-title" aria-hidden="true">
              {group}
            </p>
            {sensors
              .filter((sensor) => sensor.group === group)
              .map((sensor) => (
                <div key={sensor.entityId} className="history-explorer-probe-row">
                  <label className="history-explorer-check">
                    <input
                      type="checkbox"
                      checked={ticked.includes(sensor.entityId)}
                      onChange={(event) => toggle([sensor.entityId], event.target.checked)}
                      data-sensor={sensor.entityId}
                    />
                    <i style={{ background: sensor.color }} aria-hidden="true" />
                    <span>{sensor.label}</span>
                    <span className="muted">{sensor.unit}</span>
                  </label>
                  {(sensor.kind === "vwc" || sensor.kind === "ec") && (
                    <label className="history-explorer-probe-compare">
                      Compare with
                      <select
                        aria-label={`Compare ${sensor.label} with grow`}
                        data-probe-compare={sensor.entityId}
                        value={
                          choice.probeCompare?.[sensor.entityId] ??
                          (choice.compare
                            ? choice.compareRun
                              ? `run:${choice.compareRun}`
                              : "last"
                            : "off")
                        }
                        onChange={(event) =>
                          setChoice({
                            probeCompare: {
                              ...choice.probeCompare,
                              [sensor.entityId]: event.target.value,
                            },
                          })
                        }
                      >
                        <option value="off">Off</option>
                        <option value="last" disabled={!hasPrevious}>
                          Last grow
                        </option>
                        {others.map((grow) => (
                          <option key={grow.id} value={`run:${grow.id}`}>
                            {grow.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {(matches.get(sensor.entityId)?.match.entityId === null ||
                    !!choice.probeMatch?.[sensor.entityId]) &&
                    !!matches.get(sensor.entityId)?.match.candidates.length && (
                      <label className="history-explorer-probe-compare">
                        Historical probe
                        <select
                          aria-label={`Historical probe for ${sensor.label}`}
                          value={choice.probeMatch?.[sensor.entityId] ?? ""}
                          onChange={(event) =>
                            setChoice({
                              probeMatch: {
                                ...choice.probeMatch,
                                [sensor.entityId]: event.target.value,
                              },
                            })
                          }
                        >
                          <option value="">Choose the matching row</option>
                          {matches.get(sensor.entityId)!.match.candidates.map((probe) => (
                            <option key={probe.entity_id} value={probe.entity_id}>
                              {probe.row_label || probe.entity_id}{" "}
                              {probe.position === null ? "" : `(position ${probe.position + 1})`}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                </div>
              ))}
          </div>
        ))}
      </fieldset>
    </div>
  );
}

function Legend({
  visible,
  units,
  previous,
  shots,
  phases,
}: {
  visible: ExplorerSensor[];
  units: Unit[];
  previous: string | null;
  shots: boolean;
  phases: boolean;
}) {
  if (!visible.length) return null;
  const sides = (side: number) => units.filter((_, index) => index % 2 === side).join(", ");
  return (
    <div className="history-explorer-legend">
      <ul aria-label="Series on the chart">
        {visible.map((sensor) => (
          <li key={sensor.entityId}>
            <i style={{ background: sensor.color }} aria-hidden="true" />
            {sensor.label}
          </li>
        ))}
        {previous && (
          <li data-previous-legend>
            <i className="dashed" aria-hidden="true" />
            {previous}
          </li>
        )}
        {shots && (
          <li>
            <b className="history-explorer-shot-key" aria-hidden="true">
              ▲
            </b>
            Shots
          </li>
        )}
        {phases && <li className="muted">Shaded: P0–P3 of this zone</li>}
      </ul>
      <p className="muted small">
        Left axis {sides(0)}
        {units.length > 1 && ` · right axis ${sides(1)}`}
      </p>
    </div>
  );
}

function ExplorerTooltip({
  row,
  visible,
  compare,
  bands,
  timeZone,
}: {
  row: Row | undefined;
  visible: ExplorerSensor[];
  compare: boolean;
  bands: { phase: string; start: number; end: number }[];
  timeZone: string;
}) {
  if (!row || typeof row.t !== "number") return null;
  const phase = bands.find((band) => band.start <= row.t! && row.t! < band.end)?.phase;
  const value = (key: string, unit: Unit) =>
    row[key] === null || row[key] === undefined
      ? "—"
      : `${Number(row[key]).toFixed(UNIT_DIGITS[unit])} ${unit}`;
  return (
    <div className="history-explorer-tooltip">
      <strong>
        {new Date(row.t).toLocaleString([], {
          timeZone,
          weekday: "short",
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        })}
        {phase && ` · ${phase}`}
      </strong>
      <table>
        <tbody>
          {visible.map((sensor, index) => (
            <tr key={sensor.entityId}>
              <th scope="row">
                <i style={{ background: sensor.color }} aria-hidden="true" />
                {sensor.label}
              </th>
              <td>{value(`s${index}`, sensor.unit)}</td>
              {compare && <td className="muted">{value(`p${index}`, sensor.unit)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {compare && <p className="muted small">Grey: previous run, same grow day</p>}
    </div>
  );
}

function tickFormat(span: Span | null, timeZone: string) {
  const length = span ? span.end - span.start : 0;
  const options: Intl.DateTimeFormatOptions =
    length <= 26 * 3_600_000
      ? { hour: "2-digit", minute: "2-digit" }
      : length <= 4 * 86_400_000
        ? { weekday: "short", hour: "2-digit" }
        : { day: "numeric", month: "short" };
  const format = new Intl.DateTimeFormat([], { ...options, timeZone });
  return (value: number) => (Number.isFinite(value) ? format.format(value) : "");
}

function rangeText(span: Span, timeZone: string) {
  const format = new Intl.DateTimeFormat([], {
    timeZone,
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${format.format(span.start)} to ${format.format(span.end)}`;
}

/** A time as a datetime-local input reads it: the browser's own clock. */
function localInput(time: number) {
  const date = new Date(time - new Date(time).getTimezoneOffset() * 60_000);
  return date.toISOString().slice(0, 16);
}

// ---------------------------------------------------------------------------------------------
// History › Explorer (H1, mockup 09): the room's readings, chart by measure, under its PHASE and
// SHOTS lanes, with notes where something happened and one crosshair across every chart.

const PHASE_WORDS: Record<string, string> = { P0: "P0", P1: "P1 ramp", P2: "P2 maintain", P3: "P3 dryback" };
const HOUR = 3_600_000;
const DAY = 86_400_000;
type Board = { start: number; end: number };
const pctOf = (axis: Board, t: number) =>
  ((Math.min(axis.end, Math.max(axis.start, t)) - axis.start) / (axis.end - axis.start)) * 100;
const segmentAt = (lane: PhaseSegment[], t: number) =>
  lane.find((segment) => segment.from <= t && t < segment.to)?.phase ?? null;

/** A value as the legend shows it: the unit's digits, EC and temperature in the display units. */
function shownValue(series: ExplorerSeries, value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const digits = UNIT_DIGITS[series.unit];
  if (series.unit === "mS/cm") return formatEc(value, digits);
  if (series.unit === "°C") return formatTemp(value, digits);
  if (series.unit === "%") return `${value.toFixed(digits)}%`;
  return `${value.toFixed(digits)} ${series.unit}`;
}
/** "3.5–6.0 mS/cm": both ends in the display unit, which is said once. */
function bandWords(band: readonly [number, number], unit: Unit): string {
  const format = (v: number) => (unit === "mS/cm" ? formatEc(v, 1) : `${trim(v)}${unit === "%" ? "%" : ` ${unit}`}`);
  const high = format(band[1]);
  return `${format(band[0]).split(" ")[0].replace(/%$/, "")}–${high}`;
}
const trim = (value: number) => String(Number(value.toFixed(1)));

/** The width of an element, kept as it resizes. */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    setWidth(Math.floor(element.getBoundingClientRect().width));
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

/** The previous run's lines on this range's grid, at the same grow days (zone VWC and EC: the
 * sensors the run recorded for each zone). Null while loading or not asked. */
function useLastRunLines(
  controller: Controller,
  shown: ExplorerSeries[],
  run: RunRecord | null,
  previous: RunRecord | null,
  window: PreviousWindow | null,
  grid: { start: number; step: number; length: number } | null,
) {
  const pairs = previous
    ? shown.flatMap((series) => {
        const zone = previous.zones.find((item) => item.zone_id === series.zone);
        const id = series.kind === "vwc" ? zone?.vwc_sensor : series.kind === "ec" && series.chart === "ec" ? zone?.ec_sensor : null;
        return id ? [[series.key, id] as const] : [];
      })
    : [];
  const key =
    window && grid && run && previous && pairs.length
      ? JSON.stringify([previous.id, window.start, window.end, grid.start, grid.step, grid.length, pairs])
      : "";
  const [state, setState] = useState<{ key: string; lines: Map<string, (number | null)[]> } | null>(null);
  const latest = useRef({ controller, run, previous, window, grid, pairs });
  latest.current = { controller, run, previous, window, grid, pairs };
  useEffect(() => {
    if (!key) return;
    const { controller, run, previous, window, grid, pairs } = latest.current;
    if (!run || !previous || !window || !grid) return;
    let live = true;
    // Home Assistant's window read takes four sensors at a time.
    const ids = [...new Set(pairs.map(([, id]) => id))];
    const batches = Array.from({ length: Math.ceil(ids.length / 4) }, (_, i) => ids.slice(i * 4, i * 4 + 4));
    Promise.all(
      batches.map((entityIds) =>
        controller.historyWindow({
          entityIds,
          start: new Date(window.start).toISOString(),
          end: new Date(window.end).toISOString(),
          timeZone: previous.time_zone,
        }),
      ),
    )
      .then((reads) => {
        const result = { series: reads.flatMap((read) => read.series) };
        const lines = new Map<string, (number | null)[]>();
        for (const [seriesKey, id] of pairs) {
          const before = new SeriesGrid(window.start, window.end, grid.step);
          before.add(
            (result.series.find((item) => item.entityId === id)?.points ?? []).flatMap((point) =>
              point.value === null ? [] : [{ time: point.time, state: String(point.value) }],
            ),
          );
          lines.set(seriesKey, alignGrid(before.values(), { grid: before, run: previous }, { ...grid, run }));
        }
        if (live) setState({ key, lines });
      })
      .catch(() => live && setState({ key, lines: new Map() }));
    return () => {
      live = false;
    };
  }, [key]);
  return key && state?.key === key ? state.lines : null;
}

/** History › Explorer: the room's series by measure under its phase and shot lanes. */
export function RoomExplorer({ controller, zone }: { controller: Controller; zone?: number }) {
  const { room, states, timeZone } = controller;
  const prefix = room.room.prefix;
  const narrow = useNarrow(720);
  const connected = ["live", "demo"].includes(controller.connection);
  const [choice, setChoiceState] = useState<ExplorerChoice>(() =>
    readExplorerChoice(typeof window === "undefined" ? "" : window.location.hash),
  );
  const [now, setNow] = useState(() => Date.now());
  const [runs, setRuns] = useState<RunRecord[] | null>(null);
  const [events, setEvents] = useState<{ key: string; read: ExplorerEvents } | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [custom, setCustom] = useState(choice.range === "custom");
  function setChoice(next: Partial<ExplorerChoice>) {
    const merged = { ...choice, ...next };
    if (next.range || next.from !== undefined) setNow(Date.now());
    setChoiceState(merged);
    try {
      window.history.replaceState(null, "", writeExplorerChoice(window.location.hash, merged));
    } catch {
      /* A sandboxed frame keeps the choice in the page only. */
    }
  }
  useEffect(() => {
    if (!connected) return;
    let live = true;
    controller
      .operator<RunsDocument>("runs_get")
      .then((doc) => live && setRuns(doc.runs))
      .catch(() => live && setRuns([]));
    return () => {
      live = false;
    };
  }, [controller.roomId, connected]);
  const sensors = useMemo(
    () => explorerSensors(room, states),
    // The list changes with the room's mapping, not with every reading.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [room.room.id, Object.keys(states).length, room.zones.map((z) => `${z.vwc.entityId},${z.ec.entityId}`).join()],
  );
  const all = useMemo(() => explorerSeries(room, sensors), [sensors]); // eslint-disable-line react-hooks/exhaustive-deps
  const selected = (choice.series ?? defaultExplorerSeries(all)).filter((key) => all.some((s) => s.key === key));
  const shown = all.filter((series) => selected.includes(series.key));
  const { current: run, previous } = pickRuns(runs ?? []);
  const spans = explorerSpan(choice, { now, timeZone, run });
  const data = spans?.data ?? null;
  const axis = spans?.axis ?? null;
  const step = data ? stepFor(data.end - data.start, 480) : 60_000;
  const grid = data ? { start: data.start, step, length: Math.max(1, Math.ceil((data.end - data.start) / step)) } : null;
  const times = grid ? Array.from({ length: grid.length }, (_, i) => grid.start + i * step) : [];

  // The Journal's phases, shots and alerts over the range; `missing` on an integration before 3.18.
  const eventKey = data ? `${controller.roomId}|${data.start}|${data.end}` : "";
  useEffect(() => {
    if (!connected || !data) return;
    let live = true;
    void loadExplorerEvents(controller, controller.roomId, data).then(
      (read) => live && setEvents({ key: eventKey, read }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventKey, connected]);
  const read = events?.key === eventKey ? events.read : null;
  const legacy = read?.kind === "missing";
  const journal = read?.kind === "ok" ? read.events : [];

  // On 3.17 the lane's phases are the zone's phase sensor as Home Assistant recorded it.
  const laneZone = zone ?? room.zones[0]?.id ?? null;
  const phaseEntity = laneZone === null ? null : `sensor.crop_steering_${prefix}zone_${laneZone}_phase`;
  // The demo draws its readings from its own Journal's day, so lanes and lines agree.
  const reader = useMemo(
    () =>
      controller.demo
        ? (request: TimelineRequest) => Promise.resolve(demoExplorerTimeline(controller.states, request, Date.now()))
        : controller.timeline,
    [controller.demo, controller.timeline, controller.states],
  );
  // The tank level's own readings too: a refill is read from them, not from the grid's averages.
  const tankLevel = shown.find((series) => series.chart === "Tank level")?.entityId ?? null;
  const recorded = useGrids(
    controller,
    shown.map((series) => series.entityId),
    [...(legacy && phaseEntity && states[phaseEntity] ? [phaseEntity] : []), ...(tankLevel ? [tankLevel] : [])],
    connected ? data : null,
    step,
    reader,
  );
  // A VWC or a tank level of 0 or less is a probe gap, not a dry slab or an empty tank.
  const gappy = (series: ExplorerSeries) => series.kind === "vwc" || series.chart === "Tank level";
  const values = (series: ExplorerSeries) => {
    const list = recorded.values.get(series.entityId) ?? null;
    return list && gappy(series) ? list.map((v) => (v !== null && v <= 0 ? null : v)) : list;
  };

  // Compare with the last run: the previous finished run at the same grow days.
  const growDayNow = run ? Math.floor(runDayAt(run, now)) : null;
  const lastWindow = choice.last && run && previous && data ? previousWindow(run, previous, data.start, data.end, now) : null;
  const before = useLastRunLines(controller, shown, run, previous, lastWindow, grid);

  const lane: PhaseSegment[] =
    !data || !axis
      ? []
      : legacy
        ? phaseBands(phaseEntity ? recorded.rows.get(phaseEntity) : [], data.start, data.end).map((band) => ({
            from: band.start,
            to: band.end,
            phase: band.phase,
            planned: false,
          }))
        : phaseLane(
            journal,
            { start: data.start, end: axis.end },
            laneZone === null ? null : readProjection(states, prefix, laneZone),
            { now, zone: laneZone },
          );
  const shotRow = useMemo((): ShotRow | null => {
    if (!data || !axis || !read) return null;
    const block = (over: Partial<ShotBlock> & Pick<ShotBlock, "id" | "start" | "end" | "zone">): ShotBlock => ({
      glyph: "done",
      requestedAt: null,
      pumpWaitS: null,
      litres: null,
      meteredL: null,
      litresPerPlant: null,
      reason: null,
      phase: segmentAt(lane, over.start),
      vwcBefore: null,
      vwcExpected: null,
      source: "",
      code: null,
      eventId: null,
      skippable: false,
      roomId: controller.roomId,
      running: false,
      skipped: false,
      ...over,
    });
    const blocks: ShotBlock[] = legacy
      ? room.zones.flatMap((item) =>
          (
            tableShotLog(
              states[`sensor.crop_steering_${prefix}zone_${item.id}_shot_log_app`]?.attributes.shots,
              data.start,
              null,
            ) ?? []
          ).map((row) => block({ id: `${item.id}:${row.at}`, start: row.at, end: row.end, zone: item.id, phase: row.phase || null })),
        )
      : [
          ...journal
            .filter((e) => e.kind === "shot.completed" && e.zone !== null)
            .map((e) => {
              const end = Date.parse(e.ts);
              const seconds = Number(e.data.elapsed_s) || 0;
              const number = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
              return block({
                id: e.id,
                start: end - seconds * 1000,
                end,
                zone: e.zone!,
                litres: number(e.data.commanded_l),
                meteredL: number(e.data.metered_l),
                vwcBefore: number(e.data.vwc_before),
                source: e.source.actor,
                eventId: e.id,
                reason: e.source.detail ?? null,
              });
            }),
          ...room.zones.flatMap((item) =>
            (readProjection(states, prefix, item.id) ?? [])
              .filter((i) => Date.parse(i.at) > now && Date.parse(i.at) < axis.end)
              .map((i) =>
                block({
                  id: `planned:${item.id}:${i.at}`,
                  start: Date.parse(i.at),
                  end: Date.parse(i.at) + (Number(i.duration_s) || 60) * 1000,
                  zone: item.id,
                  glyph: i.expected ? "expected" : "planned",
                  source: i.source,
                }),
              ),
          ),
        ];
    return {
      key: "shots",
      roomId: controller.roomId,
      zone: null,
      label: room.room.name,
      sublabel: "",
      blocks: blocks.sort((a, b) => a.start - b.start),
      lights: [],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [read, legacy, data?.start, data?.end, axis?.end, lane.length, states, now]);

  // Notes in place (3.18): band excursions on the saved band, refills, alerts on a charted sensor.
  const view = useMemo(() => roomView(controller, now), [controller.roomId, controller.states, now]); // eslint-disable-line react-hooks/exhaustive-deps
  const poreBand = view?.room.stage?.poreEc ?? null;
  const ecMin = numeric(states[`number.crop_steering_${prefix}irrigation_ec_min`]);
  const ecMax = numeric(states[`number.crop_steering_${prefix}irrigation_ec_max`]);
  const feedBand: [number, number] | null = ecMin !== null && ecMax !== null && ecMax > ecMin ? [ecMin, ecMax] : null;
  const bandOf = (series: ExplorerSeries) =>
    series.chart === "ec" && series.chartTitle === "Pore EC" ? poreBand : series.chart === "Feed EC" ? feedBand : null;
  const readings: NoteReading[] = shown
    .filter((series) => bandOf(series) || series.chart === "Tank level")
    .map((series) => ({
      key: series.key,
      label: series.groupLabel,
      entityId: series.entityId,
      band: bandOf(series),
      kind: series.chart === "Tank level" ? "level" : "value",
      points:
        series.chart === "Tank level"
          ? (recorded.rows.get(series.entityId) ?? []).flatMap((row) => {
              const v = Number(row.state);
              return row.state.trim() && Number.isFinite(v) && data && row.time >= data.start ? [{ t: row.time, v }] : [];
            })
          : (values(series) ?? []).flatMap((v, i) => (v === null ? [] : [{ t: times[i], v }])),
    }));
  const notes = legacy || !read ? [] : chartNotes(journal, selected, readings, timeZone);

  const charts = [...new Set(shown.map((series) => series.chart))].map((chart) => ({
    chart,
    series: shown.filter((series) => series.chart === chart),
  }));
  const groups = [...new Set(all.map((series) => series.group))].map((group) => ({
    group,
    series: all.filter((series) => series.group === group),
  }));
  const toggle = (key: string) =>
    setChoice({ series: selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key] });
  const index = hover !== null && grid ? Math.min(grid.length - 1, Math.max(0, Math.floor((hover - grid.start) / step))) : null;
  const move = (t: number | null) => setHover(t === null || !data ? null : Math.min(data.end, Math.max(data.start, t)));
  const day = view?.room.growDay;
  const facts = [
    day?.stage ? day.stage.charAt(0).toUpperCase() + day.stage.slice(1) : null,
    day ? `day ${day.day}${day.of ? ` of ${day.of}` : ""}` : null,
  ].filter(Boolean);
  function exportCsv() {
    if (!grid) return;
    const csv = explorerCsv(
      times,
      // In the units the legend shows: ppm or °F where Settings › Display says so.
      shown.map((series) => ({
        label: `${series.groupLabel} ${series.chartTitle}`,
        ...inDisplayUnits(series.unit, values(series) ?? []),
      })),
      timeZone,
    );
    const url = URL.createObjectURL(new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    const slug = room.room.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "room";
    link.download = `${slug}-explorer-${dayKey(now, timeZone)}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const [from, setFrom] = useState(() => localInput(choice.from ?? data?.start ?? now));
  const [to, setTo] = useState(() => localInput(choice.to ?? now));
  const ticks = axis ? axisTicks(axis, timeZone, narrow) : [];
  const short = axis ? axis.end - axis.start <= 26 * HOUR : true;
  const markers = lane.filter((segment, i) => !segment.planned && i > 0);
  const busy = recorded.busy;
  return (
    <section
      className="explorer"
      aria-labelledby="explorer-title"
      data-room-explorer
      data-range-start={data?.start}
      data-range-end={data?.end}
      data-explorer-loads={recorded.loads}
    >
      <header className="explorer-head">
        <h1 id="explorer-title">Explorer</h1>
        {facts.length > 0 && <p className="explorer-facts">{facts.join(" · ")}</p>}
        <div className="explorer-actions">
          <button
            type="button"
            role="switch"
            aria-checked={choice.last}
            className="explorer-compare"
            disabled={!previous || !run}
            onClick={() => setChoice({ last: !choice.last })}
            data-compare-last
          >
            <span className="explorer-switch" aria-hidden="true" />
            Compare with last run
            {previous && growDayNow !== null && (
              <span className="muted">
                ({previous.name}, same day {growDayNow})
              </span>
            )}
          </button>
          <Button onClick={exportCsv} disabled={!shown.length || !grid || !connected} data-export-csv>
            <Download size={16} aria-hidden="true" />
            Export CSV · {shown.length} series
          </Button>
        </div>
      </header>
      <div className="explorer-toolbar">
        <div className="explorer-ranges" role="group" aria-label="Range">
          {EXPLORER_RANGES.map((range) => (
            <button
              type="button"
              key={range.id}
              aria-pressed={range.id === "custom" ? choice.range === "custom" || custom : choice.range === range.id}
              aria-expanded={range.id === "custom" ? custom : undefined}
              disabled={range.id === "run" && runs !== null && !run}
              onClick={() => {
                if (range.id === "custom") return setCustom((open) => !open);
                setCustom(false);
                setChoice({ range: range.id, from: null, to: null });
              }}
            >
              {range.label}
            </button>
          ))}
        </div>
        <span className="explorer-range-text" data-range-text>
          {data ? explorerRangeText(data, now, timeZone) : "Set a valid range"}
        </span>
        {!narrow && (
          <span className="explorer-hint muted">
            <Plus size={14} aria-hidden="true" /> Move across the charts to read every line at that moment
          </span>
        )}
      </div>
      {custom && (
        <form
          className="explorer-custom"
          onSubmit={(event) => {
            event.preventDefault();
            const start = Date.parse(from),
              end = Date.parse(to);
            if (Number.isFinite(start) && Number.isFinite(end) && end > start) setChoice({ range: "custom", from: start, to: end });
          }}
        >
          <label>
            From
            <input type="datetime-local" value={from} max={to} onChange={(event) => setFrom(event.target.value)} required />
          </label>
          <label>
            To
            <input type="datetime-local" value={to} min={from} onChange={(event) => setTo(event.target.value)} required />
          </label>
          <Button type="submit" size="sm" variant="outline" disabled={!(Date.parse(to) > Date.parse(from))}>
            Show this range
          </Button>
        </form>
      )}
      <div className="explorer-chips">
        {groups.map(({ group, series }) => (
          <div className="explorer-chip-group" role="group" aria-label={series[0].groupLabel} key={group}>
            <span className="explorer-chip-name">
              <i style={{ background: series[0].color }} aria-hidden="true" />
              {series[0].groupLabel}
            </span>
            {series.map((item) => (
              <button
                type="button"
                key={item.key}
                className="explorer-chip"
                aria-pressed={selected.includes(item.key)}
                aria-label={`${item.groupLabel} ${item.chip}`}
                style={{ "--chip": item.color } as CSSProperties}
                onClick={() => toggle(item.key)}
                data-chip={item.key}
              >
                {selected.includes(item.key) && <Check size={14} aria-hidden="true" />}
                {item.chip}
              </button>
            ))}
          </div>
        ))}
      </div>
      {!connected ? (
        <p className="muted small">Recorded history loads while Home Assistant is connected.</p>
      ) : !data || !axis ? (
        <p className="muted small">The end of the range must be after its start.</p>
      ) : (
        <div className="explorer-board" data-lanes-source={legacy ? "entities" : "journal"}>
          <div className="explorer-row explorer-lane">
            <span className="explorer-lane-name">Phase{laneZone !== null && room.zones.length > 1 ? ` · ${room.zones.find((z) => z.id === laneZone)?.name}` : ""}</span>
            <div className="explorer-phase-track" role="list" aria-label="Phases" data-phase-lane>
              {lane.map((segment) => (
                <span
                  key={`${segment.from}-${segment.planned}`}
                  role="listitem"
                  className="explorer-phase"
                  data-phase={segment.phase}
                  data-planned={segment.planned || undefined}
                  style={{ left: `${pctOf(axis, segment.from)}%`, width: `${pctOf(axis, segment.to) - pctOf(axis, segment.from)}%` }}
                  title={`${segment.phase} ${clock(segment.from, timeZone)} to ${clock(segment.to, timeZone)}${segment.planned ? " (planned)" : ""}`}
                >
                  {segment.planned ? `${segment.phase} planned` : PHASE_WORDS[segment.phase] ?? segment.phase}
                </span>
              ))}
            </div>
          </div>
          <div className="explorer-row explorer-lane">
            <span className="explorer-lane-name">Shots</span>
            <div className="explorer-shots" data-shot-lane>
              {shotRow && shotRow.blocks.length > 0 ? (
                <ShotTimeline rows={[shotRow]} span={axis} now={now} mode="strip" timeZone={timeZone} />
              ) : (
                <span className="muted small">{read ? "No shots in this range" : "Loading shots…"}</span>
              )}
            </div>
          </div>
          {(read?.kind === "ok" && read.truncated) || legacy || read?.kind === "error" ? (
            <div className="explorer-row explorer-lane-note">
              <span />
              <div>
                {read?.kind === "ok" && read.truncated && (
                  <p className="muted small" data-truncated>
                    Showing the newest {read.events.length} events
                  </p>
                )}
                {read?.kind === "error" && (
                  <p className="explorer-alert" role="alert">
                    Phases and shots did not load: {read.message}
                  </p>
                )}
                {legacy && <NeedsIntegration feature="Notes on the charts" compact />}
              </div>
            </div>
          ) : null}
          {recorded.error && (
            <p className="explorer-alert" role="alert">
              History did not load: {recorded.error}
            </p>
          )}
          {busy && (
            <p className="explorer-busy muted small" role="status">
              <LoaderCircle className="spin" size={14} aria-hidden="true" /> Loading day {busy.done + 1} of {busy.total}
            </p>
          )}
          {!charts.length && <p className="muted small">Select one or more series to chart them.</p>}
          {charts.map(({ chart, series }, chartIndex) => (
            <ExplorerChart
              key={chart}
              title={series[0].chartTitle}
              caption={captionOf(series[0], bandOf(series[0]), states, prefix)}
              series={series}
              values={values}
              before={before}
              band={bandOf(series[0])}
              axis={axis}
              data={data}
              times={times}
              index={index}
              hover={hover}
              onHover={move}
              step={step}
              now={now}
              timeZone={timeZone}
              notes={notes.filter((note) => series.some((s) => s.key === note.series))}
              markers={markers}
              markerLabels={chartIndex === 0 && short}
              last={chartIndex === charts.length - 1}
              phase={hover === null ? null : segmentAt(lane, hover)}
            />
          ))}
          {charts.length > 0 && (
            <div className="explorer-row explorer-axis" aria-hidden="true">
              <span />
              <div className="explorer-ticks">
                {ticks.map((tick) => (
                  <span key={tick.t} style={{ left: `${pctOf(axis, tick.t)}%` }}>
                    {tick.label}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** The caption beside a chart's title: its saved band or, for the tank, its refill call. */
function captionOf(series: ExplorerSeries, band: readonly [number, number] | null, states: States, prefix: string) {
  if (band) return `${series.chart === "Feed EC" ? "limits" : "band"} ${bandWords(band, series.unit)}`;
  if (series.chart === "Tank level") {
    const lines = levelLines(states, prefix, series.entityId);
    const remind = lines.find((line) => line.key === "remind");
    const minimum = lines.find((line) => line.key === "minimum");
    if (remind) return `refill call under ${remind.value}%`;
    if (minimum) return `watering held under ${minimum.value}%`;
  }
  return null;
}

/** Labelled times along the axis: every 3 h over a day (6 h on a phone), else midnights (fewer on a
 * long range or a phone). */
function axisTicks(axis: Board, timeZone: string, narrow: boolean): { t: number; label: string }[] {
  const length = axis.end - axis.start;
  if (length <= 26 * HOUR)
    return hourTicks(axis.start, axis.end + 1, narrow ? 6 : 3, timeZone).map((t) => ({ t, label: clock(t, timeZone) }));
  const days: number[] = [];
  for (let t = startOfDay(axis.start + DAY - 1, timeZone); t <= axis.end; t = startOfDay(t + 36 * HOUR, timeZone)) days.push(t);
  const every = Math.max(1, Math.ceil(days.length / (narrow ? 4 : 8)));
  return days.filter((_, i) => i % every === 0).map((t) => ({ t, label: dayLabel(t, timeZone) }));
}

function ExplorerChart({
  title,
  caption,
  series,
  values,
  before,
  band,
  axis,
  data,
  times,
  index,
  hover,
  onHover,
  step,
  now,
  timeZone,
  notes,
  markers,
  markerLabels,
  last,
  phase,
}: {
  title: string;
  caption: string | null;
  series: ExplorerSeries[];
  values: (series: ExplorerSeries) => (number | null)[] | null;
  before: Map<string, (number | null)[]> | null;
  band: readonly [number, number] | null;
  axis: Board;
  data: Board;
  times: number[];
  index: number | null;
  hover: number | null;
  onHover: (t: number | null) => void;
  step: number;
  now: number;
  timeZone: string;
  notes: ChartNote[];
  markers: PhaseSegment[];
  markerLabels: boolean;
  last: boolean;
  phase: string | null;
}) {
  const { ref, width } = useWidth();
  const height = 180;
  const inset = 14;
  const lines = series.map((item) => ({ item, values: values(item) ?? [], before: before?.get(item.key) ?? null }));
  const all = lines.flatMap((line) => [...line.values, ...(line.before ?? [])]).filter((v): v is number => v !== null);
  const span = [...all, ...(band ?? [])];
  let low = span.length ? Math.min(...span) : 0,
    high = span.length ? Math.max(...span) : 1;
  if (high - low < 1e-9) {
    low -= 1;
    high += 1;
  }
  const pad = (high - low) * 0.08;
  low -= pad;
  high += pad;
  const x = (t: number) => (pctOf(axis, t) / 100) * width;
  const y = (v: number) => inset + (1 - (v - low) / (high - low)) * (height - 2 * inset);
  const path = (list: readonly (number | null)[]) => {
    let d = "";
    let open = false;
    list.forEach((v, i) => {
      if (v === null || times[i] === undefined) return void (open = false);
      d += `${open ? "L" : "M"}${x(times[i]).toFixed(1)},${y(v).toFixed(1)}`;
      open = true;
    });
    return d;
  };
  const latest = (list: readonly (number | null)[]) => [...list].reverse().find((v) => v !== null) ?? null;
  const pointer = (event: React.PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    onHover(axis.start + ((event.clientX - box.left) / box.width) * (axis.end - axis.start));
  };
  const nowShown = now > axis.start && now < axis.end;
  return (
    <div className="explorer-row explorer-chart" data-chart={title}>
      <div className="explorer-legend">
        <h2>
          {title} {caption && <span className="muted">{caption}</span>}
        </h2>
        <ul>
          {lines.map(({ item, values: list, before: previous }) => (
            <li key={item.key} data-legend={item.key}>
              <i style={{ background: item.color }} aria-hidden="true" />
              <span>{item.groupLabel}</span>
              <b>{shownValue(item, index === null ? latest(list) : list[index])}</b>
              {previous && (
                <span className="muted explorer-before" title="Last run, same grow day">
                  {shownValue(item, index === null ? latest(previous) : previous[index])}
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
      <div
        ref={ref}
        className="explorer-plot"
        role="group"
        tabIndex={0}
        aria-label={`${title} chart: ${series.map((item) => item.groupLabel).join(", ")}. Use the left and right arrow keys to read the lines at a time.`}
        onPointerMove={pointer}
        onPointerDown={pointer}
        onPointerLeave={() => onHover(null)}
        onBlur={() => onHover(null)}
        onKeyDown={(event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          event.preventDefault();
          const by = (event.shiftKey ? 12 : 1) * step * (event.key === "ArrowLeft" ? -1 : 1);
          onHover((hover ?? data.end) + by);
        }}
      >
        <span className="explorer-y explorer-y-high">{shownValue(series[0], high - pad)}</span>
        <span className="explorer-y explorer-y-low">{shownValue(series[0], low + pad)}</span>
        {width > 0 && (
          <svg width={width} height={height} aria-hidden="true">
            {band && (
              <rect
                className="explorer-band"
                x={0}
                width={width}
                y={y(band[1])}
                height={Math.max(1, y(band[0]) - y(band[1]))}
              />
            )}
            {band && [band[0], band[1]].map((v) => <line key={v} className="explorer-band-edge" x1={0} x2={width} y1={y(v)} y2={y(v)} />)}
            {markers.map((marker) => (
              <line key={marker.from} className="explorer-marker" x1={x(marker.from)} x2={x(marker.from)} y1={0} y2={height} />
            ))}
            {lines.map(({ item, before: previous }) =>
              previous ? (
                <path key={`before-${item.key}`} className="explorer-line-before" d={path(previous)} stroke={item.color} data-before={item.key} />
              ) : null,
            )}
            {lines.map(({ item, values: list }) => (
              <path key={item.key} className="explorer-line" d={path(list)} stroke={item.color} data-series={item.key} />
            ))}
            {nowShown && <line className="explorer-now" x1={x(now)} x2={x(now)} y1={0} y2={height} />}
            {hover !== null && <line className="explorer-cross" x1={x(hover)} x2={x(hover)} y1={0} y2={height} />}
          </svg>
        )}
        {axis.end > data.end && (
          <span className="explorer-ahead" style={{ left: `${pctOf(axis, data.end)}%` }} aria-hidden="true" />
        )}
        {markerLabels &&
          markers
            // A label that would sit on the one before it is left to the lane above.
            .filter((marker, i, list) => i === 0 || x(marker.from) - x(list[i - 1].from) >= 84)
            .map((marker) => (
            <span key={marker.from} className="explorer-marker-label" style={{ left: `${pctOf(axis, marker.from)}%` }}>
              {marker.phase} {clock(marker.from, timeZone)}
            </span>
          ))}
        {notes.map((note, i) => (
          <span
            key={`${note.series}-${note.at}`}
            className="explorer-note"
            // One row each, so two notes near the same time never sit on each other.
            style={{ left: `min(${pctOf(axis, note.at)}%, calc(100% - 16rem))`, top: `${30 + (i % 4) * 24}px` }}
            data-chart-note
          >
            <CircleAlert size={13} aria-hidden="true" />
            {note.text}
          </span>
        ))}
        {last && nowShown && (
          <span className="explorer-now-label" style={{ left: `${pctOf(axis, now)}%` }}>
            Now {clock(now, timeZone)}
          </span>
        )}
        {last && hover !== null && (
          <span className="explorer-pill" style={{ left: `${pctOf(axis, hover)}%` }} data-time-pill>
            {clock(hover, timeZone)}
            {phase && ` · ${phase}`}
          </span>
        )}
      </div>
    </div>
  );
}
