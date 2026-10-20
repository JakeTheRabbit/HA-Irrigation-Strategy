import { roomDurationCapEntityId } from "./model";
import type { RoomView, Setting, States } from "./types";
import type { PlanningBounds } from "./planning-curve";

export type PreviewDrafts = Record<string, { value: string }>;
export interface SetpointCurveState {
  parameters: Record<string, number>;
  lightsOn: number;
  lightsOff: number;
  mode: "Vegetative" | "Generative" | null;
}
const steeringKeys = [
  "p1_target_vwc",
  "p2_vwc_threshold",
  "p2_shot_size",
  "p1_initial_shot_size",
  "p1_shot_size_increment",
  "p1_maximum_shots",
  "p1_time_between_shots",
  "p0_maximum_wait_time",
  "p3_emergency_vwc_threshold",
  "p3_emergency_shot_size",
  "max_daily_volume",
  "field_capacity",
  "maximum_ec",
  "watchdog_hours",
];
const hardwareKeys = [
  "substrate_volume",
  "plant_count",
  "drippers_per_plant",
  "dripper_flow_rate",
  "max_shot_duration",
];
const modeKeys = ["dryback_target", "ec_target_p0", "ec_target_p1", "ec_target_p2"];
const requiredPlanKeys = [
  ...modeKeys,
  "p1_target_vwc",
  "p2_vwc_threshold",
  "p2_shot_size",
  "p1_initial_shot_size",
  "p3_emergency_vwc_threshold",
  "p3_emergency_shot_size",
];
function validPlanParameters(
  parameters: Record<string, unknown> | undefined,
): parameters is Record<string, number> {
  if (
    !parameters ||
    Array.isArray(parameters) ||
    !requiredPlanKeys.every((key) => Object.prototype.hasOwnProperty.call(parameters, key))
  )
    return false;
  if (
    !Object.entries(parameters).every(
      ([key, value]) =>
        [...steeringKeys, ...modeKeys].includes(key) &&
        typeof value === "number" &&
        Number.isFinite(value) &&
        value >= 0,
    )
  )
    return false;
  return (
    Number(parameters.p3_emergency_vwc_threshold) + 3 <= Number(parameters.p2_vwc_threshold) &&
    Number(parameters.p2_vwc_threshold) < Number(parameters.p1_target_vwc) &&
    Number(parameters.p1_target_vwc) <= 100
  );
}

export const validateSetpoint = (setting: Setting, raw: string) =>
  !raw.trim() || !Number.isFinite(Number(raw))
    ? "Enter a number."
    : Number(raw) < setting.min || Number(raw) > setting.max
      ? `Use a value between ${setting.min} and ${setting.max}.`
      : setting.step > 0 &&
          Math.abs(
            (Number(raw) - setting.min) / setting.step -
              Math.round((Number(raw) - setting.min) / setting.step),
          ) > 0.00001
        ? `Use increments of ${setting.step} from ${setting.min}.`
        : "";

/** Maps real HA fields to the current controller's canonical planning inputs.
 * Exact prefix + zone matching prevents a missing field borrowing another room.
 * Invalid local input is deliberately missing, never replaced by its saved value.
 */
