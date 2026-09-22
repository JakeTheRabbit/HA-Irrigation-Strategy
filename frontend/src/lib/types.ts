import type { HistoryRequest, HistoryWindow } from "./comparison-types";
import type { OperatorAction } from "./operator-types";
import type { AutoSetpointStatus } from "./auto-setpoints";
export interface EntityState {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
  last_changed?: string;
  last_updated?: string;
}
export type States = Record<string, EntityState>;
export interface Room {
  id: string;
  name: string;
  prefix: string;
}
export interface Metric {
  entityId: string | null;
  label: string;
  value: number | null;
  unit: string;
}
export interface Setting {
  entityId: string;
  label: string;
  description: string;
  value: number | null;
  min: number;
  max: number;
  step: number;
  unit: string;
  group: string;
  zoneId?: number;
}
export interface Choice {
  entityId: string;
  label: string;
  value: string | null;
  options: string[];
  zoneId?: number;
}
export interface Zone {
  id: number;
  name: string;
  enabledEntity: string | null;
  enabled: boolean | null;
  valveEntity: string | null;
  valveOn: boolean | null;
  lastIrrigation: {
    entityId: string | null;
    timestamp: string | null;
    issue: string | null;
  };
  phase: string;
  vwc: Metric;
  ec: Metric;
  target: Metric;
  ecTarget: Metric;
  water: Metric;
  shots: Metric;
  status: string;
  /** The controller is not reporting: phase and status are its last word, not live. */
  stale: boolean;
  fields: Setting[];
  sensors: EntityState[];
  /** Setpoint supervisor status; null when this zone has no supervisor sensor. */
  auto: AutoSetpointStatus | null;
}
export interface LogEvent {
  id: string;
  timestamp: string;
  message: string;
  type: "water" | "phase" | "warning" | "info";
  zoneId?: number;
}
export interface Notice {
  id: string;
  title: string;
  detail: string;
  severity: "warning" | "critical" | "info";
  zoneId?: number;
}
export interface RoomView {
  room: Room;
  zones: Zone[];
  engine: { entityId: string | null; enabled: boolean | null };
  metrics: Metric[];
  events: LogEvent[];
  entities: EntityState[];
  settings: Setting[];
  choices: Choice[];
  strategy: { status: string; engaged: boolean; valid: boolean };
  alerts: Notice[];
  /** False only when switch.crop_steering_<prefix>room_active reports "off". */
  roomActive: boolean;
  /** Null when the controller has no room switch: the room is on and the control is hidden. */
  roomActiveEntity: string | null;
  autoSetpoints: { entityId: string | null; enabled: boolean | null };
}
/** One line per room: is it watering, and if not, why not and what to do. */
export interface RoomStatus {
  room: Room;
  /** "stopped": not watering until someone acts. "stale": the controller stopped reporting. */
  tone: "watering" | "holding" | "stopped" | "stale" | "off";
  text: string;
  detail: string;
  /** When the controller last reported (epoch ms); null when it has not. */
  reportedAt: number | null;
}
export interface Change {
  entityId: string;
  value: number | boolean | string;
}
export interface WriteResult {
  applied: string[];
  failed: { entityId: string; reason: string }[];
}
export interface Series {
  entityId: string;
  label: string;
  points: { time: string; value: number }[];
}
export interface Controller {
  demo: boolean;
  connection: "connecting" | "live" | "demo" | "offline";
  error: string | null;
  lastUpdated: number | null;
  roomId: string;
  rooms: Room[];
  room: RoomView;
  states: States;
  refresh: () => Promise<void>;
  changeRoom: (id: string) => void;
  connect: (base: string, token: string) => Promise<void>;
  disconnect: () => void;
  write: (changes: Change[]) => Promise<WriteResult>;
  historyWindow: (request: HistoryRequest) => Promise<HistoryWindow>;
  history: (entityIds: string[], hours: number) => Promise<Series[]>;
  operator: <T>(action: OperatorAction, data?: Record<string, unknown>) => Promise<T>;
}
