import { useState } from "react";
import { ArrowLeft, ArrowRight, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Empty,
  HistoryChart,
  number,
  ReviewDialog,
  time as clock,
  type Page,
} from "@/components/dashboard";
import { ZoneDay } from "@/components/day-timeline";
import { Pill } from "@/components/mini-visuals";
import { SensorContextCard, useSensorContext } from "@/components/sensor-context";
import { rangeText, steeringOf } from "@/lib/day-chart";
import {
  attachOutcomes,
  jevAnswer,
  jevIds,
  jevResult,
  JEV_TITLES,
  outcomeText,
  parseJevSetpoints,
  parseJevZone,
  readJev,
  type JevSetpoints,
} from "@/lib/jev";
import { referenceLines } from "@/lib/sensor-context";
import { buildSetpointPreview } from "@/lib/setpoint-preview";
import { jevChip, TARGET_GROUPS } from "@/lib/targets";
import { PROBE_TONE, zoneProbes } from "@/lib/probes";
import type { Controller, Zone } from "@/lib/types";
import { dayWord } from "@/lib/utils";
import { waitingText } from "@/lib/waiting-for";
import "./zone.css";

const PHASE_NAMES: Record<string, string> = {
  P0: "Morning dryback",
  P1: "Ramp-up",
  P2: "Maintenance",
  P3: "Overnight dryback",
};
const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** One zone: what it did today and why, whether it is on its stage's curve, whether its probes tell
 * the truth, and what happens next. Reached from its card on Today; the switcher moves between
 * zones. */
export function ZonePage({
  controller,
  zoneId,
  navigate,
}: {
  controller: Controller;
  zoneId: number | null;
  navigate: (page: Page, zone?: number) => void;
}) {
  const zones = controller.room.zones;
  const zone = zones.find((item) => item.id === zoneId) ?? zones[0];
  if (!zone)
    return (
      <>
        <h1 className="zone-empty-title">Zone</h1>
        <section className="panel">
          <Empty
            title="No zones discovered"
            detail="Zones appear once the room’s zones are configured in Equipment › Setup."
            action={<Button onClick={() => navigate("equipment/setup")}>Open setup</Button>}
          />
        </section>
      </>
    );
  const { states, room } = controller;
  const steering = steeringOf(
    states[`select.crop_steering_${room.room.prefix}zone_${zone.id}_steering_mode`]?.state,
    readJev(states, room.room.prefix).room?.stage?.steering,
  );
  // Jev on this zone shows while the room runs Jev (its journal, or its word on this zone).
  const jev =
    !!readJev(states, room.room.prefix).log ||
    !!parseJevZone(states[jevIds(room.room.prefix).zone(zone.id)]);
  return (
    <div className="zone-page" data-zone-page={zone.id}>
      <div className="zone-page-bar">
        <Button variant="ghost" size="sm" onClick={() => navigate("today")}>
          <ArrowLeft size={15} aria-hidden="true" /> Today
        </Button>
        {zones.length > 1 && (
          <nav className="zone-switcher" aria-label="Zones">
            {zones.map((item) => (
              <button
                type="button"
                key={item.id}
                aria-current={item.id === zone.id ? "page" : undefined}
                onClick={() => navigate("zone", item.id)}
              >
                {item.name}
              </button>
            ))}
          </nav>
        )}
      </div>
      <div className="zone-page-title">
        <h1>{zone.name}</h1>
        {/^P[0-3]$/.test(zone.phase) ? (
          <span className="pill" data-phase={zone.phase}>
            {zone.phase} · {PHASE_NAMES[zone.phase]}
          </span>
        ) : (
          <Pill tone="unknown">Phase unavailable</Pill>
        )}
        <Pill
          dot
          tone={zone.valveOn === true ? "on" : zone.valveOn === false ? "off" : "unknown"}
          data-zone-valve={zone.id}
          title={zone.valveEntity ?? "No valve mapped in this room's engine configuration"}
        >
          Valve {zone.valveOn === true ? "open" : zone.valveOn === false ? "shut" : "unknown"}
        </Pill>
        {zone.enabled === false && (
          <Pill dot tone="warn">
            Scheduling paused
          </Pill>
        )}
        {zone.stale && (
          <Pill
            dot
            tone="warn"
            title="The controller is not reporting: phase and status are its last report, not live."
          >
            Stale
          </Pill>
        )}
        {steering && (
          <span className="zone-steering" data-steering={steering}>
            {capital(steering)}
          </span>
        )}
      </div>
      <ZoneDay key={zone.id} controller={controller} zone={zone} />
      {/* Why it did what it did beside what happens next: Jev's decisions and the probes on the
          left, the controller's next step, the controls and the targets on the right. Without Jev
          the controls join the probes, so the columns stay about even. */}
      <div className="zone-page-grid">
        <div className="zone-page-column">
          {jev && <JevOnZone controller={controller} zone={zone} navigate={navigate} />}
          <ZoneProbes controller={controller} zone={zone} navigate={navigate} />
          {!jev && <ZoneControls key={zone.id} controller={controller} zone={zone} />}
        </div>
        <div className="zone-page-column">
          {jev && <ZoneControls key={zone.id} controller={controller} zone={zone} />}
          <ZoneTargets controller={controller} zone={zone} navigate={navigate} />
        </div>
      </div>
      <HistoryChart
        key={`history-${zone.id}`}
        controller={controller}
        zones={[zone]}
        title="History"
        ranges={[
          { hours: 48, label: "Yesterday" },
          { hours: 168, label: "7 days" },
        ]}
      />
      <RecordedBehaviour key={`recorded-${zone.id}`} controller={controller} zone={zone} />
    </div>
  );
}

