export type PlanningPhaseId = "P0" | "P1" | "P2" | "P3";
export interface PlanningPoint {
  hour: number;
  value: number;
  phase: PlanningPhaseId;
  breakBefore?: boolean;
}
export interface PlanningPhase {
  id: PlanningPhaseId;
  label: string;
  start: number;
  end: number;
  color: string;
}
/** One P1 shot on the ramp: the VWC reference before and after it. */
export interface PlanningStep {
  hour: number;
  from: number;
  to: number;
  /** Configured shot size, % of substrate volume; null when sizes were not supplied. */
  size: number | null;
}
export interface PlanningModel {
  phases: PlanningPhase[];
  vwc: PlanningPoint[];
  ec: PlanningPoint[];
  p1Steps: PlanningStep[];
  photoperiod: number;
  morningDrybackVwc: number | null;
  drybackReference: number | null;
  p1Windows: number[];
  p2Envelope: [number, number] | null;
  emergencyFloor: number | null;
  overnightEndVwc: number | null;
  emergencyReferenceActive: boolean;
  missing: string[];
  notes: string[];
  warnings: string[];
}
export const planningClock = (lightsOn: number, elapsed: number) => {
  if (!Number.isFinite(lightsOn) || !Number.isFinite(elapsed)) return "—";
  const minutes = Math.round(((((lightsOn + elapsed) % 24) + 24) % 24) * 60) % 1440;
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
};
/** A setpoint schematic: no crop-response, salt-balance or yield prediction. */
export function buildPlanningCurve(
  parameters: Record<string, number>,
  lightsOn: number,
  lightsOff: number,
): PlanningModel {
  const notes: string[] = [];
  const warnings: string[] = [];
  const missing: string[] = [];
  const value = (key: string, min = 0, max = 100): number | null => {
    const raw = parameters[key];
    if (raw === undefined || raw === null) return null;
    if (!Number.isFinite(raw) || raw < min || raw > max) {
      warnings.push(`${key.replaceAll("_", " ")} is outside the planning range ${min}–${max}.`);
      return null;
    }
    return raw;
  };
  let photoperiod = (((lightsOff - lightsOn) % 24) + 24) % 24;
  if (
    !Number.isFinite(lightsOn) ||
    !Number.isFinite(lightsOff) ||
    lightsOn < 0 ||
    lightsOn >= 24 ||
    lightsOff < 0 ||
    lightsOff >= 24 ||
    !photoperiod
  ) {
    warnings.push(
      "Lights-on and lights-off must differ and be valid hours from 0 to less than 24.",
    );
    photoperiod = 0;
  }
  const p1 = value("p1_target_vwc");
  const p2 = value("p2_vwc_threshold");
  const shot = value("p2_shot_size");
  const floor = value("p3_emergency_vwc_threshold");
  const fc = value("field_capacity");
  const dryback = value("dryback_target");
  const reference = fc ?? p1;
  if (fc === null && p1 !== null && dryback !== null)
    notes.push(
      "The peak VWC target is used as the dryback reference because full saturation was not supplied.",
    );
  const morningDryback =
    reference !== null && dryback !== null ? reference * (1 - dryback / 100) : null;
  if (p1 === null) missing.push("Peak VWC target");
  if (p2 === null) missing.push("Maintenance shot when below");
  if (morningDryback === null) missing.push("P3 dryback target/reference");
  if (p1 !== null && p2 !== null && p2 > p1)
    warnings.push("The maintenance trigger is above the peak VWC target.");
  const wait = value("p0_maximum_wait_time", 0, 1440);
  const interval = value("p1_time_between_shots", 0, 1440);
  const maxShots = value("p1_maximum_shots", 0, 200);
  if (wait === null)
    notes.push("P0 is drawn as a 1-hour layout window; the latest first shot was not supplied.");
  if (interval === null || maxShots === null)
    notes.push("P1 is drawn as a 2-hour layout window; shot count/interval were not supplied.");
  else
    notes.push(
      "P1 width uses maximum shots × shot interval as a planning window, not a prediction of when the target will be reached.",
    );
  const lastOffset = value("p3_last_irrigation", 0, 1440);
  if (lastOffset === null)
    notes.push(
      "P3 begins at lights-off in this illustration; an earlier final-irrigation offset was not supplied.",
    );
  const p3Start = Math.max(0, photoperiod - (lastOffset ?? 0) / 60);
  const rawP0End = (wait ?? 60) / 60;
  const rawP1End =
    rawP0End + (interval !== null && maxShots !== null ? (interval * maxShots) / 60 : 2);
  if (rawP0End >= p3Start || rawP1End > p3Start)
    warnings.push(
      "The illustrated P0/P1 planning windows overlap the P3 cutoff; actual phase transitions depend on controller conditions.",
    );
  const p0End = Math.min(rawP0End, p3Start);
  const p1End = Math.min(rawP1End, p3Start);
  const phases: PlanningPhase[] = [
    { id: "P0", label: "Additional dryback", start: 0, end: p0End, color: "#8f9aa6" },
    { id: "P1", label: "Ramp-up", start: p0End, end: p1End, color: "#03a9f4" },
    { id: "P2", label: "Maintenance", start: p1End, end: p3Start, color: "#42b995" },
    { id: "P3", label: "Overnight dryback", start: p3Start, end: 24, color: "#e5a43b" },
  ];
  const p1Windows =
    interval !== null && interval > 0 && maxShots !== null
      ? Array.from(
          { length: Math.floor(maxShots) },
          (_, index) => p0End + (index * interval) / 60,
        ).filter((hour) => hour < p1End && hour < p3Start)
      : [];
  if (p1Windows.length)
    notes.push(
      "P1 ticks show eligible irrigation windows at the supplied spacing, starting from the illustrated P1 boundary. Sensor feedback may end ramp-up sooner; they are not scheduled or recorded shots.",
    );
  // Draw a periodic reference cycle. Reusing field capacity at lights-on would
  // invent overnight rehydration; the next cycle starts at the same endpoint.
  const daytimeEnd = p3Start > p1End ? p2 : p1End > p0End ? p1 : morningDryback;
  const overnightEnd =
    daytimeEnd !== null && morningDryback !== null ? Math.min(daytimeEnd, morningDryback) : null;
  if (daytimeEnd !== null && morningDryback !== null && morningDryback > daytimeEnd)
    warnings.push(
      "The relative dryback endpoint is above the last daytime VWC reference. Overnight is shown flat because those settings do not define a further drop; no rehydration is invented.",
    );
  const emergencyReferenceActive = floor !== null && overnightEnd !== null && overnightEnd <= floor;
  if (emergencyReferenceActive)
    warnings.push(
      "The overnight reference reaches or crosses the rescue level. A rescue shot would be relevant at that reading; the chart does not predict or schedule one.",
    );
  // The ramp is a staircase, one riser per eligible shot. Each shot takes the share of the climb
  // that its configured size is of the ramp's total water; retained water is not predicted.
  const p1Steps: PlanningStep[] = [];
  if (p1 !== null && overnightEnd !== null && p1 > overnightEnd && p1Windows.length) {
    const initial = value("p1_initial_shot_size");
    const increment = value("p1_shot_size_increment") ?? 0;
    const sizes = p1Windows.map((_, index) =>
      initial === null ? null : initial + index * increment,
    );
    const total = sizes.reduce<number>((sum, size) => sum + (size ?? 1), 0);
    let level = overnightEnd;
    p1Windows.forEach((hour, index) => {
      const last = index === p1Windows.length - 1;
      const to = last ? p1 : level + ((p1 - overnightEnd) * (sizes[index] ?? 1)) / total;
      p1Steps.push({ hour, from: level, to, size: sizes[index] });
      level = to;
    });
    notes.push(
      "P1 is drawn one step per eligible shot. Each step takes the share of the climb that its configured shot size is of the ramp's total; how much water the substrate actually retains is not predicted.",
    );
  }
  const vwc: PlanningPoint[] = [];
  if (overnightEnd !== null) {
    vwc.push({ hour: 0, value: overnightEnd, phase: "P0" });
    if (p0End > 0) vwc.push({ hour: p0End, value: overnightEnd, phase: "P0" });
  }
  if (p1 !== null && p1End > p0End) vwc.push({ hour: p1End, value: p1, phase: "P1" });
  if (p2 !== null && p3Start > p1End)
    vwc.push(
      { hour: p1End + (p3Start - p1End) * 0.25, value: p2, phase: "P2" },
      { hour: p3Start, value: p2, phase: "P2" },
    );
  if (daytimeEnd !== null && overnightEnd !== null && p3Start < 24) {
    vwc.push({ hour: p3Start, value: daytimeEnd, phase: "P3" });
    if (photoperiod > p3Start && photoperiod < 24)
      vwc.push({
        hour: photoperiod,
        value:
          daytimeEnd + ((overnightEnd - daytimeEnd) * (photoperiod - p3Start)) / (24 - p3Start),
        phase: "P3",
      });
    vwc.push({ hour: 24, value: overnightEnd, phase: "P3" });
  }
  notes.push(
    "Overnight VWC is a straight planning connection from the last daytime reference to the relative dryback endpoint, then the same value at next lights-on. P0's latest-first-shot window is shown at that endpoint. Neither timing nor measured moisture is forecast. The rescue level is separate, not a desired overnight target.",
  );
  const ec: PlanningPoint[] = [];
  const ecTargets = phases
    .slice(0, 3)
    .map((phase) => {
      const target = value(`ec_target_${phase.id.toLowerCase()}`, 0, 20);
      if (target === null) missing.push(`${phase.id} EC target`);
      return { ...phase, target, middle: (phase.start + phase.end) / 2 };
    })
    .filter((phase) => phase.end > phase.start);
  const boundaryValue = (
    a: (typeof ecTargets)[number],
    b: (typeof ecTargets)[number],
    hour: number,
  ) => a.target! + ((b.target! - a.target!) * (hour - a.middle)) / (b.middle - a.middle);
  for (let index = 0; index < ecTargets.length; index++) {
    const phase = ecTargets[index],
      previous = ecTargets[index - 1],
      next = ecTargets[index + 1];
    if (phase.target === null) continue;
    const start =
      previous?.target != null ? boundaryValue(previous, phase, phase.start) : phase.target;
    const end = next?.target != null ? boundaryValue(phase, next, phase.end) : phase.target;
    ec.push(
      {
        hour: phase.start,
        value: start,
        phase: phase.id,
        ...(index > 0 && previous?.target == null ? { breakBefore: true } : {}),
      },
      { hour: phase.middle, value: phase.target, phase: phase.id },
      { hour: phase.end, value: end, phase: phase.id },
    );
  }
  const firstEc = ecTargets[0]?.target,
    lastEc = ecTargets.at(-1)?.target;
  if (firstEc != null && lastEc != null && p3Start < 24) {
    ec.push({ hour: p3Start, value: lastEc, phase: "P3" });
    if (photoperiod > p3Start && photoperiod < 24)
      ec.push({
        hour: photoperiod,
        value: lastEc + ((firstEc - lastEc) * (photoperiod - p3Start)) / (24 - p3Start),
        phase: "P3",
      });
    ec.push({ hour: 24, value: firstEc, phase: "P3" });
  } else {
    notes.push(
      "The overnight EC connection needs both the last daytime and next morning phase references. Missing endpoints are left unplotted.",
    );
  }
  notes.push(
    "EC is a continuous schematic through configured phase anchors. Its dashed overnight connection interpolates to the next morning reference; there is no P3 EC setpoint, salt-balance model or predicted EC response.",
  );
  const envelope: [number, number] | null =
    p2 !== null && shot !== null ? [p2, Math.min(100, p2 + shot)] : null;
  notes.push(
    "Dryback follows the engine: (peak − VWC) / peak × 100. The illustrated reference stands in for a measured peak. Lines connect setpoints for planning only. They do not forecast measured VWC, EC, uptake or runoff.",
  );
  if (envelope)
    notes.push(
      "The P2 shaded band adds nominal shot volume to VWC assuming full retention; actual retained water can be lower.",
    );
  if (p2 !== null && shot !== null && p2 + shot > 100)
    warnings.push(
      "The maintenance trigger plus a maintenance shot exceeds 100% VWC; the illustrated band is clipped at 100%.",
    );
  return {
    phases,
    vwc,
    ec,
    p1Steps,
    p1Windows,
    photoperiod,
    morningDrybackVwc: morningDryback,
    drybackReference: reference,
    p2Envelope: envelope,
    emergencyFloor: floor,
    overnightEndVwc: overnightEnd,
    emergencyReferenceActive,
    missing,
    notes,
    warnings,
  };
}

