/**
 * What each irrigation setting is called and what it does, for every page that shows one: the
 * Irrigation plan, the Schedule, the planning curve and the sensor charts. One table, so a
 * setting never has two names.
 *
 * Names follow the Athena Handbook (Metric, V20) where it has a term for the thing. Every help
 * line says what the engine does (crop-steering-engine `decide()` and the controller's reads of
 * these numbers), not what the setting was meant for: change a line only together with that code.
 */

/** Which way a level acts, shown as a small tag before its name. */
export type SettingTag = "fills" | "waters" | "dries" | "rescues" | "ceiling" | "time";
export const TAG_TEXT: Record<SettingTag, string> = {
  fills: "fills up to",
  waters: "waters below",
  dries: "dries by",
  rescues: "rescues below",
  ceiling: "ceiling",
  time: "time limit",
};

export interface SettingWords {
  label: string;
  /** The same name where a full label does not fit: chart lines and sentences. */
  short: string;
  /** One line under the field. */
  help: string;
  tag?: SettingTag;
}

/** The phase groups, in order; the Irrigation plan files the EC targets under them too. */
export const PHASE_GROUPS = [
  "P0 · Additional dryback",
  "P1 · Ramp-up",
  "P2 · Maintenance",
  "P3 · Overnight dryback",
] as const;
export const GROUP_HELP: Record<string, string> = {
  [PHASE_GROUPS[0]]:
    "Transpiration before irrigation: the plants start drinking before the first shot.",
  [PHASE_GROUPS[1]]: "The first shots after lights-on: small, spaced out, up to the peak target.",
  [PHASE_GROUPS[2]]:
    "Maintenance shots through the day, whenever the substrate dries below the trigger.",
  [PHASE_GROUPS[3]]: "The substrate dries back until the first shot of the next day.",
  Substrate: "What this substrate can hold.",
  "Hardware sizing": "What turns a shot’s percentage into litres and seconds.",
  Schedule: "When the lights come on and go off. A grow-day runs from one lights-on to the next.",
  Safety: "Limits that hold, shorten or add watering.",
};

const OF_SUBSTRATE = "as a percentage of each plant’s substrate volume";

