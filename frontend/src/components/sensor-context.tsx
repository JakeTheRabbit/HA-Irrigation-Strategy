import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { LoaderCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/dashboard";
import { errorText } from "@/lib/utils";
import type { Controller, Series, Zone } from "@/lib/types";
import {
  DEFAULT_SENSOR_WINDOW,
  SENSOR_WINDOWS,
  chartScale,
  formatReading,
  latestOnly,
  nearestReading,
  plotPoints,
  referenceLines,
  sensorStats,
  spreadLabels,
  timeTicks,
  windowLabel,
  windowPoints,
  type ReferenceLine,
  type SensorMetric,
  type SensorReading,
  type SensorStats,
  type SensorWindow,
} from "@/lib/sensor-context";
import "./sensor-context.css";

interface MetricContext {
  entityId: string | null;
  points: SensorReading[];
  stats: SensorStats | null;
}
export interface SensorContextData {
  hours: SensorWindow;
  setHours: (hours: SensorWindow) => void;
  enabled: boolean;
  loading: boolean;
  /** The readings on screen belong to the previous window while the new one loads. */
  refreshing: boolean;
  error: string;
  retry: () => void;
  loadedAt: number | null;
  now: number;
  demo: boolean;
  zoneName: string;
  vwc: MetricContext;
  ec: MetricContext;
}
const REFRESH_MS = 60_000;
const timeZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

/** Recorded VWC and pore EC for one zone. Fetches only while `enabled` (connected and
 * editable), refetches on zone or window change and every minute, and drops stale responses. */
export function useSensorContext(
  controller: Controller,
  zone: Zone | undefined,
  enabled: boolean,
): SensorContextData {
  const [hours, setHours] = useState<SensorWindow>(DEFAULT_SENSOR_WINDOW);
  const [data, setData] = useState<{
    key: string;
    probes: string;
    series: Series[];
    at: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [guard] = useState(() => latestOnly<Series[]>());
  const vwcId = zone?.vwc.entityId ?? null,
    ecId = zone?.ec.entityId ?? null;
  const probes = [vwcId, ecId].filter((id): id is string => !!id).join("|");
  const key = `${controller.roomId}|${probes}|${hours}`;
  const history = controller.history;
  const active = enabled && !!probes;
  useEffect(() => {
    if (!active) {
      guard.cancel();
      setLoading(false);
      return;
    }
    const load = () => {
      setLoading(true);
      guard.run(
        () => history(probes.split("|"), hours),
        (result) => {
          setLoading(false);
          if (result.ok) {
            setData({ key, probes, series: result.value, at: Date.now() });
            setError("");
          } else setError(errorText(result.error));
        },
      );
    };
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      guard.cancel();
      window.clearInterval(timer);
    };
  }, [active, key, probes, hours, attempt, history, guard]);
  // Readings of another zone are never shown; an earlier window of the same probes is
  // held (dimmed) until its replacement arrives, so the card does not jump.
  const held = data && data.probes === probes ? data : null;
  const now = held ? Math.max(held.at, controller.lastUpdated ?? 0) : 0;
  const liveVwc = zone?.vwc.value,
    liveEc = zone?.ec.value;
  const metrics = useMemo(() => {
    const build = (entityId: string | null, live: number | null | undefined): MetricContext => {
      const series = held?.series.find((item) => item.entityId === entityId);
      const options = { hours, now, timeZone: timeZone(), live };
      return entityId && held
        ? { entityId, points: windowPoints(series, options), stats: sensorStats(series, options) }
        : { entityId, points: [], stats: null };
    };
    return { vwc: build(vwcId, liveVwc), ec: build(ecId, liveEc) };
  }, [held, hours, now, vwcId, ecId, liveVwc, liveEc]);
  return {
    hours,
    setHours,
    enabled,
    loading,
    refreshing: !!held && held.key !== key,
    error,
    retry: () => setAttempt((value) => value + 1),
    loadedAt: held?.at ?? null,
    now,
    demo: controller.demo,
    zoneName: zone?.name ?? "No zone",
    ...metrics,
  };
}

const trim = (value: number, digits: number) => String(Number(value.toFixed(digits)));
const setpointText = (value: number, metric: SensorMetric) =>
  metric === "vwc" ? `${trim(value, 1)}%` : trim(value, 2);
function clock(time: number, hours: number): string {
  return new Date(time).toLocaleString([], {
    ...(hours > 24 ? { weekday: "short" as const } : {}),
    hour: "2-digit",
    minute: "2-digit",
  });
}
const METRICS: Record<SensorMetric, { title: string; unit: string; name: string }> = {
  vwc: { title: "VWC", unit: "%", name: "volumetric water content" },
  ec: { title: "Pore EC", unit: "mS/cm", name: "pore EC" },
};

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {value}
        {detail && <small>{detail}</small>}
      </dd>
    </div>
  );
}

