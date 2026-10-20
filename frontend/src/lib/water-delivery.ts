import { roomDurationCapEntityId } from "./model";
import type { Controller, Zone } from "./types";

export const waterParameterKeys = [
  "substrate_volume",
  "plant_count",
  "drippers_per_plant",
  "dripper_flow_rate",
  "max_shot_duration",
  "p1_initial_shot_size",
  "p1_shot_size_increment",
  "p1_maximum_shots",
  "p1_time_between_shots",
  "p2_shot_size",
  "p3_emergency_shot_size",
  "max_daily_volume",
] as const;
export type WaterParameter = (typeof waterParameterKeys)[number];
export type WaterParameters = Record<WaterParameter, number | null>;
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const positive = (value: unknown): value is number => finite(value) && value > 0;
export const positiveCount = (value: unknown): value is number =>
  positive(value) && Number.isSafeInteger(value);
const has = (object: Record<string, number>, key: string) =>
  Object.prototype.hasOwnProperty.call(object, key);

/** Local drafts win even when invalid. Never substitute another zone or invent missing sizing. */
export function waterParameters(
  controller: Controller,
  zoneId: number,
  parameters?: Record<string, number>,
  fieldOverrides: Record<string, number> = {},
): WaterParameters {
  const prefix = `number.crop_steering_${controller.room.room.prefix}`;
  const zone = controller.room.zones.find((item) => item.id === zoneId);
  const read = (key: WaterParameter): number | null => {
    if (key === "max_shot_duration") {
      // This physical limit is room-only, outside plan parameters and zone defaults.
      if (has(fieldOverrides, key)) return finite(fieldOverrides[key]) ? fieldOverrides[key] : null;
      const id = roomDurationCapEntityId(
        controller.states,
        controller.room.room,
        controller.room.settings,
      );
      if (!id) return null;
      if (has(fieldOverrides, id)) return finite(fieldOverrides[id]) ? fieldOverrides[id] : null;
      const state = controller.states[id];
      if (state) {
        const raw = state.state.trim();
        return raw && Number.isFinite(Number(raw)) ? Number(raw) : null;
      }
      const field = controller.room.settings.find((item) => item.entityId === id);
      return finite(field?.value) ? field.value : null;
    }
    const zoneEntity = `${prefix}zone_${zoneId}_${key}`,
      roomEntity = `${prefix}${key}`;
    for (const candidate of [key, zoneEntity]) {
      if (has(fieldOverrides, candidate))
        return finite(fieldOverrides[candidate]) ? fieldOverrides[candidate] : null;
    }
    const zoneExists =
      !!controller.states[zoneEntity] ||
      !!zone?.fields.some((field) => field.entityId === zoneEntity) ||
      controller.room.settings.some((field) => field.entityId === zoneEntity);
    if (!zoneExists && has(fieldOverrides, roomEntity)) {
      return finite(fieldOverrides[roomEntity]) ? fieldOverrides[roomEntity] : null;
    }
    // Explicit plan/snapshot targets are authoritative, including missing targets.
    const targetKey = ![
      "substrate_volume",
      "plant_count",
      "drippers_per_plant",
      "dripper_flow_rate",
      "max_shot_duration",
    ].includes(key);
    if (parameters !== undefined && (targetKey || has(parameters, key))) {
      return finite(parameters[key]) ? parameters[key] : null;
    }
    // Respect zone precedence even when the zone value is invalid/unavailable.
    for (const entityId of [zoneEntity, roomEntity]) {
      const entity = controller.states[entityId];
      if (entity) {
        const raw = entity.state.trim();
        return raw && Number.isFinite(Number(raw)) ? Number(raw) : null;
      }
      const field =
        zone?.fields.find((item) => item.entityId === entityId) ||
        controller.room.settings.find((item) => item.entityId === entityId);
      if (field) return finite(field.value) ? field.value : null;
    }
    return null;
  };
  return Object.fromEntries(waterParameterKeys.map((key) => [key, read(key)])) as WaterParameters;
}

