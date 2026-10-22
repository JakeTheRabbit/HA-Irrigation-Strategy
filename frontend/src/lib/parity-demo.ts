import { demoBackend, type DemoBackend } from "./demo";
import { PARITY_ACTIONS, type ParityAction } from "./parity-api";
import { DEMO_TIMER_PROGRAM_ID, demoId, demoJournal } from "./parity-demo/journal";
import type {
  AlertPreview,
  AlertRuleListItem,
  CsEvent,
  DashboardList,
  HistoryChange,
  PresetDiff,
  SupplyDoc,
  SystemStatus,
  TimelineBlock,
  TimelineGetData,
  TimelineSummary,
  TimerProgramListItem,
} from "./parity-types";

/** One lane's demo answer. `answer` returns the service's `data`, or a whole v2 envelope
 * (`api: 2`, e.g. an error) that is passed through as it is. */
export interface DemoHandler {
  action: ParityAction;
  match?(data: Record<string, unknown>): boolean;
  answer(data: Record<string, unknown>, now: number): unknown;
}

/** Each lane's `parity-demo/<lane>.ts` exports `handlers`; they run in file-name order. */
const lanes = import.meta.glob<{ handlers?: DemoHandler[] }>(
  ["./parity-demo/*.ts", "!./parity-demo/*.test.ts"],
  { eager: true },
);
const LANE_HANDLERS: DemoHandler[] = Object.keys(lanes)
  .sort()
  .flatMap((file) => lanes[file].handlers ?? []);

const DEMO_ROOMS = ["room:", "room:room_b_"];
const iso = (ms: number) => new Date(ms).toISOString();
const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const roomsOf = (data: Record<string, unknown>) =>
  Array.isArray(data.rooms) && data.rooms.length ? data.rooms.map(String) : typeof data.room_id === "string" ? [data.room_id] : DEMO_ROOMS;
const dayEvents = (rooms: string[], now: number) => rooms.flatMap((room) => demoJournal(room, now));

/** The v2 envelope around a demo answer, read back at `now`. */
export function demoEnvelope(data: unknown, now: number, roomId?: unknown) {
  return {
    api: 2,
    ok: true,
    room_id: typeof roomId === "string" ? roomId : null,
    revision: isRecord(data) && typeof data.revision === "number" ? data.revision : null,
    readback: { status: "verified", at: iso(now) },
    event_ids: [],
    data,
  };
}

/** The error an integration older than 3.18 gives for a v2 service. */
export function missingServiceError(action: string): Error {
  return Object.assign(new Error(`Service crop_steering.${action} not found.`), { code: "service_not_found" });
}

function timeline(data: Record<string, unknown>, now: number): TimelineGetData {
  const rooms = roomsOf(data);
  const zones = Array.isArray(data.zones) ? (data.zones as number[]) : null;
  return {
    rooms: rooms.map((room_id) => {
      const events = demoJournal(room_id, now);
      const rows = new Map<number, TimelineBlock[]>();
      const block = (e: CsEvent, extra: Partial<TimelineBlock>): TimelineBlock => ({
        id: e.id, kind: "shot", status: "done", start: e.ts, end: e.ts, litres: null, metered_l: null, reason: null,
        phase: null, vwc_before: null, vwc_expected: null, requested_at: null, pump_wait_s: null,
        source: e.source.actor, code: e.code, event_id: e.id, skippable: false, ...extra,
      });
      for (const e of events) {
        if (e.zone === null || (zones && !zones.includes(e.zone))) continue;
        const list = rows.get(e.zone) ?? [];
        rows.set(e.zone, list);
        if (e.kind === "shot.started") {
          const done = events.find((c) => c.kind === "shot.completed" && c.correlation?.intent_id === e.correlation?.intent_id);
          const d = e.data;
          list.push(block(e, {
            end: done?.ts ?? iso(now), litres: Number(d.commanded_l), metered_l: (done?.data.metered_l as number) ?? null,
            reason: String(d.reason), phase: String(d.phase), vwc_before: d.vwc_before as number,
            vwc_expected: (d.vwc_expected as number | null) ?? null, requested_at: String(d.requested_at),
            pump_wait_s: Number(d.pump_wait_s), status: done && Number(done.data.metered_l) / Number(d.commanded_l) < 0.8 ? "warning" : "done",
          }));
        } else if (e.kind === "intent.held")
          list.push(block(e, { kind: "held", status: "warning", reason: String(e.data.reason), end: iso(Date.parse(e.ts) + 60_000) }));
      }
      // The next shot of each zone that waters, planned 45 min after its last.
      for (const [zone, list] of rows) {
        const last = list.filter((b) => b.kind === "shot").at(-1);
        if (!last) continue;
        const at = Date.parse(last.start) + 45 * 60_000;
        list.push({ ...last, id: demoId(at, `planned:${room_id}:${zone}`), status: "planned", kind: "planned",
          start: iso(at), end: iso(at + 60_000), metered_l: null, event_id: null, source: "engine", skippable: true,
          expected: true, requested_at: null, pump_wait_s: null, code: null });
      }
      const on = demoJournal(room_id, now).find((e) => e.kind === "phase.changed" && e.data.to === "P0");
      const lightsOn = on ? Date.parse(on.ts) : now;
      return {
        room_id,
        lights: [{ on: iso(lightsOn), off: iso(lightsOn + 12 * 3_600_000) }],
        rows: [...rows].sort(([a], [b]) => a - b).map(([zone, blocks]) => ({ zone, blocks })),
        pump_load: [{ t: iso(now - 3_600_000), pct: 48 }, { t: iso(now), pct: 0 }],
      };
    }),
    errors: { count: 0, markers: [] },
  };
}

