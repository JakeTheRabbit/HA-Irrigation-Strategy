import { useEffect, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Droplets,
  FlaskConical,
  Network,
  Radio,
  Waves,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Empty,
  Heading,
  HistoryChart,
  MetricValue,
  Status,
  number,
  time,
  type Page,
} from "@/components/dashboard";
import { calibrateDripper, previewShot } from "@/lib/insights-math";
import type { Controller, Metric, Setting, Zone } from "@/lib/types";
import type { SetupDocument, SetupRoom } from "@/lib/operator-types";
import "./insights.css";

const usable = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const asId = (value: unknown) =>
  typeof value === "string" && /^[a-z_]+\.[a-z0-9_]+$/.test(value) ? value : "";
function configuredSetting(
  controller: Controller,
  zoneId: number | undefined,
  key: string,
): Setting | undefined {
  return (
    controller.room.settings.find(
      (setting) => setting.zoneId === zoneId && setting.entityId.endsWith("_" + key),
    ) ||
    controller.room.settings.find(
      (setting) => setting.zoneId === undefined && setting.entityId.endsWith("_" + key),
    )
  );
}
function Reference({ metric, controller }: { metric: Metric; controller: Controller }) {
  const entity = metric.entityId ? controller.states[metric.entityId] : undefined;
  return (
    <div className="insight-reference">
      <strong>{metric.label}</strong>
      <span>
        <MetricValue metric={metric} />
      </span>
      <small>{entity ? `Updated ${time(entity.last_updated)}` : "Entity not mapped"}</small>
      {metric.entityId && <code>{metric.entityId}</code>}
    </div>
  );
}
export function Insights({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate?: (page: Page, zoneId?: number) => void;
}) {
  const [zoneId, setZoneId] = useState<number | null>(controller.room.zones[0]?.id ?? null);
  const [setup, setSetup] = useState<SetupRoom | null>(null),
    [mappingError, setMappingError] = useState("");
  const [catchMl, setCatchMl] = useState(""),
    [catchMinutes, setCatchMinutes] = useState(""),
    [useCatchFlow, setUseCatchFlow] = useState(false),
    [shotPercent, setShotPercent] = useState("");
  const zone = controller.room.zones.find((item) => item.id === zoneId) || controller.room.zones[0];
  const descriptor = controller.room.entities.find(
    (entity) =>
      entity.attributes.prefix === controller.room.room.prefix &&
      entity.entity_id.endsWith("_engine_config"),
  );
  useEffect(() => {
    setSetup(null);
    setMappingError("");
    setUseCatchFlow(false);
    setCatchMl("");
    setCatchMinutes("");
    let current = true;
    if (!controller.roomId || !["live", "demo"].includes(controller.connection)) return;
    controller
      .operator<SetupDocument>("setup_read")
      .then((result) => {
        if (current)
          setSetup(
            result.rooms.find(
              (room) => room.prefix === controller.room.room.prefix && room.active,
            ) || null,
          );
      })
      .catch((error) => {
        if (current) setMappingError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      current = false;
    };
  }, [controller.roomId, controller.connection]);
  useEffect(() => {
    setZoneId(controller.room.zones[0]?.id ?? null);
    setShotPercent("");
  }, [controller.roomId]);
  const mappedZone = setup?.zones.find((item) => item.id === zone?.id);
  const read = (key: string, fallback?: number) => {
    const setting = configuredSetting(controller, zone?.id, key);
    return setting?.value !== null && setting?.value !== undefined
      ? setting.value
      : usable(fallback)
        ? fallback
        : null;
  };
  const substrate = read("substrate_volume", mappedZone?.substrate_volume),
    plants = read("plant_count", mappedZone?.plant_count),
    drippers = read("drippers_per_plant", mappedZone?.drippers_per_plant),
    configuredFlow = read("dripper_flow_rate", mappedZone?.dripper_flow_rate);
  const catchFlow =
    catchMl.trim() && catchMinutes.trim()
      ? calibrateDripper(Number(catchMl), Number(catchMinutes))
      : null;
  const effectiveFlow = useCatchFlow && catchFlow !== null ? catchFlow : configuredFlow;
  const percent = shotPercent.trim() ? Number(shotPercent) : read("p2_shot_size");
  const hydraulicInputs = {
    substrateL: substrate ?? NaN,
    plants: plants ?? NaN,
    drippersPerPlant: drippers ?? NaN,
    flowLph: effectiveFlow ?? NaN,
    shotPercent: percent ?? NaN,
  };
  const preview = previewShot(hydraulicInputs);
  const hydraulicMissing = [
    substrate === null ? "substrate volume" : null,
    plants === null ? "plant count" : null,
    drippers === null ? "drippers per plant" : null,
    effectiveFlow === null ? "dripper flow" : null,
  ].filter(Boolean);
  const references = zone ? [zone.vwc, zone.target, zone.ec, zone.ecTarget] : [];
  const readyProbes = controller.room.zones.filter(
    (item) => item.vwc.value !== null && item.ec.value !== null,
  ).length;
  const meanShot =
    zone && zone.water.value !== null && zone.shots.value !== null && zone.shots.value > 0
      ? zone.water.value / zone.shots.value
      : null;
  const delta = (metric: Metric, target: Metric) =>
    metric.value !== null && target.value !== null ? metric.value - target.value : null;
  const vwcDelta = zone ? delta(zone.vwc, zone.target) : null,
    ecDelta = zone ? delta(zone.ec, zone.ecTarget) : null;
  const open = (page: Page) => {
    if (navigate) navigate(page, zone?.id);
    else window.location.hash = `/${page}`;
  };
  function mappedEntity(label: string, entityId: string) {
    const entity = entityId ? controller.states[entityId] : undefined;
    const aggregate = controller.room.zones
      .flatMap((item) => [item.vwc, item.ec])
      .find((metric) => metric.entityId === entityId);
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
          {aggregate?.value === null
            ? "Current reading unavailable / unverified"
            : entity
              ? `Last reported: ${entity.state} ${entity.attributes.unit_of_measurement || ""} · ${time(entity.last_updated)}`
              : "Unavailable"}
        </small>
      </div>
    );
  }
  const hardware = (key: string, descriptorKey: string) =>
    asId(setup?.hardware[key]) || asId(descriptor?.attributes[descriptorKey]);
  const pump = hardware("pump_switch", "pump"),
    mainline = hardware("main_line_switch", "mainline");
  return (
    <div className="insights-page">
      <Heading
        title="Insights"
        description="Investigate root-zone readings, check water calculations and inspect the room’s mapped equipment."
        action={
          <Button variant="outline" onClick={() => open("setup")}>
            Room setup <ArrowUpRight size={16} />
          </Button>
        }
      />
      {!zone ? (
        <section className="panel">
          <Empty
            title="Choose a configured room"
            detail="Diagnostics need a discovered zone and its controller entities."
            action={<Button onClick={() => open("setup")}>Open room setup</Button>}
          />
        </section>
      ) : (
        <>
          <div className="insight-summary">
            <div>
              <Radio size={19} />
              <strong>
                {readyProbes}/{controller.room.zones.length}
              </strong>
              <span>zones with current VWC + EC</span>
            </div>
            <div>
              <Droplets size={19} />
              <strong>
                {number(zone.water.value)} <small>L</small>
              </strong>
              <span>{zone.name} · recorded today</span>
            </div>
            <div>
              <Waves size={19} />
              <strong>
                {number(meanShot, 2)} <small>{meanShot !== null ? "L/shot" : ""}</small>
              </strong>
              <span>recorded daily mean</span>
            </div>
          </div>
          <div className="insight-zone-picker">
            <Label htmlFor="insights-zone">Inspect zone</Label>
            <select
              id="insights-zone"
              value={zone.id}
              onChange={(event) => {
                setZoneId(Number(event.target.value));
                setShotPercent("");
                setUseCatchFlow(false);
              }}
            >
              {controller.room.zones.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <Status enabled={zone.enabled} />
            <span className="muted small">{zone.phase}</span>
          </div>
          <Tabs defaultValue="diagnostics">
            <TabsList className="insight-tabs">
              <TabsTrigger value="diagnostics">
                <Radio size={15} />
                Root-zone diagnostics
              </TabsTrigger>
              <TabsTrigger value="water">
                <FlaskConical size={15} />
                Water & calibration
              </TabsTrigger>
              <TabsTrigger value="map">
                <Network size={15} />
                Room map
              </TabsTrigger>
            </TabsList>
            <TabsContent value="diagnostics">
              <div className="insight-references">
                {references.map((metric) => (
                  <Reference key={metric.label} metric={metric} controller={controller} />
                ))}
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>What the readings show</h2>
                    <p>{zone.name} · compared with the current phase references</p>
                  </div>
                  <Button variant="ghost" onClick={() => open("strategy")}>
                    Review settings <ArrowRight size={16} />
                  </Button>
                </div>
                <div className="insight-findings">
                  <div>
                    <strong>Moisture difference</strong>
                    <p>
                      {vwcDelta === null
                        ? "A current VWC reading and phase reference are both needed for this comparison."
                        : `${Math.abs(vwcDelta).toFixed(1)} percentage points ${vwcDelta < 0 ? "below" : vwcDelta > 0 ? "above" : "from"} ${zone.target.label.toLowerCase()}.`}
                    </p>
                    <small>
                      {zone.phase === "P2"
                        ? "This is the base threshold. The controller may adjust it for EC."
                        : zone.phase === "P3"
                          ? "The emergency floor is a safety threshold, not a routine irrigation target."
                          : "A difference alone does not establish that an irrigation is due."}
                    </small>
                  </div>
                  <div>
                    <strong>EC difference</strong>
                    <p>
                      {ecDelta === null
                        ? "A current EC reading and supported phase target are needed for this comparison."
                        : `${Math.abs(ecDelta).toFixed(2)} mS/cm ${ecDelta < 0 ? "below" : ecDelta > 0 ? "above" : "from"} the selected phase EC target.`}
                    </p>
                    <small>
                      Root-zone EC and feed-water EC describe different measurements. This
                      comparison does not prescribe a feed adjustment.
                    </small>
                  </div>
                </div>
                {controller.room.alerts
                  .filter((notice) => notice.zoneId === undefined || notice.zoneId === zone.id)
                  .map((notice) => (
                    <div className="insight-notice" key={notice.id}>
                      <strong>{notice.title}</strong>
                      <p>{notice.detail}</p>
                    </div>
                  ))}
              </section>
              <HistoryChart controller={controller} zones={[zone]} />
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Probe coverage</h2>
                    <p>Controller-valid readings across the room</p>
                  </div>
                  <Button variant="ghost" onClick={() => open("sensors")}>
                    All sensors <ArrowRight size={16} />
                  </Button>
                </div>
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Zone</th>
                        <th>VWC</th>
                        <th>EC</th>
                        <th>Scheduling</th>
                      </tr>
                    </thead>
                    <tbody>
                      {controller.room.zones.map((item) => (
                        <tr key={item.id}>
                          <td>{item.name}</td>
                          <td>
                            <Status
                              enabled={item.vwc.value !== null ? true : null}
                              label={
                                item.vwc.value !== null ? "Current" : "Unavailable / unverified"
                              }
                            />
                          </td>
                          <td>
                            <Status
                              enabled={item.ec.value !== null ? true : null}
                              label={
                                item.ec.value !== null ? "Current" : "Unavailable / unverified"
                              }
                            />
                          </td>
                          <td>
                            <Status enabled={item.enabled} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </TabsContent>
            <TabsContent value="water">
              <div className="insight-water-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Nominal shot calculator</h2>
                      <p>{zone.name} · based on supplied hydraulic settings</p>
                    </div>
                    <Badge variant="outline">Local preview</Badge>
                  </div>
                  <div className="insight-calculator">
                    <div className="insight-hydraulics">
                      {[
                        ["Substrate per plant", substrate, "L"],
                        ["Plant count", plants, ""],
                        ["Drippers per plant", drippers, ""],
                        ["Flow per dripper", effectiveFlow, "L/h"],
                      ].map(([label, value, unit]) => (
                        <div key={String(label)}>
                          <span>{label}</span>
                          <strong>
                            {number(value as number | null)} <small>{unit}</small>
                          </strong>
                        </div>
                      ))}
                    </div>
                    {hydraulicMissing.length > 0 && (
                      <p className="notice-inline">
                        Missing configuration: {hydraulicMissing.join(", ")}. Set these values in
                        Room setup before calculating a duration.
                      </p>
                    )}
                    <Label htmlFor="insight-shot-percent">Shot size · % of substrate volume</Label>
                    <Input
                      id="insight-shot-percent"
                      type="number"
                      min="0"
                      max="100"
                      step="0.5"
                      value={shotPercent || (percent ?? "")}
                      placeholder="Enter a shot percentage"
                      onChange={(event) => setShotPercent(event.target.value)}
                    />
                    {preview ? (
                      <div className="insight-result-grid">
                        <div>
                          <span>Nominal zone volume</span>
                          <strong>
                            {number(preview.volumeL, 2)} <small>L</small>
                          </strong>
                        </div>
                        <div>
                          <span>Volume per plant</span>
                          <strong>
                            {number(preview.volumeMlPerPlant, 0)} <small>mL</small>
                          </strong>
                        </div>
                        <div>
                          <span>Nominal valve-open time</span>
                          <strong>
                            {number(preview.durationSeconds, 1)} <small>seconds</small>
                          </strong>
                        </div>
                      </div>
                    ) : (
                      <p className="muted small">
                        Use known positive hydraulic values and a shot percentage from 0 to 100.
                      </p>
                    )}
                    <p className="small muted">
                      Volume = substrate litres × plants × shot %. Duration = volume ÷ total dripper
                      flow. Assumes uniform rated flow; pressure, valve delays, runoff, runtime caps
                      and controller adjustments are not included.
                    </p>
                    {useCatchFlow && (
                      <p className="notice-inline">
                        Using your catch-test flow estimate for this local preview only.
                      </p>
                    )}
                  </div>
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Catch-test calibration</h2>
                      <p>Estimate actual flow from one dripper</p>
                    </div>
                  </div>
                  <div className="insight-calculator">
                    <p className="small muted">
                      Collect water from a representative dripper for a measured duration. Enter the
                      collected volume per dripper.
                    </p>
                    <Label htmlFor="catch-volume">Collected water per dripper · mL</Label>
                    <Input
                      id="catch-volume"
                      type="number"
                      min="0"
                      step="1"
                      placeholder="e.g. 200"
                      value={catchMl}
                      onChange={(event) => {
                        setCatchMl(event.target.value);
                        setUseCatchFlow(false);
                      }}
                    />
                    <Label htmlFor="catch-time">Collection time · minutes</Label>
                    <Input
                      id="catch-time"
                      type="number"
                      min="0"
                      step="0.1"
                      placeholder="e.g. 3"
                      value={catchMinutes}
                      onChange={(event) => {
                        setCatchMinutes(event.target.value);
                        setUseCatchFlow(false);
                      }}
                    />
                    <div className="insight-catch-result">
                      <span>Estimated flow per dripper</span>
                      <strong>
                        {number(catchFlow, 2)} <small>{catchFlow !== null ? "L/h" : ""}</small>
                      </strong>
                      {catchFlow !== null && configuredFlow !== null && configuredFlow > 0 && (
                        <p>
                          {number(
                            Math.abs(((catchFlow - configuredFlow) / configuredFlow) * 100),
                            1,
                          )}
                          % {catchFlow < configuredFlow ? "below" : "above"} configured{" "}
                          {number(configuredFlow, 2)} L/h.
                        </p>
                      )}
                    </div>
                    <Button
                      variant="outline"
                      disabled={catchFlow === null}
                      onClick={() => setUseCatchFlow(true)}
                    >
                      Use estimate in local preview
                    </Button>
                    {useCatchFlow && (
                      <Button variant="ghost" onClick={() => setUseCatchFlow(false)}>
                        Return to configured flow
                      </Button>
                    )}
                    <p className="small muted">
                      This calculator does not write calibration or operate irrigation. Check
                      several drippers before choosing a configuration change.
                    </p>
                  </div>
                </section>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Configured shot references</h2>
                    <p>Nominal values from this zone’s settings</p>
                  </div>
                </div>
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Phase setting</th>
                        <th>Substrate volume</th>
                        <th>Zone litres</th>
                        <th>Nominal seconds</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        ["P1 initial shot", "p1_initial_shot_size"],
                        ["P2 maintenance shot", "p2_shot_size"],
                        ["P3 emergency shot", "p3_emergency_shot_size"],
                      ].map(([label, key]) => {
                        const setting = configuredSetting(controller, zone.id, key),
                          result =
                            setting?.value !== null && setting?.value !== undefined
                              ? previewShot({ ...hydraulicInputs, shotPercent: setting.value })
                              : null;
                        return (
                          <tr key={key}>
                            <td>
                              {label}
                              {setting && <code className="cell-subtext">{setting.entityId}</code>}
                            </td>
                            <td>
                              {number(setting?.value ?? null)}
                              {setting?.value !== null && setting?.value !== undefined ? "%" : ""}
                            </td>
                            <td>{number(result?.volumeL ?? null, 2)}</td>
                            <td>{number(result?.durationSeconds ?? null, 1)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
              <p className="footnote">
                Recorded daily mean: {number(meanShot, 2)} {meanShot !== null ? "L/shot" : ""}.
                Actual shots can differ by phase and controller adjustment; this mean is not a
                calibration measurement.
              </p>
            </TabsContent>
            <TabsContent value="map">
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>{controller.room.room.name} equipment map</h2>
                    <p>Logical connections from configuration · not a measured floor plan</p>
                  </div>
                  <Button variant="ghost" onClick={() => open("setup")}>
                    Edit mappings <ArrowRight size={16} />
                  </Button>
                </div>
                <div className="insight-room-map">
                  <div className="insight-shared-map">
                    {mappedEntity("Room pump", pump)}
                    <ArrowRight size={19} />
                    {mappedEntity("Mainline valve", mainline)}
                  </div>
                  <div className="insight-zone-map">
                    {controller.room.zones.map((item) => {
                      const mapping = setup?.zones.find((z) => z.id === item.id);
                      const valve =
                        asId(mapping?.valve) ||
                        asId(
                          (descriptor?.attributes.valves as Record<string, unknown> | undefined)?.[
                            item.id
                          ],
                        );
                      const vwc = mapping?.vwc_sensors?.filter(Boolean) || [];
                      const ec = mapping?.ec_sensors?.filter(Boolean) || [];
                      return (
                        <section key={item.id} className={item.id === zone.id ? "selected" : ""}>
                          <div className="insight-map-heading">
                            <h3>{item.name}</h3>
                            <Status enabled={item.enabled} />
                          </div>
                          {mappedEntity("Zone valve", valve)}
                          <div className="insight-probe-links">
                            <strong>VWC probes</strong>
                            {vwc.length
                              ? vwc.map((entity) => mappedEntity("Mapped probe", entity))
                              : mappedEntity("Controller VWC aggregate", item.vwc.entityId || "")}
                            <strong>EC probes</strong>
                            {ec.length
                              ? ec.map((entity) => mappedEntity("Mapped probe", entity))
                              : mappedEntity("Controller EC aggregate", item.ec.entityId || "")}
                          </div>
                        </section>
                      );
                    })}
                  </div>
                  <div className="insight-feed-map">
                    {mappedEntity("Feed-water EC", hardware("feed_ec_sensor", "feed_ec_sensor"))}
                    {mappedEntity("Feed-water pH", hardware("feed_ph_sensor", "feed_ph_sensor"))}
                  </div>
                </div>
                {mappingError && (
                  <p className="insight-mapping-note">
                    Detailed setup mapping could not load: {mappingError}. Available descriptor and
                    aggregate entities are shown.
                  </p>
                )}
              </section>
              <p className="footnote">
                Mapped equipment state is shown for inspection only. “Off” does not prove valve
                closure or zero flow. No equipment can be operated from this diagram.
              </p>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}