/** What Jev says about this zone: which judges act on it now, each judge's last word, the setpoints
 * it may move and within what range, and its latest decisions here with how they turned out. */
function JevOnZone({
  controller,
  zone,
  navigate,
}: {
  controller: Controller;
  zone: Zone;
  navigate: (page: Page, zone?: number) => void;
}) {
  const { states, room } = controller;
  const ids = jevIds(room.room.prefix);
  const { log } = readJev(states, room.room.prefix);
  const sensor = parseJevZone(states[ids.zone(zone.id)]);
  const setpoints = parseJevSetpoints(states[ids.zone(zone.id)]);
  if (!log && !sensor) return null;
  const { rest, outcomes } = attachOutcomes(log?.entries ?? []);
  const recent = rest.filter((entry) => entry.zone === zone.id).slice(0, 6);
  const now = Date.now();
  return (
    <section className="panel zone-jev" aria-labelledby="zone-jev-title" data-zone-jev>
      <div className="panel-heading">
        <div>
          <h2 id="zone-jev-title">Jev on this zone</h2>
          <p>
            {sensor?.acting.length
              ? `Acting now: ${sensor.acting.map((judge) => JEV_TITLES[judge] ?? judge).join(", ")}`
              : "Watching: no judge acting on this zone now"}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => navigate("history/timeline", zone.id)}>
          History <ArrowRight size={15} aria-hidden="true" />
        </Button>
      </div>
      <div className="zone-panel-body">
        {setpoints && <JevSetpointsLine setpoints={setpoints} />}
        {!!sensor?.judges.length && (
          <ul className="zone-judges" aria-label="Each judge's last word on this zone">
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
          <ol className="zone-jev-list" aria-label="Jev's latest decisions on this zone">
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
    </section>
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
        ? `Jev may move the P2 ${parts.filter(Boolean).join(" and ")}.`
        : "Jev leaves this zone’s setpoints alone (Auto setpoints off, or a grow plan holds them)."}
      {setpoints.last && ` Last change ${lastChange(setpoints.last).replaceAll("->", "→")}.`}
      {paused && ` Paused until ${clock(setpoints.pausedUntil)} after a rescue put a change back.`}
    </p>
  );
}

/** Jev's own "2026-09-27 22:57: P2 shot 4.5% -> 4%" with the stamp as a day and a clock time. */
function lastChange(last: string) {
  const parts = last.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::\d{2})?: (.+)$/);
  if (!parts) return last;
  const [, year, month, day, hour, minute, what] = parts;
  const at = new Date(+year, +month - 1, +day, +hour, +minute).getTime();
  const word = dayWord(at, Date.now());
  return `${word === "Yesterday" ? "yesterday" : word || "today"} ${clock(at)}: ${what}`;
}

/** The zone's targets as the controller uses them now, with Jev's range where it manages one; they
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
          <h2 id="zone-probes-title">Probes</h2>
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
  // The controller's own thresholds against the readings now: what moving a phase by hand skips.
  const waiting = zone.waiting
    ? waitingText(zone.waiting, { number: (value) => number(value), clock })
    : "";
  return (
    <section className="panel zone-controls" aria-labelledby="zone-controls-title">
      <div className="panel-heading">
        <h2 id="zone-controls-title">Controls</h2>
      </div>
      <div className="zone-panel-body">
        {waiting && (
          <p className="zone-waiting">
            <span>The controller waits for</span> {waiting}
          </p>
        )}
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
                  title={`${phase} · ${name}: the controller moves the zone within a minute and carries on from there. Lights-off still moves it to P3, and lights-on to P0.`}
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
          title="Review zone scheduling"
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

/** What the probes recorded over days, against the zone's targets: opened on request. */
function RecordedBehaviour({ controller, zone }: { controller: Controller; zone: Zone }) {
  const [open, setOpen] = useState(false);
  const connected = ["live", "demo"].includes(controller.connection);
  const sensor = useSensorContext(controller, zone, open && connected);
  const preview = buildSetpointPreview(controller.room, controller.states, zone.id, {});
  return (
    <details
      className="zone-recorded"
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>Recorded behaviour against the targets: typical peak, trough and dryback</summary>
      {open && (
        <SensorContextCard
          context={sensor}
          lines={referenceLines({
            draft: preview.saved.parameters,
            typicalDailyPeak: sensor.vwc.stats?.typicalDailyPeak ?? null,
            learnedPeak: zone.auto?.learnedPeak ?? null,
          })}
          subtitle="what the probes read, with the zone’s targets drawn over it"
          disabledNote="Recorded history loads while Home Assistant is connected."
        />
      )}
    </details>
  );
}
