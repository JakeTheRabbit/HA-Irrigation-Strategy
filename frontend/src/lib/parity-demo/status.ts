import type { States } from "../types";
import { demoId, demoJournal, demoLightsOn, demoZonePause } from "./journal";

/** The 3.18 room entities the All rooms page reads, for the demo (`?demo=1`; not with
 * `?backend=3.17`). As in the Journal: Room A plays F2 (flower bulk, day 38 of 63; zone 2 waits
 * for the pump and its last shot came up short; zone 3 waters by timer; the feed pH probe is due
 * for calibration), Room B plays F1 (flower stretch, day 12 of 63; zone 2's back sensor alert is
 * open, its back sensor silent 3 h and left out; zone 3 paused by Ben, as the Journal says, so its
 * switch last changed then; each zone's shots and water today are the Journal's). */
export function demoParityStatus(states: States, now: number): States {
  const out: States = { ...states };
  const stamp = new Date(now - 18_000).toISOString();
  const put = (entity_id: string, state: string | number, attributes: Record<string, unknown> = {}) => {
    out[entity_id] = {
      entity_id,
      state: String(state),
      attributes: { ...attributes, synthetic: true },
      last_updated: stamp,
      last_changed: stamp,
    };
  };
  const rooms = [
    { prefix: "", day: 38, left: 25, stage: "Flower bulk" },
    { prefix: "room_b_", day: 12, left: 51, stage: "Flower stretch" },
  ];
  for (const { prefix, day, left, stage } of rooms) {
    const room_id = `room:${prefix}`;
    put(`sensor.crop_steering_${prefix}grow_day`, day, { friendly_name: "Grow day", room_id });
    put(`sensor.crop_steering_${prefix}days_to_harvest`, left, { friendly_name: "Days to harvest", room_id });
    put(`sensor.crop_steering_${prefix}stage`, stage, { friendly_name: "Stage", room_id });
    const queue = prefix
      ? []
      : [{ zone: 2, position: 2, requested_at: new Date(now - 40_000).toISOString(), priority: "steering" }];
    put(`binary_sensor.crop_steering_${prefix}shot_queued`, queue.length ? "on" : "off", { room_id, queue });
    const alerts = prefix
      ? [
          {
            event_id: demoId(now - 3 * 3_600_000, `${room_id}:alert:probe_silent`),
            ts: new Date(now - 3 * 3_600_000).toISOString(),
            code: "CS-406",
            title: "Back sensor silent 3 h, left out of the reading",
            zone: 2,
            rule_id: null,
            acknowledged: false,
          },
        ]
      : [];
    put(`sensor.crop_steering_${prefix}alerts_open`, alerts.length, { room_id, alerts });
    put(`binary_sensor.crop_steering_${prefix}calibration_due`, prefix ? "off" : "on", {
      friendly_name: "Feed probe calibration due",
      room_id,
      probes: prefix ? [] : ["feed_ph"],
      due_at: prefix ? {} : { feed_ph: new Date(now - 2 * 86_400_000).toISOString() },
    });
    for (const zone of [1, 2, 3])
      put(`select.crop_steering_${prefix}zone_${zone}_irrigation_mode`, !prefix && zone === 3 ? "timer" : "steering", {
        options: ["steering", "timer", "off"],
      });
  }
  // Room B's front and back sensors in each zone. Zone 2's back sensor stopped reporting 3 h ago
  // (the open CS-406 alert): the zone reads its front sensor only.
  for (const zone of [1, 2, 3]) {
    const silent = zone === 2;
    for (const kind of ["vwc", "ec"] as const) {
      const fused = `sensor.crop_steering_room_b_${kind}_zone_${zone}`;
      const value = Number(states[fused]?.state);
      const step = kind === "vwc" ? 0.8 : 0.1;
      const ids = ["front", "back"].map((side) => `sensor.demo_room_b_z${zone}_${side}_${kind}`);
      ids.forEach((id, side) => {
        put(id, (silent ? value + (side ? step : 0) : value + (side ? -step : step)).toFixed(kind === "ec" ? 2 : 1), {
          friendly_name: `Zone ${zone} ${side ? "back" : "front"} ${kind === "vwc" ? "VWC" : "EC"}`,
          unit_of_measurement: kind === "vwc" ? "%" : "mS/cm",
        });
        if (silent && side) out[id].last_updated = out[id].last_changed = new Date(now - 3 * 3_600_000).toISOString();
      });
      out[fused] = {
        ...states[fused],
        attributes: {
          ...states[fused]?.attributes,
          probes: 2,
          used: silent ? [ids[0]] : ids,
          excluded: silent ? { [ids[1]]: "not reporting" } : {},
        },
      };
    }
  }
  // Each Room B zone's shots and water today, as the Journal has them.
  const since = demoLightsOn("room:room_b_", now);
  const day = demoJournal("room:room_b_", now).filter((e) => e.kind === "shot.completed" && Date.parse(e.ts) >= since);
  for (const zone of [1, 2, 3]) {
    const shots = day.filter((e) => e.zone === zone);
    const litres = shots.reduce((sum, e) => sum + Number(e.data.metered_l), 0);
    for (const [key, state] of [
      ["irrigation_count_app", shots.length],
      ["daily_water_app", litres.toFixed(2)],
    ] as const) {
      const id = `sensor.crop_steering_room_b_zone_${zone}_${key}`;
      out[id] = { ...states[id], state: String(state) };
    }
  }
  // Who paused Room B zone 3: the Journal's user, a Home Assistant person; the switch changed then.
  put("person.ben", "home", { friendly_name: "Ben", user_id: "demo-user" });
  const pause = demoZonePause("room:room_b_", now);
  const switchId = `switch.crop_steering_room_b_zone_${pause?.zone}_enabled`;
  if (pause && out[switchId])
    out[switchId] = { ...out[switchId], last_changed: new Date(pause.at).toISOString() };
  // The Journal's shot size (1.21 L commanded); 0.96 L arrived.
  put("sensor.crop_steering_zone_2_flow_ratio", 0.79, { commanded_l: 1.21, metered_l: 0.96, shot_id: demoId(now - 600_000, "room::shot:2") });
  return out;
}

/** A 3.17 integration's shot table per zone (`zone_N_shot_log_app.shots`, newest first), from the
 * same Journal shots: what the zone page's shot log reads without the Journal (`?backend=3.17`). */
export function demoShotTable(states: States, now: number): States {
  const out: States = { ...states };
  for (const room_id of ["room:", "room:room_b_"]) {
    const events = demoJournal(room_id, now);
    const starts = new Map(
      events.filter((e) => e.kind === "shot.started").map((e) => [e.correlation?.intent_id, e]),
    );
    for (const zone of [1, 2, 3]) {
      const shots = events
        .filter((e) => e.kind === "shot.completed" && e.zone === zone)
        .map((e) => {
          const start = starts.get(e.correlation?.intent_id);
          return { start: start?.ts ?? e.ts, kind: start?.data.kind ?? "shot", litres: e.data.metered_l, verdict: "landed" };
        })
        .reverse();
      const entity_id = `sensor.crop_steering_${room_id.slice(5)}zone_${zone}_shot_log_app`;
      out[entity_id] = {
        entity_id,
        state: shots.length ? "landed" : "unknown",
        attributes: { friendly_name: `Zone ${zone} shot log`, shots },
        last_updated: new Date(now).toISOString(),
        last_changed: new Date(now).toISOString(),
      };
    }
  }
  return out;
}
