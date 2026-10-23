import { useCallback, useEffect, useRef, useState } from "react";
import type { OperatorAction } from "./operator-types";
import type { CsEvent, JournalPage } from "./parity-types";
import type { Controller } from "./types";

/** The integration release that ships every v2 service below. */
export const PARITY_MIN_VERSION = "3.18.0";

/** Exactly the services the parity backend ships (backend plan, Tasks 5–34). */
export const PARITY_ACTIONS = [
  "journal_query",
  "timeline_get",
  "timeline_summary",
  "history_changes",
  "history_revert",
  "supply_get",
  "supply_save",
  "pump_precheck",
  "pump_prime",
  "pump_stop",
  "pump_calibrate",
  "pump_calibration_commit",
  "calibration_start",
  "calibration_capture",
  "calibration_status",
  "calibration_commit",
  "calibration_revert",
  "calibration_abandon",
  "probe_offset_set",
  "alert_rule_set",
  "alert_rule_delete",
  "alert_rule_test",
  "alert_rule_preview",
  "alert_rule_list",
  "alert_ack",
  "timer_program_set",
  "timer_program_delete",
  "timer_program_list",
  "timer_program_preview",
  "timer_skip",
  "preset_list",
  "preset_save",
  "preset_apply",
  "preset_delete",
  "copy_config",
  "dashboard_create",
  "dashboard_list",
  "system_status_get",
] as const;
export type ParityAction = (typeof PARITY_ACTIONS)[number];
export const isParityAction = (action: string): action is ParityAction =>
  (PARITY_ACTIONS as readonly string[]).includes(action);

export type V2ErrorCode = "stale_revision" | "invalid" | "forbidden" | "guard_refused" | "unavailable" | "unknown";
export type V2Outcome<T> =
  | {
      kind: "ok";
      data: T;
      revision: number | null;
      readback: { status: "verified" | "unverified"; at: string | null };
      eventIds: string[];
    }
  | { kind: "missing" }
  /** `data`: the answer a refusal still carries (a copy's `applied` rows, written and refused). */
  | { kind: "error"; code: V2ErrorCode; message: string; currentRevision?: number; data?: unknown };

const KNOWN_CODES: readonly string[] = ["stale_revision", "invalid", "forbidden", "guard_refused", "unavailable"];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const messageOf = (error: unknown) =>
  error instanceof Error ? error.message : isRecord(error) && typeof error.message === "string" ? error.message : "";

/** An older integration that lacks the service: Home Assistant's "not found" (websocket code, or
 * its "Service/Action crop_steering.x not found" words), client.ts's answer when a service gives
 * no response, and an older schema refusing the `api` key. */
export function isMissingService(error: unknown): boolean {
  const code = isRecord(error) ? error.code : undefined;
  if (code === "not_found" || code === "service_not_found") return true;
  const message = messageOf(error);
  return (
    /\b(Service|Action) crop_steering\.\w+ not found/i.test(message) ||
    message.includes("needs the updated Crop Steering integration") ||
    /extra keys not allowed @ data\['api'\]/.test(message)
  );
}

/** The thrown error's v2 code, where Home Assistant's own words say it. */
function thrownCode(error: unknown): V2ErrorCode {
  const code = isRecord(error) ? error.code : undefined;
  if (code === "unauthorized" || /administrator/i.test(messageOf(error))) return "forbidden";
  if (code === "invalid_format") return "invalid";
  return "unknown";
}

/** Calls one service with `api: 2` and reads its envelope. Never throws: an older backend is
 * `missing`, anything else an `error`. The panel never sends `client` or `proposal_token`. */