export function buildSetpointPreview(
  room: RoomView,
  states: States,
  zoneId: number,
  drafts: PreviewDrafts,
) {
  const root = `crop_steering_${room.room.prefix}`;
  const fields: Record<string, Setting> = {};
  const bounds: PlanningBounds = {};
  const fieldOverrides: Record<string, number> = {};
  const issues: string[] = [];
  const readOnly = room.strategy.engaged;
  const find = (suffix: string) => {
    if (suffix === "max_shot_duration") {
      const id = roomDurationCapEntityId(states, room.room, room.settings);
      return room.settings.find((field) => field.entityId === id);
    }
    return (
      room.settings.find((field) => field.entityId === `number.${root}zone_${zoneId}_${suffix}`) ??
      room.settings.find((field) => field.entityId === `number.${root}${suffix}`)
    );
  };
  const read = (field: Setting | undefined, local: boolean): number | undefined => {
    if (!field) return undefined;
    const draft = local && !readOnly ? drafts[field.entityId] : undefined;
    if (draft) {
      const error = validateSetpoint(field, draft.value);
      if (error) {
        issues.push(`${field.label}: ${error}`);
        return undefined;
      }
      return Number(draft.value);
    }
    return field.value !== null &&
      Number.isFinite(field.value) &&
      field.value >= field.min &&
      field.value <= field.max
      ? field.value
      : undefined;
  };
  const mode = (local: boolean): SetpointCurveState["mode"] => {
    const id = `select.${root}zone_${zoneId}_steering_mode`;
    const choice = room.choices.find((item) => item.entityId === id);
    const draft = local && !readOnly ? drafts[id] : undefined;
    if (draft && !choice?.options.includes(draft.value)) {
      issues.push("Select an available zone steering mode to preview its EC and dryback targets.");
      return null;
    }
    let raw = draft?.value ?? choice?.value ?? states[id]?.state;
    if (!raw || ["unknown", "unavailable"].includes(raw))
      raw = states[`select.${root}growth_stage`]?.state;
    // The engine reads zone steering_mode, then legacy growth_stage, not room steering_mode.
    if (!raw || ["unknown", "unavailable"].includes(raw)) return null;
    if (raw.toLowerCase().startsWith("veg")) return "Vegetative";
    if (
      raw.toLowerCase().startsWith("gen") ||
      ["transition", "flowering", "fruiting", "ripening"].includes(raw.toLowerCase())
    )
      return "Generative";
    return null;
  };
  const snapshot = states[`sensor.${root}strategy_plan`];
  const planZone =
    room.strategy.valid &&
    snapshot?.attributes.room_id === room.room.id &&
    Array.isArray(snapshot.attributes.zones)
      ? (snapshot.attributes.zones.find(
          (entry: unknown) =>
            !!entry &&
            typeof entry === "object" &&
            (entry as { zone_id?: number }).zone_id === zoneId,
        ) as { status?: string; parameters?: Record<string, unknown> } | undefined)
      : undefined;
  const active =
    readOnly &&
    snapshot?.attributes.enabled === true &&
    planZone?.status === "active" &&
    validPlanParameters(planZone.parameters);
  const inherited: string[] = [];
  const build = (local: boolean): SetpointCurveState => {
    const parameters: Record<string, number> = {};
    const selectedMode = mode(local);
    const suffixes: Record<string, string> = Object.fromEntries(
      [...steeringKeys, ...hardwareKeys].map((key) => [key, key]),
    );
    if (selectedMode) {
      const short = selectedMode === "Vegetative" ? "veg" : "gen";
      suffixes.dryback_target = `${selectedMode.toLowerCase()}_dryback_target`;
      for (const phase of [0, 1, 2])
        suffixes[`ec_target_p${phase}`] = `ec_target_${short}_p${phase}`;
    }
    for (const [key, suffix] of Object.entries(suffixes)) {
      const field = find(suffix);
      const value = read(field, local);
      if (readOnly && !hardwareKeys.includes(key)) {
        if (!active || requiredPlanKeys.includes(key)) continue;
        // Optional plan omissions really fall through to live HA numbers in _zone_num.
        if (value !== undefined && planZone?.parameters?.[key] === undefined && local)
          inherited.push(field?.label ?? key);
      }
      if (value !== undefined) parameters[key] = value;
      if (local && !readOnly && field) {
        fields[key] = field;
        bounds[key] = { min: field.min, max: field.max, step: field.step };
        if (drafts[field.entityId]) fieldOverrides[field.entityId] = value ?? NaN;
      }
    }
    if (active) {
      for (const key of [...steeringKeys, ...modeKeys]) {
        const value = planZone?.parameters?.[key];
        if (typeof value === "number" && Number.isFinite(value)) parameters[key] = value;
      }
    }
    return {
      parameters,
      lightsOn: read(find("lights_on_hour"), local) ?? NaN,
      lightsOff: read(find("lights_off_hour"), local) ?? NaN,
      mode: readOnly ? null : selectedMode,
    };
  };
  const saved = build(false),
    draft = build(true);
  if (!readOnly && !draft.mode)
    issues.push(
      "Steering mode is unavailable. Mode-dependent EC and dryback targets are not plotted.",
    );
  if (readOnly && !active)
    issues.push(
      "The active plan has no valid targets for this zone. Manual fallback values are not shown as active targets.",
    );
  return {
    saved,
    draft,
    fields,
    bounds,
    fieldOverrides,
    issues: [...new Set(issues)],
    notes: inherited.length
      ? [`Optional values inherited from the controller: ${inherited.join(", ")}.`]
      : [],
    readOnly,
    source: readOnly
      ? active
        ? ("active-plan" as const)
        : ("unavailable-plan" as const)
      : ("manual" as const),
  };
}
