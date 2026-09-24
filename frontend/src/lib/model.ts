import type {
  Change,
  Choice,
  EntityState,
  LogEvent,
  Metric,
  Notice,
  Room,
  RoomStatus,
  RoomView,
  Setting,
  States,
  Zone,
} from "./types";
import { parseAutoSetpoints } from "./auto-setpoints";
import { ageText, controllerZoneLabel, readHeartbeat, RESTING } from "./controller-health";

const ROOT = "crop_steering_";
const ZONE_PARAMETERS = new Set([
  "p1_target_vwc",
  "p2_vwc_threshold",
  "p2_shot_size",
  "p1_initial_shot_size",
  "p1_shot_size_increment",
  "p1_maximum_shots",
  "p1_time_between_shots",
  "vegetative_dryback_target",
  "generative_dryback_target",
  "p0_maximum_wait_time",
  "p3_emergency_vwc_threshold",
  "p3_emergency_shot_size",
  "max_daily_volume",
  "field_capacity",
  "maximum_ec",
  "watchdog_hours",
  "substrate_volume",
  "plant_count",
  "drippers_per_plant",
  "dripper_flow_rate",
  "min_floor_drown_ceiling",
]);
const ROOM_PARAMETERS = new Set([
  "dripper_flow_rate",
  "lights_on_hour",
  "lights_off_hour",
  "irrigation_ec_min",
  "irrigation_ec_max",
  "irrigation_ph_min",
  "irrigation_ph_max",
  "max_shot_duration",
  "maximum_shot_duration",
]);
export const emptyRoom: Room = {
  id: "",
  name: "No room discovered",
  prefix: "",
};
/** Room-only controller cap: a present canonical entity always shadows its legacy alias. */
export function roomDurationCapEntityId(
  states: States,
  room: Room,
  settings: Setting[] = [],
): string | undefined {
  return ["max_shot_duration", "maximum_shot_duration"]
    .map((suffix) => `number.${ROOT}${room.prefix}${suffix}`)
    .find((id) => !!states[id] || settings.some((field) => field.entityId === id));
}
export function numeric(entity?: EntityState): number | null {
  if (!entity || !entity.state.trim() || ["unknown", "unavailable"].includes(entity.state))
    return null;
  const value = Number(entity.state);
  return Number.isFinite(value) ? value : null;
}
export function readable(entity?: EntityState): boolean {
  return !!entity && !!entity.state.trim() && !["unknown", "unavailable"].includes(entity.state);
}
function boolean(entity?: EntityState): boolean | null {
  return entity?.state === "on" ? true : entity?.state === "off" ? false : null;
}
const roomActiveId = (room: Room) => `switch.${ROOT}${room.prefix}room_active`;
/** Off means nothing is growing: the engine neither irrigates nor alerts. A missing or
 * unreadable switch is never treated as off, so an unknown state cannot hide warnings. */
