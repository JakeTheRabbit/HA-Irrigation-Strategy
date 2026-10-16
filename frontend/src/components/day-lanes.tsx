import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { time as clock } from "@/components/dashboard";
import { UiTip } from "@/components/info-tip";
import { equipmentLanes, laneDevices, phaseId, zoneLanes, type Lane } from "@/lib/day-lanes";
import { growDay, type TimelineRows } from "@/lib/day-timeline";
import { numeric } from "@/lib/model";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";
import "./day-lanes.css";

const PHASE_FILL: Record<string, string> = {
  P0: "var(--phase-p0, #8e5cd9)",
  P1: "var(--phase-p1, #1e88e5)",
  P2: "var(--phase-p2, #00897b)",
  P3: "var(--phase-p3, #7a7f87)",
};

/** Settings › Display › Equipment lanes and Room day lanes, on History › Timeline: the grow day
 * from lights-on, one row per mapped device (on spans) or per zone (phases and shots), so a pump
 * that ran with no valve open, or a zone that lags the others, shows at a glance. Read only. */
export function DayLanes({
  controller,
  mode,
}: {
  controller: Controller;
  mode: "equipment" | "zones";
}) {
  const { room, states } = controller;
  const prefix = room.room.prefix;
  const now = Date.now();
  const day = growDay(
    numeric(states[`number.crop_steering_${prefix}lights_on_hour`]),
    numeric(states[`number.crop_steering_${prefix}lights_off_hour`]),
    now,
    controller.timeZone,
  );
  const devices = laneDevices(states, room);
  const ids =
    mode === "equipment"
      ? devices.map((device) => device.id)
      : room.zones.flatMap((zone) => [
          ...(zone.valveEntity ? [zone.valveEntity] : []),
          ...(states[phaseId(prefix, zone.id)] ? [phaseId(prefix, zone.id)] : []),
        ]);
  const key = day ? [room.room.id, mode, day.start, ...ids].join(" ") : "";
  const [data, setData] = useState<{ key: string; rows: TimelineRows } | null>(null);
  const [error, setError] = useState("");
  const ready = ["live", "demo"].includes(controller.connection);
  const load = controller.timeline;
  useEffect(() => {
    if (!key || !ready || !ids.length || !day) return;
    let current = true;
    setError("");
    load({ entityIds: ids, attributeIds: [], start: day.start, end: Date.now() }).then(
      (rows) => current && setData({ key, rows }),
      (reason) => current && setError(errorText(reason)),
    );
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ready, load]);
  const title = mode === "equipment" ? "Equipment today" : "Zones today";
  if (!day || !ids.length) return null;
  const span = { start: day.start, end: day.end };
  const rows = data?.key === key ? data.rows : null;
  const lanes: Lane[] | null = rows
    ? mode === "equipment"
      ? equipmentLanes(devices, rows, { start: span.start, end: Math.min(now, span.end) })
      : zoneLanes(room, rows, { start: span.start, end: Math.min(now, span.end) })
    : null;
  const x = (time: number) => `${((time - span.start) / (span.end - span.start)) * 100}%`;
  const ticks = Array.from({ length: 5 }, (_, index) => span.start + index * 6 * 3_600_000);
  return (
    <section className="panel day-lanes" aria-labelledby={`lanes-${mode}`} data-day-lanes={mode}>
      <div className="panel-heading">
        <h2 id={`lanes-${mode}`} className="label-with-tip">
          {title}{" "}
          <UiTip copyKey={mode === "equipment" ? "equipment lanes" : "room day lanes"} />
        </h2>
        <span className="small muted">
          From lights-on {clock(day.start)} · lights off {clock(day.lightsOff)}
        </span>
      </div>
      {error ? (
        <p className="small error-text" role="alert">
          {error}
        </p>
      ) : !lanes ? (
        <p className="small muted" role="status">
          <LoaderCircle size={14} className="spin" aria-hidden="true" /> Loading today’s record…
        </p>
      ) : (
        <div className="day-lanes-grid" role="img" aria-label={laneSpeech(title, lanes)}>
          <div className="day-lanes-axis" aria-hidden="true">
            <span />
            <div className="day-lanes-track">
              {ticks.map((tick) => (
                <span key={tick} className="day-lanes-tick" style={{ left: x(tick) }}>
                  {clock(tick)}
                </span>
              ))}
            </div>
          </div>
          {lanes.map((lane) => (
            <div className="day-lanes-row" key={lane.key} data-lane={lane.key}>
              <span className="day-lanes-label">{lane.label}</span>
              <div className="day-lanes-track">
                <span
                  className="day-lanes-night"
                  style={{ left: x(day.lightsOff), width: `calc(100% - ${x(day.lightsOff)})` }}
                />
                {lane.phases.map((band) => (
                  <span
                    key={`${band.phase}-${band.start}`}
                    className="day-lanes-phase"
                    data-phase={band.phase}
                    title={`${band.phase} ${clock(band.start)}–${clock(band.end)}`}
                    style={{
                      left: x(band.start),
                      width: `calc(${x(band.end)} - ${x(band.start)})`,
                      background: PHASE_FILL[band.phase],
                    }}
                  />
                ))}
                {lane.on.map((on) => (
                  <span
                    key={on.start}
                    className={mode === "zones" ? "day-lanes-shot" : "day-lanes-on"}
                    title={`On ${clock(on.start)}–${clock(on.end)}`}
                    style={{
                      left: x(on.start),
                      width: `max(2px, calc(${x(on.end)} - ${x(on.start)}))`,
                    }}
                  />
                ))}
                <span className="day-lanes-now" style={{ left: x(Math.min(now, span.end)) }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function laneSpeech(title: string, lanes: Lane[]) {
  return `${title}: ${lanes
    .map((lane) => `${lane.label}, ${lane.on.length} ${lane.on.length === 1 ? "time" : "times"} on`)
    .join("; ")}.`;
}
