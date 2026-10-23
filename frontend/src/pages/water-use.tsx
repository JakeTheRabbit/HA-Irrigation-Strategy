import { useEffect, useMemo, useState } from "react";
import { Empty, Heading } from "@/components/dashboard";
import { Pill } from "@/components/mini-visuals";
import { NeedsIntegration } from "@/components/needs-integration";
import { ArcGauge } from "@/components/primitives/arc-gauge";
import { HoldButton } from "@/components/primitives/hold-button";
import { WaterUsePanel } from "@/components/water-use";
import { WaterVpdCard } from "@/components/sensing";
import { getDisplayUnits, formatVolume, useDisplayUnits } from "@/lib/display-units";
import type { Span, TimelineRows } from "@/lib/day-timeline";
import {
  FLOW_HIGH,
  FLOW_LOW,
  blockedSince,
  dailyRatios,
  latestReconciled,
  leakIncidents,
  leakVerdict,
  leakWatch,
  meterShared,
  roomPump,
  spanWords,
  trendWord,
  zoneFlow,
  zoneMeter,
  type ZoneFlow,
} from "@/lib/flow-check";
import { descriptor } from "@/lib/model";
import { pagedQuery, useParity, type V2Outcome } from "@/lib/parity-api";
import { demoLeakTimeline } from "@/lib/parity-demo/water";
import type { CsEvent, SupplyDoc } from "@/lib/parity-types";
import { clock, dayKey, dayLabel, hourTicks, startOfDay } from "@/lib/time";
import type { Controller, Zone } from "@/lib/types";
import { errorText } from "@/lib/utils";
import { zonePlants } from "@/lib/water-view";
import "./water-use.css";

const DAY = 86_400_000;
const KINDS = ["flow.reconciled", "shot.started", "shot.completed", "alert.raised"];

/** History › Water & flow (mockup 10): did the water each shot asked for reach the plants, as the
 * zone's flow meter counted it; water through the meter with every valve shut; water per plant
 * against the room. Then the controller's own counters: each zone's litres by grow week, and its
 * drying against VPD. Before 3.18 the metered part is "Needs integration". */
export function WaterUsePage({ controller }: { controller: Controller }) {
  useDisplayUnits(controller);
  const { zones } = controller.room;
  const supply = useParity<SupplyDoc>(controller, "supply_get", {}, []);
  const roomId = "room:" + controller.room.room.prefix;
  const pump = descriptor(controller.states, controller.room.room)?.attributes.pump;
  const meters = supply.data ? zones.map((zone) => zoneMeter(supply.data, roomId, zone.id, pump)) : [];
  const meter = mostCommon(meters);
  const others = controller.rooms.map((room) => {
    const attributes = descriptor(controller.states, room)?.attributes;
    const count = Number(attributes?.num_zones) || 0;
    return { id: "room:" + room.prefix, pump: attributes?.pump, zones: Array.from({ length: count }, (_, i) => i + 1) };
  });
  const shared = !!meter && meterShared(supply.data, others, roomId, meter);
  const oneAtATime = roomPump<{ max_concurrent_zones?: unknown }>(supply.data?.irrigation_pumps, pump)?.max_concurrent_zones === 1;
  return (
    <>
      <Heading title="Water & flow" action={meter ? <MeterLine controller={controller} meter={meter} /> : undefined} />
      {supply.state === "missing" ? (
        <>
          <div className="wf-intro">
            <h2>Did the water reach the plants?</h2>
          </div>
          <NeedsIntegration feature="Metered flow check" />
        </>
      ) : supply.state === "error" ? (
        <p className="panel wf-note" role="alert">
          Could not read the water supply: {supply.error}
        </p>
      ) : supply.state === "ready" && zones.length ? (
        meter ? (
          <FlowCheck controller={controller} meters={meters} meter={meter} shared={shared} oneAtATime={oneAtATime} />
        ) : (
          <section className="panel wf-no-meter" data-no-meter>
            <p>Add a flow meter to prove water reached the plants.</p>
            <a className="wf-link" href="#/equipment/setup">
              Map a flow meter
            </a>
          </section>
        )
      ) : null}
      {zones.length ? (
        <>
          <WaterUsePanel controller={controller} zones={zones} title="Litres by zone" />
          <WaterVpdCard controller={controller} />
        </>
      ) : (
        <section className="panel">
          <Empty
            title="No zones found"
            detail="Water use appears once the room’s zones are configured and report their water."
          />
        </section>
      )}
    </>
  );
}

