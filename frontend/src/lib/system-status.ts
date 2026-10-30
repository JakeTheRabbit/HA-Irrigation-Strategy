import { duration } from "./day-timeline";
import { buildRoom, descriptor, runningVersions } from "./model";
import type { OpenAlert } from "./open-alerts";
import type { ControllerState, RoomHeartbeat, StatusBeat, StatusEntity, SystemStatus } from "./parity-types";
import { zoneProbes } from "./probes";
import { clock, dayKey, dayLabel } from "./time";
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

/** "System health 94%: 34 of 35 devices online, controller running, 3 open alerts, each shown below
 * where it happens." */
export function healthSentence(s: SystemStatus, alerts: OpenAlert[]): string {
  const rows = s.rooms.flatMap((room) => room.entities);
  const online = rows.filter((row) => row.ok).length;
  const health = s.pct_online === null ? "System health not known" : `System health ${percent(s.pct_online)}%`;
  const devices = rows.length ? `${online} of ${rows.length} devices online` : "no mapped devices";
  const open =
    alerts.length === 0
      ? "no open alerts"
      : alerts.length === 1
        ? "1 open alert, shown below where it happens"
        : `${alerts.length} open alerts, each shown below where it happens`;
  // The site's controller is the best room's; a room whose controller is not running is said too.
  const beats = s.rooms.flatMap((room) => (room.heartbeat ? [room.heartbeat.controller] : []));
  const down = beats.filter((c) => c !== "running").length;
  const controller =
    s.controller === "running" && down
      ? `controller not reporting in ${down} of ${beats.length} rooms`
      : CONTROLLER_WORDS[s.controller];
  return `${health}: ${devices}, ${controller}, ${open}.`;
}

const NOUN: Record<StatusEntity["kind"], string> = {
  probe_vwc: "moisture probe",
  probe_ec: "EC probe",
  probe_temp: "root-zone temperature probe",
  valve: "valve",
  pump: "pump",
  main_line: "main line",
  feed_probe: "feed sensor",
  tank: "tank sensor",
  flow_meter: "flow meter",
};

/** A row's label: the room's name, then the device's. The backend's name falls back to the entity
 * id, which is not a name: the row then says what the device is. */
export function rowLabel(row: Pick<StatusEntity, "entity_id" | "name" | "kind" | "zone">, room: string): string {
  const name =
    row.name && row.name !== row.entity_id
      ? row.name
      : `${row.zone !== null ? `Zone ${row.zone} ` : ""}${NOUN[row.kind] ?? "device"}`;
  return name.startsWith(room) ? name : `${room} ${name}`;
}

/** What a screen reader hears after a row's name: the backend's ok decides online or not. */
export function rowWords(kind: string, ok: boolean, tone: "ok" | "warn" | "bad"): string {
  if (!ok) return PROBES.has(kind) ? "silent" : "not available";
  return tone === "warn" ? "online, last report over 2 min ago" : "online";
}

/** The last hour of a room's heartbeat. The backend puts ONE missed marker per gap, carrying the
 * gap (gap_s): the beats it stands for are the gap's expected beats, last + k x interval, of which
 * only those inside the hour count. The backend adds a marker only when the next beat arrives, so a
 * controller silent since its last beat gets its trailing gap here, once over 2 x interval: each
 * expected beat more than one interval overdue. `weight` is how many beats a strip bar stands for.
 * The record is in memory: `spanMin` is the minutes it covers when it starts inside the hour (after
 * a Home Assistant restart), else null. */
