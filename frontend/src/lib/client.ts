import { loadHistoryWindow } from "./comparison-history";
import type { HistoryRequest } from "./comparison-types";
import type { OperatorAction } from "./operator-types";
import type { Change, EntityState, RoomView, Series, States, WriteResult } from "./types";
import { numeric, validateChange } from "./model";

export interface HassSession {
  callApi: <T>(method: string, path: string, data?: unknown) => Promise<T>;
  callService: (domain: string, service: string, data: Record<string, unknown>) => Promise<unknown>;
}
export function findSession(base?: string): HassSession | undefined {
  if (typeof window === "undefined") return;
  for (const target of [window.parent, window]) {
    try {
      if (base && new URL(base).origin !== target.location.origin) continue;
      const root = target.document.querySelector("home-assistant") as
        (Element & { hass?: HassSession }) | null;
      const session = root?.hass;
      if (session) return session;
    } catch {
      /* Cross-origin parent; still inspect this window. */
    }
  }
}
export function haSessionToken(): string {
  try {
    const value = JSON.parse(localStorage.getItem("hassTokens") || "null");
    return typeof value?.access_token === "string" ? value.access_token : "";
  } catch {
    return "";
  }
}
export function asStates(payload: unknown): States {
  if (!Array.isArray(payload))
    throw new Error("Home Assistant returned an invalid states response.");
  return Object.fromEntries(
    payload
      .filter(
        (e): e is EntityState =>
          !!e &&
          typeof e.entity_id === "string" &&
          typeof e.state === "string" &&
          !!e.attributes &&
          typeof e.attributes === "object",
      )
      .map((e) => [e.entity_id, e]),
  );
}
export class HaClient {
  private controller = new AbortController();
  readonly base: string;
  constructor(
    base: string,
    private token = "",
    private session?: HassSession,
    private timeoutMs = 12_000,
  ) {
    const url = new URL(base || window.location.origin);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password)
      throw new Error("Enter a Home Assistant HTTP or HTTPS URL without embedded credentials.");
    this.base = url.origin;
  }
  dispose() {
    this.controller.abort();
  }
  private async request<T>(
    method: string,
    path: string,
    data?: unknown,
    service?: { domain: string; action: string },
    externalSignal?: AbortSignal,
  ): Promise<T> {
    if (externalSignal?.aborted) throw new DOMException("History request cancelled.", "AbortError");
    if (this.controller.signal.aborted) throw new Error("Connection was closed.");
    const abort = new AbortController();
    const cancel = () => abort.abort();
    this.controller.signal.addEventListener("abort", cancel, { once: true });
    externalSignal?.addEventListener("abort", cancel, { once: true });
    let timeout: ReturnType<typeof setTimeout> | undefined;
    let onAbort: (() => void) | undefined;
    const deadline = new Promise<never>((_, reject) => {
      onAbort = () =>
        reject(
          new Error(
            this.controller.signal.aborted
              ? "Connection was closed."
              : externalSignal?.aborted
                ? "History request cancelled."
                : "Home Assistant request timed out.",
          ),
        );
      abort.signal.addEventListener("abort", onAbort, { once: true });
      timeout = setTimeout(() => abort.abort(), this.timeoutMs);
    });
    try {
      const operation = this.session
        ? service
          ? this.session.callService(
              service.domain,
              service.action,
              data as Record<string, unknown>,
            )
          : this.session.callApi<T>(method, path, data)
        : fetch(`${this.base}/api/${path}`, {
            method,
            headers: {
              ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
              "Content-Type": "application/json",
            },
            signal: abort.signal,
            ...(data === undefined ? {} : { body: JSON.stringify(data) }),
          }).then(async (response) => {
            if (!response.ok) {
              const detail = await response.json().catch(() => null);
              throw new Error(
                response.status === 401 || response.status === 403
                  ? "Home Assistant authentication failed or this action needs an administrator."
                  : typeof detail?.message === "string"
                    ? detail.message
                    : "Home Assistant request failed (" +
                      response.status +
                      "). Check that the integration is updated.",
              );
            }
            return response.json();
          });
      return (await Promise.race([operation, deadline])) as T;
    } finally {
      clearTimeout(timeout);
      this.controller.signal.removeEventListener("abort", cancel);
      externalSignal?.removeEventListener("abort", cancel);
      if (onAbort) abort.signal.removeEventListener("abort", onAbort);
    }
  }
  async operator<T>(action: OperatorAction, data: Record<string, unknown>): Promise<T> {
    const allowed = [
      "runs_get",
      "runs_save",
      "runs_archive",
      "runs_import",
      "strategy_get",
      "strategy_save",
      "strategy_preview",
      "strategy_activate",
      "strategy_disarm",
      "setup_read",
      "setup_create",
      "setup_save",
      "setup_remove",
    ];
    if (!allowed.includes(action)) throw new Error("Unsupported workspace action.");
    const response = await this.request<{ service_response?: T }>(
      "POST",
      "services/crop_steering/" + action + "?return_response",
      data,
    );
    if (!response || response.service_response === undefined)
      throw new Error(
        "This action needs the updated Crop Steering integration. Open Setup for installation instructions.",
      );
    return response.service_response;
  }
  async states(): Promise<States> {
    return asStates(await this.request("GET", "states"));
  }
  async state(entityId: string): Promise<EntityState> {
    return this.request("GET", `states/${encodeURIComponent(entityId)}`);
  }
  async service(domain: string, action: string, data: Record<string, unknown>): Promise<void> {
    await this.request("POST", `services/${domain}/${action}`, data, {
      domain,
      action,
    });
  }
  async historyWindow(request: HistoryRequest) {
    return loadHistoryWindow(
      (path, signal) => this.request("GET", path, undefined, undefined, signal),
      request,
    );
  }
  async history(entityIds: string[], hours: number, states: States): Promise<Series[]> {
    if (!entityIds.length) return [];
    if (!Number.isFinite(hours) || hours <= 0 || hours > 168)
      throw new Error("History range must be between 0 and 168 hours.");
    const start = new Date(Date.now() - hours * 3_600_000).toISOString();
    const query = new URLSearchParams({
      filter_entity_id: entityIds.join(","),
      minimal_response: "",
      no_attributes: "",
    });
    const payload = await this.request<unknown>("GET", `history/period/${start}?${query}`);
    if (!Array.isArray(payload)) throw new Error("Home Assistant returned invalid history.");
    return entityIds.map((entityId) => {
      const rows = payload.find(
        (group: unknown) => Array.isArray(group) && group[0]?.entity_id === entityId,
      ) as EntityState[] | undefined;
      return {
        entityId,
        label: String(states[entityId]?.attributes.friendly_name || entityId),
        points: (rows || []).flatMap((row) => {
          const value = numeric(row);
          const time = row.last_changed || row.last_updated;
          return value !== null && time && Number.isFinite(Date.parse(time))
            ? [{ value, time }]
            : [];
        }),
      };
    });
  }
}

