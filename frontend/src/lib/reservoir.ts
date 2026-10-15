import type { PillTone } from "@/components/mini-visuals";
import { BATCH_STEPS, STEP_LABELS, resultTone, resultWords, type DosingStatus } from "./dosing";
import type { States } from "./types";

/** The tank level the controller reads from the level mapped in Rooms & setup, with its minimum and
 * overfill marks (docs/USER_GUIDE.md, "Reservoir minimum"). Published only for a room with a tank
 * level mapped. */
export const tankLevelId = (prefix: string) => `sensor.crop_steering_${prefix}tank_level`;

/** The marks the controller holds by (tank_level.py): watering held at or below the minimum until
 * the level reads RELEASE_PCT; a fill stopped at or over OVER_PCT until it reads OVER_RELEASE_PCT. */
export const MINIMUM_PCT = 8;
export const RELEASE_PCT = 12;
export const OVER_PCT = 102;
export const OVER_RELEASE_PCT = 98;

export type ReservoirState = "unmapped" | "ok" | "held" | "unknown" | "over";
export interface ReservoirView {
  state: ReservoirState;
  level: number | null;
  minimum: number;
  /** Litres drawn per 1 % of level, learned from the shots; null until learned. */
  litresPerPct: number | null;
  /** About how many litres are left above the minimum; null until the litres per 1 % are learned. */
  aboveMinimumL: number | null;
  label: string;
  tone: PillTone;
  detail: string;
  code: string | null;
}

const finite = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

/** What the reservoir minimum is doing in a room, in grower words. */
export function reservoirView(states: States, prefix: string): ReservoirView {
  const entity = states[tankLevelId(prefix)];
  const attrs = entity?.attributes ?? {};
  const minimum = finite(attrs.minimum_pct) ?? MINIMUM_PCT;
  const raw = entity && entity.state.trim() ? Number(entity.state) : NaN;
  const level = Number.isFinite(raw) ? raw : null;
  const litresPerPct = finite(attrs.litres_per_pct);
  const aboveMinimumL =
    level !== null && litresPerPct !== null && litresPerPct > 0
      ? Math.max(0, (level - minimum) * litresPerPct)
      : null;
  const view = (
    state: ReservoirState,
    label: string,
    tone: PillTone,
    detail: string,
    code: string | null = null,
  ): ReservoirView => ({
    state,
    level,
    minimum,
    litresPerPct,
    aboveMinimumL,
    label,
    tone,
    detail,
    code,
  });
  if (!entity)
    return view(
      "unmapped",
      "Off: no tank level mapped",
      "neutral",
      "Map the tank's distance sensor or low float in Rooms & setup and watering is held before the pump draws air.",
    );
  if (attrs.stuck === true || level === null)
    return view(
      "unknown",
      "Watering held: tank level unknown",
      "warn",
      attrs.stuck === true
        ? "The level has not fallen while the shots drew from the tank, so the sensor looks stuck. Watering starts again by itself once it reads again."
        : "The tank level reads nothing usable. Watering starts again by itself once it reads again.",
      "CS-902",
    );
  if (attrs.below_minimum === true || attrs.low === true)
    return view(
      "held",
      "Watering held: tank at its minimum",
      "warn",
      attrs.below_minimum === true
        ? `The tank is at or below its ${minimum} % minimum. Watering starts again by itself at ${RELEASE_PCT} %. Refill the tank.`
        : "The tank's low float reads low. Watering starts again by itself once it no longer does. Refill the tank.",
      "CS-901",
    );
  if (attrs.over_full === true)
    return view(
      "over",
      "Filling stopped: over the full mark",
      "warn",
      `The tank reads at or over ${OVER_PCT} % of its full mark, so no fill valve opens until it reads ${OVER_RELEASE_PCT} % or less. Watering carries on.`,
      "CS-904",
    );
  return view(
    "ok",
    "Watering allowed",
    "on",
    aboveMinimumL === null
      ? `Watering is held at ${minimum} % and starts again at ${RELEASE_PCT} %. The litres each 1 % holds are learned from the shots; until then no shot waits ahead of the minimum.`
      : `Watering is held at ${minimum} % and starts again at ${RELEASE_PCT} %. A shot that would take the tank to its minimum waits, and a refill is asked for one round of shots ahead.`,
  );
}

/** The batch on the tank: the step running now, else how the last one ended. Null with no batch
 * dosing reported. */
export function batchLine(status: DosingStatus | null): { label: string; tone: PillTone } | null {
  if (!status) return null;
  const batch = status.batch;
  if (batch.step !== "idle") {
    const index = BATCH_STEPS.indexOf(batch.step);
    return {
      label: `Batch running: ${STEP_LABELS[batch.step]} (step ${index + 1} of ${BATCH_STEPS.length})`,
      tone: "water",
    };
  }
  if (!batch.result) return { label: "No batch made yet", tone: "neutral" };
  const ended = batch.ended_at ? new Date(batch.ended_at) : null;
  const when =
    ended && Number.isFinite(ended.getTime())
      ? ` · ${ended.toLocaleString([], { dateStyle: "short", timeStyle: "short" })}`
      : "";
  return {
    label: `Last batch: ${resultWords(batch.result)}${when}`,
    tone: resultTone(batch.result),
  };
}
