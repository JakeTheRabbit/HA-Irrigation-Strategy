import * as z from "zod/v4";
import tables from "./integration-tables.json" with { type: "json" };

export const roomId = z
  .string()
  .regex(/^room:(?:[a-z0-9_]+_)?$/)
  .max(100);
export const entityId = z
  .string()
  .regex(/^[a-z_]+\.[a-z0-9_]+$/)
  .max(255);
const mapping = z.union([entityId, z.literal("")]);
const name = z.string().trim().min(1).max(80);
// The mapping tables are the integration's own (setup_api.py), written to JSON by
// scripts/render_mcp_tables.py; tests/test_mcp_tables.py fails when the JSON is stale.
export const hardwareDomains: Record<string, string[]> =
  tables.hardware_domains;
export const actuatorDomains: string[] = tables.actuator_domains;
export const sensorKinds: Record<string, string> = tables.sensor_kinds;
export const probeUnits: Record<string, string[]> = tables.units;
export const hardware = z.strictObject(
  Object.fromEntries(
    Object.keys(hardwareDomains).map((key) => [key, mapping.optional()]),
  ),
);
// Legacy native forms store unset mappings as null; normalize response data only.
const storedMapping = mapping.nullable().transform((value) => value ?? "");
const storedHardware = z.object(
  Object.fromEntries(
    Object.keys(hardwareDomains).map((key) => [key, storedMapping.optional()]),
  ),
);
const sizing = {
  plant_count: z.number().int().min(1).max(1000).optional(),
  substrate_volume: z.number().min(0.1).max(200).optional(),
  drippers_per_plant: z.number().int().min(1).max(20).optional(),
  dripper_flow_rate: z.number().min(0.1).max(50).optional(),
};
export const zonePatch = z.strictObject({
  id: z.number().int().min(1).max(64),
  name: name.optional(),
  valve: mapping.optional(),
  vwc_sensors: z.array(entityId).max(32).optional(),
  ec_sensors: z.array(entityId).max(32).optional(),
  ...sizing,
});
// How a room is plumbed: layout -> [has a pump switch, has a main-line valve]. The integration
// DECLARES this (custom_components/crop_steering/plumbing.py, same table) and refuses a save
// whose mapped switches contradict it, so a change to one has to travel with the other.
export const plumbingLayouts = {
  valves_only: [false, false],
  pump_valves: [true, false],
  mainline_valves: [false, true],
  pump_mainline_valves: [true, true],
} as const;
export const plumbing = z.enum(
  Object.keys(plumbingLayouts) as [
    keyof typeof plumbingLayouts,
    ...(keyof typeof plumbingLayouts)[],
  ],
);
export const setupChanges = z.strictObject({
  room_name: name.optional(),
  plumbing: plumbing.optional(),
  hardware: hardware.optional(),
  zones: z.array(zonePatch).max(64).optional(),
});
export const zone = z.object({
  id: z.number().int().min(1).max(64),
  name,
  active: z.boolean(),
  valve: storedMapping,
  vwc_sensors: z.array(entityId).max(32),
  ec_sensors: z.array(entityId).max(32),
  ...sizing,
});
export const room = z.object({
  entry_id: z.string().min(1).max(100),
  revision: z.number().int().nonnegative(),
  prefix: z
    .string()
    .regex(/^(?:[a-z0-9_]+_)?$/)
    .max(95),
  slug: z.string().max(100),
  room_name: name,
  active: z.boolean(),
  // "" = never declared; absent = an integration from before declared plumbing (2.19.0).
  plumbing: z.union([plumbing, z.literal("")]).optional(),
  plumbing_inferred: plumbing.optional(),
  zones: z.array(zone).min(1).max(64),
  hardware: storedHardware,
  safety: z.object({
    ready: z.boolean(),
    blockers: z.array(z.string().max(1000)).max(1000),
  }),
});
export type Room = z.infer<typeof room>;
export type SetupChanges = z.infer<typeof setupChanges>;
export const candidate = z.object({
  entity_id: entityId,
  name: z.string().max(500),
  domain: z.string().max(40),
  state: z.string().max(1000),
  unit: z.string().nullable().optional(),
  device_class: z.string().nullable().optional(),
});
export const setupResponse = z.object({
  api_version: z.literal(1),
  rooms: z.array(room).max(1000),
  candidates: z.array(candidate).max(50000),
});
const number = z.number();
const required = {
  dryback_target: number,
  ec_target_p0: number,
  ec_target_p1: number,
  ec_target_p2: number,
  p1_target_vwc: number,
  p2_vwc_threshold: number,
  p2_shot_size: number,
  p1_initial_shot_size: number,
  p3_emergency_vwc_threshold: number,
  p3_emergency_shot_size: number,
};
export const parameters = z.strictObject({
  ...required,
  p1_shot_size_increment: number.optional(),
  p1_maximum_shots: number.int().optional(),
  p1_time_between_shots: number.optional(),
  p0_maximum_wait_time: number.optional(),
  max_daily_volume: number.optional(),
  field_capacity: number.optional(),
  maximum_ec: number.optional(),
  watchdog_hours: number.optional(),
});
const identifier = z.string().regex(/^[a-zA-Z0-9_-]{1,64}$/);
export const date = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/)
  .refine((value) => {
    const parsed = new Date(value + "T00:00:00Z");
    return (
      Number.isFinite(parsed.getTime()) &&
      parsed.toISOString().slice(0, 10) === value
    );
  }, "Use a valid YYYY-MM-DD calendar date");
