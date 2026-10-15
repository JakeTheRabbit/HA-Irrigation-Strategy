import { athenaDryback } from "./day-chart";

/** The grow by stage, as the controller's Jev steers it: the owner's stage arc (the slab guide,
 * chosen 26 Sep 2026; addons/f2_control/f2_control/jev/doctrine.py STAGE_ARC and stage_intent),
 * with Athena's relative overnight dryback for each stage beside it. Day 1 is the first day of
 * 12/12. Pure, so the arc and today's place in it are tested on their own. */

export type StageSteering = "vegetative" | "generative" | "ripening";
export interface Stage {
  name: string;
  /** Flower days, inclusive. */
  first: number;
  last: number;
  steering: StageSteering;
  /** Root-zone (pore) EC, mS/cm. */
  poreEc: [number, number];
  /** The guide's overnight dryback, in points of true water content. */
  drybackPoints: [number, number];
  /** Athena's overnight dryback, relative to the day's peak (%): what the P3 dryback target is. */
  athena: [number, number];
  /** Runoff, % of the water fed. */
  runoff: [number, number];
  /** When the guide moves on to the next stage. */
  moveOn: string;
}

/** The slab guide's nominal flower, and its finish: "normally the final 10-14 days". */
export const NOMINAL_FLOWER_DAYS = 56;
export const FINISH_DAYS = 14;

const SETTING_LAST = 21;
const BULK_FIRST = 22;

/** The arc for a flower of `days` days. A longer cultivar stays in the bulk until its last
 * FINISH_DAYS, as the controller does: the guide moves on when ripening signals dominate, not on a
 * date. */
export function stageArc(days = NOMINAL_FLOWER_DAYS): Stage[] {
  const length = Number.isInteger(days) && days >= 1 ? days : NOMINAL_FLOWER_DAYS;
  const finish = Math.max(length - FINISH_DAYS + 1, BULK_FIRST);
  const stage = (
    name: string,
    first: number,
    last: number,
    steering: StageSteering,
    poreEc: [number, number],
    drybackPoints: [number, number],
    runoff: [number, number],
    moveOn: string,
  ): Stage => ({
    name,
    first,
    last,
    steering,
    poreEc,
    drybackPoints,
    athena: athenaDryback(name)!,
    runoff,
    moveOn,
  });
  return [
    stage(
      "flower setting",
      1,
      Math.min(SETTING_LAST, length),
      "generative",
      [5, 10],
      [15, 25],
      [1, 7],
      "vertical stretch has clearly slowed or stopped",
    ),
    stage(
      "flower bulk",
      BULK_FIRST,
      finish - 1,
      "vegetative",
      [3.5, 6],
      [10, 15],
      [8, 16],
      "flower expansion slows and ripening signals dominate",
    ),
    stage(
      "finish",
      finish,
      length,
      "ripening",
      [3, 4],
      [20, 25],
      [1, 7],
      "cultivar-specific maturity (trichomes on mid-cola calyxes)",
    ),
  ].filter((item) => item.first <= item.last);
}

/** Grow weeks of the arc: week 1 is days 1-7. */
export const weekOf = (day: number) => Math.floor((day - 1) / 7) + 1;

export interface StageNow {
  stage: Stage;
  day: number;
  week: number;
  /** The next stage, the flower day it starts and that day's date (epoch ms, local midnight);
   * null in the last stage. */
  next: { stage: Stage; day: number; date: number } | null;
}
/** Where flower day `day` sits on the arc, seen at `now`; null outside flower. */
export function stageNow(arc: readonly Stage[], day: number | null, now: number): StageNow | null {
  if (day === null || !Number.isInteger(day)) return null;
  const index = arc.findIndex((stage) => day >= stage.first && day <= stage.last);
  if (index < 0) return null;
  const following = arc[index + 1];
  const date = new Date(now);
  date.setHours(0, 0, 0, 0);
  if (following) date.setDate(date.getDate() + following.first - day);
  return {
    stage: arc[index],
    day,
    week: weekOf(day),
    next: following ? { stage: following, day: following.first, date: date.getTime() } : null,
  };
}
