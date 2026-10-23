import { describe, expect, it } from "vitest";
import {
  AI_POWERS,
  aiPowerId,
  BRAIN_DEMO_STATES,
  brainView,
  confidenceWords,
  demoBrainEntity,
  judgeCount,
  judgeMatrix,
  judgeTitle,
  keyWords,
  listWords,
  modelKey,
  outcomes,
  outcomesFromLog,
  parseBrainPanel,
  parsePowers,
  providerWords,
} from "./brain";
import { parseControllerTime } from "./controller-health";
import { createDemo } from "./demo";
import { buildRoom, discoverRooms, validateChange } from "./model";
import type { CsEvent } from "./parity-types";
import { SETTING_COPY, UI_COPY } from "./ste-copy";
import type { JevEntry } from "./jev";
import type { EntityState } from "./types";

const sensor = (state: string, attributes: Record<string, unknown>): EntityState => ({
  entity_id: "sensor.crop_steering_jev",
  state,
  attributes,
  last_updated: "2026-10-15T00:00:00Z",
  last_changed: "2026-10-15T00:00:00Z",
});
const view = (state: string, extra: Record<string, unknown> = {}, flags = {}) =>
  brainView(parseBrainPanel(sensor("on", { state, ...extra })), flags);

describe("each brain state in grower words", () => {
  it.each([
    ["rules", "AI off", "Watering by rules", "neutral"],
    ["acting", "AI acting", "AI assistant is acting", "positive"],
    ["dry_run", "AI advising", "AI assistant is advising only", "info"],
    ["legacy", "AI acting", "AI assistant on the first AI route", "info"],
    ["budget_spent", "AI paused: budget", "Daily AI limit reached", "warning"],
    ["paused", "AI paused: not answering", "AI not answering", "warning"],
    ["unavailable", "AI paused: not answering", "AI not answering", "warning"],
    ["rules_no_key", "AI paused: no key", "No working Anthropic key", "warning"],
    ["auth_failed", "AI paused: no key", "No working Anthropic key", "warning"],
    ["model_invalid", "AI off", "This release does not know that model's price", "warning"],
    ["sdk_missing", "AI off", "Not available on this device", "neutral"],
    ["brain_off", "AI off", "AI assistant off", "neutral"],
    ["start_failed", "AI off", "AI assistant off", "warning"],
  ])("%s: %s, %s", (state, chip, headline, tone) => {
    const words = view(state);
    expect(words.chip).toBe(chip);
    expect(words.headline).toBe(headline);
    expect(words.tone).toBe(tone);
    expect(words.body).not.toBe("");
    // No engine token in what a grower reads.
    expect(`${words.chip} ${words.headline} ${words.body}`).not.toMatch(/_|\bp[0-3]\b|vwc|pwec/i);
  });
  it("says every fallback ends in rules, never in red", () => {
    for (const state of ["budget_spent", "paused", "rules_no_key", "auth_failed"])
      expect(view(state).body).toMatch(/[Rr]ules/);
  });
  it("names the spend and the next lights-on when the budget is spent", () => {
    const words = view("budget_spent", {
      spent_usd: 1,
      fallback_since: "2026-10-15T14:12:00",
      resets_at: "2026-10-16T06:00",
    });
    expect(words.body).toBe("$1.00 spent at 14:12. Rules only until lights-on at 06:00.");
  });
  it("says when it stopped answering", () => {
    expect(view("unavailable", { fallback_since: "2026-10-15T10:42:00" }).headline).toBe(
      "AI not answering since 10:42",
    );
  });
  it("adds a line for the judges it would not answer", () => {
    expect(view("acting", { declined: ["night"] }).declined).toBe(
      "It would not answer the night low check 3 times in a row; rules decide that one.",
    );
    expect(view("acting").declined).toBeNull();
  });
  it("pauses on stale readings and idles with watering off, only while it could judge", () => {
    expect(view("acting", {}, { stale: true }).headline).toBe("Readings too old to judge");
    expect(view("dry_run", {}, { wateringOff: true }).chip).toBe("AI idle");
    expect(view("rules_no_key", {}, { stale: true }).headline).toBe("No working Anthropic key");
  });
  it("reads a sensor from a controller before the panel by its entity state", () => {
    expect(parseBrainPanel(sensor("on", { calls_today: 3 }))!.state).toBe("legacy");
    expect(parseBrainPanel(sensor("rules", {}))!.state).toBe("rules");
    expect(parseBrainPanel(sensor("error", {}))!.state).toBe("unavailable");
    expect(brainView(null).headline).toBe("Watering by rules");
  });
});