function SensorChart({
  metric,
  context,
  lines,
  start,
  end,
  hours,
  hover,
  onHover,
  zoneName,
}: {
  metric: SensorMetric;
  context: MetricContext;
  lines: ReferenceLine[];
  start: number;
  end: number;
  hours: number;
  hover: number | null;
  onHover: (time: number | null) => void;
  zoneName: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(560);
  const { title, unit, name } = METRICS[metric];
  const { stats, points } = context;
  const drawn = !!context.entityId && !!stats;
  useLayoutEffect(() => {
    // The plot only exists once readings arrive, so measure it from that render on.
    // Measuring before paint avoids a first frame drawn at the wrong width.
    const node = wrap.current;
    if (!drawn || !node) return;
    const measure = () => setWidth(Math.max(260, Math.round(node.clientWidth)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [drawn]);
  const plot = useMemo(() => plotPoints(points), [points]);
  const readings = useMemo(
    () => plot.filter((point): point is SensorReading => point.value !== null),
    [plot],
  );
  const shown = lines.filter((line) => line.metric === metric);
  const show = (value: number) => formatReading(value, metric);
  // Inside the plot the heading already carries the EC unit; "%" is short enough to keep.
  const inPlot = (value: number) => formatReading(value, metric, metric === "vwc");
  const span = windowLabel(hours);

  if (!context.entityId || !stats)
    return (
      <div className="sensor-chart">
        <div className="sensor-chart-heading">
          <h3>
            {title} <span>{unit}</span>
          </h3>
        </div>
        <p className="sensor-chart-empty">
          {context.entityId
            ? `No recorded history for this probe in the window (${span}). Nothing has been invented to fill it.`
            : `No ${title} probe is mapped for this zone.`}
        </p>
      </div>
    );

  const compact = width < 460;
  const left = 40,
    right = compact ? 80 : 132,
    top = 14,
    height = compact ? 190 : 214,
    bottom = height - 26;
  const plotRight = width - right;
  const { scale, offScale } = chartScale(
    readings.map((point) => point.value),
    shown,
  );
  const x = (time: number) =>
    left + (Math.min(1, Math.max(0, (time - start) / (end - start))) * (plotRight - left) || 0);
  const y = (value: number) =>
    bottom - ((value - scale.min) / (scale.max - scale.min)) * (bottom - top);
  let open = false;
  const path = plot
    .map((point) => {
      if (point.value === null) {
        open = false;
        return "";
      }
      const command = open ? "L" : "M";
      open = true;
      return `${command}${x(point.time).toFixed(1)},${y(point.value).toFixed(1)}`;
    })
    .join("");
  // A reading with a gap on both sides has no line to belong to; draw it as a dot.
  const isolated = plot.filter(
    (point, index) =>
      point.value !== null &&
      (plot[index - 1]?.value ?? null) === null &&
      (plot[index + 1]?.value ?? null) === null,
  );

  // One direct label per distinct line position: setpoints typed to the same value share it.
  const marks = new Map<string, { tone: string; value: number; lines: ReferenceLine[] }>();
  for (const line of shown)
    for (const [tone, value] of [
      [line.kind === "learned" ? "learned" : "draft", line.value],
      ["saved", line.saved],
    ] as const) {
      if (value === null) continue;
      const id = `${tone}:${value.toFixed(6)}`;
      marks.set(id, { tone, value, lines: [...(marks.get(id)?.lines ?? []), line] });
    }
  const labels = [...marks].map(([id, mark]) => {
    const pinned = offScale(mark.value);
    const names =
      mark.tone === "saved"
        ? `${mark.lines.map((line) => line.short).join(" · ")} ${compact ? "was" : "saved"}`
        : mark.lines.length > 1
          ? `${mark.lines.map((line) => line.short).join(" · ")}:`
          : compact
            ? mark.lines[0].short
            : mark.lines[0].label;
    return {
      id,
      tone: mark.tone,
      value: mark.value,
      pinned,
      at: pinned ? (mark.value > scale.max ? top : bottom) : y(mark.value),
      text:
        `${names} ${setpointText(mark.value, metric)}` +
        (pinned ? (mark.value > scale.max ? " ↑" : " ↓") : ""),
    };
  });
  const labelY = spreadLabels(
    labels.map((label) => label.at),
    12,
    top + 4,
    bottom - 2,
  );

  const current = stats.current ?? stats.last;
  const markers = [
    { id: "peak", label: "Peak", reading: stats.peak, above: true },
    { id: "trough", label: "Trough", reading: stats.trough, above: false },
  ].filter((marker, index, all) => index === 0 || marker.reading.time !== all[0].reading.time);
  // The Now tile above already carries the value; at phone width the plot has no room for it.
  const showNowLabel = !compact && markers.every((marker) => marker.reading.time !== current.time);
  const anchor = (px: number) => (px > left + (plotRight - left) * 0.62 ? "end" : "start");

  const focus = hover === null ? -1 : nearestReading(readings, hover);
  const focused = focus < 0 ? null : readings[focus];
  function pointer(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * width;
    if (px < left - 6 || px > plotRight + 6) return onHover(null);
    onHover(start + ((px - left) / (plotRight - left)) * (end - start));
  }
  function keys(event: KeyboardEvent<HTMLDivElement>) {
    if (!readings.length) return;
    const last = readings.length - 1;
    const from = focus < 0 ? last : focus;
    const step = Math.max(1, Math.round(readings.length / 60));
    const next =
      event.key === "ArrowLeft"
        ? Math.max(0, from - step)
        : event.key === "ArrowRight"
          ? Math.min(last, from + step)
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : null;
    if (event.key === "Escape") return onHover(null);
    if (next === null) return;
    event.preventDefault();
    onHover(readings[next].time);
  }
  const summary =
    `${zoneName} recorded ${name} over the last ${span}: ` +
    `${stats.current ? `now ${show(stats.current.value)}` : `live reading stale, last recorded ${show(stats.last.value)}`}, ` +
    `peak ${show(stats.peak.value)}, trough ${show(stats.trough.value)}. ` +
    (labels.length ? `Setpoints: ${labels.map((label) => label.text).join(", ")}.` : "");

  return (
    <div
      className="sensor-chart"
      style={{ "--sc-series": `var(--sc-${metric})` } as CSSProperties}
      data-sensor-chart={metric}
    >
      <div className="sensor-chart-heading">
        <h3>
          {title} <span>{unit}</span>
        </h3>
        {!stats.current && (
          <Badge variant="outline" className="status-paused">
            <span className="status-dot" />
            Live reading stale
          </Badge>
        )}
      </div>
      <dl className="sensor-stats">
        <Stat
          label="Now"
          value={stats.current ? show(stats.current.value) : "Stale"}
          detail={
            stats.current
              ? undefined
              : `last ${show(stats.last.value)} · ${clock(stats.last.time, hours)}`
          }
        />
        <Stat label="Peak" value={show(stats.peak.value)} detail={clock(stats.peak.time, hours)} />
        <Stat
          label="Trough"
          value={show(stats.trough.value)}
          detail={clock(stats.trough.time, hours)}
        />
        <Stat
          label="Typical daily peak"
          value={stats.typicalDailyPeak === null ? "—" : show(stats.typicalDailyPeak)}
          detail={`median of ${stats.days} ${stats.days === 1 ? "day" : "days"}`}
        />
        <Stat
          label="Typical daily trough"
          value={stats.typicalDailyTrough === null ? "—" : show(stats.typicalDailyTrough)}
          detail={`median of ${stats.days} ${stats.days === 1 ? "day" : "days"}`}
        />
      </dl>
      <div
        ref={wrap}
        className="sensor-chart-plot"
        role="group"
        tabIndex={0}
        aria-label={`${title} chart. Use the left and right arrow keys to read recorded values.`}
        onKeyDown={keys}
        onFocus={() => {
          if (hover === null && readings.length) onHover(readings.at(-1)!.time);
        }}
        onBlur={() => onHover(null)}
      >
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          height={height}
          role="img"
          aria-label={summary}
          onPointerMove={pointer}
          onPointerDown={pointer}
          onPointerLeave={() => onHover(null)}
        >
          {scale.ticks.map((tick) => (
            <g key={tick}>
              <line x1={left} x2={plotRight} y1={y(tick)} y2={y(tick)} className="sensor-grid" />
              <text x={left - 6} y={y(tick) + 3.5} textAnchor="end" className="sensor-axis">
                {trim(tick, 2)}
              </text>
            </g>
          ))}
          {timeTicks(start, end, hours).map((tick) => (
            <text
              key={tick.time}
              x={x(tick.time)}
              y={height - 8}
              textAnchor="middle"
              className="sensor-axis"
            >
              {tick.label}
            </text>
          ))}
          {/* Saved ghosts first, so the line being typed always draws on top. */}
          {[...labels]
            .sort((a, b) => Number(b.tone === "saved") - Number(a.tone === "saved"))
            .map(
              (label) =>
                !label.pinned && (
                  <line
                    key={label.id}
                    data-sensor-line={label.id}
                    x1={left}
                    x2={plotRight}
                    y1={label.at}
                    y2={label.at}
                    className={`sensor-line-${label.tone}`}
                  />
                ),
            )}
          <path d={path} className="sensor-series" data-sensor-series={metric} />
          {isolated.map((point) => (
            <circle
              key={point.time}
              cx={x(point.time)}
              cy={y(point.value!)}
              r={1.6}
              className="sensor-series-dot"
            />
          ))}
          {labels.map((label, index) => (
            <g key={label.id} className={`sensor-label sensor-label-${label.tone}`}>
              {!label.pinned && (
                <polyline
                  points={`${plotRight},${label.at.toFixed(1)} ${plotRight + 5},${labelY[index].toFixed(1)} ${plotRight + 8},${labelY[index].toFixed(1)}`}
                />
              )}
              <text x={plotRight + 10} y={labelY[index] + 3.5}>
                {label.text}
              </text>
            </g>
          ))}
          {markers.map((marker) => {
            const px = x(marker.reading.time),
              py = y(marker.reading.value);
            return (
              <g key={marker.id} data-sensor-marker={marker.id}>
                <circle cx={px} cy={py} r={4} className="sensor-marker" />
                <text
                  x={px + (anchor(px) === "end" ? -7 : 7)}
                  y={Math.min(bottom - 3, Math.max(top + 9, py + (marker.above ? -8 : 15)))}
                  textAnchor={anchor(px)}
                  className="sensor-marker-label"
                >
                  {marker.label} {inPlot(marker.reading.value)} ·{" "}
                  {clock(marker.reading.time, hours)}
                </text>
              </g>
            );
          })}
          <g data-sensor-now={stats.current ? "live" : "stale"}>
            <circle
              cx={x(current.time)}
              cy={y(current.value)}
              r={4.5}
              className={stats.current ? "sensor-marker" : "sensor-marker sensor-marker-stale"}
            />
            {showNowLabel && (
              <text
                x={x(current.time) - 8}
                y={Math.max(top + 9, y(current.value) - 8)}
                textAnchor="end"
                className="sensor-marker-label"
              >
                {stats.current ? "Now" : "Last"} {inPlot(current.value)}
              </text>
            )}
          </g>
          {focused && (
            <g className="sensor-crosshair">
              <line x1={x(focused.time)} x2={x(focused.time)} y1={top} y2={bottom} />
              <circle cx={x(focused.time)} cy={y(focused.value)} r={4} className="sensor-marker" />
            </g>
          )}
        </svg>
        {focused && (
          <div
            className="sensor-tooltip"
            style={{
              left: x(focused.time),
              top: y(focused.value),
              transform: `translate(${x(focused.time) > width * 0.55 ? "calc(-100% - 10px)" : "10px"}, -50%)`,
            }}
          >
            <strong>{show(focused.value)}</strong>
            <span>{clock(focused.time, 48)}</span>
          </div>
        )}
        <p className="sr-only" aria-live="polite">
          {focused ? `${clock(focused.time, 48)}: ${title} ${show(focused.value)}` : ""}
        </p>
      </div>
    </div>
  );
}

function full(reading: SensorReading, metric: SensorMetric) {
  return `${formatReading(reading.value, metric)} · ${new Date(reading.time).toLocaleString()}`;
}

/** "Recorded sensor behaviour": what the probes actually read, against the setpoints being typed. */
export function SensorContextCard({
  context,
  lines,
  subtitle = "what the probes actually read, with your setpoints drawn over it",
  disabledNote,
}: {
  context: SensorContextData;
  lines: ReferenceLine[];
  subtitle?: string;
  disabledNote?: string;
}) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);
  const { hours, vwc, ec } = context;
  const start = context.now - hours * 3_600_000;
  const hasData = context.loadedAt !== null;
  const ghost = lines.some((line) => line.saved !== null);
  const learned = lines.some((line) => line.kind === "learned");
  const value = (stats: SensorStats | null, metric: SensorMetric, pick: keyof SensorStats) => {
    const item = stats?.[pick];
    return item === null || item === undefined
      ? "—"
      : typeof item === "number"
        ? pick === "days"
          ? String(item)
          : formatReading(item, metric)
        : full(item, metric);
  };
  return (
    <section className="panel sensor-context" aria-labelledby={`${id}-title`}>
      <div className="panel-heading">
        <div>
          <h2 id={`${id}-title`}>Recorded sensor behaviour</h2>
          <p>
            {context.zoneName} · {subtitle}
          </p>
        </div>
        <div className="sensor-window" role="group" aria-label="History window">
          {SENSOR_WINDOWS.map((option) => (
            <button
              type="button"
              key={option}
              aria-pressed={hours === option}
              disabled={!context.enabled}
              onClick={() => context.setHours(option)}
            >
              {windowLabel(option)}
            </button>
          ))}
        </div>
      </div>
      {!context.enabled ? (
        <p className="sensor-context-note">
          {disabledNote ??
            "Recorded history loads while Home Assistant is connected and these targets are editable."}
        </p>
      ) : !vwc.entityId && !ec.entityId ? (
        <Empty
          title="No probes mapped for this zone"
          detail="Map a VWC and an EC sensor in Rooms & setup to see how the substrate behaves beside these targets."
        />
      ) : !hasData && context.error ? (
        <Empty
          title="Recorded history could not load"
          detail={context.error}
          action={
            <Button variant="outline" onClick={context.retry}>
              Retry history
            </Button>
          }
        />
      ) : !hasData ? (
        <div className="chart-placeholder sensor-context-loading" role="status">
          <LoaderCircle className="spin" />
          Loading recorded history…
        </div>
      ) : (
        <div className="sensor-context-body" data-refreshing={context.refreshing || undefined}>
          <div className="sensor-key" aria-hidden="true">
            <span>
              <i className="sensor-key-draft" />
              Setpoint as typed
            </span>
            {ghost && (
              <span>
                <i className="sensor-key-saved" />
                Saved on controller
              </span>
            )}
            {learned && (
              <span>
                <i className="sensor-key-learned" />
                Learned peak (auto)
              </span>
            )}
          </div>
          {(["vwc", "ec"] as const).map((metric) => (
            <SensorChart
              key={metric}
              metric={metric}
              context={context[metric]}
              lines={lines}
              start={start}
              end={context.now}
              hours={hours}
              hover={hover}
              onHover={setHover}
              zoneName={context.zoneName}
            />
          ))}
          {context.error && (
            <p className="sensor-context-note" role="status">
              Last refresh failed: {context.error} Showing the readings loaded at{" "}
              {clock(context.loadedAt!, 24)}.
            </p>
          )}
          <details className="sensor-table">
            <summary>Table view</summary>
            <div className="table-scroll" tabIndex={0} aria-label="Recorded sensor statistics">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Last {windowLabel(hours)}</th>
                    <th>VWC</th>
                    <th>Pore EC</th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ["Now (live)", "current"],
                      ["Last recorded", "last"],
                      ["Peak", "peak"],
                      ["Trough", "trough"],
                      ["Typical daily peak", "typicalDailyPeak"],
                      ["Typical daily trough", "typicalDailyTrough"],
                      ["Days behind typical values", "days"],
                    ] as const
                  ).map(([label, pick]) => (
                    <tr key={pick}>
                      <td>{label}</td>
                      <td>
                        {pick === "current" && vwc.stats && !vwc.stats.current
                          ? "Stale"
                          : value(vwc.stats, "vwc", pick)}
                      </td>
                      <td>
                        {pick === "current" && ec.stats && !ec.stats.current
                          ? "Stale"
                          : value(ec.stats, "ec", pick)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {lines.length > 0 && (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Line</th>
                      <th>Chart</th>
                      <th>As typed</th>
                      <th>Saved on controller</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((line) => (
                      <tr key={`${line.metric}-${line.key}`}>
                        <td>
                          {line.label}
                          {line.kind === "derived" ? " (typical peak less dryback)" : ""}
                        </td>
                        <td>{METRICS[line.metric].title}</td>
                        <td>
                          {line.value === null
                            ? "Invalid draft"
                            : formatReading(line.value, line.metric)}
                        </td>
                        <td>
                          {line.kind === "learned"
                            ? "—"
                            : line.saved === null
                              ? "Same"
                              : formatReading(line.saved, line.metric)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </details>
          <p className="sensor-context-caption">
            {context.demo ? "Generated demo history" : "Home Assistant recorder history"} · loaded{" "}
            {clock(context.loadedAt!, 24)}
            {context.loading ? " · refreshing…" : " · refreshes every minute"}. Typical values are
            the median of each local day’s highest and lowest reading. Lines follow your draft as
            you type; nothing is written until you review and apply.
          </p>
        </div>
      )}
    </section>
  );
}

/** Self-contained card for pages that only have a set of target parameters to draw. */
export function SensorContext({
  controller,
  zone,
  parameters,
  enabled,
  subtitle,
  disabledNote,
}: {
  controller: Controller;
  zone: Zone | undefined;
  parameters: Record<string, number>;
  enabled: boolean;
  subtitle?: string;
  disabledNote?: string;
}) {
  const context = useSensorContext(controller, zone, enabled);
  const typicalDailyPeak = context.vwc.stats?.typicalDailyPeak ?? null;
  const learnedPeak = zone?.auto?.learnedPeak ?? null;
  const lines = useMemo(
    () => referenceLines({ draft: parameters, typicalDailyPeak, learnedPeak }),
    [parameters, typicalDailyPeak, learnedPeak],
  );
  return (
    <SensorContextCard
      context={context}
      lines={lines}
      subtitle={subtitle}
      disabledNote={disabledNote}
    />
  );
}
