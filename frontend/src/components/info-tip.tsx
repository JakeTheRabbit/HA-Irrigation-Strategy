import { CircleHelp } from "lucide-react";
import { Popover } from "radix-ui";
import type { ReactNode } from "react";
import { UI_COPY, type SteCopy, type UiCopyKey } from "@/lib/ste-copy";
import "./setting-help.css";

/** Puts each value in place of the next `{x}` of a text. */
export function fillCopy(text: string, values: readonly (string | number)[] = []): string {
  let next = 0;
  return text.replace(/\{x\}/g, (slot) => (next < values.length ? String(values[next++]) : slot));
}

/** One safety notice: "WARNING: ..." (a risk to a person) or "CAUTION: ..." (a risk to the plants
 * or the equipment), with its type in bold. */
function Notice({ kind, text }: { kind: "warning" | "caution"; text: string }) {
  const body = text.replace(/^(WARNING|CAUTION):\s*/, "");
  return (
    <p className={`info-tip-notice is-${kind}`} role="note">
      <strong>{kind === "warning" ? "WARNING" : "CAUTION"}:</strong> {body}
    </p>
  );
}

/** The "?" beside a setting or a control: what it is, then any warning and caution, then the
 * impact of a change and the guidance. Opened by a click, a tap, or Enter or Space on the focused
 * button, not on hover: it is several sentences long, and a phone has no hover. Escape or a click
 * outside closes it. */
export function InfoTip({
  label,
  copy,
  code,
  values,
  children,
}: {
  label: string;
  copy: SteCopy;
  /** The setting key, shown small beside the name. */
  code?: string;
  /** The values for the `{x}` slots of the copy. */
  values?: readonly (string | number)[];
  /** More content after the copy. */
  children?: ReactNode;
}) {
  const fill = (text: string) => fillCopy(text, values);
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          className="setting-help-trigger info-tip-trigger"
          aria-label={`About ${label}`}
        >
          <CircleHelp size={15} aria-hidden="true" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        {/* Long enough to scroll on a short screen: keyboard-focusable so arrow keys can scroll it. */}
        <Popover.Content
          className="setting-help info-tip"
          aria-label={label}
          tabIndex={0}
          side="bottom"
          align="start"
          sideOffset={6}
          collisionPadding={12}
        >
          <div className="setting-help-head">
            <strong>{label}</strong>
            {code && <code>{code}</code>}
          </div>
          <p className="info-tip-what">{fill(copy.tooltip)}</p>
          {copy.warning && <Notice kind="warning" text={fill(copy.warning)} />}
          {copy.caution && <Notice kind="caution" text={fill(copy.caution)} />}
          {(copy.impact || copy.guidance) && (
            <dl>
              {copy.impact && (
                <div>
                  <dt>Impact:</dt>
                  <dd>{fill(copy.impact)}</dd>
                </div>
              )}
              {copy.guidance && (
                <div>
                  <dt>Guidance:</dt>
                  <dd>{fill(copy.guidance)}</dd>
                </div>
              )}
            </dl>
          )}
          {children}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** The "?" of a dashboard control, from its entry in the STE copy. */
export function UiTip({
  copyKey,
  label,
  values,
}: {
  copyKey: UiCopyKey;
  /** The name to show when it is not the copy's own label. */
  label?: string;
  values?: readonly (string | number)[];
}) {
  const copy = UI_COPY[copyKey];
  return <InfoTip label={label ?? fillCopy(copy.label, values)} copy={copy} values={values} />;
}
