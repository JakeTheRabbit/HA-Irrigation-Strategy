import { Fragment, type ReactNode } from "react";
import { errorCodes } from "@/lib/error-codes";

const CODE_RE = /\b(CS-\d{3})\b/g;
const byCode = new Map(errorCodes.map((entry) => [entry.code, entry]));

/** Extracts every unique `CS-xxx` code referenced in a message. */
export function extractAlertCodes(text: string): string[] {
  const found = text.match(CODE_RE);
  return found ? [...new Set(found)] : [];
}

/** The hover text of a code: its title, what it means and what it does to watering, from the
 * same catalog as Help (docs/error-codes.json). */
export function codeTooltip(code: string): string {
  const entry = byCode.get(code);
  if (!entry) return `${code}: not in this version's code list. Click to open the code list.`;
  return `${code} · ${entry.title}\n\n${entry.meaning}\n\nWatering: ${entry.watering}\n\nClick for causes and fixes in the code list.`;
}

/** A code that says what it means on hover and opens it in Help › Alert codes on click. */
export function CodeLink({ code, className, children }: { code: string; className?: string; children?: ReactNode }) {
  return (
    <a
      href={`#/settings/help?code=${encodeURIComponent(code)}`}
      className={className ? `alert-code-link ${className}` : "alert-code-link"}
      title={codeTooltip(code)}
      data-code={code}
      onClick={(event) => event.stopPropagation()}
    >
      {children ?? code}
    </a>
  );
}

/** Renders fault/warning copy with any `CS-xxx` code linked directly to Settings › Help. */
export function AlertCodeText({ text }: { text: string }) {
  const parts = text.split(CODE_RE);
  if (parts.length === 1) return <>{text}</>;
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? <CodeLink key={`${part}-${index}`} code={part} /> : <Fragment key={index}>{part}</Fragment>,
      )}
    </>
  );
}