describe("the key", () => {
  const SECRET = "sk-ant-api03-SENTINEL-never-shown";
  const leaky = sensor("on", {
    state: "auth_failed",
    key_set: true,
    anthropic_api_key: SECRET,
    api_key: SECRET,
    key: SECRET,
    last_error: `401 for ${SECRET}`,
  });
  it("reads only key_set: no attribute named like a key reaches the panel or its words", () => {
    const panel = parseBrainPanel(leaky)!;
    expect(JSON.stringify(panel)).not.toContain("SENTINEL");
    const words = brainView(panel);
    expect(JSON.stringify([words, keyWords(panel), providerWords(panel)])).not.toContain(
      "SENTINEL",
    );
  });
  it("says whether one is saved, or refused", () => {
    expect(keyWords(parseBrainPanel(sensor("on", { state: "acting", key_set: true })))).toBe(
      "Saved in the controller",
    );
    expect(keyWords(parseBrainPanel(sensor("rules", { state: "rules", key_set: false })))).toBe(
      "Not set",
    );
    expect(keyWords(parseBrainPanel(leaky))).toBe(
      "Rejected by Anthropic (check it was copied whole)",
    );
  });
});

describe("the rest of the panel", () => {
  it("names the provider in words", () => {
    expect(providerWords(parseBrainPanel(sensor("on", { provider: "claude_haiku" })))).toBe(
      "Claude Haiku (Anthropic)",
    );
    expect(providerWords(parseBrainPanel(sensor("on", { provider: "jev_legacy" })))).toMatch(
      /^First AI route \(removed\)/,
    );
  });
  it("says how sure the last decision was", () => {
    expect(confidenceWords(0.78, true)).toBe(
      "Fairly sure: both readings of the question agreed, 0.78",
    );
    expect(confidenceWords(null, true)).toBe("");
  });
  it("gives the demo one panel state for each of its seven choices", () => {
    const chips = BRAIN_DEMO_STATES.map(([state]) =>
      brainView(parseBrainPanel(demoBrainEntity(state, undefined)), { stale: state === "stale" }),
    ).map((words) => words.headline);
    expect(new Set(chips).size).toBe(7);
  });
});

describe("the grow plan line", () => {
  it("reads the plan's headline and its drifts, and nothing with no plan", () => {
    const panel = parseBrainPanel(
      sensor("rules", {
        state: "rules",
        plan: {
          status: "active",
          headline: "Plan: Autumn run · day 17 of 84 (week 3) · on track",
          bridged: false,
          drifts: [
            { class: "shadowed_edit", zone: 2, line: "a change", suggestion: "Change the plan's days", why: "" },
            { class: "x", zone: "junk", line: "" },
          ],
        },
      }),
    );
    expect(panel?.plan?.headline).toBe("Plan: Autumn run · day 17 of 84 (week 3) · on track");
    expect(panel?.plan?.drifts).toEqual([
      {
        kind: "shadowed_edit",
        zone: 2,
        line: "a change",
        suggestion: "Change the plan's days",
        why: "",
        action: "advise",
      },
    ]);
    expect(parseBrainPanel(sensor("rules", { plan: { status: "none", headline: null } }))?.plan).toBe(
      null,
    );
    expect(parseBrainPanel(sensor("rules", {}))?.plan).toBe(null);
  });
});

