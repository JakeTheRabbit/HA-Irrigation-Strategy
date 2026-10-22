/**
 * The pore-EC band around a zone's EC target, where no growth-stage band applies: the ratios of
 * pore EC to its target within which the controller leaves a shot's size alone (the engine's
 * ec_adjust, from the room's substrate profile; 80-100 % of the target on the generic one). The
 * controller's heartbeat publishes them (`pore_ec_neutral`). The day timeline and the planning
 * gauges both judge with this one band; a controller that does not publish it gets none.
 */
import type { States } from "./types";

export type EcRatios = [number, number];

/** The room's pore-EC ratios from the controller's heartbeat, or null when it does not publish them. */
export function poreEcNeutral(states: States, prefix: string): EcRatios | null {
  const value = states[`sensor.crop_steering_${prefix}ai_heartbeat`]?.attributes.pore_ec_neutral;
  return Array.isArray(value) &&
    value.length === 2 &&
    value.every((ratio) => typeof ratio === "number" && Number.isFinite(ratio) && ratio > 0) &&
    value[0] <= value[1]
    ? [value[0], value[1]]
    : null;
}

/** The band around `target` (mS/cm), or null without ratios or a target. */
export function ecTargetBand(
  ratios: EcRatios | null,
  target: number | null | undefined,
): [number, number] | null {
  return ratios && typeof target === "number" && Number.isFinite(target) && target > 0
    ? [target * ratios[0], target * ratios[1]]
    : null;
}