export const plan = z.strictObject({
  schema_version: z.literal(1),
  profiles: z
    .array(
      z.strictObject({
        id: identifier,
        name: z.string().min(1).max(100),
        vegetative: parameters,
        generative: parameters,
      }),
    )
    .min(1)
    .max(64),
  zones: z
    .array(
      z.strictObject({
        zone_id: z.number().int().min(1).max(64),
        start_date: date,
        schedule: z
          .array(
            z.strictObject({
              start_day: z.number().int().min(1).max(366),
              end_day: z.number().int().min(1).max(366),
              profile_id: identifier,
              bias: z.number().min(0).max(100),
            }),
          )
          .min(1)
          .max(366),
      }),
    )
    .min(1)
    .max(64),
});
export type Plan = z.infer<typeof plan>;

// API v2 answers (custom_components/crop_steering/api_v2.py, docs/MCP.md). Loose throughout: a
// field the integration adds later passes through; only what these tools use is checked.
export const v2Answer = z.looseObject({
  api: z.literal(2),
  ok: z.boolean(),
  data: z.unknown().optional(),
  error: z
    .looseObject({ code: z.string().max(100), message: z.string() })
    .optional(),
});
const row = z.looseObject({});
const roomRow = z.looseObject({ room_id: roomId });
// journal_query (journal.py query): a page of at most 500 events and the next page's cursor.
export const journalPage = z.looseObject({
  events: z.array(row).max(500),
  cursor: z.string().max(100).nullable(),
});
// timeline_get (timeline.py build).
export const timeline = z.looseObject({
  rooms: z.array(roomRow).max(1000),
  errors: z.looseObject({ count: z.number().int().nonnegative() }),
  truncated: z.boolean().optional(),
});
// timeline_summary (timeline.py summarise): at most 14 local days.
export const timelineSummary = z.looseObject({
  days: z
    .array(z.looseObject({ date, rooms: z.array(roomRow).max(1000) }))
    .max(14),
});
// history_changes (journal_api.py, changes.py): at most 2000 rows, `truncated` when it cut.
export const changeKinds = [
  "setpoint",
  "plan",
  "recipe",
  "setup",
  "calibration",
  "alerts",
] as const;
export const changes = z.looseObject({
  changes: z.array(row).max(2000),
  truncated: z.boolean().optional(),
});
// supply_get (site_api.py SiteStore.response): the site's supply, revision 0 until saved.
export const supply = z.looseObject({
  revision: z.number().int().nonnegative(),
});
// system_status_get (system_status.py status).
export const systemStatus = z.looseObject({
  controller: z.string().max(40),
  rooms: z.array(roomRow).max(1000),
});
// alert_rule_list (site_api.py RuleEvaluator.listing).
export const alertRules = z.looseObject({
  rules: z.array(
    z.looseObject({ id: z.string().max(100), room_id: z.string().max(100) }),
  ),
});
// The journal's source.actor values (spec section 4).
export const actors = [
  "engine",
  "timer",
  "plan",
  "manual",
  "ai",
  "learner",
  "safety",
  "mcp",
  "aigrow",
  "automation",
  "system",
] as const;

// Previewed writes (Task 31). Inputs are strict; answers are loose like the reads above.
const clock = z.string().regex(/^([01]?\d|2[0-3]):[0-5]\d$/, "Use HH:MM");
// A timer's or an alert rule's window (generated/timers.py KINDS, alert_rules.clean_window).
const window = z.discriminatedUnion("kind", [
  z.strictObject({ kind: z.enum(["all", "lights_on", "lights_off"]) }),
  z.strictObject({ kind: z.literal("custom"), from: clock, to: clock }),
]);
const zoneList = z
  .array(z.number().int().min(1).max(64))
  .max(64)
  .refine((zones) => new Set(zones).size === zones.length, "zones must be unique");
