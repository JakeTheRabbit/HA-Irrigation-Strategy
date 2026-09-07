import type { HistoryRequest, HistoryWindow } from "./comparison-types";
import type { OperatorAction } from "./operator-types";
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
  fields: Setting[];
  sensors: EntityState[];
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
