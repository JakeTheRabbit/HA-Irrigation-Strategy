import type { EntityState, States } from "./types";
import rulesFile from "./generated/rules.json";

/** Read-only sensing the controller publishes (addons/f2_control/f2_control/sensing.py, shot_audit.py,
 * gate_report.py) and the plant-stress numbers worked out here from the room's leaf and air sensors. */

const num = (value: unknown): number | null => {
  const n = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return value !== null && value !== "" && Number.isFinite(n) ? n : null;
};
const isOn = (state: EntityState | undefined) => state?.state === "on";

// ------------------------------------------------------------------ the gate list
export interface Gate {
  key: string;
  label: string;
  state: "pass" | "hold";
  detail: string;
}
/** The zone's pre-shot gates, in the controller's order, from its waiting_for sensor; null when the
 * controller does not publish them (one from before the list). */
export function zoneGates(states: States, prefix: string, zone: number): Gate[] | null {
  const raw = states[`sensor.crop_steering_${prefix}zone_${zone}_waiting_for_app`]?.attributes.gates;
  if (!Array.isArray(raw)) return null;
  return raw.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const g = item as Record<string, unknown>;
    if (typeof g.key !== "string" || typeof g.label !== "string") return [];
    return [
      {
        key: g.key,
        label: g.label,
        state: g.state === "hold" ? "hold" : "pass",
        detail: typeof g.detail === "string" ? g.detail : "",
      },
    ];
  });
}

// ------------------------------------------------------------------ the shot table
export interface ShotRow {
  start: string;
  kind: string;
  litres: number | null;
  expected: number | null;
  peak: number | null;
  retained: number | null;
  ecMove: number | null;
  verdict: string;
  aiVerdict: string | null;
}
export const VERDICT_WORDS: Record<string, string> = {
  landed: "Landed",
  small: "Small rise",
  flat_ec_moved: "Flat, EC moved",
  no_sign: "No sign",
  settling: "Settling",
  unknown: "No reading",
};
export type ShotCheck = "off" | "table" | "table_and_alert";
export function shotCheck(states: States, prefix: string): ShotCheck {
  const mode = states[`select.crop_steering_${prefix}shot_check`]?.state;
  return mode === "table" || mode === "table_and_alert" ? mode : "off";
}
/** The zone's last shots, newest first; null when the room's shot check is off or the controller does not
 * publish the table. */
export function shotLog(states: States, prefix: string, zone: number): ShotRow[] | null {
  if (shotCheck(states, prefix) === "off") return null;
  const raw = states[`sensor.crop_steering_${prefix}zone_${zone}_shot_log_app`]?.attributes.shots;
  if (!Array.isArray(raw)) return null;
  return raw.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const r = item as Record<string, unknown>;
    if (typeof r.start !== "string") return [];
    return [
      {
        start: r.start,
        kind: String(r.kind ?? "shot"),
        litres: num(r.litres),
        expected: num(r.expected_rise_pts),
        peak: num(r.peak_rise_pts),
        retained: num(r.retained_rise_pts),
        ecMove: num(r.ec_move_mscm),
        verdict: String(r.verdict ?? "unknown"),
        aiVerdict: typeof r.ai_verdict === "string" ? r.ai_verdict : null,
      },
    ];
  });
}

// ------------------------------------------------------------------ water vs VPD
export interface WaterResponse {
  slope: number | null;
  r: number | null;
  days: number;
  words: string;
}
/** A zone's dryback-vs-VPD answer; null while the room's Water vs VPD switch is off or nothing is published. */
export function waterResponse(states: States, prefix: string, zone: number): WaterResponse | null {
  if (!isOn(states[`switch.crop_steering_${prefix}water_vpd_insight`])) return null;
  const s = states[`sensor.crop_steering_${prefix}zone_${zone}_water_response_app`];
  if (!s) return null;
  return {
    slope: num(s.state),
    r: num(s.attributes.r),
    days: num(s.attributes.n_days) ?? 0,
    words: typeof s.attributes.words === "string" ? s.attributes.words : "",
  };
}

// ------------------------------------------------------------------ plant stress
/** Saturation vapour pressure in kPa at `c` deg C (Tetens). */
export const svp = (c: number) => 0.6108 * Math.exp((17.27 * c) / (c + 237.3));
export const toC = (value: number, unit: unknown) =>
  unit === "°F" ? ((value - 32) * 5) / 9 : unit === "K" ? value - 273.15 : value;

export interface Stress {
  leaf: number;
  air: number;
  delta: number;
  leafVpd: number | null;
  /** 0 (transpiring freely) .. 1 (stopped), only with the grower's own baselines (upper above lower). */
  cwsi: number | null;
}
export function stress(
  leafC: number,
  airC: number,
  humidity: number | null,
  lower: number | null,
  upper: number | null,
): Stress {
  const delta = leafC - airC;
  const leafVpd =
    humidity !== null && humidity >= 0 && humidity <= 100
      ? svp(leafC) - (humidity / 100) * svp(airC)
      : null;
  const cwsi =
    lower !== null && upper !== null && upper > lower
      ? Math.max(0, Math.min(1, (delta - lower) / (upper - lower)))
      : null;
  return { leaf: leafC, air: airC, delta, leafVpd, cwsi };
}
/** The leaf sensor a zone reads (its own, else the room's), the air temperature and humidity sensors, and
 * whether the card is switched on; null when the card is off or no leaf sensor is mapped. */
