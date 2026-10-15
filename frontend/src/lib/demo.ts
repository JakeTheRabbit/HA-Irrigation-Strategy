import {
  earlierDays,
  growDay,
  type TimelineRequest,
  type TimelineRow,
  type TimelineRows,
} from "./day-timeline";
import type { EntityState, LogEvent, Series, States } from "./types";
import type { CounterSample, WaterRecordRequest } from "./water-use";
import { addDays, daysBetween } from "./comparison";
import { stockSensorId } from "./dosing";
import { dateForDay, localDate } from "./grow-plan";
import { numeric } from "./model";
import { demoStock, stockAttributes, stockLinks } from "./stock-demo";
import { TANK_KEYS } from "./tank-level";

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
    // How Water today reads in the room (Settings → Appearance): each zone's total until chosen.
    put(`select.crop_steering_${prefix}water_today_view`, "Zone total", {
      options: ["Zone total", "Per plant"],
    });
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
    // The tank's level now, from the record its history is drawn from: the card and the chart agree.
    put(`sensor.demo_${prefix}tank_level`, demoTankModel(states, prefix, now)!.level(now), {
      unit_of_measurement: "%",
    });
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
        ...(index ? {} : demoProbes(put, id, "vwc", 54 + id * 2)),
      });
      put(`${base}ec_zone_${id}`, demoEc(index, id).toFixed(1), {
        friendly_name: `${name} Zone ${id} EC`,
        unit_of_measurement: "mS/cm",
        ...(index ? {} : demoProbes(put, id, "ec", demoEc(index, id))),
      });
      // Zone 3's back EC probe stopped reporting three hours ago: its zone reads the front one.
      if (!index && id === 3)
        states["sensor.demo_z3_back_ec"].last_updated = new Date(now - 3 * 3_600_000).toISOString();
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
      // What the controller publishes from crop_steering_engine.waiting_for, for the zone's phase.
      put(`${base}${key}waiting_for_app`, id === 1 ? "P1" : "P2", {
        at: new Date(now).toISOString(),
        conditions: demoWaiting(id === 1 ? "P1" : "P2", {
          vwc: 54 + id * 2 + index * 3,
          ec: Number(demoEc(index, id).toFixed(1)),
          peak: 64 + index * 2,
          trigger: 61 + index * 2,
          ecTarget: index ? 3.5 : 3,
          toLightsOff: minutesUntil(now, index ? 20 : 22),
        }),
      });
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
      put(`select.crop_steering_${prefix}${key}set_phase`, "Keep", {
        options: ["Keep", "P0", "P1", "P2", "P3"],
      });
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
      // Newest first: two maintenance shots, the hand-over to P2, and the ramp's last shot.
      for (let event = 0; event < 4; event++)
        events.push({
          id: `${prefix}${id}-${event}`,
          timestamp: new Date(now - (id * 17 + event * 83) * 60_000).toISOString(),
          message:
            event === 0 && index && id === 3
              ? "Zone paused for routine probe inspection (demo)."
              : event < 2
                ? `Scheduled P2 maintenance shot: ${(0.8 + id * 0.1).toFixed(1)} L (demo).`
                : event === 2
                  ? "P1 → P2: target VWC reached (demo)."
                  : `P1 ramp shot 6/6: ${(0.5 + id * 0.1).toFixed(1)} L (demo).`,
          type: event === 0 && index && id === 3 ? "warning" : event === 2 ? "phase" : "water",
          zoneId: id,
        });
    }
    put(`sensor.crop_steering_${prefix}activity_log`, "Demo activity", {
      events: events.sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    });
    // Flower 2 runs Jev; Flower 1 is a room without it.
    if (!index) demoJev(put, prefix, now);
    demoDosing(put, prefix, name, now);
    // The integration's stock sensor: a tank per pump, each drawn by its pump.
    const stock = demoStock(`room:${prefix}`, now, states);
    put(stockSensorId(prefix), stock.low.length, {
      friendly_name: `${name} stock tanks low`,
      ...stockAttributes(stock, stockLinks(states, prefix)),
    });
  }
  return states;
}
/** Each demo room's dosing pumps (id, name, calibrated flow in mL/s, the recipe's mL), each linked
 * to the stock tank of its nutrient (stock-demo.ts). Flower 1's Fade is new and not calibrated yet,
 * and its Core is dosed by hand: the recipe passes both by. */
const DEMO_PUMPS: Record<string, [string, string, number, number][]> = {
  "": [
    ["balance", "Balance", 11.06, 300],
    ["bloom", "Bloom", 10.52, 1800],
    ["core", "Core", 10.88, 1080],
    ["cleanse", "Cleanse", 9.74, 200],
  ],
  f1_: [
    ["grow", "Grow", 10.9, 1080],
    ["cleanse", "Cleanse", 9.8, 200],
    ["balance", "Balance", 11.2, 180],
    ["fade", "Fade", 0, 0],
    ["core", "Core", 10.6, 0],
    ["bloom", "Bloom", 10.4, 1800],
  ],
};
/** A demo room's batch-tank dosing (docs/DOSING.md): the pumps' hardware, the integration's
 * dosing_config sensor and the controller's dosing sensor. Flower 2's batch fills its tank, mixes
 * it with a pump and a recirculation valve, and doses four pumps; Flower 1's tank is filled by
 * hand. The last batch ended at each tank's last fill; Flower 2 has had a trim since. */
