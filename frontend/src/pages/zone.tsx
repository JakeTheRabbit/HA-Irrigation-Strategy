import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, ArrowRight, Check, X } from "lucide-react";
import { toast } from "sonner";
import { CanonicalControls } from "@/components/canonical-controls";
import { Button } from "@/components/ui/button";
import { Empty, number, ReviewDialog, time as clock, type Page } from "@/components/dashboard";
import { useBrain } from "@/lib/brain";
import { CameraCard, ClimatePanel, HardwarePanel, RootZonePanel } from "@/components/zone-extras";
import { UiTip } from "@/components/info-tip";
import { ZoneDay } from "@/components/day-timeline";
import { NeedsIntegration } from "@/components/needs-integration";
import { OverlayRows, useOverlays } from "@/components/overlay-row";
import { Pill } from "@/components/mini-visuals";
import { PlantStressCard, ZoneGates, ZoneShots } from "@/components/sensing";
import { addDays, midnight } from "@/lib/comparison";
import type { RunsDocument } from "@/lib/comparison-types";
import { rangeText, steeringOf } from "@/lib/day-chart";
import { growDay, type DayTrace, type GrowDay } from "@/lib/day-timeline";
import { formatEc, formatVolume, getDisplayUnits } from "@/lib/display-units";
import { ZONE_MODE } from "@/lib/facility-view";
import type { GaugeModel } from "@/lib/hmi";
import {
  attachOutcomes,
  brainWords,
  jevAnswer,
  jevIds,
  jevResult,
  JEV_TITLES,
  outcomeText,
  parseBrainAnswers,
  parseJevSetpoints,
  parseJevZone,
  readJev,
  type JevSetpoints,
} from "@/lib/jev";
import { numeric } from "@/lib/model";
import { overlayLabel, zoneOverlays, type Overlay, type OverlayDocument } from "@/lib/overlays";
import { pagedQuery } from "@/lib/parity-api";
import { smoothRecorded } from "@/lib/planning-curve";
import { buildSetpointPreview } from "@/lib/setpoint-preview";
import { jevChip, TARGET_GROUPS } from "@/lib/targets";
import { ecType, fusionMethod, PROBE_TONE, zoneProbes } from "@/lib/probes";
import { clock as wallClock } from "@/lib/time";
import { roomView } from "@/lib/today-room";
import type { Controller, Zone } from "@/lib/types";
import { offerUndo } from "@/lib/undo";
import { useRecentHistory } from "@/lib/use-recent-moisture";
import { dayWord, errorText } from "@/lib/utils";
import { waitingText } from "@/lib/waiting-for";
import { zonePlants } from "@/lib/water-view";
import { aiRead, zoneReasons } from "@/lib/zone-why";
import { shotLog, tableShotLog, vwcAfter, vwcBefore, type ShotLogRow } from "@/lib/zone-shot-log";
import "./today.css";
import "./zone.css";

const PHASE_NAMES: Record<string, string> = {
  P0: "Morning dryback",
  P1: "Ramp",
  P2: "Maintenance",
  P3: "Overnight dryback",
};
const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
type CompareChoice = "off" | "yesterday" | "last-run";
const COMPARE_KEY = "crop-steering-zone-compare";
/** What the zone's chart is compared with, remembered in this browser. */
function storedCompare(): CompareChoice {
  try {
    const value = localStorage.getItem(COMPARE_KEY);
    return value === "off" || value === "last-run" ? value : "yesterday";
  } catch {
    return "yesterday";
  }
}
/** An AI change to a pore EC setting: the page offers it on the pore EC chart. */
const isEcOverlay = (overlay: Overlay) => /(^|_)ec(_|$)/.test(overlay.field);

/** One zone: what it did today and why, whether it is on its stage's curve, whether its probes tell
 * the truth, and what happens next. Reached from the room tree and the room's page. */
