import type { GrowPlan, ParameterLimit } from "./operator-types";

/** Explicit draft edit only. Never alters the stored plan or selects crop targets. */
export function syncPlanZones(
  plan: GrowPlan,
  activeZoneIds: number[],
  catalog: Record<string, Record<string, ParameterLimit>>,
  startDate: string,
) {
  const next = structuredClone(plan);
  const ids = [...new Set(activeZoneIds)].sort((a, b) => a - b);
  const removed = next.zones
    .filter((zone) => !ids.includes(zone.zone_id))
    .map((zone) => zone.zone_id);
  next.zones = next.zones.filter((zone) => ids.includes(zone.zone_id));
  const added: number[] = [],
    unseeded: number[] = [];
  for (const zoneId of ids) {
    if (next.zones.some((zone) => zone.zone_id === zoneId)) continue;
    const values = Object.fromEntries(
      Object.entries(catalog[String(zoneId)] || {}).flatMap(([key, field]) =>
        typeof field.value === "number" && Number.isFinite(field.value) ? [[key, field.value]] : [],
      ),
    );
    const base = "zone-" + zoneId + "-current";
    let profileId = base,
      suffix = 2;
    while (next.profiles.some((profile) => profile.id === profileId))
      profileId = base + "-" + suffix++;
    next.profiles.push({
      id: profileId,
      name: "Zone " + zoneId + " current values",
      vegetative: { ...values },
      generative: { ...values },
    });
    next.zones.push({
      zone_id: zoneId,
      start_date: startDate,
      schedule: [{ start_day: 1, end_day: 84, profile_id: profileId, bias: 50 }],
    });
    added.push(zoneId);
    if (!Object.keys(values).length) unseeded.push(zoneId);
  }
  next.zones.sort((a, b) => a.zone_id - b.zone_id);
  return { plan: next, added, removed, unseeded };
}
