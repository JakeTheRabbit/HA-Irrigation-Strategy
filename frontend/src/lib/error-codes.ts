// The error codes shown on Help & tools. docs/error-codes.json is the one list: the controller app
// and the integration print these codes, and docs/ERROR_CODES.md is written from the same file.
import catalog from "../../../docs/error-codes.json";

export type Severity = "critical" | "warning" | "info";

export interface ErrorCode {
  code: string;
  title: string;
  source: "notification" | "repairs";
  severity: Severity;
  meaning: string;
  watering: string;
  causes: string[];
  fixes: string[];
}

export interface ErrorCodeGroup {
  prefix: string;
  name: string;
  detail: string;
}

export const errorCodes = catalog.codes as ErrorCode[];
export const errorCodeGroups = catalog.groups as ErrorCodeGroup[];

export const severityLabel: Record<Severity, string> = {
  critical: "Critical",
  warning: "Warning",
  info: "Information",
};

/** "CS-101", "cs101", "101" all name one code, and so does a line pasted from a notification or a
 * Repairs card ("Zone 2: moisture reading hasn't changed (CS-101)", "Code CS-101."): its code, not
 * the other codes its words mention. Anything else is not a code. */
export function asCode(query: string): string | null {
  const match = /\bcs-?(\d{3})\b/i.exec(query) ?? /^\s*(\d{3})\s*$/.exec(query);
  return match ? `CS-${match[1]}` : null;
}

/** The codes a search matches: a code by its number, or every word found somewhere in the entry. */
export function findErrorCodes(query: string, codes: ErrorCode[] = errorCodes): ErrorCode[] {
  const code = asCode(query);
  if (code) return codes.filter((entry) => entry.code === code);
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return codes;
  return codes.filter((entry) => {
    const text = [
      entry.code,
      entry.title,
      entry.meaning,
      entry.watering,
      ...entry.causes,
      ...entry.fixes,
    ]
      .join(" ")
      .toLowerCase();
    return words.every((word) => text.includes(word));
  });
}

/** The code a link asks for: #/help?code=CS-101. */
export function codeFromHash(hash: string): string | null {
  const query = hash.split("?")[1];
  return query ? asCode(new URLSearchParams(query).get("code") ?? "") : null;
}
