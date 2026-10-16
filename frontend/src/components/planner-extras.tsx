import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UiTip } from "@/components/info-tip";
import { PlanningCurve } from "@/components/planning-curve";
import { WaterDelivery } from "@/components/water-delivery";
import { numeric } from "@/lib/model";
import type { SteeringProfile } from "@/lib/operator-types";
import { REFERENCE_ROWS, type Reference } from "@/lib/plan-reference";
import type { Controller } from "@/lib/types";

/** Settings › Display › Day curve in the planner: the preview day's curve and its water, read only.
 * The curve is edited with the number fields here, or by drag on Plan › Targets (today only). */
export function PlannerDayCurve({
  controller,
  zoneId,
  parameters,
}: {
  controller: Controller;
  zoneId: number;
  parameters: Record<string, number>;
}) {
  const prefix = controller.room.room.prefix;
  const on = numeric(controller.states[`number.crop_steering_${prefix}lights_on_hour`]);
  const off = numeric(controller.states[`number.crop_steering_${prefix}lights_off_hour`]);
  if (on === null || off === null || !Object.keys(parameters).length) return null;
  return (
    <div className="planner-day-curve" data-planner-day-curve>
      <PlanningCurve
        parameters={parameters}
        lightsOn={on}
        lightsOff={off}
        showEditors={false}
        description="The curve of the preview day, read only. Change it with the profile and the steering balance."
      />
      <WaterDelivery controller={controller} zoneId={zoneId} parameters={parameters} />
    </div>
  );
}

/** Settings › Display › Reference rows: climate and feed bands beside a profile, for reference only. */
export function ReferenceRows({
  profile,
  disabled,
  onChange,
}: {
  profile: SteeringProfile;
  disabled: boolean;
  onChange: (reference: Reference) => void;
}) {
  const reference = (profile.reference ?? {}) as Reference;
  const set = (key: keyof Reference, index: 0 | 1, raw: string) => {
    const band = [...(reference[key] ?? [NaN, NaN])] as [number, number];
    band[index] = raw === "" ? NaN : Number(raw);
    const next = { ...reference, [key]: band };
    if (!Number.isFinite(band[0]) && !Number.isFinite(band[1])) delete next[key];
    onChange(next);
  };
  return (
    <div className="planner-reference" data-planner-reference>
      <div className="profile-grid profile-heading">
        <strong className="label-with-tip">
          Reference only <UiTip copyKey="reference rows" />
        </strong>
        <strong>Low</strong>
        <strong>High</strong>
      </div>
      {REFERENCE_ROWS.map((row) => (
        <div className="profile-grid planner-reference-row" key={row.key}>
          <div>
            <strong>{row.label}</strong>
            <p className="muted small">Drives nothing. {row.unit === "°" ? "In the unit of the room's sensor." : `Unit: ${row.unit}.`}</p>
          </div>
          {([0, 1] as const).map((index) => (
            <div key={index}>
              <Label className="sr-only" htmlFor={`reference-${row.key}-${index}`}>
                {row.label} {index ? "high" : "low"}
              </Label>
              <Input
                id={`reference-${row.key}-${index}`}
                type="number"
                min={row.min}
                max={row.max}
                step={row.step}
                disabled={disabled}
                value={Number.isFinite(reference[row.key]?.[index]) ? reference[row.key]![index] : ""}
                onChange={(event) => set(row.key, index, event.target.value)}
              />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
