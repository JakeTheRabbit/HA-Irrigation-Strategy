/** How fast a zone is drying, from its recent recorded moisture readings. */

/** Hours of readings the Overview asks for: the sparkline and the rate's longest window. */
export const DRYBACK_WINDOW_H = 2;
/** Readings this soon after a shot are the wet-up, not the dryback. */
const SETTLE_MS = 5 * 60_000;
/** A rate over less than this is noise. */
const MIN_SPAN_MS = 10 * 60_000;

export interface Reading {
  time: number;
  value: number;
}
export interface DrybackTrend {
  /** VWC percentage points lost per hour since the last shot (negative while wetting up); null
   * when there is too little to measure, with `reason` saying why. */
  rate: number | null;
  reason: string | null;
  /** Every reading of the window, oldest first, for the sparkline. */
  recent: Reading[];
}

/**
 * Least-squares slope of the readings since the last shot settled, within the last
 * `DRYBACK_WINDOW_H` hours. Recorder history only has changes, so the value held at the window's
 * start is carried in, and the live reading closes the window.
 */
export function drybackTrend(
  history: { time: string; value: number }[],
  lastShot: string | null,
  live: number | null,
  now: number,
): DrybackTrend {
  const start = now - DRYBACK_WINDOW_H * 3_600_000;
  const all = history
    .map((point) => ({ time: Date.parse(point.time), value: point.value }))
    .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value))
    .filter((point) => point.time <= now)
    .sort((a, b) => a.time - b.time);
  const window = (from: number) => {
    const held = all.filter((point) => point.time <= from).at(-1);
    const inside = all.filter((point) => point.time > from);
    const points = held ? [{ time: from, value: held.value }, ...inside] : inside;
    if (live !== null && Number.isFinite(live) && (points.at(-1)?.time ?? -Infinity) < now)
      points.push({ time: now, value: live });
    return points;
  };
  const recent = window(start);
  const shot = lastShot ? Date.parse(lastShot) : NaN;
  const from = Number.isFinite(shot) ? Math.max(start, shot + SETTLE_MS) : start;
  const measured = window(from);
  if (measured.length < 2 || !all.length)
    return { rate: null, reason: "No moisture history for this zone yet.", recent };
  if (now - from < MIN_SPAN_MS) {
    const minutes = Math.max(0, Math.round((now - shot) / 60_000));
    return {
      rate: null,
      reason: `The last shot was ${minutes} minute${minutes === 1 ? "" : "s"} ago: too soon to measure the dryback.`,
      recent,
    };
  }
  const hours = measured.map((point) => (point.time - from) / 3_600_000);
  const mx = hours.reduce((sum, x) => sum + x, 0) / hours.length;
  const my = measured.reduce((sum, point) => sum + point.value, 0) / measured.length;
  let sxx = 0,
    sxy = 0;
  measured.forEach((point, i) => {
    sxx += (hours[i] - mx) ** 2;
    sxy += (hours[i] - mx) * (point.value - my);
  });
  if (sxx === 0) return { rate: null, reason: "No moisture history for this zone yet.", recent };
  // -0 would print as "-0": a flat line is 0.
  return { rate: -(sxy / sxx) || 0, reason: null, recent };
}

/** Share of the zone's daily water limit used today, 0-100+; null without a limit. */
export function budgetShare(used: number | null, limit: number | null): number | null {
  return used === null || limit === null || !(limit > 0) ? null : (used / limit) * 100;
}