describe("what the AI assistant may do", () => {
  const sw = (entity_id: string, state: string): EntityState => ({
    entity_id,
    state,
    attributes: {},
    last_updated: "2026-10-15T00:00:00Z",
    last_changed: "2026-10-15T00:00:00Z",
  });
  const keys = [
    "advance_phase",
    "ramp_control",
    "set_probe_aside",
    "ec_mode",
    "nudge_setpoints",
    "plan_catch_up",
    "set_targets_from_achievable",
    "tune_shot_sizes",
  ];
  it("reads the 8 powers in the integration's order from the room's switches", () => {
    const states = {
      "switch.crop_steering_tent_ai_power_advance_phase": sw("x", "off"),
      "switch.crop_steering_tent_ai_power_tune_shot_sizes": sw("x", "on"),
      // Another room's switch is not this room's.
      "switch.crop_steering_ai_power_ec_mode": sw("x", "off"),
    };
    const powers = parsePowers(states, "tent_");
    expect(powers.map((p) => p.key)).toEqual(keys);
    expect(powers[0]).toEqual({
      key: "advance_phase",
      label: "Start the next phase early",
      entityId: "switch.crop_steering_tent_ai_power_advance_phase",
      on: false,
      default: true,
      missing: false,
    });
    expect(powers[7]).toMatchObject({ on: true, default: false, missing: false });
    // ec_mode's switch is missing in this room: its default, read-only.
    expect(powers[3]).toMatchObject({
      entityId: "switch.crop_steering_tent_ai_power_ec_mode",
      on: true,
      missing: true,
    });
  });
  it("shows each default, read-only, for an integration without the switches or an unavailable one", () => {
    const powers = parsePowers(
      { "switch.crop_steering_ai_power_ramp_control": sw("x", "unavailable") },
      "",
    );
    expect(powers.every((p) => p.missing)).toBe(true);
    expect(powers.map((p) => p.on)).toEqual([true, true, true, true, true, true, false, false]);
    expect(powers.map((p) => p.entityId)).toEqual(
      keys.map((key) => `switch.crop_steering_ai_power_${key}`),
    );
  });
  it("has one line of help for each power, and short plain labels with no entity ids", () => {
    for (const power of AI_POWERS) {
      const help = SETTING_COPY[`ai_power_${power.key}`]?.tooltip ?? "";
      expect(help, power.key).not.toBe("");
      expect(`${power.label} ${help}`, power.key).not.toMatch(/_|switch\.|sensor\./);
    }
    expect(UI_COPY["what the ai assistant may do"].tooltip).toBe(
      "When a power is off, the AI assistant only advises. It does not change that part.",
    );
  });
});

