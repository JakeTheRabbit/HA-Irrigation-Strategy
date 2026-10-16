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
  show_equipment_lanes: false,
  show_room_day_lanes: false,
  show_dryback_drivers: false,
  planner_reference_rows: false,
  planner_day_curve: false,
};

/** One row of Settings › Display: an on/off option, or a choice between two values. */
export interface DisplayRow {
  key: DisplayKey | "manual_hardware_enabled";
  /** A row kept in a switch of its own rather than the display store: that switch's id. */
  entity?: (prefix: string) => string;
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
  {
    key: "today_zone_layout",
    group: "Today",
    label: "Zones as",
    choice: [
      { value: "cards", label: "Cards" },
      { value: "table", label: "Table" },
    ],
    copy: {
      tooltip:
        "Shows the zones on Today as cards, or as one table with a row for each zone: phase, VWC, EC, dryback, water, shots and the next action.",
      impact:
        "Cards: each zone has a card, as before. Table: a laptop shows one table. A phone always shows the cards.",
      guidance: "A table is easier to read in a room with many zones. Select a row to open its zone.",
    },
  },
  {
    key: "show_climate",
    group: "Zone page",
    label: "Room climate",
    copy: {
      tooltip:
        "Shows the air temperature, humidity, VPD and dew point of the room on each zone page, in grey.",
      impact: "Off: the zone page does not show them. The history chart shows the climate either way.",
      guidance:
        "The room must have climate sensors in Equipment › Setup. A value shows in colour only when it is outside the band of the grow plan.",
    },
  },
  {
    key: "show_substrate_temp",
    group: "Zone page",
    label: "Root-zone temperature",
    copy: {
      tooltip: "Shows the root-zone temperature of the zone on its page, from its probe.",
      impact: "Off: the zone page does not show it. The history chart shows the probe either way.",
      guidance: "Each zone needs a root-zone temperature probe in Equipment › Setup.",
    },
  },
  {
    key: "zone_day_deltas",
    group: "Zone page",
    label: "Today against yesterday",
    copy: {
      tooltip:
        "Shows up to three chips under the day chart of a zone: VWC against yesterday at this hour, when the zone got to its ramp target, and the water until now.",
      impact:
        "Off: no chips. On: the chips use the day that “Compare with” selects. A chip shows in colour only when the difference is large.",
    },
  },
  {
    key: "show_camera",
    group: "Zone page",
    label: "Room camera",
    copy: {
      tooltip:
        "Shows a still image from the camera of the room on each zone page. The image changes each 30 s.",
      impact: "Off: no image. On: the page reads one image each 30 s while it is open.",
      guidance: "The room must have a camera in Equipment › Setup.",
    },
  },
  {
    key: "manual_hardware_enabled",
    entity: (prefix) => `switch.crop_steering_${prefix}manual_hardware_enabled`,
    group: "Zone page",
    label: "Hardware panel",
    copy: {
      tooltip:
        "Shows a Hardware panel on each zone page: the test shot of the zone, and the valve, pump, main line, lights and tank fill on or off now.",
      impact:
        "Off: no panel. On: an administrator can start a 10 s test shot from the zone page. The controller does the shot with all its safety checks. The panel opens and closes nothing itself.",
      guidance: "Only an administrator can set this to on.",
      caution:
        "CAUTION: Make sure that the drippers are in the substrate or in a container before a test shot. Loose drippers can flood the area.",
    },
  },

  {
    key: "show_equipment_lanes",
    group: "History",
    label: "Equipment lanes",
    copy: {
      tooltip:
        "Shows a row for each mapped device on History › Timeline: the lights, tank fill, pump, main line and each zone valve, on or off through the grow day.",
      impact: "Off: no lanes. On: the timeline reads one grow day of these devices from Home Assistant.",
      guidance: "A pump that ran with no valve open shows as a pump bar with no valve bar under it.",
    },
  },
  {
    key: "show_room_day_lanes",
    group: "History",
    label: "Zone lanes",
    copy: {
      tooltip:
        "Shows a row for each zone on History › Timeline: its phases and its shots through the grow day, on one time axis.",
      impact: "Off: no lanes. On: a zone that is late or early against the others is easy to see.",
    },
  },
  {
    key: "show_dryback_drivers",
    group: "History",
    label: "Dryback drivers",
    copy: {
      tooltip:
        "Adds the History › Dryback drivers page: the overnight dryback rate of each zone against the VPD, temperature, humidity or CO2 of the room, for the last 14 nights.",
      impact: "Off: no page. On: the page reads 14 days of history when you open it.",
      guidance: "The chart shows how two values go together. It does not show a cause.",
    },
  },
  {
    key: "planner_reference_rows",
    group: "Plan",
    label: "Reference rows",
    copy: {
      tooltip:
        "Adds rows under the endpoints of a profile in Plan › Schedule: bands for air temperature, humidity, VPD, CO2, PPFD, DLI and feed pH.",
      impact:
        "The rows drive nothing. The controller does not get them. The room climate on a zone page shows a value in colour when it is outside the band of today.",
    },
  },
  {
    key: "planner_day_curve",
    group: "Plan",
    label: "Day curve in the planner",
    copy: {
      tooltip:
        "Shows the curve and the water of the preview day in Plan › Schedule, read only.",
      impact: "Off: no curve. To change the curve of today with the mouse, use Plan › Targets.",
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
  // The Hardware panel is a switch of its own.
  if (param === "all" || wanted.includes("manual_hardware_enabled"))
    for (const id of Object.keys(states))
      if (/^switch\.crop_steering_[a-z0-9_]*manual_hardware_enabled$/.test(id))
        next[id] = { ...states[id], state: "on" };
  return next;
}