function demoDosing(
  put: (id: string, state: string | number, attributes?: Record<string, unknown>) => void,
  prefix: string,
  room: string,
  now: number,
) {
  const at = (hoursAgo: number) => new Date(now - hoursAgo * 3_600_000).toISOString();
  const filled = prefix ? 5 : 2;
  const list = DEMO_PUMPS[prefix] ?? [];
  const pumps = list.map(([id, name, flow, ml]) => {
    const device = `demo_${prefix}doser_${id}`;
    put(`number.${device}_volume`, ml, {
      friendly_name: `${name} dose volume`,
      min: 0,
      max: 5000,
      step: 1,
      unit_of_measurement: "mL",
    });
    put(`button.${device}_start`, at(filled + 0.2), { friendly_name: `${name} start dose` });
    put(`binary_sensor.${device}_dosing`, "off", {
      friendly_name: `${name} dosing`,
      device_class: "running",
    });
    put(`switch.${device}_power`, "on", { friendly_name: `${name} pump power` });
    put(`number.${device}_flow`, flow, {
      friendly_name: `${name} calibrated flow`,
      min: 0,
      max: 50,
      step: 0.01,
      unit_of_measurement: "mL/s",
    });
    return {
      id,
      name,
      volume_entity: `number.${device}_volume`,
      start_entity: `button.${device}_start`,
      dosing_entity: `binary_sensor.${device}_dosing`,
      dosing_prefix: "Dosing",
      power_entity: `switch.${device}_power`,
      flow_entity: `number.${device}_flow`,
      max_ml: 2000,
      restore_volume: true,
      stock_tank: id,
    };
  });
  const recipe = list.map(([id, , , ml]) => ({ pump: id, ml, ml_entity: null }));
  const batch = prefix
    ? {
        fill_valve: null,
        full_entity: null,
        full_state: "on",
        fill_timeout_min: 20,
        mix_pump: "switch.demo_f1_mix_pump",
        mix_valves: [],
        mix_power_sensor: null,
        mix_min_w: 0,
        premix_min: 2,
        postmix_min: 5,
        close_entities: [],
        hold_entity: null,
        filled_at_entity: null,
        recipe,
      }
    : {
        fill_valve: "switch.demo_tank_fill_valve",
        full_entity: "binary_sensor.demo_tank_full",
        full_state: "on",
        fill_timeout_min: 20,
        mix_pump: "switch.demo_mix_pump",
        mix_valves: ["switch.demo_recirc_valve"],
        mix_power_sensor: "sensor.demo_mix_pump_power",
        mix_min_w: 200,
        premix_min: 2,
        postmix_min: 5,
        close_entities: [],
        hold_entity: null,
        filled_at_entity: null,
        recipe,
      };
  if (prefix) put("switch.demo_f1_mix_pump", "off", { friendly_name: "Flower 1 mixing pump" });
  else {
    put("switch.demo_tank_fill_valve", "off", { friendly_name: "Batch tank fill valve" });
    put("binary_sensor.demo_tank_full", "off", { friendly_name: "Batch tank full float" });
    put("switch.demo_mix_pump", "off", { friendly_name: "Mixing pump" });
    put("switch.demo_recirc_valve", "off", { friendly_name: "Recirculation valve" });
    put("sensor.demo_mix_pump_power", 0, {
      friendly_name: "Mixing pump power",
      unit_of_measurement: "W",
      device_class: "power",
    });
  }
  put(`sensor.crop_steering_${prefix}dosing_config`, prefix ? 2 : 4, {
    friendly_name: `${room} dosing configuration`,
    pumps,
    batch,
    request: null,
    updated_at: at(24 * 6),
  });
  // The last batch, and before it the one earlier (Flower 1 stopped one by hand while it mixed);
  // since, a dose by hand in each room.
  const doses = Object.fromEntries(list.flatMap(([id, , , ml]) => (ml > 0 ? [[id, ml]] : [])));
  const lastDose = (ml: number, hoursAgo: number) => ({
    ml,
    at: at(hoursAgo),
    result: "finished",
  });
  const byHand = prefix
    ? { pump: "core", ml: 40, hours: 3 }
    : { pump: "balance", ml: 25, hours: 0.8 };
  const history = [
    {
      kind: "dose",
      at: at(byHand.hours),
      ended_at: at(byHand.hours - 3 / 3600),
      result: "finished",
      doses: { [byHand.pump]: byHand.ml },
      by: "Demo",
    },
    {
      kind: "batch",
      at: at(filled + 0.25),
      ended_at: at(filled),
      result: "finished",
      doses,
      by: "Demo",
    },
    {
      kind: "batch",
      at: at(filled + 24.25),
      ended_at: at(filled + 24.05),
      result: prefix ? "stopped: stop requested during mix after dosing" : "finished",
      doses,
      by: "Demo",
    },
  ];
  put(`sensor.crop_steering_${prefix}dosing`, "idle", {
    friendly_name: `${room} dosing`,
    pumps: Object.fromEntries(
      list.map(([id, , flow, ml], order) => [
        id,
        {
          state: "idle",
          flow_ml_s: flow,
          target_ml: null,
          started_at: null,
          expected_s: null,
          last:
            id === byHand.pump
              ? lastDose(byHand.ml, byHand.hours)
              : ml > 0
                ? lastDose(ml, filled + 0.15 - order * 0.01)
                : null,
        },
      ]),
    ),
    batch: {
      step: "idle",
      pump: null,
      started_at: at(filled + 0.25),
      step_started_at: null,
      steps: [],
      result: "finished",
      ended_at: at(filled),
    },
    handled: null,
    handled_result: null,
    history,
    updated_at: new Date(now - 18_000).toISOString(),
  });
}
/** Flower 2's probes, front and back of each zone's row, and the combined sensor's attributes as
 * the integration's fuse_probes publishes them (calculations.py): every probe used, except zone 3's
 * back EC probe, which stopped reporting. */
