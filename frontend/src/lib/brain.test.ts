import { describe, expect, it } from "vitest";
import { formatClock } from "./clock";
import {
  AI_POWERS,
  BRAIN_DEMO_STATES,
  brainView,
  confidenceWords,
  demoBrainEntity,
  keyWords,
  parseBrainPanel,
  parsePowers,
  providerWords,
} from "./brain";
import { SETTING_COPY, UI_COPY } from "./ste-copy";
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
    // The dashboard's one clock (lib/clock.ts), on Home Assistant's time.
    const at = (iso: string) => formatClock(Date.parse(iso));
    expect(words.body).toBe(
      `$1.00 spent at ${at("2026-10-15T14:12:00")}. Rules only until lights-on at ${at("2026-10-16T06:00")}.`,
    );
  });
  it("says when it stopped answering", () => {
    expect(view("unavailable", { fallback_since: "2026-10-15T10:42:00" }).headline).toBe(
      `AI not answering since ${formatClock(Date.parse("2026-10-15T10:42:00"))}`,
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
