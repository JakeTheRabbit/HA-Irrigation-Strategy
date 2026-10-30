import type { DemoHandler } from "../parity-demo";
import type { AlertPreview, AlertRule, AlertRuleListItem, AlertSource } from "../parity-types";
import { demoId } from "./journal";

/** The demo's alert rules (T1), kept as the integration keeps them (alert_rules.py, site_api.py): one
 * site-wide list with its own revision, each save journalled (`config.changed {store: site, section:
 * alert_rules, old, new}`) so `history_revert` puts it back, the sentences in the integration's own
 * words, and a replay that runs the rule's lifecycle minute by minute over a made-up yesterday. A
 * save is not read back by the envelope (`readback: none`): the panel reads the list again.
 *
 * Current values follow the demo's states: Room A zone 2 EC 4.4 mS/cm, zone 3's back EC probe silent
 * for 3 h, Room B's controller beat 18 s ago, Part B stock 5.4 L; no zone has a flow meter. Times are
 * the viewer's clock. */

type Rule = AlertRule;
type Seeded = Rule & { fired_ago_min?: number; firing_ago_min?: number };
const MIN = 60_000;
const ROOMS: Record<string, { name: string; lights: [number, number]; index: number }> = {
  "room:": { name: "Room A", lights: [10, 22], index: 0 },
  "room:room_b_": { name: "Room B", lights: [8, 20], index: 1 },
};
const TANKS: Record<string, string> = {
  silica: "Silica", part_b: "Part B", part_a: "Part A", cleaner: "Line cleaner", veg_base: "Veg base", finisher: "Finisher",
};
const UNITS: Record<AlertSource, [string, string]> = {
  "zone.vwc": ["%", "VWC"],
  "zone.ec": ["mS/cm", "EC"],
  "zone.temperature": ["°C", "root-zone temperature"],
  "feed.ph": ["pH", "feed pH"],
  "feed.ec": ["mS/cm", "feed EC"],
  "tank.level": ["%", "tank level"],
  "stock.pct": ["%", "stock tank"],
  "stock.litres": ["L", "stock tank"],
  "zone.flow_ratio": ["%", "flow"],
  "controller.heartbeat": ["s", "controller heartbeat age"],
  "probe.silence_s": ["s", "probe silence"],
};
const ZONED = ["zone.vwc", "zone.ec", "zone.temperature", "zone.flow_ratio"];

const rule = (r: Partial<Seeded> & Pick<Rule, "id" | "room_id" | "source" | "op" | "threshold">): Seeded => ({
  kind: "threshold", zones: [], unit: UNITS[r.source][0], window: { kind: "all" }, min_duration_s: 300,
  severity: "warning", routing: "sensors", active: true, ...r,
});
function seed(): { revision: number; rules: Seeded[] } {
  return {
    revision: 4,
    rules: [
      rule({ id: "01JDEMRULE0000000000000001", room_id: "room:", source: "probe.silence_s", entity_id: "sensor.demo_z3_back_ec", op: "above", threshold: 1800, firing_ago_min: 145 }),
      rule({ id: "01JDEMRULE0000000000000002", room_id: "room:", source: "zone.ec", zones: [2], op: "above", threshold: 4.5, min_duration_s: 7200, window: { kind: "lights_on" }, fired_ago_min: 160 }),
      rule({ id: "01JDEMRULE0000000000000003", room_id: "room:room_b_", source: "controller.heartbeat", op: "above", threshold: 120, fired_ago_min: 3 * 1440 + 370 }),
      rule({ id: "01JDEMRULE0000000000000004", room_id: "room:room_b_", source: "zone.flow_ratio", zones: [1], op: "below", threshold: 80 }),
      rule({ id: "01JDEMRULE0000000000000005", room_id: "room:", source: "stock.litres", tank_id: "part_b", op: "below", threshold: 6, min_duration_s: 1800, active: false }),
    ],
  };
}
let store = seed();
const journal = new Map<string, { old: Seeded[]; new: Seeded[] }>();
/** A new demo (another backend) starts from the seed. */
export function resetDemoAlertRules() {
  store = seed();
  journal.clear();
}

