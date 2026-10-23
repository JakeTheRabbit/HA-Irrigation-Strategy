import type { SentenceToken } from "@/components/primitives/sentence";
import { formatEc, formatTemp, formatVolume, getDisplayUnits } from "./display-units";
import type { NotifyKind, NotifyRecipient } from "./notify";
import { callV2 } from "./parity-api";
import type { AlertRule, AlertRuleList, AlertRuleListItem, AlertSource, TimerWindow } from "./parity-types";
import { clock, dayKey, dayLabel } from "./time";

/** Your own alert rules (T1, backend alert_rules.py): what a rule can watch, the builder's sentence,
 * a rule's status line and a test push's delivery line. The rules' own sentences (`summary_sentence`,
 * the replay's `sentence`) come from the integration and are never written here. */

export interface RuleContext {
  /** The rule's room, as the room tree names it. */
  room: string;
  zones: number[];
  /** Names of the phones ticked for the rule's routing kind in this room: its pushes go out as it.
   * Null when the phone list could not be read. */
  phones: string[] | null;
  stocks: { id: string; name: string }[];
  probes: { id: string; name: string }[];
}

/** What a rule can watch: each source the integration has (alert_rules.SOURCES), its stored unit,
 * and what it needs besides the room. */
export const RULE_SOURCES: {
  id: AlertRule["source"];
  label: (room: string, zone?: number, name?: string) => string;
  unit: string;
  zoned?: true;
  needs?: "entity_id" | "tank_id";
}[] = [
  { id: "zone.vwc", label: (r, z) => `${r} Zone ${z} moisture`, unit: "%", zoned: true },
  { id: "zone.ec", label: (r, z) => `${r} Zone ${z} EC`, unit: "mS/cm", zoned: true },
  { id: "zone.temperature", label: (r, z) => `${r} Zone ${z} root-zone temperature`, unit: "°C", zoned: true },
  { id: "zone.flow_ratio", label: (r, z) => `${r} Zone ${z} flow`, unit: "%", zoned: true },
  { id: "feed.ph", label: (r) => `${r} feed pH`, unit: "pH" },
  { id: "feed.ec", label: (r) => `${r} feed EC`, unit: "mS/cm" },
  { id: "tank.level", label: (r) => `${r} feed tank level`, unit: "%" },
  { id: "stock.litres", label: (r, _z, n) => `${inRoom(r, n)} stock`, unit: "L", needs: "tank_id" },
  { id: "stock.pct", label: (r, _z, n) => `${inRoom(r, n)} stock level`, unit: "%", needs: "tank_id" },
  { id: "controller.heartbeat", label: (r) => `${r} controller heartbeat age`, unit: "s" },
  { id: "probe.silence_s", label: (r, _z, n) => `${inRoom(r, n)} silence`, unit: "s", needs: "entity_id" },
];
const sourceOf = (id: AlertSource) => RULE_SOURCES.find((s) => s.id === id) ?? RULE_SOURCES[0];
/** A tank's or probe's name after its room, unless Home Assistant's name already starts with it. */
const inRoom = (room: string, name = "") => (name.toLowerCase().startsWith(`${room.toLowerCase()} `) ? name : `${room} ${name}`);

/** A new rule's threshold for each source, in its stored unit. */
const FIRST_THRESHOLD: Record<AlertSource, { op: AlertRule["op"]; threshold: number }> = {
  "zone.vwc": { op: "below", threshold: 30 },
  "zone.ec": { op: "above", threshold: 6 },
  "zone.temperature": { op: "above", threshold: 26 },
  "zone.flow_ratio": { op: "below", threshold: 80 },
  "feed.ph": { op: "above", threshold: 6.5 },
  "feed.ec": { op: "above", threshold: 3 },
  "tank.level": { op: "below", threshold: 25 },
  "stock.litres": { op: "below", threshold: 5 },
  "stock.pct": { op: "below", threshold: 20 },
  "controller.heartbeat": { op: "above", threshold: 120 },
  "probe.silence_s": { op: "above", threshold: 1800 },
};

