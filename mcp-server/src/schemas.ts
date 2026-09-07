import * as z from "zod/v4";

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
export const hardwareDomains: Record<string, string[]> = {
  pump_switch: ["switch"],
  main_line_switch: ["switch"],
  waste_switch: ["switch"],
  light_entity: ["light", "switch"],
  feed_ec_sensor: ["sensor"],
  feed_ph_sensor: ["sensor"],
  temperature_sensor: ["sensor"],
  humidity_sensor: ["sensor"],
  vpd_sensor: ["sensor"],
  water_level_sensor: ["sensor"],
  tank_temperature_sensor: ["sensor"],
  tank_ec_sensor: ["sensor"],
  tank_ph_sensor: ["sensor"],
  tank_last_fill_sensor: ["sensor", "input_datetime"],
  tank_fill_entity: ["switch", "binary_sensor"],
};
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
export const setupChanges = z.strictObject({
  room_name: name.optional(),
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
const date = z
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
