import { useEffect, useState, type ReactNode } from "react";
import { Heading } from "@/components/dashboard";
import { NeedsIntegration } from "@/components/needs-integration";
import { UpgradeReports } from "@/components/upgrade-report";
import { HealthRing } from "@/components/primitives/ring";
import { Button } from "@/components/ui/button";
import { duration } from "@/lib/day-timeline";
import { runningVersions } from "@/lib/model";
import { openAlerts, type OpenAlert } from "@/lib/open-alerts";
import { callV2, useParity } from "@/lib/parity-api";
import type { RoomHeartbeat, StatusEntity, SystemStatus as Status } from "@/lib/parity-types";
import {
  CARD,
  KIND_LABEL,
  ageTone,
  healthSentence,
  heartbeatHour,
  percent,
  placeAlert,
  readbackText,
  rowLabel,
  rowWords,
  seenText,
  statusFromEntities,
} from "@/lib/system-status";
import { clock } from "@/lib/time";
import type { Controller } from "@/lib/types";
import type { PageProps } from "./placeholder";
import "./system.css";

const POLL_MS = 30_000;
const GROUPS = [...new Set(Object.values(KIND_LABEL))];
const TANK_GROUP = KIND_LABEL.tank;
const TONE_ORDER = { bad: 0, warn: 1, ok: 2 } as const;
const instant = (text: string | null | undefined) => {
  const ms = text ? Date.parse(text) : NaN;
  return Number.isFinite(ms) ? ms : null;
};

type Row = StatusEntity & { roomId: string; label: string };
type Ack = { busy: boolean; error: string | null };

/** Settings › System status (mockup 21): the health ring and its sentence, each room's Upgrade
 * report after an update (CS-616), Software, Heartbeat and every mapped device, each open alert on
 * the device it is about. */