export function ZonePage({
  controller,
  zoneId,
  navigate,
  onDirtyChange,
}: {
  controller: Controller;
  zoneId: number | null;
  onDirtyChange?: (dirty: boolean) => void;
  navigate: (page: Page, zone?: number) => void;
}) {
  const zones = controller.room.zones;
  const zone = zones.find((item) => item.id === zoneId) ?? zones[0];
  const [compare, setCompare] = useState(storedCompare);
  const [dismissed, setDismissed] = useState<string[]>([]);
  const { doc, reload } = useOverlays(controller);
  const now = Date.now();
  const { states, room, timeZone } = controller;
  const prefix = room.room.prefix;
  const day = growDay(
    numeric(states[`number.crop_steering_${prefix}lights_on_hour`]),
    numeric(states[`number.crop_steering_${prefix}lights_off_hour`]),
    now,
    timeZone,
  );
  const view = roomView(controller, now);
  const lastRun = useLastRun(controller, zone?.id ?? null, view?.room.growDay?.day ?? null);
  const series = useRecentHistory(
    controller,
    zone ? [zone.vwc.entityId, zone.ec.entityId].filter((id): id is string => !!id) : [],
    25,
  );
  if (!zone)
    return (
      <>
        <div className="label-with-tip">
          <h1 className="zone-empty-title">Zone</h1>
          <UiTip copyKey="zone" />
        </div>
        <section className="panel">
          <Empty
            title="No zones found"
            detail="Zones appear once the room’s zones are configured in Equipment › Setup."
            action={<Button onClick={() => navigate("equipment/setup")}>Open setup</Button>}
          />
        </section>
      </>
    );
  const display = room.display.options;
  const steering = steeringOf(
    states[`select.crop_steering_${prefix}zone_${zone.id}_steering_mode`]?.state,
    readJev(states, prefix).room?.stage?.steering,
  );
  const row = view?.rows.find((item) => item.zone === zone.id);
  const grow = view?.room.growDay ?? null;
  const plants = zonePlants(controller, zone.id);
  const sensors = row?.view.sensors.length ?? 0;
  const facts = [
    grow && `Day ${grow.day}${grow.of !== null ? ` of ${grow.of}` : ""}`,
    plants !== null && `${plants} plant${plants === 1 ? "" : "s"}`,
    sensors > 0 && `${sensors} sensor${sensors === 1 ? "" : "s"}`,
  ].filter(Boolean);
  const pointsOf = (id: string | null) =>
    (series?.find((item) => item.entityId === id)?.points ?? []).map((point) => ({
      t: Date.parse(point.time),
      v: point.value,
    }));
  const ecGauge = row?.gauges.find((item) => item.label === "Pore EC") ?? null;
  const overlays = zoneOverlays(doc, controller.roomId, zone.id);
  const suggestion =
    overlays.find((overlay) => isEcOverlay(overlay) && !dismissed.includes(overlay.entity_id)) ??
    null;
  const choose = (next: CompareChoice) => {
    setCompare(next);
    try {
      localStorage.setItem(COMPARE_KEY, next);
    } catch {
      /* The choice still applies on this page. */
    }
  };
  return (
    <div className="zone-page" data-zone-page={zone.id}>
      <div className="zone-page-title">
        <button type="button" className="zone-room" onClick={() => navigate("today")}>
          {room.room.name}
        </button>
        <span className="zone-crumb" aria-hidden="true">
          /
        </span>
        <h1>{zone.name}</h1>
        {zone.cultivar && <span className="zone-cultivar">{zone.cultivar}</span>}
        {/^P[0-3]$/.test(zone.phase) ? (
          <span className="pill" data-phase={zone.phase}>
            {zone.phase} · {PHASE_NAMES[zone.phase]}
          </span>
        ) : (
          <Pill tone="unknown">Phase unavailable</Pill>
        )}
        {zone.enabled === false ? (
          <Pill dot tone="warn">
            Scheduling paused
          </Pill>
        ) : (
          row && (
            <span className="today-mode" data-mode={row.view.mode}>
              <i aria-hidden="true" />
              {ZONE_MODE[row.view.mode]}
            </span>
          )
        )}
        <Pill
          dot
          tone={zone.valveOn === true ? "on" : zone.valveOn === false ? "neutral" : "unknown"}
          data-zone-valve={zone.id}
          title={zone.valveEntity ?? "No valve is mapped in the configuration of this room"}
        >
          Valve {zone.valveOn === true ? "open" : zone.valveOn === false ? "closed" : "unknown"}
        </Pill>
        {steering && (
          <span className="zone-steering" data-steering={steering}>
            {capital(steering)}
          </span>
        )}
        {facts.length > 0 && (
          <p className="zone-facts" data-zone-facts>
            {facts.join(" · ")}
          </p>
        )}
      </div>
      <div className="zone-layout">
        <ZoneDay
          key={zone.id}
          controller={controller}
          zone={zone}
          compare={compare}
          onCompare={choose}
          lastRun={lastRun}
          beside={{
            name: "Pore EC",
            chart: (
              <PoreEcChart
                points={pointsOf(zone.ec.entityId)}
                day={day}
                now={now}
                band={ecGauge?.band ?? null}
                timeZone={timeZone}
                loading={series === null}
              />
            ),
          }}
        />
        {suggestion && (
          <EcSuggestion
            key={suggestion.entity_id}
            controller={controller}
            overlay={suggestion}
            gauge={ecGauge}
            reload={reload}
            onDismiss={() => setDismissed((list) => [...list, suggestion.entity_id])}
          />
        )}
        <ZoneWhy
          key={`why-${zone.id}`}
          controller={controller}
          zone={zone}
          navigate={navigate}
          overlays={overlays.filter((overlay) => overlay !== suggestion)}
          reload={reload}
        />
        <ShotLogCard
          key={`log-${zone.id}`}
          controller={controller}
          zone={zone}
          day={day}
          plants={plants}
          vwc={pointsOf(zone.vwc.entityId)}
          navigate={navigate}
        />
      </div>
      {(display.show_climate || display.show_substrate_temp) && (
        <div className="zone-extras-row">
          {display.show_climate && <ClimatePanel controller={controller} zone={zone.id} />}
          {display.show_substrate_temp && <RootZonePanel controller={controller} zone={zone} />}
        </div>
      )}
      <Button variant="outline" onClick={() => navigate("history/explorer", zone.id)}>
        Explore recorded history and comparisons <ArrowRight size={15} aria-hidden="true" />
      </Button>
      <PlantStressCard key={`stress-${zone.id}`} controller={controller} zone={zone} />
      {/* Hardware controls and optional camera retain their separate operational roles. */}
      <div className={display.show_camera ? "zone-page-grid" : "zone-page-stack"}>
        {display.show_camera && (
          <div className="zone-page-column">
            <CameraCard controller={controller} />
          </div>
        )}
        <div className="zone-page-stack">
          <ZoneControls key={zone.id} controller={controller} zone={zone} />
          <CanonicalControls
            key={`zone-config-${zone.id}`}
            controller={controller}
            owner="zone"
            zoneId={zone.id}
            onDirtyChange={onDirtyChange}
          />
          <HardwarePanel controller={controller} zone={zone} />
        </div>
      </div>
      {/* The rest on request: the day chart above already shows today. */}
      <Collapsed key={`targets-${zone.id}`} title="Targets (read only)">
        {() => <ZoneTargets controller={controller} zone={zone} navigate={navigate} />}
      </Collapsed>
      <Collapsed key={`probes-${zone.id}`} title="Probes used and not used">
        {() => <ZoneProbes controller={controller} zone={zone} navigate={navigate} />}
      </Collapsed>
      <ZoneShots key={`shots-${zone.id}`} controller={controller} zone={zone} />
    </div>
  );
}

