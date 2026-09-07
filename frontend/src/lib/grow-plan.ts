import type {
  GrowPlan,
  ParameterLimit,
  ScheduleBlock,
  SteeringProfile,
  ZonePlan,
} from "./operator-types";

export const parameterLabels: Record<string, string> = {
  dryback_target: "Morning dryback",
  ec_target_p0: "P0 EC target",
  ec_target_p1: "P1 EC target",
  ec_target_p2: "P2 EC target",
  p1_target_vwc: "P1 moisture target",
  p2_vwc_threshold: "P2 moisture trigger",
  p1_initial_shot_size: "First shot size",
  p2_shot_size: "Maintenance shot size",
  p3_emergency_vwc_threshold: "Overnight emergency floor",
  p3_emergency_shot_size: "Emergency shot size",
  p0_maximum_wait_time: "Latest first irrigation",
  p1_time_between_shots: "Ramp-up interval",
  p1_maximum_shots: "Maximum ramp-up shots",
  p1_shot_size_increment: "Ramp-up shot increase",
  max_daily_volume: "Daily water limit",
  maximum_ec: "Maximum substrate EC",
  field_capacity: "Substrate field capacity",
  watchdog_hours: "Watchdog interval",
};
export const parameterHelp: Record<string, string> = {
  dryback_target:
    "Relative drop from the detected peak before ramp-up can start. At 60% peak VWC, a 10% dryback target is 54% VWC.",
  ec_target_p0: "Root-zone EC reference for morning dryback. It does not set tank dosing.",
  ec_target_p1: "Root-zone EC reference during ramp-up. Keep feed-water EC and pore EC distinct.",
  ec_target_p2: "Root-zone EC reference used for maintenance steering.",
  p1_target_vwc: "Moisture level at which morning ramp-up finishes.",
  p2_vwc_threshold: "Base trigger for maintenance watering; the engine may adjust it for EC.",
  p1_initial_shot_size:
    "First shot as a percentage of substrate volume. Hydraulic preview uses pot size and dripper flow.",
  p2_shot_size: "Each maintenance shot as a percentage of substrate volume.",
  p3_emergency_vwc_threshold:
    "Emergency-only floor during the overnight phase, not a routine daytime target.",
  p3_emergency_shot_size: "Rescue shot size when the overnight floor is crossed.",
};
export function localDate(date = new Date()): string {
  return (
    String(date.getFullYear()) +
    "-" +
    String(date.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(date.getDate()).padStart(2, "0")
  );
}
export function validDate(value: string): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value + "T00:00:00Z").toISOString().slice(0, 10) === value
  );
}
export function growDay(start: string, date: string): number {
  return (
    Math.floor((Date.parse(date + "T00:00:00Z") - Date.parse(start + "T00:00:00Z")) / 86400000) + 1
  );
}
export function dateForDay(start: string, day: number): string {
  if (!validDate(start) || !Number.isInteger(day)) return "";
  return new Date(Date.parse(start + "T00:00:00Z") + (day - 1) * 86400000)
    .toISOString()
    .slice(0, 10);
}
export function blockForDay(zone: ZonePlan | undefined, day: number): ScheduleBlock | undefined {
  return zone?.schedule.find((block) => day >= block.start_day && day <= block.end_day);
}
export function replaceRange(schedule: ScheduleBlock[], block: ScheduleBlock): ScheduleBlock[] {
  const remaining = schedule.flatMap((old) => {
    if (old.end_day < block.start_day || old.start_day > block.end_day) return [old];
    return [
      ...(old.start_day < block.start_day ? [{ ...old, end_day: block.start_day - 1 }] : []),
      ...(old.end_day > block.end_day ? [{ ...old, start_day: block.end_day + 1 }] : []),
    ];
  });
  return [...remaining, block].sort((a, b) => a.start_day - b.start_day);
}
export function interpolate(
  profile: SteeringProfile | undefined,
  bias: number,
  catalog: Record<string, ParameterLimit> = {},
): Record<string, number> {
  if (!profile || !Number.isFinite(bias) || bias < 0 || bias > 100) return {};
  return Object.fromEntries(
    Object.entries(profile.vegetative).flatMap(([key, vegetative]) => {
      const generative = profile.generative[key];
      if (!Number.isFinite(vegetative) || !Number.isFinite(generative)) return [];
      const limit = catalog[key];
      let value = vegetative + ((generative - vegetative) * bias) / 100;
      if (limit?.step > 0)
        value = limit.min + Math.round((value - limit.min) / limit.step) * limit.step;
      return [[key, Math.round(value * 1e6) / 1e6]];
    }),
  );
}
export function planErrors(
  plan: GrowPlan,
  catalog: Record<string, Record<string, ParameterLimit>>,
): string[] {
  const errors: string[] = [];
  if (plan.schema_version !== 1 || !Array.isArray(plan.profiles) || !Array.isArray(plan.zones))
    return ["Unsupported plan format."];
  if (!plan.profiles.length) errors.push("Add at least one endpoint profile.");
  const expectedZones = Object.keys(catalog)
    .map(Number)
    .sort((a, b) => a - b);
  const plannedZones = plan.zones.map((zone) => zone.zone_id).sort((a, b) => a - b);
  if (JSON.stringify(expectedZones) !== JSON.stringify(plannedZones))
    errors.push("Update zone assignments to include every active setup zone exactly once.");
  const profiles = new Map(plan.profiles.map((p) => [p.id, p]));
  if (profiles.size !== plan.profiles.length) errors.push("Profile IDs must be unique.");
  const zoneIds = new Set<number>();
  for (const zone of plan.zones) {
    if (zoneIds.has(zone.zone_id)) errors.push("A zone can have only one plan.");
    zoneIds.add(zone.zone_id);
    if (!validDate(zone.start_date))
      errors.push("Zone " + zone.zone_id + ": choose a valid grow start date.");
    let last = 0;
    for (const block of [...zone.schedule].sort((a, b) => a.start_day - b.start_day)) {
      if (
        ![block.start_day, block.end_day].every(Number.isInteger) ||
        block.start_day < 1 ||
        block.end_day < block.start_day ||
        block.end_day > 366
      )
        errors.push("Zone " + zone.zone_id + ": ranges must use grow days 1-366.");
      if (block.start_day <= last) errors.push("Zone " + zone.zone_id + ": date ranges overlap.");
      if (block.start_day > last + 1)
        errors.push(
          "Zone " + zone.zone_id + ": fill the unscheduled gap before day " + block.start_day + ".",
        );
      last = block.end_day;
      if (!Number.isFinite(block.bias) || block.bias < 0 || block.bias > 100)
        errors.push("Steering must be between 0 and 100.");
      const profile = profiles.get(block.profile_id);
      if (!profile) {
        errors.push("A schedule references a missing profile.");
        continue;
      }
      const a = Object.keys(profile.vegetative).sort().join(),
        b = Object.keys(profile.generative).sort().join();
      if (!a || a !== b) errors.push(profile.name + ": both endpoints need matching parameters.");
      const limits = catalog[String(zone.zone_id)] || {};
      for (const side of ["vegetative", "generative"] as const)
        for (const [key, value] of Object.entries(profile[side])) {
          const limit = limits[key];
          if (!limit || !Number.isFinite(value) || value < limit.min || value > limit.max)
            errors.push(
              profile.name +
                ": " +
                (parameterLabels[key] || key) +
                " must fit Zone " +
                zone.zone_id +
                " limits.",
            );
        }
    }
    if (!zone.schedule.length) errors.push("Zone " + zone.zone_id + ": add a schedule.");
  }
  return [...new Set(errors)];
}
export function parsePlanImport(text: string): GrowPlan {
  if (text.length > 500000) throw new Error("Plan file is too large.");
  const parsed = JSON.parse(text);
  const plan = parsed.plan || parsed;
  if (
    plan.schema_version !== 1 ||
    !Array.isArray(plan.profiles) ||
    !Array.isArray(plan.zones) ||
    plan.profiles.length > 100 ||
    plan.zones.length > 24
  )
    throw new Error("Choose a version 1 Crop Steering plan.");
  for (const p of plan.profiles)
    if (
      !p ||
      typeof p.id !== "string" ||
      typeof p.name !== "string" ||
      !p.vegetative ||
      !p.generative ||
      typeof p.vegetative !== "object" ||
      typeof p.generative !== "object"
    )
      throw new Error("Invalid endpoint profile.");
  for (const z of plan.zones)
    if (
      !z ||
      !Number.isInteger(z.zone_id) ||
      typeof z.start_date !== "string" ||
      !Array.isArray(z.schedule) ||
      z.schedule.length > 366 ||
      z.schedule.some(
        (b: ScheduleBlock) =>
          !b ||
          typeof b.profile_id !== "string" ||
          ![b.start_day, b.end_day, b.bias].every(Number.isFinite),
      )
    )
      throw new Error("Invalid zone schedule.");
  return structuredClone(plan);
}
