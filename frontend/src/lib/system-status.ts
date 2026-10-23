import { buildRoom, descriptor, runningVersions } from "./model";
import type { OpenAlert } from "./open-alerts";
import type { ControllerState, RoomHeartbeat, StatusEntity, SystemStatus } from "./parity-types";
import { zoneProbes } from "./probes";
import type { EntityState, Room, States } from "./types";

/** Settings › System status (mockup 21): every mapped device, each open alert on the device it is
 * about, the software and the controllers' heartbeats. 3.18 reads system_status_get; an older
 * integration gets the same page built from the entities (`statusFromEntities`). */

/** The display groups over the backend's `kind`. */
export const KIND_LABEL = {
  probe_vwc: "Moisture and EC probes",
  probe_ec: "Moisture and EC probes",
  probe_temp: "Moisture and EC probes",
  valve: "Valves",
  main_line: "Valves",
  pump: "Pumps",
  feed_probe: "Tank and feed sensors",
  tank: "Tank and feed sensors",
  flow_meter: "Pumps",
} as const;

/** The backend's kind order (system_status.py KINDS). */
const KINDS: StatusEntity["kind"][] = [
  "probe_vwc",
  "probe_ec",
  "probe_temp",
  "valve",
  "pump",
  "main_line",
  "feed_probe",
  "tank",
  "flow_meter",
];
const PROBES = new Set(["probe_vwc", "probe_ec", "probe_temp", "feed_probe"]);

/** Where an alert sits that is about no single row. The backend maps no dosing devices, so a
 * dosing alert sits on the tank and feed card, beside the feed sensors. */
export const CARD = { software: "card:software", tank: "card:tank" } as const;

const instant = (text: string | null | undefined) => {
  const ms = text ? Date.parse(text) : NaN;
  return Number.isFinite(ms) ? ms : null;
};

/** A percentage as the page prints it: at most one decimal, never padded. */
export const percent = (value: number) => value.toLocaleString("en", { maximumFractionDigits: 1 });

const CONTROLLER_WORDS: Record<ControllerState, string> = {
  running: "controller running",
  stale: "controller not reporting",
  absent: "no controller heartbeat",
};

/** "System health 94 %: 34 of 35 devices online, controller running, 3 open alerts, each shown below
 * where it happens." */
export function healthSentence(s: SystemStatus, alerts: OpenAlert[]): string {
  const rows = s.rooms.flatMap((room) => room.entities);
  const online = rows.filter((row) => row.ok).length;
  const health = s.pct_online === null ? "System health not known" : `System health ${percent(s.pct_online)} %`;
  const devices = rows.length ? `${online} of ${rows.length} devices online` : "no mapped devices";
  const open =
    alerts.length === 0
      ? "no open alerts"
      : alerts.length === 1
        ? "1 open alert, shown below where it happens"
        : `${alerts.length} open alerts, each shown below where it happens`;
  return `${health}: ${devices}, ${CONTROLLER_WORDS[s.controller]}, ${open}.`;
}

type PlaceRow = { entity_id: string; kind: string; zone: number | null; ok?: boolean };

/** The row or card an alert sits on, or null for its room's header. The alert's own entity wins
 * where it names a row here; otherwise its code family places it: CS-1xx on the zone's probe (the
 * silent one first, an EC code on an EC probe), CS-3xx on the zone's valve or on the pump or main
 * line, the AI assistant and controller codes on Software, the tank, stock and dosing codes on
 * the tank and feed card. `rows` are the alert's room's. */
export function placeAlert(alert: OpenAlert, rows: PlaceRow[]): string | null {
  if (alert.entityId && rows.some((row) => row.entity_id === alert.entityId)) return alert.entityId;
  const code = /^CS-(\d)(\d\d)$/.exec(alert.code ?? "");
  if (!code) return null;
  const family = code[1],
    n = Number(code[1] + code[2]);
  const pick = (match: (row: PlaceRow) => boolean) => {
    const found = rows.filter(match);
    return (found.find((row) => row.ok === false) ?? found[0])?.entity_id ?? null;
  };
  const inZone = (row: PlaceRow) => alert.zone !== null && row.zone === alert.zone;
  if (family === "1") {
    const kinds = n === 104 ? ["probe_ec"] : ["probe_vwc", "probe_ec", "probe_temp"];
    return pick((row) => inZone(row) && kinds.includes(row.kind));
  }
  if (family === "3") {
    if (n === 302 || n === 317) return pick((row) => row.kind === "pump");
    if (n === 303) return pick((row) => row.kind === "main_line");
    return pick((row) => inZone(row) && row.kind === "valve");
  }
  if (family === "7" || n === 602 || n === 609 || n === 610) return CARD.software;
  if (family === "8" || family === "9" || n === 608) return CARD.tank;
  return null;
}

const PROBE_WARN_MS = 120_000;
const PROBE_BAD_MS = 20 * 60_000;

/** A row's dot: a probe by how long ago it reported (orange after 120 s, red after 20 min, red when
 * the backend calls it silent); a valve, pump or other actuator only by whether the backend says it
 * is ok, since it reports when it switches. */
