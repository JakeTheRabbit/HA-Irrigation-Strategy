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
export interface PlanningModel {
  phases: PlanningPhase[];
  vwc: PlanningPoint[];
  ec: PlanningPoint[];
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
      "P1 target is used as the dryback reference because field capacity was not supplied.",
    );
  const morningDryback =
    reference !== null && dryback !== null ? reference * (1 - dryback / 100) : null;
  if (p1 === null) missing.push("P1 VWC target");
  if (p2 === null) missing.push("P2 VWC threshold");
  if (morningDryback === null) missing.push("Dryback target/reference");
  if (p1 !== null && p2 !== null && p2 > p1)
    warnings.push("P2 maintenance threshold is above the P1 ramp-up target.");
  const wait = value("p0_maximum_wait_time", 0, 1440);
  const interval = value("p1_time_between_shots", 0, 1440);
  const maxShots = value("p1_maximum_shots", 0, 200);
  if (wait === null)
    notes.push("P0 is drawn as a 1-hour layout window; a maximum wait was not supplied.");
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
    { id: "P0", label: "Morning wait", start: 0, end: p0End, color: "#8f9aa6" },
    { id: "P1", label: "Ramp-up", start: p0End, end: p1End, color: "#03a9f4" },
    { id: "P2", label: "Maintenance", start: p1End, end: p3Start, color: "#42b995" },
    { id: "P3", label: "Overnight", start: p3Start, end: 24, color: "#e5a43b" },
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
      "The overnight reference reaches or crosses the P3 emergency floor. Emergency protection would be relevant at that reading; the chart does not predict or schedule an emergency shot.",
    );
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
    "Overnight VWC is a straight planning connection from the last daytime reference to the relative dryback endpoint, then the same value at next lights-on. P0's maximum-wait window is shown at that endpoint. Neither timing nor measured moisture is forecast. The emergency floor is separate, not a desired overnight target.",
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
      "P2 threshold plus nominal shot exceeds 100% VWC; the illustrated band is clipped at 100%.",
    );
  return {
    phases,
    vwc,
    ec,
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
