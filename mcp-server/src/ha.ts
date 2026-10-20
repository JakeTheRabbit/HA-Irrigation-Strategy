export class SafeError extends Error {}
export type Service =
  | "setup_read"
  | "setup_save"
  | "strategy_get"
  | "strategy_preview"
  | "strategy_save"
  | "runs_get";
const services = new Set<Service>([
  "setup_read",
  "setup_save",
  "strategy_get",
  "strategy_preview",
  "strategy_save",
  "runs_get",
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
    if (service.endsWith("_save") && !this.config.writes)
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