export function roomIsActive(states: States, room: Room): boolean {
  return states[roomActiveId(room)]?.state !== "off";
}
function lastIrrigation(entity: EntityState | undefined, now: number): Zone["lastIrrigation"] {
  const result: Zone["lastIrrigation"] = {
    entityId: entity?.entity_id || null,
    timestamp: null,
    issue: "No irrigation timestamp reported",
  };
  if (!entity) return result;
  if (!readable(entity)) return { ...result, issue: "Irrigation timestamp unavailable" };
  // Only a dated, timezone-aware event state proves when irrigation happened.
  // last_updated/last_changed describe publication, not irrigation. Old retained
  // event timestamps remain valid, even when there are no recent sensor updates.
  const parts = entity.state.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/,
  );
  const timestamp = Date.parse(entity.state);
  const calendar = parts && new Date(`${parts[1]}-${parts[2]}-${parts[3]}T00:00:00Z`);
  if (
    !parts ||
    !Number.isFinite(timestamp) ||
    calendar?.getUTCFullYear() !== Number(parts[1]) ||
    (calendar?.getUTCMonth() ?? -1) + 1 !== Number(parts[2]) ||
    calendar?.getUTCDate() !== Number(parts[3]) ||
    Number(parts[4]) > 23 ||
    Number(parts[5]) > 59 ||
    Number(parts[6]) > 59
  )
    return { ...result, issue: "Invalid irrigation timestamp" };
  if (timestamp > now) return { ...result, issue: "Irrigation timestamp is in the future" };
  return { ...result, timestamp: new Date(timestamp).toISOString(), issue: null };
}
function title(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (s) => s.toUpperCase())
    .replace(/\bVwc\b/g, "VWC")
    .replace(/\bEc\b/g, "EC");
}
export function descriptor(states: States, room: Room): EntityState | undefined {
  if (!room.id) return undefined;
  return Object.values(states).find(
    (e) =>
      /^sensor\.crop_steering_.*engine_config$/.test(e.entity_id) &&
      e.attributes.prefix === room.prefix,
  );
}
export function discoverRooms(states: States): Room[] {
  const rooms: Room[] = [];
  for (const entity of Object.values(states)) {
    if (!/^sensor\.crop_steering_.*engine_config$/.test(entity.entity_id)) continue;
    if (entity.attributes.active === false) continue;
    const { prefix, slug, num_zones, room_name, friendly_name } = entity.attributes;
    if (
      typeof prefix !== "string" ||
      !/^(?:[a-z0-9_]+_)?$/.test(prefix) ||
      !Number.isInteger(Number(num_zones)) ||
      Number(num_zones) < 1 ||
      Number(num_zones) > 64
    )
      continue;
    if (rooms.some((r) => r.prefix === prefix)) continue;
    // ':' cannot occur in a validated prefix, including named "f2"/"default".
    const id = `room:${prefix}`;
    // The sensor's HA friendly name can be generic or retained from an older setup.
    // The descriptor publishes the actual user-configured room name.
    const configuredName = typeof room_name === "string" ? room_name.trim() : "";
    const name =
      typeof friendly_name === "string"
        ? friendly_name.replace(/\s*(?:engine configuration|engine config)$/i, "").trim()
        : "";
    rooms.push({
      id,
      prefix,
      name:
        configuredName ||
        name ||
        (typeof slug === "string" && slug
          ? title(slug)
          : prefix
            ? title(prefix.slice(0, -1))
            : "Default room"),
    });
  }
  return rooms.sort((a, b) =>
    a.prefix === "" ? -1 : b.prefix === "" ? 1 : a.name.localeCompare(b.name),
  );
}

export function resolveRequestedRoom(rooms: Room[], requested: string | null): Room | undefined {
  if (!requested) return undefined;
  const canonical = rooms.find((room) => room.id === requested);
  if (canonical) return canonical;
  // Legacy links name a real prefix first. F2 means the unprefixed room only
  // when no named f2_ room exists. Canonical IDs never participate in aliases.
  if (requested.startsWith("room:")) return undefined;
  const named = rooms.find((room) => room.prefix === `${requested}_`);
  return named || (requested === "f2" ? rooms.find((room) => room.prefix === "") : undefined);
}

// Legacy F1 integration sensors had a system_ namespace. Explicit aliases from
// www/f2-classic.html; never apply these to any other named/default room.
const F1_ALIASES: Record<string, string> = {
  average_vwc_all_zones: "sensor.crop_steering_system_average_vwc_all_zones",
  average_ec_all_zones: "sensor.crop_steering_system_average_ec_all_zones",
  daily_water_usage: "sensor.crop_steering_system_daily_water_usage",
  zone_1_status: "sensor.crop_steering_system_zone_1_status",
  zone_2_status: "sensor.crop_steering_system_zone_2_status",
  zone_3_status: "sensor.crop_steering_system_zone_3_status",
  zone_1_daily_water_usage: "sensor.crop_steering_system_zone_1_daily_water_usage",
  zone_2_daily_water_usage: "sensor.crop_steering_system_zone_2_daily_water_usage",
  zone_3_daily_water_usage: "sensor.crop_steering_system_zone_3_daily_water_usage",
  zone_1_irrigations_today: "sensor.crop_steering_system_zone_1_irrigations_today",
  zone_2_irrigations_today: "sensor.crop_steering_system_zone_2_irrigations_today",
  zone_3_irrigations_today: "sensor.crop_steering_system_zone_3_irrigations_today",
};
function resolve(
  states: States,
  room: Room,
  domain: string,
  ...suffixes: string[]
): EntityState | undefined {
  for (const suffix of suffixes) {
    const id = `${domain}.${ROOT}${room.prefix}${suffix}`;
    // Existing unavailable primary entities stay unavailable: never hide faults.
    if (states[id]) return states[id];
    if (
      room.prefix === "f1_" &&
      domain === "sensor" &&
      F1_ALIASES[suffix] &&
      states[F1_ALIASES[suffix]]
    )
      return states[F1_ALIASES[suffix]];
  }
}
/** Which integration and which controller are actually RUNNING for this room, as they report
 * themselves: the integration in its room descriptor, the controller in its heartbeat. Nothing
 * here is a number baked into the dashboard, so a release has no third place to bump. `null`
 * means that half is not reporting one (older than 2.19.1 / 0.16.1, or not running). */