export interface PlanningBound {
  min: number;
  max: number;
  step: number;
}
export type PlanningBounds = Record<string, PlanningBound>;
/** Use the HA field's minimum as the step origin; the highest step may be below max. */
export function changePlanningValue(
  key: string,
  value: number,
  bounds: PlanningBounds,
  onChange?: (key: string, value: number) => void,
) {
  const bound = bounds[key];
  if (
    !onChange ||
    !bound ||
    ![value, bound.min, bound.max, bound.step].every(Number.isFinite) ||
    bound.min > bound.max ||
    bound.step <= 0
  )
    return;
  const maxStep = Math.floor((bound.max - bound.min) / bound.step + 1e-9);
  const step = Math.min(maxStep, Math.max(0, Math.round((value - bound.min) / bound.step)));
  const quantized = Number((bound.min + step * bound.step).toFixed(10));
  onChange(key, quantized);
}

export interface RecordedReading {
  time: number;
  value: number;
}
export interface RecordedPoint extends RecordedReading {
  /** Hours since that grow-day's lights-on, the plan graph's x-axis. */
  hour: number;
}
export interface FoldedRecording {
  today: RecordedPoint[];
  /** Earlier grow-days, most recent first. */
  previous: RecordedPoint[][];
  /** Earlier grow-days with too few readings to draw. */
  earlier: number;
}
/** Fold recorded readings onto the lights-on axis so they sit under the targets being edited.
 * A grow-day runs from lights-on to the next lights-on, in the browser's time zone. */
