import type { LogEvent } from "./types";

/** The room's setpoint change log (crop_steering.setpoint_log_get): every write to one of its
 * settings, oldest first, with who made it. Read only. */
export type SetpointWriter = "operator" | "learner" | "brain" | "safety" | "home_assistant";
export interface SetpointChange {
  at: string;
  entity_id: string;
  field: string;
  zone: number | null;
  old: number | null;
  new: number;
  who: SetpointWriter;
}
export interface SetpointLogDocument {
  schema_version: number;
  room_id: string;
  changes: SetpointChange[];
  error: string | null;
  max_changes: number;
}

export const WRITER_WORDS: Record<SetpointWriter, string> = {
  operator: "By hand",
  learner: "Auto setpoints",
  brain: "AI assistant",
  safety: "Put back for safety",
  home_assistant: "Home Assistant",
};

/** The id prefix that marks a change log row on the Timeline. */
export const CHANGE_ID = "setpoint-change:";

/** Each change as a Timeline record: "By hand: p2 vwc threshold 40.4 → 41.4". */
export function changeEvents(doc: SetpointLogDocument | null): LogEvent[] {
  return (doc?.changes ?? []).map((change, index) => ({
    id: `${CHANGE_ID}${index}`,
    timestamp: change.at,
    message: `${WRITER_WORDS[change.who] ?? change.who}: ${change.field.replaceAll("_", " ")} ${
      change.old ?? "—"
    } → ${change.new}`,
    type: "info",
    ...(change.zone === null ? {} : { zoneId: change.zone }),
  }));
}