export function stressSources(
  states: States,
  descriptor: Record<string, unknown>,
  prefix: string,
  zone: number | null,
): { leaf: string; air: string | null; humidity: string | null } | null {
  if (!isOn(states[`switch.crop_steering_${prefix}plant_stress_card`])) return null;
  const own = descriptor.zone_leaf_sensors;
  const zoneLeaf =
    zone !== null && own && typeof own === "object"
      ? (own as Record<string, unknown>)[String(zone)]
      : undefined;
  const leaf =
    typeof zoneLeaf === "string" && zoneLeaf
      ? zoneLeaf
      : typeof descriptor.leaf_temperature_sensor === "string"
        ? descriptor.leaf_temperature_sensor
        : "";
  if (!leaf) return null;
  const pick = (key: string) =>
    typeof descriptor[key] === "string" && descriptor[key] ? (descriptor[key] as string) : null;
  return { leaf, air: pick("temperature_sensor"), humidity: pick("humidity_sensor") };
}
export function stressNow(
  states: States,
  prefix: string,
  sources: { leaf: string; air: string | null; humidity: string | null },
): Stress | null {
  const read = (id: string | null) => {
    const s = id ? states[id] : undefined;
    const value = num(s?.state);
    return value === null ? null : toC(value, s?.attributes.unit_of_measurement);
  };
  const leaf = read(sources.leaf),
    air = read(sources.air);
  if (leaf === null || air === null) return null;
  const humidity = sources.humidity ? num(states[sources.humidity]?.state) : null;
  const base = (key: string) => {
    const v = num(states[`number.crop_steering_${prefix}${key}`]?.state);
    return v === 0 ? null : v;
  };
  return stress(leaf, air, humidity, base("cwsi_lower_baseline"), base("cwsi_upper_baseline"));
}
/** Leaf minus air over time: each leaf reading against the air reading in force at that moment. */
export function deltaSeries(
  leaf: { time: number; value: number }[],
  air: { time: number; value: number }[],
): { time: number; value: number }[] {
  const out: { time: number; value: number }[] = [];
  let i = 0;
  for (const point of leaf) {
    while (i + 1 < air.length && air[i + 1].time <= point.time) i++;
    if (air.length && air[i].time <= point.time) out.push({ time: point.time, value: point.value - air[i].value });
  }
  return out;
}

// ------------------------------------------------------------------ the rules
export interface RuleParam {
  settings: string[];
  bounds: [number, number] | null;
  note: string;
}
export interface Rule {
  id: string;
  topic: string;
  priority: number;
  text: string;
  evidence: string;
  params: string[];
}
export const RULES = rulesFile as unknown as {
  doctrine_version: string;
  rules: Rule[];
  params: Record<string, RuleParam>;
};
export interface LiveValue {
  setting: string;
  /** Zone id, or null for the room's own setting. */
  zone: number | null;
  value: number | boolean;
  /** Outside the engine's bounds for the parameter: worth a second look. */
  outside: boolean;
}
/** A setting's live values in the room: each zone's own number where it has one, else the room's. */
export function liveValues(
  states: States,
  prefix: string,
  zones: number[],
  setting: string,
  bounds: [number, number] | null,
): LiveValue[] {
  const out: LiveValue[] = [];
  const check = (value: number | boolean) =>
    typeof value === "number" && bounds !== null && (value < bounds[0] || value > bounds[1]);
  const perZone = zones.flatMap((zone) => {
    const v = num(states[`number.crop_steering_${prefix}zone_${zone}_${setting}`]?.state);
    return v === null ? [] : [{ setting, zone, value: v, outside: check(v) }];
  });
  if (perZone.length) return perZone;
  const room = num(states[`number.crop_steering_${prefix}${setting}`]?.state);
  if (room !== null) out.push({ setting, zone: null, value: room, outside: check(room) });
  const sw = states[`switch.crop_steering_${prefix}${setting}`];
  if (sw && (sw.state === "on" || sw.state === "off"))
    out.push({ setting, zone: null, value: sw.state === "on", outside: false });
  return out;
}
/** The rules matching `query` (id, topic or words), each with the live values of the settings it names. */
export function ruleRows(states: States, prefix: string, zones: number[], query: string) {
  const q = query.trim().toLowerCase();
  return RULES.rules
    .filter(
      (rule) =>
        !q ||
        rule.id.toLowerCase().includes(q) ||
        rule.topic.toLowerCase().includes(q) ||
        rule.text.toLowerCase().includes(q),
    )
    .map((rule) => ({
      rule,
      values: rule.params.flatMap((param) => {
        const p = RULES.params[param];
        return p ? p.settings.flatMap((s) => liveValues(states, prefix, zones, s, p.bounds)) : [];
      }),
    }));
}
/** Settings whose live value is outside the engine's bounds for their parameter: the "double-check these"
 * list. Bounds only, never doctrine moisture bands (a probe can read far from them). */
export function doubleCheck(states: States, prefix: string, zones: number[]): LiveValue[] {
  const seen = new Set<string>();
  return Object.values(RULES.params).flatMap((p) =>
    p.settings.flatMap((setting) => {
      if (seen.has(setting)) return [];
      seen.add(setting);
      return liveValues(states, prefix, zones, setting, p.bounds).filter((v) => v.outside);
    }),
  );
}
