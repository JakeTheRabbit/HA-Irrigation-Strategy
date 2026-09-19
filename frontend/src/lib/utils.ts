import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
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