function summary(data: Record<string, unknown>, now: number): TimelineSummary {
  const days = Array.isArray(data.days) && data.days.length ? data.days.map(String) : [new Date(now).toLocaleDateString("sv")];
  const rooms = roomsOf(data);
  return {
    days: days.map((date) => ({
      date,
      rooms: rooms.map((room_id) => {
        const on = demoJournal(room_id, now).filter((e) => new Date(e.ts).toLocaleDateString("sv") === date);
        const count = (kind: string, test: (e: CsEvent) => boolean = () => true) => on.filter((e) => e.kind === kind && test(e)).length;
        return {
          room_id,
          shots: count("shot.completed"),
          failed: count("shot.aborted"),
          warnings: count("flow.reconciled", (e) => Number(e.data.ratio) < 0.8),
          held: count("intent.held"),
          queued: count("intent.queued"),
        };
      }),
    })),
  };
}

function changes(data: Record<string, unknown>, now: number): { changes: HistoryChange[] } {
  const rooms = typeof data.room_id === "string" ? [data.room_id] : DEMO_ROOMS;
  const kinds = { "target.changed": "setpoint", "config.changed": "setup", "calibration.committed": "calibration" } as const;
  return {
    changes: dayEvents(rooms, now)
      .filter((e): e is CsEvent & { kind: keyof typeof kinds } => e.kind in kinds)
      .filter((e) => data.zone == null || e.zone === Number(data.zone))
      .sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts))
      .map((e) => ({
        id: e.id, room_id: e.room_id, ts: e.ts, actor: e.source.actor, kind: kinds[e.kind],
        ...(e.kind === "target.changed" ? { key: String(e.data.key) } : { section: String(e.data.section ?? e.data.probe) }),
        scope: (e.data.scope as string) ?? null, old: e.data.old ?? null, new: e.data.new ?? null,
        reason: (e.data.reason as string) ?? null,
        outcome: e.source.actor === "learner" ? "Too soon to judge — check after the next lights-on." : null,
        limits: e.source.actor === "learner" ? { writer: "learner", min: 50, max: 65, step_scope: "zone" } : null,
        revertible: e.kind !== "calibration.committed",
        user_id: e.source.user_id ?? null, user_name: e.source.actor === "manual" ? "Ben" : null,
      })),
  };
}

const SUPPLY: SupplyDoc = {
  revision: 1,
  irrigation_pumps: [{ entity_id: "switch.demo_irrigation_pump", max_flow_lph: 1200, max_concurrent_zones: 1, flow_meter: null }],
  water_sources: [],
  zone_groups: {},
  zone_meters: {},
  capacity_check: {
    worst_case_lph: 480, max_flow_lph: 1200, ok: true, suggest_max_concurrent: 2,
    pairs: [{ zones: [1, 2], lph: 960, pct_of_pump: 80, verdict: "one_after_another" }],
  },
};

const timerProgram = (now: number): TimerProgramListItem => ({
  id: DEMO_TIMER_PROGRAM_ID, room_id: "room:", name: "Zone 3 day timer", zones: [3], type: "recycle",
  duration_s: 60, interval_min: 45, frequency_per_day: null, start_at: null,
  window: { kind: "lights_on" }, sync_time: null, active: true, revision: 1,
  next_at: iso(now + 30 * 60_000), zones_in_timer_mode: [3],
});