const WORDS: Record<string, SettingWords> = {
  p0_maximum_wait_time: {
    label: "Latest first shot",
    short: "Latest first shot",
    tag: "time",
    help: "The ramp starts this long after lights-on at the latest; sooner if moisture falls to the maintenance trigger.",
  },
  p1_target_vwc: {
    label: "Peak VWC target",
    short: "Peak target",
    tag: "fills",
    help: "The morning ramp waters up to this: the top of the day. It is capped at full saturation.",
  },
  p1_initial_shot_size: {
    label: "First P1 shot",
    short: "First P1 shot",
    help: `The ramp’s first shot, ${OF_SUBSTRATE}.`,
  },
  p1_shot_size_increment: {
    label: "Each P1 shot adds",
    short: "Each P1 shot adds",
    help: "Every ramp shot is this much bigger than the one before.",
  },
  p1_time_between_shots: {
    label: "Time between P1 shots",
    short: "Time between P1 shots",
    help: "Lets each ramp shot soak in before the next. Athena: 15–30 minutes.",
  },
  p1_maximum_shots: {
    label: "Most P1 shots",
    short: "Most P1 shots",
    help: "The ramp ends after this many shots, even below the peak VWC target.",
  },
  p2_vwc_threshold: {
    label: "Maintenance shot when below",
    short: "Maintenance trigger",
    tag: "waters",
    help: "Through the day, a maintenance shot fires whenever moisture reads below this. The peak VWC target down to here is the daytime dryback.",
  },
  p2_shot_size: {
    label: "Maintenance shot size",
    short: "Maintenance shot",
    help: `Each maintenance shot, ${OF_SUBSTRATE}.`,
  },
  p3_emergency_vwc_threshold: {
    label: "Rescue shot when below",
    short: "Rescue level",
    tag: "rescues",
    help: "In P3, a rescue shot fires whenever moisture reads below this. Keep it above the wilting point.",
  },
  p3_emergency_shot_size: {
    label: "Rescue shot size",
    short: "Rescue shot",
    help: `Each rescue shot, ${OF_SUBSTRATE}.`,
  },
  field_capacity: {
    label: "Full saturation (most it holds)",
    short: "Full saturation",
    tag: "ceiling",
    help: "The wettest this substrate gets; the peak VWC target is capped here. It is not Athena’s field capacity, which is lower.",
  },
  max_daily_volume: {
    label: "Daily water limit",
    short: "Daily water limit",
    help: "The most water a zone gets in one grow-day. Routine shots stop at it; ramp, rescue and watchdog shots and high-EC flushes can go past it.",
  },
  maximum_ec: {
    label: "Maximum substrate EC",
    short: "Maximum EC",
    help: "At this substrate EC a flush fires in any phase (in P2, from 1 mS/cm below it), when the feed is weaker than the substrate.",
  },
  watchdog_hours: {
    label: "Watchdog interval",
    short: "Watchdog interval",
    help: "After P0, with lights on, a zone below its maintenance trigger that has had no shot for this long gets one, even past the daily limit. 0 turns it off.",
  },
  min_floor_drown_ceiling: {
    label: "Daily minimum stops at",
    short: "Daily minimum stops at",
    help: "Shots that make up a zone’s daily minimum water only fire while moisture reads below this.",
  },
  irrigation_ec_min: {
    label: "Feed EC, lowest",
    short: "Feed EC, lowest",
    help: "Shots wait while the feed (tank) EC reads below this; 0 means no lower limit. It needs a feed EC sensor set in the controller app.",
  },
  irrigation_ec_max: {
    label: "Feed EC, highest",
    short: "Feed EC, highest",
    help: "Shots wait while the feed (tank) EC reads above this; 0 means no upper limit. It needs a feed EC sensor set in the controller app.",
  },
  irrigation_ph_min: {
    label: "Feed pH, lowest",
    short: "Feed pH, lowest",
    help: "Shots wait while the feed (tank) pH reads below this; 0 means no lower limit. It needs a feed pH sensor set in the controller app.",
  },
  irrigation_ph_max: {
    label: "Feed pH, highest",
    short: "Feed pH, highest",
    help: "Shots wait while the feed (tank) pH reads above this; 0 means no upper limit. It needs a feed pH sensor set in the controller app.",
  },
  max_shot_duration: {
    label: "Longest shot",
    short: "Longest shot",
    help: "The longest any valve in this room stays open for one shot. A longer planned shot is cut short and delivers less.",
  },
  substrate_volume: {
    label: "Substrate per plant",
    short: "Substrate per plant",
    help: "Litres of substrate in each plant’s pot or block. Shot sizes are a percentage of it.",
  },
  plant_count: {
    label: "Plants",
    short: "Plants",
    help: "Plants in this zone. A shot’s water is its size times the substrate per plant, times this.",
  },
  drippers_per_plant: {
    label: "Drippers per plant",
    short: "Drippers per plant",
    help: "With the dripper flow, this sets how long a shot runs: its water divided by the zone’s total dripper flow.",
  },
  dripper_flow_rate: {
    label: "Dripper flow",
    short: "Dripper flow",
    help: "Litres per hour from each dripper.",
  },
  lights_on_hour: {
    label: "Lights on",
    short: "Lights on",
    help: "The hour the lights come on, on the controller’s clock. The grow-day and P0 start here.",
  },
  lights_off_hour: {
    label: "Lights off",
    short: "Lights off",
    help: "The hour the lights go off. Any zone not yet in P3 moves to P3.",
  },
};

const EC_WORDS: Record<string, SettingWords> = {
  "0": {
    label: "Substrate EC target, P0",
    short: "P0 EC target",
    help: "In P0, a flush fires when substrate EC is more than 2.5 times this.",
  },
  "1": {
    label: "Substrate EC target, P1",
    short: "P1 EC target",
    help: "At the peak VWC target, the ramp ends only once substrate EC is no more than 15% above this (or after the most P1 shots).",
  },
  "2": {
    label: "Substrate EC target, P2",
    short: "P2 EC target",
    help: "Maintenance shots are sized against this; more than 20% above it, a dilution shot runs.",
  },
};

const DRYBACK_WORDS: SettingWords = {
  label: "P3 dryback target",
  short: "P3 dryback target",
  tag: "dries",
  help: "How far to dry back overnight, relative to the day’s peak: a 30% dryback from a 60% peak ends at 42%.",
};

const MODE: Record<string, string> = {
  veg: "vegetative",
  vegetative: "vegetative",
  gen: "generative",
  generative: "generative",
};
const withMode = (words: SettingWords, mode: string | undefined): SettingWords =>
  mode ? { ...words, label: `${words.label} (${MODE[mode]})` } : words;

/** Words for a setting key: an entity's parameter ("zone_1_" already removed), or the Schedule's
 * mode-resolved key ("dryback_target", "ec_target_p1"). Undefined for a key nobody has named. */
export function settingWords(param: string): SettingWords | undefined {
  const ec = param.match(/^ec_target_(?:(veg|gen)_)?p([012])$/);
  if (ec) return withMode(EC_WORDS[ec[2]], ec[1]);
  const dryback = param.match(/^(?:(vegetative|generative)_)?dryback_target$/);
  if (dryback) return withMode(DRYBACK_WORDS, dryback[1]);
  return WORDS[param === "maximum_shot_duration" ? "max_shot_duration" : param];
}
