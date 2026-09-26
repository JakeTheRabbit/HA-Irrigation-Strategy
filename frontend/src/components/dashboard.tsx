import { useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowUpRight,
  Droplets,
  Info,
  LoaderCircle,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { Change, Controller, LogEvent, Metric, Series, Zone } from "@/lib/types";
import { errorText } from "@/lib/utils";
import { budgetShare, DRYBACK_WINDOW_H, drybackTrend, type DrybackTrend } from "@/lib/dryback";
import { useRecentHistory } from "@/lib/use-recent-moisture";
import { coreWaterValue, waterParameters } from "@/lib/water-delivery";
import {
  Meter,
  MiniBars,
  Pill,
  Sparkline,
  type MiniBar,
  type PillTone,
  type Tone,
} from "./mini-visuals";
import "./zone-state.css";

export type Page =
  | "overview"
  | "zones"
  | "strategy"
  | "grow-plan"
  | "compare"
  | "insights"
  | "setup"
  | "activity"
  | "sensors"
  | "settings"
  | "stock"
  | "help";
export const number = (value: number | null, digits = 1) =>
  value === null || !Number.isFinite(value)
    ? "Unavailable"
    : value.toLocaleString(undefined, { maximumFractionDigits: digits });
export const time = (value?: string | number | null) =>
  typeof value === "string" && /^\d{1,2}:\d{2}(:\d{2})?$/.test(value)
    ? value
    : !value || !Number.isFinite(new Date(value).getTime())
      ? "Not reported"
      : new Date(value).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        });