/** The previous run's grow-day with today's number, for the zone's VWC: the latest finished run
 * that is not archived, cut from its own lights-on. Null while loading, and without such a run, a
 * zone sensor registered in it, or two readings that day. */
function useLastRun(controller: Controller, zoneId: number | null, dayNumber: number | null) {
  const key = zoneId !== null && dayNumber ? `${controller.roomId} ${zoneId} ${dayNumber}` : "";
  const [read, setRead] = useState<{
    key: string;
    value: { day: number; trace: DayTrace } | null;
  } | null>(null);
  const latest = useRef(controller);
  latest.current = controller;
  useEffect(() => {
    if (!key || zoneId === null || !dayNumber) return;
    let current = true;
    const load = async () => {
      const controller = latest.current;
      const doc = await controller.operator<RunsDocument>("runs_get");
      const open = doc.runs.filter((run) => !run.archived);
      const running = open.find((run) => !run.end_date);
      const previous = open
        .filter((run) => run.id !== running?.id && run.end_date)
        .sort((a, b) => b.start_date.localeCompare(a.start_date))[0];
      const sensor = previous?.zones.find((item) => item.zone_id === zoneId)?.vwc_sensor;
      const { on, off } = previous?.lights ?? { on: null, off: null };
      if (!previous || !sensor || on === null || off === null) return null;
      const date = addDays(previous.start_date, dayNumber - 1);
      if (date > previous.end_date!) return null;
      const tz = previous.time_zone;
      const day = growDay(on, off, midnight(date, tz) + (on + 1) * 3_600_000, tz);
      if (!day) return null;
      const window = await controller.historyWindow({
        entityIds: [sensor],
        start: new Date(day.start).toISOString(),
        end: new Date(day.end).toISOString(),
        timeZone: tz,
      });
      const points = smoothRecorded(
        (window.series.find((item) => item.entityId === sensor)?.points ?? []).flatMap((point) =>
          point.value === null ? [] : [{ time: point.time, value: point.value }],
        ),
      ).map((point) => ({ ...point, hour: (point.time - day.start) / 3_600_000 }));
      return points.length < 2 ? null : { day: dayNumber, trace: { day, points, shots: [] } };
    };
    load().then(
      (value) => current && setRead({ key, value }),
      () => current && setRead({ key, value: null }),
    );
    return () => {
      current = false;
    };
  }, [key, zoneId, dayNumber]);
  return read?.key === key ? read.value : null;
}

/** Today's pore EC against the stage's band, from lights-on to the next: the lights-off hours
 * dark, a line at now. */
