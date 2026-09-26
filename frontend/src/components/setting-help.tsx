import { CircleHelp } from "lucide-react";
import { Popover } from "radix-ui";
import { DETAIL_HEADINGS, type SettingDetail } from "@/lib/setting-words";
import "./setting-help.css";

/** The "?" beside an irrigation setting: what it is, when it acts, what it affects and what the
 * Athena Handbook says. Opened by a click or tap, not on hover: it is several paragraphs long,
 * and a phone has no hover. Escape or a click outside closes it. */
export function SettingHelp({
  label,
  param,
  detail,
}: {
  label: string;
  param: string;
  detail: SettingDetail;
}) {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className="setting-help-trigger" aria-label={`About ${label}`}>
          <CircleHelp size={15} aria-hidden="true" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        {/* Long enough to scroll on a short screen: keyboard-focusable so arrow keys can scroll it. */}
        <Popover.Content
          className="setting-help"
          aria-label={label}
          tabIndex={0}
          side="bottom"
          align="start"
          sideOffset={6}
          collisionPadding={12}
        >
          <div className="setting-help-head">
            <strong>{label}</strong>
            <code>{param}</code>
          </div>
          <dl>
            {DETAIL_HEADINGS.filter(([key]) => detail[key]).map(([key, heading]) => (
              <div key={key}>
                <dt>{heading}</dt>
                <dd>{detail[key]}</dd>
              </div>
            ))}
          </dl>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
