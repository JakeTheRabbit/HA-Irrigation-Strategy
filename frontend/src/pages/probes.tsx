import { useEffect, useState } from "react";
import { ArrowRight, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Empty, Heading, Status, time, type Page } from "@/components/dashboard";
import { JevTrouble, jevUsage } from "@/components/jev-status";
import { Pill, Sparkline } from "@/components/mini-visuals";
import { ageText, readHeartbeat } from "@/lib/controller-health";
import { recentReadings } from "@/lib/dryback";
import { readJev } from "@/lib/jev";
import { descriptor, numeric } from "@/lib/model";
import type { SetupDocument, SetupRoom } from "@/lib/operator-types";
import { PROBE_TONE, zoneProbes, type Probe } from "@/lib/probes";
import type { Controller, EntityState } from "@/lib/types";
import { useRecentHistory } from "@/lib/use-recent-moisture";
import { errorText } from "@/lib/utils";
import "./probes.css";

/** Hours of readings each sparkline draws. */
const RECENT_H = 6;
const asId = (value: unknown) =>
  typeof value === "string" && /^[a-z_]+\.[a-z0-9_]+$/.test(value) ? value : "";

/** Equipment › Probes: is every probe reporting, and believable; which one is off, and since when.
 * Then the valves and pump, the controller's heartbeat and Jev, and, one tap down, the room map and
 * the controller's own sensors. */
