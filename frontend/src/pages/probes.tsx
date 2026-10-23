import { CanonicalControls } from "@/components/canonical-controls";
import { Fragment, useEffect, useRef, useState } from "react";
import { ArrowRight, Search, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Empty, Heading, Status, time, type Page } from "@/components/dashboard";
import { UiTip } from "@/components/info-tip";
import { JevTrouble, jevUsage } from "@/components/jev-status";
import { Pill, Sparkline } from "@/components/mini-visuals";
import { NeedsIntegration } from "@/components/needs-integration";
import { ProbeCalibration } from "@/components/probe-calibration";
import { ReviewApply, type ReviewRow } from "@/components/review-apply";
import { ageText, readHeartbeat } from "@/lib/controller-health";
import { formatEc, formatTemp } from "@/lib/display-units";
import { recentReadings } from "@/lib/dryback";
import { brainWords, readJev } from "@/lib/jev";
import { descriptor, numeric } from "@/lib/model";
import type { SetupDocument, SetupRoom } from "@/lib/operator-types";
import { callV2, type V2Outcome } from "@/lib/parity-api";
import {
  applyOffset,
  curveDisabledReason,
  handheldOffset,
  moisturePct,
  offsetsBlocked,
  previewOffset,
  readOffsets,
  signedPoints,
  type OffsetAnswer,
  type ProbeOffset,
} from "@/lib/probe-offset";
import {
  PROBE_TONE,
  READING_REASON,
  healthChip,
  placementProblem,
  probeChoicePayload,
  probeCounts,
  probeChoices,
  probeRows,
  zoneProbes,
  type Probe,
  type ProbeChoice,
  type ProbeRow,
} from "@/lib/probes";
import type { Controller, EntityState, RoomView, Zone } from "@/lib/types";
import { revertEvents } from "@/lib/undo";
import { useRecentHistory } from "@/lib/use-recent-moisture";
import { errorText } from "@/lib/utils";
import { rootZoneSensor } from "@/lib/zone-extras";
import "./probes.css";

/** Hours of readings each controller-sensor sparkline draws; each probe's line draws a day. */
const RECENT_H = 6;
const PROBE_H = 24;
const asId = (value: unknown) =>
  typeof value === "string" && /^[a-z_]+\.[a-z0-9_]+$/.test(value) ? value : "";
const pct = (value: number | null) => (value === null ? "—" : `${value.toFixed(1)}%`);
const digits = (state: string | undefined) => (state?.split(".")[1] ?? "").length;

/** The rooms' stored probe offsets (calibration_get): `missing` on an integration older than 3.18,
 * which keeps none; a room whose store cannot be read has none to show. */
function useOffsets(controller: Controller, roomIds: string[]) {
  const [read, setRead] = useState<{
    key: string;
    missing: boolean;
    rooms: Record<string, Record<string, ProbeOffset> | null>;
    blocked: Record<string, string | null>;
  } | null>(null);
  const [tick, setTick] = useState(0);
  const key = roomIds.join("|");
  useEffect(() => {
    let current = true;
    if (!["live", "demo"].includes(controller.connection) || !key) return;
    void Promise.all(
      key.split("|").map((id) => callV2<unknown>(controller, "calibration_get", { room_id: id })),
    ).then((outcomes) => {
      if (!current) return;
      setRead({
        key,
        missing: outcomes.some((outcome) => outcome.kind === "missing"),
        rooms: Object.fromEntries(
          key.split("|").map((id, index) => {
            const outcome = outcomes[index];
            return [id, outcome.kind === "ok" ? readOffsets(outcome.data) : null];
          }),
        ),
        blocked: Object.fromEntries(
          key.split("|").map((id, index) => {
            const outcome = outcomes[index];
            return [id, outcome.kind === "ok" ? offsetsBlocked(outcome.data) : null];
          }),
        ),
      });
    });
    return () => {
      current = false;
    };
  }, [key, controller.connection, tick]);
  const fallback: {
    missing: boolean;
    rooms: Record<string, Record<string, ProbeOffset> | null>;
    blocked: Record<string, string | null>;
  } = { missing: false, rooms: {}, blocked: {} };
  return { ...(read && read.key === key ? read : fallback), reload: () => setTick((n) => n + 1) };
}