function PoreEcChart({
  points,
  day,
  now,
  band,
  timeZone,
  loading,
}: {
  points: { t: number; v: number }[];
  day: GrowDay | null;
  now: number;
  band: [number, number] | null;
  timeZone: string;
  loading: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const today = day ? points.filter((point) => point.t >= day.start && point.t <= now) : [];
  const values = [...today.map((point) => point.v), ...(band ?? [])];
  const low = values.length ? Math.floor(Math.min(...values) - 0.5) : 0;
  const high = values.length ? Math.ceil(Math.max(...values) + 0.5) : 1;
  const L = 34,
    R = 8,
    T = 8,
    H = width && width < 420 ? 120 : 140;
  const plot = Math.max(10, width - L - R);
  const x = (time: number) => (day ? L + ((time - day.start) / (day.end - day.start)) * plot : L);
  const y = (value: number) => T + H - ((value - low) / (high - low || 1)) * H;
  const ticks = day ? [0, 6, 12, 18, 24].map((hour) => day.start + hour * 3_600_000) : [];
  const target = band ? `${number(band[0], 1)}–${number(band[1], 1)}` : null;
  return (
    <section className="panel zone-ec-chart" aria-labelledby="zone-ec-title" data-zone-ec-chart>
      <div className="panel-heading">
        <h2 id="zone-ec-title">Today · Pore EC</h2>
        {target && <span className="muted small">target {target}</span>}
      </div>
      <div className="zone-ec-plot" ref={box}>
        {!day ? (
          <p className="muted small">Set this room’s lights hours to draw its grow day.</p>
        ) : loading ? (
          <p className="muted small" role="status">
            Loading today’s pore EC…
          </p>
        ) : today.length < 2 ? (
          <p className="muted small">No pore EC recorded since lights-on.</p>
        ) : (
          width > 0 && (
            <svg
              width={width}
              height={T + H + 22}
              role="img"
              aria-label={`Pore EC since lights-on, from ${number(today[0].v, 2)} to ${number(today.at(-1)!.v, 2)}${target ? `, target ${target}` : ""}`}
            >
              <rect
                className="zone-ec-dark"
                x={x(day.lightsOff)}
                y={T}
                width={Math.max(0, x(day.end) - x(day.lightsOff))}
                height={H}
              />
              {band && (
                <rect
                  className="zone-ec-band"
                  x={L}
                  width={plot}
                  y={y(band[1])}
                  height={Math.max(0, y(band[0]) - y(band[1]))}
                />
              )}
              {[low, (low + high) / 2, high].map((value) => (
                <text key={value} className="zone-ec-axis" x={L - 6} y={y(value) + 4} textAnchor="end">
                  {number(value, 1)}
                </text>
              ))}
              {ticks.map((time, index) => (
                <text
                  key={time}
                  className="zone-ec-axis"
                  x={x(time)}
                  y={T + H + 16}
                  textAnchor={index === 0 ? "start" : index === ticks.length - 1 ? "end" : "middle"}
                >
                  {wallClock(time, timeZone)}
                </text>
              ))}
              <path
                className="zone-ec-line"
                data-series="pore-ec"
                d={today
                  .map((point, index) => `${index ? "L" : "M"}${x(point.t).toFixed(1)} ${y(point.v).toFixed(1)}`)
                  .join("")}
              />
              <line className="zone-ec-now" x1={x(now)} x2={x(now)} y1={T} y2={T + H} />
            </svg>
          )
        )}
      </div>
    </section>
  );
}

/** Settings shown with as many decimals as they were written with. */
const digitsOf = (value: number) => (String(value).split(".")[1] ?? "").length;

/** The AI assistant's change to a pore EC setting, on the pore EC chart: the problem it answers,
 * what it set against the grower's own, Apply (keep it as the grower's) with Undo, or Dismiss. */
function EcSuggestion({
  controller,
  overlay,
  gauge,
  reload,
  onDismiss,
}: {
  controller: Controller;
  overlay: Overlay;
  gauge: GaugeModel | null;
  reload: () => void;
  onDismiss: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const tz = controller.timeZone;
  const label = overlayLabel(overlay);
  const ec = (value: number) => formatEc(value, digitsOf(value));
  const over =
    gauge?.band && gauge.value !== null && (gauge.deviation ?? 0) > 0
      ? `Pore EC ${number(gauge.value, gauge.digits)} is over the ${number(gauge.band[0], 1)}–${number(gauge.band[1], 1)} band.`
      : null;
  const locked = controller.admin === false;
  async function apply() {
    setBusy(true);
    setError("");
    try {
      await controller.operator("overlay_keep", { entity_id: overlay.entity_id });
      const after = await controller.operator<OverlayDocument>("overlay_get");
      reload();
      if (after.overlays.some((item) => item.entity_id === overlay.entity_id))
        throw new Error("The controller did not confirm it. Reload and check it before trying again.");
      offerUndo({
        message: `${label} ${ec(overlay.new)} is yours now. Written and read back ${wallClock(Date.now(), tz)}.`,
        // Kept, the AI's change has ended, so overlay_undo has nothing left to undo: Undo writes
        // the grower's own value back, as overlay_undo would have.
        undo: async () => {
          const result = await controller.write([{ entityId: overlay.entity_id, value: overlay.old }]);
          if (!result.applied.includes(overlay.entity_id))
            throw new Error(result.failed[0]?.reason || "The controller did not confirm the previous value.");
          toast(`${label} is back to ${ec(overlay.old)}. Written and read back ${wallClock(Date.now(), tz)}.`);
        },
      });
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel zone-suggestion" aria-label="AI suggestion" data-zone-suggestion>
      <AlertTriangle className="zone-suggestion-icon" size={20} aria-hidden="true" />
      <div className="zone-suggestion-text">
        {over && <p className="zone-suggestion-problem">{over}</p>}
        <p>
          AI assistant suggests: <strong>{label} {ec(overlay.new)}</strong> instead of your{" "}
          {ec(overlay.old)}. It holds until lights-on, then yours comes back unless you apply it.
        </p>
        {error && (
          <p className="jev-trouble" role="alert">
            {error}
          </p>
        )}
      </div>
      <div className="zone-suggestion-actions">
        <Button
          disabled={busy || locked}
          title={locked ? "Needs a Home Assistant administrator" : undefined}
          onClick={() => void apply()}
        >
          Apply
        </Button>
        <Button variant="outline" disabled={busy} onClick={onDismiss}>
          Dismiss
        </Button>
      </div>
    </section>
  );
}

/** Water each plant got: mL, or gallons when the room shows gallons. */
const perPlant = (ml: number) =>
  getDisplayUnits().volume === "gal" ? formatVolume(ml / 1000, 4) : `${Math.round(ml)} mL`;

type ShotLogRead = ShotLogRow[] | "missing" | { error: string };

/** Today's shots in this zone, newest first: when, the phase, water per plant and run time, and VWC
 * before and five minutes after. From the Journal on 3.18; from the controller's shot table on 3.17. */
function ShotLogCard({
  controller,
  zone,
  day,
  plants,
  vwc,
  navigate,
}: {
  controller: Controller;
  zone: Zone;
  day: GrowDay | null;
  plants: number | null;
  vwc: { t: number; v: number }[];
  navigate: (page: Page, zone?: number) => void;
}) {
  const since = day?.start ?? null;
  const fresh = controller.recentEvents.filter(
    (event) => event.kind === "shot.completed" && event.zone === zone.id,
  ).length;
  const key = since === null ? "" : `${controller.roomId} ${zone.id} ${since} ${plants} ${fresh}`;
  const [read, setRead] = useState<{ key: string; rows: ShotLogRead } | null>(null);
  const latest = useRef(controller);
  latest.current = controller;
  useEffect(() => {
    if (!key || since === null) return;
    let current = true;
    void pagedQuery(latest.current, {
      room_id: latest.current.roomId,
      since: new Date(since).toISOString(),
      kinds: ["shot.started", "shot.completed"],
      zones: [zone.id],
    }).then((outcome) => {
      if (!current) return;
      setRead({
        key,
        rows:
          outcome.kind === "ok"
            ? shotLog(outcome.data.events, zone.id, since, plants)
            : outcome.kind === "missing"
              ? "missing"
              : { error: outcome.message },
      });
    });
    return () => {
      current = false;
    };
  }, [key, since, zone.id, plants]);
  const answer = read?.key === key ? read.rows : null;
  const rows = Array.isArray(answer)
    ? answer
    : answer === "missing" && since !== null
      ? tableShotLog(
          controller.states[
            `sensor.crop_steering_${controller.room.room.prefix}zone_${zone.id}_shot_log_app`
          ]?.attributes.shots,
          since,
          plants,
        )
      : null;
  const tz = controller.timeZone;
  const pct = (value: number | null) => (value === null ? "—" : value.toFixed(1));
  return (
    <section className="panel zone-shot-log" aria-labelledby="zone-shot-log-title" data-zone-shot-log>
      <div className="panel-heading">
        <h2 id="zone-shot-log-title">Shot log · today</h2>
        <Button variant="ghost" size="sm" onClick={() => navigate("history/explorer", zone.id)}>
          History <ArrowRight size={15} aria-hidden="true" />
        </Button>
      </div>
      {since === null ? (
        <p className="muted small">Set this room’s lights hours to log its grow day.</p>
      ) : answer === null ? (
        <p className="muted small" role="status">
          Loading today’s shots…
        </p>
      ) : typeof answer === "object" && "error" in answer ? (
        <p className="jev-trouble" role="alert">
          {answer.error}
        </p>
      ) : !rows ? (
        <NeedsIntegration compact feature="Today's shot log" />
      ) : rows.length === 0 ? (
        <p className="muted small">No shots since lights-on.</p>
      ) : (
        <ol className="zone-shot-rows" aria-label={`${zone.name} shots since lights-on`}>
          {rows.map((row) => {
            const before = row.vwcBefore ?? vwcBefore(vwc, row.at);
            const after = vwcAfter(vwc, row.end);
            return (
              <li key={row.at} data-shot-row>
                <time>{wallClock(row.at, tz)}</time>
                {row.phase ? (
                  <span className="pill" data-phase={row.phase}>
                    {row.phase}
                  </span>
                ) : (
                  <span />
                )}
                <span className="zone-shot-water">
                  {row.mlPerPlant === null ? "—" : perPlant(row.mlPerPlant)}
                  {!row.metered && <small> commanded</small>}
                  {row.seconds !== null && ` · ${Math.round(row.seconds)} s`}
                </span>
                <span
                  className="zone-shot-vwc"
                  title="VWC as the shot began, and five minutes after it ended"
                >
                  {pct(before)} → {pct(after)}%
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

/** Why this zone is doing what it is doing: the controller's reason from its decision record and what
 * it waits for next; with the AI on, the AI's read and a "Why?" that asks it. On rules, the
 * controller's reason only. */
function ZoneWhy({
  controller,
  zone,
  navigate,
  overlays,
  reload,
}: {
  controller: Controller;
  zone: Zone;
  navigate: (page: Page, zone?: number) => void;
  /** The zone's AI changes that the page does not offer elsewhere. */
  overlays: Overlay[];
  reload: () => void;
}) {
  const { panel: brainPanel, view: brainView } = useBrain(controller);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { states, room } = controller;
  const ids = jevIds(room.room.prefix);
  const reasons = zoneReasons(
    zone,
    states[`sensor.crop_steering_${room.room.prefix}current_decision`],
  );
  const waiting = zone.waiting
    ? waitingText(zone.waiting, { number: (value) => number(value), clock })
    : "";
  const on = !!readJev(states, room.room.prefix).room?.on;
  const sensor = on ? parseJevZone(states[ids.zone(zone.id)]) : null;
  const read = sensor ? aiRead(sensor.judges, sensor.acting) : null;
  // "Why?" needs a controller that answers (its answers sensor); asking costs from the AI budget.
  const answers = on ? parseBrainAnswers(states[ids.answers]) : null;
  const answer = answers?.answers.find((item) => item.zone === zone.id);
  const locked = controller.admin === false;
  async function ask() {
    setBusy(true);
    setError("");
    try {
      await controller.operator("brain_ask", {
        question: `Why is ${zone.name} doing what it is doing now?`,
        zone: zone.id,
      });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel zone-why-panel" aria-labelledby="zone-why-title" data-zone-why>
      <div className="panel-heading">
        <div>
          <h2 id="zone-why-title">Why / next action</h2>
          <p>{on ? "The controller’s reason, then the AI’s read" : "The controller’s reason"}</p>
        </div>
        {answers && (
          <Button
            variant="outline"
            size="sm"
            disabled={busy || locked || !!answers.pending}
            onClick={() => void ask()}
          >
            Why?
          </Button>
        )}
      </div>
      <div className="zone-panel-body">
        {reasons.length ? (
          <ul className="zone-reasons" aria-label="Controller reason">
            {reasons.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : (
          <p className="muted small">The controller has not said anything about this zone yet.</p>
        )}
        {waiting && (
          <p className="zone-waiting">
            <span>The controller waits for</span> {waiting}
          </p>
        )}
        <p className="muted small">{brainView.headline}</p>
        {!sensor && brainPanel?.lastDecision?.zone === zone.id && (
          <p className="zone-ai-read">
            Latest AI proposal: {brainPanel.lastDecision.answer || "No answer"}.{" "}
            {brainPanel.lastDecision.why}
          </p>
        )}
        {read && (
          <p className="zone-ai-read">
            <span>AI’s read · {read.title}</span> {read.why}
          </p>
        )}
        {answers && locked && (
          <p className="muted small">
            Only an administrator can ask: each answer costs from the room’s AI budget.
          </p>
        )}
        {error && (
          <p className="jev-trouble" role="alert">
            {error}
          </p>
        )}
        {!!answers?.pending && <p className="muted small">Asking…</p>}
        {answer && (
          <p className="zone-ai-read" data-cannot={answer.cannotAnswer || undefined}>
            <span>AI’s answer{answer.answeredAt !== null && ` · ${clock(answer.answeredAt)}`}</span>{" "}
            {answer.answer}
          </p>
        )}
        <details className="zone-more">
          <summary>All next-shot conditions</summary>
          <ZoneGates controller={controller} zone={zone} />
        </details>
        <details className="zone-more">
          <summary>AI proposals, applied changes and outcomes</summary>
          <JevOnZone
            controller={controller}
            zone={zone}
            navigate={navigate}
            overlays={overlays}
            reload={reload}
          />
        </details>
      </div>
    </section>
  );
}

/** A section left closed until asked for: it renders only while open. */
function Collapsed({ title, children }: { title: string; children: () => ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="zone-more"
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>{title}</summary>
      {open && children()}
    </details>
  );
}

/** What the AI assistant says about this zone: which judges act on it now, each judge's last word, the setpoints
 * it may move and within what range, and its latest decisions here with how they turned out. */
function JevOnZone({
  controller,
  zone,
  navigate,
  overlays,
  reload,
}: {
  controller: Controller;
  zone: Zone;
  navigate: (page: Page, zone?: number) => void;
  overlays: Overlay[];
  reload: () => void;
}) {
  const { states, room } = controller;
  const ids = jevIds(room.room.prefix);
  const { log, room: brain } = readJev(states, room.room.prefix);
  const sensor = parseJevZone(states[ids.zone(zone.id)]);
  const rules = brain && !brain.on ? brainWords(brain).subtitle : null;
  const setpoints = parseJevSetpoints(states[ids.zone(zone.id)]);
  if (!log && !sensor && !overlays.length) return null;
  const { rest, outcomes } = attachOutcomes(log?.entries ?? []);
  const recent = rest.filter((entry) => entry.zone === zone.id).slice(0, 6);
  const now = Date.now();
  return (
    <div className="zone-jev" aria-labelledby="zone-jev-title" data-zone-jev>
      <div className="panel-heading">
        <div>
          <h2 id="zone-jev-title">AI assistant on this zone</h2>
          <p>
            {rules ??
              (sensor?.acting.length
                ? `Acting now: ${sensor.acting.map((judge) => JEV_TITLES[judge] ?? judge).join(", ")}`
                : "Watching: no judge acting on this zone now")}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => navigate("history/explorer", zone.id)}>
          History <ArrowRight size={15} aria-hidden="true" />
        </Button>
      </div>
      <div className="zone-panel-body">
        {setpoints && <JevSetpointsLine setpoints={setpoints} />}
        <OverlayRows controller={controller} overlays={overlays} reload={reload} />
        {!!sensor?.judges.length && (
          <ul className="zone-judges" aria-label="Last answer of each judge">
            {sensor.judges.map((judge) => (
              <li key={judge.judge}>
                <strong>{judge.title}</strong>{" "}
                <span>{jevAnswer({ verdict: judge.answer, p: judge.p })}</span>
                {judge.directive && <span className="muted"> → {judge.directive}</span>}
                {judge.why && <span className="zone-why">{judge.why}</span>}
              </li>
            ))}
          </ul>
        )}
        {recent.length > 0 && (
          <ol className="zone-jev-list" aria-label="Last AI assistant decisions">
            {recent.map((entry) => {
              const result = jevResult(entry);
              const checked = outcomes.get(entry.key)?.at(-1);
              return (
                <li key={entry.key} data-result={entry.result}>
                  <time>
                    {entry.time !== null && dayWord(entry.time, now) && (
                      <small>{dayWord(entry.time, now)}</small>
                    )}
                    {entry.time === null ? "—" : clock(entry.time)}
                  </time>
                  <span className="zone-jev-what">
                    <strong>{entry.title}</strong>{" "}
                    {entry.kind === "outcome"
                      ? `after “${entry.verdict || "an earlier call"}”`
                      : jevAnswer(entry)}
                    {entry.action && <> → {entry.action.replaceAll("->", "→")}</>}
                  </span>
                  <span className="zone-jev-result">
                    <Pill tone={result.tone}>{result.label}</Pill>
                    {checked && (
                      <span
                        className="zone-outcome"
                        data-worked={checked.result === "worked"}
                        title={outcomeText(checked)}
                      >
                        {checked.result === "worked" ? (
                          <Check size={13} aria-hidden="true" />
                        ) : (
                          <X size={13} aria-hidden="true" />
                        )}
                        <span className="sr-only">{outcomeText(checked)}</span>
                      </span>
                    )}
                  </span>
                </li>
              );
            })}
          </ol>
        )}
        {!recent.length && !sensor?.judges.length && (
          <p className="muted small">No decisions on this zone yet.</p>
        )}
      </div>
    </div>
  );
}

function JevSetpointsLine({ setpoints }: { setpoints: JevSetpoints }) {
  const part = (key: "p2_shot_size" | "p2_vwc_threshold", name: string) => {
    const range = setpoints.range[key];
    if (!range) return null;
    const home = setpoints.home[key],
      now = setpoints.current[key];
    return `${name} ${rangeText(range)}%${home === undefined ? "" : ` (yours ${number(home)}%${now !== undefined && now !== home ? `, now ${number(now)}%` : ""})`}`;
  };
  const parts = [part("p2_shot_size", "shot size"), part("p2_vwc_threshold", "re-water point")];
  const paused = setpoints.pausedUntil !== null && setpoints.pausedUntil > Date.now();
  return (
    <p className="zone-jev-setpoints" data-managed={setpoints.managed}>
      {setpoints.managed
        ? `The AI assistant can change the P2 ${parts.filter(Boolean).join(" and ")}.`
        : "The AI assistant does not change the setpoints of this zone (Auto setpoints is off, or a grow plan holds them)."}
      {setpoints.last && ` Last change ${lastChange(setpoints.last).replaceAll("->", "→")}.`}
      {paused && ` Paused until ${clock(setpoints.pausedUntil)} after a rescue put a change back.`}
    </p>
  );
}

/** The AI assistant's own "2026-09-27 22:57: P2 shot 4.5% -> 4%" with the stamp as a day and a clock time. */
function lastChange(last: string) {
  const parts = last.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::\d{2})?: (.+)$/);
  if (!parts) return last;
  const [, year, month, day, hour, minute, what] = parts;
  const at = new Date(+year, +month - 1, +day, +hour, +minute).getTime();
  const word = dayWord(at, Date.now());
  return `${word === "Yesterday" ? "yesterday" : word || "today"} ${clock(at)}: ${what}`;
}

/** The zone's targets as the controller uses them now, with the AI assistant's range where it manages one; they
 * are edited in Plan. */
function ZoneTargets({
  controller,
  zone,
  navigate,
}: {
  controller: Controller;
  zone: Zone;
  navigate: (page: Page, zone?: number) => void;
}) {
  const { room, states } = controller;
  const preview = buildSetpointPreview(room, states, zone.id, {});
  const params = preview.saved.parameters;
  const setpoints = parseJevSetpoints(states[jevIds(room.room.prefix).zone(zone.id)]);
  return (
    <section className="panel zone-targets" aria-labelledby="zone-targets-title">
      <div className="panel-heading">
        <div>
          <h2 id="zone-targets-title">Targets</h2>
          <p>
            {preview.readOnly
              ? "Set by the armed grow plan"
              : preview.saved.mode
                ? `${preview.saved.mode} steering: its dryback and EC targets`
                : "As the controller reads them now"}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => navigate("plan/targets", zone.id)}>
          Edit in Plan <ArrowRight size={15} aria-hidden="true" />
        </Button>
      </div>
      <table className="zone-targets-table">
        {TARGET_GROUPS.map((group) => (
          <tbody key={group.phase}>
            <tr className="zone-targets-phase">
              <th colSpan={3} scope="colgroup">
                <span className="pill" data-phase={group.phase}>
                  {group.phase}
                </span>{" "}
                {group.title.split(" · ")[1]}
              </th>
            </tr>
            {group.rows.map((row) => {
              const value = params[row.key];
              const chip = jevChip(setpoints, row.key, row.unit);
              return (
                <tr key={row.key}>
                  <th scope="row">{row.label}</th>
                  <td className="numeric">
                    {value === undefined ? "—" : number(value, row.digits ?? 1)}
                    {value !== undefined && row.unit && <span className="unit"> {row.unit}</span>}
                  </td>
                  <td>{chip && <span className="jev-chip">{chip}</span>}</td>
                </tr>
              );
            })}
          </tbody>
        ))}
      </table>
    </section>
  );
}

/** The probes behind the zone's two readings: each one's reading, whether the combined reading uses
 * it, and whether to believe it (lib/probes, as Equipment › Probes shows them). */
function ZoneProbes({
  controller,
  zone,
  navigate,
}: {
  controller: Controller;
  zone: Zone;
  navigate: (page: Page) => void;
}) {
  const { states } = controller;
  const probes = zoneProbes(zone, states, Date.now());
  return (
    <section className="panel zone-probes" aria-labelledby="zone-probes-title">
      <div className="panel-heading">
        <div>
          <div className="label-with-tip">
            <h2 id="zone-probes-title">Probes</h2>
            <UiTip copyKey="probes" />
          </div>
          <p>What each probe reads, and whether the zone’s reading uses it</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => navigate("equipment/probes")}>
          Equipment <ArrowRight size={15} aria-hidden="true" />
        </Button>
      </div>
      <div className="zone-panel-body">
        {(["vwc", "ec"] as const).map((kind) => {
          const metric = zone[kind];
          const fused = metric.entityId ? states[metric.entityId] : undefined;
          const spread =
            typeof fused?.attributes.spread === "number" ? fused.attributes.spread : null;
          const mine = probes.filter((probe) => probe.kind === kind);
          const method = fusionMethod(fused);
          const steersOn = kind === "ec" ? ecType(fused) : null;
          return (
            <div className="zone-probe-group" key={kind}>
              <h3>
                {kind === "vwc" ? "Moisture" : "Pore EC"}{" "}
                <span className="muted">
                  {metric.value === null
                    ? "· no usable reading"
                    : `· zone reads ${number(metric.value, kind === "ec" ? 2 : 1)}${kind === "vwc" ? "%" : ""}`}
                  {spread !== null &&
                    mine.filter((probe) => probe.used).length > 1 &&
                    ` · probes ${number(spread, kind === "ec" ? 2 : 1)} apart`}
                  {method && ` · the ${method}`}
                  {steersOn && ` · ${steersOn}`}
                </span>
              </h3>
              <ul className="zone-probe-list">
                {mine.map((probe) => (
                  <li key={probe.id}>
                    <span className="zone-probe-name">
                      {probe.name}
                      <code>{probe.id}</code>
                    </span>
                    <span className="numeric">
                      {probe.value === null ? "—" : `${probe.value} ${probe.unit}`.trim()}
                    </span>
                    <Pill dot tone={PROBE_TONE[probe.health]} data-probe-health={probe.health}>
                      {probe.health !== "ok"
                        ? probe.text
                        : probe.used === null
                          ? "Reporting"
                          : "Used"}
                    </Pill>
                  </li>
                ))}
                {!mine.length && (
                  <li>
                    <span className="zone-probe-name">Not mapped</span>
                  </li>
                )}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** Pause the zone's scheduling, and move it to a phase by hand: each through its review. */
function ZoneControls({ controller, zone }: { controller: Controller; zone: Zone }) {
  const [review, setReview] = useState(false);
  const [phaseChoice, setPhaseChoice] = useState<string | null>(null);
  const connected = ["live", "demo"].includes(controller.connection);
  const pauseWords =
    "Paused, the zone gets no water at all, not even a rescue shot, and a shot already running in it stops within a few seconds. It is not an emergency stop: use the installation's physical shut-off for that.";
  return (
    <section className="panel zone-controls" aria-labelledby="zone-controls-title">
      <div className="panel-heading">
        <h2 id="zone-controls-title">Controls</h2>
      </div>
      <div className="zone-panel-body">
        <div className="zone-control-row">
          <span>
            Scheduling{" "}
            <Pill
              dot
              tone={zone.enabled === true ? "on" : zone.enabled === false ? "warn" : "unknown"}
            >
              {zone.enabled === true ? "On" : zone.enabled === false ? "Paused" : "Unavailable"}
            </Pill>
          </span>
          <Button
            variant="outline"
            size="sm"
            title={
              zone.enabled
                ? pauseWords
                : "The controller waters the zone again from its next check."
            }
            disabled={!zone.enabledEntity || zone.enabled === null || !connected}
            onClick={() => setReview(true)}
          >
            {zone.enabled ? "Pause zone scheduling" : "Enable zone scheduling"}
          </Button>
        </div>
        {zone.setPhaseEntity && (
          <div className="zone-control-row zone-phase-row">
            <span>Move to a phase</span>
            <div className="phase-picker" role="group" aria-label={`Move ${zone.name} to`}>
              {Object.entries(PHASE_NAMES).map(([phase, name]) => (
                <Button
                  key={phase}
                  size="sm"
                  variant="outline"
                  aria-pressed={phase === zone.phase}
                  title={`${phase} · ${name}: the controller moves the zone within a minute and continues from there. Lights-off still moves it to P3, and lights-on to P0.`}
                  disabled={phase === zone.phase || !connected}
                  onClick={() => setPhaseChoice(phase)}
                >
                  {phase} · {name}
                </Button>
              ))}
            </div>
          </div>
        )}
      </div>
      {zone.enabledEntity && (
        <ReviewDialog
          open={review}
          onOpenChange={setReview}
          controller={controller}
          title="Review zone switch"
          items={[
            {
              change: { entityId: zone.enabledEntity, value: !zone.enabled },
              label: `${zone.name} scheduling`,
              before: zone.enabled ? "Enabled" : "Paused",
              after: zone.enabled ? "Paused" : "Enabled",
            },
          ]}
          note={
            zone.enabled
              ? "Paused, the zone gets no water, not even a rescue shot, and a shot already running in it stops within a few seconds."
              : "The controller waters the zone again from its next check."
          }
        />
      )}
      {zone.setPhaseEntity && (
        <ReviewDialog
          open={phaseChoice !== null}
          onOpenChange={(open) => {
            if (!open) setPhaseChoice(null);
          }}
          controller={controller}
          title={`Move ${zone.name} to ${phaseChoice}?`}
          items={
            phaseChoice
              ? [
                  {
                    change: { entityId: zone.setPhaseEntity, value: phaseChoice },
                    label: `${zone.name} phase`,
                    before: zone.phase,
                    after: phaseChoice,
                  },
                ]
              : []
          }
          note="The controller moves the zone at its next check, within a minute. Today's water and shot counts stay; a zone moved to P1 ramps from its first shot again."
        />
      )}
    </section>
  );
}