// ------------------------------------------------------------------ the integration's words
const num = (v: number) => String(Number(v.toFixed(2)));
const duration = (seconds: number) => {
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  if (s % 3600 === 0) return `${s / 3600} h`;
  return `${Number((s / 60).toFixed(1))} min`;
};
const amount = (v: number, unit: string) => (unit === "s" ? duration(v) : unit === "%" ? `${num(v)}%` : unit === "pH" ? `pH ${num(v)}` : `${num(v)} ${unit}`);
const zonesWords = (z: number[]) => (z.length === 1 ? `zone ${z[0]}` : `zones ${z.slice(0, -1).join(", ")} and ${z.at(-1)}`);
const probeName = (entity: string) => {
  const m = /^sensor\.demo_z(\d)_(front|back)_(vwc|ec)$/.exec(entity);
  return m ? `Zone ${m[1]} ${m[2]} ${m[3] === "ec" ? "EC" : "VWC"}` : null;
};
function label(r: Rule) {
  const words = UNITS[r.source][1];
  if (ZONED.includes(r.source)) return `${zonesWords(r.zones ?? [])} ${words}`;
  if (r.source === "stock.pct" || r.source === "stock.litres") return `${words} ${TANKS[r.tank_id ?? ""] ?? r.tank_id}`;
  if (r.source === "probe.silence_s") return `${probeName(r.entity_id ?? "") ?? r.entity_id} silence`;
  return words;
}
function summary(r: Rule) {
  const seconds = r.min_duration_s;
  let text = `Tell when ${ROOMS[r.room_id]?.name ?? r.room_id} ${label(r)} ${seconds ? "stays" : "goes"} ${r.op} ${amount(r.threshold, r.unit)}`;
  if (seconds) text += ` for ${duration(seconds)}`;
  if (r.window.kind === "lights_on") text += " during lights-on";
  else if (r.window.kind === "lights_off") text += " during lights-off";
  else if (r.window.kind === "custom") text += ` between ${r.window.from} and ${r.window.to}`;
  return `${text}.`;
}

// ------------------------------------------------------------------ the rule as stored
function validate(raw: Record<string, unknown>, id: string): Seeded {
  if (typeof raw.room_id !== "string" || !ROOMS[raw.room_id]) throw new Error("Room is unknown or ambiguous");
  const source = raw.source as AlertSource;
  if (!UNITS[source]) throw new Error(`source must be one of ${Object.keys(UNITS).join(", ")}`);
  const zones = [...new Set(Array.isArray(raw.zones) ? (raw.zones as number[]) : [])].sort((a, b) => a - b);
  if (zones.some((z) => !Number.isInteger(z) || z < 1)) throw new Error("zones must be a list of zone numbers");
  if (ZONED.includes(source) && !zones.length) throw new Error(`${source} needs at least one zone`);
  if (raw.op !== "above" && raw.op !== "below") throw new Error("op must be above or below");
  if (typeof raw.threshold !== "number" || !Number.isFinite(raw.threshold)) throw new Error("threshold must be a number");
  const wait = raw.min_duration_s ?? 0;
  if (!Number.isInteger(wait) || (wait as number) < 0 || (wait as number) > 86400)
    throw new Error("min_duration_s must be a whole number of seconds from 0 to 86400");
  const window = (typeof raw.window === "object" && raw.window ? raw.window : { kind: "all" }) as Rule["window"];
  const out: Seeded = rule({
    id, room_id: raw.room_id, source, zones, op: raw.op, threshold: raw.threshold, min_duration_s: wait as number,
    window: window.kind === "custom" ? window : { kind: window.kind }, active: raw.active !== false,
  });
  if (source === "probe.silence_s") {
    if (typeof raw.entity_id !== "string" || !raw.entity_id.includes(".")) throw new Error("probe.silence_s needs the probe's entity_id");
    out.entity_id = raw.entity_id;
  }
  if (source === "stock.pct" || source === "stock.litres") {
    if (typeof raw.tank_id !== "string" || !raw.tank_id) throw new Error(`${source} needs the stock tank's tank_id`);
    out.tank_id = raw.tank_id;
  }
  return out;
}

