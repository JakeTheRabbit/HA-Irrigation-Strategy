/** History › Dryback drivers (Settings › Display): each zone's overnight dryback rate against the
 * room's climate over the same night, one point per zone and night. The rate is VWC percentage
 * points per hour (pp/h), not the dryback target's percent of peak. Correlation only: the page says
 * no cause. */
export interface Night {
  start: number;
  end: number;
}
export interface DriverPoint {
  zone: number;
  night: number;
  /** The driver's mean over the night. */
  x: number;
  /** pp/h: (VWC at lights-off − VWC at lights-on) / hours. */
  y: number;
}
/** A rise of more than this in a night (pp) is a shot: that night is left out. */
export const SHOT_RISE = 0.5;

/** Every whole night (lights-off to the next lights-on) between `from` and `to`. */
export function nights(
  lightsOffTimes: readonly number[],
  nightHours: number,
  from: number,
  to: number,
): Night[] {
  return lightsOffTimes
    .map((start) => ({ start, end: start + nightHours * 3_600_000 }))
    .filter((night) => night.start >= from && night.end <= to);
}

const inside = (times: readonly number[], night: Night) =>
  times.flatMap((t, i) => (t >= night.start && t <= night.end ? [i] : []));

/** One point per night for a zone: none where the zone or the driver has too few readings, or the
 * zone's VWC rose in the night (a shot). */
export function driverPoints(
  zone: number,
  times: readonly number[],
  vwc: readonly (number | null)[],
  driver: readonly (number | null)[],
  list: readonly Night[],
): DriverPoint[] {
  return list.flatMap((night) => {
    const at = inside(times, night);
    const readings = at.flatMap((i) => (vwc[i] === null ? [] : [{ t: times[i], v: vwc[i]! }]));
    const drivers = at.flatMap((i) => (driver[i] === null ? [] : [driver[i]!]));
    if (readings.length < 3 || drivers.length < 3) return [];
    let low = readings[0].v;
    for (const reading of readings) {
      if (reading.v - low > SHOT_RISE) return [];
      low = Math.min(low, reading.v);
    }
    const first = readings[0],
      last = readings.at(-1)!;
    const hours = (last.t - first.t) / 3_600_000;
    if (hours < 1) return [];
    return [
      {
        zone,
        night: night.start,
        x: drivers.reduce((sum, value) => sum + value, 0) / drivers.length,
        y: (first.v - last.v) / hours,
      },
    ];
  });
}