export function runningVersions(
  states: States,
  room: Room,
): { integration: string | null; controller: string | null } {
  const text = (value: unknown) =>
    typeof value === "string" && value.trim() && value !== "unknown" ? value.trim() : null;
  return {
    integration: text(descriptor(states, room)?.attributes.integration_version),
    controller: text(
      resolve(states, room, "sensor", "ai_heartbeat")?.attributes.controller_version,
    ),
  };
}
export function roomEntities(states: States, room: Room): EntityState[] {
  if (!room.id) return [];
  const prefixes = [
    ...new Set([
      "f1_",
      ...discoverRooms(states)
        .map((r) => r.prefix)
        .filter(Boolean),
    ]),
  ].sort((a, b) => b.length - a.length);
  const aliases = new Set(Object.values(F1_ALIASES));
  return Object.values(states).filter((e) => {
    if (aliases.has(e.entity_id)) return room.prefix === "f1_";
    const suffix = e.entity_id.split(".")[1];
    if (!suffix?.startsWith(ROOT)) return false;
    const key = suffix.slice(ROOT.length);
    const owner = prefixes.find((prefix) => key.startsWith(prefix)) || "";
    return owner === room.prefix;
  });
}
function metric(entity: EntityState | undefined, label: string, unit: string): Metric {
  return {
    entityId: entity?.entity_id || null,
    label,
    unit: String(entity?.attributes.unit_of_measurement || unit),
    value: numeric(entity),
  };
}
function telemetryIssue(
  entity: EntityState | undefined,
  maxAgeS: number,
  now: number,
): string | null {
  if (numeric(entity) === null) return "reading unavailable";
  // Like the controller's read path, use last_updated, never last_changed.
  // Missing/invalid timestamps cannot prove freshness. Allow 60s clock skew.
  const updated = entity?.last_updated ? Date.parse(entity.last_updated) : NaN;
  if (!Number.isFinite(updated)) return "freshness unknown (missing or invalid update time)";
  if (updated > now + 60_000) return "freshness unknown (update time is in the future)";
  if (now - updated > maxAgeS * 1000)
    return `stale (older than ${Number((maxAgeS / 60).toFixed(2))} minutes)`;
  return null;
}
function readingMetric(
  entity: EntityState | undefined,
  label: string,
  unit: string,
  maxAgeS: number,
  now: number,
): Metric {
  const result = metric(entity, label, unit);
  return telemetryIssue(entity, maxAgeS, now) ? { ...result, value: null } : result;
}
function group(key: string) {
  if (/^p0_|dryback/.test(key)) return "P0 · Morning dryback";
  if (/^p1_/.test(key)) return "P1 · Ramp-up";
  if (/^p2_/.test(key)) return "P2 · Maintenance";
  if (/^p3_/.test(key)) return "P3 · Overnight";
  if (/^ec_target/.test(key)) return "EC targets";
  if (/substrate|plant_count|dripper/.test(key)) return "Hardware sizing";
  if (/light.*hour/.test(key)) return "Schedule";
  if (/max_|maximum_shot_duration|maximum_ec|watchdog|irrigation_(ec|ph)/.test(key))
    return "Safety";
  return "General";
}
function setting(entity: EntityState, room: Room): Setting | null {
  const key = entity.entity_id.replace(`number.${ROOT}${room.prefix}`, "");
  const match = key.match(/^zone_(\d+)_(.*)$/);
  const param = match?.[2] || key;
  if (
    !ZONE_PARAMETERS.has(param) &&
    !/^ec_target_(veg|gen)_p[012]$/.test(param) &&
    (match || !ROOM_PARAMETERS.has(param))
  )
    return null;
  const { min, max, step } = entity.attributes;
  if (
    ![min, max, step].every((v) => typeof v === "number" && Number.isFinite(v)) ||
    Number(min) > Number(max) ||
    Number(step) <= 0
  )
    return null;
  return {
    entityId: entity.entity_id,
    label: title(param),
    description: ["max_shot_duration", "maximum_shot_duration"].includes(param)
      ? "Maximum valve-open runtime for every zone in this room."
      : /dryback/.test(param)
        ? "Relative drop as a percentage of peak VWC. Example: 60% peak with a 10% target means 54% VWC."
        : param === "substrate_volume"
          ? "Substrate volume per plant; the engine scales by plant count."
          : match
            ? `Zone ${match[1]} configuration.`
            : "Room default; an available zone-specific value takes precedence.",
    value: numeric(entity),
    min: Number(min),
    max: Number(max),
    step: Number(step),
    unit: String(entity.attributes.unit_of_measurement || ""),
    group: group(param),
    ...(match ? { zoneId: Number(match[1]) } : {}),
  };
}
export function eventsForRoom(states: States, room: Room): LogEvent[] {
  const log = resolve(states, room, "sensor", "activity_log");
  if (!log || !readable(log)) return [];
  if (Array.isArray(log.attributes.events))
    return log.attributes.events
      .filter(
        (e): e is LogEvent =>
          !!e &&
          typeof e === "object" &&
          typeof e.message === "string" &&
          typeof e.timestamp === "string" &&
          typeof e.id === "string",
      )
      .map((e) => ({
        ...e,
        type: ["water", "phase", "warning", "info"].includes(e.type) ? e.type : "info",
      }));
  if (typeof log.attributes.feed !== "string") return [];
  const named = discoverRooms(states)
    .filter((r) => r.prefix)
    .map((r) => String(descriptor(states, r)?.attributes.slug || r.prefix.slice(0, -1)));
  const slug = String(descriptor(states, room)?.attributes.slug || room.prefix.slice(0, -1));
  return log.attributes.feed.split("\n").flatMap((line, i): LogEvent[] => {
    const match = line.match(/^(\d{2}:\d{2})\s+(.+)$/);
    if (!match) return [];
    let message = match[2];
    if (room.prefix) {
      if (!message.startsWith(`${slug} `)) return [];
      message = message.slice(slug.length + 1);
    } else if (named.some((name) => message.startsWith(`${name} `)) || !/^Z\d+\s/.test(message))
      return [];
    const zone = message.match(/\bZ(?:one\s*)?(\d+)\b/i);
    return [
      {
        id: `${log.entity_id}:${i}:${line}`,
        timestamp: match[1],
        message,
        type: /block|fault|hold|unavailable/i.test(message)
          ? "warning"
          : /P[0-3].*(?:→|->)/.test(message)
            ? "phase"
            : /shot|watered|irrigat/i.test(message)
              ? "water"
              : "info",
        ...(zone ? { zoneId: Number(zone[1]) } : {}),
      },
    ];
  });
}

