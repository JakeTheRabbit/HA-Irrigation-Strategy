import { addDays, ageAt, dateInZone, daysBetween, validDate } from "./comparison";
import { buildPlanningCurve, type PlanningPhaseId, type PlanningPoint } from "./planning-curve";

export interface ComparisonTargetPoint {
  time: number;
  age: number;
  value: number | null;
}
export interface ComparisonTarget {
  vwc: ComparisonTargetPoint[];
  ec: ComparisonTargetPoint[];
  floor: ComparisonTargetPoint[];
  warnings: string[];
}
export interface ComparisonTargetInput {
  parameters: Record<string, number>;
  lightsOn: number;
  lightsOff: number;
  start: number;
  end: number;
  now: number;
  timeZone: string;
  runStartDate: string;
}
const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const ids: PlanningPhaseId[] = ["P0", "P1", "P2", "P3"];

/** Repeated configured references, never historical applied targets or recorder samples.
 * Lines are split between cycles/phases and clipped at now. Local light boundaries follow
 * civil time; wait/cadence durations use elapsed minutes across clock changes.
 */
export function buildComparisonTarget(input: ComparisonTargetInput): ComparisonTarget {
  const result: ComparisonTarget = { vwc: [], ec: [], floor: [], warnings: [] };
  const warn = (message: string) => {
    if (!result.warnings.includes(message)) result.warnings.push(message);
  };
  const { parameters, lightsOn, lightsOff, timeZone, runStartDate, start } = input;
  const end = Math.min(input.end, input.now);
  const empty = (message: string) => {
    warn(message);
    return result;
  };
  if (
    ![start, input.end, input.now].every(Number.isFinite) ||
    end <= start ||
    !validDate(runStartDate)
  )
    return empty("The configured reference needs a valid elapsed range and run start date.");
  if (
    ![lightsOn, lightsOff].every((hour) => Number.isFinite(hour) && hour >= 0 && hour < 24) ||
    lightsOn === lightsOff
  )
    return empty(
      "The configured reference needs readable, distinct lights-on and lights-off hours.",
    );
  const plan = buildPlanningCurve(parameters, lightsOn, lightsOff);
  plan.warnings.forEach(warn);
  const finiteRange = (key: string, max: number) =>
    Number.isFinite(parameters[key]) && parameters[key] >= 0 && parameters[key] <= max;
  const p0Known = finiteRange("p0_maximum_wait_time", 1440);
  const cadenceKnown =
    p0Known &&
    finiteRange("p1_time_between_shots", 1440) &&
    finiteRange("p1_maximum_shots", 200) &&
    Number.isInteger(parameters.p1_maximum_shots);
  const known = [p0Known, cadenceKnown, cadenceKnown, true];
  if (!cadenceKnown)
    warn("P0/P1 timing is incomplete. Only reference segments with known timing are shown.");
  if (plan.missing.length)
    warn(`Missing reference targets are not drawn: ${plan.missing.join(", ")}.`);
  let first: string, last: string;
  let clock: Intl.DateTimeFormat;
  try {
    first = dateInZone(start, timeZone);
    last = dateInZone(end - 1, timeZone);
    if (daysBetween(first, last) > 365)
      return empty("Configured references are limited to 366 calendar days.");
    clock = new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      fractionalSecondDigits: 3,
      hourCycle: "h23",
    });
  } catch {
    return empty("The configured reference has an invalid date or time zone.");
  }
  const instantCache = new Map<string, number | null>();
  // Treat local date-time fields as a naive UTC instant solely to solve the zone offset.
  const wall = (time: number) => {
    const parts = Object.fromEntries(
      clock.formatToParts(time).map((part) => [part.type, part.value]),
    );
    return Date.parse(
      `${parts.year.padStart(4, "0")}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}.${parts.fractionalSecond}Z`,
    );
  };
  const localInstant = (date: string, hour: number): number | null => {
    const key = `${date}/${hour}`;
    if (instantCache.has(key)) return instantCache.get(key)!;
    const target = Date.parse(date + "T00:00:00Z") + Math.round(hour * HOUR);
    const offsets = new Set(
      [-36, 0, 36].map((hours) => {
        const probe = target + hours * HOUR;
        return wall(probe) - probe;
      }),
    );
    const candidates = [...offsets]
      .map((offset) => target - offset)
      .filter((time) => wall(time) === target)
      .sort((a, b) => a - b);
    if (!candidates.length)
      warn(
        `Local light time ${hour}:00 on ${date} does not exist in ${timeZone}; that cycle is omitted.`,
      );
    if (candidates.length > 1)
      warn(
        `Local light time on ${date} repeats in ${timeZone}; the first occurrence anchors the illustration.`,
      );
    const value = candidates[0] ?? null;
    instantCache.set(key, value);
    return value;
  };
  const point = (time: number, value: number | null): ComparisonTargetPoint => ({
    time,
    value,
    age: ageAt(time, runStartDate, timeZone),
  });
  const segment = (
    target: ComparisonTargetPoint[],
    a: { time: number; value: number },
    b: { time: number; value: number },
  ) => {
    if (b.time <= a.time || b.time < start || a.time >= end) return;
    const from = Math.max(start, a.time),
      to = Math.min(end, b.time);
    if (to <= from) return;
    const at = (time: number) =>
      a.value + ((b.value - a.value) * (time - a.time)) / (b.time - a.time);
    target.push(point(from, at(from)), point(to, at(to)), point(to, null));
  };
  // Include the preceding light cycle so a midnight range start retains its overnight part.
  for (
    let date = addDays(first, -1), count = 0;
    date <= last && count < 368;
    date = addDays(date, 1), count++
  ) {
    try {
      const anchor = localInstant(date, lightsOn);
      const nextAnchor = localInstant(addDays(date, 1), lightsOn);
      const offDate = lightsOff <= lightsOn ? addDays(date, 1) : date;
      const off = localInstant(offDate, lightsOff);
      if (anchor === null || nextAnchor === null || off === null) continue;
      const offset = finiteRange("p3_last_irrigation", 1440)
        ? parameters.p3_last_irrigation * 60_000
        : 0;
      const p3 = Math.max(anchor, Math.min(nextAnchor, off - offset));
      const boundaries = [
        anchor,
        Math.min(p3, anchor + plan.phases[0].end * HOUR),
        Math.min(p3, anchor + plan.phases[1].end * HOUR),
        p3,
        nextAnchor,
      ];
      const mapped = (p: PlanningPoint) => {
        const index = ids.indexOf(p.phase),
          phase = plan.phases[index];
        const fraction =
          phase.end > phase.start ? (p.hour - phase.start) / (phase.end - phase.start) : 0;
        return {
          time: boundaries[index] + fraction * (boundaries[index + 1] - boundaries[index]),
          value: p.value,
        };
      };
      for (let index = 1; index < plan.vwc.length; index++) {
        const a = plan.vwc[index - 1],
          b = plan.vwc[index];
        const ap = ids.indexOf(a.phase),
          bp = ids.indexOf(b.phase);
        if (known[ap] && known[bp] && bp - ap <= 1) segment(result.vwc, mapped(a), mapped(b));
      }
      for (let index = 0; index < plan.phases.length; index++) {
        if (!known[index]) continue;
        const points = plan.ec.filter((p) => p.phase === ids[index]);
        if (points.length === 2) segment(result.ec, mapped(points[0]), mapped(points[1]));
      }
      if (plan.emergencyFloor !== null)
        segment(
          result.floor,
          { time: p3, value: plan.emergencyFloor },
          { time: nextAnchor, value: plan.emergencyFloor },
        );
    } catch {
      warn(`Reference cycle ${date} could not be placed in ${timeZone} and was omitted.`);
    }
  }
  return result;
}
