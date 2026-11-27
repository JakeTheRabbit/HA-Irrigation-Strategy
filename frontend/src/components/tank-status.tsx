import { useId } from "react";
import { Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChartKey, NOW_KEY, type KeyItem } from "@/components/chart-key";
import type { Controller } from "@/lib/types";
import { tankTelemetry, type TankReading } from "@/lib/tank-telemetry";
import { TankHistory, TankSparkline, useTankHistory, useTankLines } from "./tank-history";
import { formatDateTime } from "@/lib/clock";
import { clock } from "@/lib/time";
import "./tank-status.css";

export function TankStatus({
  controller,
  onConfigure,
}: {
  controller: Controller;
  onConfigure: () => void;
}) {
  const tank = tankTelemetry(controller.states, controller.room.room);
  const clipId = useId();
  const connected = ["live", "demo"].includes(controller.connection);
  // The last day of EC and pH: the sparklines, and the History panel's first range.
  const recent = useTankHistory(
    controller,
    [tank.ec.entityId, tank.ph.entityId].filter((id): id is string => !!id),
    24,
    true,
  );
  const spark = useTankLines(controller, tank, recent, 24, 96);
  const value = (r: TankReading, digits = 1) =>
    r.value === null
      ? r.issue
      : `${r.value.toLocaleString(undefined, { maximumFractionDigits: digits })} ${r.unit}`;
  const pump = tank.pump.on === null ? tank.pump.issue : tank.pump.on ? "On" : "Off";
  const lastKnown = connected ? "" : " · last known";
  const level = tank.level.value;
  // The drawing's inside runs from y=119 (empty) to y=1 (full): 1.18 units per percent.
  const surface = level === null ? null : 119 - level * 1.18;
  return (
    <section className="panel tank-panel" aria-label="Tank and pump status" data-tank-status>
      <div className="panel-heading">
        <h2>Tank and pump</h2>
        {!connected && <span className="tank-stale">Disconnected · last received</span>}
        <div className="tank-actions">
          <TankHistory
            controller={controller}
            ec={tank.ec}
            ph={tank.ph}
            recent={recent}
            onConfigure={onConfigure}
          />
          <Button variant="ghost" onClick={onConfigure}>
            <Settings2 size={16} /> Map sensors
          </Button>
        </div>
      </div>
      <div className="tank-layout">
        <div
          className="tank-vessel"
          data-tank-level={level ?? "unknown"}
          title={tank.level.entityId || undefined}
        >
          <svg viewBox="0 0 100 120" role="img" aria-label={`Tank level: ${value(tank.level)}`}>
            <defs>
              <clipPath id={clipId}>
                <rect x="1" y="1" width="98" height="118" rx="12" />
              </clipPath>
            </defs>
            <rect x="1" y="1" width="98" height="118" rx="12" className="tank-shell" />
            {surface !== null && (
              <g clipPath={`url(#${clipId})`}>
                <rect x="1" y={surface} width="98" height={119 - surface} className="tank-water" />
                <path d={`M1 ${surface} H99`} className="tank-waterline" />
              </g>
            )}
            {[25, 50, 75].map((p) => (
              <path key={p} d={`M86 ${119 - p * 1.18}h13`} className="tank-tick" />
            ))}
            <text x="50" y="58" textAnchor="middle" className="tank-percent">
              {level === null ? "—" : `${Math.round(level)}%`}
            </text>
            <text x="50" y="76" textAnchor="middle" className="tank-caption">
              {tank.level.issue || "full"}
            </text>
          </svg>
        </div>
        <dl className="tank-quality">
          {(
            [
              // Live: what the tank reads now, apart from a batch's mix-check sample.
              { key: "ec", label: "Live tank EC", reading: tank.ec, digits: 2 },
              { key: "ph", label: "Live tank pH", reading: tank.ph, digits: 2 },
              { key: null, label: "Temperature", reading: tank.temperature, digits: 1 },
            ] as const
          ).map(({ key, label, reading, digits }) => {
            const updated = Date.parse(
              (reading.entityId && controller.states[reading.entityId]?.last_updated) || "",
            );
            return (
            <div key={label} title={reading.entityId || undefined}>
              <dt>
                {label}
                {key && Number.isFinite(updated) && (
                  <small className="tank-updated"> · updated {clock(updated, controller.timeZone)}</small>
                )}
              </dt>
              <dd>
                {key && <TankSparkline which={key} line={spark[key]} end={recent.at} />}
                <span className="tank-value">{value(reading, digits)}</span>
              </dd>
            </div>
            );
          })}
        </dl>
        <ChartKey
          className="tank-spark-key"
          label="Sparkline key"
          items={(["ec", "ph"] as const)
            .filter((key) => spark[key]?.lowest && spark[key]?.highest && recent.at !== null)
            .map(
              (key): KeyItem => ({
                mark: "line",
                color: `var(--tank-${key})`,
                label: `Tank ${key === "ec" ? "EC" : "pH"}`,
                detail: "last 24 h",
              }),
            )
            .concat(recent.at !== null && (spark.ec?.lowest || spark.ph?.lowest) ? [NOW_KEY] : [])}
        />
        <dl className="tank-equipment">
          <div
            className={connected && tank.pump.on ? "is-on" : undefined}
            data-pump-state={tank.pump.on === null ? "unknown" : tank.pump.on ? "on" : "off"}
          >
            <dt>Pump{lastKnown}</dt>
            <dd>{pump}</dd>
          </div>
          <div>
            <dt>Filling{lastKnown}</dt>
            <dd>
              {tank.fill.on === null
                ? tank.fill.issue
                : tank.fill.on
                  ? "Filling now"
                  : "Not filling"}
            </dd>
          </div>
          <div>
            <dt>Last fill</dt>
            <dd>
              {tank.lastFill.timestamp ? (
                <time dateTime={tank.lastFill.timestamp}>
                  {formatDateTime(tank.lastFill.timestamp, {
                    dateStyle: "short",
                    timeStyle: "short",
                  })}
                </time>
              ) : (
                tank.lastFill.issue
              )}
            </dd>
          </div>
        </dl>
        <p className="tank-note">
          Pump: the switch’s report, not measured flow. Last fill: a recorded fill.
        </p>
      </div>
    </section>
  );
}