const SEVERITY_RANK: Record<Notice["severity"], number> = { critical: 0, warning: 1, info: 2 };
/** A short notice list: every critical notice, then the next ones up to `limit`. Expects
 * `buildRoom` order (most severe first). */
export function leadingNotices(alerts: Notice[], limit = 3): Notice[] {
  return alerts.filter((notice, index) => notice.severity === "critical" || index < limit);
}

export function buildRoom(states: States, room: Room): RoomView {
  const config = descriptor(states, room);
  const entities = roomEntities(states, room);
  const settings = entities
    .filter((e) => e.entity_id.startsWith("number."))
    .filter(
      (e) =>
        e.entity_id !== `number.${ROOT}${room.prefix}maximum_shot_duration` ||
        e.entity_id === roomDurationCapEntityId(states, room),
    )
    .map((e) => setting(e, room))
    .filter((s): s is Setting => s !== null);
  const choices: Choice[] = entities.flatMap((entity) => {
    const key = entity.entity_id.replace(`select.${ROOT}${room.prefix}`, "");
    if (
      !entity.entity_id.startsWith("select.") ||
      !/^(zone_\d+_)?steering_mode$/.test(key) ||
      !Array.isArray(entity.attributes.options)
    )
      return [];
    const options = entity.attributes.options.filter((v): v is string => typeof v === "string");
    const zone = key.match(/^zone_(\d+)_/);
    return [
      {
        entityId: entity.entity_id,
        label: zone ? `Zone ${zone[1]} steering mode` : "Room steering mode",
        value: readable(entity) ? entity.state : null,
        options,
        ...(zone ? { zoneId: Number(zone[1]) } : {}),
      },
    ];
  });
  const heartbeat = resolve(states, room, "sensor", "ai_heartbeat");
  const maxAgeS =
    [heartbeat?.attributes.max_sensor_age_s, config?.attributes.max_sensor_age_s].find(
      (value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0,
    ) ?? 20 * 60;
  const strategyEntity = resolve(states, room, "sensor", "strategy_plan");
  const strategyAttrs = strategyEntity?.attributes || {};
  const strategyEngaged =
    strategyAttrs.enabled === true || heartbeat?.attributes.strategy_required === true;
  const strategyUpdated =
    typeof strategyAttrs.updated_at === "string" ? Date.parse(strategyAttrs.updated_at) : NaN;
  const strategyValidUntil =
    typeof strategyAttrs.valid_until === "string" ? Date.parse(strategyAttrs.valid_until) : NaN;
  const strategyValid =
    strategyAttrs.snapshot_version === 1 &&
    strategyAttrs.room_id === room.id &&
    ["active", "disarming"].includes(strategyEntity?.state || "") &&
    Number.isFinite(strategyUpdated) &&
    Date.now() - strategyUpdated <= 180000 &&
    strategyUpdated - Date.now() <= 60000 &&
    Number.isFinite(strategyValidUntil) &&
    strategyValidUntil > Date.now();
  const now = Date.now();
  const beat = readHeartbeat(heartbeat, now);
  const live = beat.health === "fresh";
  const decision = resolve(states, room, "sensor", "current_decision");
  const flag = heartbeat?.attributes.enable_flag ?? config?.attributes.enable_flag;
  const engineEntity =
    typeof flag === "string" && /^(switch|input_boolean)\./.test(flag) ? states[flag] : undefined;
  const configuredIds = Array.from(
    { length: config ? Number(config.attributes.num_zones) : 0 },
    (_, i) => i + 1,
  );
  const activeIds = Array.isArray(config?.attributes.active_zone_ids)
    ? configuredIds.filter((id) => (config!.attributes.active_zone_ids as unknown[]).includes(id))
    : configuredIds;
  const names = config?.attributes.zone_names as Record<string, unknown> | undefined;
  const valves = config?.attributes.valves;
  const activeSwitch = room.id ? states[roomActiveId(room)] : undefined;
  const roomActive = !room.id || roomIsActive(states, room);
  const autoSwitch = room.id ? resolve(states, room, "switch", "auto_setpoints") : undefined;
  const zones: Zone[] = activeIds.map((id) => {
    const z = `zone_${id}_`;
    const phase = resolve(states, room, "sensor", `${z}phase`);
    const enabled = resolve(states, room, "switch", `${z}enabled`);
    const status = resolve(states, room, "sensor", `${z}status`, `${z}safety_status`);
    const mappedValve =
      valves && typeof valves === "object" && !Array.isArray(valves)
        ? (valves as Record<string, unknown>)[String(id)]
        : undefined;
    const valveEntity =
      typeof mappedValve === "string" && /^switch\.[a-z0-9_]+$/.test(mappedValve)
        ? mappedValve
        : null;
    const plannedZone = Array.isArray(strategyAttrs.zones)
      ? (strategyAttrs.zones.find(
          (item: unknown) =>
            !!item && typeof item === "object" && (item as { zone_id?: number }).zone_id === id,
        ) as { parameters?: Record<string, number>; status?: string } | undefined)
      : undefined;
    const plannedMetric = (key: string | null, fallback: Metric): Metric => {
      if (!strategyEngaged) return fallback;
      const value =
        key && strategyValid && plannedZone?.status === "active"
          ? plannedZone.parameters?.[key]
          : undefined;
      return {
        ...fallback,
        entityId: strategyEntity?.entity_id || null,
        label: "Plan · " + fallback.label,
        value: typeof value === "number" && Number.isFinite(value) ? value : null,
      };
    };
    const targetKey =
      phase?.state === "P1"
        ? "p1_target_vwc"
        : phase?.state === "P2"
          ? "p2_vwc_threshold"
          : phase?.state === "P3"
            ? "p3_emergency_vwc_threshold"
            : null;
    const target = targetKey
      ? resolve(states, room, "number", `${z}${targetKey}`, targetKey)
      : undefined;
    const mode = resolve(states, room, "select", `${z}steering_mode`, "steering_mode");
    const family = mode?.state.toLowerCase().startsWith("gen")
      ? "gen"
      : mode?.state.toLowerCase().startsWith("veg")
        ? "veg"
        : null;
    const p = /^P[012]$/.test(phase?.state || "") ? phase!.state.toLowerCase() : null;
    // The controller posts this status with a reason; the integration's fixed-threshold sensor
    // writes the same entity without one. While the controller is live, show the controller's.
    const label =
      (live &&
        !(status && "reason" in status.attributes) &&
        controllerZoneLabel(id, phase, decision)) ||
      (readable(status) ? status!.state : "Unavailable");
    return {
      id,
      name: typeof names?.[id] === "string" ? String(names[id]) : "Zone " + id,
      enabledEntity: enabled?.entity_id || null,
      enabled: boolean(enabled),
      valveEntity,
      valveOn: valveEntity ? boolean(states[valveEntity]) : null,
      lastIrrigation: lastIrrigation(
        resolve(states, room, "sensor", `${z}last_irrigation_app`, `${z}last_irrigation`),
        now,
      ),
      phase: readable(phase) ? phase!.state : "Unavailable",
      vwc: readingMetric(
        resolve(states, room, "sensor", `vwc_zone_${id}`, `${z}vwc`),
        "VWC",
        "%",
        maxAgeS,
        now,
      ),
      ec: readingMetric(
        resolve(states, room, "sensor", `ec_zone_${id}`, `${z}ec`),
        "EC",
        "mS/cm",
        maxAgeS,
        now,
      ),
      target: plannedMetric(
        targetKey,
        metric(
          target,
          phase?.state === "P2"
            ? "P2 base VWC threshold"
            : phase?.state === "P3"
              ? "Emergency VWC floor"
              : "VWC target",
          "%",
        ),
      ),
      ecTarget: plannedMetric(
        p ? "ec_target_" + p : null,
        metric(
          family && p
            ? resolve(
                states,
                room,
                "number",
                `${z}ec_target_${family}_${p}`,
                `ec_target_${family}_${p}`,
              )
            : undefined,
          "EC target",
          "mS/cm",
        ),
      ),
      water: metric(
        resolve(states, room, "sensor", `${z}daily_water_app`, `${z}daily_water_usage`),
        "Water today",
        "L",
      ),
      shots: metric(
        resolve(states, room, "sensor", `${z}irrigation_count_app`, `${z}irrigations_today`),
        "Shots today",
        "",
      ),
      // Overnight dryback is intended: the fixed threshold's "needs water" never applies in P3.
      status: !roomActive
        ? "Room off"
        : phase?.state === "P3" && label === "Dry - Needs Water"
          ? RESTING.P3
          : label,
      stale: roomActive && !live,
      fields: settings.filter((s) => s.zoneId === id),
      sensors: entities.filter(
        (e) =>
          e.entity_id.startsWith("sensor.") &&
          (e.entity_id.includes(`_zone_${id}_`) || e.entity_id.endsWith(`_zone_${id}`)),
      ),
      auto: parseAutoSetpoints(resolve(states, room, "sensor", `${z}auto_setpoints`)),
    };
  });
  const aggregate = (
    key: "vwc" | "ec" | "water" | "shots",
    label: string,
    unit: string,
    average = false,
  ): Metric => {
    const values = zones.map((z) => z[key].value);
    return {
      entityId: null,
      label,
      unit,
      key,
      value:
        values.length && values.every((v) => v !== null)
          ? values.reduce<number>((a, b) => a + b!, 0) / (average ? values.length : 1)
          : null,
    };
  };
  // Zones with the identical problem share one notice instead of one each.
  const problems = new Map<string, { kind: "sensors" | "status"; detail: string; zones: Zone[] }>();
  for (const zone of zones) {
    const problem =
      zone.vwc.value === null || zone.ec.value === null
        ? {
            kind: "sensors" as const,
            detail:
              [zone.vwc, zone.ec]
                .flatMap((reading) => {
                  const issue = telemetryIssue(
                    reading.entityId ? states[reading.entityId] : undefined,
                    maxAgeS,
                    now,
                  );
                  return issue ? [`${reading.label}: ${issue}.`] : [];
                })
                .join(" ") +
              " Check probes and update times before relying on automatic irrigation.",
          }
        : /fault|blocked|unsafe|error/i.test(zone.status)
          ? { kind: "status" as const, detail: zone.status }
          : null;
    if (!problem) continue;
    const key = `${problem.kind}\n${problem.detail}`;
    problems.set(key, { ...problem, zones: [...(problems.get(key)?.zones ?? []), zone] });
  }
  const alerts = [...problems.values()].map<Notice>(({ kind, detail, zones: group }) => {
    const one = group.length === 1 ? group[0] : null;
    const names = group.map((zone) => zone.name);
    const list = one ? one.name : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
    return {
      id: one
        ? `zone-${one.id}-${kind}`
        : `zones-${group.map((zone) => zone.id).join("-")}-${kind}`,
      title:
        kind === "sensors"
          ? `${list}: sensor data unavailable`
          : `${list} ${one ? "needs" : "need"} attention`,
      detail,
      severity: kind === "sensors" ? "warning" : "critical",
      ...(one ? { zoneId: one.id } : {}),
    };
  });
  if (
    typeof heartbeat?.attributes.hardware_fault === "string" &&
    heartbeat.attributes.hardware_fault
  )
    alerts.unshift({
      id: `${room.id}-hardware-fault`,
      severity: "critical",
      title: "Hardware fault — irrigation inhibited",
      detail: `${heartbeat.attributes.hardware_fault}. Disarm the engine, physically resolve the stuck hardware, verify all recorded devices are off, then re-arm.`,
    });
  if (strategyEngaged)
    alerts.unshift({
      id: room.id + "-strategy",
      severity: strategyValid ? "info" : "critical",
      title: strategyValid ? "Grow plan controls this room" : "Grow plan snapshot unavailable",
      detail: strategyValid
        ? "Displayed VWC and EC references come from the active plan. Manual setpoints are retained for use after the plan is disarmed."
        : "The controller requires a valid plan snapshot. Targets are unavailable until plan status is restored; do not treat legacy number values as active targets.",
    });
  if (config && !live)
    alerts.push({
      id: `${room.id}-controller`,
      severity: "critical",
      title: "Controller not running",
      detail:
        (beat.health === "stale"
          ? `The controller last reported ${ageText(now - beat.at!)} ago`
          : beat.health === "missing"
            ? `There is no controller heartbeat (sensor.${ROOT}${room.prefix}ai_heartbeat is missing)`
            : `The controller heartbeat has no readable time`) +
        ", so nothing confirms this room is being watered. Start or restart the controller app and check its log. Zone phases and statuses are its last report, not live.",
    });
  if (config && boolean(engineEntity) === null)
    alerts.unshift({
      id: `${room.id}-engine-unavailable`,
      severity: "warning",
      title: "Engine control unavailable",
      detail:
        "No readable configured engine control was found. Check the room descriptor and engine heartbeat.",
    });
  // The integration's stock sensor lists every stock tank; the low ones get one notice.
  const stockTanks = resolve(states, room, "sensor", "stock_low")?.attributes.tanks;
  const lowStock = (Array.isArray(stockTanks) ? stockTanks : []).filter(
    (tank): tank is { name: string; level_l: number; batches_left: number | null } =>
      !!tank && typeof tank === "object" && (tank as { low?: unknown }).low === true,
  );
  if (lowStock.length)
    alerts.push({
      id: `${room.id}-stock-low`,
      severity: "warning",
      title: `Stock ${lowStock.length === 1 ? "tank" : "tanks"} running low`,
      detail:
        lowStock
          .map(
            (tank) =>
              `${tank.name}: ${tank.level_l} L` +
              (typeof tank.batches_left === "number"
                ? `, about ${tank.batches_left} batch${tank.batches_left === 1 ? "" : "es"} left`
                : ""),
          )
          .join("; ") + ". Refill, then press Refilled on the Stock tanks page.",
    });
  return {
    room,
    zones,
    engine: {
      entityId: engineEntity?.entity_id || null,
      enabled: boolean(engineEntity),
    },
    metrics: [
      aggregate("vwc", "Average VWC", "%", true),
      aggregate("ec", "Average EC", "mS/cm", true),
      aggregate("water", "Water today", "L"),
      aggregate("shots", "Shots today", ""),
    ],
    events: eventsForRoom(states, room),
    entities,
    settings,
    choices,
    strategy: {
      status: strategyEntity?.state || "manual",
      engaged: strategyEngaged,
      valid: strategyValid,
    },
    // An off room is empty: probe, heartbeat and status warnings are noise there.
    // Physically stuck hardware is the one notice that still matters.
    alerts: (roomActive
      ? alerts
      : alerts.filter((alert) => alert.id === `${room.id}-hardware-fault`)
    ).sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]),
    roomActive,
    roomActiveEntity: activeSwitch?.entity_id ?? null,
    autoSetpoints: {
      entityId: autoSwitch?.entity_id ?? null,
      enabled: boolean(autoSwitch),
    },
  };
}

