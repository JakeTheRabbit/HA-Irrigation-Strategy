/** The v2 `crop_steering.*` service shapes, with the backend plan's field names exactly
 * (docs/archive/superpowers/plans/2026-10-22-parity-backend.md). Times are ISO strings with an offset;
 * compare them as instants, never as text. Values are canonical: %, mS/cm, °C, litres, seconds. */

export type JournalActor =
  | "engine" | "timer" | "plan" | "manual" | "ai" | "learner" | "safety" | "mcp" | "aigrow"
  | "automation" | "system";
export type JournalOutcome = "ok" | "queued" | "held" | "refused" | "aborted" | "failed" | "partial";

/** One Journal event (unified schema §4). `data` is kind-specific. */
export interface CsEvent {
  v: 1;
  id: string;
  seq?: number;
  ts: string;
  room_id: string;
  zone: number | null;
  kind: string;
  outcome: JournalOutcome;
  code: string | null;
  source: {
    actor: JournalActor;
    detail?: string | null;
    program_id?: string | null;
    user_id?: string | null;
    judge?: string | null;
    client?: string | null;
  };
  correlation?: {
    intent_id?: string | null;
    causation_id?: string | null;
    batch_id?: string | null;
    run_id?: string | null;
    ledger_id?: string | null;
  };
  data: Record<string, unknown>;
  readback?: { status: string; entities?: string[]; at?: string } | null;
}

/** `journal_query` → data. */
export interface JournalPage {
  events: CsEvent[];
  cursor: string | null;
}

// timeline_get / timeline_summary (backend Task 25)
export type TimelineBlockKind = "shot" | "held" | "queued" | "planned" | "alert";
export type TimelineBlockStatus = "done" | "planned" | "error" | "warning";
export interface TimelineBlock {
  id: string;
  kind: TimelineBlockKind;
  status: TimelineBlockStatus;
  start: string;
  end: string;
  /** Commanded litres. */
  litres: number | null;
  /** Metered litres; null without a meter. */
  metered_l: number | null;
  reason: string | null;
  phase: string | null;
  vwc_before: number | null;
  vwc_expected: number | null;
  requested_at: string | null;
  pump_wait_s: number | null;
  source: string | null;
  code: string | null;
  event_id: string | null;
  skippable: boolean;
  /** An engine expectation, not a fixed timer slot. */
  expected?: boolean;
  /** A shot still open inside its expected window (status "done"). */
  running?: boolean;
  /** A planned slot already skipped (no longer skippable). */
  skipped?: boolean;
}
export interface TimelineRoom {
  room_id: string;
  lights: { on: string; off: string }[];
  rows: { zone: number; blocks: TimelineBlock[] }[];
  /** The room's irrigation pump (switch entity), else null. */
  pump: string | null;
  /** Every room on that pump; its `pump_load` is their total. */
  pump_rooms: string[];
  /** pct is null when the pump's capacity or a running zone's demand is unknown. */
  pump_load: { t: string; pct: number | null }[];
  /** "unavailable": the controller gave no planned shots, so the room has no planned blocks. */
  planned_source: "projection_app" | "unavailable";
}
export interface TimelineGetData {
  rooms: TimelineRoom[];
  /** True when the answer was cut to the newest blocks. */
  truncated?: boolean;
  /** The backend plan fixes `count` only; a marker's fields are not specified yet. */
  errors: { count: number; markers: Record<string, unknown>[] };
}
export interface TimelineSummary {
  days: {
    date: string;
    rooms: { room_id: string; shots: number; failed: number; warnings: number; held: number; queued: number }[];
  }[];
}

// history_changes / history_revert (backend Task 24)
export interface HistoryChange {
  id: string;
  room_id: string;
  ts: string;
  actor: JournalActor;
  kind: "setpoint" | "plan" | "recipe" | "setup" | "calibration" | "alerts";
  key?: string;
  section?: string;
  scope: string | null;
  old: unknown;
  new: unknown;
  reason: string | null;
  outcome: string | null;
  limits: { writer: "learner" | "brain"; min: number; max: number; step_scope: string | null } | null;
  revertible: boolean;
  user_id: string | null;
  user_name: string | null;
  /** The writer's own words: "put back" for a revert, "preset …" for a recipe. */
  detail?: string | null;
}
export interface HistoryRevertResult {
  reverted_event_id: string;
  new_event_id: string;
  readback: unknown;
  /** A store put back: each program the change had deleted, back under a new id. */
  renewed?: { name: string | null; old_id: string; id: string }[];
}

