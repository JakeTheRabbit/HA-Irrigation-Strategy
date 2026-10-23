import type { PresetMissing, PresetResult, PresetTarget, StoredPreset } from "../parity-types";
import type { States } from "../types";
import { demoId } from "./journal";
import { journalDemoTargetWrite } from "./targets";
import { copyDemoTimers, demoTimerShapes } from "./timers";

/** The demo's presets and copy (I4), kept as the integration keeps them (presets.py, site_api.py):
 * one site-wide list with a revision, a save that captures the source's live values by section,
 * and preset_apply / copy_config answering `{diff, missing, applied?}` with a read-back of each write.
 * Each number write is journalled as a manual base `target.changed` and a timers write as a timers
 * save, so `history_revert` puts either back.
 *
 * The demo rooms have no room-level copies of the zone settings, so a room's own value of a zone
 * setting is its zone 1's. Room A also has a dilution-shot ratio that no page shows; Room B, set up
 * before dilution shots, has no entity for it, so a copy from Room A to Room B lists it as not
 * copied. Room B has no timer programs, so a copy from Room B leaves Room A's programs and the
 * apply is refused for that one row (`guard_refused`, the other writes stand). */

const MODE_KEYS = ["vegetative_dryback_target", "generative_dryback_target", ...[0, 1, 2].flatMap((p) => [`ec_target_veg_p${p}`, `ec_target_gen_p${p}`])];
const SECTIONS: Record<string, readonly string[]> = {
  targets: [
    ...MODE_KEYS,
    "p1_target_vwc",
    "p2_vwc_threshold",
    "p2_shot_size",
    "p1_initial_shot_size",
    "p3_emergency_vwc_threshold",
    "p3_emergency_shot_size",
    "p1_shot_size_increment",
    "p1_maximum_shots",
    "p1_time_between_shots",
    "p0_maximum_wait_time",
    "max_daily_volume",
    "field_capacity",
    "maximum_ec",
    "watchdog_hours",
    "p2_mode",
  ],
  phase_timing: [
    "p0_minimum_wait",
    "p0_dryback_drop_percent",
    "p0_additional_dryback",
    "p1_minimum_shots",
    "p1_rise_pts",
    "p1_maximum_extra_shots",
    "p2_time_between_shots",
    "p2_timed_interval_min",
    "p2_timed_shot_size",
    "p2_timed_first_hours",
    "p2_end_hours_before_off",
    "p3_time_between_shots",
    "ec_min_interval",
    "ec_flush_target",
    "p2_dilute_ratio",
  ],
  water_limits: ["min_daily_ml_per_plant", "max_shot_duration"],
  timers: ["timers", "timer"],
};
const SCOPES: Record<string, string[]> = { targets: ["targets"], timers: ["timers"], all: Object.keys(SECTIONS) };
const NO_TIMER: Record<string, string> = { timer: "source zone has no timer program", timers: "source room has no timer programs" };
/** Settings a room has outside the demo's states (see above). */
const OFF_STATES: Record<string, Record<string, number>> = { "room:": { p2_dilute_ratio: 0.5 } };

type Values = Record<string, unknown>;
type Wanted = Record<string, Values>;
const prefixOf = (roomId: string) => roomId.replace(/^room:/, "");
const known = (states: States, roomId: string) => roomId === "room:" || Object.keys(states).some((id) => id.startsWith(`number.crop_steering_${prefixOf(roomId)}`));

/** The number entity a target's key reads and writes, or null where it has none. */
function entityOf(states: States, t: PresetTarget, key: string): string | null {
  const p = prefixOf(t.room_id);
  const ids =
    t.zone === undefined
      ? [`number.crop_steering_${p}${key}`, `number.crop_steering_${p}zone_1_${key}`]
      : [`number.crop_steering_${p}zone_${t.zone}_${key}`];
  return ids.find((id) => states[id]) ?? null;
}
const numberIn = (states: States, id: string) => {
  const text = states[id]?.state ?? "";
  const value = Number(text);
  return text.trim() && Number.isFinite(value) ? value : null;
};

