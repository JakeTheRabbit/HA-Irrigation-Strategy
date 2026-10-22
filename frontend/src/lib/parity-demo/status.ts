import type { States } from "../types";
import { demoId } from "./journal";

/** The 3.18 room entities the All rooms page reads, for the demo (`?demo=1`; not with
 * `?backend=3.17`). As in the Journal: Room A plays F2 (flower bulk, day 38 of 63; zone 2 waits
 * for the pump and its last shot came up short; zone 3 waters by timer; the feed pH probe is due
 * for calibration), Room B plays F1 (flower stretch, day 12 of 63; zone 2's back sensor alert is
 * open). */
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
  // The Journal's shot size (1.21 L commanded); 0.96 L arrived.
  put("sensor.crop_steering_zone_2_flow_ratio", 0.79, { commanded_l: 1.21, metered_l: 0.96, shot_id: demoId(now - 600_000, "room::shot:2") });
  return out;
}