// ------------------------------------------------------------------ values and yesterday
const ec = (room: number, zone: number) => (room ? 2.9 + zone * 0.2 : ([2.8, 4.4, 4.1][zone - 1] ?? 4.2));
/** What the source reads now; null for what the demo has no sensor for (flow meters). */
function current(r: Rule, now: number): number | null {
  const room = ROOMS[r.room_id]?.index ?? 0;
  const z = r.zones ?? [];
  const worst = (values: number[]) => (r.op === "below" ? Math.min(...values) : Math.max(...values));
  switch (r.source) {
    case "zone.vwc": return worst(z.map((n) => 54 + n * 2 + room * 3));
    case "zone.ec": return worst(z.map((n) => ec(room, n)));
    case "zone.temperature": return 21.4;
    case "zone.flow_ratio": return null;
    case "feed.ph": return room ? 5.8 : 5.66;
    case "feed.ec": return room ? 2.8 : 3.06;
    case "tank.level": return room ? 71 : 58;
    case "stock.litres": return r.tank_id === "part_b" && !room ? 5.4 : 12;
    case "stock.pct": return r.tank_id === "part_b" && !room ? 27 : 60;
    case "controller.heartbeat": return 18;
    case "probe.silence_s": return r.entity_id === "sensor.demo_z3_back_ec" ? Math.round((3 * 60 * MIN + (now % MIN)) / 1000) : 40;
  }
}
/** Yesterday's 5-minute readings: VWC drying back through the night and topped up by two shots a
 * day (with one short dip), the others wandering around their value now. */
function series(r: Rule, now: number): [number, number | null][] {
  const [on] = ROOMS[r.room_id]?.lights ?? [10, 22];
  const start = now - 24 * 60 * MIN;
  const out: [number, number | null][] = [];
  const base = current(r, now);
  for (let t = start; t <= now; t += 5 * MIN) {
    const d = new Date(t);
    const hour = d.getHours() + d.getMinutes() / 60;
    const since = (hour - on + 24) % 24;
    let v: number | null;
    if (base === null) v = null;
    else if (r.source === "zone.vwc") {
      // 64 % after each shot (lights-on, 6 h later); 3 %/h down while lit, 1.4 %/h in the dark.
      v = since < 6 ? 64 - since * 3 : since < 12 ? 64 - (since - 6) * 3 : 46 - (since - 12) * 1.4;
      v += (base - 58) / 2;
      if (since >= 3 && since < 3 + 10 / 60) v -= 20;
    } else if (r.source === "probe.silence_s") {
      v = r.entity_id === "sensor.demo_z3_back_ec" ? Math.max(0, (t - (now - 3 * 60 * MIN)) / 1000) || (t % (2 * MIN)) / 1000 : (t % (2 * MIN)) / 1000;
    } else if (r.source === "controller.heartbeat") {
      v = since > 17 && since < 17.2 ? (since - 17) * 3600 + 60 : ((t / 1000) % 60);
    } else if (r.source === "tank.level") v = 92 - since * 2.8;
    else v = base * (1 + 0.06 * Math.sin((since / 12) * Math.PI));
    out.push([t, v === null ? null : Number(v.toFixed(2))]);
  }
  return out;
}