const clean = (v: number) => Number(v.toPrecision(10));

/** How a source's threshold reads and is typed: in the display units (EC, temperature, volume) or
 * minutes for a probe's silence; stored as the integration keeps it. */
export function displayScale(source: AlertSource): {
  unit: string;
  toDisplay(v: number): number;
  fromDisplay(v: number): number;
  min: number;
  max: number;
  step: number;
} {
  const same = (unit: string, min: number, max: number, step: number) => ({
    unit, min, max, step, toDisplay: clean, fromDisplay: clean,
  });
  const linear = (unit: string, k: number, min: number, max: number, step: number, add = 0) => ({
    unit, min, max, step, toDisplay: (v: number) => clean(v * k + add), fromDisplay: (v: number) => clean((v - add) / k),
  });
  const units = getDisplayUnits();
  switch (sourceOf(source).unit) {
    case "mS/cm":
      if (units.ec === "mS/cm") return same("mS/cm", 0, 20, 0.1);
      return linear("ppm", units.ec === "ppm500" ? 500 : 700, 0, 14000, 10);
    case "°C":
      return units.temp === "F" ? linear("°F", 9 / 5, 32, 122, 0.1, 32) : same("°C", 0, 50, 0.1);
    case "L":
      return units.volume === "gal" ? linear("gal", 1 / 3.785411784, 0, 264, 0.1) : same("L", 0, 1000, 0.1);
    case "pH":
      return same("pH", 0, 14, 0.1);
    case "s":
      return source === "probe.silence_s" ? linear("min", 1 / 60, 0, 1440, 1) : same("s", 0, 86400, 1);
    default:
      return same("%", 0, source === "zone.flow_ratio" ? 200 : 100, 0.1);
  }
}

/** A reading of the rule's source in the display units: "5.4 L", "4.4 mS/cm", "30 %", "3 h". `places`
 * fixes the decimals (the replay's axis and line); else the value's own, at most two. */
export function formatRuleValue(source: AlertSource, value: number, places?: number): string {
  const digits = (v: number) => places ?? Math.min(2, (String(v).split(".")[1] ?? "").length);
  switch (sourceOf(source).unit) {
    case "mS/cm":
      return formatEc(value, digits(value));
    case "°C":
      return formatTemp(value, digits(value));
    case "L":
      return formatVolume(value, digits(value));
    case "pH":
      return `pH ${clean(value)}`;
    case "s": {
      const s = Math.round(value);
      if (s < 120) return `${s} s`;
      if (s < 7200) return `${Math.round(s / 60)} min`;
      return `${clean(Number((s / 3600).toFixed(1)))} h`;
    }
    default:
      return places === undefined ? `${clean(Number(value.toFixed(2)))} %` : `${value.toFixed(places)} %`;
  }
}

const breaching = (rule: Pick<AlertRule, "op" | "threshold">, value: number) =>
  rule.op === "below" ? value < rule.threshold : value > rule.threshold;

const DAY = 86_400_000;

/** A rule's line in Your rules: firing, fired today, last fired, never, or off (and whether it
 * would fire now); held while its room is muted. Times on Home Assistant's clock. */
export function ruleStatus(item: AlertRuleListItem, now: number, tz: string): { text: string; tone: "bad" | "warn" | "muted" } {
  const when = (ms: number) => {
    if (dayKey(ms, tz) === dayKey(now, tz)) return clock(ms, tz);
    const [weekday, day, month] = dayLabel(ms, tz).split(" ");
    return `${now - ms < 6 * DAY ? weekday : `${day} ${month}`} ${clock(ms, tz)}`;
  };
  const since = item.firing_since ? Date.parse(item.firing_since) : NaN;
  if ((item.state === "firing" || item.state === "acknowledged") && Number.isFinite(since))
    return { text: `Firing now · since ${when(since)}`, tone: "bad" };
  if (!item.active) {
    if (item.current_value !== null && breaching(item, item.current_value))
      return { text: `Off · would fire now (${formatRuleValue(item.source, item.current_value)})`, tone: "warn" };
    return { text: "Off", tone: "muted" };
  }
  const held = item.state === "muted" ? "Held: room muted · " : "";
  const fired = item.last_fired ? Date.parse(item.last_fired) : NaN;
  if (!Number.isFinite(fired)) return { text: `${held}Never fired`, tone: "muted" };
  if (dayKey(fired, tz) === dayKey(now, tz)) return { text: `${held}Fired ${clock(fired, tz)} today`, tone: "warn" };
  return { text: `${held}Last fired ${when(fired)}`, tone: "muted" };
}

