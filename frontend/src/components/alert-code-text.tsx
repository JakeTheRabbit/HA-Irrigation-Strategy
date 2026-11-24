import { Fragment } from "react";

const CODE_RE = /\b(CS-\d{3})\b/g;

/** Extracts every unique `CS-xxx` code referenced in a message. */
export function extractAlertCodes(text: string): string[] {
  const found = text.match(CODE_RE);
  return found ? [...new Set(found)] : [];
}

/** Renders fault/warning copy with any `CS-xxx` code linked directly to Settings › Help. */
export function AlertCodeText({ text }: { text: string }) {
  const parts = text.split(CODE_RE);
  if (parts.length === 1) return <>{text}</>;
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <a
            key={`${part}-${index}`}
            href={`#/settings/help?code=${encodeURIComponent(part)}`}
            className="alert-code-link"
            title={`Look up ${part} in Help`}
            onClick={(event) => event.stopPropagation()}
          >
            {part}
          </a>
        ) : (
          <Fragment key={index}>{part}</Fragment>
        ),
      )}
    </>
  );
}