const pad = (n: number) => String(n).padStart(2, "0");
const hhmm = (ms: number) => `${pad(new Date(ms).getHours())}:${pad(new Date(ms).getMinutes())}`;
const breaching = (v: number | null, r: Rule) => v !== null && (r.op === "below" ? v < r.threshold : v > r.threshold);
function inWindow(t: number, r: Rule) {
  if (r.window.kind === "all") return true;
  const [on, off] = ROOMS[r.room_id]?.lights ?? [10, 22];
  const d = new Date(t);
  const minute = d.getHours() * 60 + d.getMinutes();
  const [from, to] =
    r.window.kind === "custom"
      ? [r.window.from, r.window.to].map((x = "00:00") => Number(x.slice(0, 2)) * 60 + Number(x.slice(3, 5)))
      : r.window.kind === "lights_on" ? [on * 60, off * 60] : [off * 60, on * 60];
  return (minute - from + 1440) % 1440 < (to - from + 1440) % 1440;
}
/** alert_rules.replay without mutes: the rule's lifecycle at every minute over yesterday. */
function replay(r: Rule, now: number): AlertPreview {
  const samples = series(r, now);
  const values = samples.flatMap(([, v]) => (v === null ? [] : [v]));
  const iso = (ms: number) => new Date(ms).toISOString();
  const fires: AlertPreview["fires"] = [];
  const ignored: AlertPreview["ignored"] = [];
  let state: "armed" | "pending" | "firing" = "armed";
  let since = 0;
  let i = 0;
  let value: number | null = null;
  let outside: number | null = null;
  for (let t = samples[0][0]; t <= now; t += MIN) {
    while (i < samples.length && samples[i][0] <= t) value = samples[i++][1];
    const bad = breaching(value, r);
    if (state === "firing") {
      if (value !== null && !bad) {
        fires[fires.length - 1].end = iso(t);
        state = "armed";
      }
    } else if (bad && inWindow(t, r)) {
      if (state === "armed") [state, since] = ["pending", t];
      if (t - since >= r.min_duration_s * 1000) {
        fires.push({ start: iso(since), fired_at: iso(t), end: null });
        state = "firing";
      }
    } else if (state === "pending") {
      if (value !== null && !bad) ignored.push({ start: iso(since), end: iso(t), reason: "shorter than min_duration" });
      state = "armed";
    }
    const out = bad && state === "armed";
    if (out && outside === null) outside = t;
    if (!out && outside !== null) {
      ignored.push({ start: iso(outside), end: iso(t), reason: "outside window" });
      outside = null;
    }
  }
  ignored.sort((a, b) => a.start.localeCompare(b.start));
  const count = fires.length;
  const min = values.length ? Math.min(...values) : null;
  const max = values.length ? Math.max(...values) : null;
  let sentence: string;
  if (count > 10) sentence = `That's ${count} messages a day. Try a longer wait or a ${r.op === "below" ? "lower" : "higher"} threshold.`;
  else if (count) sentence = `This rule would have fired ${count === 1 ? "once" : `${count} times`} yesterday — ${fires.map((f) => hhmm(Date.parse(f.fired_at))).join(", ")}.`;
  else if (min === null) sentence = "There's no history for this in the last 24 h.";
  else sentence = `It wouldn't have fired in the last 24 h. ${r.op === "below" ? `Lowest was ${amount(min, r.unit)}` : `Highest was ${amount(max!, r.unit)}`}.`;
  return {
    summary_sentence: summary(r),
    series: samples.map(([t, v]) => [iso(t), v] as [string, number]),
    fires, ignored, count, min, max, sentence,
  };
}

// ------------------------------------------------------------------ the services
const refusal = (code: string, message: string, current?: number) => ({
  api: 2, ok: false, error: { code, message, ...(current === undefined ? {} : { current_revision: current }) },
});
const envelope = (now: number, data: Record<string, unknown>, status: string, eventIds: string[] = [], room: string | null = null) => ({
  api: 2, ok: true, room_id: room, revision: typeof data.revision === "number" ? data.revision : null,
  readback: { status, at: new Date(now).toISOString() }, event_ids: eventIds, data,
});
const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const stored = (r: Seeded): Rule => {
  const { fired_ago_min: _f, firing_ago_min: _g, ...rest } = r;
  return structuredClone(rest);
};

function save(data: Record<string, unknown>, now: number, change: (rules: Seeded[]) => Seeded) {
  if (data.expected_revision !== store.revision)
    return refusal("stale_revision", "Alert rules changed elsewhere. Reload before saving.", store.revision);
  const rules = structuredClone(store.rules);
  let r: Seeded;
  try {
    r = change(rules);
  } catch (error) {
    return refusal("invalid", message(error));
  }
  const eventId = demoId(now, `alert_rules:${store.revision}`);
  journal.set(eventId, { old: store.rules, new: rules });
  store = { revision: store.revision + 1, rules };
  return { r, eventId };
}
const same = (a: Seeded[], b: Seeded[]) => JSON.stringify(a.map(stored)) === JSON.stringify(b.map(stored));