export function SystemStatus({ controller }: PageProps) {
  const v2 = useParity<Status>(controller, "system_status_get", {}, []);
  const { reload } = v2;
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  // The last answer read, kept on screen when a later poll fails (and that failure said).
  const [lastGood, setLastGood] = useState<Status | null>(null);
  const [acked, setAcked] = useState<Set<string>>(() => new Set());
  const [acks, setAcks] = useState<Record<string, Ack>>({});
  const [said, setSaid] = useState("");
  // An integration without system_status_get has nothing to poll: the page follows the entities.
  const missing = v2.state === "missing";
  useEffect(() => {
    if (missing) return;
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [reload, missing]);
  useEffect(() => {
    if (!v2.data) return;
    setCheckedAt(Date.now());
    setLastGood(v2.data);
  }, [v2.data]);

  const now = Date.now();
  const entityOnly = missing;
  const status: Status | null = entityOnly
    ? statusFromEntities(controller.states, controller.rooms, now)
    : (v2.data ?? lastGood);
  const checked = entityOnly ? controller.lastUpdated : checkedAt;
  const roomName = (id: string) => controller.rooms.find((room) => room.id === id)?.name ?? id;
  const alerts = openAlerts(controller).filter((alert) => !alert.eventId || !acked.has(alert.eventId));

  async function acknowledge(alert: OpenAlert) {
    const id = alert.eventId!;
    setAcks((all) => ({ ...all, [id]: { busy: true, error: null } }));
    const outcome = await callV2<{ event_id: string }>(controller, "alert_ack", {
      room_id: alert.roomId,
      alert_event_id: id,
    });
    if (outcome.kind === "ok") {
      setAcked((all) => new Set(all).add(id));
      const at = instant(outcome.readback.at);
      setSaid(
        `${alert.code ?? "Alert"} acknowledged.${
          outcome.readback.status === "verified" && at !== null
            ? ` Written and read back ${clock(at, controller.timeZone)}.`
            : ""
        }`,
      );
      setAcks(({ [id]: _done, ...rest }) => rest);
    } else
      setAcks((all) => ({
        ...all,
        [id]: {
          busy: false,
          error:
            outcome.kind === "missing"
              ? "This integration cannot acknowledge alerts yet. Update it to 3.18."
              : outcome.message,
        },
      }));
  }

  if (!status)
    return (
      <>
        <Heading title="System status" action={<Capabilities />} />
        <section className="panel system-loading" role="status">
          {v2.state === "error" ? (
            <p>
              System status could not be read: {v2.error}{" "}
              <Button size="sm" variant="outline" onClick={reload}>
                Read again
              </Button>
            </p>
          ) : (
            <p>Reading system status…</p>
          )}
        </section>
      </>
    );

  const rows: Row[] = status.rooms.flatMap((room) =>
    room.entities.map((entity) => ({ ...entity, roomId: room.room_id, label: rowLabel(entity, roomName(room.room_id)) })),
  );
  const groups = GROUPS.map((label) => ({
    label,
    rows: rows
      .filter((row) => KIND_LABEL[row.kind] === label)
      .map((row, index) => ({ row, index, tone: ageTone(row, now) }))
      .sort((a, b) => TONE_ORDER[a.tone] - TONE_ORDER[b.tone] || a.index - b.index),
  })).filter((group) => group.rows.length);

  // Each alert on its row or card; the rest on their room's header.
  const placed = new Map<string, OpenAlert[]>();
  const onRoom = new Map<string, OpenAlert[]>();
  for (const alert of alerts) {
    let at = placeAlert(
      alert,
      rows.filter((row) => row.roomId === alert.roomId),
    );
    if (at === CARD.tank && !groups.some((group) => group.label === TANK_GROUP)) at = null;
    const list = at === null ? onRoom : placed;
    const key = at ?? alert.roomId;
    list.set(key, [...(list.get(key) ?? []), alert]);
  }
  const cards = (key: string) =>
    (placed.get(key) ?? []).map((alert) => (
      <AlertCard key={alert.eventId ?? `${alert.roomId}:${alert.code}:${alert.zone}`} alert={alert} ack={alert.eventId ? acks[alert.eventId] : undefined} onAck={acknowledge} />
    ));

  return (
    <>
      <Heading title="System status" action={<Capabilities />} />
      <section className="panel system-health" aria-label="System health">
        <div className="system-health-line">
          {status.pct_online !== null && <HealthRing pct={status.pct_online} label="System health" />}
          <p>
            <strong>{healthSentence(status, alerts)}</strong>
            {checked !== null && (
              <>
                {" "}
                <span className="system-checked">Checked {clock(checked, controller.timeZone)}</span>
              </>
            )}
          </p>
        </div>
        {v2.state === "error" && (
          <p className="system-poll-error" role="alert">
            Could not read system status again: {v2.error}. Showing what was read at the Checked time.{" "}
            <Button size="sm" variant="outline" onClick={reload}>
              Read again
            </Button>
          </p>
        )}
        {[...onRoom].map(([roomId, list]) => (
          <div key={roomId} className="system-room-alerts" data-room-alerts={roomId}>
            <h2>{roomName(roomId)}</h2>
            {list.map((alert) => (
              <AlertCard key={alert.eventId ?? `${alert.code}:${alert.zone}:${alert.title}`} alert={alert} ack={alert.eventId ? acks[alert.eventId] : undefined} onAck={acknowledge} />
            ))}
          </div>
        ))}
        <p className="system-said" role="status">
          {said}
        </p>
      </section>
      <UpgradeReports controller={controller} />

      <div className="system-grid">
        <div className="system-side">
          <Software controller={controller} status={status}>
            {cards(CARD.software)}
          </Software>
          <Heartbeats
            rooms={status.rooms.map((room) => ({ name: roomName(room.room_id), beat: room.heartbeat }))}
            entityOnly={entityOnly}
            now={now}
          />
        </div>
        <section className="panel system-devices" aria-labelledby="system-devices-title">
          <header className="system-card-head">
            <h2 id="system-devices-title">Every mapped device</h2>
            <p>Last seen, and the share of the last 7 days it was online.</p>
            {entityOnly && <NeedsIntegration feature="Uptime over 7 days" compact />}
          </header>
          <div className="system-groups">
            {groups.map((group) => {
              const online = group.rows.filter(({ row }) => row.ok).length;
              const known = group.rows.flatMap(({ row }) => (row.uptime_7d_pct === null ? [] : [row.uptime_7d_pct]));
              const mean = known.length ? known.reduce((sum, v) => sum + v, 0) / known.length : null;
              return (
                <section key={group.label} className="system-group" aria-label={group.label} data-group={group.label}>
                  <h3>
                    <span>{group.label}</span>
                    <span className="system-group-sum" data-tone={online < group.rows.length ? "warn" : undefined}>
                      {online} of {group.rows.length} online
                      {mean !== null && ` · ${percent(mean)}% over 7 days`}
                    </span>
                  </h3>
                  {group.label === TANK_GROUP && cards(CARD.tank)}
                  <ul>
                    {group.rows.map(({ row, tone }) => (
                      <li key={row.entity_id}>
                        <DeviceRow row={row} tone={tone} controller={controller} now={now} />
                        {cards(row.entity_id)}
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        </section>
      </div>
    </>
  );
}

function Capabilities() {
  return (
    <a className="system-capabilities" href="#/settings/features">
      Capabilities ›
    </a>
  );
}

function AlertCard({ alert, ack, onAck }: { alert: OpenAlert; ack: Ack | undefined; onAck: (alert: OpenAlert) => void }) {
  return (
    <div className="system-alert" role="group" aria-label={`${alert.code ?? "Alert"}: ${alert.title}`} data-alert={alert.code ?? ""}>
      {alert.code && <strong>{alert.code}</strong>}
      <span className="system-alert-title">{alert.title}</span>
      <span className="system-alert-actions">
        <a href={alert.code ? `#/help?code=${alert.code}` : "#/help"}>What to do →</a>
        {alert.eventId && (
          <Button size="xs" variant="outline" disabled={ack?.busy} onClick={() => onAck(alert)}>
            {ack?.busy ? "Acknowledging…" : "Acknowledge"}
          </Button>
        )}
      </span>
      {ack?.error && (
        <span className="system-alert-error" role="alert">
          {ack.error}
        </span>
      )}
    </div>
  );
}

function DeviceRow({ row, tone, controller, now }: { row: Row; tone: "ok" | "warn" | "bad"; controller: Controller; now: number }) {
  const pct = row.uptime_7d_pct;
  return (
    <div className="system-row" data-entity={row.entity_id} data-tone={tone}>
      <span className="system-dot" aria-hidden="true" />
      <span className="system-row-name">
        {row.label}
        <span className="sr-only">, {rowWords(row.kind, row.ok, tone)}</span>
        <span className="system-row-entity">{row.entity_id}</span>
      </span>
      <span className="system-row-seen">{seenText(row, controller.states[row.entity_id]?.state, controller.timeZone, now)}</span>
      <span className="system-bar" aria-hidden="true" data-low={pct !== null && pct < 95 ? "" : undefined}>
        {pct !== null && <span style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />}
      </span>
      <span className="system-row-pct">{pct === null ? "—" : `${percent(pct)}%`}</span>
    </div>
  );
}

function Software({ controller, status, children }: { controller: Controller; status: Status; children: ReactNode }) {
  const integration = runningVersions(controller.states, controller.room.room).integration;
  const addon = status.addon_version;
  const ai = status.ai;
  const items: { name: string; version: string | null; note: string; tone: "ok" | "warn" | "bad" }[] = [
    {
      name: "Controller app (f2_control)",
      version: addon,
      note: { running: "Running", stale: "Not reporting", absent: "No heartbeat" }[status.controller],
      tone: status.controller === "running" ? "ok" : "bad",
    },
    {
      name: "Integration (crop_steering)",
      version: integration,
      note:
        !integration || !addon
          ? "Version not reported"
          : integration === addon
            ? "Matches the controller"
            : `The controller runs ${addon}`,
      tone: integration && addon && integration === addon ? "ok" : "warn",
    },
    {
      name: "Dashboard cards",
      version: null,
      note: status.card_version ? `Loaded as ?v=${status.card_version}` : "Card version not reported",
      tone: status.card_version ? "ok" : "warn",
    },
    { name: "Home Assistant", version: status.ha_version, note: "", tone: "ok" },
    {
      name: "AI assistant",
      version: ai?.model ?? null,
      note: !ai
        ? "Not reporting"
        : ai.calls_today === null
          ? "Calls today not reported"
          : `${ai.calls_today}${ai.daily_budget ? ` of ${ai.daily_budget}` : ""} calls today`,
      tone: ai ? "ok" : "warn",
    },
  ];
  return (
    <section className="panel system-card" aria-labelledby="system-software-title">
      <header className="system-card-head">
        <h2 id="system-software-title">Software</h2>
      </header>
      <dl className="system-software">
        {items.map((item) => (
          <div key={item.name}>
            <dt>{item.name}</dt>
            <dd className="system-version">{item.version ?? (item.name === "Dashboard cards" ? "" : "—")}</dd>
            {item.note && (
              <dd className="system-note" data-tone={item.tone}>
                {item.note}
              </dd>
            )}
          </div>
        ))}
      </dl>
      {children}
    </section>
  );
}

function Heartbeats({ rooms, entityOnly, now }: { rooms: { name: string; beat: RoomHeartbeat }[]; entityOnly: boolean; now: number }) {
  return (
    <section className="panel system-card" aria-labelledby="system-heartbeat-title">
      <header className="system-card-head">
        <h2 id="system-heartbeat-title">Heartbeat</h2>
        {entityOnly && <NeedsIntegration feature="Heartbeat history" compact />}
      </header>
      {rooms.map(({ name, beat }) => {
        const { strip, missed, received, spanMin } = heartbeatHour(beat.beats, beat.interval_s, now);
        const span = spanMin === null ? "the last hour" : `the last ${spanMin} min`;
        const recorded = beat.beats.length > 0;
        const last = instant(beat.last_beat);
        const readback = [...beat.beats].reverse().find((b) => b.readback_ms !== null)?.readback_ms ?? null;
        return (
          <div key={name} className="system-beat" data-heartbeat={name}>
            <div className="system-beat-head">
              <span>{name} controller</span>
              <span data-tone={beat.controller === "running" ? "ok" : "bad"}>
                {last === null
                  ? "no heartbeat"
                  : `beat ${duration(Math.max(0, now - last))} ago${beat.controller === "running" ? "" : ", not reporting"}`}
              </span>
            </div>
            {entityOnly ? (
              <p className="system-beat-note">—</p>
            ) : (
              <>
                <div
                  className="system-strip"
                  role="img"
                  aria-label={`${received} beats in ${span}, ${missed} missed`}
                >
                  {strip.map((b) => (
                    <span key={b.at} data-missed={b.missed ? "" : undefined} style={{ flexGrow: b.weight }} />
                  ))}
                </div>
                <p className="system-beat-note">
                  Every {beat.interval_s} s ·{" "}
                  {recorded ? `${missed} missed in ${span}` : "no beats recorded since Home Assistant started"}
                  {readback !== null && ` · read-back ${readbackText(readback)}`}
                </p>
              </>
            )}
          </div>
        );
      })}
    </section>
  );
}
