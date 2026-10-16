import { useEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle, SlidersHorizontal } from "lucide-react";
import {
  Brush,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceDot,
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
import type { RunRecord, RunsDocument } from "@/lib/comparison-types";
import { growDay, phaseBands, valveShots, type TimelineRow } from "@/lib/day-timeline";
import {
  alignGrid,
  chunks,
  DRYBACK_MARKER_DAYS,
  drybackMarkers,
  EXPLORER_COPY,
  explorerSensors,
  pickRuns,
  PRESETS,
  previousWindow,
  readChoice,
  resolveRange,
  runDayAt,
  SeriesGrid,
  stepFor,
  UNIT_DIGITS,
  writeChoice,
  type Choice,
  type ExplorerSensor,
  type Span,
  type Unit,
} from "@/lib/history-explorer";
import { dateInZone } from "@/lib/comparison";
import { numeric } from "@/lib/model";
import { dayOfRun, type GrowDay, type GrowDaysDocument } from "@/lib/grows";
import type { Controller, Zone } from "@/lib/types";
import { errorText } from "@/lib/utils";
import "./history-explorer.css";

const PHASE_FILL: Record<string, string> = {
  P0: "#6b7580",
  P1: "#2f6fb5",
  P2: "#6450b0",
  P3: "#34405a",
};

function useNarrow() {
  const query = "(max-width: 640px)";
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && window.matchMedia?.(query).matches,
  );
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const change = () => setNarrow(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  return narrow;
}

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
          const result = await controller.timeline({
            entityIds: [...wanted, ...events],
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

/** The zone page's history explorer: a range, any sensor of the room, the zone's phases and the
 * room's shots, and the previous run at the same grow days. */
export function HistoryExplorer({ controller, zone }: { controller: Controller; zone: Zone }) {
  const { room, states, timeZone } = controller;
  const [choice, setChoiceState] = useState<Choice>(() => readChoice(window.location.hash));
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
    (choice.compareRun && (runs ?? []).find((r) => r.id === choice.compareRun && r.id !== run?.id)) ||
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
  const previousIds = new Map<string, string>();
  for (const sensor of visible) {
    let id = sensor.entityId;
    const recorded = previous?.zones.find((item) => item.zone_id === sensor.zone);
    if (recorded && id === room.zones.find((z) => z.id === sensor.zone)?.vwc.entityId)
      id = recorded.vwc_sensor ?? id;
    if (recorded && id === room.zones.find((z) => z.id === sensor.zone)?.ec.entityId)
      id = recorded.ec_sensor ?? id;
    // Only what the room still has can be read.
    if (sensors.some((item) => item.entityId === id)) previousIds.set(sensor.entityId, id);
  }
  const before = useGrids(
    controller,
    [...previousIds.values()],
    [],
    connected && previousSpan ? { start: previousSpan.start, end: previousSpan.end } : null,
    step,
  );
  // Past the recorder's retention, the picked grow's daily summaries stand in: each grow day's mean.
  const summaries = useGrowDays(
    controller,
    choice.compare && previous && previousSpan ? previous : null,
    previousSpan,
  );
  const summaryFor = (sensor: ExplorerSensor, day: number): number | null => {
    if (!previous) return null;
    const row = summaries.find(
      (d) => d.zone === sensor.zone && dayOfRun(previous, d.date) === day,
    );
    if (!row) return null;
    const zone = room.zones.find((z) => z.id === sensor.zone);
    if (sensor.entityId === zone?.vwc.entityId) return row.vwc?.mean ?? null;
    if (sensor.entityId === zone?.ec.entityId) return row.ec?.mean ?? null;
    // A probe: its own entity id, else the same name (a probe replaced under a new id).
    const probe =
      row.probes?.find((p) => p.entity_id === sensor.entityId) ??
      row.probes?.find((p) => p.name && p.name === sensor.label);
    return probe?.mean ?? null;
  };
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
      const id = previousIds.get(sensor.entityId);
      const old = id && previousSpan && run && previous ? before.values.get(id) : undefined;
      if (old && previousSpan && run && previous) {
        const from = new SeriesGrid(previousSpan.start, previousSpan.end, step);
        alignGrid(old, { grid: from, run: previous }, { ...grid, run }).forEach(
          (value, at) => (rows[at][`p${index}`] = value),
        );
      }
      if (summaries.length && run && rows.every((row) => row[`p${index}`] == null))
        rows.forEach((row) => {
          const day = Math.floor(runDayAt(run, row.t as number));
          row[`p${index}`] = summaryFor(sensor, day);
        });
    });
    return rows;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    // The loaded maps fill in place: their load counts say when.
    recorded.values,
    recorded.loads,
    before.values,
    before.loads,
    summaries,
    previousSpan?.start,
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
  // Settings-free overlay (URL dryback=1, off by default): each grow day's peak and the low after
  // it on this zone's VWC, labelled as the controller measures dryback, on ranges of 14 d at most.
  const vwcIndex = visible.findIndex((sensor) => sensor.entityId === zone.vwc.entityId);
  const markers =
    choice.dryback && span && grid && vwcIndex >= 0 && span.end - span.start <= DRYBACK_MARKER_DAYS * 86_400_000
      ? (() => {
          const first = growDay(hour("on"), hour("off"), span.start, timeZone)?.start;
          if (first === undefined) return [];
          const starts: number[] = [];
          for (let t = first; t < span.end; t += 86_400_000) starts.push(t);
          const times = Array.from({ length: grid.length }, (_, i) => grid.timeAt(i));
          const values = times.map((_, i) => data[i]?.[`s${vwcIndex}`] ?? null);
          return drybackMarkers(times, values, starts);
        })()
      : [];
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
                  choice.compare && hasPrevious && previous && previousSpan
                    ? `Run ${previous.name}, days ${previousSpan.firstDay}–${previousSpan.lastDay}${
                        !before.values.size && summaries.length ? " (daily summary mean)" : ""
                      }`
                    : null
                }
                shots={shots.length > 0}
                phases={bands.length > 0}
              />
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
                              compare={choice.compare && hasPrevious}
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
                        {choice.compare &&
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
                        {markers.flatMap((marker) => [
                          <ReferenceDot
                            key={`peak-${marker.peak.t}`}
                            x={marker.peak.t}
                            y={marker.peak.value}
                            yAxisId={`axis-${units.indexOf("%")}`}
                            r={3}
                            fill="var(--muted-foreground)"
                            stroke="none"
                            className="history-explorer-dryback"
                          />,
                          <ReferenceDot
                            key={`low-${marker.low.t}`}
                            x={marker.low.t}
                            y={marker.low.value}
                            yAxisId={`axis-${units.indexOf("%")}`}
                            r={3}
                            fill="var(--surface)"
                            stroke="var(--muted-foreground)"
                            className="history-explorer-dryback"
                            label={{
                              value: `${marker.percent.toFixed(1)}% of peak`,
                              position: "bottom",
                              fill: "var(--muted-foreground)",
                              fontSize: 12,
                            }}
                          />,
                        ])}
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

/** The daily summaries of `run` over `span`, for the compare line past the recorder's retention. */
function useGrowDays(controller: Controller, run: RunRecord | null, span: Span | null): GrowDay[] {
  const [days, setDays] = useState<GrowDay[]>([]);
  const start = run && span ? dateInZone(span.start, run.time_zone) : "",
    end = run && span ? dateInZone(span.end, run.time_zone) : "";
  useEffect(() => {
    if (!start) {
      setDays([]);
      return;
    }
    let cancelled = false;
    controller
      .operator<GrowDaysDocument>("grow_days_get", { start, end })
      .then((doc) => !cancelled && setDays(doc.days))
      .catch(() => !cancelled && setDays([]));
    return () => {
      cancelled = true;
    };
  }, [controller.operator, start, end]);
  return days;
}

function Controls({
  choice,
  setChoice,
  sensors,
  ticked,
  span,
  runName,
  hasPrevious,
  others = [],
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
        <label className="history-explorer-check">
          <input
            type="checkbox"
            checked={choice.dryback}
            onChange={(event) => setChoice({ dryback: event.target.checked })}
            data-dryback-toggle
          />
          Dryback (% of peak)
          <InfoTip label={EXPLORER_COPY.dryback.label} copy={EXPLORER_COPY.dryback.copy} />
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
                <label className="history-explorer-check" key={sensor.entityId}>
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