/** The rooms' zones as Probes & offsets draws them: each moisture probe on a row, pore EC beside it. */
interface ZoneGroup {
  zone: Zone;
  rows: ProbeRow[];
}
interface RoomGroup {
  view: RoomView;
  zones: ZoneGroup[];
}

/** Equipment › Probes & offsets: the selected room's probes, under the room's name, whether to believe each one,
 * and each moisture probe's offset, matched to a handheld meter in place. Then the substrate curve, where
 * to put a probe, the probes that count, the feed-water probes' calibration, and one tap down the room
 * map and the controller's own sensors. */
export function Probes({
  controller,
  navigate,
  onDirtyChange,
}: {
  controller: Controller;
  navigate: (page: Page) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const { room, states } = controller;
  const now = Date.now();
  // The room the tree picks: each room's readings, history and calibration store are its own.
  const groups: RoomGroup[] = room.zones.length
    ? [{ view: room, zones: room.zones.map((zone) => ({ zone, rows: probeRows(zoneProbes(zone, states, now)) })) }]
    : [];
  const rows = groups.flatMap((group) => group.zones.flatMap((zone) => zone.rows));
  const probes = room.zones.flatMap((zone) => zoneProbes(zone, states, now));
  const history = useRecentHistory(
    controller,
    rows.flatMap((row) => [row.vwc.id, ...(row.ec ? [row.ec.id] : [])]),
    PROBE_H,
  );
  const offsets = useOffsets(
    controller,
    groups.map((group) => group.view.room.id),
  );
  const [open, setOpen] = useState<string | null>(null);
  const placement = useRef<HTMLElement>(null);
  const checkPlacement = () => {
    placement.current?.scrollIntoView({ block: "nearest" });
    placement.current?.focus();
  };
  const config = descriptor(states, room.room)?.attributes ?? {};
  const heartbeat = readHeartbeat(
    states[`sensor.crop_steering_${room.room.prefix}ai_heartbeat`],
    now,
  );
  const status = states[`sensor.crop_steering_${room.room.prefix}app_status`]?.state;
  const jev = readJev(states, room.room.prefix).room;
  const counts = probeCounts(rows);
  const hardware = [
    ["Pump", asId(config.pump)],
    ["Main-line valve", asId(config.mainline)],
    ["Feed-water EC", asId(config.feed_ec_sensor)],
    ["Feed-water pH", asId(config.feed_ph_sensor)],
  ].filter(([, id]) => id) as [string, string][];
  const misplaced = groups.flatMap((group) =>
    group.zones.flatMap(({ zone, rows }) =>
      rows
        .filter((row) => placementProblem(row.vwc))
        .map((row) => ({ room: group.view.room.name, zone: zone.name, row })),
    ),
  );
  const tempIds = new Set(
    groups.flatMap((group) => group.view.zones.map((zone) => rootZoneSensor(states, group.view.room, zone.id))),
  );
  const showTemp = [...tempIds].some(Boolean);
  const reload = () => {
    offsets.reload();
    void controller.refresh();
  };
  return (
    <>
      <Heading
        title="Probes & offsets"
        description={`${counts.total} ${counts.total === 1 ? "probe" : "probes"} · ${counts.used} in zone values · raw readings always kept`}
        action={<UiTip copyKey="probes" />}
      />
      <CanonicalControls controller={controller} owner="probes" onDirtyChange={onDirtyChange} />
      <section className="panel probes-status" aria-label="Controller and AI assistant">
        <div>
          <span className="eyebrow">Controller</span>
          <strong>
            {heartbeat.health === "fresh"
              ? "Reporting"
              : heartbeat.health === "stale"
                ? "Not reporting"
                : heartbeat.health === "missing"
                  ? "No heartbeat"
                  : heartbeat.health === "stopped"
                    ? "Stopped"
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
          <span className="eyebrow">AI assistant</span>
          <strong>{brainWords(jev).tile}</strong>
          <span className="muted small">
            {jev?.on ? jevUsage(jev, true) || "No calls today" : brainWords(jev).detail}
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
      <div className="probes-layout">
        <section className="panel probes-board" aria-label="Probes by room">
          {offsets.missing && (
            <div className="probes-missing" data-match-handheld-missing>
              <span>Match handheld</span>
              <NeedsIntegration feature="Matching a probe to a handheld meter" compact />
            </div>
          )}
          {!rows.length ? (
            <Empty
              title="No probes found"
              detail="Probes appear once the room’s zones are mapped in Setup."
            />
          ) : (
            <div className="table-scroll" tabIndex={0} role="region" aria-label="Probes, by room and zone">
              <table className="data-table probes-table">
                <thead>
                  <tr>
                    <th scope="col">Zone value</th>
                    <th scope="col">Health</th>
                    <th scope="col">Probe</th>
                    <th scope="col">Last 24 h</th>
                    <th scope="col" className="numeric">VWC</th>
                    <th scope="col" className="numeric">{showTemp ? "EC · Temp" : "EC"}</th>
                    <th scope="col" className="numeric">Offset</th>
                    <th scope="col">
                      <span className="sr-only">Action</span>
                    </th>
                  </tr>
                </thead>
                {groups.map((group) => (
                  <RoomRows
                    key={group.view.room.id}
                    controller={controller}
                    group={group}
                    offsets={offsets.missing ? null : (offsets.rooms[group.view.room.id] ?? null)}
                    v2={!offsets.missing}
                    blocked={offsets.missing ? null : (offsets.blocked[group.view.room.id] ?? null)}
                    history={history}
                    now={now}
                    open={open}
                    onOpen={setOpen}
                    onCheckPlacement={checkPlacement}
                    onChanged={reload}
                  />
                ))}
              </table>
            </div>
          )}
        </section>
        <aside className="probes-aside">
          <SubstrateCurve room={room} probes={probes} missing={offsets.missing} offsets={offsets.rooms[room.room.id] ?? null} />
          <section
            className="panel probe-placement"
            aria-labelledby="probe-placement-title"
            tabIndex={-1}
            ref={placement}
            data-placement-card
            data-warning={misplaced.length ? "" : undefined}
          >
            <h2 id="probe-placement-title">Where to put a probe</h2>
            {misplaced.map(({ room, zone, row }) => (
              <p className="probe-placement-warning" key={row.vwc.id} data-placement-warning={row.vwc.id}>
                <TriangleAlert size={17} aria-hidden="true" />
                <span>
                  {`${room} ${zone} ${row.side} reads ${pct(row.vwc.value)}`}
                  {row.vwc.health === "out-of-range"
                    ? ", which no probe can read: it is likely not seated, or sits in the drip. Move it, and it rejoins the zone value once it reads in range."
                    : ", far from the zone’s other probes: probably right under a dripper. Move it, and it rejoins the zone value once it reads like the others."}
                </span>
              </p>
            ))}
            <PlacementPicture />
            <ul>
              <li>Push straight down, prongs fully in, not touching the slab bottom.</li>
              <li>5–8 cm from the dripper, towards the middle of the slab.</li>
              <li>Not at a slab end, a drain slit or a cube edge.</li>
              <li>Front and back probes: same distance from their drippers.</li>
            </ul>
          </section>
        </aside>
      </div>
      <ProbePicker controller={controller} probes={probes} />
      {hardware.length > 0 && (
        <section className="panel" aria-labelledby="probes-room-title">
          <div className="panel-heading">
            <div>
              <h2 id="probes-room-title">Pump, main line and feed</h2>
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
      <ProbeCalibration controller={controller} />
      <RoomMap controller={controller} navigate={navigate} />
      <ControllerInternals controller={controller} />
      <p className="footnote">
        A probe the zone’s reading leaves out does not steer watering while another one reports.
        Reporting does not prove a probe is calibrated.
      </p>
    </>
  );
}

/** One room's zones: its name, how its probes are laid out and how many are healthy, then each moisture
 * probe's row, and the handheld match under the probe it is open on. */
function RoomRows({
  controller,
  group,
  offsets,
  v2,
  blocked,
  history,
  now,
  open,
  onOpen,
  onCheckPlacement,
  onChanged,
}: {
  controller: Controller;
  group: RoomGroup;
  /** The room's stored offsets; null where they are not known. */
  offsets: Record<string, ProbeOffset> | null;
  v2: boolean;
  /** Why the integration cannot set an offset in this room now, in its words; null when it can. */
  blocked: string | null;
  history: { entityId: string; points: { time: string; value: number }[] }[] | null;
  now: number;
  open: string | null;
  onOpen: (id: string | null) => void;
  onCheckPlacement: () => void;
  onChanged: () => void;
}) {
  const { view, zones } = group;
  const rows = zones.flatMap((zone) => zone.rows);
  const { healthy, total } = probeCounts(rows);
  const counts = new Set(zones.map((zone) => zone.rows.length));
  const sides = rows.every((row) => row.side === "Front" || row.side === "Back");
  const layout =
    counts.size === 1 && counts.has(1)
      ? "1 probe per zone"
      : counts.size === 1 && counts.has(2) && sides
        ? "2 per zone, front and back"
        : `${rows.length} moisture probes`;
  const points = (id: string) => history?.find((series) => series.entityId === id)?.points;
  return (
    <tbody data-probes-room={view.room.id}>
      <tr className="probes-room">
        <th scope="colgroup" colSpan={8}>
          <span className="probes-room-name">
            <span className="probes-room-dot" aria-hidden="true" />
            {view.room.name}
          </span>
          <span className="muted">{layout}</span>
          <span className="probes-room-health" data-tone={healthy < total ? "warn" : "ok"}>
            {healthy} of {total} {total === 1 ? "probe" : "probes"} healthy
          </span>
        </th>
      </tr>
      {blocked && (
        <tr className="probes-room-blocked">
          <td colSpan={8} role="status" data-offsets-blocked={view.room.id}>
            <TriangleAlert size={15} aria-hidden="true" /> {blocked}
          </td>
        </tr>
      )}
      {zones.map(({ zone, rows }) => {
        const usedRows = rows.filter((row) => row.vwc.used !== false && row.vwc.value !== null);
        // Raw readings in %, before any offset: what each probe itself reads around the zone's value.
        const values = usedRows
          .map((row) => moisturePct(row.vwc.value, row.vwc.unit))
          .filter((value): value is number => value !== null);
        const spread = values.length > 1 ? Math.max(...values) - Math.min(...values) : null;
        const stuck = rows.some((row) => row.vwc.health === "stuck");
        const sub =
          spread !== null
            ? `raw spread ${spread.toFixed(1)} points`
            : rows.length > 1
              ? `${usedRows.length} of ${rows.length} probes used`
              : `1 probe${stuck ? " · stuck" : ""}`;
        const editing = rows.find((row) => row.vwc.id === open);
        return rows.map((row, index) => {
          const offset = offsets ? (offsets[row.vwc.id]?.offset ?? 0) : null;
          const raw = moisturePct(row.vwc.value, row.vwc.unit);
          const temp = index === 0 ? rootZoneSensor(controller.states, view.room, zone.id) : null;
          const tempState = temp ? controller.states[temp] : undefined;
          const tempValue = numeric(tempState);
          const tempC =
            tempValue === null
              ? null
              : String(tempState?.attributes.unit_of_measurement ?? "").includes("F")
                ? ((tempValue - 32) * 5) / 9
                : tempValue;
          const action =
            placementProblem(row.vwc) ? (
              <Button variant="link" size="sm" onClick={onCheckPlacement} data-check-placement={row.vwc.id}>
                Check placement <ArrowRight size={14} aria-hidden="true" />
              </Button>
            ) : row.vwc.health === "stale" || row.vwc.health === "no-reading" ? (
              <span className="muted small">Check cable</span>
            ) : v2 && !blocked && raw !== null && row.vwc.used !== null ? (
              <Button
                variant="outline"
                size="sm"
                aria-expanded={open === row.vwc.id}
                aria-label={`Match handheld: ${zone.name} ${row.side}`}
                onClick={() => onOpen(open === row.vwc.id ? null : row.vwc.id)}
                data-match-handheld={row.vwc.id}
              >
                Match handheld
              </Button>
            ) : rows.length === 1 && row.vwc.health === "stuck" ? (
              <span className="muted small">Only probe here, still used</span>
            ) : null;
          return (
            <Fragment key={row.vwc.id}>
              <tr data-probe={row.vwc.id} data-health={row.vwc.health} className="probe-row">
                {index === 0 && (
                  <td rowSpan={rows.length + (editing ? 1 : 0)} className="probes-zone-value" data-zone-value={`${view.room.id}:${zone.id}`}>
                    <span className="muted">{zone.name}</span>
                    <strong>{pct(zone.vwc.value)}</strong>
                    <SpreadBar values={values} value={zone.vwc.value} label={`${zone.name} probes read raw from ${values.length ? Math.min(...values).toFixed(1) : "—"} to ${values.length ? Math.max(...values).toFixed(1) : "—"}%`} />
                    <span className="small" data-tone={stuck ? "warn" : undefined}>{sub}</span>
                  </td>
                )}
                <td data-label="Health">
                  <Pill dot tone={PROBE_TONE[row.vwc.health]} data-probe-health={row.vwc.health} title={row.vwc.text}>
                    {healthChip(row.vwc, now)}
                  </Pill>
                  {row.vwc.used === false && row.vwc.health !== "not-counted" && (
                    <span className="cell-subtext">left out of zone</span>
                  )}
                  {row.vwc.reason && row.vwc.reason !== "fresh" && (
                    <span className="cell-subtext" data-probe-reason={row.vwc.reason}>
                      Reading: {READING_REASON[row.vwc.reason] ?? row.vwc.reason.replaceAll("_", " ")}
                      {row.vwc.quality ? ` (${row.vwc.quality})` : ""}
                    </span>
                  )}
                </td>
                <td data-label="Probe">
                  <strong title={row.vwc.id}>{row.side}</strong>
                  {row.vwc.primary && (
                    <Pill tone="phase" data-probe-primary>
                      Primary
                    </Pill>
                  )}
                </td>
                <td data-sensor-trend={row.vwc.id} data-label="Last 24 h">
                  {points(row.vwc.id) && (
                    <Sparkline
                      points={recentReadings(points(row.vwc.id)!, PROBE_H, row.vwc.value, now)}
                      width={80}
                      label={`${zone.name} ${row.side} moisture over the last ${PROBE_H} hours`}
                    />
                  )}
                </td>
                <td className="numeric probes-vwc" data-label="VWC" data-tone={row.vwc.health === "out-of-range" ? "bad" : undefined}>
                  {row.vwc.value === null ? "—" : `${row.vwc.value}${row.vwc.unit === "%" ? "%" : ` ${row.vwc.unit}`}`}
                </td>
                <td className="numeric" data-label={temp ? "EC · Temp" : "EC"} data-probe-ec={row.ec?.id}>
                  {row.ec ? <EcCell probe={row.ec} now={now} /> : "—"}
                  {tempC !== null && ` · ${formatTemp(tempC, Math.min(1, digits(tempState?.state)))}`}
                </td>
                <td className="numeric" data-label="Offset" data-offset={row.vwc.id}>
                  {offset === null ? "—" : signedPoints(offset)}
                </td>
                <td data-label="">{action}</td>
              </tr>
              {editing === row && (
                <tr className="probe-offset-row">
                  <td colSpan={7}>
                    <MatchHandheld
                      controller={controller}
                      roomId={view.room.id}
                      room={view.room.name}
                      zone={zone.name}
                      row={row}
                      raw={raw!}
                      current={offset}
                      onClose={() => onOpen(null)}
                      onChanged={onChanged}
                      onCheckPlacement={onCheckPlacement}
                    />
                  </td>
                </tr>
              )}
            </Fragment>
          );
        });
      })}
    </tbody>
  );
}

/** A pore EC probe's reading in the display unit, its trouble said beside it. */
function EcCell({ probe, now }: { probe: Probe; now: number }) {
  const value = probe.value === null ? "—" : formatEc(probe.value, String(probe.value).split(".")[1]?.length ?? 0);
  if (probe.health === "ok") return <>{value}</>;
  return (
    <span className="probes-ec-trouble" title={probe.text} data-probe-health={probe.health}>
      {value} <TriangleAlert size={13} aria-hidden="true" /> {healthChip(probe, now)}
    </span>
  );
}

/** Where the zone's probes sit around the zone's value: the span from lowest to highest, a tick at the
 * value. 10 points either side. */
function SpreadBar({ values, value, label }: { values: number[]; value: number | null; label: string }) {
  if (value === null || !values.length) return null;
  const at = (v: number) => `${Math.max(0, Math.min(100, ((v - value + 10) / 20) * 100))}%`;
  const low = Math.min(...values),
    high = Math.max(...values);
  return (
    <span className="probes-spread" role="img" aria-label={label}>
      <span className="probes-spread-range" style={{ left: at(low), width: `calc(${at(high)} - ${at(low)})` }} />
      <span className="probes-spread-tick" style={{ left: at(value) }} />
    </span>
  );
}

/** Match handheld: the grower's handheld reading at the same spot, the offset it makes (the integration's
 * own rule) and, from the integration's preview, what the zone would read. Review & apply writes exactly
 * that offset; the receipt says what the zone read before and after, from the write's own answer. */
function MatchHandheld({
  controller,
  roomId,
  room,
  zone,
  row,
  raw,
  current,
  onClose,
  onChanged,
  onCheckPlacement,
}: {
  controller: Controller;
  roomId: string;
  room: string;
  zone: string;
  row: ProbeRow;
  raw: number;
  /** The probe's stored offset; null when it is not known. */
  current: number | null;
  onClose: () => void;
  onChanged: () => void;
  onCheckPlacement: () => void;
}) {
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<{ text: string; outcome: V2Outcome<OffsetAnswer> } | null>(null);
  const [tick, setTick] = useState(0);
  const handheld = text.trim() === "" ? null : Number(text.replace(",", "."));
  const valid = handheld !== null && Number.isFinite(handheld);
  const offset = valid ? handheldOffset(raw, handheld) : null;
  useEffect(() => {
    if (!valid) return;
    let current = true;
    const timer = setTimeout(() => {
      void previewOffset(controller, roomId, row.vwc.id, handheld).then((outcome) => {
        if (current) setPreview({ text, outcome });
      });
    }, 250);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [text, tick, roomId, row.vwc.id, raw]);
  const shown = preview && preview.text === text && valid ? preview.outcome : null;
  const answer = shown?.kind === "ok" ? shown.data : null;
  const name = `${zone} ${row.side}`;
  const rows: ReviewRow[] = answer
    ? [
        answer.fused_before !== null && answer.fused_after !== null
          ? { id: row.vwc.id, label: `${room} ${zone} value`, before: pct(answer.fused_before), after: pct(answer.fused_after) }
          : {
              id: row.vwc.id,
              label: `${name} offset`,
              before: current === null ? "—" : signedPoints(current),
              after: signedPoints(answer.offset),
            },
      ]
    : [];
  const checks =
    !valid && text.trim()
      ? [{ ok: false, text: "Enter the handheld reading as a number from 0 to 100." }]
      : shown?.kind === "error"
        ? [{ ok: false, text: shown.message }]
        : [];
  return (
    <div className="probe-offset" data-offset-editor={row.vwc.id} aria-label={`Match ${name} to a handheld reading`} role="group">
      <div className="probe-offset-inputs">
        <label>
          <span>Handheld reading, same spot</span>
          <span className="probe-offset-field">
            <Input
              inputMode="decimal"
              value={text}
              autoFocus
              onChange={(event) => setText(event.target.value)}
              aria-label="Handheld reading, same spot, %"
            />
            %
          </span>
        </label>
        <div className="probe-offset-result" aria-live="polite">
          <span className="muted">Probe reads {pct(raw)}</span>
          <strong data-offset-preview>{offset === null ? "—" : signedPoints(offset)}</strong>
          <span className="muted small">offset, VWC points</span>
        </div>
        <div className="probe-offset-links">
          <Button variant="link" size="sm" onClick={onCheckPlacement} data-check-placement-editor>
            Reads oddly? Check placement <ArrowRight size={14} aria-hidden="true" />
          </Button>
        </div>
      </div>
      {shown?.kind === "missing" ? (
        <NeedsIntegration feature="Matching a probe to a handheld meter" compact />
      ) : (
        <ReviewApply
          layout="bar"
          rows={rows}
          checks={checks}
          summary={rows.length ? undefined : valid ? "Working out the zone value…" : "Type the handheld reading"}
          applyLabel={answer ? `Apply ${signedPoints(answer.offset)} offset to ${name}` : undefined}
          discardLabel="Cancel"
          onDiscard={onClose}
          consequence="The zone value updates once the controller holds the offset. Fusion re-baselines, so no step alert fires."
          timeZone={controller.timeZone}
          onReload={() => {
            onChanged();
            setTick((n) => n + 1);
          }}
          apply={async () => {
            const receipt = await applyOffset(controller, {
              roomId,
              entityId: row.vwc.id,
              offset: answer!.offset,
              revision: answer!.revision,
              room,
              zone,
              probe: name,
              before: current,
            });
            if ("ok" in receipt && receipt.ok) setText("");
            onChanged();
            return receipt;
          }}
          undo={async (receipt) => {
            if (!receipt.eventIds.length) throw new Error("Undo not available here: put the offset back from History › Changes.");
            await revertEvents(controller, receipt.eventIds);
            onChanged();
          }}
        />
      )}
      <p className="probe-offset-foot muted small">
        Raw value kept · logged in History › Changes
        {!text && (
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        )}
      </p>
    </div>
  );
}

/** The selected room's substrate curve: what turns a probe's raw reading into VWC. Generic curves stay
 * off until they are signed off, so this says what the room's probes do and why a curve does not apply. */
function SubstrateCurve({
  room,
  probes,
  missing,
  offsets,
}: {
  room: RoomView;
  probes: Probe[];
  missing: boolean;
  offsets: Record<string, ProbeOffset> | null;
}) {
  const moisture = probes.filter((probe) => probe.kind === "vwc");
  const reasons = [...new Set(moisture.map((probe) => curveDisabledReason({ unit: probe.unit })))];
  const curves = [...new Set(moisture.map((probe) => offsets?.[probe.id]?.curve).filter(Boolean))];
  return (
    <section className="panel probe-curve" aria-labelledby="probe-curve-title" data-substrate-curve>
      <h2 id="probe-curve-title">Substrate curve · {room.room.name}</h2>
      <p className="muted">
        Turns a probe’s raw reading into VWC.
        {curves.length > 0 &&
          ` Applies to all ${moisture.length} ${room.room.name} moisture ${moisture.length === 1 ? "probe" : "probes"}.`}
      </p>
      {missing ? (
        <NeedsIntegration feature="Probe curves" compact />
      ) : (
        <>
          <p data-curve-in-use>
            <strong>In use:</strong> {offsets === null ? "—" : curves.length ? curves.join(", ").replaceAll("_", " ") : "none"}
          </p>
          {reasons.map((reason) => (
            <p className="probe-curve-reason" key={reason ?? "none"} data-curve-reason>
              {reason ?? "Substrate curves stay off until they are signed off for this grow. Match a handheld meter instead."}
            </p>
          ))}
        </>
      )}
    </section>
  );
}

/** A slab from the side: the dripper's wet cone, and a probe 5–8 cm away, prongs fully in. */
function PlacementPicture() {
  return (
    <svg className="probe-placement-picture" viewBox="0 0 320 130" role="img" aria-label="A probe pushed straight down 5 to 8 cm from the dripper, out of the wet cone">
      <rect x="4" y="52" width="312" height="62" rx="4" className="slab" />
      <path d="M92 52 Q92 92 112 98 Q132 92 132 52 Z" className="cone" />
      <rect x="96" y="24" width="32" height="28" rx="2" className="cube" />
      <line x1="112" y1="10" x2="112" y2="24" className="dripper" />
      <text x="70" y="108" className="label">not in the wet cone</text>
      <rect x="208" y="30" width="12" height="20" rx="2" className="probe-head" />
      <line x1="211" y1="50" x2="211" y2="96" className="prong" />
      <line x1="217" y1="50" x2="217" y2="96" className="prong" />
      <text x="230" y="80" className="label accent">prongs fully in</text>
      <line x1="132" y1="122" x2="211" y2="122" className="measure" />
      <text x="150" y="119" className="label accent">5–8 cm</text>
    </svg>
  );
}

/** Which of each zone's probes count towards its reading, and which one is primary: the controller
 * says when the primary goes offline, and the zone reads on from the others. Saved with the room's
 * setup, alone, so it needs nothing switched off. Only where the integration names the probes. */
function ProbePicker({ controller, probes }: { controller: Controller; probes: Probe[] }) {
  const { room } = controller;
  const saved = probeChoices(probes);
  const [draft, setDraft] = useState<Record<string, ProbeChoice> | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const choices = draft ?? saved;
  const groups = room.zones.flatMap((zone) =>
    (["vwc", "ec"] as const)
      .filter((kind) => choices[`${zone.id}:${kind}`])
      .map((kind) => ({
        zone,
        kind,
        key: `${zone.id}:${kind}`,
        listed: probes.filter((probe) => probe.zone === zone.id && probe.kind === kind),
      })),
  );
  if (!groups.length) return null;
  const change = (key: string, next: ProbeChoice) => {
    setDraft({ ...choices, [key]: next });
    setMessage("");
  };
  async function save() {
    setBusy(true);
    setMessage("");
    try {
      const setup = await controller.operator<SetupDocument>("setup_read");
      const target = setup.rooms.find((item) => item.prefix === room.room.prefix && item.active);
      if (!target) throw new Error("This room's setup could not be found.");
      await controller.operator("setup_save", probeChoicePayload(target, choices));
      await controller.refresh();
      setDraft(null);
      setMessage("Saved. Each zone's reading uses the probes that count.");
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel" aria-labelledby="probe-picker-title">
      <div className="panel-heading">
        <div>
          <h2 id="probe-picker-title">Probes that count</h2>
          <p>
            Each zone’s reading is made from the probes that count. If its primary goes offline you
            are told once, and the zone reads on from the others.
          </p>
        </div>
      </div>
      <div className="probe-picker">
        {groups.map(({ zone, kind, key, listed }) => {
          const choice = choices[key];
          const counted = listed.filter((probe) => !choice.unused.includes(probe.id));
          const what = `${zone.name} ${kind === "vwc" ? "moisture" : "pore EC"}`;
          return (
            <fieldset key={key} data-probe-choice={key}>
              <legend>{what}</legend>
              {listed.map((probe) => {
                const counts = !choice.unused.includes(probe.id);
                return (
                  <div className="probe-choice" key={probe.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={counts}
                        disabled={busy || (counts && counted.length === 1)}
                        onChange={(event) =>
                          change(key, {
                            unused: event.target.checked
                              ? choice.unused.filter((id) => id !== probe.id)
                              : [...choice.unused, probe.id],
                            primary:
                              !event.target.checked && choice.primary === probe.id
                                ? ""
                                : choice.primary,
                          })
                        }
                      />
                      {probe.name}
                    </label>
                    <label className="muted small">
                      <input
                        type="radio"
                        name={`primary-${key}`}
                        checked={choice.primary === probe.id}
                        disabled={busy || !counts}
                        aria-label={`${probe.name} is the primary ${what} probe`}
                        onChange={() => change(key, { ...choice, primary: probe.id })}
                      />
                      Primary
                    </label>
                  </div>
                );
              })}
              <label className="muted small">
                <input
                  type="radio"
                  name={`primary-${key}`}
                  checked={!choice.primary}
                  disabled={busy}
                  onChange={() => change(key, { ...choice, primary: "" })}
                />
                No primary
              </label>
            </fieldset>
          );
        })}
      </div>
      <div className="probe-picker-actions">
        <Button size="sm" disabled={busy || !draft} onClick={save}>
          {busy ? "Saving…" : "Save"}
        </Button>
        {draft && (
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => setDraft(null)}>
            Cancel
          </Button>
        )}
        {message && (
          <span className="muted small" role="status">
            {message}
          </span>
        )}
      </div>
    </section>
  );
}

/** How the room is wired, from its setup: the pump, the main line, each zone's valve and probes,
 * and the feed-water probes. Read only. */
function RoomMap({
  controller,
  navigate,
  onDirtyChange,
}: {
  controller: Controller;
  navigate: (page: Page) => void;
  onDirtyChange?: (dirty: boolean) => void;
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
      <summary>Room map</summary>
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
        All sensors of this room ({reporting} of {sensors.length} reporting)
      </summary>
      {open && (
        <>
          <div className="toolbar">
            <div className="search-field">
              <Search size={17} />
              <Input
                aria-label="Search sensors"
                placeholder="Name or entity ID"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <select
              aria-label="Sensor status filter"
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
                title="No sensors found"
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
