import { addDays, daysBetween } from "./comparison";
import type { DailyReading } from "./comparison-types";

/** History › Compare runs: a run by grow week, and where two runs differ most. A grow week is seven
 * days counted from the run's start date. Pure, so each figure is tested on its own. */

export interface RunWeek {
  /** 1 for the run's first seven days. */
  week: number;
  first: string;
  last: string;
  /** Today falls in it: the week is still running. */
  current: boolean;
  /** The week's typical day: the median of its daily lows, and of its daily highs. */
  moisture: [number, number] | null;
  poreEc: [number, number] | null;
  /** Litres per plant a day, averaged over the week's recorded grow-days before today. */
  water: number | null;
  /** Days of the week with moisture readings, and days elapsed. */
  recorded: number;
  days: number;
}

const median = (values: number[]) => {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = sorted.length / 2;
  return sorted.length % 2 ? sorted[Math.floor(middle)] : (sorted[middle - 1] + sorted[middle]) / 2;
};
const typical = (rows: DailyReading[]): [number, number] | null =>
  rows.length ? [median(rows.map((row) => row.min)), median(rows.map((row) => row.max))] : null;

export function runWeeks(input: {
  /** The run's start date, and the last date it covers (its end, or today). */
  start: string;
  last: string;
  today: string;
  vwc: readonly DailyReading[];
  ec: readonly DailyReading[];
  /** Litres per grow-day, for the whole zone. */
  water: ReadonlyMap<string, number>;
  plants: number | null;
}): RunWeek[] {
  const { start, last, today, plants } = input;
  const span = daysBetween(start, last);
  if (!(span >= 0)) return [];
  const weeks: RunWeek[] = [];
  for (let index = 0; index * 7 <= span; index++) {
    const first = addDays(start, index * 7);
    const end = addDays(first, 6) < last ? addDays(first, 6) : last;
    const inside = (row: { date: string }) => row.date >= first && row.date <= end;
    const vwc = input.vwc.filter(inside);
    const litres = [...input.water]
      .filter(([day]) => day >= first && day <= end && day < today)
      .map(([, value]) => value);
    weeks.push({
      week: index + 1,
      first,
      last: end,
      current: today >= first && today <= addDays(first, 6) && today <= last,
      moisture: typical(vwc),
      poreEc: typical(input.ec.filter(inside)),
      water:
        litres.length && plants && plants > 0
          ? litres.reduce((sum, value) => sum + value, 0) / litres.length / plants
          : null,
      recorded: new Set(vwc.map((row) => row.date)).size,
      days: daysBetween(first, end) + 1,
    });
  }
  return weeks;
}

export type RunMetric = "moisture" | "poreEc" | "water";
export interface RunDifference {
  week: number;
  metric: RunMetric;
  /** This run's figure less the other's: points of moisture, mS/cm of pore EC, a share of water. */
  by: number;
  /** How big against what a grower notices (3 points, 0.5 mS/cm, a fifth of the water): 1 is
   * just worth saying. */
  score: number;
  text: string;
}
/** What counts as a difference worth saying. */
export const NOTICE = { moisture: 3, poreEc: 0.5, water: 0.2 } as const;

const round = (value: number, digits = 1) => {
  const factor = 10 ** digits;
  return String(Math.round(value * factor) / factor);
};
const mid = (range: [number, number]) => (range[0] + range[1]) / 2;
const span = (range: [number, number], digits: number) =>
  `${round(range[0], digits)}–${round(range[1], digits)}`;

/** The weeks where this run and the other differ most, biggest first; nothing under NOTICE. */
export function biggestDifferences(
  current: readonly RunWeek[],
  other: readonly RunWeek[],
  limit = 3,
): RunDifference[] {
  const found: RunDifference[] = [];
  for (const week of current) {
    const then = other.find((item) => item.week === week.week);
    if (!then) continue;
    if (week.moisture && then.moisture) {
      const by = mid(week.moisture) - mid(then.moisture);
      found.push({
        week: week.week,
        metric: "moisture",
        by,
        score: Math.abs(by) / NOTICE.moisture,
        text: `Week ${week.week}: moisture ${span(week.moisture, 0)} % against ${span(then.moisture, 0)} %, ${round(Math.abs(by))} points ${by > 0 ? "wetter" : "drier"}`,
      });
    }
    if (week.poreEc && then.poreEc) {
      const by = mid(week.poreEc) - mid(then.poreEc);
      found.push({
        week: week.week,
        metric: "poreEc",
        by,
        score: Math.abs(by) / NOTICE.poreEc,
        text: `Week ${week.week}: pore EC ${span(week.poreEc, 1)} against ${span(then.poreEc, 1)}, ${round(Math.abs(by))} ${by > 0 ? "higher" : "lower"}`,
      });
    }
    if (week.water !== null && then.water !== null && then.water > 0) {
      const by = week.water / then.water - 1;
      found.push({
        week: week.week,
        metric: "water",
        by,
        score: Math.abs(by) / NOTICE.water,
        text: `Week ${week.week}: ${round(week.water, 2)} L per plant a day against ${round(then.water, 2)}, ${round(Math.abs(by) * 100, 0)} % ${by > 0 ? "more" : "less"}`,
      });
    }
  }
  return found
    .filter((item) => item.score >= 1)
    .sort((a, b) => b.score - a.score || a.week - b.week)
    .slice(0, limit);
}