/** {key: value} of every setting the target has a reading of, and the keys it has but cannot read. */
function read(states: States, t: PresetTarget): { values: Values; unread: string[] } {
  const values: Values = {},
    unread: string[] = [];
  for (const section of ["targets", "phase_timing", "water_limits"])
    for (const key of SECTIONS[section]) {
      const id = entityOf(states, t, key);
      if (!id) continue;
      const value = numberIn(states, id);
      if (value === null) unread.push(key);
      else values[key] = value;
    }
  if (t.zone === undefined) Object.assign(values, OFF_STATES[t.room_id] ?? {});
  const shapes = demoTimerShapes(t.room_id);
  if (shapes === null) unread.push(t.zone === undefined ? "timers" : "timer");
  else if (t.zone === undefined) values.timers = shapes;
  else {
    const program = shapes.find((p) => p.active !== false && Array.isArray(p.zones) && p.zones.includes(t.zone));
    values.timer = program ? (({ zones: _z, ...rest }) => rest)(program) : null;
  }
  return { values, unread };
}
const capture = (values: Values, sections: string[]): Wanted =>
  Object.fromEntries(sections.map((s) => [s, Object.fromEntries(SECTIONS[s].filter((k) => k in values).map((k) => [k, structuredClone(values[k])]))]));
const same = (a: unknown, b: unknown) =>
  typeof a === "number" && typeof b === "number" ? Math.abs(a - b) <= 1e-9 : JSON.stringify(a) === JSON.stringify(b);
const ref = (target: unknown): PresetTarget => {
  const t = (target ?? {}) as Record<string, unknown>;
  if (typeof t.room_id !== "string" || !t.room_id.startsWith("room:")) throw new Error("Each target needs a room_id such as room:f2_");
  if (t.zone === undefined || t.zone === null) return { room_id: t.room_id };
  if (!Number.isInteger(t.zone) || (t.zone as number) < 1) throw new Error("zone must be a whole number from 1");
  return { room_id: t.room_id, zone: t.zone as number };
};

/** The seeded presets' ids. */
export const DEMO_PRESET_IDS = { roomB: "01JDEMOPRESETROOMBGEN00000", timer: "01JDEMOPRESETZONE3TIMER000" } as const;
let store: { revision: number; presets: StoredPreset[] } | null = null;
/** A new demo (another backend) starts from the seed again. */
export function resetDemoPresets() {
  store = null;
}
/** Two presets saved earlier, from the rooms' live values when the demo starts. */
function seeded(states: States, now: number) {
  if (store) return store;
  const make = (id: string, name: string, scope: string, from: PresetTarget, daysAgo: number): StoredPreset => {
    const at = new Date(now - daysAgo * 86_400_000).toISOString();
    return {
      id,
      name,
      scope: scope as StoredPreset["scope"],
      sections: SCOPES[scope],
      from,
      values: capture(read(states, from).values, SCOPES[scope]),
      created_at: at,
      updated_at: at,
      deleted_at: null,
    };
  };
  store = {
    revision: 1,
    presets: [
      make(DEMO_PRESET_IDS.roomB, "Room B generative push", "targets", { room_id: "room:room_b_" }, 9),
      make(DEMO_PRESET_IDS.timer, "Zone 3 day timer", "timers", { room_id: "room:" }, 21),
    ],
  };
  return store;
}

const ok = (data: unknown, now: number, status = "verified", eventIds: string[] = []) => ({
  api: 2,
  ok: true,
  room_id: null,
  revision: data && typeof data === "object" && typeof (data as { revision?: unknown }).revision === "number" ? (data as { revision: number }).revision : null,
  readback: { status, at: new Date(now).toISOString() },
  event_ids: eventIds,
  data,
});
const failure = (code: string, message: string, data?: unknown, current?: number) => ({
  api: 2,
  ok: false,
  error: { code, message, ...(current === undefined ? {} : { current_revision: current }) },
  ...(data === undefined ? {} : { data }),
});