/** One line per room from what the controller publishes: watering, holding and why, not watering
 * and what to do, or how old the data is once the controller has stopped reporting. */
export function roomStatus(states: States, room: Room, now = Date.now()): RoomStatus {
  const beat = readHeartbeat(resolve(states, room, "sensor", "ai_heartbeat"), now);
  const say = (tone: RoomStatus["tone"], text: string, detail: string): RoomStatus => ({
    room,
    tone,
    text,
    detail,
    reportedAt: beat.at,
  });
  const note = (key: string) => {
    const value = beat.attributes[key];
    return typeof value === "string" && value.trim() ? value.trim() : null;
  };
  const fault = note("hardware_fault");
  if (fault)
    return say(
      "stopped",
      "Not watering",
      `Hardware fault: ${fault}. Disarm the engine, fix the stuck hardware and check it is off, then re-arm.`,
    );
  if (!roomIsActive(states, room))
    return say("off", "Room off", "Nothing growing: no irrigation, no alerts.");
  if (beat.health === "missing" || beat.health === "unreadable")
    return say(
      "stopped",
      "Not watering",
      "The controller is not running. Start the controller app and check its log.",
    );
  if (beat.health === "stale")
    return say(
      "stale",
      `Data ${ageText(now - beat.at!)} old`,
      "The controller stopped reporting. Check the controller app and its log.",
    );
  const pending = note("setup_pending");
  if (pending)
    return say(
      "stopped",
      "Not watering",
      pending.startsWith("Setup changed")
        ? `${pending}. Turn the engine off, wait up to 5 minutes for the controller to adopt the setup, then turn it back on.`
        : `${pending}. Correct the room in Rooms & setup.`,
    );
  const flag = beat.attributes.enable_flag ?? descriptor(states, room)?.attributes.enable_flag;
  const engine =
    typeof flag === "string" && /^(switch|input_boolean)\./.test(flag)
      ? states[flag]?.state
      : undefined;
  if (engine !== "on")
    return say(
      "stopped",
      "Not watering",
      engine === "off"
        ? "The engine switch is off. Turn it on to resume automatic irrigation."
        : "The engine switch is unavailable. Check this room's kill switch in Home Assistant.",
    );
  const plan = note("strategy_error");
  if (plan)
    return say(
      "stopped",
      "Not watering",
      `Grow plan hold: ${plan}. Re-activate or disarm the plan in Irrigation plan.`,
    );
  const decision = resolve(states, room, "sensor", "current_decision");
  const entries = (key: string) => {
    const value = decision?.attributes[key];
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string")
      : [];
  };
  const fired = entries("fired"),
    blocked = entries("blocked");
  const app = resolve(states, room, "sensor", "app_status")?.state;
  if (fired.length) return say("watering", "Watering", fired.join(" · "));
  if (app === "irrigating") return say("watering", "Watering", "A shot is running.");
  // "error": a fail-closed hold; its block names what failed.
  if (app === "error")
    return say(
      "stopped",
      "Not watering",
      blocked.join(" · ") || "The controller reports an error. Check its log.",
    );
  if (blocked.length) return say("holding", "Holding", blocked.join(" · "));
  return say(
    "holding",
    "Holding",
    readable(decision)
      ? decision!.state.replace(/^Holding\s*[—-]\s*/, "")
      : "No decision reported yet.",
  );
}

