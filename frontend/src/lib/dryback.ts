/** Recent recorded moisture readings for a sparkline, and the share of the daily water limit used. */

export interface Reading {
  time: number;
  value: number;
}
const parse = (history: { time: string; value: number }[], now: number): Reading[] =>
  history
    .map((point) => ({ time: Date.parse(point.time), value: point.value }))
    .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value))
    .filter((point) => point.time <= now)
    .sort((a, b) => a.time - b.time);

/** The readings after `from`, oldest first. Recorder history only has changes, so the value held
 * at `from` is carried in, and the live reading closes the window. */
function since(all: Reading[], from: number, live: number | null, now: number): Reading[] {
  const held = all.filter((point) => point.time <= from).at(-1);
  const inside = all.filter((point) => point.time > from);
  const points = held ? [{ time: from, value: held.value }, ...inside] : inside;
  if (live !== null && Number.isFinite(live) && (points.at(-1)?.time ?? -Infinity) < now)
    points.push({ time: now, value: live });
  return points;
}

/** A sensor's readings over the last `hours`, for a sparkline. */
export function recentReadings(
  history: { time: string; value: number }[],
  hours: number,
  live: number | null,
  now: number,
): Reading[] {
  return since(parse(history, now), now - hours * 3_600_000, live, now);
}

/** Share of the zone's daily water limit used today, 0-100+; null without a limit. */
export function budgetShare(used: number | null, limit: number | null): number | null {
  return used === null || limit === null || !(limit > 0) ? null : (used / limit) * 100;
}