export async function applyChanges(
  client: Pick<HaClient, "service" | "state">,
  room: RoomView,
  states: States,
  changes: Change[],
  isCurrent = () => true,
): Promise<WriteResult> {
  const result: WriteResult = { applied: [], failed: [] };
  const seen = new Set<string>();
  for (const change of changes) {
    let reason = !isCurrent()
      ? "Room or connection changed; remaining changes cancelled."
      : validateChange(room, states, change);
    if (seen.has(change.entityId)) reason = "Duplicate entity in this batch.";
    seen.add(change.entityId);
    if (reason) {
      result.failed.push({ entityId: change.entityId, reason });
      continue;
    }
    try {
      const domain = change.entityId.split(".")[0];
      await client.service(
        domain,
        domain === "number"
          ? "set_value"
          : domain === "select"
            ? "select_option"
            : change.value
              ? "turn_on"
              : "turn_off",
        {
          entity_id: change.entityId,
          ...(domain === "number"
            ? { value: change.value }
            : domain === "select"
              ? { option: change.value }
              : {}),
        },
      );
      const readback = await client.state(change.entityId);
      if (!isCurrent())
        throw new Error("Room or connection changed during write; result is unconfirmed.");
      const matches =
        typeof change.value === "number"
          ? numeric(readback) !== null && Math.abs(numeric(readback)! - change.value) < 1e-6
          : readback.state ===
            (typeof change.value === "boolean" ? (change.value ? "on" : "off") : change.value);
      if (readback.entity_id !== change.entityId || !matches)
        throw new Error(
          "Readback did not confirm the requested value. Refresh and review before retrying.",
        );
      result.applied.push(change.entityId);
    } catch (error) {
      result.failed.push({
        entityId: change.entityId,
        reason: error instanceof Error ? error.message : "Write failed.",
      });
    }
  }
  return result;
}