function demoProbes(
  put: (id: string, state: string | number, attributes?: Record<string, unknown>) => void,
  zone: number,
  kind: "vwc" | "ec",
  value: number,
) {
  const step = kind === "vwc" ? 0.8 : 0.15;
  const ids = ["front", "back"].map((side) => `sensor.demo_z${zone}_${side}_${kind}`);
  const out = kind === "ec" && zone === 3 ? ids[1] : null;
  // The zone reads the mean of the probes it uses: with one left out, the other one's reading; the
  // silent one kept its last, drifted reading.
  const reading = (id: string, side: number) =>
    id === out ? value + 0.75 : out ? value : value + (side ? -step : step);
  ids.forEach((id, side) =>
    put(id, reading(id, side).toFixed(kind === "ec" ? 2 : 1), {
      friendly_name: `Zone ${zone} ${side ? "back" : "front"} ${kind === "vwc" ? "VWC" : "EC"}`,
      unit_of_measurement: kind === "vwc" ? "%" : "mS/cm",
    }),
  );
  return {
    probes: 2,
    used: ids.filter((id) => id !== out),
    excluded: out ? { [out]: "not reporting" } : {},
    spread: out ? 0 : Math.round(step * 200) / 100,
  };
}
/** A demo zone's pore EC. Flower 2 is in the bulk (3.5-6): zone 1 reads under that band, as the
 * owner's own zone 1 did, and the others sit inside it. */
const demoEc = (room: number, zone: number) =>
  room ? 2.9 + zone * 0.2 : ([2.8, 4.4, 4.1][zone - 1] ?? 4.2);