// supply_get / supply_save (backend Task 11)
export interface IrrigationPump {
  entity_id: string;
  max_flow_lph?: number | null;
  max_concurrent_zones: number;
  flow_meter?: string | null;
}
export interface CapacityPair {
  zones: number[] | { room_id: string; zone: number }[];
  lph: number;
  pct_of_pump: number | null;
  verdict: "together" | "one_after_another";
}
export interface SupplyDoc {
  revision: number;
  irrigation_pumps: IrrigationPump[];
  water_sources: Record<string, unknown>[];
  /** `{"room:f2_": {"3": "a"}}` */
  zone_groups: Record<string, Record<string, string>>;
  /** `{"room:f2_": {"3": "sensor.f2_meter_3"}}` */
  zone_meters: Record<string, Record<string, string>>;
  capacity_check: {
    worst_case_lph: number;
    max_flow_lph: number | null;
    ok: boolean;
    suggest_max_concurrent: number | null;
    pairs: CapacityPair[];
    /** Each pump's own row (site_store.capacity_check). */
    pumps?: PumpCheck[];
  };
}
export interface PumpCheck {
  entity_id: string;
  worst_case_lph: number;
  max_flow_lph: number | null;
  max_concurrent_zones: number;
  ok: boolean;
  suggest_max_concurrent: number | null;
}
/** supply_save with `preview: true`: what would change and the check of the result; nothing saved. */
export interface SupplyPreview {
  diff: unknown;
  capacity_check: SupplyDoc["capacity_check"];
}

// timer_program_* / timer_skip (backend Task 14)
export interface TimerWindow {
  kind: "all" | "lights_on" | "lights_off" | "custom";
  from?: string;
  to?: string;
}
export interface TimerProgram {
  id: string;
  room_id: string;
  name: string;
  zones: number[];
  type: "one_off" | "recycle" | "simple";
  duration_s: number;
  interval_min: number | null;
  frequency_per_day: number | null;
  start_at: string | null;
  window: TimerWindow;
  sync_time?: string | null;
  active: boolean;
  revision?: number;
}
export interface TimerProgramListItem extends TimerProgram {
  next_at: string | null;
  zones_in_timer_mode: number[];
  /** Why its next shot could not be worked out; the other programs still list. */
  error?: string | null;
}
export interface TimerPreview {
  preview: { zone: number; at: string; duration_s: number }[];
  shots: number;
  total_s: number;
}

// alert_rule_* (backend Task 16)
export type AlertSource =
  | "zone.vwc" | "zone.ec" | "zone.temperature" | "feed.ph" | "feed.ec" | "tank.level" | "stock.pct"
  | "zone.flow_ratio" | "controller.heartbeat" | "probe.silence_s" | "stock.litres";
export interface AlertRule {
  id: string;
  kind: "threshold" | "builtin";
  room_id: string;
  zones?: number[];
  source: AlertSource;
  /** Required for `probe.silence_s`. */
  entity_id?: string;
  /** Required for `stock.litres`. */
  tank_id?: string;
  op: "above" | "below";
  threshold: number;
  unit: string;
  window: TimerWindow;
  min_duration_s: number;
  severity: "info" | "warning" | "emergency";
  routing: string;
  active: boolean;
}
export interface AlertRuleListItem extends AlertRule {
  /** The integration's own words for the rule: "Tell when F2 tank level stays below 30% for 10 min." */
  summary_sentence: string;
  state: "draft" | "armed" | "pending" | "firing" | "acknowledged" | "muted";
  last_fired: string | null;
  firing_since: string | null;
  current_value: number | null;
}
/** `alert_rule_list`: `revision` is the site-wide one `alert_rule_set` takes as `expected_revision`. */
export interface AlertRuleList {
  rules: AlertRuleListItem[];
  revision: number;
}
export interface AlertPreview {
  summary_sentence: string;
  series: [string, number][];
  fires: { start: string; fired_at: string; end: string | null }[];
  ignored: { start: string; end: string; reason: "shorter than min_duration" | "outside window" | "muted" }[];
  count: number;
  min: number | null;
  max: number | null;
  sentence: string;
  /** `alert_rule_test` with `send: true` only. */
  delivery?: { service: string | null; ok: boolean; error: string | null }[];
}

// preset_* / copy_config (backend Task 22)
export interface PresetTarget {
  room_id: string;
  zone?: number;
}
export interface PresetDiff {
  diff: { target: PresetTarget; key: string; old: unknown; new: unknown }[];
  applied?: { target: PresetTarget; key: string; readback: "verified" | "refused"; error?: string | null }[];
}
/** A key the target has no setting for (no `reason`), or a timer the source has none of (`reason`):
 * never written, never in `diff`. */
