import type { TimelineRequest, TimelineRow, TimelineRows } from "./day-timeline";
import type { EntityState, LogEvent, Series, States } from "./types";
import { numeric } from "./model";

export function isDemoLocation(location: Pick<Location, "hostname" | "search">): boolean {
  return (
    new URLSearchParams(location.search).has("demo") || location.hostname.endsWith(".github.io")
  );
}
export function createDemo(now = Date.now()): States {
  const states: States = {};
  function put(
    entity_id: string,
    state: string | number,
    attributes: Record<string, unknown> = {},
  ) {
    states[entity_id] = {
      entity_id,
      state: String(state),
      attributes: { ...attributes, synthetic: true },
      last_updated: new Date(now - 18_000).toISOString(),
      last_changed: new Date(now - 180_000).toISOString(),
    };
  }
  function number(
    prefix: string,
    key: string,
    value: number,
    min: number,
    max: number,
    step: number,
    unit = "",
  ) {
    put(`number.crop_steering_${prefix}${key}`, value, {
      min,
      max,
      step,
      unit_of_measurement: unit,
    });
  }
  for (const [index, prefix] of ["", "f1_"].entries()) {
    const name = index === 0 ? "Flower 2" : "Flower 1";
    const enable =
      index === 0 ? "input_boolean.f2_control_enabled" : "switch.crop_steering_f1_engine_enabled";
    put(`sensor.crop_steering_${prefix}engine_config`, "ready", {
      prefix,
      slug: index === 0 ? "" : "f1",
      num_zones: 3,
      friendly_name: `${name} engine config`,
      enable_flag: enable,
      pump: `switch.demo_${prefix}pump`,
      valves: {
        1: `switch.demo_${prefix}valve_1`,
        2: `switch.demo_${prefix}valve_2`,
        3: `switch.demo_${prefix}valve_3`,
      },
      water_level_sensor: `sensor.demo_${prefix}tank_level`,
      tank_ec_sensor: `sensor.demo_${prefix}tank_ec`,
      tank_ph_sensor: `sensor.demo_${prefix}tank_ph`,
      tank_temperature_sensor: `sensor.demo_${prefix}tank_temperature`,
      tank_last_fill_sensor: `sensor.demo_${prefix}tank_last_fill`,
      tank_fill_entity: `binary_sensor.demo_${prefix}tank_filling`,
      // Flower 2 checks its feed water on the tank probes (the source-water gate); Flower 1 maps
      // no feed-water probe, so its gate is off. Both have been saved in Rooms & setup.
      ...(index
        ? {}
        : { feed_ec_sensor: "sensor.demo_tank_ec", feed_ph_sensor: "sensor.demo_tank_ph" }),
      setup_revision: 1,
    });
    put(`switch.demo_${prefix}pump`, index ? "off" : "on");
    put(`sensor.demo_${prefix}tank_level`, index ? 72 : 42, { unit_of_measurement: "%" });
    put(`sensor.demo_${prefix}tank_ec`, index ? 2.8 : 3.06, { unit_of_measurement: "mS/cm" });
    put(`sensor.demo_${prefix}tank_ph`, index ? 5.8 : 5.66, { unit_of_measurement: "pH" });
    put(`sensor.demo_${prefix}tank_temperature`, index ? 19.2 : 17.6, {
      unit_of_measurement: "°C",
    });
    put(
      `sensor.demo_${prefix}tank_last_fill`,
      new Date(now - (index ? 5 : 2) * 3600_000).toISOString(),
      { device_class: "timestamp" },
    );
    put(`binary_sensor.demo_${prefix}tank_filling`, "off");
    put(enable, "on");
    put(`switch.crop_steering_${prefix}room_active`, "on");
    // Flower 2 demonstrates a running setpoint supervisor; Flower 1 keeps the default (off).
    put(`switch.crop_steering_${prefix}auto_setpoints`, index ? "off" : "on");
    put(`sensor.crop_steering_${prefix}ai_heartbeat`, "online", {
      enable_flag: enable,
      last_beat: new Date(now - 18_000).toISOString(),
    });
    put(`sensor.crop_steering_${prefix}app_status`, "safe_idle");
    const fired = index ? [] : ["Z1 P1 ramp shot 3/6 (demo)"];
    put(
      `sensor.crop_steering_${prefix}current_decision`,
      fired[0] ?? "Holding — all zones in band",
      { fired, blocked: [] },
    );
    put(`select.crop_steering_${prefix}steering_mode`, index ? "Generative" : "Vegetative", {
      options: ["Vegetative", "Generative"],
    });
    const events: LogEvent[] = [];
    number(prefix, "dripper_flow_rate", 4, 0.5, 12, 0.5, "L/h");
    number(prefix, "max_shot_duration", 120, 5, 3600, 1, "s");
    number(prefix, "lights_on_hour", index ? 8 : 10, 0, 23, 1, "h");
    number(prefix, "lights_off_hour", index ? 20 : 22, 0, 23, 1, "h");
    number(prefix, "irrigation_ec_min", 2.3, 0, 6, 0.1, "mS/cm");
    number(prefix, "irrigation_ec_max", 3.5, 0, 8, 0.1, "mS/cm");
    number(prefix, "irrigation_ph_min", 5.5, 3, 9, 0.05, "pH");
    number(prefix, "irrigation_ph_max", 6.5, 3, 9, 0.05, "pH");
    for (let id = 1; id <= 3; id++) {
      put(`switch.demo_${prefix}valve_${id}`, !index && id === 1 ? "on" : "off");
      put(
        `sensor.crop_steering_${prefix}zone_${id}_last_irrigation_app`,
        new Date(now - (id * 12 + index * 20) * 60_000).toISOString(),
        { device_class: "timestamp" },
      );
      const key = `zone_${id}_`;
      const base = `sensor.crop_steering_${prefix}`;
      put(`${base}vwc_zone_${id}`, 54 + id * 2 + index * 3, {
        friendly_name: `${name} Zone ${id} VWC`,
        unit_of_measurement: "%",
      });
      put(`${base}ec_zone_${id}`, (2.6 + id * 0.2 + index * 0.3).toFixed(1), {
        friendly_name: `${name} Zone ${id} EC`,
        unit_of_measurement: "mS/cm",
      });
      put(`${base}${key}phase`, id === 1 ? "P1" : "P2");
      put(
        `${base}${key}status`,
        index && id === 3
          ? "Paused — zone disabled for inspection"
          : !index && id === 1
            ? "Demo irrigation pulse — valve on"
            : "Holding — within target band",
        // The controller always posts its zone status with a reason.
        { reason: "demo" },
      );
      put(`${base}${key}daily_water_app`, (4.4 + id * 0.9 + index).toFixed(1), {
        unit_of_measurement: "L",
      });
      put(`${base}${key}irrigation_count_app`, 5 + id + index);
      put(`switch.crop_steering_${prefix}${key}enabled`, index && id === 3 ? "off" : "on");
      put(`switch.crop_steering_${prefix}${key}manual_override`, "off");
      put(
        `select.crop_steering_${prefix}${key}steering_mode`,
        index ? "Generative" : "Vegetative",
        { options: ["Vegetative", "Generative"] },
      );
      number(prefix, `${key}p0_maximum_wait_time`, 60, 5, 240, 1, "min");
      number(prefix, `${key}generative_dryback_target`, 14, 2, 60, 0.5, "% of peak");
      number(prefix, `${key}p1_target_vwc`, 64 + index * 2, 20, 90, 0.5, "%");
      number(prefix, `${key}p2_vwc_threshold`, 61 + index * 2, 10, 90, 0.5, "%");
      number(prefix, `${key}p1_initial_shot_size`, 6, 0.5, 20, 0.5, "%");
      number(prefix, `${key}p1_shot_size_increment`, 0.5, 0.05, 10, 0.05, "%");
      number(prefix, `${key}p1_maximum_shots`, 6, 1, 30, 1);
      number(prefix, `${key}p1_time_between_shots`, 15, 5, 120, 1, "min");
      number(prefix, `${key}p2_shot_size`, 4, 0.5, 20, 0.5, "%");
      number(prefix, `${key}vegetative_dryback_target`, 8, 1, 30, 0.5, "% of peak");
      number(prefix, `${key}p3_emergency_vwc_threshold`, 35, 10, 70, 0.5, "%");
      number(prefix, `${key}max_daily_volume`, 40, 1, 200, 1, "L");
      number(prefix, `${key}substrate_volume`, 6, 0.5, 50, 0.5, "L/plant");
      number(prefix, `${key}plant_count`, 36, 1, 200, 1);
      number(prefix, key + "drippers_per_plant", 1, 1, 20, 1);
      number(prefix, key + "p3_emergency_shot_size", 3, 0.5, 15, 0.5, "%");
      number(prefix, key + "field_capacity", 70, 5, 100, 1, "%");
      number(prefix, key + "maximum_ec", 9, 1, 20, 0.1, "mS/cm");
      const supervisor = index ? "off" : (["tracking", "learning", "frozen"][id - 1] ?? "off");
      put(`${base}${key}auto_setpoints`, supervisor, {
        friendly_name: `${name} Zone ${id} auto setpoints`,
        learned_peak: supervisor === "off" || supervisor === "learning" ? null : 58 + id * 2,
        gain: supervisor === "off" ? null : 0.62,
        day_rate: supervisor === "off" ? null : 0.7,
        night_rate: supervisor === "off" ? null : 0.37,
        p1_outcome:
          supervisor === "tracking" ? "plateau" : supervisor === "frozen" ? "suspect" : "pending",
        last_change:
          supervisor === "tracking"
            ? "P1 target 66.0 → 64.0 % (demo)"
            : supervisor === "frozen"
              ? "P2 threshold 56.0 → 54.0 % (demo)"
              : "",
        jev: index ? "disabled" : supervisor === "frozen" ? "unavailable" : "ok",
        hold_days: supervisor === "tracking" ? 3 : 0,
        frozen_reason:
          supervisor === "frozen" ? "probe response looks suspect after a sensor dropout" : null,
        managed: index
          ? []
          : [
              "p1_target_vwc",
              "field_capacity",
              "p2_vwc_threshold",
              "p3_emergency_vwc_threshold",
            ].map((suffix) => `number.crop_steering_${prefix}${key}${suffix}`),
        updated: new Date(now - 120_000).toISOString(),
      });
      for (const family of ["veg", "gen"])
        for (const phase of ["p0", "p1", "p2"])
          number(
            prefix,
            `${key}ec_target_${family}_${phase}`,
            3 + (family === "gen" ? 0.5 : 0),
            0.5,
            8,
            0.1,
            "mS/cm",
          );
      for (let event = 0; event < 4; event++)
        events.push({
          id: `${prefix}${id}-${event}`,
          timestamp: new Date(now - (id * 17 + event * 83) * 60_000).toISOString(),
          message:
            event === 0 && index && id === 3
              ? "Zone paused for routine probe inspection (demo)."
              : event % 2 === 0
                ? `Scheduled P2 maintenance shot: ${(0.8 + id * 0.1).toFixed(1)} L (demo).`
                : "P1 → P2: target VWC reached (demo).",
          type: event === 0 && index && id === 3 ? "warning" : event % 2 === 0 ? "water" : "phase",
          zoneId: id,
        });
    }
    put(`sensor.crop_steering_${prefix}activity_log`, "Demo activity", {
      events: events.sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    });
  }
  return states;
}
/** The demo controller reports in like a running one, so it never reads as stopped. */
export function demoBeat(states: States, now = Date.now()): States {
  const stamp = new Date(now).toISOString();
  return Object.fromEntries(
    Object.entries(states).map(([id, entity]) => [
      id,
      /^sensor\.crop_steering_.*ai_heartbeat$/.test(id)
        ? { ...entity, last_updated: stamp, attributes: { ...entity.attributes, last_beat: stamp } }
        : entity,
    ]),
  );
}
/** Demo-only side effects of a switch write that a real controller would publish itself. */
export function demoReact(states: States, entityId: string, value: unknown): States {
  const auto = entityId.match(/^switch\.crop_steering_(.*)auto_setpoints$/);
  if (!auto || typeof value !== "boolean") return states;
  const sensor = new RegExp(`^sensor\\.crop_steering_${auto[1]}zone_\\d+_auto_setpoints$`);
  return Object.fromEntries(
    Object.entries(states).map(([id, entity]) => [
      id,
      sensor.test(id) ? { ...entity, state: value ? "learning" : "off" } : entity,
    ]),
  );
}
/** One synthetic crop-steering day, 0 (morning trough) to 1 (daytime peak), by hours since
 * lights-on: P0 dryback tail, P1 ramp-up shots, P2 maintenance sawtooth, overnight dryback. */