export function heartbeatHour(beats: StatusBeat[], interval_s: number, now: number) {
  const from = now - 3_600_000;
  const strip: { at: string; missed: boolean; weight: number }[] = [];
  let missed = 0,
    received = 0;
  for (const beat of beats) {
    const at = instant(beat.at);
    if (at === null) continue;
    if (!beat.missed) {
      if (at >= from) {
        received++;
        strip.push({ at: beat.at, missed: false, weight: 1 });
      }
      continue;
    }
    const n = beat.gap_s ? Math.max(1, Math.round(beat.gap_s / interval_s) - 1) : 1;
    const last = at - interval_s * 1000; // the marker sits one interval after the last beat
    let weight = 0;
    for (let k = 1; k <= n; k++) if (last + k * interval_s * 1000 >= from) weight++;
    if (weight) {
      missed += weight;
      strip.push({ at: beat.at, missed: true, weight });
    }
  }
  const step = interval_s * 1000;
  const lastBeat = beats.at(-1);
  const last = lastBeat && !lastBeat.missed ? instant(lastBeat.at) : null;
  if (last !== null && now - last > 2 * step) {
    let weight = 0;
    for (let k = 1; last + (k + 1) * step <= now; k++) if (last + k * step >= from) weight++;
    if (weight) {
      missed += weight;
      strip.push({ at: new Date(last + step).toISOString(), missed: true, weight });
    }
  }
  const head = beats[0] ? instant(beats[0].at) : null;
  const start = head === null ? now : beats[0].missed ? head - step : head;
  const spanMin = start > from ? Math.round((now - start) / 60_000) : null;
  return { strip, missed, received, spanMin };
}

type PlaceRow = { entity_id: string; kind: string; zone: number | null; ok?: boolean };

/** The row or card an alert sits on, or null for its room's header. The alert's own entity wins
 * where it names a row here; otherwise its code family places it: CS-1xx on the zone's probe (the
 * silent one first, an EC code on an EC probe), CS-3xx on the zone's valve or on the pump or main
 * line, a zone's CS-7xx water or probe code on its valve or probe, the AI service and controller
 * codes on Software, lights-dimmed codes on the room header, the tank, stock and dosing codes on
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
  const probe = (kinds = ["probe_vwc", "probe_ec", "probe_temp"]) => pick((row) => inZone(row) && kinds.includes(row.kind));
  const valve = () => pick((row) => inZone(row) && row.kind === "valve");
  // Flat and out-of-range moisture on a moisture probe, EC out of range on an EC probe.
  if (family === "1")
    return probe(n === 101 || n === 103 ? ["probe_vwc"] : n === 104 ? ["probe_ec"] : undefined);
  if (family === "3") {
    if (n === 302 || n === 317) return pick((row) => row.kind === "pump");
    if (n === 303) return pick((row) => row.kind === "main_line");
    return valve();
  }
  // The AI service and the controller app on Software; a zone's water or probe on that zone's row.
  if ([602, 609, 610, 706, 708, 709].includes(n)) return CARD.software;
  if (n === 701 || n === 702 || n === 710) return valve();
  if (n === 703 || n === 704 || n === 705) return probe();
  if (n === 810 || n === 811) return null; // lights dimmed: the room
  if (family === "8" || family === "9" || n === 608) return CARD.tank;
  return null;
}

const PROBE_WARN_MS = 120_000;
const ACTUATORS = new Set(["valve", "pump", "main_line"]);

/** "4 s ago" for a probe or sensor (a flow meter too); "open now", "running" or "switched 13:58"
 * for a valve, pump or main line. `state` is the row's Home Assistant state. */
export function seenText(
  row: Pick<StatusEntity, "kind" | "last_seen" | "last_change">,
  state: string | undefined,
  tz: string,
  now: number,
): string {
  if (ACTUATORS.has(row.kind)) {
    if (state === "on") return row.kind === "pump" ? "running" : "open now";
    const changed = instant(row.last_change);
    if (changed === null) return "not found in Home Assistant";
    return `switched ${dayKey(changed, tz) === dayKey(now, tz) ? "" : `${dayLabel(changed, tz)} `}${clock(changed, tz)}`;
  }
  const seen = instant(row.last_seen);
  return seen === null ? "not found in Home Assistant" : `${duration(now - seen)} ago`;
}

/** The controller's read-back time: milliseconds under a second, else seconds to a tenth. */
export const readbackText = (ms: number) =>
  ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toLocaleString("en", { maximumFractionDigits: 1 })} s`;

/** A row's dot: red only when the backend calls the device silent or unavailable (its probe limit
 * follows the probe's own rhythm); a probe it counts online is orange once its last report is over
 * 120 s old. A valve, pump or other actuator reports when it switches, so its age is not used. */
export function ageTone(row: { kind: string; last_seen: string | null; ok: boolean }, now: number): "ok" | "warn" | "bad" {
  if (!row.ok) return "bad";
  if (!PROBES.has(row.kind)) return "ok";
  const seen = instant(row.last_seen);
  return seen === null || now - seen > PROBE_WARN_MS ? "warn" : "ok";
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
