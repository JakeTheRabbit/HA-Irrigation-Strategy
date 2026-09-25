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
  /** The "?" beside the field. */
  detail?: SettingDetail;
}

/** What the "?" beside an irrigation setting says, in the order shown. */
export interface SettingDetail {
  what: string;
  when: string;
  affects?: string;
  stacking?: string;
  auto?: string;
  athena?: string;
}
export const DETAIL_HEADINGS: ReadonlyArray<readonly [keyof SettingDetail, string]> = [
  ["what", "What it is"],
  ["when", "When it acts"],
  ["affects", "What it affects"],
  ["stacking", "With EC stacking on"],
  ["auto", "With Auto setpoints on"],
  ["athena", "Athena Handbook"],
];

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

// The "?" text. Quotes are the handbook's own words, with its printed page; the rest is what the
// engine does, from decide() and the controller's parameter reads.
const AUTO = "The controller adjusts this zone’s value itself. Auto setpoints is off by default.";
const EC_STAGES =
  "Substrate EC targets by growth stage: veg 3–5, flower stretch 4–10, bulk 3.5–6, finish 3–4 (p. 40).";
const DETAILS: Record<string, SettingDetail> = {
  p0_maximum_wait_time: {
    what: "How long after lights-on the first shot can wait: Athena’s “transpiration before irrigation”.",
    when: "P0 ends and the ramp starts at the first of: this long after lights-on; moisture at or below the maintenance trigger; moisture down by the P3 dryback target from its highest reading since lights-on. The ramp’s first shot then fires straight away, unless moisture is still at the peak VWC target.",
    athena:
      "Additional dryback is “the decrease in VWC% that occurs during P3, after the lights turn on and before the first irrigation event of the day” (p. 33): 1–5%, first shot 30 minutes to 2 hours after lights-on (p. 39). The P1 page says 1–2 hours (p. 36).",
  },
  p1_target_vwc: {
    what: "The moisture the morning ramp brings the substrate up to: the top of the day’s range. Athena calls it the Peak VWC% Target.",
    when: "In P1, a ramp shot fires while moisture is below it (or below full saturation, if that is lower) and the time between P1 shots has passed. P1 hands over to P2 once moisture has reached it, the P1 minimum shots have fired (3 by default, set in Home Assistant) and substrate EC is no more than 15% above the P1 target; or after the most P1 shots.",
    affects:
      "Where the day peaks, which the P3 dryback target is measured from, and how much runoff the ramp makes. The maintenance trigger is always kept at least 1 point below it.",
    auto: AUTO,
    athena:
      "“The goal for maximum VWC% established by the last P1 event and maintained throughout the P2 phase” (p. 33). Set between field capacity and full saturation it forces runoff (vegetative); at or below field capacity it restricts runoff (generative) (p. 40).",
  },
  p1_initial_shot_size: {
    what: `The size of the ramp’s first shot, ${OF_SUBSTRATE}.`,
    when: "The first shot of P1. Each later ramp shot adds “Each P1 shot adds” to the one before, until the most P1 shots.",
    affects:
      "Ramp shots are sized by substrate EC against the P1 target: up to twice this while EC is well above it, as little as half while it is well below.",
    athena:
      "2–6% shots, 15–30 minutes apart, saturate slowly and avoid channelling (p. 36). A 1% shot of a 4 L pot is 40 mL (p. 40).",
  },
  p1_shot_size_increment: {
    what: `How much bigger each ramp shot is than the one before, ${OF_SUBSTRATE}.`,
    when: "Every P1 shot after the first: the third shot, for example, is the first P1 shot plus twice this.",
  },
  p1_time_between_shots: {
    what: "The wait between ramp shots.",
    when: "A ramp shot fires only once this long has passed since the last shot, so each one can soak in.",
    athena:
      "“2%-6% shots, spaced 15-30 minutes apart allows the substrate to gradually build up to target VWC%” (p. 36).",
  },
  p1_maximum_shots: {
    what: "The most shots the ramp fires.",
    when: "After this many ramp shots P1 hands over to P2, wherever moisture is. P2 then waters whenever moisture reads below the maintenance trigger.",
  },
  p2_vwc_threshold: {
    what: "The level that triggers a daytime maintenance shot. The peak VWC target minus this is how far the substrate dries back during the day.",
    when: "Each time the controller checks in P2 (every minute by default), from the end of the ramp until P3: whenever moisture reads below it, a maintenance shot fires. It is a level, not a crossing: moisture does not need to have been above it first, and reading exactly the value does not fire. There is no minimum wait between maintenance shots; the daily water limit still applies.",
    affects:
      "How often maintenance shots fire, runoff and substrate EC. In P0, reaching it ends the wait and starts the ramp. After P0, with lights on, the watchdog waters a zone below it that has had no shot for the watchdog interval. It is always kept at least 1 point below the peak VWC target and 3 points above the rescue level, whatever is entered.",
    stacking:
      "Moved 1 point down while substrate EC is under 90% of the P2 target (a bigger dryback, less runoff) and 1 point up while it is over 110%, checked every 30 minutes. The PID option can move it up to 20%.",
    auto: AUTO,
    athena:
      "Athena names the maintenance shots, not this level. P2 “is used to maintain a desired VWC% throughout the lights on period” (p. 37), and “as plants grow and the rate of dryback increases it is now necessary to add P2 events to keep the substrate from drying back too much” (p. 38). Here, that means raising this level.",
  },
  p2_shot_size: {
    what: `The size of each maintenance shot, ${OF_SUBSTRATE}.`,
    when: "Every maintenance shot. Watchdog and daily-minimum shots use it as it is; dilution and high-EC flushes are 1.5 times it or more.",
    affects:
      "Maintenance shots are sized by substrate EC against the P2 target, from half to twice this. Bigger shots make more runoff and lower substrate EC.",
    auto: "With the optional judge set up, the controller nudges it at most one step a day, within 1–4%. Auto setpoints is off by default.",
    athena:
      "“Decrease Substrate EC: Increase shot size”; “Increase Substrate EC: Decrease shot size” (p. 38).",
  },
  p3_emergency_vwc_threshold: {
    what: "The overnight safety level. It is not an Athena setting.",
    when: "Each time the controller checks in P3, a rescue shot fires if moisture reads below it. The daily water limit does not hold rescue shots.",
    affects:
      "It can cut the P3 dryback short: if the P3 dryback target ends below this level, a rescue shot fires before the substrate gets there. The maintenance trigger is always kept at least 3 points above it.",
    auto: AUTO,
    athena:
      "“Caution: make sure to monitor the drybacks in larger plants to avoid drying back past wilting point” (p. 41). Set this above the wilting point.",
  },
  p3_emergency_shot_size: {
    what: `The size of each rescue shot, ${OF_SUBSTRATE}.`,
    when: "Every P3 rescue shot. The daily water limit does not hold them.",
  },
  field_capacity: {
    what: "The wettest the substrate can be: the ceiling for the peak VWC target.",
    when: "The ramp stops at the lower of this and the peak VWC target. EC flushes and dilution shots only run while moisture is more than 2 points below it. The zone’s safety status reports approaching saturation within 5 points of it, and over-saturated at or above it.",
    auto: AUTO,
    athena:
      "Full saturation: “a substrate can no longer hold anymore water and peak VWC% can no longer increase” (p. 33), and a target above it “is a target that is impossible to reach” (p. 40). That is how this setting behaves. Field capacity, “maximum VWC% of a substrate prior to runoff” (p. 33), is lower: enter that here and a vegetative peak target above it (p. 40) is capped and never reached.",
  },
};
const EC_DETAILS: Record<string, SettingDetail> = {
  "0": {
    what: "The substrate (pore water) EC reference for P0.",
    when: "In P0, a 10% flush fires when substrate EC is more than 2.5 times this, the feed is weaker than the substrate and moisture is more than 2 points below full saturation.",
    athena: EC_STAGES,
  },
  "1": {
    what: "The substrate (pore water) EC the ramp checks before it hands over.",
    when: "At the peak VWC target, P1 ends only once substrate EC is no more than 15% above this. Until then, while the feed is weaker than the substrate and there is room below full saturation, the ramp keeps shooting at the ceiling to flush, up to the most P1 shots.",
    affects:
      "Ramp shots are sized 1.2×, 1.5× or 2× while EC is above this (by up to 20%, up to 50%, or more), and 0.7× or 0.5× while it is under 80% or 50% of it.",
    auto: "After a ramp levels off, the controller may raise this (never above the P2 target) so a finished ramp can hand over. Auto setpoints is off by default.",
    athena: EC_STAGES,
  },
  "2": {
    what: "The substrate (pore water) EC the day is steered toward.",
    when: "Maintenance shots are sized against it, from half to twice the maintenance shot size. More than 20% above it, a dilution shot of 1.5 times the maintenance shot runs, if the feed is weaker than the substrate and there is room below full saturation.",
    stacking: "The maintenance trigger moves to steer substrate EC toward it.",
    athena: EC_STAGES,
  },
};
const DRYBACK_DETAIL: SettingDetail = {
  what: "How far the substrate should dry back overnight, as a percentage of the day’s peak: a relative change. A 30% dryback from a 65% peak ends at 45.5%. The zone’s steering mode picks the vegetative or generative one.",
  when: "Overnight nothing waters toward it: the substrate simply dries. It acts in two places. In the last 3 hours before lights-off, maintenance shots stop early if drying this far by lights-on needs the rest of the night (and no more than 12 hours). After lights-on, P0 also ends once moisture drops this much below its highest reading since lights-on; with P3-sized values that rarely comes first.",
  affects: "When P2 ends, and so substrate EC: a bigger dryback raises it.",
  athena:
    "P3 dryback targets: vegetative 30–40% (less stress), generative 40–50% (more stress), “based on a relative change” (p. 39). By growth stage, the veg stage dries back 50% the first time, then 25% (p. 40). “The grower can control the amount of dryback by adding or subtracting P2 shots at the end of the day” (p. 37): stopping maintenance shots early is how the controller does that.",
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
  if (ec) return withMode({ ...EC_WORDS[ec[2]], detail: EC_DETAILS[ec[2]] }, ec[1]);
  const dryback = param.match(/^(?:(vegetative|generative)_)?dryback_target$/);
  if (dryback) return withMode({ ...DRYBACK_WORDS, detail: DRYBACK_DETAIL }, dryback[1]);
  const key = param === "maximum_shot_duration" ? "max_shot_duration" : param;
  return WORDS[key] && { ...WORDS[key], ...(DETAILS[key] ? { detail: DETAILS[key] } : {}) };
}
