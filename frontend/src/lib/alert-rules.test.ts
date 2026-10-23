import { afterEach, describe, expect, test } from "vitest";
import type { SentenceToken } from "@/components/primitives/sentence";
import { setDisplayUnits } from "./display-units";
import type { AlertRule, AlertRuleListItem } from "./parity-types";
import { parityDemo } from "./parity-demo";
import { resetDemoAlertRules } from "./parity-demo/settings";
import {
  RULE_SOURCES,
  deliveryLine,
  formatRuleValue,
  notReporting,
  ruleContext,
  ruleStatus,
  ruleTokens,
  saveReceipt,
  sensorsPhones,
  type RuleContext,
} from "./alert-rules";

const TZ = "Pacific/Auckland";
// Fri 23 Oct 2026, 14:10 in Auckland.
const NOW = Date.parse("2026-10-23T14:10:00+13:00");
const at = (text: string) => new Date(Date.parse(text)).toISOString();

const base: AlertRule = {
  id: "r1", kind: "threshold", room_id: "room:f2_", zones: [1], source: "zone.vwc", op: "below", threshold: 30,
  unit: "%", window: { kind: "all" }, min_duration_s: 600, severity: "warning", routing: "sensors", active: true,
};
const item = (over: Partial<AlertRuleListItem>): AlertRuleListItem => ({
  ...base, summary_sentence: "Tell when F2 zone 1 VWC stays below 30% for 10 min.", state: "armed", last_fired: null, firing_since: null, current_value: 50, ...over,
});
const ctx: RuleContext = {
  room: "F2",
  zones: [1, 2, 3],
  phones: ["Ben's phone"],
  stocks: [{ id: "part_b", name: "Part B" }],
  probes: [{ id: "sensor.z2_back_ec", name: "Zone 2 back EC" }],
};
const token = (parts: (string | SentenceToken)[], id: string) => {
  const found = parts.find((p): p is SentenceToken => typeof p !== "string" && p.id === id);
  if (!found) throw new Error(`no ${id} token`);
  return found;
};

afterEach(() => setDisplayUnits({ ec: "mS/cm", temp: "C", volume: "L", clock: "24" }));

describe("ruleStatus", () => {
  test("ruleStatus covers firing, fired today, last fired, never, off-would-fire", () => {
    expect(ruleStatus(item({ state: "firing", firing_since: at("2026-10-23T12:42:00+13:00") }), NOW, TZ)).toEqual({
      text: "Firing now · since 12:42",
      tone: "bad",
    });
    expect(ruleStatus(item({ last_fired: at("2026-10-23T11:31:00+13:00") }), NOW, TZ)).toEqual({
      text: "Fired 11:31 today",
      tone: "warn",
    });
    expect(ruleStatus(item({ last_fired: at("2026-10-20T03:40:00+13:00") }), NOW, TZ)).toEqual({
      text: "Last fired Tue 03:40",
      tone: "muted",
    });
    // Older than a week: the date, not a weekday that could be read as this week's.
    expect(ruleStatus(item({ last_fired: at("2026-10-02T03:40:00+13:00") }), NOW, TZ).text).toBe("Last fired 2 Oct 03:40");
    expect(ruleStatus(item({}), NOW, TZ)).toEqual({ text: "Never fired", tone: "muted" });
    const stock = item({ source: "stock.litres", unit: "L", tank_id: "part_b", zones: [], threshold: 6, active: false, state: "draft", current_value: 5.4 });
    expect(ruleStatus(stock, NOW, TZ)).toEqual({ text: "Off · would fire now (5.4 L)", tone: "warn" });
    expect(ruleStatus({ ...stock, current_value: 8 }, NOW, TZ)).toEqual({ text: "Off", tone: "muted" });
    // The value is shown in the display units.
    setDisplayUnits({ volume: "gal" });
    expect(ruleStatus(stock, NOW, TZ).text).toBe("Off · would fire now (1.4 gal)");
  });

  test("12-hour clock follows the display units", () => {
    setDisplayUnits({ clock: "12" });
    expect(ruleStatus(item({ last_fired: at("2026-10-23T11:31:00+13:00") }), NOW, TZ).text).toBe("Fired 11:31 am today");
  });

  test("a source that is not reporting is named in place", () => {
    expect(notReporting(item({ source: "tank.level", zones: [], current_value: null }), ctx)).toBe(
      "F2 feed tank level isn't reporting. This rule can't fire until it does.",
    );
    expect(notReporting(item({}), ctx)).toBeNull();
  });
});

