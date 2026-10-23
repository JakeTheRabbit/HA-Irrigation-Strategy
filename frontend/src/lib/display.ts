import { formatEc, formatTemp, formatVolume, readDisplayUnits } from "./display-units";
import type { SteCopy } from "./ste-copy";
import { clock } from "./time";
import type { EntityState, RoomView, States } from "./types";

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
  /** Units and clock (integration 3.18): display only, storage stays mS/cm, °C and litres. */
  ec_unit: "mS/cm" | "ppm500" | "ppm700";
  temp_unit: "C" | "F";
  /** "auto" follows Home Assistant's unit system. */
  volume_unit: "auto" | "L" | "gal";
  clock: 12 | 24;
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
  ec_unit: "mS/cm",
  temp_unit: "C",
  volume_unit: "auto",
  clock: 24,
};

/** The options that take one of several values (display.py `choices`); the rest are on or off. */
export const DISPLAY_CHOICES: Partial<Record<DisplayKey, readonly (string | number)[]>> = {
  today_zone_layout: ["cards", "table"],
  ec_unit: ["mS/cm", "ppm500", "ppm700"],
  temp_unit: ["C", "F"],
  volume_unit: ["auto", "L", "gal"],
  clock: [12, 24],
};
/** The four unit options: an integration from before 3.18 publishes none of them. */
export const UNIT_KEYS = ["ec_unit", "temp_unit", "volume_unit", "clock"] as const;
export type UnitKey = (typeof UNIT_KEYS)[number];

/** Whether `value` is one `key` takes. */
export function validDisplayValue(key: DisplayKey, value: unknown): boolean {
  const choices = DISPLAY_CHOICES[key];
  return choices ? choices.includes(value as string | number) : typeof value === "boolean";
}

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

/** The rows Settings › Display offers, in page order. A row is listed once its panel exists, and no
 * longer once its panel is gone: `today_zone_layout` (Zones as) stays stored but is not offered, since
 * the room page has no zone table. */
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
    key: "show_climate",
    group: "Zone page",
    label: "Room climate",
    copy: {
      tooltip:
        "Shows the air temperature, humidity, VPD and dew point of the room on each zone page, in grey.",
      impact:
        "Off: the zone page does not show them. The history chart shows the climate either way.",
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
      impact:
        "Off: no lanes. On: the timeline reads one grow day of these devices from Home Assistant.",
      guidance:
        "A pump that ran with no valve open shows as a pump bar with no valve bar under it.",
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
        "Adds rows under the endpoints of a profile in Irrigation › Calendar: bands for air temperature, humidity, VPD, CO2, PPFD, DLI and feed pH.",
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
        "Shows the curve and the water of the preview day in Irrigation › Calendar, read only.",
      impact:
        "Off: no curve. To change the curve of today with the mouse, use Irrigation › Current day.",
    },
  },
];

export interface RoomDisplay {
  /** The room has the store (an integration from before it does not, and nothing can be saved). */
  available: boolean;
  /** The store keeps the units and clock (integration 3.18): the sensor carries all four. */
  units: boolean;
  revision: number;
  options: DisplayOptions;
}

export const displayEntityId = (prefix: string) => `sensor.crop_steering_${prefix}display`;

/** The room's display options from its sensor: each option the sensor does not carry, or carries
 * with a value it does not take, reads as its default. */
export function readDisplay(entity: EntityState | undefined): RoomDisplay {
  const revision = Number(entity?.state);
  const available = !!entity && Number.isInteger(revision) && revision >= 0;
  const options = { ...DISPLAY_DEFAULTS } as Record<DisplayKey, unknown>;
  for (const key of Object.keys(DISPLAY_DEFAULTS) as DisplayKey[]) {
    const value = available ? entity!.attributes[key] : undefined;
    if (validDisplayValue(key, value)) options[key] = value;
  }
  const units = available && UNIT_KEYS.every((key) => key in entity!.attributes);
  return { available, units, revision: available ? revision : 0, options: options as DisplayOptions };
}

/** The unit `key` as stored, "auto" unresolved: the room's option on 3.18, else this browser's
 * choice (`stored`, the JSON under crop-steering.units), else the default. */
/** How Settings › Units saves: in the room's display store (3.18), in this browser (an integration
 * without units), or not at all: offline or still connecting (the room's units are not known yet,
 * and would later override this browser's), or the room's display sensor is unavailable. */