/** A rule binary sensor's line on an integration before 3.18: only "off" is quiet. */
export function legacyRuleStatus(state: string): { text: string; tone: "bad" | "muted" } {
  if (state === "on") return { text: "Firing now", tone: "bad" };
  return { text: state === "off" ? "Quiet" : "Not reporting", tone: "muted" };
}

/** What a rule watches, in the builder's words. */
export function sourceLabel(rule: Pick<AlertRule, "source" | "zones" | "tank_id" | "entity_id">, ctx: Pick<RuleContext, "room" | "stocks" | "probes">): string {
  const def = sourceOf(rule.source);
  if (def.zoned) {
    const zones = rule.zones ?? [];
    if (zones.length === 1) return def.label(ctx.room, zones[0]);
    const words = `${zones.slice(0, -1).join(", ")} and ${zones.at(-1)}`;
    return def.label(ctx.room, 0).replace("Zone 0", `Zones ${words}`);
  }
  if (def.needs === "tank_id") return def.label(ctx.room, undefined, ctx.stocks.find((s) => s.id === rule.tank_id)?.name ?? rule.tank_id);
  if (def.needs === "entity_id") return def.label(ctx.room, undefined, ctx.probes.find((p) => p.id === rule.entity_id)?.name ?? rule.entity_id);
  return def.label(ctx.room);
}

/** The builder's context for a rule: zones, probes and stocks of the room the tree picked (`here`);
 * in another room, its probe by Home Assistant's name and the stock tanks read for that room. */
export function ruleContext(
  rule: Pick<AlertRule, "room_id" | "entity_id">,
  here: { roomId: string; zones: number[]; probes: { id: string; name: string }[] },
  room: { room: string; phones: string[] | null; stocks: { id: string; name: string }[]; nameOf(entity: string): string },
): RuleContext {
  const own = rule.room_id === here.roomId;
  return {
    room: room.room,
    zones: own ? here.zones : [],
    phones: room.phones,
    stocks: room.stocks,
    probes: own ? here.probes : rule.entity_id ? [{ id: rule.entity_id, name: room.nameOf(rule.entity_id) }] : [],
  };
}

/** The note after a save, worded from the rule the list read back. */
export function saveReceipt(rule: Pick<AlertRule, "active">, at: number, tz: string): string {
  return `${rule.active ? "Saved and watching." : "Saved (off)."} Written and read back ${clock(at, tz)}.`;
}

/** In place on a rule whose source reads nothing: it can't fire until it does. */
export function notReporting(item: AlertRuleListItem, ctx: Pick<RuleContext, "room" | "stocks" | "probes">): string | null {
  return item.current_value === null ? `${sourceLabel(item, ctx)} isn't reporting. This rule can't fire until it does.` : null;
}

/** The phones ticked for a rule's routing kind (Sensors unless the rule says otherwise) that cover
 * the room (`prefix`): its pushes go out as that kind. */
export function sensorsPhones(recipients: readonly NotifyRecipient[], prefix: string, kind = "sensors"): { service: string; name: string }[] {
  return recipients
    .filter((r) => r.kinds.includes(kind) && (!r.rooms.length || r.rooms.includes(prefix)))
    .map((r) => ({ service: r.service, name: r.name }));
}

/** A routing kind as the Notifications page names it. */
export const kindName = (kinds: readonly NotifyKind[], id: string) => kinds.find((k) => k.id === id)?.name ?? id;

