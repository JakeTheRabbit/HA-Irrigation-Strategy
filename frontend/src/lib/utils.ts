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
