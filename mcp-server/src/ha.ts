import { v2Answer } from "./schemas.js";

// `code`: the API v2 error code of a refused answer (stale_revision, guard_refused, ...); `data`:
// what the service answered with it (a preset's `applied` rows, written or not).
export class SafeError extends Error {
  constructor(
    message: string,
    readonly code?: string,
    readonly data?: unknown,
  ) {
    super(message);
  }
}
// Every Crop Steering service this process may call. Nothing that moves hardware (intent_submit,
// pump_*, calibration_*) is here.
export const SERVICES = [
  "setup_read",
  "setup_save",
  "strategy_get",
  "strategy_preview",
  "strategy_save",
  "runs_get",
  "journal_query",
  "timeline_get",
  "timeline_summary",
  "history_changes",
  "supply_get",
  "system_status_get",
  "alert_rule_list",
  "timer_program_list",
  "timer_program_preview",
  "alert_rule_preview",
  "timer_program_set",
  "alert_rule_set",
  "preset_apply",
  "copy_config",
  "probe_offset_set",
  "supply_save",
] as const;
export type Service = (typeof SERVICES)[number];
const services = new Set<Service>(SERVICES);
// The writes, gated by CROP_STEERING_ALLOW_WRITES. The last four also dry-run with `preview: true`,
// which is not gated.
const writes = new Set<Service>([
  "setup_save",
  "strategy_save",
  "timer_program_set",
  "alert_rule_set",
  "preset_apply",
  "copy_config",
  "probe_offset_set",
  "supply_save",
]);
export interface Config {
  url: string;
  token: string;
  writes: boolean;
  timeoutMs: number;
}
export function configFromEnv(env: NodeJS.ProcessEnv): Config {
  let url: URL;
  try {
    url = new URL(env.HA_URL || "");
  } catch {
    throw new SafeError("Set HA_URL to the Home Assistant http(s) origin.");
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== "/"
  )
    throw new SafeError(
      "HA_URL must be an http(s) origin without credentials, path, query, or fragment.",
    );
  const token = env.HA_TOKEN?.trim();
  if (!token || /[\r\n]/.test(token))
    throw new SafeError("Set HA_TOKEN to a Home Assistant access token.");
  const timeoutMs = Number(env.HA_TIMEOUT_MS ?? "10000");
  if (!Number.isInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 60000)
    throw new SafeError("HA_TIMEOUT_MS must be 100..60000.");
  return {
    url: url.origin,
    token,
    timeoutMs,
    writes: env.CROP_STEERING_ALLOW_WRITES === "true",
  };
}
export class HaClient {
  constructor(readonly config: Config) {}
  redact(text: string) {
    return text.split(this.config.token).join("[REDACTED]");
  }
  private async request(
    path: string,
    data?: unknown,
    allowMissing = false,
  ): Promise<unknown> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.config.timeoutMs);
    try {
      const body = data === undefined ? undefined : JSON.stringify(data);
      if (body && Buffer.byteLength(body) > 262144)
        throw new SafeError("Request exceeds the 256 KiB limit.");
      const response = await fetch(this.config.url + "/api/" + path, {
        method: body === undefined ? "GET" : "POST",
        headers: {
          Authorization: `Bearer ${this.config.token}`,
          "Content-Type": "application/json",
        },
        body,
        redirect: "error",
        signal: controller.signal,
      });
      if (allowMissing && response.status === 404) {
        await response.body?.cancel();
        return null;
      }
      const reader = response.body?.getReader();
      if (!reader)
        throw new SafeError("Home Assistant returned an empty response.");
      const chunks: Uint8Array[] = [];
      let size = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 8 * 1024 * 1024) {
          await reader.cancel();
          throw new SafeError("Home Assistant response exceeds 8 MiB.");
        }
        chunks.push(value);
      }
      const text = Buffer.concat(chunks).toString("utf8");
      let result: unknown;
      try {
        result = JSON.parse(text);
      } catch {
        throw new SafeError(
          "Home Assistant returned invalid JSON. Check its URL and integration version.",
        );
      }
      if (!response.ok) {
        if (response.status === 401 || response.status === 403)
          throw new SafeError(
            "Home Assistant authentication failed or this operation requires an administrator.",
          );
        const message =
          result &&
          typeof result === "object" &&
          "message" in result &&
          typeof result.message === "string"
            ? this.redact(result.message).slice(0, 600)
            : "Request rejected";
        throw new SafeError(
          `Home Assistant HTTP ${response.status}: ${message}`,
        );
      }
      return result;
    } catch (error) {
      if (error instanceof SafeError) throw error;
      throw new SafeError(
        controller.signal.aborted
          ? "Home Assistant request timed out. Do not assume a write failed; read back before a new proposal."
          : "Home Assistant connection failed. Redirects are rejected; check HA_URL, connectivity, and TLS.",
      );
    } finally {
      clearTimeout(timeout);
    }
  }
  async service(
    service: Service,
    data: Record<string, unknown> = {},
  ): Promise<unknown> {
    if (!services.has(service))
      throw new SafeError("Unsupported Crop Steering service.");
    if (writes.has(service) && data.preview !== true && !this.config.writes)
      throw new SafeError(
        "Writes are disabled. Set CROP_STEERING_ALLOW_WRITES=true and restart to allow reviewed configuration saves.",
      );
    const result = await this.request(
      `services/crop_steering/${service}?return_response`,
      data,
    );
    if (
      !result ||
      typeof result !== "object" ||
      !("service_response" in result)
    )
      throw new SafeError(
        "The updated Crop Steering response API is required.",
      );
    return result.service_response;
  }
  // An API v2 read (custom_components/crop_steering/api_v2.py): asks with `api: 2` and answers
  // the envelope's `data`; `ok: false` is an error carrying its code and message.
  async read(
    service: Service,
    data: Record<string, unknown> = {},
  ): Promise<unknown> {
    const answer = v2Answer.safeParse(
      await this.service(service, { ...data, api: 2 }),
    );
    if (!answer.success)
      throw new SafeError(
        `Unsupported Crop Steering ${service} response. Update the integration to one that answers API v2.`,
      );
    if (!answer.data.ok) {
      const error = answer.data.error;
      throw new SafeError(
        error
          ? `${error.code}: ${this.redact(error.message).slice(0, 600)}`
          : `Home Assistant refused ${service}.`,
        error?.code,
        answer.data.data,
      );
    }
    return answer.data.data;
  }
  async state(entity: string): Promise<Record<string, unknown> | null> {
    if (!/^[a-z_]+\.[a-z0-9_]+$/.test(entity))
      throw new SafeError("Invalid mapped entity ID.");
    const result = await this.request(
      `states/${encodeURIComponent(entity)}`,
      undefined,
      true,
    );
    if (result === null) return null;
    if (
      !result ||
      typeof result !== "object" ||
      Array.isArray(result) ||
      !("entity_id" in result) ||
      result.entity_id !== entity
    )
      throw new SafeError("Home Assistant returned a different entity.");
    return result as Record<string, unknown>;
  }
}