/** What a 3.18 integration answers for the preset services and copy_config. `write`
 * sets one number entity and returns the states after it. */
/** presets.given_values: only the scope's sections (never timers), only their keys, finite numbers
 * (p2_mode a text). */
function givenValues(value: unknown, sections: string[]): Record<string, Record<string, unknown>> {
  if (!value || typeof value !== "object" || Array.isArray(value) || !Object.keys(value).length)
    throw new Error("values must name at least one section");
  const out: Record<string, Record<string, unknown>> = {};
  for (const [section, keys] of Object.entries(value as Record<string, unknown>)) {
    if (!sections.includes(section) || section === "timers") throw new Error(`values cannot hold the section ${section}`);
    if (!keys || typeof keys !== "object" || Array.isArray(keys) || !Object.keys(keys).length)
      throw new Error(`values.${section} must hold at least one setting`);
    out[section] = {};
    for (const [key, v] of Object.entries(keys as Record<string, unknown>)) {
      if (!SECTIONS[section].includes(key)) throw new Error(`${key} is not a setting of ${section}`);
      if (key === "p2_mode" ? typeof v !== "string" : typeof v !== "number" || !Number.isFinite(v))
        throw new Error(`${key} must be a ${key === "p2_mode" ? "text" : "finite number"}`);
      out[section][key] = v;
    }
  }
  return out;
}

