import { useEffect, useState, type ReactNode } from "react";
import { Activity, ArrowUpRight, Droplets, Info, LoaderCircle } from "lucide-react";
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
import { Badge } from "@/components/ui/badge";
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
import type { Change, Controller, Metric, Series, Zone } from "@/lib/types";

export type Page =
  | "overview"
  | "zones"
  | "strategy"
  | "grow-plan"
  | "insights"
  | "setup"
  | "activity"
  | "sensors"
  | "settings"
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
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
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
export function Status({ enabled, label }: { enabled?: boolean | null; label?: string }) {
  return (
    <Badge
      variant="outline"
      className={
        enabled === true ? "status-good" : enabled === false ? "status-paused" : "status-neutral"
      }
    >
      <span className="status-dot" />
      {label || (enabled === true ? "Enabled" : enabled === false ? "Paused" : "Unavailable")}
    </Badge>
  );
}
export function Metrics({ metrics }: { metrics: Metric[] }) {
  return (
    <div className="metric-strip">
      {metrics.map((metric, i) => (
        <div className="metric-item" key={metric.label}>
          <span className="eyebrow">{metric.label}</span>
          <strong>
            <MetricValue metric={metric} />
          </strong>
          <span className="metric-caption">
            {metric.value === null
              ? "Waiting for controller data"
              : i > 1
                ? "Recorded by the controller"
                : "Across reporting zones"}
          </span>
        </div>
      ))}
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
        if (current) setError(error instanceof Error ? error.message : String(error));
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

export function ZoneTable({ zones, onSelect }: { zones: Zone[]; onSelect: (zone: Zone) => void }) {
  return (
    <>
      <div className="table-scroll zone-table-desktop">
        <table className="data-table">
          <thead>
            <tr>
              <th>Zone</th>
              <th>State / phase</th>
              <th>Moisture</th>
              <th>VWC reference</th>
              <th>Root-zone EC</th>
              <th>Water today</th>
              <th>
                <span className="sr-only">Details</span>
              </th>
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
                  <Status enabled={zone.enabled} />
                  <span className="cell-subtext">{zone.phase || "Phase unavailable"}</span>
                </td>
                <td className="numeric">
                  <MetricValue metric={zone.vwc} />
                </td>
                <td className="numeric muted">
                  <MetricValue metric={zone.target} />
                  <span className="cell-subtext">{zone.target.label}</span>
                </td>
                <td className="numeric">
                  <MetricValue metric={zone.ec} />
                </td>
                <td className="numeric">
                  <MetricValue metric={zone.water} />
                </td>
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
            <p className="small muted">{zone.phase || "Phase unavailable"}</p>
            <div className="zone-mobile-readings">
              <div>
                <span>Moisture</span>
                <strong>
                  <MetricValue metric={zone.vwc} />
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
                  <MetricValue metric={zone.water} />
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
      setErrors([error instanceof Error ? error.message : String(error)]);
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
  useEffect(() => setReview(false), [zone?.id]);
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
              <div className="split-row">
                <Status enabled={zone.enabled} />
                <Badge variant="secondary">{zone.phase || "Phase unavailable"}</Badge>
              </div>
              <p className="muted">{zone.status}</p>
              <div className="detail-metrics">
                {[zone.vwc, zone.target, zone.ec, zone.ecTarget, zone.water, zone.shots].map(
                  (m) => (
                    <div key={m.label}>
                      <span>{m.label}</span>
                      <strong>
                        <MetricValue metric={m} />
                      </strong>
                    </div>
                  ),
                )}
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
            <span>
              {event.zoneId !== undefined ? `Zone ${event.zoneId} · ` : ""}
              {event.type}
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