function dayShape(hour: number, photoperiod: number, shots: boolean): number {
  const p3 = Math.max(4, photoperiod - 2);
  if (hour < 1.5) return 0.06 * (1 - hour / 1.5);
  if (hour < 3.5) {
    const shot = (hour - 1.5) / (2 / 6);
    return shots ? Math.min(1, (Math.floor(shot) + 1) / 6 - 0.03 * (shot % 1)) : shot / 6;
  }
  if (hour < p3) {
    if (shots) return 1 - 0.3 * (((hour - 3.5) / 1.25) % 1);
    // Pore EC follows the moisture trend; it does not jump with every maintenance shot.
    // Ease between the P1 peak, the P2 average (0.85) and the P3 starting point.
    const edge = Math.min(1, (hour - 3.5) / 0.5, (p3 - hour) / 0.5);
    return 1 - 0.15 * edge;
  }
  return 1 - 0.94 * ((hour - p3) / (24 - p3)) ** 0.75;
}
/** Each demo probe runs its day a few minutes after the others. */
const seedOf = (entityId: string) =>
  [...entityId].reduce((total, char) => total + char.charCodeAt(0), 0) % 17;
/** Plausible probe history: a daily irrigation and dryback cycle that ends at the live value. */
function cycleHistory(
  states: States,
  match: RegExpMatchArray,
  base: number,
  hours: number,
  now: number,
) {
  const [entityId, prefix, kind] = match;
  const hourSetting = (key: string, fallback: number) =>
    numeric(states[`number.crop_steering_${prefix}lights_${key}_hour`]) ?? fallback;
  const on = hourSetting("on", 8),
    off = hourSetting("off", 20);
  const photoperiod = (off - on + 24) % 24 || 12;
  const seed = seedOf(entityId);
  const raw = (time: number) => {
    const date = new Date(time - seed * 180_000);
    const hour = (date.getHours() + date.getMinutes() / 60 - on + 24) % 24;
    // Days differ a little, so typical daily peaks are a real median and not one repeated day.
    const day = Math.floor((time - seed * 180_000 - on * 3_600_000) / 86_400_000);
    const amplitude = 9 * (1 + 0.12 * Math.sin(day * 2.3 + seed));
    const vwc =
      amplitude * dayShape(hour, photoperiod, kind === "vwc") +
      0.8 * Math.sin(day * 1.7 + seed) +
      0.12 * Math.sin(time / 353_000 + seed);
    // Pore EC concentrates as the substrate dries and dilutes with each irrigation.
    return kind === "ec" ? -0.075 * vwc : vwc;
  };
  const step = (hours <= 24 ? 5 : hours <= 72 ? 10 : 15) * 60_000;
  const count = Math.floor((hours * 3_600_000) / step);
  const offset = base - raw(now);
  return Array.from({ length: count + 1 }, (_, index) => {
    const time = now - (count - index) * step;
    return {
      time: new Date(time).toISOString(),
      value: Number((offset + raw(time)).toFixed(kind === "ec" ? 3 : 2)),
    };
  });
}
/** Plausible batch-tank chemistry: each refill (the recorded last fill, and every three days
 * before it) starts a fresh mix, a step down. Then EC creeps up steadily as water evaporates, and
 * pH climbs, fastest in the first day. Each batch mixes a little differently; EC follows the
 * day's temperature a little. Ends at the live reading. */
