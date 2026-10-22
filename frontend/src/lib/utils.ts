import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
/** The local calendar day of `at` as seen from `now`: "" for today, "Yesterday", else "Fri 26 Sep". */
export function dayWord(at: number, now: number): string {
  const midnight = (ms: number) => new Date(ms).setHours(0, 0, 0, 0);
  const days = Math.round((midnight(now) - midnight(at)) / 86_400_000);
  if (days === 0) return "";
  if (days === 1) return "Yesterday";
  return new Date(at).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}
/** Readable text for anything a catch block can receive. Home Assistant rejects
 * service calls with plain objects, which String() renders as "[object Object]". */
export function errorText(e: unknown): string {
  // hass.callApi rejects with HttpError: its message is only "Response error: 400/500".
  // The response body carries the service's explanation, including setup safety blockers.
  if (e && typeof e === "object") {
    const body = (e as { body?: unknown }).body;
    if (body && typeof body === "object") {
      const message = (body as { message?: unknown }).message;
      if (typeof message === "string" && message.trim()) return message;
    }
  }
  if (e instanceof Error) return e.message;
  if (e === null || e === undefined) return "Unknown error";
  if (typeof e === "string") return e;
  if (typeof e === "object") {
    const record = e as Record<string, unknown>;
    for (const key of ["message", "detail", "error"]) {
      const value = record[key];
      if (typeof value === "string" && value) return value;
    }
    try {
      return JSON.stringify(e) ?? "Request failed";
    } catch {
      return "Request failed";
    }
  }
  return String(e);
}

/** Whether an entity's state reads `want`: a finite number within half its step (the precision
 * Home Assistant keeps), or within 1e-6 where the step is unknown. */
export function sameValue(state: string | undefined, want: number, step?: number): boolean {
  const value = state === undefined || state.trim() === "" ? NaN : Number(state);
  return Number.isFinite(value) && Number.isFinite(want) && Math.abs(value - want) <= Math.max(1e-6, (step ?? 0) / 2);
}