describe("ruleTokens", () => {
  test("ruleTokens Tell token lists sensors-kind phones and links to notifications", () => {
    const parts = ruleTokens(base, () => {}, { ...ctx, phones: ["Ben's phone", "Night phone"] });
    expect(token(parts, "tell")).toEqual({
      id: "tell",
      kind: "static",
      label: "Tell",
      text: "Ben's phone and Night phone",
      href: "#/settings/notifications",
    });
    expect(parts.filter((p) => typeof p === "string")).toEqual(["Tell", "when", "is", "for", ",", "."]);
    expect((token(ruleTokens(base, () => {}, { ...ctx, phones: [] }), "tell") as { text: string }).text).toBe("no phone yet");
  });

  test("sensorsPhones: the phones ticked for Sensors that cover this room", () => {
    const recipients = [
      { service: "notify.a", name: "Ben's phone", user_id: null, kinds: ["sensors", "stock"], rooms: [], urgent_high_priority: false },
      { service: "notify.b", name: "Night phone", user_id: null, kinds: ["sensors"], rooms: ["f1_"], urgent_high_priority: false },
      { service: "notify.c", name: "Sam's phone", user_id: null, kinds: ["stock"], rooms: [], urgent_high_priority: false },
    ];
    expect(sensorsPhones(recipients, "f2_")).toEqual([{ service: "notify.a", name: "Ben's phone" }]);
    expect(sensorsPhones(recipients, "f1_").map((p) => p.name)).toEqual(["Ben's phone", "Night phone"]);
  });

  test("the source select names each zone, tank and probe, and picks the rule's", () => {
    const source = token(ruleTokens(base, () => {}, ctx), "source") as Extract<SentenceToken, { kind: "select" }>;
    expect(source.value).toBe("zone.vwc:1");
    const labels = source.options.map((o) => o.label);
    expect(labels).toContain("F2 Zone 1 moisture");
    expect(labels).toContain("F2 Zone 3 EC");
    expect(labels).toContain("F2 Part B stock");
    expect(labels).toContain("F2 Zone 2 back EC silence");
    expect(labels).toContain("F2 controller heartbeat age");
    // Every source the backend has is offered.
    expect(new Set(source.options.map((o) => o.value.split(":")[0]))).toEqual(new Set(RULE_SOURCES.map((s) => s.id)));
  });

  test("picking a source sets what it needs and a threshold in its own unit", () => {
    let next: AlertRule | null = null;
    const source = token(ruleTokens(base, (d) => (next = d), ctx), "source") as Extract<SentenceToken, { kind: "select" }>;
    source.onChange("stock.litres:part_b");
    expect(next).toMatchObject({ source: "stock.litres", tank_id: "part_b", zones: [], unit: "L" });
    expect(next!.entity_id).toBeUndefined();
    source.onChange("zone.ec:2");
    expect(next).toMatchObject({ source: "zone.ec", zones: [2], unit: "mS/cm" });
    expect(next!.tank_id).toBeUndefined();
  });

  test("probe.silence_s token shows minutes and stores seconds", () => {
    let next: AlertRule | null = null;
    const rule: AlertRule = { ...base, source: "probe.silence_s", unit: "s", zones: [], entity_id: "sensor.z2_back_ec", op: "above", threshold: 1800 };
    const threshold = token(ruleTokens(rule, (d) => (next = d), ctx), "threshold") as Extract<SentenceToken, { kind: "number" }>;
    expect(threshold.value).toBe(30);
    expect(threshold.unit).toBe("min");
    threshold.onChange(45);
    expect(next!.threshold).toBe(2700);
  });

  test("EC and the wait follow the display units, stored in mS/cm and seconds", () => {
    setDisplayUnits({ ec: "ppm500" });
    let next: AlertRule | null = null;
    const rule: AlertRule = { ...base, source: "zone.ec", unit: "mS/cm", op: "above", threshold: 6 };
    const parts = ruleTokens(rule, (d) => (next = d), ctx);
    const threshold = token(parts, "threshold") as Extract<SentenceToken, { kind: "number" }>;
    expect([threshold.value, threshold.unit]).toEqual([3000, "ppm"]);
    threshold.onChange(2600);
    expect(next!.threshold).toBe(5.2);
    const wait = token(parts, "wait") as Extract<SentenceToken, { kind: "number" }>;
    expect([wait.value, wait.unit]).toEqual([10, "min"]);
    wait.onChange(15);
    expect(next!.min_duration_s).toBe(900);
  });
});

describe("deliveryLine", () => {
  test("delivery line names each phone", () => {
    const names = { "notify.a": "Ben's phone", "notify.b": "Night phone" };
    expect(
      deliveryLine(
        [
          { service: "notify.a", ok: true, error: null },
          { service: "notify.b", ok: false, error: "held for the phone's digest or quiet hours" },
        ],
        names,
      ),
    ).toBe("Delivered to Ben's phone ✓ · Night phone: not delivered — held for the phone's digest or quiet hours.");
    expect(deliveryLine([{ service: null, ok: false, error: "Notifications are not set up" }], names)).toBe(
      "Not delivered — Notifications are not set up.",
    );
    expect(deliveryLine([{ service: "notify.zz", ok: true, error: null }], names)).toBe("Delivered to notify.zz ✓.");
    expect(deliveryLine([], names)).toBe("No phone got it: none is ticked for Sensors alerts.");
  });
});