function mostCommon(values: (string | null)[]): string | null {
  const counts = new Map<string, number>();
  for (const value of values) if (value) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
}

/** The room's meter, as Home Assistant reads it now. Home Assistant's live states carry when the
 * value last changed, not when the meter last reported: a still meter shows an older time. */
function MeterLine({ controller, meter }: { controller: Controller; meter: string }) {
  const entity = controller.states[meter];
  const name = String(entity?.attributes.friendly_name ?? meter);
  const changed = Date.parse(entity?.last_changed ?? "");
  const reading = entity && entity.state.trim() !== "" && Number.isFinite(Number(entity.state));
  return (
    <p className="wf-meter" data-meter-line>
      <span className="wf-dot" data-ok={reading ? "" : undefined} aria-hidden />
      {name}
      {reading && Number.isFinite(changed)
        ? ` · last changed ${clock(changed, controller.timeZone)}`
        : " · not reading"}
    </p>
  );
}

function useFlowEvents(controller: Controller, since: number) {
  const roomId = controller.roomId;
  const connected = ["live", "demo"].includes(controller.connection);
  const [read, setRead] = useState<{ key: string; outcome: V2Outcome<{ events: CsEvent[] }> } | null>(null);
  // A shot the meter has counted since (the live feed): read the Journal again for its bar.
  const fresh = latestReconciled(controller.recentEvents, roomId);
  const key = `${roomId}|${since}`;
  useEffect(() => {
    if (!connected) return;
    let live = true;
    void pagedQuery(controller, { room_id: roomId, since: new Date(since).toISOString(), kinds: KINDS }).then(
      (outcome) => live && setRead({ key, outcome }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, connected, fresh]);
  return read?.key === key ? read.outcome : null;
}

function FlowCheck({
  controller,
  meters,
  meter,
  shared,
  oneAtATime,
}: {
  controller: Controller;
  meters: (string | null)[];
  meter: string;
  shared: boolean;
  oneAtATime: boolean;
}) {
  const tz = controller.timeZone;
  // The page's day: read once as it opens (the Journal read is one snapshot).
  const [now] = useState(() => Date.now());
  const dayStart = startOfDay(now, tz);
  const since = startOfDay(dayStart - 6 * DAY + 12 * 3_600_000, tz);
  const read = useFlowEvents(controller, since);
  const events = read?.kind === "ok" ? read.data.events : [];
  const zones = controller.room.zones;
  const flows = useMemo(
    () => zones.map((zone) => zoneFlow(events, zone.id, dayStart)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [events, dayStart, zones.map((zone) => zone.id).join()],
  );
  if (!read)
    return controller.connection === "offline" ? (
      <p className="panel wf-note" role="alert">
        Not connected to Home Assistant: the controller’s Journal cannot be read.
      </p>
    ) : (
      <p className="wf-loading muted">Reading the controller’s Journal…</p>
    );
  if (read.kind === "missing") return <NeedsIntegration feature="Metered flow check" />;
  if (read.kind === "error")
    return (
      <p className="panel wf-note" role="alert">
        Could not read the Journal: {read.message}
      </p>
    );
  const shotsToday = (zone: number) =>
    events.filter((e) => e.kind === "shot.completed" && e.zone === zone && Date.parse(e.ts) >= dayStart).length;
  return (
    <>
      <div className="wf-intro">
        <h2>Did the water reach the plants?</h2>
        <p>
          {controller.room.room.name} today · metered litres against what each shot asked for.
          {oneAtATime && !shared ? " Shots run one zone at a time, so every litre is counted against its own zone." : ""}
        </p>
      </div>
      <div className="wf-zones">
        {zones.map((zone, i) => (
          <ZoneCard
            key={zone.id}
            controller={controller}
            zone={zone}
            flow={flows[i]}
            metered={!!meters[i]}
            shots={shotsToday(zone.id)}
            days={dailyRatios(events, zone.id, now, tz)}
          />
        ))}
      </div>
      <div className="wf-lower">
        <LeakCheck controller={controller} meter={meter} shared={shared} events={events} now={now} dayStart={dayStart} />
        <WaterPerPlant controller={controller} flows={flows} />
      </div>
    </>
  );
}

const pct = (value: number) => `${Math.round(value)}%`;

function ZoneCard({
  controller,
  zone,
  flow,
  metered,
  shots,
  days,
}: {
  controller: Controller;
  zone: Zone;
  flow: ZoneFlow;
  metered: boolean;
  shots: number;
  days: (number | null)[];
}) {
  const plants = zonePlants(controller, zone.id);
  const facts = [plants ? `${plants} plants` : null, `${shots} ${shots === 1 ? "shot" : "shots"}`].filter(Boolean).join(" · ");
  const asked = flow.shots.reduce((sum, s) => sum + s.askedL, 0);
  const got = flow.shots.reduce((sum, s) => sum + s.meteredL, 0);
  const trend = trendWord(days);
  const low = flow.verdict === "low";
  return (
    <section className="panel wf-zone" data-flow-zone={zone.id} data-flow-verdict={flow.verdict} aria-labelledby={`wf-zone-${zone.id}`}>
      <header className="wf-zone-head">
        <h3 id={`wf-zone-${zone.id}`}>
          {zone.name} <small>{facts}</small>
        </h3>
        <VerdictChip verdict={flow.verdict} metered={metered} />
      </header>
      {flow.last3Pct === null ? (
        <p className="muted">
          {metered
            ? "No shot reconciled yet: the meter’s first count shows after this zone’s next shot."
            : "No flow meter counts this zone’s water."}
        </p>
      ) : (
        <>
          <div className="wf-gauge-row">
            <ArcGauge
              value={Math.round(flow.last3Pct)}
              min={40}
              max={160}
              band={[FLOW_LOW * 100, FLOW_HIGH * 100]}
              tone={flow.verdict === "on_target" ? "ok" : "warn"}
              label={`${zone.name} metered vs asked, last 3 shots`}
              unit="%"
            />
            <div className="wf-gauge-words">
              <strong data-tone={flow.verdict === "on_target" ? undefined : "warn"}>{pct(flow.last3Pct)}</strong>
              <span>metered vs asked, last 3 shots</span>
              {flow.todayPct !== null && (
                <span className="wf-today">
                  <b>Today {pct(flow.todayPct)}</b> · {formatVolume(got, 3).replace(/\s\S+$/, "")} of {formatVolume(asked, 3)}
                </span>
              )}
            </div>
          </div>
          {flow.shots.length > 0 && <ShotBars flow={flow} tz={controller.timeZone} zone={zone.name} />}
          <div className="wf-week">
            <span>
              Last 7 days{trend ? <b>{trend}</b> : null}
            </span>
            <WeekLine days={days} zone={zone.name} />
          </div>
        </>
      )}
      {low && <BlockedCard controller={controller} zone={zone} since={blockedSince(flow.shots)} />}
      {flow.verdict === "high" && (
        <p className="wf-high" role="note">
          <b>More water than asked.</b> The meter counted more than the shots asked for: check {zone.name} for a split line
          or a dripper off its stake.
        </p>
      )}
    </section>
  );
}

function VerdictChip({ verdict, metered }: { verdict: ZoneFlow["verdict"]; metered: boolean }) {
  if (verdict === "no_meter") return <Pill tone="neutral">{metered ? "Not counted yet" : "No meter"}</Pill>;
  return (
    <Pill dot tone={verdict === "on_target" ? "on" : "warn"} data-flow-chip>
      {verdict === "on_target" ? "On target" : verdict === "low" ? "Blocked line?" : "More than asked"}
    </Pill>
  );
}

/** Asked (hollow) and metered (filled) litres of each shot today. */
function ShotBars({ flow, tz, zone }: { flow: ZoneFlow; tz: string; zone: string }) {
  const { shots } = flow;
  const top = Math.max(...shots.flatMap((s) => [s.askedL, s.meteredL])) * 1.12 || 1;
  const maxAsked = Math.max(...shots.map((s) => s.askedL));
  const width = 320,
    height = 120,
    base = 100;
  const slot = width / shots.length;
  const bar = Math.min(14, slot / 3);
  const y = (l: number) => base - (l / top) * (base - 6);
  const every = Math.ceil(shots.length / 7);
  return (
    <figure className="wf-bars">
      <figcaption>
        <span>Per shot, {getDisplayUnits().volume === "gal" ? "gallons" : "litres"}</span>
        <span className="wf-legend">
          <i data-key="asked" /> Asked <i data-key="metered" /> Metered
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${zone}: ${shots.length} shots today, asked against metered`}>
        <line className="wf-bars-top" x1="0" x2={width} y1={y(maxAsked)} y2={y(maxAsked)} />
        <text className="wf-bars-scale" x={width} y={y(maxAsked) - 3} textAnchor="end">
          {formatVolume(maxAsked, 2)}
        </text>
        {shots.map((s, i) => {
          const x = i * slot + slot / 2;
          const short = s.askedL > 0 && s.meteredL / s.askedL < FLOW_LOW;
          return (
            <g key={s.at}>
              <rect className="wf-bar-asked" x={x - bar - 1} y={y(s.askedL)} width={bar} height={base - y(s.askedL)} />
              <rect className="wf-bar-metered" data-short={short ? "" : undefined} x={x + 1} y={y(s.meteredL)} width={bar} height={base - y(s.meteredL)} />
              {i % every === 0 && (
                <text className="wf-bars-time" x={x} y={height - 4} textAnchor="middle">
                  {clock(s.at, tz)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

/** Each day's mean metered against asked, the 80–120% band shaded. */
function WeekLine({ days, zone }: { days: (number | null)[]; zone: string }) {
  const width = 200,
    height = 32;
  const lo = 0.4,
    hi = 1.6;
  const y = (r: number) => height - ((Math.min(hi, Math.max(lo, r)) - lo) / (hi - lo)) * height;
  const x = (i: number) => (i / Math.max(1, days.length - 1)) * width;
  const points = days.map((d, i) => (d === null ? null : `${x(i).toFixed(1)},${y(d).toFixed(1)}`)).filter(Boolean);
  const words = days.map((d) => (d === null ? "none" : pct(d * 100))).join(", ");
  return (
    <svg className="wf-weekline" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={`${zone} metered vs asked by day, oldest first: ${words}`}>
      <rect className="wf-weekline-band" x="0" width={width} y={y(FLOW_HIGH)} height={y(FLOW_LOW) - y(FLOW_HIGH)} />
      {points.length > 1 && <polyline points={points.join(" ")} />}
      {points.length > 0 && <circle r="3" cx={points.at(-1)!.split(",")[0]} cy={points.at(-1)!.split(",")[1]} />}
    </svg>
  );
}

/** The problem in place: on the zone whose metered water fell under 80%. */
function BlockedCard({ controller, zone, since }: { controller: Controller; zone: Zone; since: number | null }) {
  const [sent, setSent] = useState<{ at: number } | { error: string } | null>(null);
  const seconds = Number(controller.states[`number.crop_steering_${controller.room.room.prefix}zone_${zone.id}_manual_shot_seconds`]?.state);
  const label = Number.isFinite(seconds) && seconds > 0 ? `Run ${seconds} s test shot on ${zone.name}` : `Run a test shot on ${zone.name}`;
  const connected = ["live", "demo"].includes(controller.connection);
  const run = () => {
    setSent(null);
    controller
      .operator<{ requested: string | null }>("test_shot", { room_id: "room:" + controller.room.room.prefix, zone: zone.id })
      .then(
        (answer) => setSent({ at: Date.parse(answer.requested ?? "") || Date.now() }),
        (error: unknown) => setSent({ error: errorText(error) }),
      );
  };
  return (
    <div className="wf-blocked" role="note" data-blocked-card>
      <p>
        <b>Blocked line?</b>{" "}
        {since !== null ? `Metered water dropped from the ${clock(since, controller.timeZone)} shot on. ` : "Metered water is under 80% of what the shots asked for. "}
        Check the {zone.name} drippers and line filter.
      </p>
      <div className="wf-blocked-actions">
        <HoldButton
          mode="hold-to-confirm"
          label={label}
          srLabel="Hold for 1.5 seconds to ask the controller for the shot. It runs through every safety check of a shot."
          maxSeconds={60}
          disabledReason={connected ? undefined : "Connect to Home Assistant to run a test shot."}
          onStart={run}
        />
        <a className="wf-link" href="#/equipment/setup">
          Open catch test
        </a>
      </div>
      {sent && (
        <p className="small" role="status" data-test-shot-receipt>
          {"error" in sent
            ? `The test shot was not sent: ${sent.error}`
            : `Test shot asked for at ${clock(sent.at, controller.timeZone)}. Its bar shows here once the meter has counted it.`}
        </p>
      )}
    </div>
  );
}

const span = (ms: number) => {
  const minutes = Math.round(ms / 60_000);
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
};

const LEAK_CHIP = {
  flowing: "Water with valves shut",
  clear: "Clear today",
  no_alert: "No alert today",
  unwatched: "Not watched",
} as const;

/** Water through the meter while every valve is shut: today's lanes, then the last 7 days' CS-319s. */
function LeakCheck({
  controller,
  meter,
  shared,
  events,
  now,
  dayStart,
}: {
  controller: Controller;
  meter: string;
  /** Another room reads this meter too: this room's valves alone cannot tell its shots from a leak. */
  shared: boolean;
  events: CsEvent[];
  now: number;
  dayStart: number;
}) {
  const tz = controller.timeZone;
  const valves = Object.fromEntries(
    controller.room.zones.flatMap((zone) => (zone.valveEntity ? [[zone.valveEntity, zone.id] as const] : [])),
  );
  const valveKey = Object.keys(valves).join();
  const [rows, setRows] = useState<{ key: string; rows: TimelineRows | null; error: string | null } | null>(null);
  const key = `${meter}|${valveKey}|${dayStart}`;
  useEffect(() => {
    let live = true;
    const request = { entityIds: [...Object.keys(valves), meter], attributeIds: [], start: dayStart, end: now };
    const load = controller.demo
      ? Promise.resolve(demoLeakTimeline(valves, meter, dayStart, dayStart + DAY, now))
      : controller.timeline(request);
    load.then(
      (answer) => live && setRows({ key, rows: answer, error: null }),
      (error: unknown) => live && setRows({ key, rows: null, error: errorText(error) }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const read = rows?.key === key ? rows : null;
  const unit = controller.states[meter]?.attributes.unit_of_measurement;
  const watch = read?.rows
    ? leakWatch(Object.keys(valves).map((id) => read.rows![id] ?? []), read.rows[meter] ?? [], unit, dayStart, now)
    : null;
  const incidents = leakIncidents(events);
  const today = incidents.filter((i) => i.at >= dayStart);
  const verdict = watch ? leakVerdict(watch, today.length, shared) : null;
  const flowing = verdict === "flowing";
  const days = Array.from({ length: 7 }, (_, i) => startOfDay(dayStart - (6 - i) * DAY + 12 * 3_600_000, tz));
  const last = incidents.at(-1);
  const x = (t: number) => (((Math.min(dayStart + DAY, Math.max(dayStart, t)) - dayStart) / DAY) * 100).toFixed(2);
  const lane = (spans: Span[], kind: string, words: string) => (
    <div className="wf-lane" data-lane={kind} role="img" aria-label={`${words}: ${spanWords(spans, tz)}`}>
      {spans.map((s) => (
        <span key={s.start} style={{ left: `${x(s.start)}%`, width: `max(2px, ${(Number(x(s.end)) - Number(x(s.start))).toFixed(2)}%)` }} />
      ))}
      <span className="wf-lane-future" style={{ left: `${x(now)}%` }} />
    </div>
  );
  return (
    <section className="panel wf-leak" data-leak-check aria-labelledby="wf-leak-title">
      <header className="wf-card-head">
        <h3 id="wf-leak-title">
          Leak check <small>water through the meter while every valve is shut</small>
        </h3>
        {verdict && (
          <Pill dot={verdict === "flowing" || verdict === "clear"} tone={flowing ? "warn" : verdict === "clear" ? "on" : "neutral"} data-leak-chip>
            {LEAK_CHIP[verdict]}
          </Pill>
        )}
      </header>
      {read?.error ? (
        <p className="muted" role="alert">
          Could not read the recorded valves and meter: {read.error}
        </p>
      ) : !watch ? (
        <p className="muted">Reading the recorded valves and meter…</p>
      ) : (
        <div className="wf-lanes">
          <span>{shared ? "This room’s valves" : "Valve open"}</span>
          {lane(watch.valveOpen, "valve", shared ? "This room’s valves open" : "Valve open")}
          <span>Meter flow</span>
          {lane(watch.meterFlow, "meter", "Meter flow")}
          <span>Flow, valves shut</span>
          <p className="wf-shut" data-shut-flow data-tone={flowing ? "warn" : undefined}>
            {shared
              ? "Another room’s zones run through this meter too: only the controller’s alert tells water with every valve shut."
              : watch.litres === null
                ? `The meter reads in ${String(unit ?? "no unit")}, not litres: nothing to count.`
                : watch.watchedMs <= 0
                  ? "No meter reading today: nothing watched."
                  : `${formatVolume(watch.litres, 2)} in ${span(watch.watchedMs)} watched`}
          </p>
          <span aria-hidden />
          <div className="wf-ticks" aria-hidden>
            {[...hourTicks(dayStart, dayStart + DAY, 6, tz), dayStart + DAY].map((t, i) => (
              <span key={t} style={{ left: `${x(t)}%` }}>
                {i === 4 ? "24:00" : clock(t, tz)}
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="wf-days">
        <span>Last 7 days</span>
        <ol aria-label="Water with every valve shut, last 7 days">
          {days.map((d) => {
            const hit = incidents.some((i) => dayKey(i.at, tz) === dayKey(d, tz));
            const name = dayLabel(d, tz).split(" ")[0];
            return (
              <li key={d} data-hit={hit ? "" : undefined} aria-label={`${dayLabel(d, tz)}: ${hit ? "water with valves shut" : "clear"}`}>
                <i aria-hidden />
                {name}
              </li>
            );
          })}
        </ol>
        {last && (
          <p data-leak-last>
            <b>
              {dayLabel(last.at, tz).split(" ").slice(0, 2).join(" ")}, {clock(last.at, tz)}
            </b>{" "}
            {last.title}
            {last.litres !== null ? ` · ${formatVolume(last.litres, 2)}` : ""}
          </p>
        )}
      </div>
    </section>
  );
}

/** Water per plant in the display's unit: mL under litres, the volume's own unit in gallons. */
const perPlant = (ml: number) => (getDisplayUnits().volume === "gal" ? formatVolume(ml / 1000, 3) : `${Math.round(ml)} mL`);

/** Metered water per plant today, zone against zone, the room's median marked. */
function WaterPerPlant({ controller, flows }: { controller: Controller; flows: ZoneFlow[] }) {
  const rows = controller.room.zones.flatMap((zone, i) => {
    const plants = zonePlants(controller, zone.id);
    const shots = flows[i].shots;
    if (!plants || !shots.length) return [];
    const metered = (shots.reduce((sum, s) => sum + s.meteredL, 0) * 1000) / plants;
    const asked = (shots.reduce((sum, s) => sum + s.askedL, 0) * 1000) / plants;
    return [{ zone, metered, asked, low: flows[i].verdict === "low" }];
  });
  if (!rows.length) return null;
  const sorted = rows.map((r) => r.metered).sort((a, b) => a - b);
  const mid = sorted.length / 2;
  const median = sorted.length % 2 ? sorted[Math.floor(mid)] : (sorted[mid - 1] + sorted[mid]) / 2;
  const top = Math.max(...rows.flatMap((r) => [r.metered, r.asked]), median) * 1.15;
  const at = (ml: number) => `${((ml / top) * 100).toFixed(2)}%`;
  const under = rows.filter((r) => r.metered < median * 0.9).sort((a, b) => a.metered - b.metered)[0];
  return (
    <section className="panel wf-plant" data-water-per-plant aria-labelledby="wf-plant-title">
      <header className="wf-card-head">
        <h3 id="wf-plant-title">
          Water per plant <small>metered today, against the room median</small>
        </h3>
      </header>
      <ul className="wf-plant-rows">
        {rows.map((r) => (
          <li key={r.zone.id} data-plant-zone={r.zone.id}>
            <span>{r.zone.name}</span>
            <span className="wf-plant-track" role="img" aria-label={`${r.zone.name}: ${perPlant(r.metered)} a plant metered, ${perPlant(r.asked)} asked, room median ${perPlant(median)}`}>
              <span className="wf-plant-fill" data-tone={r.low ? "warn" : undefined} style={{ width: at(r.metered) }} />
              <span className="wf-plant-asked" style={{ left: at(r.asked) }} />
              <span className="wf-plant-median" style={{ left: at(median) }} />
            </span>
            <b data-tone={r.low ? "warn" : undefined}>{perPlant(r.metered)}</b>
          </li>
        ))}
      </ul>
      <p className="wf-plant-key">
        <i data-key="median" /> Room median {perPlant(median)} <i data-key="asked" /> Asked
      </p>
      {under && (
        <p className="wf-plant-note" role="note">
          <b>
            {under.zone.name} is {perPlant(median - under.metered)} a plant under the median.
          </b>{" "}
          It asked for {perPlant(under.asked)}
          {/* Most of the gap is water asked for that did not arrive, or the plan asked for less. */}
          {under.asked - under.metered >= (median - under.metered) / 2
            ? under.low
              ? ", so the gap is most likely the blocked line, not the plan."
              : ", so the gap is water that did not arrive, not the plan."
            : ", so the gap is mostly the plan asking for less."}
        </p>
      )}
    </section>
  );
}