export function MetricValue({ metric }: { metric: Metric }) {
  return (
    <>
      {number(metric.value)}
      {metric.value !== null && <span className="unit"> {metric.unit}</span>}
    </>
  );
}
export function Heading({
  title,
  description,
  action,
}: {
  title: string;
  /** Only a behaviour the operator could get wrong; never a restatement of the title. */
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}
export function Empty({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <Info size={24} />
      <h3>{title}</h3>
      <p>{detail}</p>
      {action}
    </div>
  );
}
/** On is a green pill, paused an amber one, anything else grey. */
export function Status({ enabled, label }: { enabled?: boolean | null; label?: string }) {
  return (
    <Pill dot tone={enabled === true ? "on" : enabled === false ? "warn" : "unknown"}>
      {label || (enabled === true ? "Enabled" : enabled === false ? "Paused" : "Unavailable")}
    </Pill>
  );
}
/** Each kind of controller record, as the words and colour of its pill. */
const EVENT_TYPES: Record<LogEvent["type"], { label: string; tone: PillTone }> = {
  water: { label: "Water", tone: "water" },
  phase: { label: "Phase", tone: "phase" },
  warning: { label: "Warning", tone: "warn" },
  info: { label: "Info", tone: "neutral" },
};
export function EventType({ type }: { type: LogEvent["type"] }) {
  return (
    <Pill tone={EVENT_TYPES[type].tone} data-event-type={type}>
      {EVENT_TYPES[type].label}
    </Pill>
  );
}
/** The zone's daily water limit as the controller enforces it: the configured value inside its
 * safety bounds. */
export const dailyLimit = (controller: Controller, zoneId: number) =>
  coreWaterValue("max_daily_volume", waterParameters(controller, zoneId).max_daily_volume).value;
/** Water used against the daily limit: amber from 80 %, red once it is spent. */
export const budgetTone = (share: number | null): Tone =>
  share === null ? "normal" : share >= 100 ? "over" : share >= 80 ? "high" : "normal";

/** A room metric's zones as mini bars, and the line under the headline number. */
export function zoneBreakdown(
  metric: Metric,
  zones: Zone[],
  limits: Record<number, number | null>,
): { caption: string | null; bars: MiniBar[]; max: number; label: string } {
  const key = metric.key!;
  const known = zones.flatMap((zone) => (zone[key].value === null ? [] : [zone[key].value!]));
  const average = known.length ? known.reduce((a, b) => a + b, 0) / known.length : null;
  const unit = key === "shots" ? " shots" : ` ${metric.unit}`;
  const limited = key === "water" && zones.some((zone) => (limits[zone.id] ?? null) !== null);
  const bars = zones.map((zone): MiniBar => {
    const value = zone[key].value;
    const limit = limits[zone.id] ?? null;
    const share = limited ? budgetShare(value, limit) : null;
    return {
      id: String(zone.id),
      label: String(zone.id),
      value: limited ? share : value,
      tone: limited ? budgetTone(share) : "normal",
      title:
        `${zone.name}: ${number(value)}${value === null ? "" : unit}` +
        (share === null ? "" : ` of ${number(limit)} L, ${number(share, 0)}% of its daily limit`),
    };
  });
  const lo = Math.min(...known),
    hi = Math.max(...known);
  return {
    caption:
      average === null
        ? null
        : key === "water" || key === "shots"
          ? `Avg ${number(average)}${unit} per zone`
          : known.length > 1
            ? `Range ${number(lo)}–${number(hi)}${unit}`
            : null,
    bars,
    // Totals start from zero; averages leave headroom so the smallest zone still shows.
    max: limited ? 100 : key === "shots" || key === "water" ? hi : hi * 1.1,
    label:
      (limited ? "Share of each zone's daily water limit. " : `${metric.label} by zone. `) +
      bars.map((bar) => bar.title).join("; "),
  };
}

export function Metrics({
  metrics,
  zones = [],
  waterLimits = {},
}: {
  metrics: Metric[];
  /** The zones behind the room metrics: each metric then gets one mini bar per zone. */
  zones?: Zone[];
  /** Each zone's daily water limit in litres, for the water bars. */
  waterLimits?: Record<number, number | null>;
}) {
  return (
    <div className="metric-strip">
      {metrics.map((metric, i) => {
        const breakdown =
          metric.key && metric.value !== null && zones.length
            ? zoneBreakdown(metric, zones, waterLimits)
            : null;
        return (
          <div
            className="metric-item"
            key={metric.label}
            title={i > 1 ? "Recorded by the controller" : "Across reporting zones"}
          >
            <span className="eyebrow">{metric.label}</span>
            <div className="metric-body">
              <div>
                <strong>
                  <MetricValue metric={metric} />
                </strong>
                {metric.value === null ? (
                  <span className="metric-caption">Waiting for controller data</span>
                ) : (
                  breakdown?.caption && (
                    <span className="metric-caption">{breakdown.caption}</span>
                  )
                )}
              </div>
              {breakdown && (
                <MiniBars bars={breakdown.bars} max={breakdown.max} label={breakdown.label} />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function HistoryChart({ controller, zones }: { controller: Controller; zones: Zone[] }) {
  const [hours, setHours] = useState(24);
  const [data, setData] = useState<Series[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [hiddenZones, setHiddenZones] = useState<number[]>([]);
  const [retry, setRetry] = useState(0);
  const ids = [
    ...new Set(
      zones
        .flatMap((zone) => [zone.vwc.entityId, zone.ec.entityId])
        .filter((id): id is string => Boolean(id)),
    ),
  ];
  const key = ids.join("|");
  useEffect(() => setHiddenZones([]), [controller.roomId]);
  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    setData([]);
    if (!key) {
      setLoading(false);
      return;
    }
    controller
      .history(key.split("|"), hours)
      .then((result) => {
        if (current) setData(result);
      })
      .catch((error) => {
        if (current) setError(errorText(error));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [controller.roomId, controller.connection, key, hours, retry]);
  const palette = ["#03a9f4", "#e5a43b", "#a57bf3", "#e97d98", "#43bdab"];
  const visibleZones = zones.filter((zone) => !hiddenZones.includes(zone.id));
  const lines = visibleZones.flatMap((zone) =>
    (["vwc", "ec"] as const).map((kind) => {
      const entityId = zone[kind].entityId;
      const points = (data.find((series) => series.entityId === entityId)?.points || [])
        .filter((point) => Number.isFinite(point.value) && Number.isFinite(Date.parse(point.time)))
        .map((point) => ({ timestamp: Date.parse(point.time), value: point.value }))
        .sort((a, b) => a.timestamp - b.timestamp);
      return {
        zone,
        kind,
        entityId,
        points,
        color: palette[zones.findIndex((z) => z.id === zone.id) % palette.length],
      };
    }),
  );
  const recordedLines = lines.filter((line) => line.points.length);
  const times = [
    ...new Set(recordedLines.flatMap((line) => line.points.map((point) => point.timestamp))),
  ].sort((a, b) => a - b);
  const missing = lines
    .filter((line) => !line.points.length)
    .map((line) => `${line.zone.name} ${line.kind.toUpperCase()}`);
  return (
    <section className="panel chart-panel">
      <div className="panel-heading">
        <div>
          <h2>Moisture & EC history</h2>
          <p>Compare water content and root-zone conductivity over time</p>
        </div>
        <label className="sr-only" htmlFor="history-range">
          History range
        </label>
        <select
          id="history-range"
          value={hours}
          onChange={(event) => setHours(Number(event.target.value))}
        >
          <option value={6}>Last 6 hours</option>
          <option value={24}>Last 24 hours</option>
          <option value={72}>Last 3 days</option>
        </select>
      </div>
      {!!zones.length && (
        <div className="history-controls">
          <div className="history-zone-options" aria-label="Zones shown in history">
            {zones.map((zone, index) => (
              <button
                key={zone.id}
                aria-pressed={!hiddenZones.includes(zone.id)}
                onClick={() =>
                  setHiddenZones((current) =>
                    current.includes(zone.id)
                      ? current.filter((id) => id !== zone.id)
                      : [...current, zone.id],
                  )
                }
              >
                <i style={{ background: palette[index % palette.length] }} />
                {zone.name}
              </button>
            ))}
          </div>
          <span className="history-selection">
            {visibleZones.length} of {zones.length} zones shown
          </span>
        </div>
      )}
      <div className="history-axis-key">
        <span>
          <i />
          VWC · left axis (%)
        </span>
        <span>
          <i className="dashed" />
          EC · right axis (mS/cm)
        </span>
      </div>
      {loading ? (
        <div className="chart-placeholder" role="status">
          <LoaderCircle className="spin" />
          Loading recorded history…
        </div>
      ) : error ? (
        <Empty
          title="History could not load"
          detail={error}
          action={
            <Button variant="outline" onClick={() => setRetry((value) => value + 1)}>
              Retry history
            </Button>
          }
        />
      ) : !visibleZones.length ? (
        <Empty
          title="Choose a zone to compare"
          detail="Select one or more zones above to show their recorded moisture and EC."
          action={
            <Button variant="outline" onClick={() => setHiddenZones([])}>
              Show all zones
            </Button>
          }
        />
      ) : !recordedLines.length ? (
        <Empty
          title="No recorded moisture or EC history"
          detail="History appears when Home Assistant records the selected sensors. Missing measurements are not replaced with sample values."
        />
      ) : (
        <>
          <div
            className="chart-wrap combined-chart"
            role="img"
            aria-label={`Recorded VWC on the left percent axis and EC on the right mS/cm axis for ${visibleZones.map((zone) => zone.name).join(", ")} over ${hours} hours`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={times.map((timestamp) => ({ timestamp }))}
                margin={{ top: 12, right: 3, bottom: 8, left: 3 }}
              >
                <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="timestamp"
                  type="number"
                  scale="time"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(value) => time(value)}
                  minTickGap={65}
                  tickLine={false}
                  axisLine={false}
                  stroke="var(--muted-foreground)"
                />
                <YAxis
                  yAxisId="vwc"
                  orientation="left"
                  unit="%"
                  domain={[0, 100]}
                  width={44}
                  tickCount={5}
                  tickLine={false}
                  axisLine={false}
                  stroke="var(--muted-foreground)"
                />
                <YAxis
                  yAxisId="ec"
                  orientation="right"
                  domain={[0, "auto"]}
                  width={38}
                  tickCount={5}
                  tickFormatter={(value) => number(Number(value), 1)}
                  tickLine={false}
                  axisLine={false}
                  stroke="var(--muted-foreground)"
                />
                <Tooltip
                  labelFormatter={(value) => new Date(Number(value)).toLocaleString()}
                  contentStyle={{
                    background: "var(--surface)",
                    color: "var(--foreground)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                  }}
                  formatter={(value, name, item) => [
                    `${Number(value).toFixed(item.unit === "%" ? 1 : 2)} `,
                    name,
                  ]}
                />
                {recordedLines.map((line) => (
                  <Line
                    key={`${line.zone.id}-${line.kind}`}
                    data={line.points}
                    dataKey="value"
                    name={`${line.zone.name} · ${line.kind.toUpperCase()}`}
                    unit={line.kind === "vwc" ? "%" : "mS/cm"}
                    yAxisId={line.kind}
                    type="linear"
                    stroke={line.color}
                    strokeWidth={line.kind === "vwc" ? 2.2 : 1.8}
                    strokeDasharray={line.kind === "ec" ? "5 4" : undefined}
                    connectNulls={false}
                    dot={line.points.length === 1 ? { r: 3 } : false}
                    activeDot={{ r: 4 }}
                    isAnimationActive={false}
                  />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          {!!missing.length && (
            <p className="history-missing" role="status">
              No recorded samples: {missing.join(", ")}.
            </p>
          )}
          <p className="history-caption">
            {controller.demo ? "Demo history · " : "Home Assistant history · "}Solid lines: VWC.
            Dashed lines: EC. Each axis has its own scale.
          </p>
        </>
      )}
    </section>
  );
}

/** The phases a zone can be moved to by hand, with the names the zone views use. */
const PHASE_NAMES: Record<string, string> = {
  P0: "Dry-back",
  P1: "Ramp-up",
  P2: "Maintenance",
  P3: "Overnight",
};

/** A phase in its timeline colour; anything else in grey. */
export function PhasePill({ phase }: { phase: string }) {
  return /^P[0-3]$/.test(phase) ? (
    <span className="pill" data-phase={phase}>
      {phase}
    </span>
  ) : (
    <span className="pill" data-tone="unknown">
      {phase === "Unavailable" || !phase ? "Phase unavailable" : phase}
    </span>
  );
}

export function ZoneOperatingState({
  zone,
  showScheduling = true,
}: {
  zone: Zone;
  showScheduling?: boolean;
}) {
  return (
    <div className="zone-operating-state" data-stale={zone.stale || undefined}>
      <span className="zone-controller-status" data-zone-status={zone.id}>
        {zone.status === "Unavailable" ? "Controller status unavailable" : zone.status}
      </span>
      <div className="zone-state-flags">
        <span
          className={`pill zone-valve-state${zone.valveOn === true ? " valve-on" : ""}`}
          data-tone={zone.valveOn === true ? "on" : zone.valveOn === false ? "off" : "unknown"}
          data-zone-valve={zone.id}
          title={
            zone.valveEntity
              ? `Reported switch state · ${zone.valveEntity}`
              : "No valve mapped in this room's engine configuration"
          }
        >
          <span className="pill-dot" />
          Valve {zone.valveOn === true ? "on" : zone.valveOn === false ? "off" : "unknown"}
        </span>
        <PhasePill phase={zone.phase} />
        {zone.stale && (
          <Pill
            dot
            tone="warn"
            title="The controller is not reporting: phase and status are its last report, not live."
          >
            Stale
          </Pill>
        )}
        {showScheduling && <Status enabled={zone.enabled} />}
      </div>
    </div>
  );
}

export function LastIrrigation({ zone, compact = false }: { zone: Zone; compact?: boolean }) {
  const { timestamp, issue } = zone.lastIrrigation;
  if (!timestamp)
    return (
      <span className="zone-last-irrigation" data-last-irrigation={zone.id}>
        <span>Not reported</span>
        <span className="cell-subtext">{issue}</span>
      </span>
    );
  const date = new Date(timestamp);
  const minutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60_000));
  const relative =
    minutes < 1
      ? compact
        ? "Just now"
        : "Less than a minute ago"
      : new Intl.RelativeTimeFormat(undefined, {
          numeric: "always",
          style: compact ? "short" : "long",
        }).format(
          -(minutes < 60
            ? minutes
            : minutes < 1440
              ? Math.floor(minutes / 60)
              : Math.floor(minutes / 1440)),
          minutes < 60 ? "minute" : minutes < 1440 ? "hour" : "day",
        );
  const full = date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
  return (
    <time
      className="zone-last-irrigation"
      data-last-irrigation={zone.id}
      dateTime={timestamp}
      title={timestamp}
      aria-label={`Last irrigation: ${full}. ${relative}.`}
    >
      <span>{relative}</span>
      {!compact && <span className="cell-subtext">{full}</span>}
    </time>
  );
}

/** How fast the zone is drying, and the line it has drawn over the last two hours. */
export function DrybackRate({
  zone,
  trend,
  width,
}: {
  zone: Zone;
  trend: DrybackTrend | undefined;
  /** Of the sparkline, where there is room for a longer one. */
  width?: number;
}) {
  if (!trend)
    return (
      <span className="muted" title="Loading the recorded moisture readings">
        —
      </span>
    );
  const { rate } = trend;
  const drying = rate !== null && rate >= 0;
  // Below this the probe's own jitter decides the sign.
  const steady = rate !== null && Math.abs(rate) < 0.05;
  return (
    <span
      className="dryback"
      data-dryback={zone.id}
      title={
        trend.reason ??
        `Moisture lost per hour since the last shot settled, over up to the last ${DRYBACK_WINDOW_H} hours, in VWC percentage points.`
      }
    >
      <span className="dryback-rate">
        {rate === null ? (
          "—"
        ) : steady ? (
          "Steady"
        ) : (
          <>
            {drying ? <TrendingDown size={14} /> : <TrendingUp size={14} />}
            <span className="sr-only">{drying ? "Drying" : "Wetting"}</span>
            {number(Math.abs(rate), Math.abs(rate) < 1 ? 2 : 1)}
            <span className="unit"> %/h</span>
          </>
        )}
      </span>
      <Sparkline
        points={trend.recent}
        width={width}
        label={`${zone.name} moisture over the last ${DRYBACK_WINDOW_H} hours`}
      />
    </span>
  );
}

/** Water today against the zone's daily limit. */
export function WaterUse({ zone, limit }: { zone: Zone; limit: number | null }) {
  const share = budgetShare(zone.water.value, limit);
  return (
    <span className="water-use" data-water-share={share === null ? "" : Math.round(share)}>
      <span>
        {number(zone.water.value)}
        {zone.water.value !== null && (
          <span className="unit">{limit === null ? " L" : ` / ${number(limit)} L`}</span>
        )}
      </span>
      {share !== null && (
        <>
          <Meter
            value={share}
            max={100}
            tone={budgetTone(share)}
            label={`${number(share, 0)}% of the ${number(limit)} L daily limit`}
          />
          <span className="cell-subtext">{number(share, 0)}% of limit</span>
        </>
      )}
    </span>
  );
}

/** "P2 base VWC threshold" → "Threshold", keeping a grow plan's "Plan · " prefix. */
const shortTarget = (label: string) => {
  const plan = label.startsWith("Plan · ");
  const kind = /threshold/i.test(label) ? "threshold" : /floor/i.test(label) ? "floor" : "target";
  return plan ? `Plan · ${kind}` : kind[0].toUpperCase() + kind.slice(1);
};

/** Moisture with a bar to 100 % and a marker at the phase's target; `target` names it below. */
export function MoistureCell({ zone, target = true }: { zone: Zone; target?: boolean }) {
  return (
    <>
      <MetricValue metric={zone.vwc} />
      {zone.vwc.value !== null && (
        <Meter
          value={zone.vwc.value}
          max={100}
          mark={zone.target.value}
          label={`Moisture ${number(zone.vwc.value)} %${
            zone.target.value === null
              ? ""
              : `, ${zone.target.label} ${number(zone.target.value)} % marked`
          }`}
        />
      )}
      {target && (
        <span className="cell-subtext moisture-target" title={zone.target.label}>
          {shortTarget(zone.target.label)} <MetricValue metric={zone.target} />
        </span>
      )}
    </>
  );
}

export function ZoneTable({
  zones,
  onSelect,
  compact = false,
  trends,
  limits = {},
}: {
  zones: Zone[];
  onSelect: (zone: Zone) => void;
  /** Overview: the target rides under the moisture reading; ages without dates; no arrow column. */
  compact?: boolean;
  /** Each zone's dryback; null while the readings load. */
  trends?: Record<number, DrybackTrend> | null;
  /** Each zone's daily water limit in litres. */
  limits?: Record<number, number | null>;
}) {
  return (
    <>
      <div
        className="table-scroll zone-table-desktop"
        tabIndex={0}
        aria-label="Zone readings and irrigation events"
      >
        <table className={compact ? "data-table zone-table-compact" : "data-table"}>
          <thead>
            <tr>
              <th>Zone</th>
              <th>Current state</th>
              <th>Last irrigation</th>
              <th>Moisture</th>
              {!compact && <th>VWC reference</th>}
              <th>Root-zone EC</th>
              <th title="VWC percentage points lost per hour">Dryback</th>
              <th>Water today</th>
              {!compact && (
                <th>
                  <span className="sr-only">Details</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {zones.map((zone) => (
              <tr key={zone.id}>
                <td>
                  <button className="zone-name" onClick={() => onSelect(zone)}>
                    <span className="zone-icon">
                      <Droplets size={17} />
                    </span>
                    {zone.name}
                  </button>
                </td>
                <td>
                  {/* The Overview flags a zone that is not scheduled; enabled is the norm. */}
                  <ZoneOperatingState zone={zone} showScheduling={!compact || zone.enabled !== true} />
                </td>
                <td>
                  <LastIrrigation zone={zone} compact={compact} />
                </td>
                <td className="numeric">
                  {/* The full table names the target in its own column. */}
                  <MoistureCell zone={zone} target={compact} />
                </td>
                {!compact && (
                  <td className="numeric muted">
                    <MetricValue metric={zone.target} />
                    <span className="cell-subtext">{zone.target.label}</span>
                  </td>
                )}
                <td className="numeric">
                  <MetricValue metric={zone.ec} />
                </td>
                <td className="numeric">
                  <DrybackRate zone={zone} trend={trends?.[zone.id]} />
                </td>
                <td className="numeric">
                  <WaterUse zone={zone} limit={limits[zone.id] ?? null} />
                </td>
                {!compact && (
                  <td>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={`View ${zone.name}`}
                      onClick={() => onSelect(zone)}
                    >
                      <ArrowUpRight size={17} />
                    </Button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="zone-mobile-list">
        {zones.map((zone) => (
          <div className="zone-mobile-row" key={zone.id}>
            <button className="zone-mobile-title" onClick={() => onSelect(zone)}>
              <span className="zone-icon">
                <Droplets size={17} />
              </span>
              <strong>{zone.name}</strong>
              <Status enabled={zone.enabled} />
              <ArrowUpRight size={16} />
            </button>
            <ZoneOperatingState zone={zone} showScheduling={false} />
            <div className="zone-irrigation-summary">
              <span className="small muted">Last irrigation</span>
              <LastIrrigation zone={zone} />
            </div>
            <div className="zone-mobile-readings">
              <div>
                <span>Moisture</span>
                <strong>
                  <MoistureCell zone={zone} target={false} />
                </strong>
              </div>
              <div>
                <span>Root-zone EC</span>
                <strong>
                  <MetricValue metric={zone.ec} />
                </strong>
              </div>
              <div>
                <span>Water today</span>
                <strong>
                  <WaterUse zone={zone} limit={limits[zone.id] ?? null} />
                </strong>
              </div>
              <div>
                <span>Dryback</span>
                <strong>
                  <DrybackRate zone={zone} trend={trends?.[zone.id]} />
                </strong>
              </div>
            </div>
            <p className="zone-mobile-target">
              {zone.target.label}: <MetricValue metric={zone.target} />
            </p>
          </div>
        ))}
      </div>
    </>
  );
}

export interface ReviewItem {
  change: Change;
  label: string;
  before: string;
  after: string;
}
export function ReviewDialog({
  open,
  onOpenChange,
  controller,
  items,
  onApplied,
  title = "Review changes",
  note,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  controller: Controller;
  items: ReviewItem[];
  onApplied?: (applied: string[]) => void;
  title?: string;
  note?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  useEffect(() => {
    if (open) setErrors([]);
  }, [open]);
  async function apply() {
    setBusy(true);
    setErrors([]);
    try {
      const result = await controller.write(items.map((item) => item.change));
      onApplied?.(result.applied);
      if (result.failed.length)
        setErrors(
          result.failed.map(
            (f) =>
              `${items.find((i) => i.change.entityId === f.entityId)?.label || f.entityId}: ${f.reason}`,
          ),
        );
      else onOpenChange(false);
    } catch (error) {
      setErrors([errorText(error)]);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!busy) onOpenChange(v);
      }}
    >
      <DialogContent className="review-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {controller.demo ? "Demo only. " : ""}These changes affect {controller.room.room.name}{" "}
            only. Confirm each value before applying.
          </DialogDescription>
        </DialogHeader>
        <div className="review-list">
          {items.map((item) => (
            <div className="review-row" key={item.change.entityId}>
              <strong>{item.label}</strong>
              <span>
                {item.before} <span aria-hidden="true">→</span> <b>{item.after}</b>
              </span>
            </div>
          ))}
        </div>
        {note && <p className="notice-inline">{note}</p>}
        {errors.length > 0 && (
          <div role="alert" className="form-error">
            <strong>Some changes were not applied.</strong>
            {errors.map((error) => (
              <p key={error}>{error}</p>
            ))}
            <p>Successful changes were saved. Failed changes remain available for review.</p>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            Back to editing
          </Button>
          <Button
            disabled={
              busy ||
              !items.length ||
              controller.connection === "offline" ||
              controller.connection === "connecting"
            }
            onClick={apply}
          >
            {busy && <LoaderCircle className="spin" size={16} />}
            {busy
              ? "Applying & verifying…"
              : `Apply ${items.length} ${items.length === 1 ? "change" : "changes"}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ZoneDetails({
  controller,
  zone,
  close,
  navigate,
}: {
  controller: Controller;
  zone: Zone | null;
  close: () => void;
  navigate: (page: Page, zoneId?: number) => void;
}) {
  const [review, setReview] = useState(false);
  const [phaseChoice, setPhaseChoice] = useState<string | null>(null);
  useEffect(() => {
    setReview(false);
    setPhaseChoice(null);
  }, [zone?.id]);
  // Only an open sheet reads its zone's moisture: one small request, for the dryback line.
  const moisture = useRecentHistory(
    controller,
    zone?.vwc.entityId ? [zone.vwc.entityId] : [],
    DRYBACK_WINDOW_H + 1,
  );
  const trend =
    zone && moisture
      ? drybackTrend(
          moisture[0]?.points ?? [],
          zone.lastIrrigation.timestamp,
          zone.vwc.value,
          Date.now(),
        )
      : undefined;
  return (
    <>
      <Sheet
        open={Boolean(zone)}
        onOpenChange={(open) => {
          if (!open) close();
        }}
      >
        <SheetContent className="zone-sheet">
          <SheetHeader>
            <SheetTitle>{zone?.name}</SheetTitle>
            <SheetDescription>{controller.room.room.name} · zone details</SheetDescription>
          </SheetHeader>
          {zone && (
            <div className="sheet-body">
              <ZoneOperatingState zone={zone} />
              <div className="zone-irrigation-summary">
                <span className="small muted">Last irrigation</span>
                <LastIrrigation zone={zone} />
              </div>
              <div className="detail-metrics">
                <div>
                  <span>Moisture</span>
                  <strong>
                    <MoistureCell zone={zone} target={false} />
                  </strong>
                  <small>
                    {zone.target.label} <MetricValue metric={zone.target} />
                  </small>
                </div>
                <div>
                  <span>Root-zone EC</span>
                  <strong>
                    <MetricValue metric={zone.ec} />
                  </strong>
                  {zone.ec.value !== null && zone.ecTarget.value !== null && (
                    // Twice the target, so the target sits in the middle.
                    <Meter
                      value={zone.ec.value}
                      max={2 * zone.ecTarget.value}
                      mark={zone.ecTarget.value}
                      label={`Root-zone EC ${number(zone.ec.value)} mS/cm, ${zone.ecTarget.label} ${number(zone.ecTarget.value)} mS/cm marked`}
                    />
                  )}
                  <small>
                    {zone.ecTarget.label} <MetricValue metric={zone.ecTarget} />
                  </small>
                </div>
                <div>
                  <span>Water today</span>
                  <strong>
                    <WaterUse zone={zone} limit={dailyLimit(controller, zone.id)} />
                  </strong>
                </div>
                <div>
                  <span>Shots today</span>
                  <strong>
                    <MetricValue metric={zone.shots} />
                  </strong>
                </div>
                <div className="detail-wide">
                  <span>Dryback · last {DRYBACK_WINDOW_H} hours</span>
                  <DrybackRate zone={zone} trend={trend} width={180} />
                </div>
              </div>
              <h3>Configuration</h3>
              <p className="muted">Review phase targets and timing in irrigation strategy.</p>
              <Button
                className="full-width"
                onClick={() => {
                  close();
                  navigate("strategy", zone.id);
                }}
              >
                Edit {zone.name} strategy <ArrowUpRight size={16} />
              </Button>
              <Button
                variant="outline"
                className="full-width"
                disabled={
                  !zone.enabledEntity ||
                  zone.enabled === null ||
                  !["live", "demo"].includes(controller.connection)
                }
                onClick={() => setReview(true)}
              >
                {zone.enabled ? "Pause zone scheduling" : "Enable zone scheduling"}
              </Button>
              <p className="small muted">
                Pausing scheduling may prevent future cycles. It is not an emergency stop and may
                not interrupt a shot already running.
              </p>
              {zone.setPhaseEntity && (
                <>
                  <h3>Phase</h3>
                  <p className="muted">
                    Move {zone.name} to another phase. The controller moves it within a minute and
                    carries on from there: lights-off still moves it to P3, and lights-on to P0.
                  </p>
                  <div className="phase-picker" role="group" aria-label={`Move ${zone.name} to`}>
                    {Object.entries(PHASE_NAMES).map(([phase, name]) => (
                      <Button
                        key={phase}
                        size="sm"
                        variant="outline"
                        aria-pressed={phase === zone.phase}
                        disabled={
                          phase === zone.phase || !["live", "demo"].includes(controller.connection)
                        }
                        onClick={() => setPhaseChoice(phase)}
                      >
                        {phase} · {name}
                      </Button>
                    ))}
                  </div>
                </>
              )}
              <h3>Reporting sensors</h3>
              {zone.sensors.length ? (
                <div className="sensor-mini-list">
                  {zone.sensors.map((sensor) => (
                    <div key={sensor.entity_id}>
                      <span>{String(sensor.attributes.friendly_name || sensor.entity_id)}</span>
                      <strong>
                        {sensor.state} {String(sensor.attributes.unit_of_measurement || "")}
                      </strong>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">No sensor entities mapped to this zone.</p>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
      {zone && (
        <ReviewDialog
          open={review}
          onOpenChange={setReview}
          controller={controller}
          title="Review zone scheduling"
          items={
            zone.enabledEntity
              ? [
                  {
                    change: {
                      entityId: zone.enabledEntity,
                      value: !zone.enabled,
                    },
                    label: `${zone.name} scheduling`,
                    before: zone.enabled ? "Enabled" : "Paused",
                    after: zone.enabled ? "Paused" : "Enabled",
                  },
                ]
              : []
          }
          note="This changes future scheduling. An active irrigation shot may continue."
        />
      )}
      {zone?.setPhaseEntity && (
        <ReviewDialog
          open={phaseChoice !== null}
          onOpenChange={(open) => {
            if (!open) setPhaseChoice(null);
          }}
          controller={controller}
          title={`Move ${zone.name} to ${phaseChoice}?`}
          items={
            phaseChoice
              ? [
                  {
                    change: { entityId: zone.setPhaseEntity, value: phaseChoice },
                    label: `${zone.name} phase`,
                    before: zone.phase,
                    after: phaseChoice,
                  },
                ]
              : []
          }
          note="The controller moves the zone at its next check, within a minute. Today's water and shot counts stay; a zone moved to P1 ramps from its first shot again."
        />
      )}
    </>
  );
}

export function EventList({ events }: { events: Controller["room"]["events"] }) {
  return events.length ? (
    <div className="event-list">
      {events.map((event) => (
        <div className="event-row" key={event.id}>
          <span className={`event-icon event-${event.type}`}>
            {event.type === "water" ? <Droplets size={16} /> : <Activity size={16} />}
          </span>
          <div>
            <p>{event.message}</p>
            <span className="event-meta">
              <EventType type={event.type} />
              {event.zoneId !== undefined ? `Zone ${event.zoneId}` : "Room"}
            </span>
          </div>
          <time dateTime={event.timestamp}>{time(event.timestamp)}</time>
        </div>
      ))}
    </div>
  ) : (
    <Empty
      title="No recorded activity"
      detail="Controller events will appear here when they are available. An empty log does not mean no irrigation occurred."
    />
  );
}