export interface FlowInputs {
  plants: number | null;
  drippersPerPlant: number | null;
  flowLph: number | null;
  maxDurationS: number | null;
}
export interface Delivery {
  seconds: number;
  mlPerPlant: number;
  zoneL: number | null;
}
export interface RuntimeEstimate {
  requested: Delivery | null;
  effective: Delivery | null;
  capped: boolean;
  minimumApplied: boolean;
  rounded: boolean;
}
function flowDelivery(input: FlowInputs, seconds: number): Delivery | null {
  if (!positiveCount(input.drippersPerPlant) || !positive(input.flowLph)) return null;
  const mlPerPlant = (seconds * input.drippersPerPlant * input.flowLph) / 3.6;
  const zoneL = positiveCount(input.plants) ? (mlPerPlant * input.plants) / 1000 : null;
  if (!finite(mlPerPlant) || (zoneL !== null && !finite(zoneL))) return null;
  return { seconds, mlPerPlant, zoneL };
}
/** Controller timing: integer seconds, configured upper cap, then the five-second minimum. */
export function estimateRuntime(input: FlowInputs, seconds: number | null): RuntimeEstimate {
  const empty = {
    requested: null,
    effective: null,
    capped: false,
    minimumApplied: false,
    rounded: false,
  };
  if (!positive(seconds)) return empty;
  const requested = flowDelivery(input, seconds);
  if (!requested || !positive(input.maxDurationS) || input.maxDurationS < 5)
    return { ...empty, requested };
  const effectiveSeconds = Math.max(
    5,
    Math.min(Math.trunc(input.maxDurationS), Math.trunc(seconds)),
  );
  return {
    requested,
    effective: flowDelivery(input, effectiveSeconds),
    capped: seconds > input.maxDurationS,
    minimumApplied: seconds < 5,
    rounded: effectiveSeconds !== seconds && seconds >= 5 && seconds <= input.maxDurationS,
  };
}
export function flowInputs(parameters: WaterParameters): FlowInputs {
  return {
    plants: parameters.plant_count,
    drippersPerPlant: parameters.drippers_per_plant,
    flowLph: parameters.dripper_flow_rate,
    maxDurationS: parameters.max_shot_duration,
  };
}
export function totalSubstrateL(perPlant: number | null, plants: number | null): number | null {
  const total = positive(perPlant) && positiveCount(plants) ? perPlant * plants : null;
  return finite(total) ? total : null;
}
export function estimatePercent(
  parameters: WaterParameters,
  percent: number | null,
): RuntimeEstimate {
  const flow = flowInputs(parameters);
  const seconds =
    positive(percent) &&
    positive(parameters.substrate_volume) &&
    positiveCount(flow.drippersPerPlant) &&
    positive(flow.flowLph)
      ? ((parameters.substrate_volume * percent) / 100 / (flow.drippersPerPlant * flow.flowLph)) *
        3600
      : null;
  return estimateRuntime(flow, seconds);
}
// Matches crop-steering-engine/core.py _PARAM_BOUNDS. HA field limits can be wider.
export const coreWaterBounds = {
  p1_initial_shot_size: [0.5, 15],
  p1_shot_size_increment: [0, 5],
  p1_maximum_shots: [1, 40],
  p1_time_between_shots: [1, 120],
  p2_shot_size: [0.5, 20],
  p3_emergency_shot_size: [0.5, 15],
  max_daily_volume: [10, 2000],
} as const;
export type PhaseShotKey = "p1_initial_shot_size" | "p2_shot_size" | "p3_emergency_shot_size";
export function coreWaterValue(key: keyof typeof coreWaterBounds, configured: number | null) {
  const [min, max] = coreWaterBounds[key];
  const value = finite(configured) ? Math.max(min, Math.min(max, configured)) : null;
  return { configured, value, min, max, changed: value !== null && value !== configured };
}
export function estimatePhaseShot(parameters: WaterParameters, key: PhaseShotKey) {
  const limit = coreWaterValue(key, parameters[key]);
  const configured = estimatePercent(parameters, limit.configured);
  const controlled = estimatePercent(parameters, limit.value);
  return { limit, configured, controlled };
}
/** Conditional max-count P1 series after core parameter and runtime limits. No P2/P3 count forecast. */
export function p1WaterBudget(parameters: WaterParameters) {
  const initial = coreWaterValue("p1_initial_shot_size", parameters.p1_initial_shot_size);
  const increment = coreWaterValue("p1_shot_size_increment", parameters.p1_shot_size_increment);
  const shotsLimit = coreWaterValue("p1_maximum_shots", parameters.p1_maximum_shots);
  const spacing = coreWaterValue("p1_time_between_shots", parameters.p1_time_between_shots);
  if (
    !positiveCount(parameters.p1_maximum_shots) ||
    initial.value === null ||
    increment.value === null
  )
    return null;
  // Core allows at most40; ordinary HA controls allow at most30. Show any core clamp explicitly.
  const count = shotsLimit.value!;
  const shots = Array.from({ length: count }, (_, i) => ({
    requested: estimatePercent(parameters, initial.configured! + i * increment.configured!)
      .requested,
    effective: estimatePercent(parameters, initial.value! + i * increment.value!).effective,
  }));
  if (shots.some((shot) => !shot.effective)) return null;
  const sum = (kind: "requested" | "effective", key: "mlPerPlant" | "zoneL") => {
    const values = shots.map((shot) => shot[kind]?.[key] ?? null);
    const value = values.every(finite) ? values.reduce((a, b) => a + b, 0) : null;
    return finite(value) ? value : null;
  };
  return {
    count,
    initial,
    increment,
    shotsLimit,
    spacing,
    lastPercent: initial.configured! + (count - 1) * increment.configured!,
    coreLastPercent: initial.value + (count - 1) * increment.value,
    requestedZoneL: sum("requested", "zoneL"),
    effectiveZoneL: sum("effective", "zoneL"),
    effectiveMlPerPlant: sum("effective", "mlPerPlant"),
    minimumSpacingMinutes: spacing.value !== null ? (count - 1) * spacing.value : null,
  };
}
/** Reported daily volume / current configured count: an average, never individual plant flow. */
export function dailyWater(zone: Zone, plants: number | null) {
  const value = zone.water.value;
  const unit = zone.water.unit.trim().toLowerCase();
  const zoneL =
    finite(value) && value >= 0
      ? ["l", "litre", "litres", "liter", "liters"].includes(unit)
        ? value
        : unit === "ml"
          ? value / 1000
          : null
      : null;
  const mlPerPlant = zoneL !== null && positiveCount(plants) ? (zoneL * 1000) / plants : null;
  return {
    zoneL,
    plants: positiveCount(plants) ? plants : null,
    mlPerPlant: finite(mlPerPlant) ? mlPerPlant : null,
  };
}