describe("the judges matrix", () => {
  const rooms = [
    { id: "room:", name: "F2", prefix: "" },
    { id: "room:f1_", name: "F1", prefix: "f1_" },
  ];
  const entity = (
    entity_id: string,
    state: string,
    attributes: Record<string, unknown> = {},
  ): EntityState => ({
    entity_id,
    state,
    attributes,
    last_updated: "2026-10-22T00:00:00Z",
    last_changed: "2026-10-22T00:00:00Z",
  });
  const states = Object.fromEntries(
    [
      ...AI_POWERS.map((p) => entity(aiPowerId("", p.key), "on")),
      entity(aiPowerId("f1_", "advance_phase"), "on"),
      entity(aiPowerId("f1_", "ec_mode"), "on"),
      entity(aiPowerId("f1_", "set_targets_from_achievable"), "off"),
      entity("switch.crop_steering_f1_ec_stacking_enabled", "off"),
      entity("sensor.crop_steering_jev", "on", {
        judges: ["dawn", "ramp", "salt", "dusk", "setpoints", "shot", "channel", "stage"],
      }),
      entity("sensor.crop_steering_f1_jev", "on", { judges: ["dawn", "salt", "shot"] }),
    ].map((e) => [e.entity_id, e]),
  );

  it("judgeMatrix maps per-room switches and notes", () => {
    const matrix = judgeMatrix(states, rooms);
    const row = (id: string) => matrix.find((r) => r.id === id)!;
    // A judge that can act is its power's switch, in each room.
    expect(row("dawn")).toMatchObject({ name: "Morning start", power: "act" });
    expect(row("dawn").perRoom["room:"]).toEqual({
      on: true,
      entityId: aiPowerId("", "advance_phase"),
    });
    expect(row("targets").perRoom["room:f1_"]).toEqual({
      on: false,
      entityId: aiPowerId("f1_", "set_targets_from_achievable"),
    });
    // Two judges share one power: each row says so.
    expect(row("dawn").shares).toBe("Day end");
    expect(row("dusk").shares).toBe("Morning start");
    // Pore EC never asks where EC stacking is off.
    expect(row("salt").perRoom["room:f1_"]).toEqual({
      on: false,
      entityId: aiPowerId("f1_", "ec_mode"),
      note: "stacking off",
    });
    // No switch in a room: said, never shown as on or off.
    expect(row("probe").perRoom["room:f1_"]).toEqual({ on: false, entityId: null, note: "No switch" });
    // Alert and advice judges have no switch: asked or not, as the controller publishes it.
    expect(row("channel")).toMatchObject({ name: "Water path", power: "alerts" });
    expect(row("channel").perRoom["room:"]).toEqual({
      on: true,
      entityId: null,
      note: "Set in the controller app",
    });
    expect(row("channel").perRoom["room:f1_"]).toEqual({
      on: false,
      entityId: null,
      note: "Set in the controller app",
    });
    expect(row("stage").power).toBe("advice");
    // A judge the room's list leaves out is not asked there, whatever its switch says (ai_judges).
    expect(row("probe").perRoom["room:"]).toEqual({ on: false, entityId: null, note: "Not asked" });
    expect(row("dusk").perRoom["room:f1_"]).toEqual({ on: false, entityId: null, note: "Not asked" });
    // Targets and Shot sizes are always asked; the grow plan is never in the list: their switches decide.
    expect(row("targets").perRoom["room:"]).toMatchObject({ on: true, entityId: aiPowerId("", "set_targets_from_achievable") });
    expect(row("shotsize").perRoom["room:"]).toMatchObject({ on: true, entityId: aiPowerId("", "tune_shot_sizes") });
    expect(row("plan").perRoom["room:"]).toMatchObject({ on: true, entityId: aiPowerId("", "plan_catch_up") });
    // ...but the controller builds the plan task only when ai_judges names plan: the switch says so.
    expect(row("plan").hint).toMatch(/ai_judges/);
    expect(row("targets").hint).toBeUndefined();
    // A room that publishes no judge list.
    expect(
      judgeMatrix({}, rooms.slice(0, 1)).find((r) => r.id === "shot")!.perRoom["room:"],
    ).toEqual({ on: false, entityId: null, note: "Not reported" });
  });

  it("names each judge once, as the controller titles it", () => {
    const matrix = judgeMatrix(states, rooms);
    for (const row of matrix) expect(row.name, row.id).toBe(judgeTitle(row.id));
    expect(judgeTitle("ramp")).toBe("Ramp hand-over");
    expect(judgeTitle("stage")).toBe("Stage arc");
    expect(judgeTitle("balance")).toBe("Room balance");
  });

  it("counts k of n over the cells with a known state", () => {
    // Not asked, no switch and stacking off are left out of n.
    expect(judgeCount(judgeMatrix(states, rooms))).toEqual({ on: 13, of: 22 });
  });
});

