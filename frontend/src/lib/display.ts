import type { SteCopy } from "./ste-copy";
import type { EntityState, States } from "./types";

/** What the dashboard shows in a room: the room's display options (Settings › Display), kept by
 * the integration in one store per room and published as sensor.crop_steering_<prefix>display
 * (custom_components/crop_steering/display.py). Every option is off until someone turns it on:
 * an option that is missing (an older integration, or no store) reads as its default, so the
 * dashboard then looks as it always did. */
export interface DisplayOptions {
  today_tank_readout: boolean;
  today_zone_layout: "cards" | "table";
  show_camera: boolean;
  show_climate: boolean;
  show_substrate_temp: boolean;
  zone_day_deltas: boolean;
  show_hardware: boolean;
  show_equipment_lanes: boolean;
  show_room_day_lanes: boolean;
  show_dryback_drivers: boolean;
  planner_reference_rows: boolean;
  planner_day_curve: boolean;
}
export type DisplayKey = keyof DisplayOptions;

export const DISPLAY_DEFAULTS: DisplayOptions = {
  today_tank_readout: false,
  today_zone_layout: "cards",
  show_camera: false,
  show_climate: false,
  show_substrate_temp: false,
  zone_day_deltas: false,
  show_hardware: false,
  show_equipment_lanes: false,
  show_room_day_lanes: false,
  show_dryback_drivers: false,
  planner_reference_rows: false,
  planner_day_curve: false,
};

/** One row of Settings › Display: an on/off option, or a choice between two values. */
export interface DisplayRow {
  key: DisplayKey;
  group: "Today" | "Zone page" | "History" | "Plan";
  label: string;
  copy: SteCopy;
  /** For a choice: its two values and their words, the default first. */
  choice?: { value: string; label: string }[];
}

/** The rows Settings › Display offers, in page order. A row is listed once its panel exists. */
export const DISPLAY_ROWS: DisplayRow[] = [
  {
    key: "today_tank_readout",
    group: "Today",
    label: "Tank readout",
    copy: {
      tooltip:
        "Shows the level, EC and pH of the feed tank in the room line on Today, in grey, also when all values are correct.",
      impact:
        "Off: Today shows the tank only when a value is low or out of range. On: the room line always shows the tank values. A value that is low or out of range gives the same warning line as before.",
      guidance:
        "The room must have tank sensors in Equipment › Setup. Without them, Today shows no tank values. A phone does not show the tank values on Today. Use Equipment › Feed.",
    },
  },
];

export interface RoomDisplay {
  /** The room has the store (an integration from before it does not, and nothing can be saved). */
  available: boolean;
  revision: number;
  options: DisplayOptions;
}

export const displayEntityId = (prefix: string) => `sensor.crop_steering_${prefix}display`;

/** The room's display options from its sensor: each option the sensor does not carry, or carries
 * with a value it does not take, reads as its default. */
export function readDisplay(entity: EntityState | undefined): RoomDisplay {
  const revision = Number(entity?.state);
  const available = !!entity && Number.isInteger(revision) && revision >= 0;
  const options = { ...DISPLAY_DEFAULTS } as Record<DisplayKey, boolean | string>;
  for (const key of Object.keys(DISPLAY_DEFAULTS) as DisplayKey[]) {
    const value = available ? entity!.attributes[key] : undefined;
    if (typeof DISPLAY_DEFAULTS[key] === "boolean" ? typeof value === "boolean" : value === "table")
      options[key] = value as boolean | string;
  }
  return { available, revision: available ? revision : 0, options: options as DisplayOptions };
}

export const roomDisplay = (states: States, prefix: string) =>
  readDisplay(states[displayEntityId(prefix)]);

/** The demo's ?display=a,b (or ?display=all): those options on in every demo room, for a look at
 * each panel without a trip to Settings. */
export function demoDisplay(states: States, param: string | null): States {
  if (!param) return states;
  const wanted = param === "all" ? Object.keys(DISPLAY_DEFAULTS) : param.split(",");
  const next = { ...states };
  for (const [id, entity] of Object.entries(states)) {
    if (!/^sensor\.crop_steering_[a-z0-9_]*display$/.test(id)) continue;
    const attributes = { ...entity.attributes };
    for (const key of wanted)
      if (key in DISPLAY_DEFAULTS) attributes[key] = key === "today_zone_layout" ? "table" : true;
    next[id] = { ...entity, attributes };
  }
  return next;
}