export function foldRecorded(
  readings: readonly RecordedReading[],
  lightsOn: number,
  now: number,
): FoldedRecording {
  const folded: FoldedRecording = { today: [], previous: [], earlier: 0 };
  if (!Number.isFinite(lightsOn) || lightsOn < 0 || lightsOn >= 24 || !Number.isFinite(now))
    return folded;
  const dayStart = (time: number) => {
    const date = new Date(time);
    const at = (offset: number) =>
      new Date(
        date.getFullYear(),
        date.getMonth(),
        date.getDate() + offset,
        0,
        Math.round(lightsOn * 60),
      ).getTime();
    return at(0) > time ? at(-1) : at(0);
  };
  const current = dayStart(now);
  const days = new Map<number, RecordedPoint[]>();
  for (const reading of readings) {
    if (!Number.isFinite(reading.time) || !Number.isFinite(reading.value) || reading.time > now)
      continue;
    const start = dayStart(reading.time);
    const hour = Math.min(24, Math.max(0, (reading.time - start) / 3_600_000));
    const day = days.get(start) ?? [];
    day.push({ hour, value: reading.value, time: reading.time });
    days.set(start, day);
  }
  for (const [start, points] of [...days].sort((a, b) => b[0] - a[0])) {
    points.sort((a, b) => a.time - b.time);
    if (start === current) folded.today = points;
    else if (points.length > 1) folded.previous.push(points);
    else folded.earlier++;
  }
  return folded;
}
/** VWC axis for the plan graph: what is plotted plus headroom. The span is always 20, 40, 60, 80
 * or 100 points, so its four grid intervals land on whole multiples of 5. */
