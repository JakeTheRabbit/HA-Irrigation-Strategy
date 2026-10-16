import { useState } from "react";
import { Check, Eye, EyeOff } from "lucide-react";
import { ReviewDialog } from "@/components/dashboard";
import { InfoTip } from "@/components/info-tip";
import { DISPLAY_ROWS, displayEntityId, type DisplayOptions, type DisplayRow } from "@/lib/display";
import type { Controller } from "@/lib/types";
import "./display-settings.css";

const ON_OFF = [
  { value: false, label: "Off", icon: EyeOff },
  { value: true, label: "On", icon: Eye },
] as const;

/** Settings › Display: which extra panels the dashboard shows in this room. Each row is off until
 * someone turns it on; a change is reviewed, then saved for everyone who opens the room. A row kept
 * in a switch of its own (the Hardware panel) writes that switch, and only an administrator may. */
export function DisplaySettings({ controller }: { controller: Controller }) {
  const display = controller.room.display;
  const prefix = controller.room.room.prefix;
  const [pending, setPending] = useState<{ row: DisplayRow; value: boolean | string } | null>(null);
  const connected = ["live", "demo"].includes(controller.connection);
  const words = (row: DisplayRow, value: boolean | string) =>
    row.choice?.find((c) => c.value === value)?.label ?? (value ? "On" : "Off");
  const valueOf = (row: DisplayRow): boolean | string | null => {
    if (!row.entity) return display.options[row.key as keyof DisplayOptions];
    const state = controller.states[row.entity(prefix)]?.state;
    return state === "on" ? true : state === "off" ? false : null;
  };
  const writable = (row: DisplayRow) =>
    connected &&
    (row.entity
      ? valueOf(row) !== null && controller.admin !== false
      : display.available);
  const groups = [...new Set(DISPLAY_ROWS.map((row) => row.group))];
  const entityId = pending?.row.entity
    ? pending.row.entity(prefix)
    : `${displayEntityId(prefix)}.${pending?.row.key}`;
  return (
    <div className="display-settings" data-display-settings>
      {!display.available && (
        <p className="small muted">This needs the updated Crop Steering integration.</p>
      )}
      {groups.map((group) => (
        <div key={group} className="display-group">
          <h3>{group}</h3>
          {DISPLAY_ROWS.filter((row) => row.group === group).map((row) => {
            const current = valueOf(row);
            const options = row.choice
              ? row.choice.map((c) => ({ value: c.value, label: c.label, icon: undefined }))
              : ON_OFF;
            return (
              <div key={row.key} className="display-row" data-display-option={row.key}>
                <span className="label-with-tip">
                  <span id={`display-${row.key}`}>{row.label}</span>
                  <InfoTip label={row.label} copy={row.copy} />
                </span>
                <div
                  className="theme-options display-options"
                  role="group"
                  aria-labelledby={`display-${row.key}`}
                >
                  {options.map((option) => (
                    <button
                      key={String(option.value)}
                      className={current === option.value ? "chosen" : ""}
                      aria-pressed={current === option.value}
                      disabled={!writable(row)}
                      onClick={() =>
                        current !== option.value && setPending({ row, value: option.value })
                      }
                    >
                      {option.icon && <option.icon size={18} />}
                      <span>{option.label}</span>
                      {current === option.value && <Check size={16} />}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ))}
      <ReviewDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        controller={controller}
        title="Review the display option"
        items={
          pending
            ? [
                {
                  change: { entityId, value: pending.value },
                  label: pending.row.label,
                  before: words(pending.row, valueOf(pending.row) ?? false),
                  after: words(pending.row, pending.value),
                },
              ]
            : []
        }
        note="Changes what the dashboard shows for everyone who opens this room. It does not change watering, a setpoint or hardware."
        run={
          pending?.row.entity
            ? undefined
            : async () => {
                if (!pending) return;
                await controller.operator("display_save", {
                  expected_revision: display.revision,
                  options: { [pending.row.key]: pending.value } as Partial<DisplayOptions>,
                });
              }
        }
      />
    </div>
  );
}