const and = (names: string[]) => (names.length < 2 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`);

const sourceKey = (rule: Pick<AlertRule, "source" | "zones" | "tank_id" | "entity_id">) => {
  const def = sourceOf(rule.source);
  if (def.zoned) return `${rule.source}:${(rule.zones ?? []).join(",")}`;
  if (def.needs === "tank_id") return `${rule.source}:${rule.tank_id ?? ""}`;
  if (def.needs === "entity_id") return `${rule.source}:${rule.entity_id ?? ""}`;
  return rule.source;
};

const WINDOWS: { value: TimerWindow["kind"]; label: string }[] = [
  { value: "all", label: "at any time" },
  { value: "lights_on", label: "while lights are on" },
  { value: "lights_off", label: "while lights are off" },
];

/** The builder as a sentence: "Tell [phones] when [source] is [below] [30 %] for [10 min], [at any
 * time]." Who is told is not a choice: rule pushes go to the phones ticked for Sensors, set on the
 * Notifications page. */
export function ruleTokens(draft: AlertRule, set: (next: AlertRule) => void, ctx: RuleContext): (string | SentenceToken)[] {
  const options: { value: string; label: string }[] = [];
  for (const def of RULE_SOURCES) {
    if (def.zoned) for (const z of ctx.zones) options.push({ value: `${def.id}:${z}`, label: def.label(ctx.room, z) });
    else if (def.needs === "tank_id") for (const t of ctx.stocks) options.push({ value: `${def.id}:${t.id}`, label: def.label(ctx.room, undefined, t.name) });
    else if (def.needs === "entity_id") for (const p of ctx.probes) options.push({ value: `${def.id}:${p.id}`, label: def.label(ctx.room, undefined, p.name) });
    else options.push({ value: def.id, label: def.label(ctx.room) });
  }
  const key = sourceKey(draft);
  if (!options.some((o) => o.value === key)) options.unshift({ value: key, label: sourceLabel(draft, ctx) });
  const scale = displayScale(draft.source);
  const windows = draft.window.kind === "custom"
    ? [...WINDOWS, { value: "custom" as const, label: `between ${draft.window.from} and ${draft.window.to}` }]
    : WINDOWS;
  return [
    "Tell",
    { id: "tell", kind: "static", label: "Tell", text: ctx.phones === null ? "phones not known" : ctx.phones.length ? and(ctx.phones) : "no phone yet", href: "#/settings/notifications" },
    "when",
    {
      id: "source",
      kind: "select",
      label: "When",
      value: key,
      options,
      onChange(value) {
        const [id, thing = ""] = value.split(/:(.*)/s) as [AlertSource, string?];
        const def = sourceOf(id);
        const { tank_id: _t, entity_id: _e, ...rest } = draft;
        set({
          ...rest,
          source: id,
          unit: def.unit,
          zones: def.zoned ? thing.split(",").map(Number) : [],
          ...(def.needs === "tank_id" ? { tank_id: thing } : {}),
          ...(def.needs === "entity_id" ? { entity_id: thing } : {}),
          ...(id === draft.source ? {} : FIRST_THRESHOLD[id]),
        });
      },
    },
    "is",
    {
      id: "op",
      kind: "select",
      label: "Is",
      value: draft.op,
      options: [
        { value: "below", label: "below" },
        { value: "above", label: "above" },
      ],
      onChange: (op) => set({ ...draft, op: op as AlertRule["op"] }),
    },
    {
      id: "threshold",
      kind: "number",
      label: "Threshold",
      value: scale.toDisplay(draft.threshold),
      unit: scale.unit,
      min: scale.min,
      max: scale.max,
      step: scale.step,
      onChange: (v) => set({ ...draft, threshold: scale.fromDisplay(v) }),
    },
    "for",
    {
      id: "wait",
      kind: "number",
      label: "For",
      value: clean(draft.min_duration_s / 60),
      unit: "min",
      min: 0,
      max: 1440,
      step: 1,
      onChange: (v) => set({ ...draft, min_duration_s: Math.round(v * 60) }),
    },
    ",",
    {
      id: "window",
      kind: "select",
      label: "When it counts",
      value: draft.window.kind,
      options: windows,
      onChange: (kind) => set({ ...draft, window: kind === "custom" ? draft.window : { kind: kind as "all" } }),
    },
    ".",
  ];
}

/** What a test push did, phone by phone: "Delivered to Ben's phone ✓ · Night phone: not delivered —
 * held for the phone's digest or quiet hours." */
export function deliveryLine(rows: { service: string | null; ok: boolean; error: string | null }[], names: Record<string, string>, kind: string): string {
  if (!rows.length) return `No phone got it: none is ticked for ${kind}.`;
  const name = (service: string) => names[service] ?? service;
  const ok = rows.filter((r) => r.ok && r.service).map((r) => name(r.service!));
  const parts = ok.length ? [`Delivered to ${and(ok)} ✓`] : [];
  for (const r of rows.filter((row) => !row.ok))
    parts.push(r.service ? `${name(r.service)}: not delivered — ${r.error ?? "no reason given"}` : `Not delivered — ${r.error ?? "no reason given"}`);
  return `${parts.join(" · ")}.`;
}

/** A new rule for the room: the first zone's moisture below 30 % for 10 minutes, at any time. */
export function newRule(roomId: string, zone: number): AlertRule {
  return {
    id: "", kind: "threshold", room_id: roomId, zones: [zone], source: "zone.vwc", op: "below", threshold: 30, unit: "%",
    window: { kind: "all" }, min_duration_s: 600, severity: "warning", routing: "sensors", active: true,
  };
}

/** The rule as alert_rule_set and alert_rule_preview take it: no list fields, no empty id. */
export function ruleBody(rule: AlertRule): Record<string, unknown> {
  const out: Record<string, unknown> = {
    kind: "threshold", room_id: rule.room_id, zones: rule.zones ?? [], source: rule.source, op: rule.op,
    threshold: rule.threshold, window: rule.window, min_duration_s: rule.min_duration_s, severity: rule.severity,
    routing: rule.routing, active: rule.active,
  };
  if (rule.id) out.id = rule.id;
  if (rule.entity_id) out.entity_id = rule.entity_id;
  if (rule.tank_id) out.tank_id = rule.tank_id;
  return out;
}

/** What a replay's readings depend on: a preview drawn for another source or room is not this one's. */
export const replayKey = (rule: AlertRule) => `${rule.room_id}|${sourceKey(rule)}`;

/** Undo for a delete that came back with no Journal event: the rule saved again as a new rule, only
 * while the rules are as the delete left them (`revision`), then read back from the list. */
export async function putBackDeleted(controller: Parameters<typeof callV2>[0], rule: AlertRule, revision: number): Promise<void> {
  const listed = await callV2<AlertRuleList>(controller, "alert_rule_list", {});
  if (listed.kind !== "ok") throw new Error("The rule list could not be read. Nothing was changed.");
  if (listed.data.revision !== revision) throw new Error("The rules changed since the delete. Nothing was changed: put it back from History.");
  const { id: _id, ...body } = ruleBody(rule);
  const out = await callV2(controller, "alert_rule_set", { expected_revision: revision, rule: body });
  if (out.kind !== "ok") throw new Error(out.kind === "error" ? `${out.message} Nothing was changed.` : "This needs Crop Steering 3.18 or newer.");
  const back = await callV2<AlertRuleList>(controller, "alert_rule_list", {});
  if (back.kind !== "ok" || !back.data.rules.some((r) => sameRule(r, rule)))
    throw new Error("The controller did not confirm the rule is back. Reload and check it before trying again.");
}

/** Whether the listed rule holds what was saved (the read-back of a save or a switch). */
export function sameRule(a: AlertRule, b: AlertRule): boolean {
  const { id: _a, ...x } = ruleBody(a);
  const { id: _b, ...y } = ruleBody(b);
  return JSON.stringify(x) === JSON.stringify(y);
}