export function ageTone(row: { kind: string; last_seen: string | null; ok: boolean }, now: number): "ok" | "warn" | "bad" {
  if (!row.ok) return "bad";
  if (!PROBES.has(row.kind)) return "ok";
  const seen = instant(row.last_seen);
  if (seen === null) return "bad";
  const age = now - seen;
  return age > PROBE_BAD_MS ? "bad" : age > PROBE_WARN_MS ? "warn" : "ok";
}

// ------------------------------------------------------------------ older integration
const OFF = ["unknown", "unavailable"];
const DEAD = ["unavailable", "unknown", "none", ""];
const PROBE_LIMIT_MS = 900_000; // the backend's limit for a probe whose report rhythm is not known
const STALE_MS = 10 * 60_000;
const RANK: Record<ControllerState, number> = { absent: 0, stale: 1, running: 2 };

function entityRow(
  states: States,
  kind: StatusEntity["kind"],
  entity_id: string,
  zone: number | null,
  now: number,
): StatusEntity {
  const state: (EntityState & { last_reported?: string }) | undefined = states[entity_id];
  const seen = state?.last_reported ?? state?.last_updated ?? null;
  const seenMs = instant(seen);
  const ok =
    !!state &&
    !OFF.includes(state.state) &&
    (!PROBES.has(kind) || (seenMs !== null && now - seenMs <= PROBE_LIMIT_MS));
  return {
    entity_id,
    kind,
    zone,
    name: String(
      state?.attributes.friendly_name ??
        (kind === "valve" && zone !== null ? `Zone ${zone} valve` : kind === "pump" ? "Pump" : kind === "main_line" ? "Main line" : entity_id),
    ),
    last_seen: seen,
    last_change: state?.last_changed ?? null,
    ok,
    uptime_7d_pct: null,
  };
}

function heartbeat(states: States, room: Room, now: number): RoomHeartbeat {
  const state = states[`sensor.crop_steering_${room.prefix}ai_heartbeat`];
  const at = instant(state?.last_updated);
  const age = at === null ? null : (now - at) / 1000;
  return {
    last_beat: at === null ? null : new Date(at).toISOString(),
    age_s: age,
    controller: !state
      ? "absent"
      : DEAD.includes(state.state.toLowerCase()) || age === null || age * 1000 > STALE_MS
        ? "stale"
        : "running",
    beats: [],
    interval_s: 60,
  };
}

const pct = (rows: StatusEntity[]) => (rows.length ? (rows.filter((r) => r.ok).length / rows.length) * 100 : null);

/** system_status_get's answer built from the entities, for an integration older than 3.18: the
 * zones' probes and valves and the room's pump and main line, a probe online while it reported in
 * the last 15 min (the backend's limit until it knows a probe's rhythm), the rest while available.
 * No uptime, no heartbeat history, no card or Home Assistant version. */
export function statusFromEntities(states: States, rooms: Room[], now: number): SystemStatus {
  let best: { rank: number; room: Room | null } = { rank: -1, room: null };
  let ai: SystemStatus["ai"] = null;
  const out = rooms.map((room) => {
    const view = buildRoom(states, room);
    const wanted: [StatusEntity["kind"], string, number | null][] = [];
    for (const zone of view.zones) {
      for (const probe of zoneProbes(zone, states, now))
        wanted.push([probe.kind === "vwc" ? "probe_vwc" : "probe_ec", probe.id, zone.id]);
      if (zone.valveEntity) wanted.push(["valve", zone.valveEntity, zone.id]);
    }
    const attributes = descriptor(states, room)?.attributes ?? {};
    for (const [kind, key] of [
      ["pump", "pump"],
      ["main_line", "mainline"],
    ] as const)
      if (typeof attributes[key] === "string") wanted.push([kind, attributes[key] as string, null]);
    const seen = new Set<string>();
    const rows = wanted
      .filter(([, id]) => !seen.has(id) && !!seen.add(id))
      .sort((a, b) => KINDS.indexOf(a[0]) - KINDS.indexOf(b[0]))
      .map(([kind, id, zone]) => entityRow(states, kind, id, zone, now));
    const beat = heartbeat(states, room, now);
    if (RANK[beat.controller] > best.rank) best = { rank: RANK[beat.controller], room };
    const jev = states[`sensor.crop_steering_${room.prefix}jev`]?.attributes;
    if (!ai && jev) {
      const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
      const calls = num(jev.calls_today),
        budget = num(jev.daily_budget);
      ai = {
        model: typeof jev.model === "string" ? jev.model : null,
        calls_today: calls,
        daily_budget: budget,
        pct_used: calls !== null && budget ? (calls / budget) * 100 : null,
      };
    }
    return {
      room_id: room.id,
      pct_online: pct(rows),
      alerts_open: null,
      entities: rows,
      groups: KINDS.filter((kind) => rows.some((r) => r.kind === kind)).map((kind) => ({
        kind,
        entities: rows.filter((r) => r.kind === kind),
      })),
      heartbeat: beat,
    };
  });
  return {
    controller: (Object.keys(RANK) as ControllerState[]).find((c) => RANK[c] === best.rank) ?? "absent",
    addon_version: best.room ? runningVersions(states, best.room).controller : null,
    pct_online: pct(out.flatMap((room) => room.entities)),
    ha_version: null,
    ai,
    card_version: null,
    rooms: out,
  };
}