export function answerPresets(
  action: string,
  data: Record<string, unknown>,
  states: States,
  write: (entityId: string, value: number) => States,
  now: number,
): unknown {
  const site = seeded(states, now);
  try {
    if (action === "preset_list")
      return ok({ revision: site.revision, presets: structuredClone(site.presets.filter((p) => !p.deleted_at)), error: null }, now);
    if (action === "preset_save") {
      const name = String(data.name ?? "").trim();
      if (!name || name.length > 60) throw new Error("A preset needs a name of up to 60 characters");
      const scope = String(data.scope);
      if (!SCOPES[scope]) throw new Error("scope must be targets, timers or all");
      const from = ref(data.from);
      if (data.expected_revision !== site.revision)
        return failure("stale_revision", "Presets changed elsewhere. Reload before saving.", undefined, site.revision);
      // Given values (a browser recipe imported) are checked as the integration's given_values does.
      const given = data.values === undefined ? null : givenValues(data.values, SCOPES[scope]);
      const { values, unread } = given ? { values: given, unread: [] as string[] } : read(states, from);
      const at = new Date(now).toISOString();
      const preset: StoredPreset = {
        id: demoId(now, `preset:${name}:${site.presets.length}`),
        name,
        scope: scope as StoredPreset["scope"],
        sections: SCOPES[scope],
        from,
        values: given ? Object.fromEntries(SCOPES[scope].filter((x) => x in given).map((x) => [x, given[x]])) : capture(values, SCOPES[scope]),
        created_at: at,
        updated_at: at,
        deleted_at: null,
      };
      site.presets.push(preset);
      site.revision += 1;
      const keys = SCOPES[scope].flatMap((s) => SECTIONS[s]);
      return ok({ preset: structuredClone(preset), revision: site.revision, skipped: unread.filter((k) => keys.includes(k)) }, now, "none");
    }
    if (action === "preset_delete") {
      const preset = site.presets.find((p) => p.id === data.id && !p.deleted_at);
      if (!preset) throw new Error(`No preset ${String(data.id)}`);
      if (data.expected_revision !== site.revision)
        return failure("stale_revision", "Presets changed elsewhere. Reload before saving.", undefined, site.revision);
      preset.deleted_at = preset.updated_at = new Date(now).toISOString();
      site.revision += 1;
      return ok({ preset: structuredClone(preset), revision: site.revision }, now, "none");
    }
    // preset_apply / copy_config
    let wanted: Wanted;
    let skipped: string[] | undefined;
    if (action === "preset_apply") {
      const preset = site.presets.find((p) => p.id === data.preset_id && !p.deleted_at);
      if (!preset) throw new Error(`No preset ${String(data.preset_id)}`);
      wanted = structuredClone(preset.values);
    } else {
      const sections = Array.isArray(data.sections) ? data.sections.map(String) : [];
      if (!sections.length || sections.some((s) => !SECTIONS[s])) throw new Error("sections must name one or more of " + Object.keys(SECTIONS).join(", "));
      const source = ref(data.from);
      if (!known(states, source.room_id)) throw new Error(`Room ${source.room_id} is unknown or ambiguous`);
      const { values, unread } = read(states, source);
      wanted = capture(values, sections);
      const keys = sections.flatMap((s) => SECTIONS[s]);
      skipped = unread.filter((k) => keys.includes(k));
    }
    if (!Array.isArray(data.to) || !data.to.length) throw new Error("Give at least one target");
    const targets = data.to.map(ref);
    for (const t of targets) if (!known(states, t.room_id)) throw new Error(`Room ${t.room_id} is unknown or ambiguous`);
    const out: PresetResult = { diff: [], missing: [] };
    const refused: NonNullable<PresetResult["applied"]> = [];
    const plans = targets.map((target) => {
      const current = read(states, target).values;
      const rows: { section: string; key: string; value: unknown }[] = [];
      for (const [section, keys] of Object.entries(wanted))
        for (const [key, value] of Object.entries(keys)) {
          if (!(key in current)) {
            out.missing.push({ target, key } as PresetMissing);
            continue;
          }
          if (same(current[key], value)) continue;
          if (section === "timers" && !(Array.isArray(value) ? value.length : value)) {
            out.missing.push({ target, key, reason: NO_TIMER[key] });
            refused.push({ target, key, readback: "refused", error: NO_TIMER[key] });
            continue;
          }
          rows.push({ section, key, value });
          out.diff.push({ target, key, old: current[key], new: value });
        }
      return { target, rows };
    });
    if (data.preview) return ok(skipped ? { ...out, skipped } : out, now, "none");
    const applied: NonNullable<PresetResult["applied"]> = [];
    const eventIds: string[] = [];
    let live = states;
    for (const { target, rows } of plans)
      for (const row of rows) {
        if (row.section === "timers") {
          const id = row.key === "timers" ? copyDemoTimers(target.room_id, row.value as Record<string, unknown>[], now) : null;
          if (id) eventIds.push(id);
          applied.push({ target, key: row.key, readback: id ? "verified" : "refused", error: id ? null : "the timer programs read back different" });
          continue;
        }
        const entityId = entityOf(live, target, row.key);
        if (!entityId) {
          // Room A's off-state setting: never reached, as no other room has an entity for it.
          applied.push({ target, key: row.key, readback: "refused", error: "no entity" });
          continue;
        }
        const old = numberIn(live, entityId);
        live = write(entityId, Number(row.value));
        const held = numberIn(live, entityId);
        const verified = held !== null && same(held, row.value);
        const id = journalDemoTargetWrite(target.room_id, prefixOf(target.room_id), entityId, old, Number(row.value), now);
        if (id) eventIds.push(id);
        applied.push({ target, key: row.key, readback: verified ? "verified" : "refused", error: verified ? null : "the value read back different" });
      }
    const result: PresetResult = { ...out, applied: [...applied, ...refused], ...(skipped ? { skipped } : {}) };
    const notApplied = result.applied!.filter((a) => a.readback === "refused");
    if (notApplied.length) return failure("guard_refused", "Not applied: " + notApplied.map((a) => `${a.key}: ${a.error}`).join("; "), result);
    return ok(result, now, applied.length ? "verified" : "none", eventIds);
  } catch (error) {
    return failure("invalid", error instanceof Error ? error.message : String(error));
  }
}
