export type OperatorAction =
  | "runs_get"
  | "runs_save"
  | "runs_archive"
  | "runs_import"
  | "setpoint_log_get"
  | "overlay_get"
  | "overlay_keep"
  | "overlay_undo"
  | "strategy_get"
  | "strategy_save"
  | "strategy_preview"
  | "strategy_activate"
  | "strategy_disarm"
  | "setup_read"
  | "setup_create"
  | "setup_save"
  | "setup_remove"
  | "setup_commission"
  | "test_shot"
  | "stock_get"
  | "stock_save"
  | "stock_refill"
  | "stock_record_batch"
  | "calibration_get"
  | "calibration_record"
  | "dosing_get"
  | "dosing_save"
  | "dosing_request"
  | "notify_get"
  | "notify_save"
  | "notify_test"
  | "whats_new_get"
  | "whats_new_seen"
  | "brain_ask";

export interface ParameterLimit {
  value: number | null;
  min: number;
  max: number;
  step: number;
  unit: string;
  entity_ids: string[];
}
export interface SteeringProfile {
  id: string;
  name: string;
  vegetative: Record<string, number>;
  generative: Record<string, number>;
}
export interface ScheduleBlock {
  start_day: number;
  end_day: number;
  profile_id: string;
  bias: number;
}
export interface ZonePlan {
  zone_id: number;
  start_date: string;
  schedule: ScheduleBlock[];
}
export interface GrowPlan {
  schema_version: 1;
  /** The grower's own name for the plan (optional; a plan saved before it has none). */
  name?: string;
  profiles: SteeringProfile[];
  zones: ZonePlan[];
}
export interface HydraulicPreview {
  substrate_l_per_plant: number;
  plant_count: number;
  drippers_per_plant: number;
  dripper_flow_lph: number;
  zone_substrate_l: number;
  zone_flow_lps: number;
  shots: Record<string, { volume_l: number; duration_s: number; capped_duration_s: number }>;
}
export interface PlanZonePreview {
  zone_id: number;
  day: number;
  profile_id?: string;
  bias?: number;
  parameters: Record<string, number>;
  hydraulics?: HydraulicPreview;
  errors: string[];
}
export interface StrategyDocument {
  room_id: string;
  revision: number;
  status: "draft" | "armed" | "active" | "disarming" | "error";
  plan: GrowPlan;
  error: string | null;
  active: {
    grow_day: string | null;
    zones: {
      zone_id: number;
      day: number;
      profile_id: string;
      bias: number;
      parameters: Record<string, number>;
      status: string;
      error?: string;
    }[];
  };
  capabilities: { strategy_snapshot_version: number; controller_supported: boolean };
  catalog: Record<string, Record<string, ParameterLimit>>;
  preview?: { date: string; zones: PlanZonePreview[] };
}
export interface SetupZone {
  id: number;
  name: string;
  active: boolean;
  valve: string;
  vwc_sensors: string[];
  ec_sensors: string[];
  plant_count: number;
  substrate_volume?: number;
  drippers_per_plant?: number;
  dripper_flow_rate?: number;
  /** Mapped probes that do not count towards the zone's reading, and the primary one ("" none):
   * the Probes page's choice. Absent from an older integration. */
  vwc_unused?: string[];
  vwc_primary?: string;
  ec_unused?: string[];
  ec_primary?: string;
}
export interface SetupRoom {
  entry_id: string;
  revision: number;
  room_name: string;
  prefix: string;
  slug: string;
  active: boolean;
  num_zones: number;
  active_zone_ids: number[];
  zones: SetupZone[];
  /** Each mapping; ac_entities and dehumidifier_entities are lists (the runoff estimator's units). */
  hardware: Record<string, string | number | string[]>;
  /** Declared plumbing layout; "" (or absent, from an older integration) when never declared. */
  plumbing?: string;
  /** What the SAVED switches imply: a prefill for a room that never declared, never stored. */
  plumbing_inferred?: string;
  safety: { ready: boolean; blockers: string[] };
  /** The setup wizard's live checks (lib/commissioning.ts); absent from an older integration. */
  commissioning?: Commissioning;
}
export type CommissioningCheckId =
  "controller" | "room" | "valves" | "probes" | "sizing" | "test_shot";
export interface CommissioningCheck {
  id: CommissioningCheckId;
  step: number;
  ok: boolean;
  /** A safety check: Switch on waits for it. The others only warn. */
  blocking: boolean;
  problems: string[];
}
export interface Commissioning {
  /** Set up already: every room from before the wizard, and one the wizard finished. */
  commissioned: boolean;
  ready: boolean;
  waiting_for: string | null;
  checks: CommissioningCheck[];
  draft: { water_seen: Record<string, string>; sizing_confirmed: boolean };
}
export interface SetupCandidate {
  entity_id: string;
  name: string;
  domain: string;
  state: string;
  unit: string;
  device_class?: string;
}
export interface SetupDocument {
  api_version: number;
  capabilities: {
    create: boolean;
    save: boolean;
    remove: boolean;
    stable_zone_ids: boolean;
    /** The integration stores and checks a declared plumbing layout (absent before 2.19). */
    plumbing?: boolean;
    /** The setup API reports each room's readiness and saves the wizard's draft. */
    commissioning?: boolean;
  };
  rooms: SetupRoom[];
  candidates: SetupCandidate[];
  limits: { max_zones: number };
  /** What a new zone's sizing starts at: the integration's one defaults table (absent before it). */
  sizing_defaults?: Partial<
    Pick<SetupZone, "plant_count" | "substrate_volume" | "drippers_per_plant" | "dripper_flow_rate">
  >;
}
