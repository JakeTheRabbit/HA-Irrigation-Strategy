/** Pure helpers for the operator cards: data quality and how far a value is from its target. */

/** A substrate probe in use never reads 1 % VWC or less. Such a reading is a gap in the probe's
 * data (a dropout), not a dry substrate, so it is not drawn and is not used as a peak or a low. */
export const PROBE_GAP_VWC = 1;

export interface ProbeGap {
  start: number;
  end: number;
}
/** Splits readings into the usable ones and the gaps, a gap being one run of readings at or under
 * `limit`. Each gap keeps the time of its first and its last bad reading. */
export function probeGaps<T extends { time: number; value: number }>(
  readings: readonly T[],
  limit = PROBE_GAP_VWC,
): { clean: T[]; gaps: ProbeGap[] } {
  const clean: T[] = [];
  const gaps: ProbeGap[] = [];
  let open: ProbeGap | null = null;
  for (const reading of readings) {
    if (reading.value <= limit) {
      if (open) open.end = reading.time;
      else gaps.push((open = { start: reading.time, end: reading.time }));
    } else {
      open = null;
      clean.push(reading);
    }
  }
  return { clean, gaps };
}

export type GaugeState = "normal" | "abnormal" | "no-data";
export interface GaugeModel {
  label: string;
  value: number | null;
  unit: string;
  digits: number;
  /** A single target, or the band the value must stay in. */
  target: number | null;
  band: [number, number] | null;
  /** Signed distance from the target, or from the nearest edge of the band (0 inside it). */
  deviation: number | null;
  state: GaugeState;
  /** What the deviation means, in a few words: "24.6 points under", "in band". */
  words: string;
  /** The scale of the bar. */
  min: number;
  max: number;
  /** Why there is no value, when there is none. */
  quality?: string;
}
const fix = (value: number, digits: number) => String(Number(value.toFixed(digits)));
const amount = (value: number, digits: number, points: string) =>
  `${fix(Math.abs(value), digits)}${points.startsWith("%") ? "" : " "}${points}`;

/** One key value against its target or band. `tolerance` is how far from a single target the value
 * can be before it is abnormal; a value outside a band is always abnormal. `points` names the unit
 * of the deviation ("points" for VWC, the unit itself for EC). */
export function gauge(options: {
  label: string;
  value: number | null;
  unit: string;
  digits?: number;
  target?: number | null;
  band?: [number, number] | null;
  tolerance?: number;
  points?: string;
  /** Under the target is normal (for example a peak that is not reached yet). */
  underIsNormal?: boolean;
  quality?: string;
  scale?: [number, number];
}): GaugeModel {
  const digits = options.digits ?? 1;
  const target = finite(options.target) ? options.target : null;
  const band =
    options.band && options.band.every(Number.isFinite) && options.band[0] <= options.band[1]
      ? options.band
      : null;
  const value = finite(options.value) ? options.value : null;
  const points = options.points ?? "points";
  const known = [value, target, ...(band ?? [])].filter(finite);
  const lo = known.length ? Math.min(...known) : 0;
  const hi = known.length ? Math.max(...known) : 100;
  const pad = Math.max((hi - lo) * 0.25, hi * 0.05, 0.5);
  const [min, max] = options.scale ?? [Math.max(0, lo - pad), hi + pad];
  const base = {
    label: options.label,
    value,
    unit: options.unit,
    digits,
    target,
    band,
    min,
    max,
    quality: options.quality,
  };
  if (value === null)
    return { ...base, deviation: null, state: "no-data", words: options.quality ?? "no reading" };
  if (band) {
    const deviation = value < band[0] ? value - band[0] : value > band[1] ? value - band[1] : 0;
    return {
      ...base,
      deviation,
      state: Math.abs(deviation) > (options.tolerance ?? 0) ? "abnormal" : "normal",
      words:
        deviation === 0
          ? "in band"
          : `${amount(deviation, digits, points)} ${deviation < 0 ? "under" : "over"}`,
    };
  }
  if (target === null) return { ...base, deviation: null, state: "normal", words: "no target" };
  const deviation = value - target;
  const tolerance = options.tolerance ?? 0;
  const abnormal =
    Math.abs(deviation) > tolerance && !(options.underIsNormal && deviation < 0);
  return {
    ...base,
    deviation,
    state: abnormal ? "abnormal" : "normal",
    words:
      Math.abs(deviation) < 10 ** -digits / 2
        ? "on target"
        : `${amount(deviation, digits, points)} ${deviation < 0 ? "under" : "over"}`,
  };
}

/** VWC now against what its phase asks for: up to the peak target in P1, between the re-water point
 * and the peak target in P2, and above the rescue floor overnight and in the morning dryback. */
export function vwcGauge(options: {
  value: number | null;
  phase: string | null;
  rewater: number | null;
  peak: number | null;
  rescue: number | null;
  quality?: string;
}): GaugeModel {
  const { phase, rewater, peak, rescue } = options;
  const base = { label: "VWC now", value: options.value, unit: "%", quality: options.quality };
  if (phase === "P1" && finite(peak))
    return gauge({ ...base, target: peak, tolerance: 3, underIsNormal: true });
  if (phase === "P2" && finite(rewater) && finite(peak) && peak > rewater)
    return gauge({ ...base, band: [rewater, peak], tolerance: 2 });
  if (finite(rescue) && finite(peak) && peak > rescue)
    return gauge({ ...base, band: [rescue, peak], tolerance: 2 });
  return gauge({ ...base, target: peak, tolerance: 3, underIsNormal: true });
}

/** What a screen reader says for a gauge: "VWC now 25.4%, target 50%, 24.6 points under". */
export function gaugeSpeech(model: GaugeModel): string {
  const unit = (value: number) => `${fix(value, model.digits)}${model.unit}`;
  const parts = [`${model.label} ${model.value === null ? model.words : unit(model.value)}`];
  if (model.band) parts.push(`band ${unit(model.band[0])} to ${unit(model.band[1])}`);
  else if (model.target !== null) parts.push(`target ${unit(model.target)}`);
  if (model.value !== null && (model.band || model.target !== null)) parts.push(model.words);
  return parts.join(", ");
}

/** The value of a line at `hour`, straight between its points; null outside it. */
export function valueAt(points: readonly { hour: number; value: number }[], hour: number) {
  if (!points.length || hour < points[0].hour || hour > points.at(-1)!.hour) return null;
  for (let index = 1; index < points.length; index++) {
    const a = points[index - 1],
      b = points[index];
    if (hour <= b.hour)
      return b.hour === a.hour
        ? b.value
        : a.value + ((b.value - a.value) * (hour - a.hour)) / (b.hour - a.hour);
  }
  return points.at(-1)!.value;
}

function finite(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