function tankHistory(
  states: States,
  match: RegExpMatchArray,
  base: number,
  hours: number,
  now: number,
) {
  const [entityId, prefix, kind] = match;
  const filled = Date.parse(states[`sensor.demo_${prefix}tank_last_fill`]?.state ?? "");
  const last = Number.isFinite(filled) ? filled : now;
  const batch = 72 * 3_600_000;
  const seed = seedOf(entityId);
  const raw = (time: number) => {
    const index = Math.floor((time - last) / batch);
    const hoursIn = (time - last - index * batch) / 3_600_000;
    return kind === "ec"
      ? 0.004 * hoursIn +
          0.05 * Math.sin(index * 2.1 + seed) +
          0.012 * Math.sin((time / 86_400_000) * 2 * Math.PI)
      : 0.3 * (1 - Math.exp(-hoursIn / 18)) +
          0.003 * hoursIn +
          0.04 * Math.sin(index * 1.7 + seed) +
          0.008 * Math.sin(time / 2.5e7);
  };
  const step = (hours <= 24 ? 5 : hours <= 168 ? 15 : 60) * 60_000;
  const count = Math.floor((hours * 3_600_000) / step);
  const offset = base - raw(now);
  return Array.from({ length: count + 1 }, (_, index) => {
    const time = now - (count - index) * step;
    return {
      time: new Date(time).toISOString(),
      value: Number((offset + raw(time)).toFixed(kind === "ec" ? 3 : 2)),
    };
  });
}
/** A recorded grow-day for the day timeline, on the demo probes' own day shape (P0 dryback, a
 * six-shot P1 ramp, P2 top-ups every 75 minutes, P3 two hours before lights-off), each zone shifted
 * like its probe so its shots land where its readings jump. Flower 2's zone 2 waits out a feed-EC
 * hold that ends when the feed band is widened; Flower 1's zone 3 is held since it was disabled. */