export function planningAxis(values: readonly number[]): { min: number; max: number } {
  const finite = values.filter((value) => Number.isFinite(value));
  if (!finite.length) return { min: 0, max: 100 };
  let min = Math.max(0, Math.floor((Math.min(...finite) - 2) / 5) * 5);
  let max = Math.min(100, Math.ceil((Math.max(...finite) + 2) / 5) * 5);
  for (let lower = true; (max - min) % 20 !== 0 || max === min; lower = !lower) {
    if (lower ? min > 0 : max >= 100) min -= 5;
    else max += 5;
  }
  return { min, max };
}

export interface DryRates {
  /** VWC points lost per hour with lights on / lights off; null until enough quiet hours exist. */
  day: number | null;
  night: number | null;
}
const median = (values: number[]) => {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = sorted.length >> 1;
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};
/** How fast this zone actually dries, from its own recorded VWC: the median fall rate over quiet
 * runs (four consecutive readings, under an hour, none of them rising), separately for lights-on and
 * lights-off. A shot ends a run, so frequent P2 top-ups do not flatten the answer the way hour-to-hour
 * averages do. Checked against three live zones and a synthetic sawtooth with a known rate. */
export function dryRates(
  days: readonly (readonly RecordedPoint[])[],
  photoperiod: number,
): DryRates {
  const SPAN = 3,
    RISE_TOLERANCE = 0.15;
  const falls: { day: number[]; night: number[] } = { day: [], night: [] };
  for (const points of days)
    for (let index = 0; index + SPAN < points.length; index++) {
      const run = points.slice(index, index + SPAN + 1);
      const hours = run[SPAN].hour - run[0].hour;
      if (hours <= 0 || hours > 1) continue;
      if (run.some((point, k) => k > 0 && point.value > run[k - 1].value + RISE_TOLERANCE))
        continue;
      const rate = (run[0].value - run[SPAN].value) / hours;
      if (rate <= 0 || rate > 6) continue;
      ((run[0].hour + run[SPAN].hour) / 2 < photoperiod ? falls.day : falls.night).push(rate);
    }
  const rate = (values: number[]) => (values.length > 5 ? +median(values).toFixed(2) : null);
  return { day: rate(falls.day), night: rate(falls.night) };
}

