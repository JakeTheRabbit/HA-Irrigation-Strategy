import { addDays, daysBetween, validDate } from "./comparison";
import type { RunRecord } from "./comparison-types";
import type { JevStage } from "./jev";
import type { StrategyDocument } from "./operator-types";
import { stageArc } from "./stage-arc";
import type { EntityState } from "./types";

/** Today › the run strip: where the room's run is, day 1 to its last day, the phases of the grow on
 * it, and the grow plan and feed recipe that run today. Pure, so each figure is tested on its own. */

export interface RunPhase {
  /** Run days, inclusive: day 1 is the run's start date. */
  first: number;
  last: number;
  label: string;
  /** The label for a narrow screen. */
  short: string;
}
export interface RunProgress {
  name: string;
  start: string;
  /** Today's run day: 1 on the start date. */
  day: number;
  /** The run's length in days, and its last date; null when nothing sets it. */
  days: number | null;
  end: string | null;
  /** Where the length comes from: the run's own end date, the grow plan's last day, or the
   * flower length the controller reports. */
  endFrom: "run" | "plan" | "stage" | null;
  /** Days before today, and days from today to the end (today counts as left): done + left = days. */
  done: number;
  left: number | null;
  phases: RunPhase[];
  /** The phase today is in; null outside every phase. */
  phase: RunPhase | null;
  /** Where the phases come from. */
  phasesFrom: "plan" | "stage" | null;
}

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

/** The plan's schedule for the first of these zones that has one, as run days. A block's label is
 * its balance, with its profile's name when the plan has more than one profile. */
function planPhases(
  doc: Pick<StrategyDocument, "plan"> | null,
  zoneIds: readonly number[],
  start: string,
): RunPhase[] {
  const plan = doc?.plan;
  const zone = zoneIds
    .map((id) => plan?.zones.find((item) => item.zone_id === id))
    .find((item) => item && validDate(item.start_date) && item.schedule.length);
  if (!plan || !zone) return [];
  const shift = daysBetween(start, zone.start_date);
  const named = new Set(zone.schedule.map((block) => block.profile_id)).size > 1;
  return [...zone.schedule]
    .sort((a, b) => a.start_day - b.start_day)
    .map((block) => {
      const profile = plan.profiles.find((item) => item.id === block.profile_id)?.name;
      const balance = `${block.bias}% generative`;
      return {
        first: Math.max(1, block.start_day + shift),
        last: block.end_day + shift,
        label: named && profile ? `${profile}, ${balance}` : balance,
        short: `${block.bias}% G`,
      };
    })
    .filter((phase) => phase.last >= phase.first);
}

/** "flower setting (stretch)" -> "stretch", "flower bulk" -> "bulk": the word a grower uses. */
const stageWord = (name: string) => /\(([^)]+)\)/.exec(name)?.[1] ?? name.split(" ").at(-1)!;
const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** Without a plan: the controller's flower day puts the stage arc on the run, with veg before it. */
function stagePhases(stage: JevStage | null, day: number): RunPhase[] {
  if (stage?.day == null || stage.days == null) return [];
  const before = day - stage.day;
  const veg: RunPhase[] =
    before > 0 ? [{ first: 1, last: before, label: "Veg", short: "Veg" }] : [];
  return [
    ...veg,
    ...stageArc(stage.days).map((item) => ({
      first: Math.max(1, item.first + before),
      last: item.last + before,
      label: capital(item.name),
      short: capital(stageWord(item.name)),
    })),
  ].filter((phase) => phase.last >= phase.first);
}

export function runProgress(input: {
  run: RunRecord;
  today: string;
  plan: Pick<StrategyDocument, "plan"> | null;
  zoneIds: readonly number[];
  stage: JevStage | null;
}): RunProgress {
  const { run, today } = input;
  const day = daysBetween(run.start_date, today) + 1;
  const fromPlan = planPhases(input.plan, input.zoneIds, run.start_date);
  const phases = fromPlan.length ? fromPlan : stagePhases(input.stage, day);
  const days =
    run.end_date && validDate(run.end_date)
      ? daysBetween(run.start_date, run.end_date) + 1
      : phases.length
        ? Math.max(...phases.map((phase) => phase.last))
        : null;
  const done = days === null ? day - 1 : Math.min(day - 1, days);
  return {
    name: run.name,
    start: run.start_date,
    day,
    days,
    end: days === null ? null : addDays(run.start_date, days - 1),
    endFrom: days === null ? null : run.end_date ? "run" : fromPlan.length ? "plan" : "stage",
    done,
    left: days === null ? null : days - done,
    phases,
    phase: phases.find((phase) => day >= phase.first && day <= phase.last) ?? null,
    phasesFrom: fromPlan.length ? "plan" : phases.length ? "stage" : null,
  };
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