export function demoDay(states: States, request: TimelineRequest, now = Date.now()): TimelineRows {
  const end = Math.min(now, request.end);
  const wanted = new Set([...request.entityIds, ...request.attributeIds]);
  const rows: TimelineRows = {};
  const put = (id: string | undefined, list: TimelineRow[]) => {
    if (id && wanted.has(id))
      rows[id] = list.filter((row) => row.time <= end).sort((a, b) => a.time - b.time);
  };
  const moved = (id: string, before: number, time: number) => {
    if (states[id] && time <= end)
      put(id, [
        { state: String(before), time: request.start },
        { state: states[id].state, time },
      ]);
  };
  // Anything not drawn below held its current value all day.
  for (const id of wanted)
    if (states[id]) put(id, [{ state: states[id].state, time: request.start }]);
  for (const config of Object.values(states)) {
    if (!/^sensor\.crop_steering_.*engine_config$/.test(config.entity_id)) continue;
    const prefix = String(config.attributes.prefix ?? "");
    const lights = (key: string) =>
      numeric(states[`number.crop_steering_${prefix}lights_${key}_hour`]);
    const on = lights("on"),
      off = lights("off");
    if (on === null || off === null) continue;
    const p3 = Math.max(4, ((off - on + 24) % 24 || 12) - 2);
    const valves = (config.attributes.valves ?? {}) as Record<string, string>;
    const events: { time: number; zone: number; list: "fired" | "blocked"; text: string | null }[] =
      [];
    for (let zone = 1; zone <= Number(config.attributes.num_zones); zone++) {
      const vwc = `sensor.crop_steering_${prefix}vwc_zone_${zone}`;
      const at = (hour: number) => request.start + seedOf(vwc) * 180_000 + hour * 3_600_000;
      const phases = [
        [0.02, "P0"],
        [1.5, "P1"],
        [3.5, "P2"],
        [p3, "P3"],
      ] as const;
      put(`sensor.crop_steering_${prefix}zone_${zone}_phase`, [
        { state: "P3", time: request.start },
        ...phases.map(([hour, state]) => ({ state, time: at(hour) })),
      ]);
      const hold = !prefix && zone === 2 ? [2.5, 2.7] : null;
      const disabled = prefix && zone === 3 ? 6 : Infinity;
      const shots: { hour: number; seconds: number; text: string }[] = [];
      for (let shot = 0, hour = 1.5; shot < 6; shot++, hour += 1 / 3) {
        if (hold && hour >= hold[0] && hour < hold[1]) hour = hold[1];
        shots.push({ hour, seconds: 90 + 15 * shot, text: `P1 P1 ramp shot ${shot + 1}/6 (demo)` });
      }
      for (let hour = 4.75; hour < Math.min(p3, disabled); hour += 1.25)
        shots.push({ hour, seconds: 150, text: "P2 P2 top-up (demo)" });
      const valve: TimelineRow[] = [{ state: "off", time: request.start }];
      for (const shot of shots) {
        const start = at(shot.hour),
          stop = start + shot.seconds * 1000;
        valve.push({ state: "on", time: start }, { state: "off", time: stop });
        events.push(
          { time: stop + 2_000, zone, list: "fired", text: shot.text },
          { time: stop + 62_000, zone, list: "fired", text: null },
        );
      }
      put(valves[zone], valve);
      if (hold) {
        events.push(
          {
            time: at(hold[0]),
            zone,
            list: "blocked",
            text: "P1 source-water EC 3.45 out of [2.3,3.4]",
          },
          { time: at(hold[1]), zone, list: "blocked", text: null },
        );
        moved(`number.crop_steering_${prefix}irrigation_ec_max`, 3.4, at(hold[1]) - 30_000);
      }
      if (disabled < p3)
        events.push(
          { time: at(disabled), zone, list: "blocked", text: "P2 zone disabled" },
          { time: at(p3), zone, list: "blocked", text: null },
        );
      const recorded = demoHistory(states, [vwc], (end - request.start) / 3_600_000, end);
      put(
        vwc,
        (recorded[0]?.points ?? []).map((point) => ({
          state: String(point.value),
          time: Date.parse(point.time),
        })),
      );
    }
    if (!prefix) {
      moved("number.crop_steering_zone_1_p1_target_vwc", 66, request.start + 0.4 * 3_600_000);
      moved("number.crop_steering_zone_2_p2_vwc_threshold", 62, request.start + 5.2 * 3_600_000);
    }
    const fired = new Map<number, string>(),
      blocked = new Map<number, string>();
    const listed = (entries: Map<number, string>) =>
      [...entries].sort(([a], [b]) => a - b).map(([zone, text]) => `Z${zone} ${text}`);
    const decision: TimelineRow[] = [
      {
        state: "Holding — all zones in band",
        time: request.start,
        attributes: { fired: [], blocked: [] },
      },
    ];
    events.sort((a, b) => a.time - b.time);
    for (const [index, event] of events.entries()) {
      const entries = event.list === "fired" ? fired : blocked;
      if (event.text === null) entries.delete(event.zone);
      else entries.set(event.zone, event.text);
      // One post per moment, as the controller posts every zone at once.
      if (events[index + 1]?.time === event.time) continue;
      decision.push({
        state: listed(fired)[0] ?? listed(blocked)[0] ?? "Holding — all zones in band",
        time: event.time,
        attributes: { fired: listed(fired), blocked: listed(blocked) },
      });
    }
    put(`sensor.crop_steering_${prefix}current_decision`, decision);
  }
  return rows;
}
export function demoHistory(
  states: States,
  entityIds: string[],
  hours: number,
  now = Date.now(),
): Series[] {
  return entityIds
    .filter((id) => states[id])
    .map((entityId) => {
      const state: EntityState = states[entityId];
      const base = numeric(state);
      const isEC = /(?:_ec_|_ec$)/.test(entityId);
      const amplitude = isEC ? 0.3 : 3;
      const probe =
        entityId.match(/^sensor\.crop_steering_(.*?)(vwc|ec)_zone_\d+$/) ??
        entityId.match(/^sensor\.crop_steering_(.*?)zone_\d+_(vwc|ec)$/);
      if (probe && base !== null)
        return {
          entityId,
          label: String(state.attributes.friendly_name || entityId),
          points: cycleHistory(states, probe, base, hours, now),
        };
      const tank = entityId.match(/^sensor\.demo_(.*?)tank_(ec|ph)$/);
      if (tank && base !== null)
        return {
          entityId,
          label: String(state.attributes.friendly_name || entityId),
          points: tankHistory(states, tank, base, hours, now),
        };
      return {
        entityId,
        label: String(state.attributes.friendly_name || entityId),
        points:
          base === null
            ? []
            : Array.from({ length: 97 }, (_, index) => ({
                time: new Date(now - (hours * 3_600_000 * (96 - index)) / 96).toISOString(),
                value: Number(
                  (
                    base +
                    Math.sin(index * 0.18) * amplitude +
                    ((index % 12) * amplitude) / 20
                  ).toFixed(2),
                ),
              })),
      };
    });
}