describe("what it did, and what happened", () => {
  const event = (
    id: string,
    ts: string,
    kind: string,
    data: Record<string, unknown>,
    extra: Partial<CsEvent> = {},
  ): CsEvent => ({
    v: 1,
    id,
    ts,
    room_id: "room:",
    zone: 2,
    kind,
    outcome: "ok",
    code: null,
    source: { actor: "ai", detail: String(data.judge ?? "") },
    data,
    ...extra,
  });
  const ledger = (id: string) => ({ correlation: { ledger_id: id } });

  it("outcomes verdict from ai.outcome", () => {
    const rows = outcomes([
      event("01A", "2026-10-21T02:14:00Z", "ai.judgement", { judge: "setpoints", label: "Raised the P2 re-water point", action: "setpoint" }, ledger("7")),
      event("01B", "2026-10-22T02:14:00Z", "ai.outcome", { what: "Dryback back in band", good: true }, ledger("7")),
      event("01C", "2026-10-21T22:41:00Z", "ai.judgement", { judge: "shotsize", label: "Cut the maintenance shot", action: "shot_size" }, { zone: 1, ...ledger("8") }),
      event("01D", "2026-10-20T02:30:00Z", "ai.judgement", { judge: "setpoints", label: "Lowered the maintenance shot", action: "setpoint" }, ledger("5")),
      event("01E", "2026-10-21T02:30:00Z", "ai.outcome", { what: "Dryback overshot", good: false, band: [18, 22], value: 24.1 }, ledger("5")),
      event("01F", "2026-10-21T03:00:00Z", "ai.judgement", { judge: "dawn", label: "Start early", action: "refused" }, { outcome: "refused", ...ledger("9") }),
    ]);
    expect(rows.map((r) => [r.judge, r.verdict, r.result])).toEqual([
      // Shot sizes has no scheduled check (outcome_after_min): nothing will measure it.
      ["shotsize", "not checked", ""],
      ["setpoints", "worked", "Dryback back in band"],
      ["setpoints", "did not work", "Dryback overshot"],
    ]);
    expect(rows[1]).toMatchObject({
      roomId: "room:",
      zone: 2,
      text: "Raised the P2 re-water point",
      band: null,
      value: null,
      at: Date.parse("2026-10-21T02:14:00Z"),
    });
    // A band is drawn only from numbers the controller sent.
    expect(rows[2]).toMatchObject({ band: [18, 22], value: 24.1 });
  });

  it("measures only judges the controller checks later; alerts and unchecked actions say Not checked", () => {
    const rows = outcomes([
      // ramp, salt, dusk, setpoints, targets (outcome_after_min) and plan (6 h) are checked.
      ...["ramp", "salt", "dusk", "setpoints", "targets", "plan"].map((judge, i) =>
        event(`02${i}`, `2026-10-22T0${i}:00:00Z`, "ai.judgement", { judge, label: judge, action: "setpoint" }, ledger(`c${i}`)),
      ),
      // Alerts and the other acting judges are never checked.
      ...["channel", "night", "stage", "zones", "dawn", "probe", "shotsize"].map((judge, i) =>
        event(`03${i}`, `2026-10-22T1${i}:00:00Z`, "ai.judgement", { judge, label: judge, action: i < 4 ? "alert" : "setpoint" }, ledger(`u${i}`)),
      ),
    ]);
    expect(Object.fromEntries(rows.map((r) => [r.judge, r.verdict]))).toEqual({
      ramp: "measuring",
      salt: "measuring",
      dusk: "measuring",
      setpoints: "measuring",
      targets: "measuring",
      plan: "measuring",
      channel: "not checked",
      night: "not checked",
      stage: "not checked",
      zones: "not checked",
      dawn: "not checked",
      probe: "not checked",
      shotsize: "not checked",
    });
  });

  it("pairs an outcome without a ledger id with the next one in the same room, zone and judge", () => {
    const rows = outcomes([
      event("01A", "2026-10-22T07:30:00Z", "ai.judgement", { judge: "ramp", label: "Ended the ramp", action: "setpoint" }, { zone: 1 }),
      event("01C", "2026-10-22T08:00:00Z", "ai.outcome", { what: "Another zone", good: false }, { zone: 3, source: { actor: "ai", detail: "ramp" } }),
      event("01D", "2026-10-22T09:00:00Z", "ai.outcome", { what: "Another judge", good: false }, { zone: 1, source: { actor: "ai", detail: "salt" } }),
      event("01B", "2026-10-22T10:00:00Z", "ai.outcome", { what: "Peak reached in band.", good: true }, { zone: 1, source: { actor: "ai", detail: "ramp" } }),
    ]);
    expect(rows.map((r) => [r.verdict, r.result])).toEqual([["worked", "Peak reached in band."]]);
  });

  it("reads the 3.17 ledger: decisions and the outcome that names them", () => {
    const entry = (over: Partial<JevEntry>): JevEntry => ({
      key: "k",
      time: 0,
      stamp: "",
      of: "",
      zone: 1,
      judge: "dawn",
      title: "Morning start",
      kind: "decision",
      verdict: "",
      p: null,
      agreed: null,
      action: "",
      result: "acted",
      resultText: "acted",
      reason: "",
      ...over,
    });
    const rows = outcomesFromLog(
      [
        entry({ key: "a", time: 2000, stamp: "t2", of: "t1", kind: "outcome", verdict: "Peak reached in band", result: "worked" }),
        entry({ key: "b", time: 1000, stamp: "t1", action: "Started the ramp sooner" }),
        entry({ key: "c", time: 900, stamp: "t0", zone: 2, judge: "salt", result: "refused" }),
        entry({ key: "e", time: 800, stamp: "s0", zone: 2, judge: "salt", action: "Diluted" }),
        entry({ key: "f", time: 700, stamp: "p0", zone: 2, judge: "probe", action: "Held the probe" }),
      ],
      "room:",
    );
    // A controller before 3.4 names the decision by its time, not its stamp.
    const at = parseControllerTime("2026-10-22T07:30:00")!;
    expect(
      outcomesFromLog(
        [
          entry({ key: "o", time: at + 3_600_000, stamp: "x2", of: "2026-10-22T07:30", kind: "outcome", verdict: "Ramp ended in band", result: "worked" }),
          entry({ key: "d", time: at, stamp: "x1", action: "Ended the ramp" }),
        ],
        "room:",
      )[0],
    ).toMatchObject({ result: "Ramp ended in band", verdict: "worked" });
    expect(rows).toEqual([
      expect.objectContaining({
        judge: "dawn",
        text: "Started the ramp sooner",
        result: "Peak reached in band",
        verdict: "worked",
        at: 1000,
      }),
      expect.objectContaining({ judge: "salt", verdict: "measuring" }),
      expect.objectContaining({ judge: "probe", verdict: "not checked" }),
    ]);
  });
});

