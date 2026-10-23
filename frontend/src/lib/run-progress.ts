import { validDate } from "./comparison";
import type { RunRecord } from "./comparison-types";
import type { EntityState } from "./types";

/** The room's run today (History › Grows, Compare) and the feed recipe the room doses today (the
 * room page). Pure, so each is tested on its own. */

/** The room's run today: not archived, started, and not ended before today; the latest start wins. */
export function currentRun(runs: readonly RunRecord[], today: string): RunRecord | null {
  return (
    runs
      .filter(
        (run) =>
          !run.archived &&
          validDate(run.start_date) &&
          run.start_date <= today &&
          (!run.end_date || run.end_date >= today),
      )
      .sort((a, b) => b.start_date.localeCompare(a.start_date))[0] ?? null
  );
}

export interface FeedToday {
  recipe: string;
  /** The feed EC the recipe mixes to, mS/cm; null when it declares none. */
  ec: number | null;
  week: number | null;
  weeks: number | null;
  /** "schedule", "held" (picked by hand over the schedule), "hand" or "batch". */
  source: string;
}
/** The feed recipe the room doses today, from `sensor.crop_steering_<prefix>dosing_config`: its
 * `feed` (the feed schedule's pick), else the batch recipe's own name; null without either. */
export function feedToday(entity: EntityState | undefined): FeedToday | null {
  const attributes = entity?.attributes ?? {};
  const feed = (attributes.feed ?? {}) as Record<string, unknown>;
  const batch = (attributes.batch ?? {}) as Record<string, unknown>;
  const count = (value: unknown) =>
    typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
  const recipe =
    typeof feed.recipe === "string" && feed.recipe.trim()
      ? feed.recipe.trim()
      : typeof batch.name === "string" && batch.name.trim()
        ? batch.name.trim()
        : null;
  if (!recipe) return null;
  const scheduled = typeof feed.recipe === "string" && feed.recipe.trim() !== "";
  return {
    recipe,
    ec: scheduled && typeof feed.ec === "number" && Number.isFinite(feed.ec) ? feed.ec : null,
    week: scheduled ? count(feed.week) : null,
    weeks: scheduled ? count(feed.weeks) : null,
    source: scheduled && typeof feed.source === "string" ? feed.source : "batch",
  };
}
