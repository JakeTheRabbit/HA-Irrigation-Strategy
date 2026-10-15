import { settingWords } from "./setting-words";

/** The controller's own tokens in grower words, for every line it or the brain writes that the page
 * shows: the Timeline, Today's changes, a zone's decisions and the day chart's shots. A setting's
 * key becomes its name on the Irrigation plan, a phase call becomes what it does, and the probe's
 * abbreviations become the reading. Anything else passes through as written. */

/** The answers and calls the controller writes with a phase's token in them. */
const CALLS: ReadonlyArray<readonly [RegExp, string]> = [
  [/\bone[ _]more[ _]top[ _-]?up[ _]then[ _]p3\b/g, "one more top-up, then end the day's watering"],
  [/\benter[ _]p3[ _]now\b/g, "end the day's watering now"],
  [/\bcontinue[ _]p2\b/g, "keep watering through the day"],
  [/\benter[ _]p([0-3])\b/g, "move to P$1"],
];

/** Setting keys longest first, so "p1_target_vwc" wins over any shorter key inside it. */
const KEYS = [
  "p0_maximum_wait_time",
  "p1_target_vwc",
  "p1_initial_shot_size",
  "p1_shot_size_increment",
  "p1_time_between_shots",
  "p1_maximum_shots",
  "p2_vwc_threshold",
  "p2_shot_size",
  "p3_emergency_vwc_threshold",
  "p3_emergency_shot_size",
  "vegetative_dryback_target",
  "generative_dryback_target",
  "dryback_target",
  "field_capacity",
].sort((a, b) => b.length - a.length);
/** A key as the controller writes it, with underscores, or as a log shows it, with spaces; with or
 * without its "zone_N_" in front. */
const KEY = new RegExp(
  `\\b(?:zone[ _]\\d+[ _])?(${KEYS.map((key) => key.replaceAll("_", "[ _]")).join("|")})\\b`,
  "g",
);
/** A phase's rule as the controller's attributes name it ("p2_topup"), and the probe's lower-case
 * abbreviations. Its own sentences ("P1 ramp VWC 25<36") are already words. */
const RULES: ReadonlyArray<readonly [RegExp, string]> = [
  [/\bp1_ramp\b/g, "ramp shot"],
  [/\bp1_done\b/g, "ramp done"],
  [/\bp1_max_shots\b/g, "most ramp shots"],
  [/\bp2_topup\b/g, "maintenance shot"],
  [/\bp2_dilute\b/g, "dilution shot"],
  [/\bp3_emergency\b/g, "rescue shot"],
  [/\bpwec\b/g, "pore EC"],
  [/\bvwc\b/g, "moisture"],
];

export function growerWords(text: string): string {
  let out = text;
  for (const [pattern, words] of CALLS) out = out.replace(pattern, words);
  out = out.replace(KEY, (whole, key: string) => {
    const words = settingWords(key.toLowerCase().replaceAll(" ", "_"));
    if (!words) return whole;
    // Mid-sentence: "Maintenance shot" reads "maintenance shot"; "P3 dryback target" stays.
    return /^[A-Z][a-z]/.test(words.short)
      ? words.short.charAt(0).toLowerCase() + words.short.slice(1)
      : words.short;
  });
  for (const [pattern, words] of RULES) out = out.replace(pattern, words);
  return out;
}
