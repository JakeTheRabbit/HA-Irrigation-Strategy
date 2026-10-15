import { CircleHelp } from "lucide-react";
import { Popover } from "radix-ui";
import { InfoTip } from "@/components/info-tip";
import { DETAIL_HEADINGS, type SettingDetail } from "@/lib/setting-words";
import { SETTING_COPY } from "@/lib/ste-copy";
import "./setting-help.css";

/** The "?" beside an irrigation setting. A setting with STE copy shows what it is, any warning and
 * caution, the impact of a change and the guidance; one without shows its own explanation. Opened
 * by a click or tap, not on hover: it is several paragraphs long, and a phone has no hover. Escape
 * or a click outside closes it. */
export function SettingHelp({
  label,
  param,
  detail,
}: {
  label: string;
  param: string;
  detail: SettingDetail;
}) {
  const copy = SETTING_COPY[param];
  if (copy) return <InfoTip label={label} copy={copy} code={param} />;
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