const rule = (data: Record<string, unknown>): AlertRuleListItem => ({
  id: "01JDEMORULETANKLOW0000000", kind: "threshold", room_id: "room:", source: "tank.level", op: "below",
  threshold: 30, unit: "%", window: { kind: "lights_on" }, min_duration_s: 600, severity: "warning", routing: "sensors",
  active: true, state: "armed", last_fired: null, firing_since: null, current_value: 68,
  ...(isRecord(data.rule) ? data.rule : {}),
});

const preview = (now: number): AlertPreview => ({
  summary_sentence: "Tell when Room A tank level stays below 30% for 10 min during lights-on.",
  series: Array.from({ length: 24 }, (_, h) => [iso(now - (24 - h) * 3_600_000), 70 - h]),
  fires: [], ignored: [], count: 0, min: 46, max: 70,
  sentence: "It wouldn't have fired in the last 24 h. Lowest was 46%.",
});

const presetDiff = (data: Record<string, unknown>): PresetDiff => {
  const diff = [{ target: { room_id: "room:room_b_", zone: 1 }, key: "p1_target_vwc", old: 65, new: 66 }];
  return data.preview === false || data.preview === undefined
    ? { diff, applied: diff.map(({ target, key }) => ({ target, key, readback: "verified" as const })) }
    : { diff };
};

const status = (now: number): SystemStatus => ({
  controller: "running", addon_version: "3.18.0", ha_version: "2026.10.1",
  ai: { model: "claude-haiku-4-5", calls_today: 42, daily_budget: 200, pct_used: 21 },
  card_version: "3.18.0",
  rooms: DEMO_ROOMS.map((room_id, index) => {
    const entity = (n: number) => ({
      entity_id: `sensor.crop_steering_${room_id.slice(5)}vwc_zone_${n}`, name: `Zone ${n} VWC`, kind: "probe_vwc" as const,
      zone: n, last_seen: iso(now - 40_000), last_change: iso(now - 40_000), ok: !(index === 1 && n === 2),
      uptime_7d_pct: index === 1 && n === 2 ? 92.85714285714286 : 100,
    });
    const probes = [1, 2, 3].map(entity);
    return {
      room_id, pct_online: index ? 66.66666666666667 : 100, alerts_open: 1,
      entities: probes.map(({ entity_id, last_seen, ok }) => ({ entity_id, last_seen, ok })),
      groups: [{ kind: "probe_vwc", entities: probes }],
      heartbeat: {
        last_beat: iso(now - 18_000), age_s: 18, controller: "running", interval_s: 60,
        beats: Array.from({ length: 10 }, (_, i) => ({ at: iso(now - (10 - i) * 60_000), missed: false, readback_ms: null })),
      },
    };
  }),
});

const DASHBOARDS: DashboardList = {
  dashboards: [],
  templates: [
    { id: "facility_wall", name: "Facility wall", description: "Every room at a glance, for a wall screen." },
    { id: "room_tablet", name: "Room tablet", description: "One room's zones and tank, for a tablet by the door." },
    { id: "dosing_station", name: "Dosing station", description: "Feed tank, stock and pumps." },
  ],
};