export interface ProjectedShot {
  hour: number;
  phase: PlanningPhaseId;
  from: number;
  to: number;
  /** Configured size, % of substrate volume. */
  size: number | null;
  emergency?: boolean;
}
export interface PlanningProjection {
  points: PlanningPoint[];
  shots: ProjectedShot[];
  /** Projected VWC at lights-on: where the night's dry-down ends and the next day starts. */
  lightsOnVwc: number;
  peak: number;
  /** The dryback target as a VWC level: the projected peak less the relative dryback. */
  drybackVwc: number | null;
  rates: { day: number; night: number };
  measured: { day: boolean; night: boolean };
  retention: number;
}
/** Used until a zone has enough recorded history to measure its own dry-down: a flowering room
 * transpiring well (about 2 points an hour under lights, 1 overnight). The first default, 0.7 / 0.35,
 * was one low-light week on one zone; at that rate no ordinary plan ever reached its P2 threshold, so
 * the maintenance sawtooth never drew. */
export const NOMINAL_DRY_RATES = { day: 2, night: 1 };
const usable = (value: number | null | undefined): value is number =>
  typeof value === "number" && Number.isFinite(value) && value > 0;
/** The zone's own dry-down where it was measured, else the nominal rates; a learned retention up to
 * 1.5 points per 1% shot, else every shot kept whole. */
function projectionInputs(options: { rates?: DryRates; retention?: number | null }) {
  return {
    rates: {
      day: usable(options.rates?.day) ? options.rates.day : NOMINAL_DRY_RATES.day,
      night: usable(options.rates?.night) ? options.rates.night : NOMINAL_DRY_RATES.night,
    },
    measured: { day: usable(options.rates?.day), night: usable(options.rates?.night) },
    retention: usable(options.retention) ? Math.min(1.5, options.retention) : 1,
  };
}
interface PhaseRun {
  /** The phase the run starts in and the VWC it starts at. */
  phase: PlanningPhaseId;
  value: number;
  /** P0–P3 from there on, in hours since lights-on. */
  phases: readonly { start: number; end: number }[];
  /** The ramp shots still to come, and how many the ramp fired before them. */
  p1Windows: readonly number[];
  p1Done: number;
  /** The ramp's shot count or spacing is not known: P1 climbs to its target as one line. */
  jump: boolean;
}
/** The engine's rules from `run.phase` to the end of P3: P0 dries on; P1 climbs one riser per
 * window, each taking its share of the rest of the climb, drying between them; P2 fires a shot each
 * time VWC falls to its threshold; P3 dries on, with an emergency shot at the floor. */
