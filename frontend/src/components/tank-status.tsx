import { useId } from "react";
import { Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Controller } from "@/lib/types";
import { tankTelemetry, type TankReading } from "@/lib/tank-telemetry";
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
        <h2>Tank & pump</h2>
        {!connected && <span className="tank-stale">Disconnected · last received</span>}
        <Button variant="ghost" onClick={onConfigure}>
          <Settings2 size={16} /> Map sensors
        </Button>
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
          {[
            { label: "EC", reading: tank.ec, digits: 2 },
            { label: "pH", reading: tank.ph, digits: 2 },
            { label: "Temperature", reading: tank.temperature, digits: 1 },
          ].map(({ label, reading, digits }) => (
            <div key={label} title={reading.entityId || undefined}>
              <dt>{label}</dt>
              <dd>{value(reading, digits)}</dd>
            </div>
          ))}
        </dl>
        <dl className="tank-equipment">
          <div
            className={connected && tank.pump.on ? "is-on" : undefined}
            data-pump-state={tank.pump.on === null ? "unknown" : tank.pump.on ? "on" : "off"}
            title="The mapped pump switch's report. It does not prove water is flowing."
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
          <div title="A recorded fill event. Sensor updates are not fills.">
            <dt>Last fill</dt>
            <dd>
              {tank.lastFill.timestamp ? (
                <time dateTime={tank.lastFill.timestamp}>
                  {new Date(tank.lastFill.timestamp).toLocaleString([], {
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
      </div>
    </section>
  );
}
