import { Fragment } from "react";
import { TriangleAlert } from "lucide-react";
import { Input } from "@/components/ui/input";
import { number } from "@/components/dashboard";
import { AutoBadge } from "@/components/room-controls";
import { FieldSuggestionLine, type SensorContextData } from "@/components/sensor-context";
import { SettingHelp } from "@/components/setting-help";
import { validateSetpoint } from "@/lib/setpoint-preview";
import { fieldHint, setpointMetric, setpointParam, suggestedDraft } from "@/lib/sensor-context";
import { settingWords, type SettingDetail } from "@/lib/setting-words";
import type { Setting } from "@/lib/types";
import "./setting-row.css";

/** A setting's "?": its full help where there is one, else its one line. */
function helpFor(setting: Setting, param: string | null): SettingDetail | null {
  const words = param ? settingWords(param) : undefined;
  if (words?.detail) return words.detail;
  const what = words?.help || setting.description;
  return what ? { what, when: "" } : null;
}

/** One controller setting as a table row: its name and "?", its input, and Jev's range or Auto
 * where either moves it; under it, only what matters while editing it (the value now, an error,
 * what the probe recorded, a suggestion or a warning). Inputs keep the `setting-<entity id>` id. */
export function SettingRow({
  setting,
  label,
  unit,
  draft,
  prefix,
  sensor,
  learnedPeak,
  chip,
  auto,
  readOnly,
  disabled,
  onEdit,
}: {
  setting: Setting;
  label: string;
  unit: string;
  draft?: { value: string; original: number | string | null };
  prefix: string;
  /** The recorded probe behaviour behind the hints; none without. */
  sensor?: SensorContextData | null;
  learnedPeak?: number | null;
  chip?: string | null;
  auto?: boolean;
  /** Shown, not edited: an armed grow plan owns it. */
  readOnly?: boolean;
  disabled: boolean;
  onEdit: (setting: Setting, value: string) => void;
}) {
  const error = draft ? validateSetpoint(setting, draft.value) : "";
  const stale = draft && draft.original !== setting.value;
  const param = setpointParam(setting.entityId, prefix);
  const metric = param ? setpointMetric(param) : null;
  const typed = !draft
    ? setting.value
    : draft.value.trim() && Number.isFinite(Number(draft.value))
      ? Number(draft.value)
      : null;
  const hint =
    sensor && param && metric
      ? fieldHint(param, typed, sensor[metric].stats, sensor.hours, learnedPeak)
      : null;
  const suggested = hint?.suggestion ? suggestedDraft(hint.suggestion.value, setting) : null;
  const help = helpFor(setting, param);
  const note =
    error ||
    (stale
      ? `The controller now reports ${number(setting.value)}. Review before applying.`
      : draft
        ? `Currently ${number(setting.value)} ${unit}`
        : "");
  const context = draft || hint?.suggestion || hint?.warning;
  return (
    <Fragment>
      <tr className={draft ? "is-draft" : undefined} data-setting={param ?? undefined}>
        <th scope="row">
          <label htmlFor={`setting-${setting.entityId}`}>{label}</label>
          {help && param && <SettingHelp label={label} param={param} detail={help} />}
          {draft && <span className="draft-dot" title="Unsaved draft" />}
        </th>
        <td className="targets-input">
          {readOnly ? (
            <strong>{number(setting.value)}</strong>
          ) : (
            <Input
              id={`setting-${setting.entityId}`}
              type="number"
              min={setting.min}
              max={setting.max}
              step={setting.step}
              title={`Allowed ${setting.min}–${setting.max}${setting.unit ? ` ${setting.unit}` : ""}, in steps of ${setting.step}`}
              value={draft?.value ?? setting.value ?? ""}
              placeholder={setting.value === null ? "Unavailable" : undefined}
              aria-invalid={Boolean(error)}
              aria-describedby={context ? `note-${setting.entityId}` : undefined}
              disabled={disabled}
              onChange={(event) => onEdit(setting, event.target.value)}
            />
          )}
          <span className="targets-unit">{unit}</span>
        </td>
        <td className="targets-chip">
          {chip && <span className="jev-chip">{chip}</span>}
          {auto && <AutoBadge />}
        </td>
      </tr>
      {context && (
        <tr className="targets-note" id={`note-${setting.entityId}`}>
          <td colSpan={3}>
            {note && <p className={error ? "field-error" : undefined}>{note}</p>}
            {auto && draft && (
              <p className="setting-auto-hint">
                Managed automatically: a manual edit is overwritten.
              </p>
            )}
            {draft && hint?.text && (
              <p>
                {setting.zoneId === undefined && sensor ? `${sensor.zoneName} probe · ` : ""}
                {hint.text}
              </p>
            )}
            {hint?.suggestion && (
              <FieldSuggestionLine
                suggestion={hint.suggestion}
                zoneName={setting.zoneId === undefined ? sensor?.zoneName : undefined}
                draftValue={suggested}
                unit={setting.unit}
                action="in draft"
                disabled={disabled || typed === suggested}
                onUse={(value) => onEdit(setting, String(value))}
              />
            )}
            {hint?.warning && (
              <p className="setting-advisory">
                <TriangleAlert size={13} aria-hidden="true" />
                <span>
                  {hint.warning[0].toUpperCase() + hint.warning.slice(1)}. Advisory only; you can
                  still save this value.
                </span>
              </p>
            )}
          </td>
        </tr>
      )}
    </Fragment>
  );
}