/** Naive local time, as the controller stamps its journal (Python's datetime.now().isoformat()). */
const localStamp = (time: number) => {
  const date = new Date(time),
    two = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}T${two(date.getHours())}:${two(date.getMinutes())}:${two(date.getSeconds())}`;
};
/** A day of Jev's decisions for a room with lights 10:00-22:00 in flower bulk (vegetative): hours
 * after lights-on, zone, judge, answer, how sure, both phrasings, what it asked for, what code did,
 * code's why, and for an outcome the hour of the decision it checks (its answer is then that
 * decision's action, in words). */
const JEV_DAY: [
  number,
  number | null,
  string,
  string,
  number | null,
  boolean | null,
  string,
  string,
  string,
  number?,
][] = [
  [0.2, 1, "dawn", "keep drying", 0.78, true, "", "no action", ""],
  [0.3, 2, "probe", "healthy", 0.91, true, "", "no action", ""],
  [
    0.9,
    3,
    "dawn",
    "start ramp now",
    0.66,
    true,
    "start the ramp now",
    "refused",
    "dryback 3.2% under half the target (4.0%) and only 38 of 60 min waited",
  ],
  [
    1.35,
    1,
    "dawn",
    "start ramp now",
    0.84,
    true,
    "start the ramp now",
    "acted",
    "P0 far enough along",
  ],
  [2.6, 2, "ramp", "keep ramping", 0.74, true, "", "no action", ""],
  [
    3.2,
    1,
    "ramp",
    "slab full",
    0.81,
    true,
    "hand over to maintenance",
    "acted",
    "ramp near its ceiling with the minimum shots in",
  ],
  [3.3, 3, "ramp", "probe lagging", 0.55, false, "", "no action", ""],
  [
    4.2,
    1,
    "ramp",
    "hand over to maintenance",
    null,
    null,
    "",
    "worked",
    "VWC held within a point of the peak for the hour after the hand-over",
    3.2,
  ],
  [
    4.4,
    2,
    "salt",
    "below band vegetative",
    0.72,
    true,
    "hold the EC steer",
    "acted",
    "the EC steer stays inside its own clamp",
  ],
  [4.8, 3, "shot", "landed", 0.93, true, "", "no action", ""],
  [
    5,
    2,
    "stage",
    "ec below band",
    0.68,
    true,
    "CS-705: this zone is off the stage's arc",
    "acted",
    "alerts never move water",
  ],
  [
    5.02,
    2,
    "alerts",
    "first of its kind today",
    null,
    null,
    "CS-705: card only",
    "acted",
    "this zone is off the stage's arc",
  ],
  [
    5.5,
    3,
    "salt",
    "salts accumulating",
    0.63,
    true,
    "let the EC steer work",
    "acted",
    "the EC steer stays inside its own clamp",
  ],
  [6.3, 1, "zones", "recipe difference", 0.7, true, "", "no action", ""],
  [
    6.9,
    null,
    "alerts",
    "not urgent, stock lasts a week",
    null,
    null,
    "CS-608: card only",
    "acted",
    "Stock tanks running low",
  ],
  [
    7.5,
    3,
    "salt",
    "let the EC steer work",
    null,
    null,
    "",
    "did not work",
    "pore EC still rising 0.2 an hour two hours later",
    5.5,
  ],
  [8.2, 1, "dusk", "continue p2", 0.77, true, "", "no action", ""],
  [
    9.6,
    2,
    "dusk",
    "enter p3 now",
    0.61,
    true,
    "end the day's watering",
    "refused",
    "the zone is steered vegetative: its watering stops late (owner's doctrine)",
  ],
  [12.5, 1, "night", "real drying", 0.88, true, "", "no action", ""],
  [16, 3, "night", "real drying", 0.9, true, "", "no action", ""],
  // The Setpoints judge's nightly notch; yesterday's copy keeps it (index 21).
  [
    12.8,
    3,
    "setpoints",
    "smaller shots",
    0.7,
    true,
    "P2 shot 4.5% -> 4%",
    "acted",
    "inside Jev's range 3.5–5.5%",
  ],
  // Zone 2's re-water point set by hand (demoDay records it): Jev only notes it. Today only (22).
  [
    5.22,
    2,
    "setpoints",
    "set by hand",
    null,
    null,
    "p2 vwc threshold 62 -> 61",
    "acted",
    "your value is the new centre of Jev's range",
  ],
];
/** The controller's Jev sensors for a demo room: its usage and stage (flower day 37, the bulk), the
 * decision log over today and yesterday, and what each judge last said about each zone. */
function demoJev(
  put: (id: string, state: string | number, attributes?: Record<string, unknown>) => void,
  prefix: string,
  now: number,
) {
  const day = growDay(10, 22, now)!;
  const hours = (now - day.start) / 3_600_000;
  const titles: Record<string, string> = {
    dawn: "Morning start",
    ramp: "Ramp hand-over",
    salt: "Pore EC",
    dusk: "Day end",
    probe: "Probe trust",
    shot: "Shot landing",
    night: "Night low",
    zones: "Zone comparison",
    stage: "Stage arc",
    alerts: "Alert triage",
    setpoints: "Setpoints",
  };
  // Yesterday ran a little differently: fewer calls, a few minutes later.
  const days = [
    { start: day.start - 86_400_000 + 9 * 60_000, keep: (index: number) => index % 3 !== 1 },
    { start: day.start, keep: () => true },
  ];
  const entries = days
    .flatMap(({ start, keep }) =>
      JEV_DAY.filter((_, index) => keep(index)).map(
        ([hour, zone, judge, verdict, p, agreed, action, result, reason, of]) => ({
          time: start + hour * 3_600_000,
          entry: {
            t: localStamp(start + hour * 3_600_000),
            zone,
            judge,
            title: titles[judge],
            kind: result === "worked" || result === "did not work" ? "outcome" : "decision",
            verdict,
            p,
            agreed,
            action,
            result,
            reason,
            ...(of === undefined ? {} : { of: localStamp(start + of * 3_600_000) }),
          },
        }),
      ),
    )
    .filter((item) => item.time <= now)
    .sort((a, b) => b.time - a.time)
    .slice(0, 30)
    .map((item) => item.entry);
  const newest = entries[0];
  put(
    `sensor.crop_steering_${prefix}jev_log`,
    newest
      ? `${newest.t.slice(11, 16)} ${newest.zone === null ? "" : `Z${newest.zone} `}${newest.title}: ${newest.verdict} -> ${newest.action || newest.result}`
      : "no decisions yet",
    { entries, friendly_name: "Jev decisions", engine: "f2-control" },
  );
  const calls = Math.round(4 + 2.6 * Math.min(24, hours));
  put(`sensor.crop_steering_${prefix}jev`, "on", {
    calls_today: calls,
    input_tokens_today: calls * 3_050,
    errors_today: hours > 5 ? 1 : 0,
    last_error:
      hours > 5 ? "TimeoutError: Workers AI did not answer within 30 s (asked again)" : null,
    judges: [
      "alerts",
      "dawn",
      "dusk",
      "night",
      "probe",
      "ramp",
      "salt",
      "setpoints",
      "shot",
      "stage",
      "zones",
    ],
    judge_errors: {},
    stage: {
      day: 37,
      days: 56,
      name: "flower bulk",
      steering: "vegetative",
      stage_days: [22, 42],
      peak: "at or above field capacity",
      pore_ec: [3.5, 6.0],
      dryback_points: [10, 15],
      runoff_pct: [8, 16],
    },
    friendly_name: "Jev",
    engine: "f2-control",
  });
  const judge = (answer: string, p: number, directive: string | null, why: string) => ({
    verdicts: { main: { answer, p, agreed: true } },
    directive,
    why,
    streak: 1,
  });
  // What the Setpoints judge may move on each zone tonight, around the grower's own value as the
  // controller bands it: the shot size 1 % either side, the re-water point 2 under to 1 over.
  // Zone 3's shot size was notched down at its latest setpoint check (the journal's 22:48 entry,
  // tonight's once it has run); zone 2's re-water point was set by hand today, so its range
  // follows it.
  const notch = localStamp(
    [days[1], days[0]].map((item) => item.start + 12.8 * 3_600_000).find((time) => time <= now)!,
  )
    .slice(0, 16)
    .replace("T", " ");
  const setpoints = (zone: number) => {
    const shot = zone === 3 ? 4.5 : 4;
    return {
      managed: true,
      home: { p2_shot_size: shot, p2_vwc_threshold: 61 },
      range: { p2_shot_size: [shot - 1, shot + 1], p2_vwc_threshold: [59, 62] },
      current: { p2_shot_size: 4, p2_vwc_threshold: 61 },
      last: zone === 3 ? `${notch}: P2 shot 4.5% -> 4%` : null,
      paused_until: null,
    };
  };
  put(`sensor.crop_steering_${prefix}zone_1_jev`, "watching", {
    judges: { dusk: judge("continue_p2", 0.77, null, "no action") },
    setpoints: setpoints(1),
    friendly_name: "Zone 1 Jev",
    engine: "f2-control",
  });
  put(`sensor.crop_steering_${prefix}zone_2_jev`, "salt", {
    judges: {
      salt: judge(
        "below_band_vegetative",
        0.72,
        "ec_mode hold",
        "the EC steer stays inside its own clamp",
      ),
    },
    setpoints: setpoints(2),
    friendly_name: "Zone 2 Jev",
    engine: "f2-control",
  });
  put(`sensor.crop_steering_${prefix}zone_3_jev`, "watching", {
    judges: {
      shot: judge("landed", 0.93, null, "no action"),
      setpoints: judge("smaller_shots", 0.7, "setpoint p2_shot_size 4", "inside Jev's range"),
    },
    setpoints: setpoints(3),
    friendly_name: "Zone 3 Jev",
    engine: "f2-control",
  });
}
/** The demo's controller keeps the clock as a real one does: from lights-off to lights-on every zone
 * is in P3 with nothing firing, its valve shut and only a rescue shot possible; by day the demo's own
 * day returns (zone 1 ramping, the others in maintenance). It changes a room only when its lights
 * do, so what someone changes in the demo (a phase picked by hand) stays until then. */
export function demoClock(states: States, now = Date.now()): States {
  let next: States | null = null;
  let base: States | null = null;
  for (const config of Object.values(states)) {
    if (!/^sensor\.crop_steering_.*engine_config$/.test(config.entity_id)) continue;
    const prefix = String(config.attributes.prefix ?? "");
    const root = `sensor.crop_steering_${prefix}`;
    const day = growDay(
      numeric(states[`number.crop_steering_${prefix}lights_on_hour`]),
      numeric(states[`number.crop_steering_${prefix}lights_off_hour`]),
      now,
    );
    const decision = states[`${root}current_decision`];
    if (!day || !decision) continue;
    const night = now >= day.lightsOff;
    if (decision.attributes.demo_night === night) continue;
    base ??= createDemo(now);
    const out = (next ??= { ...states });
    const stamp = new Date(now).toISOString();
    const set = (id: string, state: string, attributes?: Record<string, unknown>) => {
      if (!out[id]) return;
      out[id] = {
        ...out[id],
        state,
        attributes: attributes ?? out[id].attributes,
        last_changed: stamp,
        last_updated: stamp,
      };
    };
    const valves = (config.attributes.valves ?? {}) as Record<string, string>;
    for (let zone = 1; zone <= Number(config.attributes.num_zones); zone++) {
      const z = `${root}zone_${zone}_`;
      for (const id of [
        `${z}phase`,
        `${z}status`,
        `${z}waiting_for_app`,
        `${z}last_irrigation_app`,
        valves[zone],
      ])
        if (id && base[id] && !night) set(id, base[id].state, base[id].attributes);
      if (!night) continue;
      set(`${z}phase`, "P3");
      // The day's last maintenance shot, two hours or so before lights-off (demoDay's day).
      set(
        `${z}last_irrigation_app`,
        new Date(day.lightsOff - 2.25 * 3_600_000 - zone * 3 * 60_000).toISOString(),
      );
      set(`${z}status`, "Overnight dryback — rescue only", { reason: "demo" });
      if (valves[zone]) set(valves[zone], "off");
      set(`${z}waiting_for_app`, "P3", {
        at: stamp,
        conditions: [
          {
            rule: "p3_emergency",
            shot: true,
            to: null,
            metric: "vwc",
            op: "<",
            value: numeric(
              states[`number.crop_steering_${prefix}zone_${zone}_p3_emergency_vwc_threshold`],
            ),
            now: numeric(states[`${root}vwc_zone_${zone}`]),
          },
          {
            rule: "lights_on",
            shot: false,
            to: "P0",
            in_min: Math.round((day.end - now) / 60_000),
          },
        ],
      });
    }
    // Its records end with the day's last shots and each zone's move to P3 two hours before
    // lights-off (demoDay's day); by day they are the demo's own.
    const log = `${root}activity_log`;
    const events = (base[log]?.attributes.events ?? []) as LogEvent[];
    if (!night && base[log]) set(log, base[log].state, base[log].attributes);
    if (night && events.length) {
      const shift =
        Math.max(...events.map((event) => Date.parse(event.timestamp))) -
        (day.lightsOff - 2.25 * 3_600_000);
      const p3: LogEvent[] = Array.from(
        { length: Number(config.attributes.num_zones) },
        (_, i) => ({
          id: `${prefix}${i + 1}-p3`,
          timestamp: new Date(day.lightsOff - 2 * 3_600_000 + (i + 1) * 180_000).toISOString(),
          message: "P2 → P3: the day's watering is done (demo).",
          type: "phase",
          zoneId: i + 1,
        }),
      );
      set(log, base[log].state, {
        ...base[log].attributes,
        events: [
          ...p3.reverse(),
          ...events.map((event) => ({
            ...event,
            timestamp: new Date(Date.parse(event.timestamp) - shift).toISOString(),
          })),
        ],
      });
    }
    const pump = typeof config.attributes.pump === "string" ? config.attributes.pump : "";
    if (night) {
      set(pump, "off");
      set(`${root}current_decision`, "Holding — all zones in band", {
        fired: [],
        blocked: [],
        demo_night: true,
      });
    } else {
      if (base[pump]) set(pump, base[pump].state);
      const day = base[`${root}current_decision`];
      set(`${root}current_decision`, day.state, { ...day.attributes, demo_night: false });
    }
  }
  return next ?? states;
}
/** The demo controller reports in like a running one, so it never reads as stopped: its heartbeat,
 * and its dosing report's time, which a real one refreshes at least every 60 s. */
export function demoBeat(states: States, now = Date.now()): States {
  const stamp = new Date(now).toISOString();
  return Object.fromEntries(
    Object.entries(states).map(([id, entity]) => [
      id,
      /^sensor\.crop_steering_.*ai_heartbeat$/.test(id)
        ? { ...entity, last_updated: stamp, attributes: { ...entity.attributes, last_beat: stamp } }
        : /^sensor\.crop_steering_.*waiting_for_app$/.test(id)
          ? { ...entity, last_updated: stamp, attributes: rebased(entity.attributes, now) }
          : /^sensor\.crop_steering_.*dosing$/.test(id)
            ? {
                ...entity,
                last_updated: stamp,
                attributes: { ...entity.attributes, updated_at: stamp },
              }
            : entity,
    ]),
  );
}
/** A demo zone's waiting_for conditions, from its own numbers, as the engine would give them. */
function demoWaiting(
  phase: string,
  zone: {
    vwc: number;
    ec: number;
    peak: number;
    trigger: number;
    ecTarget: number;
    toLightsOff: number;
  },
) {
  const round = (value: number) => Math.round(value * 100) / 100;
  if (phase === "P1")
    return [
      {
        rule: "p1_ramp",
        shot: true,
        to: null,
        metric: "vwc",
        op: "<",
        value: zone.peak,
        now: zone.vwc,
        in_min: 4,
      },
      {
        rule: "p1_done",
        shot: false,
        to: "P2",
        metric: "vwc",
        op: ">=",
        value: zone.peak,
        now: zone.vwc,
        shots_left: 0,
        ec_max: round(zone.ecTarget * 1.15),
        ec_now: zone.ec,
      },
      { rule: "p1_max_shots", shot: false, to: "P2", shots_left: 3 },
    ];
  return [
    {
      rule: "p2_topup",
      shot: true,
      to: null,
      metric: "vwc",
      op: "<",
      value: zone.trigger,
      now: zone.vwc,
    },
    {
      rule: "p2_dilute",
      shot: true,
      to: null,
      metric: "ec",
      op: ">",
      value: round(zone.ecTarget * 1.2),
      now: zone.ec,
    },
    { rule: "lights_off", shot: false, to: "P3", in_min: zone.toLightsOff },
  ];
}
const minutesUntil = (now: number, hour: number) => {
  const date = new Date(now);
  return (hour * 60 - (date.getHours() * 60 + date.getMinutes()) + 1440) % 1440;
};
/** The demo's waits keep their clock times as its clock moves: `at` becomes now, each wait shortens. */
function rebased(attributes: Record<string, unknown>, now: number) {
  const at = Date.parse(String(attributes.at));
  const gone = Number.isFinite(at) ? (now - at) / 60_000 : 0;
  const conditions = Array.isArray(attributes.conditions)
    ? attributes.conditions.map((item: Record<string, unknown>) =>
        typeof item.in_min === "number"
          ? { ...item, in_min: Math.max(0, Math.round((item.in_min - gone) * 10) / 10) }
          : item,
      )
    : attributes.conditions;
  return { ...attributes, at: new Date(now).toISOString(), conditions };
}
/** Demo-only side effects of a switch write that a real controller would publish itself. */
export function demoReact(states: States, entityId: string, value: unknown): States {
  // What the controller does with a phase picked on a zone's Set Phase select: it moves the zone,
  // then sets the select back to Keep.
  const pick = entityId.match(/^select\.crop_steering_(.*zone_\d+_)set_phase$/);
  if (pick && typeof value === "string" && /^P[0-3]$/.test(value)) {
    const phase = `sensor.crop_steering_${pick[1]}phase`;
    return {
      ...states,
      [entityId]: { ...states[entityId], state: "Keep" },
      ...(states[phase] ? { [phase]: { ...states[phase], state: value } } : {}),
    };
  }
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
/** One demo zone's shots on the grow-day from lights-on `start`, shifted like its probe so they land
 * where its readings jump: six P1 ramp shots from 1.5 h, then a P2 top-up every 75 minutes until P3,
 * each grow-day's a little longer or shorter than the day before's. Flower 2's zone 2 waits out a
 * feed-EC hold; Flower 1's zone 3 is disabled from 6 h. */
function demoZoneDay(prefix: string, zone: number, start: number, p3: number) {
  const vwc = `sensor.crop_steering_${prefix}vwc_zone_${zone}`;
  const at = (hour: number) => start + seedOf(vwc) * 180_000 + hour * 3_600_000;
  const hold = !prefix && zone === 2 ? [2.5, 2.7] : null;
  const disabled = prefix && zone === 3 ? 6 : Infinity;
  const drift = 1 + 0.12 * Math.sin(new Date(start).getDate() * 1.9 + zone);
  const shots: { start: number; stop: number; text: string }[] = [];
  const shot = (hour: number, seconds: number, text: string) =>
    shots.push({ start: at(hour), stop: at(hour) + seconds * 1000, text });
  for (let index = 0, hour = 1.5; index < 6; index++, hour += 1 / 3) {
    if (hold && hour >= hold[0] && hour < hold[1]) hour = hold[1];
    shot(hour, Math.round((90 + 15 * index) * drift), `P1 P1 ramp shot ${index + 1}/6 (demo)`);
  }
  for (let hour = 4.75; hour < Math.min(p3, disabled); hour += 1.25)
    shot(hour, Math.round(150 * drift), "P2 P2 top-up (demo)");
  return { vwc, at, hold, disabled, shots };
}
const FILL_MS = 20 * 60_000;
/** How low each demo cycle runs before its refill, in %, give or take the last shot's few: F2's
 * own lows over a week ran 0 to 25. */
const TANK_LOWS = [0, 15, 20, 1, 15, 0, 20, 0, 15, 2];
/** The demo batch tank as F2's behaves: each fill takes 20 minutes and leaves it at 100 %, the
 * pump draws it down while a shot runs (started 3 s before the valve, as the controller primes it;
 * about 1.6 % a pump-minute in Flower 2, 1.3 % in Flower 1), and it is filled again once it has run
 * low, to between 0 and 25 %: once or twice a day. The recorded last fill is the anchor; the fills
 * before it are worked back from it through the shots of the ten grow-days before. A shot while
 * the tank fills draws nothing. Null without a lights schedule or a recorded fill. */
function demoTankModel(states: States, prefix: string, now: number) {
  const config = states[`sensor.crop_steering_${prefix}engine_config`]?.attributes;
  const hour = (key: string) => numeric(states[`number.crop_steering_${prefix}lights_${key}_hour`]);
  const on = hour("on"),
    off = hour("off");
  const today = growDay(on, off, now);
  const last = Date.parse(states[String(config?.[TANK_KEYS.fill] ?? "")]?.state ?? "");
  if (!config || !today || on === null || off === null || !Number.isFinite(last)) return null;
  const p3 = Math.max(4, ((off - on + 24) % 24 || 12) - 2);
  const shots = [today, ...earlierDays(today, 10, () => ({ on, off }))]
    .flatMap((day) =>
      Array.from({ length: Number(config.num_zones) }, (_, index) =>
        demoZoneDay(prefix, index + 1, day.start, p3).shots.filter((shot) => shot.start < now),
      ).flat(),
    )
    .sort((a, b) => a.start - b.start);
  const runs: { start: number; stop: number }[] = [];
  for (const shot of shots) {
    const run = runs.at(-1);
    if (run && shot.start - 3_000 <= run.stop) run.stop = Math.max(run.stop, shot.stop);
    else runs.push({ start: shot.start - 3_000, stop: shot.stop });
  }
  const rate = (prefix ? 1.3 : 1.6) / 60_000; // % of the tank per pump-millisecond
  // Back from the recorded fill: each cycle's pump runs drew 100 % down to its low, and the run
  // before them, the one that would have drawn it lower, ended the cycle before. That run left the
  // tank low, so the fill started as it ended, as F2's is refilled, unless this cycle's first run
  // came too soon after; then the fill ended just before that first run.
  const fills = [last];
  for (let cycle = 0; ; cycle++) {
    let index = runs.length - 1;
    while (index >= 0 && runs[index].stop > fills[cycle] - FILL_MS) index--;
    let drawn = 0;
    const need = (100 - TANK_LOWS[cycle % TANK_LOWS.length]) / rate;
    const length = (run: { start: number; stop: number }) => run.stop - run.start;
    while (index >= 0 && drawn + length(runs[index]) <= need) drawn += length(runs[index--]);
    if (index < 0 || !drawn) break;
    const first = runs[index + 1].start,
      low = runs[index].stop;
    fills.push(low + FILL_MS + 62_000 <= first ? low + FILL_MS + 2_000 : first - 120_000);
  }
  fills.reverse();
  const draws = runs.filter(
    (run) => !fills.some((fill) => run.start < fill && run.stop > fill - FILL_MS),
  );
  return {
    runs,
    fills,
    draws,
    /** The level at `time` in whole %, as F2's sensor reports it. */
    level(time: number): number {
      let index = -1;
      while (index + 1 < fills.length && fills[index + 1] <= time) index++;
      const from = index < 0 ? -Infinity : fills[index];
      const until = Math.min(time, (fills[index + 1] ?? Infinity) - FILL_MS);
      const drawn = draws.reduce(
        (sum, run) => sum + Math.max(0, Math.min(run.stop, until) - Math.max(run.start, from)),
        0,
      );
      return Math.round(Math.min(100, Math.max(0, 100 - rate * drawn)));
    },
  };
}
/** The demo batch tank's record over [from, to] (demoTankModel): its level, the pump, the tank
 * filling and the last-fill record. */
function demoTank(
  states: States,
  config: EntityState,
  from: number,
  to: number,
  now: number,
): TimelineRows {
  const mapped = (key: string) => String(config.attributes[key] ?? "");
  const model = demoTankModel(states, String(config.attributes.prefix ?? ""), now);
  if (!model) return {};
  const switched = (runs: { start: number; stop: number }[]): TimelineRow[] => [
    { state: runs.some((run) => run.start <= from && from < run.stop) ? "on" : "off", time: from },
    ...runs.flatMap((run) => [
      ...(run.start > from ? [{ state: "on", time: run.start }] : []),
      ...(run.stop > from ? [{ state: "off", time: run.stop }] : []),
    ]),
  ];
  const iso = (time: number) => new Date(time).toISOString();
  const before = model.fills.filter((fill) => fill <= from).at(-1);
  return {
    [mapped(TANK_KEYS.level)]: [from, ...model.draws.map((run) => run.stop), ...model.fills, to]
      .filter((time, index) => !index || (time > from && time <= to))
      .map((time) => ({ state: String(model.level(time)), time })),
    [mapped(TANK_KEYS.pump)]: switched(model.runs),
    [mapped(TANK_KEYS.filling)]: switched(
      model.fills.map((fill) => ({ start: fill - FILL_MS, stop: fill })),
    ),
    [mapped(TANK_KEYS.fill)]: [
      ...(before === undefined ? [] : [{ state: iso(before), time: from }]),
      ...model.fills
        .filter((fill) => fill > from)
        .map((fill) => ({ state: iso(fill), time: fill })),
    ],
  };
}
/** A recorded grow-day for the day timeline, on the demo probes' own day shape (P0 dryback, a
 * six-shot P1 ramp, P2 top-ups every 75 minutes, P3 two hours before lights-off), each zone shifted
 * like its probe so its shots land where its readings jump. Flower 2's zone 2 waits out a feed-EC
 * hold that ends when the feed band is widened; Flower 1's zone 3 is held since it was disabled.
 * Earlier grow-days, to compare today with, come from the same curve. */
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
  // Anything not drawn below held its current value all day, but a room switched off now was on
  // in the days before.
  const past = request.end < now - 60_000;
  for (const id of wanted)
    if (states[id])
      put(id, [
        {
          state: past && id.endsWith("room_active") ? "on" : states[id].state,
          time: request.start,
        },
      ]);
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
      const { vwc, at, hold, disabled, shots } = demoZoneDay(prefix, zone, request.start, p3);
      const phases = [
        [0.02, "P0"],
        [1.5, "P1"],
        [3.5, "P2"],
        [p3, "P3"],
      ] as const;
      put(`sensor.crop_steering_${prefix}zone_${zone}_phase`, [
        { state: "P3", time: request.start },
        // Lights-on moves every zone to P0 at once; the rest follows the zone's own day.
        ...phases.map(([hour, state]) => ({
          state,
          time: state === "P0" ? request.start + hour * 3_600_000 : at(hour),
        })),
      ]);
      const valve: TimelineRow[] = [{ state: "off", time: request.start }];
      for (const { start, stop, text } of shots) {
        valve.push({ state: "on", time: start }, { state: "off", time: stop });
        events.push(
          { time: stop + 2_000, zone, list: "fired", text },
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
      // Every day on one curve that ends at the live reading, so an earlier day joins up with today;
      // pore EC on the same day, concentrating as the slab dries and easing as it is watered.
      const ec = `sensor.crop_steering_${prefix}ec_zone_${zone}`;
      for (const probe of wanted.has(ec) ? [vwc, ec] : [vwc]) {
        const recorded = demoHistory(states, [probe], (now - request.start) / 3_600_000, now);
        put(
          probe,
          (recorded[0]?.points ?? []).map((point) => ({
            state: String(point.value),
            time: Date.parse(point.time),
          })),
        );
      }
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
    // The batch tank, for the tank chart, when it is asked for.
    if (Object.values(TANK_KEYS).some((key) => wanted.has(String(config.attributes[key]))))
      for (const [id, list] of Object.entries(demoTank(states, config, request.start, end, now)))
        put(id, list);
  }
  return rows;
}
/** Recorded water for the Water use panel, as the hourly statistics of each zone's water-today
 * counter: a grow that began on the demo grow plan's start date after eight dry grow-days, drinking
 * a little more each day. Complete grow-days only; the live counter supplies today. Before it, the
 * demo's previous run (112 to 57 days ago, comparison-demo) drank a fifth less by grow day. */
export function demoWaterRecord(
  states: States,
  request: WaterRecordRequest,
  now = Date.now(),
): Record<string, CounterSample[]> {
  const today = localDate(new Date(now));
  const growStart = dateForDay(today, -13); // as the demo plan (operator-demo)
  const grows = [
    {
      start: addDays(today, -112),
      first: addDays(today, -112),
      last: addDays(today, -57),
      scale: 0.8,
    },
    { start: growStart, first: addDays(growStart, -8), last: today, scale: 1 },
  ];
  const samples: Record<string, CounterSample[]> = {};
  for (const entityId of request.entityIds) {
    const match = entityId.match(
      /^sensor\.crop_steering_(.*?)zone_(\d+)_daily_water_(?:app|usage)$/,
    );
    if (!match || !states[entityId]) continue;
    const [, prefix, zone] = match;
    const hour = (key: string, fallback: number) =>
      numeric(states[`number.crop_steering_${prefix}lights_${key}_hour`]) ?? fallback;
    const on = hour("on", 8);
    const photoperiod = (hour("off", 20) - on + 24) % 24 || 12;
    const lightsOn = (day: string) => {
      const [year, month, date] = day.split("-").map(Number);
      return new Date(year, month - 1, date, 0, Math.round(on * 60)).getTime();
    };
    const list: CounterSample[] = [];
    for (const grow of grows)
      for (
        let day = grow.first;
        day <= grow.last && lightsOn(addDays(day, 1)) <= now;
        day = addDays(day, 1)
      ) {
        const age = daysBetween(grow.start, day) + 1;
        const total =
          age < 1
            ? 0
            : grow.scale *
              Math.min(
                38,
                16 +
                  0.9 * age +
                  1.6 * Number(zone) +
                  (prefix ? 2 : 0) +
                  2.5 * Math.sin(1.7 * age + Number(zone)),
              );
        // One reading at the end of each hour; a daylight-saving grow-day has 23 or 25 of them.
        const from = lightsOn(day);
        for (let time = from + 3_600_000 - 1; time < lightsOn(addDays(day, 1)); time += 3_600_000) {
          const share = Math.min(
            1,
            Math.max(0, ((time + 1 - from) / 3_600_000 - 1) / (photoperiod - 3)),
          );
          if (time >= request.start && time <= request.end)
            list.push({ time, value: Math.round(total * share * 100) / 100 });
        }
      }
    samples[entityId] = list;
  }
  return samples;
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
