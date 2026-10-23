import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { calendarDays, formatDateTime } from "./clock";
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
/** The calendar day of `at` as seen from `now`, on Home Assistant's calendar (lib/clock.ts): "" for
 * today, "Yesterday", else "Fri 26 Sep". */
export function dayWord(at: number, now: number): string {
  const days = calendarDays(at, now);
  if (days === 0) return "";
  if (days === 1) return "Yesterday";
  return formatDateTime(at, { weekday: "short", day: "numeric", month: "short" });
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

/** A Home Assistant state that holds no reading: missing, blank, "unknown", "unavailable" or
 * "none", in any case. The integration's own test (`_DEAD` in health.py, stock.py and
 * zone_status.py); every page asks this one, so an entity is never live on one page and missing on
 * another. */
export function unreadableState(state: string | null | undefined): boolean {
  const text = state?.trim().toLowerCase() ?? "";
  return !text || ["unknown", "unavailable", "none"].includes(text);
}

/** A number to at most `digits` decimals, without trailing zeros: 1.50 → "1.5", 2.00 → "2". */
export function trimNumber(value: number, digits = 2): string {
  return String(Number(value.toFixed(digits)));
}