describe("review round 1", () => {
  test("saveReceipt words the read-back rule: watching only when it is on", () => {
    expect(saveReceipt({ active: true }, NOW, TZ)).toBe("Saved and watching. Written and read back 14:10.");
    expect(saveReceipt({ active: false }, NOW, TZ)).toBe("Saved (off). Written and read back 14:10.");
  });

  test("Tell token says phones not known when the phone list could not be read", () => {
    expect((token(ruleTokens(base, () => {}, { ...ctx, phones: null }), "tell") as { text: string; href: string })).toMatchObject({
      text: "phones not known",
      href: "#/settings/notifications",
    });
  });

  test("ruleContext: another room's probe by its friendly name and its stock tanks by name", () => {
    const here = { roomId: "room:f2_", zones: [1, 2], probes: [{ id: "sensor.a", name: "A" }] };
    const names = (id: string) => (id === "sensor.b_back_ec" ? "Room B zone 1 back EC" : id);
    const probe = { ...base, room_id: "room:b_", source: "probe.silence_s" as const, zones: [], entity_id: "sensor.b_back_ec" };
    const other = ruleContext(probe, here, { room: "Room B", phones: ["Phone 1"], stocks: [{ id: "part_b", name: "Part B" }], nameOf: names });
    expect(other).toEqual({ room: "Room B", zones: [], phones: ["Phone 1"], stocks: [{ id: "part_b", name: "Part B" }], probes: [{ id: "sensor.b_back_ec", name: "Room B zone 1 back EC" }] });
    const silent = notReporting({ ...item({}), ...probe, current_value: null }, other);
    expect(silent).toBe("Room B Room B zone 1 back EC silence isn't reporting. This rule can't fire until it does.");
    const stock = { ...base, room_id: "room:b_", source: "stock.litres" as const, zones: [], tank_id: "part_b" };
    expect(notReporting({ ...item({}), ...stock, current_value: null }, ruleContext(stock, here, { room: "Room B", phones: [], stocks: [{ id: "part_b", name: "Part B" }], nameOf: names })))
      .toBe("Room B Part B stock isn't reporting. This rule can't fire until it does.");
    const own = ruleContext({ ...base, room_id: "room:f2_" }, here, { room: "F2", phones: null, stocks: [], nameOf: names });
    expect([own.zones, own.probes, own.phones]).toEqual([[1, 2], [{ id: "sensor.a", name: "A" }], null]);
  });

  test("formatRuleValue goes through the display units at a given precision", () => {
    setDisplayUnits({ ec: "ppm500", temp: "F", volume: "gal", clock: "24" });
    expect(formatRuleValue("zone.ec", 4.5, 1)).toBe("2250 ppm");
    expect(formatRuleValue("zone.temperature", 25, 1)).toBe("77.0 °F");
    expect(formatRuleValue("stock.litres", 3.785411784, 1)).toBe("1.0 gal");
    setDisplayUnits({ ec: "mS/cm", temp: "C", volume: "L", clock: "24" });
    expect(formatRuleValue("zone.ec", 4.5, 1)).toBe("4.5 mS/cm");
    expect(formatRuleValue("zone.vwc", 40.1, 1)).toBe("40.1 %");
  });
});

describe("the demo's alert rules", () => {
  afterEach(() => resetDemoAlertRules());
  const call = async (action: "alert_rule_list" | "alert_rule_set" | "alert_rule_preview" | "history_revert", data: Record<string, unknown>) =>
    (await parityDemo(action, data, NOW, "3.18")) as { ok: boolean; data: Record<string, unknown>; event_ids: string[] };

  test("a save is listed with its server sentence and history_revert puts it back", async () => {
    const before = (await call("alert_rule_list", {})).data as { rules: AlertRuleListItem[]; revision: number };
    expect(before.rules).toHaveLength(5);
    const rule = { ...base, id: undefined, room_id: "room:", source: "tank.level", zones: [], threshold: 25 };
    const saved = await call("alert_rule_set", { expected_revision: before.revision, rule });
    expect(saved.ok).toBe(true);
    expect(saved.data.summary_sentence).toBe("Tell when Room A tank level stays below 25% for 10 min.");
    const after = (await call("alert_rule_list", {})).data as { rules: AlertRuleListItem[] };
    expect(after.rules).toHaveLength(6);
    const stale = await call("alert_rule_set", { expected_revision: before.revision, rule });
    expect(stale.ok).toBe(false);
    const reverted = await call("history_revert", { event_id: saved.event_ids[0] });
    expect(reverted.ok).toBe(true);
    expect(((await call("alert_rule_list", {})).data as { rules: unknown[] }).rules).toHaveLength(5);
  });

  test("a preview's sentence follows the threshold", async () => {
    const rule = { ...base, room_id: "room:", zones: [1], threshold: 30 };
    const low = (await call("alert_rule_preview", { rule })).data as { sentence: string; series: unknown[] };
    const high = (await call("alert_rule_preview", { rule: { ...rule, threshold: 60 } })).data as { sentence: string; count: number };
    expect(low.series.length).toBeGreaterThan(100);
    expect(low.sentence).not.toBe(high.sentence);
    expect(high.count).toBeGreaterThan(0);
  });
});
