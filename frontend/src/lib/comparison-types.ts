export interface RunZone {
  zone_id: number;
  name: string;
  vwc_sensor: string | null;
  ec_sensor: string | null;
  plant_count: number | null;
  parameters: Record<string, number>;
  reference_source?: string;
}
export interface RunRecord {
  id: string;
  room_id: string;
  name: string;
  start_date: string;
  end_date: string | null;
  time_zone: string;
  archived: boolean;
  captured_at: string;
  reference_source: string;
  lights: { on: number | null; off: number | null };
  zones: RunZone[];
}
export interface RunsDocument {
  schema_version: 1;
  room_id: string;
  revision: number;
  time_zone: string;
  runs: RunRecord[];
  error: string | null;
  max_runs: number;
}
export interface HistoryPoint {
  time: number;
  value: number | null;
}
export interface DailyReading {
  date: string;
  records: number;
  min: number;
  max: number;
}
export interface WindowSeries {
  entityId: string;
  points: HistoryPoint[];
  daily: DailyReading[];
}
export interface HistoryWindow {
  start: string;
  end: string;
  series: WindowSeries[];
  warnings: string[];
}
export interface HistoryRequest {
  entityIds: string[];
  start: string;
  end: string;
  timeZone: string;
  signal?: AbortSignal;
}
