import { useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Empty, Heading, time } from "@/components/dashboard";
import { Pill, Sparkline } from "@/components/mini-visuals";
import { recentReadings } from "@/lib/dryback";
import { numeric } from "@/lib/model";
import { useRecentHistory } from "@/lib/use-recent-moisture";
import type { Controller, EntityState } from "@/lib/types";

/** Hours of readings each numeric sensor draws. */
const RECENT_H = 6;

export function Sensors({ controller }: { controller: Controller }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const rawAvailable = (state: string) =>
    !["unavailable", "unknown", "none", ""].includes(state.toLowerCase());
  const unverifiedProbeIds = new Set(
    controller.room.zones
      .flatMap((zone) => [zone.vwc, zone.ec])
      .filter((metric) => metric.entityId !== null && metric.value === null)
      .map((metric) => metric.entityId),
  );
  const isUnverifiedProbe = (sensor: EntityState) =>
    rawAvailable(sensor.state) && unverifiedProbeIds.has(sensor.entity_id);
  const isAvailable = (sensor: EntityState) =>
    rawAvailable(sensor.state) && !isUnverifiedProbe(sensor);
  const sensors = controller.room.entities.filter(
    (e) => e.entity_id.startsWith("sensor.") || e.entity_id.startsWith("binary_sensor."),
  );
  // Every numeric sensor's recent readings in one request, never one per row.
  const history = useRecentHistory(
    controller,
    sensors
      .filter((sensor) => sensor.entity_id.startsWith("sensor.") && numeric(sensor) !== null)
      .map((sensor) => sensor.entity_id),
    RECENT_H,
  );
  const now = Date.now();
  const visible = sensors.filter(
    (e) =>
      `${e.entity_id} ${e.attributes.friendly_name || ""}`
        .toLowerCase()
        .includes(query.toLowerCase()) &&
      (status === "all" || (status === "available") === isAvailable(e)),
  );
  const reporting = sensors.filter((e) => isAvailable(e)).length;
  // Red once any sensor is down; amber while the only ones not reporting are stale probes.
  const unavailableTone =
    reporting === sensors.length
      ? "neutral"
      : sensors.some((e) => !rawAvailable(e.state))
        ? "off"
        : "warn";
  return (
    <>
      <Heading title="Sensors" />
      <div className="sensor-summary">
        <span>
          <strong>{sensors.length}</strong> sensor entities
        </span>
        <Pill dot tone={reporting ? "on" : "neutral"}>
          {reporting} reporting
        </Pill>
        <Pill dot tone={unavailableTone}>
          {sensors.length - reporting} unavailable
        </Pill>
      </div>
      {controller.room.alerts.length > 0 && (
        <div className="attention-list">
          {controller.room.alerts.map((notice) => (
            <div className={`attention attention-${notice.severity}`} key={notice.id}>
              <div>
                <strong>{notice.title}</strong>
                <p>{notice.detail}</p>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="toolbar">
        <div className="search-field">
          <Search size={17} />
          <Input
            aria-label="Search sensors"
            placeholder="Search name or entity ID…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select
          aria-label="Filter sensor availability"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">All statuses</option>
          <option value="available">Reporting</option>
          <option value="unavailable">Unavailable</option>
        </select>
        <span className="muted small">{visible.length} results</span>
      </div>
      <section className="panel">
        {!visible.length ? (
          <Empty
            title="No matching sensors"
            detail={
              sensors.length
                ? "Clear your filters to see all sensor entities."
                : "No sensor entities were discovered for this room. Check the connection and controller configuration."
            }
            action={
              sensors.length ? (
                <Button
                  variant="outline"
                  onClick={() => {
                    setQuery("");
                    setStatus("all");
                  }}
                >
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="table-scroll">
            <table className="data-table sensors-table">
              <thead>
                <tr>
                  <th>Sensor</th>
                  <th>Reading</th>
                  <th>Last {RECENT_H} hours</th>
                  <th>Availability</th>
                  <th>Last updated</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((sensor) => {
                  const name = String(sensor.attributes.friendly_name || sensor.entity_id);
                  const points = history?.find((series) => series.entityId === sensor.entity_id);
                  return (
                    <tr key={sensor.entity_id}>
                      <td>
                        <strong>{name}</strong>
                        <code className="cell-subtext">{sensor.entity_id}</code>
                      </td>
                      <td className="numeric">
                        {isAvailable(sensor)
                          ? `${sensor.state} ${sensor.attributes.unit_of_measurement || ""}`
                          : "Unavailable"}
                      </td>
                      <td data-sensor-trend={sensor.entity_id}>
                        {points && (
                          <Sparkline
                            points={recentReadings(points.points, RECENT_H, numeric(sensor), now)}
                            width={96}
                            label={`${name} over the last ${RECENT_H} hours`}
                          />
                        )}
                      </td>
                      <td>
                        {isUnverifiedProbe(sensor) ? (
                          <Pill dot tone="warn">
                            Stale or unverified
                          </Pill>
                        ) : isAvailable(sensor) ? (
                          <Pill dot tone="on">
                            Reporting
                          </Pill>
                        ) : (
                          <Pill dot tone="off">
                            Unavailable
                          </Pill>
                        )}
                      </td>
                      <td>
                        <time
                          title={sensor.last_updated || "No timestamp"}
                          dateTime={sensor.last_updated}
                        >
                          {time(sensor.last_updated)}
                        </time>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <p className="footnote">
        Stale or unverified probes are excluded from reporting totals. Availability does not confirm
        calibration.
      </p>
    </>
  );
}