function runPhases(
  plan: PlanningModel,
  parameters: Record<string, number>,
  rates: { day: number; night: number },
  retention: number,
  run: PhaseRun,
) {
  const target = parameters.p1_target_vwc,
    threshold = parameters.p2_vwc_threshold;
  const lift = (size: number) => (usable(size) ? Math.max(0.1, size * retention) : 0);
  const [p0, p1, p2, p3] = run.phases;
  const floor = plan.emergencyFloor;
  const order = ["P0", "P1", "P2", "P3"].indexOf(run.phase);
  const points: PlanningPoint[] = [],
    shots: ProjectedShot[] = [];
  let value = run.value;
  const mark = (hour: number, phase: PlanningPhaseId) => points.push({ hour, value, phase });
  /** Dry down minute by minute from `from` to `to`, firing `fire` whenever `due` says so. */
  const dry = (
    from: number,
    to: number,
    phase: PlanningPhaseId,
    due?: (value: number) => Omit<ProjectedShot, "hour" | "phase" | "from" | "to"> | null,
    /** Without a shot size there is nothing to lift the zone: hold the line here instead. */
    holdAt?: number,
  ) => {
    mark(from, phase);
    const end = Math.round(to * 60);
    for (let minute = Math.round(from * 60); minute < end; minute++) {
      value -= (minute / 60 < plan.photoperiod ? rates.day : rates.night) / 60;
      value = Math.max(holdAt ?? 0, value);
      const hour = (minute + 1) / 60;
      const shot = shots.length < 200 ? due?.(value) : null;
      if (shot && usable(shot.size) && minute + 1 < end) {
        mark(hour, phase);
        const before = value;
        value += lift(shot.size);
        shots.push({ hour, phase, from: before, to: value, ...shot });
        mark(hour, phase);
      } else if (minute + 1 === Math.round(plan.photoperiod * 60)) mark(hour, phase);
    }
    mark(to, phase);
  };
  if (order === 0 && p0.end > p0.start) dry(p0.start, p0.end, "P0");
  if (order <= 1) {
    const start = value,
      windows = run.p1Windows;
    if (run.jump && target > start) {
      // shot count or spacing not supplied: the climb is known, its steps are not
      mark(p1.start, "P1");
      value = target;
      mark(p1.end, "P1");
    } else if (windows.length && target > start) {
      // one riser per eligible shot; each takes its share of the climb, and the substrate dries between them
      const initial = parameters.p1_initial_shot_size;
      const increment = Number.isFinite(parameters.p1_shot_size_increment)
        ? parameters.p1_shot_size_increment
        : 0;
      const sizes = windows.map((_, index) =>
        usable(initial) ? initial + (run.p1Done + index) * increment : null,
      );
      const total = sizes.reduce<number>((sum, size) => sum + (size ?? 1), 0);
      let climbed = 0;
      windows.forEach((hour, index) => {
        if (index) dry(windows[index - 1], hour, "P1");
        else if (hour > p1.start) dry(p1.start, hour, "P1");
        else mark(hour, "P1");
        climbed += (sizes[index] ?? 1) / total;
        const to = index === windows.length - 1 ? target : start + (target - start) * climbed;
        shots.push({ hour, phase: "P1", from: value, to, size: sizes[index] ?? null });
        value = to;
        mark(hour, "P1");
      });
      if (p1.end > windows.at(-1)!) dry(windows.at(-1)!, p1.end, "P1");
    } else if (p1.end > p1.start) dry(p1.start, p1.end, "P1");
  }
  if (order <= 2 && p2.end > p2.start)
    dry(
      p2.start,
      p2.end,
      "P2",
      (now) => (now <= threshold ? { size: parameters.p2_shot_size ?? null } : null),
      usable(parameters.p2_shot_size) ? undefined : threshold,
    );
  if (p3.end > p3.start)
    dry(p3.start, p3.end, "P3", (now) =>
      floor !== null && now <= floor
        ? { size: parameters.p3_emergency_shot_size ?? null, emergency: true }
        : null,
    );
  return { points, shots, value };
}
/** The whole day as the engine would run these setpoints: P0 dries on, P1 climbs shot by shot,
 * P2 fires a shot each time VWC falls to its threshold, P3 dries down to the next lights-on.
 * Timing comes from the zone's dry-down rate, so it is a projection, not a schedule. */
