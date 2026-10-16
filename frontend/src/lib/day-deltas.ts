import { compareDays, openSeconds, reachedHour, type DayTrace, type Reading, type Shot } from "./day-timeline";

/** Settings › Display › Day deltas: today against yesterday or the typical day, at this hour since
 * lights-on, as at most three short chips under the zone's day chart. Grey unless the difference is
 * large (ISA-101): VWC 3 points, the P1 target an hour, water a quarter. */
export interface DayDelta {
  key: "vwc" | "target" | "water";
  text: string;
  abnormal: boolean;
}
export const DELTA_LIMITS = { vwc: 3, targetMinutes: 60, waterPercent: 25 };

const signed = (value: number, digits: number) =>
  `${value > 0 ? "+" : value < 0 ? "−" : "±"}${Math.abs(value).toFixed(digits)}`;

export function dayDeltas({
  points,
  shots,
  start,
  now,
  compared,
  against,
  vwc,
  target,
}: {
  /** Today's VWC readings and shots. */
  points: readonly Reading[];
  shots: readonly Shot[];
  /** Today's lights-on, and now (epoch ms). */
  start: number;
  now: number;
  /** The days compared with: yesterday, or the days of the typical day. */
  compared: readonly DayTrace[];
  against: "yesterday" | "the typical day";
  vwc: number | null;
  /** The P1 target VWC, if the zone has one. */
  target: number | null;
}): DayDelta[] {
  const hour = (now - start) / 3_600_000;
  const them = compareDays(compared, hour, vwc, target);
  if (!them || hour <= 0) return [];
  const chips: DayDelta[] = [];
  if (them.vwc !== null)
    chips.push({
      key: "vwc",
      text: `VWC ${signed(them.vwc, 1)} pp vs ${against}`,
      abnormal: Math.abs(them.vwc) >= DELTA_LIMITS.vwc,
    });
  const today =
    target === null
      ? null
      : reachedHour(
          points.map((p) => ({ time: p.time, hour: (p.time - start) / 3_600_000, value: p.value })),
          target,
        );
  if (today !== null && them.reached !== null) {
    const minutes = Math.round((today - them.reached) * 60);
    chips.push({
      key: "target",
      text:
        minutes === 0
          ? "Target at the same time"
          : `Target ${Math.abs(minutes)} min ${minutes < 0 ? "earlier" : "later"}`,
      abnormal: Math.abs(minutes) >= DELTA_LIMITS.targetMinutes,
    });
  }
  if (them.seconds > 0) {
    const percent = (openSeconds(shots, start, hour) / them.seconds - 1) * 100;
    chips.push({
      key: "water",
      text: `Water ${signed(percent, 0)}%`,
      abnormal: Math.abs(percent) >= DELTA_LIMITS.waterPercent,
    });
  }
  return chips;
}