/** Task 3's answer for every parity action: plausible, deterministic for `now`. */
const DEFAULTS: Record<ParityAction, (data: Record<string, unknown>, now: number) => unknown> = {
  // Never reached: parity-demo/journal.ts always answers journal_query (the record needs a key).
  journal_query: () => ({ events: [], cursor: null }),
  timeline_get: timeline,
  timeline_summary: summary,
  history_changes: changes,
  history_revert: (d, now) => ({ reverted_event_id: d.event_id ?? null, new_event_id: demoId(now, `revert:${String(d.event_id)}`), readback: "verified" }),
  supply_get: () => structuredClone(SUPPLY),
  supply_save: (d) => ({ ...structuredClone(SUPPLY), revision: Number(d.expected_revision ?? SUPPLY.revision) + (d.preview ? 0 : 1) }),
  pump_precheck: () => ({ ok: true, blockers: [] }),
  pump_prime: (d, now) =>
    // The integration's schema caps a prime at 1–30 s; the envelope reports it as `invalid`.
    d.seconds !== undefined && !(Number(d.seconds) >= 1 && Number(d.seconds) <= 30)
      ? { api: 2, ok: false, error: { code: "invalid", message: "value must be between 1 and 30 for dictionary value @ data['seconds']" } }
      : { request_id: demoId(now, "prime"), outcome: "requested", blockers: [] },
  pump_stop: (_d, now) => ({ request_id: demoId(now, "stop") }),
  pump_calibrate: (_d, now) => ({ session_id: demoId(now, "pump-cal"), outcome: "requested" }),
  pump_calibration_commit: (d) => ({ ml_min: (Number(d.measured_ml) || 150) / 30 * 60, previous_ml_min: 290, flow_entity_written: true }),
  calibration_start: (_d, now) => ({ session_id: demoId(now, "feed-cal"), raw_entity_id: "sensor.demo_feed_ph", temperature_entity_id: "sensor.demo_tank_temperature", dosing_paused: true, expires_at: iso(now + 30 * 60_000) }),
  calibration_capture: () => ({ reading: 7.02, raw: 7.08, stable: true, drift: 0.004, stable_s: 32 }),
  calibration_status: (_d, now) => ({ reading: 7.02, raw: 7.08, stable: true, drift: 0.004, stable_s: 32, points_captured: 0, expires_at: iso(now + 30 * 60_000) }),
  calibration_commit: () => ({ slope_pct: 98.4, offset: 0.06, verdict: "pass", applied: true }),
  calibration_revert: () => ({ slope_pct: null, offset: null, verdict: null, applied: false }),
  probe_offset_set: (d) => ({ offset: 3, corrected_now: 52, fused_before: 49, fused_after: 52, ...(d.preview ? { diff: [{ path: "offset", old: 0, new: 3 }] } : {}) }),
  alert_rule_set: (d) => ({ ...rule(d), summary_sentence: preview(0).summary_sentence, revision: 2 }),
  alert_rule_delete: (d) => ({ id: d.id ?? null, revision: 2 }),
  alert_rule_test: (d, now) => ({ ...preview(now), ...(d.send ? { delivery: [{ service: "notify.mobile_app_demo", ok: true, error: null }] } : {}) }),
  alert_rule_preview: (_d, now) => preview(now),
  alert_rule_list: (d) => ({ rules: [rule({})].filter((r) => d.room_id == null || r.room_id === d.room_id) }),
  alert_ack: (d, now) => ({ alert_event_id: d.alert_event_id ?? null, event_id: demoId(now, "ack") }),
  timer_program_set: (d, now) => ({ program: { ...timerProgram(now), ...(isRecord(d.program) ? d.program : {}) }, revision: 2, preview: [] }),
  timer_program_delete: (d) => ({ id: d.id ?? null, revision: 2 }),
  timer_program_list: (d, now) => ({ programs: [timerProgram(now)].filter((p) => d.room_id == null || p.room_id === d.room_id), revision: 1 }),
  timer_program_preview: (_d, now) => {
    const preview = Array.from({ length: 8 }, (_, i) => ({ zone: 3, at: iso(now + (i + 1) * 30 * 60_000), duration_s: 120 }));
    return { preview, shots: preview.length, total_s: preview.length * 120 };
  },
  timer_skip: (d) => ({ skip: { zone: d.zone ?? null, at: d.at ?? null, until: typeof d.at === "string" ? iso(Date.parse(d.at) + 15 * 60_000) : null }, revision: 2 }),
  preset_list: () => ({ presets: [{ id: "01JDEMOPRESETBULKWEEK5000", name: "Bulk week 5", scope: "targets", from: { room_id: "room:" } }], revision: 1 }),
  preset_save: (d, now) => ({ id: demoId(now, `preset:${String(d.name)}`), name: d.name ?? "Preset", scope: d.scope ?? "targets", from: d.from ?? null, revision: 2 }),
  preset_apply: presetDiff,
  preset_delete: (d) => ({ id: d.id ?? null, revision: 2 }),
  copy_config: presetDiff,
  dashboard_create: (d) => ({ url_path: `crop-steering-${String(d.template ?? "facility_wall")}-1`, title: d.title ?? "Crop Steering" }),
  dashboard_list: () => structuredClone(DASHBOARDS),
  system_status_get: (_d, now) => status(now),
};

/** The demo's v2 integration: a lane handler whose `match` accepts the call, else Task 3's default.
 * With `?backend=3.17` every parity action is missing, as on an older integration. */
export async function parityDemo(
  action: ParityAction,
  data: Record<string, unknown>,
  now: number,
  backend: DemoBackend = demoBackend(typeof window !== "undefined" ? window.location.search : ""),
): Promise<unknown> {
  if (backend === "3.17" || !(PARITY_ACTIONS as readonly string[]).includes(action)) throw missingServiceError(action);
  const handler = LANE_HANDLERS.find((h) => h.action === action && (!h.match || h.match(data)));
  const answer = handler ? handler.answer(data, now) : DEFAULTS[action](data, now);
  return isRecord(answer) && answer.api === 2 ? answer : demoEnvelope(answer, now, data.room_id);
}