export const handlers: DemoHandler[] = [
  {
    action: "alert_rule_list",
    answer: (data, now) => ({
      rules: store.rules
        .filter((r) => data.room_id == null || r.room_id === data.room_id)
        .map((r): AlertRuleListItem => {
          const firing = r.active && r.firing_ago_min !== undefined;
          return {
            ...stored(r),
            summary_sentence: summary(r),
            state: firing ? "firing" : r.active ? "armed" : "draft",
            last_fired: firing ? new Date(now - r.firing_ago_min! * MIN).toISOString() : r.fired_ago_min !== undefined ? new Date(now - r.fired_ago_min * MIN).toISOString() : null,
            firing_since: firing ? new Date(now - r.firing_ago_min! * MIN).toISOString() : null,
            current_value: current(r, now),
          } as AlertRuleListItem;
        }),
      revision: store.revision,
    }),
  },
  {
    action: "alert_rule_preview",
    answer: (data, now) => {
      try {
        return replay(validate((data.rule ?? {}) as Record<string, unknown>, "draft"), now);
      } catch (error) {
        return refusal("invalid", message(error));
      }
    },
  },
  {
    action: "alert_rule_test",
    answer: (data, now) => {
      try {
        const r = typeof data.id === "string" ? store.rules.find((x) => x.id === data.id) : validate((data.rule ?? {}) as Record<string, unknown>, "test");
        if (!r) throw new Error(`No alert rule ${String(data.id)}`);
        const out = { summary_sentence: summary(r), replay: replay(r, now) };
        // Rule pushes go to the phones ticked for Sensors: the demo's owner (Phone 1).
        return data.send ? { ...out, delivery: [{ service: "notify.mobile_app_phone_1", ok: true, error: null }] } : out;
      } catch (error) {
        return refusal("invalid", message(error));
      }
    },
  },
  {
    action: "alert_rule_set",
    answer: (data, now) => {
      const raw = (data.rule ?? {}) as Record<string, unknown>;
      const out = save(data, now, (rules) => {
        const id = typeof raw.id === "string" ? raw.id : null;
        const at = id ? rules.findIndex((r) => r.id === id) : -1;
        if (id && at < 0) throw new Error(`No alert rule ${id}`);
        const r = validate(raw, id ?? demoId(now, `rule:${store.revision}`));
        if (at < 0) rules.push(r);
        else rules[at] = { ...r, fired_ago_min: rules[at].fired_ago_min, firing_ago_min: r.active ? rules[at].firing_ago_min : undefined };
        return r;
      });
      if (!("eventId" in out)) return out;
      const sentence = summary(out.r);
      return envelope(now, { rule: { ...stored(out.r), summary_sentence: sentence }, summary_sentence: sentence, revision: store.revision }, "none", [out.eventId], out.r.room_id);
    },
  },
  {
    action: "alert_rule_delete",
    answer: (data, now) => {
      const out = save(data, now, (rules) => {
        const at = rules.findIndex((r) => r.id === data.id);
        if (at < 0) throw new Error(`No alert rule ${String(data.id)}`);
        return rules.splice(at, 1)[0];
      });
      if (!("eventId" in out)) return out;
      return envelope(now, { id: out.r.id, revision: store.revision }, "none", [out.eventId], out.r.room_id);
    },
  },
  {
    action: "history_revert",
    match: (data) => journal.has(String(data.event_id)),
    answer: (data, now) => {
      const change = journal.get(String(data.event_id))!;
      if (!same(store.rules, change.new))
        return refusal("stale_revision", "The alert rules have changed since this change; reload the history", store.revision);
      const newId = demoId(now, `revert:${String(data.event_id)}`);
      journal.set(newId, { old: store.rules, new: change.old });
      store = { revision: store.revision + 1, rules: structuredClone(change.old) };
      return envelope(now, { reverted_event_id: data.event_id, new_event_id: newId, readback: "verified" }, "verified", [newId]);
    },
  },
];
