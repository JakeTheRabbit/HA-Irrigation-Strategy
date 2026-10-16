import generated from "./generated/arcs.json";

/** The grow by stage, as the controller steers it: the doctrine pack's default stage arc, read from
 * frontend/src/lib/generated/arcs.json (written by doctrine/tools/build_doctrine.py from the same rows
 * the controller's brain/doctrine.py stage_rows reads). Day 1 is the first day of 12/12. Pure, so the arc
 * and today's place in it are tested on their own. */

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
  /** Runoff, % of the water fed. */
  runoff: [number, number];
  /** When the guide moves on to the next stage. */
  moveOn: string;
}

/** A row of the generated arc: flower days are a day pair, "last N days" for the finish, or null
 * for the veg row. */
interface ArcRow {
  stage: string;
  flower_days: [number, number] | string | null;
  steering: StageSteering;
  dryback_points: [number, number];
  pore_ec: [number, number];
  runoff_pct: [number, number];
  move_on_when: string;
}
const pack = generated as unknown as { default_arc: string; arcs: Record<string, { stages: ArcRow[] }> };
/** The default arc's rows, as the pack has them. */
export const ARC_ROWS: readonly ArcRow[] = pack.arcs[pack.default_arc].stages;

/** The slab guide's nominal flower, and its finish: "normally the final 10-14 days". */
export const NOMINAL_FLOWER_DAYS = 56;
export const FINISH_DAYS = 14;

/** The arc for a flower of `days` days. A longer cultivar stays in the stage before the finish until
 * its last FINISH_DAYS, as the controller does: the guide moves on when ripening signals dominate,
 * not on a date. */
export function stageArc(days = NOMINAL_FLOWER_DAYS, rows: readonly ArcRow[] = ARC_ROWS): Stage[] {
  const length = Number.isInteger(days) && days >= 1 ? days : NOMINAL_FLOWER_DAYS;
  const flower = rows.filter((row) => row.flower_days !== null);
  const middle = flower.slice(0, -1);
  const pair = (row: ArcRow) => row.flower_days as [number, number];
  const finish = Math.max(length - FINISH_DAYS + 1, middle.length ? pair(middle.at(-1)!)[0] : 1);
  const stage = (row: ArcRow, first: number, last: number): Stage => ({
    name: row.stage,
    first,
    last,
    steering: row.steering,
    poreEc: row.pore_ec,
    drybackPoints: row.dryback_points,
    runoff: row.runoff_pct,
    moveOn: row.move_on_when,
  });
  return [
    ...middle.map((row, index) =>
      index === middle.length - 1
        ? stage(row, pair(row)[0], finish - 1)
        : stage(row, pair(row)[0], Math.min(pair(row)[1], length)),
    ),
    stage(flower.at(-1)!, finish, length),
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