export function validateChange(room: RoomView, states: States, change: Change): string | null {
  if (!room.room.id || !readable(descriptor(states, room.room)))
    return "No current readable room descriptor.";
  if (room.strategy.engaged && /^(number|select)[.]/.test(change.entityId))
    return "An active grow plan owns these targets. Disarm the plan before editing manual setpoints.";
  const hardware = discoverRooms(states).flatMap((r) => {
    const attributes = descriptor(states, r)?.attributes || {};
    return [
      attributes.pump,
      attributes.mainline,
      ...Object.values(
        typeof attributes.valves === "object" && attributes.valves ? attributes.valves : {},
      ),
    ];
  });
  if (hardware.includes(change.entityId))
    return "Direct hardware control is not available in this dashboard.";
  if (
    change.entityId === room.engine.entityId &&
    discoverRooms(states).some((other) => {
      if (other.id === room.room.id) return false;
      const otherFlag =
        resolve(states, other, "sensor", "ai_heartbeat")?.attributes.enable_flag ??
        descriptor(states, other)?.attributes.enable_flag;
      return otherFlag === change.entityId;
    })
  )
    return "This engine control is shared with another room; a room-local write cannot be guaranteed.";
  const entity = states[change.entityId];
  if (!entity || !readable(entity)) return "Entity is missing or unavailable.";
  const choice = room.choices.find((c) => c.entityId === change.entityId);
  if (choice)
    return typeof change.value === "string" && choice.options.includes(change.value)
      ? null
      : "Select an available steering mode.";
  const field = room.settings.find((s) => s.entityId === change.entityId);
  if (field) {
    if (typeof change.value !== "number" || !Number.isFinite(change.value))
      return "Enter a finite number.";
    if (change.value < field.min || change.value > field.max)
      return `Value must be between ${field.min} and ${field.max}.`;
    const steps = (change.value - field.min) / field.step;
    if (Math.abs(steps - Math.round(steps)) > 1e-6) return `Value must follow step ${field.step}.`;
    return null;
  }
  const safeSwitches = new Set([
    room.engine.entityId,
    room.roomActiveEntity,
    room.autoSetpoints.entityId,
    ...room.zones.flatMap((z) => [
      z.enabledEntity,
      `switch.${ROOT}${room.room.prefix}zone_${z.id}_manual_override`,
    ]),
  ]);
  if (
    safeSwitches.has(change.entityId) &&
    /^(switch|input_boolean)\./.test(change.entityId) &&
    boolean(entity) !== null &&
    typeof change.value === "boolean"
  )
    return null;
  return "This entity is not an editable configuration control in the current room.";
}