export type UnitMode = "room" | "local" | "offline" | "unavailable";
export function unitMode(entity: EntityState | undefined, connection: string): UnitMode {
  if (connection !== "live" && connection !== "demo") return "offline";
  const display = readDisplay(entity);
  if (entity && !display.available) return "unavailable";
  return display.units ? "room" : "local";
}

export function storedUnit(display: RoomDisplay, stored: string | null, key: UnitKey): string | number {
  if (display.units) return display.options[key];
  const local = readDisplayUnits(undefined, stored);
  const value = { ec_unit: local.ec, temp_unit: local.temp, volume_unit: local.volume, clock: local.clock }[key];
  return key === "clock" ? Number(value) : value;
}

export const roomDisplay = (states: States, prefix: string) =>
  readDisplay(states[displayEntityId(prefix)]);

/** The demo's ?display=a,b (or ?display=all): those options on in every demo room, for a look at
 * each panel without a trip to Settings. */
export function demoDisplay(states: States, param: string | null): States {
  if (!param) return states;
  // Panels only: a unit is a choice, not a panel to turn on.
  const panels = Object.keys(DISPLAY_DEFAULTS).filter((key) => !(UNIT_KEYS as readonly string[]).includes(key));
  const wanted = param === "all" ? panels : param.split(",").filter((key) => panels.includes(key));
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

/** Decimals the reading has (never formatted past them), at most 2. */
const digitsOf = (value: number) =>
  Math.min(2, (String(Number(value.toFixed(6))).split(".")[1] ?? "").length);
const numberOf = (entity: EntityState | undefined) => {
  const value = Number(entity?.state);
  return entity && entity.state !== "" && Number.isFinite(value) ? value : null;
};

/** One live example per unit row of Settings, from the room's own readings through the display
 * store: average EC, a °C or °F sensor of the room, water today, lights off. A row whose reading the
 * room lacks says so and shows the unit on a plain example number. */
export function unitExamples(
  states: States,
  room: RoomView,
): { ec: string; temp: string; volume: string; clock: string } {
  const metric = (key: "ec" | "water") => room.metrics.find((m) => m.key === key)?.value ?? null;
  const ec = metric("ec");
  const water = metric("water");
  // The room's mapped thermometers (Equipment › Setup): zone 1's root zone, else the feed tank.
  const config = states[`sensor.crop_steering_${room.room.prefix}engine_config`]?.attributes ?? {};
  const roots = config.substrate_temperature_sensors as Record<string, unknown> | undefined;
  const thermometer = (
    [
      ["Root zone", roots?.["1"]],
      ["Feed tank", config.tank_temperature_sensor],
    ] as const
  )
    .map(([label, id]) => ({ label, entity: typeof id === "string" ? states[id] : undefined }))
    .find(({ entity }) => ["°C", "°F"].includes(String(entity?.attributes.unit_of_measurement)) && numberOf(entity) !== null);
  const reading = numberOf(thermometer?.entity);
  // A probe on US units reads in °F: stored and formatted as °C, kept to a tenth at least.
  const fahrenheit = thermometer?.entity?.attributes.unit_of_measurement === "°F";
  const temp = reading !== null && fahrenheit ? ((reading - 32) * 5) / 9 : reading;
  const tempDigits = reading === null ? 0 : fahrenheit ? Math.max(1, digitsOf(reading)) : digitsOf(reading);
  const off = numberOf(states[`number.crop_steering_${room.room.prefix}lights_off_hour`]);
  return {
    ec: ec !== null ? `Average EC ${formatEc(ec, digitsOf(ec))}` : `No EC reading yet, for example ${formatEc(2, 1)}`,
    temp:
      thermometer && temp !== null
        ? `${thermometer.label} ${formatTemp(temp, tempDigits)}`
        : `No temperature reading yet, for example ${formatTemp(21, 1)}`,
    volume:
      water !== null
        ? `${room.room.name} water today ${formatVolume(water, digitsOf(water))}`
        : `No water reading yet, for example ${formatVolume(10, 1)}`,
    // A whole hour on the room's clock; UTC only carries the wall time to the formatter.
    clock:
      off !== null && Number.isInteger(off) && off >= 0 && off <= 23
        ? `Lights off ${clock(Date.UTC(2000, 0, 1, off), "UTC")}`
        : `No lights-off time yet, for example ${clock(Date.UTC(2000, 0, 1, 18), "UTC")}`,
  };
}