export function projectDay(
  plan: PlanningModel,
  parameters: Record<string, number>,
  options: { rates?: DryRates; retention?: number | null } = {},
): PlanningProjection | null {
  const target = parameters.p1_target_vwc,
    threshold = parameters.p2_vwc_threshold;
  if (
    !plan.photoperiod ||
    !plan.vwc.length ||
    !Number.isFinite(target) ||
    !Number.isFinite(threshold)
  )
    return null;
  const { rates, measured, retention } = projectionInputs(options);
  let lightsOnVwc = Math.min(threshold, target);
  let run!: ReturnType<typeof runPhases>;
  for (let pass = 0; pass < 6; pass++) {
    run = runPhases(plan, parameters, rates, retention, {
      phase: "P0",
      value: lightsOnVwc,
      phases: plan.phases,
      p1Windows: plan.p1Windows,
      p1Done: 0,
      jump: !plan.p1Windows.length,
    });
    if (Math.abs(run.value - lightsOnVwc) < 0.005) break;
    lightsOnVwc = run.value;
  }
  const { points, shots } = run;
  points.at(-1)!.value = lightsOnVwc; // the next day starts where this one ends
  const peak = Math.max(...points.map((point) => point.value));
  const dryback = parameters.dryback_target;
  return {
    points,
    shots,
    lightsOnVwc,
    peak,
    drybackVwc: Number.isFinite(dryback) ? peak * (1 - dryback / 100) : null,
    rates,
    measured,
    retention,
  };
}
/** The rest of today on the same rules, from now instead of lights-on: `hour` hours after lights-on,
 * in the zone's current phase and at its current VWC. P0 ends at its maximum wait from `since`,
 * sooner once VWC dries to the dryback target below `peak`, at once when VWC is already at the P2
 * threshold (the engine's bypass). P1 fires the shots it has left `p1_time_between_shots` apart,
 * from the last one. The day ends `end` hours after lights-on, the next lights-on: 23 or 25 hours
 * across a clock change. Null without the targets or a reading to start from. */
export function projectFrom(
  plan: PlanningModel,
  parameters: Record<string, number>,
  now: {
    hour: number;
    phase: PlanningPhaseId;
    since: number;
    value: number;
    p1Shots: number;
    lastShot: number | null;
    peak: number | null;
  },
  options: { rates?: DryRates; retention?: number | null; end?: number } = {},
): PlanningProjection | null {
  const target = parameters.p1_target_vwc,
    threshold = parameters.p2_vwc_threshold,
    end = options.end ?? 24;
  if (
    !plan.photoperiod ||
    !Number.isFinite(target) ||
    !Number.isFinite(threshold) ||
    ![now.hour, now.since, now.value].every(Number.isFinite) ||
    now.hour >= end
  )
    return null;
  const { rates, measured, retention } = projectionInputs(options);
  const hours = (key: string) => (usable(parameters[key]) ? parameters[key] / 60 : null);
  const interval = hours("p1_time_between_shots"),
    maxShots = usable(parameters.p1_maximum_shots) ? Math.floor(parameters.p1_maximum_shots) : null;
  // Routine watering stops where P3 starts: lights-off, less any last-irrigation offset.
  const cutoff = Math.max(now.hour, plan.phases[3].start);
  const at = (hour: number) => Math.min(Math.max(hour, now.hour), cutoff);
  let phase: PlanningPhaseId = now.hour >= plan.phases[3].start ? "P3" : now.phase;
  let p1Start = now.hour;
  if (phase === "P0") {
    const dryback = parameters.dryback_target;
    const level =
      now.peak !== null && Number.isFinite(dryback) ? now.peak * (1 - dryback / 100) : null;
    p1Start = at(
      now.value <= threshold
        ? now.hour
        : Math.min(
            now.since + (hours("p0_maximum_wait_time") ?? 1),
            level === null ? Infinity : now.hour + Math.max(0, now.value - level) / rates.day,
          ),
    );
  }
  // A ramp already at its target, or out of shots, hands over to P2.
  const rampFrom = phase === "P0" ? now.value - rates.day * (p1Start - now.hour) : now.value;
  const rampDone =
    rampFrom >= target || (phase === "P1" && maxShots !== null && now.p1Shots >= maxShots);
  const done = phase === "P1" ? now.p1Shots : 0,
    windows: number[] = [];
  let p1End = p1Start;
  if ((phase === "P0" || phase === "P1") && !rampDone) {
    if (interval !== null && maxShots !== null) {
      const first =
        phase === "P1" && now.lastShot !== null
          ? Math.max(now.hour, now.lastShot + interval)
          : p1Start;
      for (let index = 0; index < maxShots - done && first + index * interval < cutoff; index++)
        windows.push(first + index * interval);
      p1End = at(windows.length ? windows.at(-1)! + interval : first);
    } else p1End = at(p1Start + 2); // buildPlanningCurve's layout window without count or spacing
  }
  if (phase === "P1" && rampDone) phase = "P2";
  const p2Start = phase === "P2" ? now.hour : p1End;
  const run = runPhases(plan, parameters, rates, retention, {
    phase,
    value: now.value,
    phases: [
      { start: now.hour, end: p1Start },
      { start: phase === "P1" ? now.hour : p1Start, end: p1End },
      { start: p2Start, end: Math.max(p2Start, cutoff) },
      { start: phase === "P3" ? now.hour : cutoff, end },
    ],
    p1Windows: windows,
    p1Done: done,
    jump: interval === null || maxShots === null,
  });
  const peak = Math.max(...run.points.map((point) => point.value));
  const dryback = parameters.dryback_target;
  return {
    points: run.points,
    shots: run.shots,
    lightsOnVwc: run.value,
    peak,
    drybackVwc: Number.isFinite(dryback) ? peak * (1 - dryback / 100) : null,
    rates,
    measured,
    retention,
  };
}