const recordId = z.string().regex(/^[A-Za-z0-9_-]{1,64}$/);
// timers_api / generated/timers.validate, with the schema field names (G7).
export const timerProgram = z.strictObject({
  id: recordId.optional(),
  name,
  type: z.enum(["one_off", "recycle", "simple"]),
  zones: zoneList.min(1),
  duration_s: z.number().positive().max(86400),
  active: z.boolean().optional(),
  window: window.optional(),
  sync_time: clock.optional(),
  interval_min: z.number().min(1).max(1440).optional(),
  frequency_per_day: z.number().int().min(1).max(1440).optional(),
  start_at: z.string().trim().min(1).max(64).optional(),
});
export type TimerProgram = z.infer<typeof timerProgram>;
// alert_rules.validate_rule; the room comes from the tool's room_id.
export const alertRule = z.strictObject({
  id: recordId.optional(),
  zones: zoneList.optional(),
  source: z.string().regex(/^[a-z]+\.[a-z_]+$/).max(64),
  op: z.enum(["above", "below"]),
  threshold: z.number(),
  min_duration_s: z.number().int().min(0).max(86400).optional(),
  severity: z.enum(["info", "warning", "emergency"]).optional(),
  routing: z.string().regex(/^[a-z_]+$/).max(64).optional(),
  active: z.boolean().optional(),
  window: window.optional(),
  entity_id: entityId.optional(),
  tank_id: z.string().min(1).max(100).optional(),
});
export type AlertRule = z.infer<typeof alertRule>;
// supply_save (site_store.clean_*): zone maps nest the zone number as text under the room id (R9).
const byZone = <T extends z.ZodType>(value: T) =>
  z.record(roomId, z.record(z.string().regex(/^[1-9]\d?$/), value));
export const supplyChanges = z.strictObject({
  irrigation_pumps: z
    .array(
      z.strictObject({
        entity_id: entityId,
        max_flow_lph: z.number().positive().nullable().optional(),
        max_concurrent_zones: z.number().int().min(1).max(64).optional(),
        flow_meter: entityId.nullable().optional(),
      }),
    )
    .max(32),
  water_sources: z.array(z.record(z.string(), z.unknown())).max(32).optional(),
  zone_groups: byZone(z.string().regex(/^[A-Za-z0-9_-]{1,24}$/)).optional(),
  zone_meters: byZone(entityId).optional(),
});
export type SupplyChanges = z.infer<typeof supplyChanges>;
export const probeOffset = z
  .strictObject({
    room_id: roomId,
    entity_id: entityId,
    offset: z.number().min(-20).max(20).optional(),
    curve: z.string().regex(/^[a-z_]+$/).max(40).optional(),
    match_handheld: z.number().min(0).max(100).optional(),
  })
  .refine(
    (value) => ["offset", "curve", "match_handheld"].some((key) => key in value),
    "Give an offset, a curve or a handheld reading to match",
  )
  .refine(
    (value) => !("offset" in value && "match_handheld" in value),
    "Give an offset or a handheld reading to match, not both",
  );
export type ProbeOffset = z.infer<typeof probeOffset>;
// presets.SECTIONS.
export const sections = z
  .array(z.enum(["targets", "phase_timing", "water_limits", "timers"]))
  .min(1)
  .max(4);
export const source = z.strictObject({
  room_id: roomId,
  zone: z.number().int().min(1).max(64).optional(),
});

// timer_program_list (timers_api.list_programs) for one room.
export const timerPrograms = z.looseObject({
  programs: z.array(z.looseObject({ id: z.string().max(100), room_id: roomId })).max(1000),
  revision: z.number().int().nonnegative(),
  error: z.string().nullable().optional(),
});
// alert_rule_list with the alert rules revision alert_rule_set takes.
export const revisionedRules = alertRules.extend({
  revision: z.number().int().nonnegative(),
});
// supply_save with preview (SiteStore.save).
export const supplyPreview = z.looseObject({
  diff: z.array(row).max(10000),
  capacity_check: z.unknown(),
});
const diffRow = z.looseObject({ path: z.string().max(1000) });
// probe_offset_set (calibration.probe_offset_set): the fix it works out and the store's revision.
export const probeAnswer = z.looseObject({
  offset: z.number(),
  curve: z.string().nullable(),
  revision: z.number().int().nonnegative(),
  diff: z.array(diffRow).max(1000).optional(),
});
// preset_apply / copy_config (presets.apply): `missing` holds a key with no entity and a refused
// timer row (with its reason), never written and never in `diff`.
const targetRow = z.looseObject({
  target: z.looseObject({ room_id: z.string().max(100) }),
  key: z.string().max(100),
});
export const presetAnswer = z.looseObject({
  diff: z.array(targetRow).max(10000),
  missing: z.array(targetRow.extend({ reason: z.string().optional() })).max(10000),
  applied: z
    .array(targetRow.extend({ readback: z.string().max(40) }))
    .max(10000)
    .optional(),
});
export type PresetAnswer = z.infer<typeof presetAnswer>;
