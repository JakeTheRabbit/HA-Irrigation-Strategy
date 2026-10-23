import type { PillTone } from "@/components/mini-visuals";
import type { States } from "./types";

/** The tank level the controller reads from the level mapped in Rooms and setup, with its minimum and
 * overfill marks (docs/USER_GUIDE.md, "Reservoir minimum"). Published only for a room with a tank
 * level mapped. */
export const tankLevelId = (prefix: string) => `sensor.crop_steering_${prefix}tank_level`;

/** The marks the controller holds by (tank_level.py), as it publishes them on its tank level:
 * watering held at or below `minimum` until the level reads `release`; a fill stopped at or over
 * `over` until it reads `overRelease`. Null where the controller does not say (one from before it
 * published the release and full marks): the dashboard keeps no copy of its numbers. */
export interface TankMarks {
  minimum: number | null;
  release: number | null;
  over: number | null;
  overRelease: number | null;
}
const mark = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
export function tankMarks(attrs: Record<string, unknown>): TankMarks {
  return {
    minimum: mark(attrs.minimum_pct),
    release: mark(attrs.release_pct),
    over: mark(attrs.over_pct),
    overRelease: mark(attrs.over_release_pct),
  };
}

export type ReservoirState = "unmapped" | "ok" | "held" | "unknown" | "over";
export interface ReservoirView {
  state: ReservoirState;
  level: number | null;
  minimum: number | null;
  marks: TankMarks;
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
  const marks = tankMarks(attrs);
  const { minimum } = marks;
  const heldAt = minimum === null ? "at its minimum" : `at ${minimum} %`;
  const startsAgain =
    marks.release === null ? "once it reads above it" : `at ${marks.release} %`;
  const raw = entity && entity.state.trim() ? Number(entity.state) : NaN;
  const level = Number.isFinite(raw) ? raw : null;
  const litresPerPct = finite(attrs.litres_per_pct);
  const aboveMinimumL =
    level !== null && minimum !== null && litresPerPct !== null && litresPerPct > 0
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
    marks,
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
      "Map the distance sensor or the low float of the tank in Rooms and setup. The controller then holds shots before the pump draws air.",
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
        ? `The tank is at or below its ${minimum === null ? "" : `${minimum} % `}minimum. Watering starts again by itself ${startsAgain}. Refill the tank.`
        : "The tank's low float reads low. Watering starts again by itself once it no longer does. Refill the tank.",
      "CS-901",
    );
  if (attrs.over_full === true)
    return view(
      "over",
      "Filling stopped: over the full mark",
      "warn",
      `The tank reads at or over ${marks.over === null ? "its full mark" : `${marks.over} % of its full mark`}, so no fill valve opens until it reads ${marks.overRelease === null ? "less again" : `${marks.overRelease} % or less`}. The shots continue.`,
      "CS-904",
    );
  return view(
    "ok",
    "Watering allowed",
    "on",
    aboveMinimumL === null
      ? `Watering is held ${heldAt} and starts again ${startsAgain}. The litres each 1 % holds are learned from the shots; until then no shot waits ahead of the minimum.`
      : `Watering is held ${heldAt} and starts again ${startsAgain}. A shot that would take the tank to its minimum waits, and a refill is asked for one round of shots ahead.`,
  );
}