/** Recorder rows thinned to one median per time bucket. Probe jitter (pore EC flickers every few
 * seconds) goes; a shot, which moves the reading for many minutes, stays. The final reading is kept
 * exactly, so "now" is the live value. */
export function smoothRecorded(
  readings: readonly RecordedReading[],
  bucketMinutes = 10,
): RecordedReading[] {
  const size = bucketMinutes * 60_000;
  const buckets = new Map<number, RecordedReading[]>();
  for (const reading of readings) {
    if (!Number.isFinite(reading.time) || !Number.isFinite(reading.value)) continue;
    const key = Math.floor(reading.time / size);
    const bucket = buckets.get(key) ?? [];
    bucket.push(reading);
    buckets.set(key, bucket);
  }
  const smoothed = [...buckets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([, bucket]) => {
      const byValue = [...bucket].sort((a, b) => a.value - b.value);
      return { time: bucket[bucket.length >> 1].time, value: byValue[byValue.length >> 1].value };
    });
  const last = readings.reduce<RecordedReading | null>(
    (latest, reading) =>
      Number.isFinite(reading.time) &&
      Number.isFinite(reading.value) &&
      reading.time >= (latest?.time ?? -Infinity)
        ? reading
        : latest,
    null,
  );
  if (last && smoothed.length)
    smoothed[smoothed.length - 1] = { time: last.time, value: last.value };
  return smoothed;
}

export interface P2Advice {
  shots: number;
  firstShotHour: number | null;
  /** VWC points from the start of P2 down to the threshold, and the hours that takes to dry. */
  pointsToThreshold: number;
  hoursToThreshold: number;
  /** A threshold a point under where P2 starts: a sawtooth from the start of P2. */
  suggestedThreshold: number;
  /** Hours between shots once the zone sits at its threshold: one shot's lift at the dry-down rate. */
  repeatHours: number;
}
/** Why P2 shows few or no shots, and the threshold that would give them. Null when maintenance is
 * already under way by the middle of P2. The engine fires a P2 shot only once VWC has fallen to the
 * threshold, so a threshold far under the P1 target spends the whole window just drying down. */
export function p2Advice(
  plan: PlanningModel,
  parameters: Record<string, number>,
  projection: PlanningProjection,
): P2Advice | null {
  const window = plan.phases[2];
  const threshold = parameters.p2_vwc_threshold;
  const start = projection.points.find((point) => point.phase === "P2");
  if (!start || window.end <= window.start || !Number.isFinite(threshold)) return null;
  const shots = projection.shots.filter((shot) => shot.phase === "P2");
  const firstShotHour = shots[0]?.hour ?? null;
  if (firstShotHour !== null && firstShotHour - window.start <= (window.end - window.start) / 2)
    return null;
  const size = parameters.p2_shot_size;
  const lift = (Number.isFinite(size) && size > 0 ? size : 2) * projection.retention;
  const pointsToThreshold = Math.max(0, start.value - threshold);
  return {
    shots: shots.length,
    firstShotHour,
    pointsToThreshold,
    hoursToThreshold: pointsToThreshold / projection.rates.day,
    suggestedThreshold: Math.max(threshold, Math.floor((start.value - 1) * 2) / 2),
    repeatHours: lift / projection.rates.day,
  };
}
