export type OperatorAction =
  | "runs_get"
  | "runs_save"
  | "runs_archive"
  | "runs_import"
  | "strategy_get"
  | "strategy_save"
  | "strategy_preview"
  | "strategy_activate"
  | "strategy_disarm"
  | "setup_read"
  | "setup_create"
  | "setup_save"
  | "setup_remove";

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
  hardware: Record<string, string | number>;
  safety: { ready: boolean; blockers: string[] };
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
  capabilities: { create: boolean; save: boolean; remove: boolean; stable_zone_ids: boolean };
  rooms: SetupRoom[];
  candidates: SetupCandidate[];
  limits: { max_zones: number };
}
