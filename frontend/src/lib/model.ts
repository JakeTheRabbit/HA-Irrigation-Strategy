import type {
  Change,
  Choice,
  EntityState,
  LogEvent,
  Metric,
  Notice,
  Room,
  RoomView,
  Setting,
  States,
  Zone,
} from "./types";

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
]);
export const emptyRoom: Room = {
  id: "",
  name: "No room discovered",
  prefix: "",
};
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
    const { prefix, slug, num_zones, friendly_name } = entity.attributes;
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
    const name =
      typeof friendly_name === "string"
        ? friendly_name.replace(/\s*(?:engine configuration|engine config)$/i, "").trim()
        : "";
    rooms.push({
      id,
      prefix,
      name:
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
  if (/max_|maximum_ec|watchdog|irrigation_(ec|ph)/.test(key)) return "Safety";
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
    description: /dryback/.test(param)
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

export function buildRoom(states: States, room: Room): RoomView {
  const config = descriptor(states, room);
  const entities = roomEntities(states, room);
  const settings = entities
    .filter((e) => e.entity_id.startsWith("number."))
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
  const zones: Zone[] = activeIds.map((id) => {
    const z = `zone_${id}_`;
    const phase = resolve(states, room, "sensor", `${z}phase`);
    const enabled = resolve(states, room, "switch", `${z}enabled`);
    const status = resolve(states, room, "sensor", `${z}status`, `${z}safety_status`);
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
    return {
      id,
      name: typeof names?.[id] === "string" ? String(names[id]) : "Zone " + id,
      enabledEntity: enabled?.entity_id || null,
      enabled: boolean(enabled),
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
      status: readable(status) ? status!.state : "Unavailable",
      fields: settings.filter((s) => s.zoneId === id),
      sensors: entities.filter(
        (e) =>
          e.entity_id.startsWith("sensor.") &&
          (e.entity_id.includes(`_zone_${id}_`) || e.entity_id.endsWith(`_zone_${id}`)),
      ),
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
      value:
        values.length && values.every((v) => v !== null)
          ? values.reduce<number>((a, b) => a + b!, 0) / (average ? values.length : 1)
          : null,
    };
  };
  const alerts = zones.flatMap<Notice>((zone) => {
    if (zone.vwc.value === null || zone.ec.value === null)
      return [
        {
          id: `zone-${zone.id}-sensors`,
          title: `${zone.name}: sensor data unavailable`,
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
              .join(" ") + " Check probes and update times before relying on automatic irrigation.",
          severity: "warning" as const,
          zoneId: zone.id,
        },
      ];
    if (/fault|blocked|unsafe|error/i.test(zone.status))
      return [
        {
          id: `zone-${zone.id}-status`,
          title: `${zone.name} needs attention`,
          detail: zone.status,
          severity: "critical" as const,
          zoneId: zone.id,
        },
      ];
    return [];
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
  const lastBeat =
    typeof heartbeat?.attributes.last_beat === "string"
      ? Date.parse(heartbeat.attributes.last_beat)
      : NaN;
  if (Number.isFinite(lastBeat) && Date.now() - lastBeat > 5 * 60_000)
    alerts.push({
      id: `${room.id}-stale-heartbeat`,
      severity: "warning",
      title: "Controller heartbeat is stale",
      detail:
        "The engine has not reported a heartbeat for over five minutes. Displayed controller status may be outdated.",
    });
  if (config && boolean(engineEntity) === null)
    alerts.unshift({
      id: `${room.id}-engine-unavailable`,
      severity: "warning",
      title: "Engine control unavailable",
      detail:
        "No readable configured engine control was found. Check the room descriptor and engine heartbeat.",
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
    alerts,
  };
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