export interface PresetMissing {
  target: PresetTarget;
  key: string;
  reason?: string;
}
/** preset_apply / copy_config: what would change (`preview`) or what changed (`applied`, one row a
 * write with its read-back). copy_config adds the source's `skipped` keys (no reading). */
export interface PresetResult extends PresetDiff {
  missing: PresetMissing[];
  skipped?: string[];
}
export type PresetScope = "targets" | "timers" | "all";
/** One preset as the site store keeps it: values by section, keyed without a zone prefix. */
export interface StoredPreset {
  id: string;
  name: string;
  scope: PresetScope;
  sections: string[];
  from: PresetTarget;
  values: Record<string, Record<string, unknown>>;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}
export interface PresetList {
  revision: number;
  presets: StoredPreset[];
  error: string | null;
}
export interface PresetSaved {
  preset: StoredPreset;
  revision: number;
  /** The source's settings that could not be read, so are not in the preset. */
  skipped: string[];
}

// system_status_get (backend Task 28)
export interface StatusEntity {
  entity_id: string;
  name: string;
  kind: "probe_vwc" | "probe_ec" | "probe_temp" | "valve" | "pump" | "main_line" | "feed_probe" | "tank" | "flow_meter";
  zone: number | null;
  last_seen: string | null;
  last_change: string | null;
  ok: boolean;
  uptime_7d_pct: number | null;
}
export type ControllerState = "running" | "stale" | "absent";
/** One heartbeat: a missed one is put in where the gap was over 2 x interval_s, with that gap. */
export interface StatusBeat {
  at: string;
  missed: boolean;
  readback_ms: number | null;
  gap_s?: number;
}
export interface RoomHeartbeat {
  last_beat: string | null;
  age_s: number | null;
  controller: ControllerState;
  beats: StatusBeat[];
  interval_s: number;
}
export interface SystemStatus {
  controller: ControllerState;
  addon_version: string | null;
  /** Share of every mapped entity that is ok, unrounded; null with none mapped. */
  pct_online: number | null;
  ha_version: string | null;
  ai: { model: string | null; calls_today: number | null; daily_budget: number | null; pct_used: number | null } | null;
  card_version: string | null;
  rooms: {
    room_id: string;
    pct_online: number | null;
    alerts_open: number | null;
    entities: StatusEntity[];
    groups: { kind: StatusEntity["kind"]; entities: StatusEntity[] }[];
    heartbeat: RoomHeartbeat;
  }[];
}

// calibration_* (backend Task 17; calibration.py)
export interface CalibrationSession {
  session_id: string;
  room_id: string;
  probe: "feed_ph" | "feed_ec";
  kind: "ph" | "ec";
  /** The two reference solutions, in the order they are captured. */
  solutions: number[];
  raw_entity_id: string;
  temperature_entity_id: string | null;
  dosing_paused: boolean;
  expires_at: string;
}
export interface CaptureResult {
  reading: number | null;
  raw: number | null;
  stable: boolean;
  drift: number | null;
  stable_s: number;
}
export interface CalibrationStatus extends CaptureResult {
  points_captured: number;
  expires_at: string;
}
export interface CalibrationCommitResult {
  record_id: string;
  revision: number;
  slope_pct: number;
  offset: number;
  verdict: "pass" | "drifting" | "fail";
  applied: boolean;
}

// pump_* (backend Tasks 19, 20)
export type PumpBlockerCode =
  | "no_power_entity" | "batch_running" | "mix_pump_on" | "tank_filling" | "calibrating" | "pump_calibrating" | "controller_offline";
export interface PumpPrecheck {
  ok: boolean;
  blockers: { code: PumpBlockerCode; message: string }[];
}
export interface PumpPrimeResult {
  request_id: string;
  outcome: "requested" | "refused";
  blockers: PumpPrecheck["blockers"];
}
export interface PumpCalibrateStart {
  session_id: string | null;
  request_id: string | null;
  outcome: "requested" | "refused";
  blockers: PumpPrecheck["blockers"];
}
export interface PumpCalibrationResult {
  ml_min: number;
  previous_ml_min: number | null;
  flow_entity_written: boolean;
}

// probe_offset_set (backend Task 21)
export interface ProbeOffsetResult {
  offset: number;
  corrected_now: number | null;
  fused_before: number | null;
  fused_after: number | null;
  /** With `preview: true` only. */
  diff?: unknown;
}

// dashboard_* (backend Task 32)
export interface DashboardList {
  dashboards: { url_path: string; title: string; template: string; rooms: string[]; created_at: string; exists: boolean }[];
  templates: { id: string; name: string; description: string }[];
}