export function Probes({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: (page: Page) => void;
}) {
  const { room, states } = controller;
  const now = Date.now();
  const probes = room.zones.flatMap((zone) => zoneProbes(zone, states, now));
  const history = useRecentHistory(
    controller,
    probes.map((probe) => probe.id),
    RECENT_H,
  );
  const config = descriptor(states, room.room)?.attributes ?? {};
  const heartbeat = readHeartbeat(
    states[`sensor.crop_steering_${room.room.prefix}ai_heartbeat`],
    now,
  );
  const status = states[`sensor.crop_steering_${room.room.prefix}app_status`]?.state;
  const jev = readJev(states, room.room.prefix).room;
  const trouble = probes.filter((probe) => probe.health !== "ok").length;
  const hardware = [
    ["Pump", asId(config.pump)],
    ["Main-line valve", asId(config.mainline)],
    ["Feed-water EC", asId(config.feed_ec_sensor)],
    ["Feed-water pH", asId(config.feed_ph_sensor)],
  ].filter(([, id]) => id) as [string, string][];
  return (
    <>
      <Heading title="Probes" />
      <section className="panel probes-status" aria-label="Controller and Jev">
        <div>
          <span className="eyebrow">Probes</span>
          <strong>
            {probes.length - trouble} of {probes.length} OK
          </strong>
          <span className="muted small">
            {trouble ? `${trouble} to look at, below` : "Every probe reports and reads true"}
          </span>
        </div>
        <div>
          <span className="eyebrow">Controller</span>
          <strong>
            {heartbeat.health === "fresh"
              ? "Reporting"
              : heartbeat.health === "stale"
                ? "Not reporting"
                : heartbeat.health === "missing"
                  ? "No heartbeat"
                  : "Heartbeat unreadable"}
          </strong>
          <span className="muted small">
            {heartbeat.at === null
              ? "No time on its last report"
              : `Last report ${ageText(now - heartbeat.at)} ago`}
            {status ? ` · ${status.replaceAll("_", " ")}` : ""}
          </span>
        </div>
        <div>
          <span className="eyebrow">Jev</span>
          <strong>
            {jev ? (jev.state === "error" ? "Not answering" : "On") : "Not on this room"}
          </strong>
          <span className="muted small">
            {jev ? jevUsage(jev, true) || "No calls today" : "The controller runs without it"}
          </span>
        </div>
      </section>
      {jev && <JevTrouble jev={jev} />}
      {room.alerts.length > 0 && (
        <div className="attention-list">
          {room.alerts.map((notice) => (
            <div className={`attention attention-${notice.severity}`} key={notice.id}>
              <div>
                <strong>{notice.title}</strong>
                <p>{notice.detail}</p>
              </div>
            </div>
          ))}
        </div>
      )}
      <section className="panel" aria-labelledby="probes-title">
        <div className="panel-heading">
          <div>
            <h2 id="probes-title">Each zone’s probes</h2>
            <p>
              What each probe reads, when it last reported, and whether the zone’s reading uses it
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => navigate("equipment/setup")}>
            Map probes <ArrowRight size={15} aria-hidden="true" />
          </Button>
        </div>
        {!room.zones.length ? (
          <Empty
            title="No zones discovered"
            detail="Probes appear once the room’s zones are mapped in Setup."
          />
        ) : (
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Probes by zone">
            <table className="data-table probes-table">
              <thead>
                <tr>
                  <th scope="col">Probe</th>
                  <th scope="col">Reading</th>
                  <th scope="col">Last report</th>
                  <th scope="col">Last {RECENT_H} h</th>
                  <th scope="col">Health</th>
                </tr>
              </thead>
              {room.zones.map((zone) => (
                <tbody key={zone.id}>
                  <tr className="probes-zone">
                    <th scope="colgroup" colSpan={5}>
                      {zone.name}
                      <Pill
                        dot
                        tone={
                          zone.valveOn === true ? "on" : zone.valveOn === false ? "off" : "unknown"
                        }
                        title={zone.valveEntity ?? "No valve mapped"}
                        data-zone-valve={zone.id}
                      >
                        Valve{" "}
                        {zone.valveOn === true
                          ? "open"
                          : zone.valveOn === false
                            ? "shut"
                            : "unknown"}
                      </Pill>
                      {zone.enabled === false && (
                        <Status enabled={false} label="Scheduling paused" />
                      )}
                    </th>
                  </tr>
                  {probes
                    .filter((probe) => probe.zone === zone.id)
                    .map((probe) => (
                      <ProbeRow
                        key={probe.id}
                        probe={probe}
                        points={history?.find((series) => series.entityId === probe.id)?.points}
                        now={now}
                      />
                    ))}
                </tbody>
              ))}
            </table>
          </div>
        )}
      </section>
      {hardware.length > 0 && (
        <section className="panel" aria-labelledby="probes-room-title">
          <div className="panel-heading">
            <div>
              <h2 id="probes-room-title">The room’s pump, main line and feed water</h2>
              <p>As Home Assistant reports them. “Off” does not prove a valve closed or no flow.</p>
            </div>
          </div>
          <ul className="probes-hardware">
            {hardware.map(([label, id]) => {
              const entity = states[id];
              return (
                <li key={id}>
                  <span>
                    <strong>{label}</strong>
                    <code>{id}</code>
                  </span>
                  <span className="numeric">
                    {entity
                      ? `${entity.state} ${String(entity.attributes.unit_of_measurement ?? "")}`.trim()
                      : "Not in Home Assistant"}
                  </span>
                  <span className="muted small">
                    {entity?.last_updated ? time(entity.last_updated) : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      <RoomMap controller={controller} navigate={navigate} />
      <ControllerInternals controller={controller} />
      <p className="footnote">
        A probe the zone’s reading leaves out does not steer watering while another one reports.
        Reporting does not prove a probe is calibrated.
      </p>
    </>
  );
}

function ProbeRow({
  probe,
  points,
  now,
}: {
  probe: Probe;
  points: { time: string; value: number }[] | undefined;
  now: number;
}) {
  return (
    <tr data-probe={probe.id} data-health={probe.health}>
      <td>
        <strong>{probe.name}</strong>
        <code className="cell-subtext">{probe.id}</code>
      </td>
      <td className="numeric">
        {probe.value === null ? "—" : `${probe.value} ${probe.unit}`.trim()}
      </td>
      <td>
        {probe.reported === null ? (
          <span className="muted">Not known</span>
        ) : (
          <time
            dateTime={new Date(probe.reported).toISOString()}
            title={new Date(probe.reported).toLocaleString()}
          >
            {ageText(now - probe.reported)} ago
          </time>
        )}
      </td>
      <td data-sensor-trend={probe.id}>
        {points && (
          <Sparkline
            points={recentReadings(points, RECENT_H, probe.value, now)}
            width={110}
            label={`${probe.name} over the last ${RECENT_H} hours`}
          />
        )}
      </td>
      <td>
        <Pill dot tone={PROBE_TONE[probe.health]} data-probe-health={probe.health}>
          {probe.text}
        </Pill>
      </td>
    </tr>
  );
}

/** How the room is wired, from its setup: the pump, the main line, each zone's valve and probes,
 * and the feed-water probes. Read only. */
function RoomMap({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: (page: Page) => void;
}) {
  const [open, setOpen] = useState(false);
  const [setup, setSetup] = useState<SetupRoom | null>(null),
    [mappingError, setMappingError] = useState("");
  const { room, states } = controller;
  const config = descriptor(states, room.room)?.attributes ?? {};
  useEffect(() => {
    setSetup(null);
    setMappingError("");
    let current = true;
    if (!open || !controller.roomId || !["live", "demo"].includes(controller.connection)) return;
    controller
      .operator<SetupDocument>("setup_read")
      .then((result) => {
        if (current)
          setSetup(
            result.rooms.find((item) => item.prefix === room.room.prefix && item.active) || null,
          );
      })
      .catch((error) => {
        if (current) setMappingError(errorText(error));
      });
    return () => {
      current = false;
    };
  }, [open, controller.roomId, controller.connection]);
  const hardware = (key: string, configKey: string) =>
    asId(setup?.hardware[key]) || asId(config[configKey]);
  const mapped = (label: string, entityId: string) => {
    const entity = entityId ? states[entityId] : undefined;
    return (
      <div className="insight-mapping" key={label + entityId}>
        <span>{label}</span>
        <strong>
          {entity
            ? String(entity.attributes.friendly_name || entity.entity_id)
            : entityId
              ? "Mapped · no current state"
              : "Not mapped"}
        </strong>
        {entityId && <code>{entityId}</code>}
        <small>
          {entity
            ? `Last reported: ${entity.state} ${entity.attributes.unit_of_measurement || ""} · ${time(entity.last_updated)}`
            : "Unavailable"}
        </small>
      </div>
    );
  };
  return (
    <details
      className="probes-more"
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>Room map: how the pump, valves and probes connect</summary>
      {open && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>{room.room.name} equipment map</h2>
              <p>Logical connections from configuration · not a measured floor plan</p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => navigate("equipment/setup")}>
              Edit mappings <ArrowRight size={15} aria-hidden="true" />
            </Button>
          </div>
          <div className="insight-room-map">
            <div className="insight-shared-map">
              {mapped("Room pump", hardware("pump_switch", "pump"))}
              <ArrowRight size={19} />
              {mapped("Main-line valve", hardware("main_line_switch", "mainline"))}
            </div>
            <div className="insight-zone-map">
              {room.zones.map((item) => {
                const mapping = setup?.zones.find((zone) => zone.id === item.id);
                const valve =
                  asId(mapping?.valve) ||
                  asId((config.valves as Record<string, unknown> | undefined)?.[item.id]);
                const vwc = mapping?.vwc_sensors?.filter(Boolean) || [];
                const ec = mapping?.ec_sensors?.filter(Boolean) || [];
                return (
                  <section key={item.id}>
                    <div className="insight-map-heading">
                      <h3>{item.name}</h3>
                      <Status enabled={item.enabled} />
                    </div>
                    {mapped("Zone valve", valve)}
                    <div className="insight-probe-links">
                      <strong>VWC probes</strong>
                      {vwc.length
                        ? vwc.map((entity) => mapped("Mapped probe", entity))
                        : mapped("Controller VWC aggregate", item.vwc.entityId || "")}
                      <strong>EC probes</strong>
                      {ec.length
                        ? ec.map((entity) => mapped("Mapped probe", entity))
                        : mapped("Controller EC aggregate", item.ec.entityId || "")}
                    </div>
                  </section>
                );
              })}
            </div>
            <div className="insight-feed-map">
              {mapped("Feed-water EC", hardware("feed_ec_sensor", "feed_ec_sensor"))}
              {mapped("Feed-water pH", hardware("feed_ph_sensor", "feed_ph_sensor"))}
            </div>
          </div>
          {mappingError && (
            <p className="insight-mapping-note">
              Detailed setup mapping could not load: {mappingError}. Available descriptor and
              aggregate entities are shown.
            </p>
          )}
        </section>
      )}
    </details>
  );
}

/** Every sensor of the room the integration and controller publish (phase, waiting for, counts, last
 * irrigation, status...), with its reading and the last hours: one tap down. */
function ControllerInternals({ controller }: { controller: Controller }) {
  const [open, setOpen] = useState(false);
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
  // Every numeric sensor's recent readings in one request, once the list is open.
  const history = useRecentHistory(
    controller,
    open
      ? sensors
          .filter((sensor) => sensor.entity_id.startsWith("sensor.") && numeric(sensor) !== null)
          .map((sensor) => sensor.entity_id)
      : [],
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
  return (
    <details
      className="probes-more"
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>
        Controller internals: every sensor of this room ({reporting} of {sensors.length} reporting)
      </summary>
      {open && (
        <>
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
                      const points = history?.find(
                        (series) => series.entityId === sensor.entity_id,
                      );
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
                                points={recentReadings(
                                  points.points,
                                  RECENT_H,
                                  numeric(sensor),
                                  now,
                                )}
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
        </>
      )}
    </details>
  );
}
