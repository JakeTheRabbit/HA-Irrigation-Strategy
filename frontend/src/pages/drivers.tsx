import { useMemo, useState } from "react";
import { LoaderCircle } from "lucide-react";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Empty, Heading } from "@/components/dashboard";
import { useGrids } from "@/components/history-explorer";
import { UiTip } from "@/components/info-tip";
import { growDay } from "@/lib/day-timeline";
import { driverPoints, type Night } from "@/lib/dryback-drivers";
import { SERIES_COLORS, SeriesGrid, stepFor } from "@/lib/history-explorer";
import { descriptor, numeric } from "@/lib/model";
import type { Controller } from "@/lib/types";
import "./drivers.css";

const DAY = 86_400_000;
const DAYS = 14;
const DRIVERS = [
  ["vpd_sensor", "VPD", "kPa"],
  ["temperature_sensor", "Air temperature", "°C"],
  ["humidity_sensor", "Humidity", "%"],
  ["co2_sensor", "CO2", "ppm"],
] as const;

/** History › Dryback drivers (Settings › Display): for the last 14 nights, how fast each zone dried
 * from lights-off to lights-on (VWC points per hour) against the room's mean VPD, temperature,
 * humidity or CO2 that night. A night with a shot is left out. It shows how the two go together,
 * not what caused what. */
export function DrybackDrivers({ controller }: { controller: Controller }) {
  const { room, states, timeZone } = controller;
  const prefix = room.room.prefix;
  const mapped = descriptor(states, room.room)?.attributes ?? {};
  const drivers = DRIVERS.filter(
    ([key]) => typeof mapped[key] === "string" && mapped[key] && states[String(mapped[key])],
  );
  const [choice, setChoice] = useState<string>(drivers[0]?.[0] ?? "");
  const driver = drivers.find(([key]) => key === choice) ?? drivers[0];
  const driverId = driver ? String(mapped[driver[0]]) : null;
  const [now] = useState(() => Date.now());
  const span = { start: now - DAYS * DAY, end: now };
  const step = stepFor(span.end - span.start);
  const zones = room.zones.filter((zone) => zone.vwc.entityId);
  const ids = [...zones.map((zone) => zone.vwc.entityId!), ...(driverId ? [driverId] : [])];
  const connected = ["live", "demo"].includes(controller.connection);
  const on = room.display.options.show_dryback_drivers;
  const recorded = useGrids(controller, ids, [], on && connected && driverId ? span : null, step);
  const list = useMemo(() => {
    const hour = (key: string) => numeric(states[`number.crop_steering_${prefix}lights_${key}_hour`]);
    const seen = new Map<number, Night>();
    for (let t = span.start; t <= span.end; t += DAY / 2) {
      const day = growDay(hour("on"), hour("off"), t, timeZone);
      if (day && day.lightsOff >= span.start && day.end <= span.end)
        seen.set(day.lightsOff, { start: day.lightsOff, end: day.end });
    }
    return [...seen.values()];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [span.start, prefix, timeZone]);
  const points = useMemo(() => {
    if (!driverId) return [];
    const grid = new SeriesGrid(span.start, span.end, step);
    const times = Array.from({ length: grid.length }, (_, i) => grid.timeAt(i));
    const x = recorded.values.get(driverId);
    if (!x) return [];
    return zones.flatMap((zone) => {
      const vwc = recorded.values.get(zone.vwc.entityId!);
      return vwc ? driverPoints(zone.id, times, vwc, x, list) : [];
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recorded.values, recorded.loads, driverId, list]);
  return (
    <>
      <Heading title="Dryback drivers" />
      {!on ? (
        <section className="panel">
          <Empty
            title="This page is off"
            detail="Set Dryback drivers to on in Settings › Display to show this page."
          />
        </section>
      ) : !drivers.length ? (
        <section className="panel">
          <Empty
            title="No climate sensor"
            detail="Add a VPD, temperature, humidity or CO2 sensor to this room in Equipment › Setup."
          />
        </section>
      ) : (
        <section className="panel dryback-drivers" data-dryback-drivers>
          <div className="panel-heading">
            <h2 className="label-with-tip">
              Overnight dryback rate against {driver![1]} <UiTip copyKey="dryback drivers" />
            </h2>
            <label className="dryback-drivers-pick">
              Driver
              <select value={driver![0]} onChange={(event) => setChoice(event.target.value)}>
                {drivers.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="small muted">
            One point for each zone and night of the last {DAYS} days: from lights-off to
            lights-on. A night with a shot is not shown. The chart shows how the two go together. It
            does not show a cause.
          </p>
          {recorded.busy ? (
            <p className="small muted" role="status">
              <LoaderCircle size={14} className="spin" aria-hidden="true" /> Loading day{" "}
              {recorded.busy.done + 1} of {recorded.busy.total}
            </p>
          ) : recorded.error ? (
            <p className="small error-text" role="alert">
              History did not load: {recorded.error}
            </p>
          ) : !points.length ? (
            <p className="small muted">No whole night with readings in the last {DAYS} days.</p>
          ) : (
            <div className="dryback-drivers-chart" role="img" aria-label={`Overnight dryback rate in points per hour against ${driver![1]}, ${points.length} nights`}>
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 16, right: 16, bottom: 24, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 5" stroke="var(--border)" />
                  <XAxis
                    type="number"
                    dataKey="x"
                    name={driver![1]}
                    unit={` ${driver![2]}`}
                    domain={["auto", "auto"]}
                    stroke="var(--muted-foreground)"
                    tickFormatter={(value) => Number(value).toFixed(driver![2] === "kPa" ? 2 : 0)}
                  />
                  <YAxis
                    type="number"
                    dataKey="y"
                    name="Dryback rate"
                    unit=" pp/h"
                    width={70}
                    domain={["auto", "auto"]}
                    stroke="var(--muted-foreground)"
                    tickFormatter={(value) => Number(value).toFixed(2)}
                  />
                  <Tooltip cursor={{ strokeDasharray: "3 3" }} />
                  {zones.map((zone, index) => (
                    <Scatter
                      key={zone.id}
                      name={zone.name}
                      data={points.filter((point) => point.zone === zone.id)}
                      fill={SERIES_COLORS[index % SERIES_COLORS.length]}
                      isAnimationActive={false}
                    />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}
          <ul className="dryback-drivers-legend" aria-label="Zones">
            {zones.map((zone, index) => (
              <li key={zone.id}>
                <i style={{ background: SERIES_COLORS[index % SERIES_COLORS.length] }} />
                {zone.name}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
