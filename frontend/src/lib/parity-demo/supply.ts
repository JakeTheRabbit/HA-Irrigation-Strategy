import type { PumpCheck, SupplyDoc } from "../parity-types";
import type { States } from "../types";

/** The demo's supply (G1), kept as the integration keeps it (site_api.py, site_store.py): one
 * site-wide document with a revision, supply_get answering it with a capacity check worked out from
 * each room's zone sizing, supply_save refusing a stale revision or a pump set to feed more zones
 * at once than it can, and a save publishing sensor.crop_steering_supply_config with each active
 * zone's demand in L/h. Room A's pump starts at 1200 L/h, one zone at a time. */

export interface DemoSupplyRoom {
  room_id: string;
  pump: string;
  /** Each active zone's demand in L/h. */
  zones: Record<string, number>;
}
type Section = Pick<SupplyDoc, "irrigation_pumps" | "water_sources" | "zone_groups" | "zone_meters">;

const START: Section & { revision: number } = {
  revision: 1,
  irrigation_pumps: [{ entity_id: "switch.demo_pump", max_flow_lph: 1200, max_concurrent_zones: 1, flow_meter: null }],
  water_sources: [],
  zone_groups: {},
  zone_meters: {},
};
let stored = structuredClone(START);
export function resetDemoSupply(): void {
  stored = structuredClone(START);
}
export const SUPPLY_SENSOR = "sensor.crop_steering_supply_config";

/** generated/guards.py worst_case_lph: the largest total over `count` zones, one per group. */
function worstCase(demands: number[], groups: (string | undefined)[], count: number) {
  const free: number[] = [];
  const largest = new Map<string, number>();
  demands.forEach((lph, i) => {
    const g = groups[i];
    if (!g) free.push(lph);
    else largest.set(g, Math.max(largest.get(g) ?? 0, lph));
  });
  return [...free, ...largest.values()].sort((a, b) => b - a).slice(0, Math.max(count, 0)).reduce((s, x) => s + x, 0);
}

/** site_store.capacity_check. */
export function demoCapacityCheck(section: Section, rooms: DemoSupplyRoom[]): SupplyDoc["capacity_check"] {
  const rows: PumpCheck[] = [];
  const pairs: SupplyDoc["capacity_check"]["pairs"] = [];
  for (const pump of section.irrigation_pumps) {
    const members = rooms
      .filter((r) => r.pump === pump.entity_id)
      .flatMap((r) => Object.entries(r.zones).map(([zone, lph]) => ({ room: r.room_id, zone: Number(zone), lph })))
      .sort((a, b) => a.room.localeCompare(b.room) || a.zone - b.zone);
    const demands = members.map((m) => m.lph);
    const groups = members.map((m) => section.zone_groups[m.room]?.[String(m.zone)]);
    const max = pump.max_flow_lph ?? null;
    const concurrent = pump.max_concurrent_zones;
    let suggest: number | null = null;
    if (max !== null && demands.length) {
      suggest = 1;
      for (let n = 2; n <= demands.length && worstCase(demands, groups, n) <= max; n++) suggest = n;
    }
    const worst = worstCase(demands, groups, concurrent);
    rows.push({ entity_id: pump.entity_id, worst_case_lph: worst, max_flow_lph: max, max_concurrent_zones: concurrent, ok: max === null || worst <= max, suggest_max_concurrent: suggest });
    for (let a = 0; a < members.length; a++)
      for (let b = a + 1; b < members.length; b++) {
        const lph = demands[a] + demands[b];
        const shared = !!groups[a] && groups[a] === groups[b];
        const sameRoom = members[a].room === members[b].room;
        pairs.push({
          zones: sameRoom ? [members[a].zone, members[b].zone] : [a, b].map((i) => ({ room_id: members[i].room, zone: members[i].zone })),
          lph,
          pct_of_pump: max === null ? null : (lph / max) * 100,
          verdict: shared || concurrent < 2 || (max !== null && lph > max) ? "one_after_another" : "together",
        } as SupplyDoc["capacity_check"]["pairs"][number]);
      }
  }
  const head = rows.find((r) => !r.ok) ?? [...rows].sort((a, b) => b.worst_case_lph - a.worst_case_lph)[0];
  return {
    worst_case_lph: head?.worst_case_lph ?? 0,
    max_flow_lph: head?.max_flow_lph ?? null,
    ok: rows.every((r) => r.ok),
    suggest_max_concurrent: head?.suggest_max_concurrent ?? null,
    pairs,
    pumps: rows,
  };
}