describe("model and room names", () => {
  it("names the model only by its exact priced id, after a router prefix too", () => {
    expect(modelKey("claude-haiku-5-5")).toBe("claude-haiku-5-5");
    expect(modelKey("openrouter/claude-sonnet-5-5")).toBe("claude-sonnet-5-5");
    expect(modelKey("claude-opus-5-5")).toBe("claude-opus-5-5");
    expect(modelKey("claude-haiku-4-5")).toBeNull();
    expect(modelKey("")).toBeNull();
  });

  it("lists room names as a sentence", () => {
    expect(listWords(["Room A"])).toBe("Room A");
    expect(listWords(["Room A", "Room B"])).toBe("Room A and Room B");
    expect(listWords(["Room A", "Room B", "Room C"])).toBe("Room A, Room B, and Room C");
  });
});

describe("judge switches of any room pass the write check", () => {
  it("accepts another room's AI power switch, nothing else of that room", () => {
    const states = createDemo(Date.parse("2026-10-22T01:00:00Z"));
    const other = aiPowerId("room_b_", "ec_mode");
    states[other] = { ...states[aiPowerId("", "ec_mode")], entity_id: other };
    const roomA = discoverRooms(states).find((r) => r.prefix === "")!;
    const view = buildRoom(states, roomA);
    expect(validateChange(view, states, { entityId: other, value: false })).toBeNull();
    expect(
      validateChange(view, states, {
        entityId: "switch.crop_steering_room_b_auto_setpoints",
        value: false,
      }),
    ).not.toBeNull();
  });
});
