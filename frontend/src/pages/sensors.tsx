import { useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Empty, Heading, Status, time } from "@/components/dashboard";
import type { Controller, EntityState } from "@/lib/types";

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
  const visible = sensors.filter(
    (e) =>
      `${e.entity_id} ${e.attributes.friendly_name || ""}`
        .toLowerCase()
        .includes(query.toLowerCase()) &&
      (status === "all" || (status === "available") === isAvailable(e)),
  );
  return (
    <>
      <Heading
        title="Sensors"
        description="Inspect measurements and availability reported by Home Assistant."
      />
      <div className="sensor-summary">
        <span>
          <strong>{sensors.length}</strong> sensor entities
        </span>
        <span>
          <i className="health-dot" />
          <strong>{sensors.filter((e) => isAvailable(e)).length}</strong> reporting
        </span>
        <span>
          <i className="health-dot warning-dot" />
          <strong>{sensors.filter((e) => !isAvailable(e)).length}</strong> unavailable
        </span>
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
                  <th>Availability</th>
                  <th>Last updated</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((sensor) => (
                  <tr key={sensor.entity_id}>
                    <td>
                      <strong>{String(sensor.attributes.friendly_name || sensor.entity_id)}</strong>
                      <code className="cell-subtext">{sensor.entity_id}</code>
                    </td>
                    <td className="numeric">
                      {isAvailable(sensor)
                        ? `${sensor.state} ${sensor.attributes.unit_of_measurement || ""}`
                        : "Unavailable"}
                    </td>
                    <td>
                      <Status
                        enabled={isAvailable(sensor) ? true : null}
                        label={
                          isUnverifiedProbe(sensor)
                            ? "Stale or unverified"
                            : isAvailable(sensor)
                              ? "Reporting"
                              : "Unavailable"
                        }
                      />
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
                ))}
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