const refusal = (code: string, message: string, current_revision?: number) => ({
  api: 2,
  ok: false,
  error: { code, message, ...(current_revision === undefined ? {} : { current_revision }) },
});

function publish(states: States, rooms: DemoSupplyRoom[], now: number): States {
  return {
    ...states,
    [SUPPLY_SENSOR]: {
      entity_id: SUPPLY_SENSOR,
      state: String(stored.revision),
      attributes: {
        friendly_name: "Crop Steering supply",
        irrigation_pumps: structuredClone(stored.irrigation_pumps),
        zone_groups: structuredClone(stored.zone_groups),
        zone_meters: structuredClone(stored.zone_meters),
        zone_demand_lph: Object.fromEntries(rooms.filter((r) => Object.keys(r.zones).length).map((r) => [r.room_id, { ...r.zones }])),
      },
      last_updated: new Date(now).toISOString(),
    },
  };
}

/** supply_get / supply_save. Returns the v2 answer (envelope added by the caller for a success) and
 * the states to publish, if any. */
export function answerSupply(
  action: "supply_get" | "supply_save",
  data: Record<string, unknown>,
  rooms: DemoSupplyRoom[],
  states: States,
  now: number,
): { answer: unknown; states?: States } {
  const response = () => ({ ...structuredClone(stored), capacity_check: demoCapacityCheck(stored, rooms), warnings: [], error: null });
  if (action === "supply_get") return { answer: response(), states: states[SUPPLY_SENSOR] ? undefined : publish(states, rooms, now) };
  if (data.expected_revision !== stored.revision)
    return { answer: refusal("stale_revision", "Supply settings changed elsewhere. Reload before saving.", stored.revision) };
  const pumps = data.irrigation_pumps;
  if (!Array.isArray(pumps)) return { answer: refusal("invalid", "irrigation_pumps must be a list") };
  for (const p of pumps as Record<string, unknown>[]) {
    const flow = p.max_flow_lph;
    if (flow != null && !(typeof flow === "number" && flow > 0))
      return { answer: refusal("invalid", `${String(p.entity_id)}: max_flow_lph must be more than 0`) };
    const n = p.max_concurrent_zones;
    if (!(Number.isInteger(n) && (n as number) >= 1 && (n as number) <= 24))
      return { answer: refusal("invalid", `${String(p.entity_id)}: max_concurrent_zones must be a whole number from 1 to 24`) };
  }
  const section: Section = {
    irrigation_pumps: (pumps as SupplyDoc["irrigation_pumps"]).map((p) => ({
      entity_id: p.entity_id,
      max_flow_lph: p.max_flow_lph ?? null,
      max_concurrent_zones: p.max_concurrent_zones,
      flow_meter: p.flow_meter ?? null,
    })),
    water_sources: stored.water_sources,
    zone_groups: (data.zone_groups as Section["zone_groups"]) ?? stored.zone_groups,
    zone_meters: (data.zone_meters as Section["zone_meters"]) ?? stored.zone_meters,
  };
  const check = demoCapacityCheck(section, rooms);
  if (data.preview) return { answer: { diff: [], capacity_check: check } };
  const over = check.pumps!.find((r) => !r.ok && r.max_concurrent_zones >= 2);
  if (over)
    return {
      answer: refusal(
        "invalid",
        `pump_over_capacity: ${over.entity_id} cannot feed ${over.max_concurrent_zones} zones at once: the worst mix needs ${over.worst_case_lph} L/h and the pump gives ${over.max_flow_lph} L/h. Set Zones at once to ${over.suggest_max_concurrent ?? "None"} or less.`,
      ),
    };
  stored = { ...structuredClone(section), revision: stored.revision + 1 };
  return { answer: { ...response(), readback: { status: "ok", at: new Date(now).toISOString(), entity_id: SUPPLY_SENSOR } }, states: publish(states, rooms, now) };
}
