import { useId } from "react";
import { Droplets, FlaskConical, Gauge, Settings2, Thermometer, Waves } from "lucide-react";
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
  return (
    <section className="panel tank-panel" aria-label="Tank and pump status" data-tank-status>
      <div className="panel-heading">
        <div>
          <h2>Tank & pump</h2>
          <p>
            {connected
              ? "Mapped equipment readings for this room"
              : "Disconnected · readings below are last received"}
          </p>
        </div>
        <Button variant="ghost" onClick={onConfigure}>
          <Settings2 size={16} /> Map sensors
        </Button>
      </div>
      <div className="tank-layout">
        <div className="tank-vessel" data-tank-level={tank.level.value ?? "unknown"}>
          <svg viewBox="0 0 180 170" role="img" aria-label={`Tank level: ${value(tank.level)}`}>
            <defs>
              <clipPath id={clipId}>
                <rect x="27" y="15" width="126" height="140" rx="17" />
              </clipPath>
            </defs>
            <rect x="27" y="15" width="126" height="140" rx="17" className="tank-shell" />
            {tank.level.value !== null && (
              <g clipPath={`url(#${clipId})`}>
                <rect
                  x="27"
                  y={155 - tank.level.value * 1.4}
                  width="126"
                  height={tank.level.value * 1.4}
                  className="tank-water"
                />
                <path d={`M27 ${155 - tank.level.value * 1.4} H153`} className="tank-waterline" />
              </g>
            )}
            {[25, 50, 75].map((p) => (
              <path key={p} d={`M139 ${155 - p * 1.4}h14`} className="tank-tick" />
            ))}
            <text x="90" y="86" textAnchor="middle" className="tank-percent">
              {tank.level.value === null ? "—" : `${Math.round(tank.level.value)}%`}
            </text>
            <text x="90" y="108" textAnchor="middle" className="tank-caption">
              {tank.level.issue || "full"}
            </text>
          </svg>
          <span className="muted small" title={tank.level.entityId || undefined}>
            Tank fill level
          </span>
        </div>
        <div className="tank-equipment">
          <div
            className={`tank-pump ${connected && tank.pump.on ? "is-on" : ""}`}
            data-pump-state={tank.pump.on === null ? "unknown" : tank.pump.on ? "on" : "off"}
          >
            <span className="tank-pump-icon">
              <Gauge size={26} />
            </span>
            <div>
              <span className="muted small">Room pump{!connected && " · last known"}</span>
              <strong>{pump}</strong>
            </div>
            <span className="tank-pipe" aria-hidden="true" />
            <Droplets size={23} aria-hidden="true" />
          </div>
          <div className="tank-fill-record">
            <Waves size={19} />
            <div>
              <span className="muted small">Tank filling{!connected && " · last known"}</span>
              <strong>
                {tank.fill.on === null
                  ? tank.fill.issue
                  : tank.fill.on
                    ? "Filling now"
                    : "Not filling"}
              </strong>
            </div>
          </div>
          <div className="tank-fill-record">
            <Droplets size={19} />
            <div>
              <span className="muted small">Last recorded fill</span>
              {tank.lastFill.timestamp ? (
                <time dateTime={tank.lastFill.timestamp}>
                  {new Date(tank.lastFill.timestamp).toLocaleString()}
                </time>
              ) : (
                <strong>{tank.lastFill.issue}</strong>
              )}
            </div>
          </div>
        </div>
        <div className="tank-quality">
          {[
            { label: "Tank EC", reading: tank.ec, Icon: Waves, digits: 2 },
            { label: "Tank pH", reading: tank.ph, Icon: FlaskConical, digits: 2 },
            { label: "Tank temperature", reading: tank.temperature, Icon: Thermometer, digits: 1 },
          ].map(({ label, reading, Icon, digits }) => (
            <div className="tank-quality-item" key={label} title={reading.entityId || undefined}>
              <Icon size={21} />
              <div>
                <span className="muted small">{label}</span>
                <strong>{value(reading, digits)}</strong>
              </div>
            </div>
          ))}
        </div>
      </div>
      <p className="tank-note muted small">
        Pump state is the mapped switch report. Last fill requires a recorded fill timestamp; sensor
        updates are not fill events.
      </p>
    </section>
  );
}