export async function callV2<T>(
  controller: Pick<Controller, "operator">,
  action: ParityAction | OperatorAction,
  data: Record<string, unknown>,
): Promise<V2Outcome<T>> {
  const { client: _client, proposal_token: _token, ...rest } = data;
  let answer: unknown;
  try {
    answer = await controller.operator<unknown>(action as OperatorAction, { ...rest, api: 2 });
  } catch (error) {
    if (isMissingService(error)) return { kind: "missing" };
    return { kind: "error", code: thrownCode(error), message: messageOf(error) || "Home Assistant request failed." };
  }
  if (!isRecord(answer) || answer.api !== 2) return { kind: "missing" };
  if (answer.ok !== true) {
    const error = isRecord(answer.error) ? answer.error : {};
    const code = typeof error.code === "string" && KNOWN_CODES.includes(error.code) ? (error.code as V2ErrorCode) : "unknown";
    return {
      kind: "error",
      code,
      message: typeof error.message === "string" ? error.message : "The integration refused this.",
      ...(typeof error.current_revision === "number" ? { currentRevision: error.current_revision } : {}),
      ...(answer.data !== undefined ? { data: answer.data } : {}),
    };
  }
  const readback = isRecord(answer.readback) ? answer.readback : {};
  return {
    kind: "ok",
    data: answer.data as T,
    revision: typeof answer.revision === "number" ? answer.revision : null,
    readback: {
      status: readback.status === "verified" ? "verified" : "unverified",
      at: typeof readback.at === "string" ? readback.at : null,
    },
    eventIds: Array.isArray(answer.event_ids) ? answer.event_ids.filter((id): id is string => typeof id === "string") : [],
  };
}

/** Reads a room's Journal from `since`, 500 events a call, until the cursor runs out, a page comes
 * back empty, or `max` events are read. */
export async function pagedQuery(
  controller: Pick<Controller, "operator">,
  q: { room_id: string; since: string; until?: string; kinds?: string[]; zones?: number[] },
  max = 5000,
): Promise<V2Outcome<{ events: CsEvent[] }>> {
  const events: CsEvent[] = [];
  let cursor: string | null = null;
  for (;;) {
    const page: V2Outcome<JournalPage> = await callV2<JournalPage>(controller, "journal_query", {
      ...q,
      limit: 500,
      ...(cursor ? { cursor } : {}),
    });
    if (page.kind !== "ok") return page;
    events.push(...page.data.events);
    cursor = page.data.cursor;
    if (!cursor || !page.data.events.length || events.length >= max)
      return { ...page, data: { events: events.slice(0, max) } };
  }
}

export type ParityState = "idle" | "loading" | "ready" | "missing" | "error";

/** One v2 read for a page part: `missing` on an older backend (render `NeedsIntegration`), and
 * `idle` (nothing asked) while `data` is null. Re-reads when `deps` change or on `reload()`;
 * `deps` are compared by their JSON. */
export function useParity<T>(
  controller: Pick<Controller, "operator">,
  action: ParityAction,
  data: Record<string, unknown> | null,
  deps: unknown[],
): { state: ParityState; data: T | null; error: string | null; reload(): void } {
  const [result, setResult] = useState<{ state: ParityState; data: T | null; error: string | null }>(() => ({
    state: data ? "loading" : "idle",
    data: null,
    error: null,
  }));
  const [tick, setTick] = useState(0);
  const latest = useRef({ controller, data });
  latest.current = { controller, data };
  const key = JSON.stringify([data === null, deps]);
  useEffect(() => {
    const { controller, data } = latest.current;
    if (!data) {
      setResult({ state: "idle", data: null, error: null });
      return;
    }
    let current = true;
    setResult((previous) => ({ ...previous, state: "loading", error: null }));
    void callV2<T>(controller, action, data).then((outcome) => {
      if (!current) return;
      if (outcome.kind === "ok") setResult({ state: "ready", data: outcome.data, error: null });
      else if (outcome.kind === "missing") setResult({ state: "missing", data: null, error: null });
      else setResult({ state: "error", data: null, error: outcome.message });
    });
    return () => {
      current = false;
    };
  }, [action, tick, key]);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { ...result, reload };
}
