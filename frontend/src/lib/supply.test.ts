import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { ReviewApplyView, type ReviewRow } from "@/components/review-apply";
import { answerSupply, demoCapacityCheck, resetDemoSupply } from "./parity-demo/supply";
import type { V2Outcome } from "./parity-api";
import type { SupplyDoc } from "./parity-types";
import {
  applySupply,
  capacityRefusal,
  flowText,
  parseFlow,
  supplyChecks,
  togetherRows,
  togetherVerdict,
  undoSupply,
  type DripperEdit,
} from "./supply";

const AT = Date.parse("2026-10-22T14:02:00+13:00");

const doc = (check: Partial<SupplyDoc["capacity_check"]>): SupplyDoc => ({
  revision: 4,
  irrigation_pumps: [{ entity_id: "switch.f2_feed_pump", max_flow_lph: 900, max_concurrent_zones: 1, flow_meter: null }],
  water_sources: [],
  zone_groups: { "room:f2_": { "2": "A", "3": "A" } },
  zone_meters: {},
  capacity_check: {
    worst_case_lph: 536,
    max_flow_lph: 900,
    ok: true,
    suggest_max_concurrent: 1,
    pairs: [
      { zones: [1, 2], lph: 1064, pct_of_pump: 118.22222222222223, verdict: "one_after_another" },
      { zones: [1, 3], lph: 840, pct_of_pump: 93.33333333333333, verdict: "one_after_another" },
      { zones: [2, 3], lph: 848, pct_of_pump: 94.22222222222223, verdict: "one_after_another" },
    ],
    ...check,
  },
});

describe("supplyChecks", () => {
  test("supplyChecks warns over-capacity from capacity_check", () => {
    expect(supplyChecks(doc({}))).toEqual([
      { ok: true, text: "Pump max flow 900 L/h is in range" },
      { ok: true, text: "Every zone fits the pump on its own" },
      { ok: "warn", text: "Zones 1 + 2 need 118%: shots queue, one after another" },
    ]);
  });
  test("a pump set to feed more zones at once than it can is a red check", () => {
    const checks = supplyChecks(
      doc({
        ok: false,
        worst_case_lph: 1064,
        suggest_max_concurrent: 1,
        pumps: [
          {
            entity_id: "switch.f2_feed_pump",
            worst_case_lph: 1064,
            max_flow_lph: 900,
            max_concurrent_zones: 2,
            ok: false,
            suggest_max_concurrent: 1,
          },
        ],
      }),
    );
    expect(checks).toContainEqual({ ok: false, text: "Zones at once: more than the pump can feed" });
  });
  test("no max flow: nothing to check", () => {
    expect(supplyChecks(doc({ max_flow_lph: null, pairs: [] }))).toEqual([]);
  });
});

describe("togetherRows", () => {
  test("togetherRows sums demand and flags same group", () => {
    const rows = togetherRows({ "1": 528, "2": 536, "3": 312 }, 900, { "2": "A", "3": "A" });
    expect(rows.map((r) => [r.zones, Math.round(r.pct), r.sameGroup])).toEqual([
      [[1, 2], 118, false],
      [[1, 3], 93, false],
      [[2, 3], 94, true],
      [[1, 2, 3], 153, true],
    ]);
    expect(rows[0].pct).toBeCloseTo((1064 / 900) * 100, 10);
  });
  test("more than four zones: pairs only", () => {
    const rows = togetherRows({ "1": 1, "2": 1, "3": 1, "4": 1, "5": 1 }, 10, {});
    expect(rows).toHaveLength(10);
    expect(rows.every((r) => r.zones.length === 2)).toBe(true);
  });
  test("verdict words", () => {
    const groups = { "2": "A", "3": "A" };
    const [z12, z13, z23] = togetherRows({ "1": 528, "2": 536, "3": 312 }, 900, groups);
    expect(togetherVerdict(z12, groups, 2)).toBe("over the pump: will run one after another");
    expect(togetherVerdict(z13, groups, 2)).toBe("fits: can run together");
    expect(togetherVerdict(z23, groups, 2)).toBe("never together: exclusive group A");
    expect(togetherVerdict(z13, groups, 1)).toBe("one at a time: Zones at once is 1");
  });
});

describe("capacityRefusal", () => {
  test("capacityRefusal parses pump_over_capacity and suggests", () => {
    expect(
      capacityRefusal(
        "pump_over_capacity: switch.f2_feed_pump cannot feed 6 zones at once: the worst mix needs 1100 L/h and the pump gives 900 L/h. Set Zones at once to 5 or less.",
      ),
    ).toEqual({ text: "The pump can't feed 6 zones at once. Set Zones at once to 5 or less.", suggest: 5 });
  });
  test("no suggestion, and other refusals", () => {
    expect(
      capacityRefusal(
        "pump_over_capacity: switch.p cannot feed 2 zones at once: the worst mix needs 9 L/h and the pump gives 1 L/h. Set Zones at once to None or less.",
      ),
    ).toEqual({ text: "The pump can't feed 2 zones at once.", suggest: null });
    expect(capacityRefusal("switch.p: max_flow_lph must be more than 0")).toBeNull();
  });
});

describe("flow units", () => {
  test("litres per hour, never past the source's digits", () => {
    expect(flowText(900, 0)).toBe("900 L/h");
    expect(flowText(3, 1)).toBe("3.0 L/h");
    expect(parseFlow("4.0")).toBe(4);
    expect(parseFlow("4,5")).toBe(4.5);
    expect(parseFlow("")).toBeNull();
    expect(parseFlow("-1")).toBeNull();
  });
});

const row = (id: string, label: string, before: string, after: string): ReviewRow => ({ id, label, before, after });
const ROWS = [row("max_flow", "Pump max flow", "1000 L/h", "900 L/h"), row("dripper:3", "Zone 3 dripper flow", "3.0 L/h", "4.0 L/h")];
const EDITS: DripperEdit[] = [{ zone: 3, before: 3, after: 4, rowId: "dripper:3" }];
const saved: V2Outcome<SupplyDoc> = {
  kind: "ok",
  data: doc({}),
  revision: 5,
  readback: { status: "verified", at: "2026-10-22T14:02:00+13:00" },
  eventIds: ["e1"],
};

describe("applySupply", () => {
  test("two-write apply reports the setup failure only", async () => {
    const order: string[] = [];
    const receipt = await applySupply(
      {
        saveSupply: async () => (order.push("supply_save"), saved),
        saveDrippers: async () => (order.push("setup_save"), { holds: { 3: 3 }, reason: "switch.f2_feed_pump must read OFF" }),
      },
      ROWS,
      EDITS,
      AT,
    );
    expect(order).toEqual(["supply_save", "setup_save"]);
    expect(receipt).toMatchObject({
      ok: false,
      failed: [{ id: "dripper:3", holds: "3.0 L/h", label: "Zone 3 dripper flow" }],
      message: "Pump settings were saved. Zone 3 dripper flow was not: controller still holds 3.0 L/h.",
      summary: "Pump max flow 1000 L/h → 900 L/h",
      eventIds: ["e1"],
    });
  });
  test("both read back: one receipt", async () => {
    const receipt = await applySupply(
      { saveSupply: async () => saved, saveDrippers: async () => ({ holds: { 3: 4 } }) },
      ROWS,
      EDITS,
      AT,
    );
    expect(receipt).toEqual({
      at: AT,
      ok: true,
      failed: [],
      summary: "Pump max flow 1000 L/h → 900 L/h · Zone 3 dripper flow 3.0 L/h → 4.0 L/h",
      eventIds: ["e1"],
    });
  });
  test("a dripper flow not read back is named, not claimed", async () => {
    const receipt = await applySupply(
      { saveSupply: async () => saved, saveDrippers: async () => ({ holds: { 3: null } }) },
      ROWS,
      EDITS,
      AT,
    );
    expect(receipt).toMatchObject({ ok: false, failed: [], notConfirmed: ["dripper:3"] });
    expect("message" in receipt && receipt.message).toBeFalsy();
  });
  test("a refused supply save writes nothing else", async () => {
    let dripper = false;
    const receipt = await applySupply(
      {
        saveSupply: async () => ({
          kind: "error",
          code: "invalid",
          message:
            "pump_over_capacity: switch.f2_feed_pump cannot feed 6 zones at once: the worst mix needs 1100 L/h and the pump gives 900 L/h. Set Zones at once to 5 or less.",
        }),
        saveDrippers: async () => ((dripper = true), { holds: { 3: 4 } }),
      },
      ROWS,
      EDITS,
      AT,
    );
    expect(dripper).toBe(false);
    expect(receipt).toMatchObject({
      ok: false,
      message: "The pump can't feed 6 zones at once. Set Zones at once to 5 or less. Nothing was changed.",
    });
  });
  test("a stale supply save is the refusal itself", async () => {
    const stale = { kind: "error", code: "stale_revision", message: "x", currentRevision: 6 } as const;
    expect(await applySupply({ saveSupply: async () => stale, saveDrippers: null }, ROWS.slice(0, 1), [], AT)).toEqual(stale);
  });
  test("an unverified supply save claims nothing", async () => {
    const receipt = await applySupply(
      { saveSupply: async () => ({ ...saved, readback: { status: "unverified", at: null } }), saveDrippers: async () => ({ holds: { 3: 4 } }) },
      ROWS,
      EDITS,
      AT,
    );
    expect(receipt).toMatchObject({ ok: false, unconfirmed: true });
  });
});

describe("undoSupply", () => {
  test("puts back the pump, then the drippers; k of n when one stops", async () => {
    await expect(
      undoSupply({ saveSupply: async () => saved, saveDrippers: async () => ({ holds: { 3: 4 }, reason: "Zone 3 dripper flow changed since." }) }, [
        { zone: 3, before: 4, after: 3, rowId: "dripper:3" },
      ]),
    ).rejects.toMatchObject({ reverted: 1, total: 2, message: "1 of 2 put back: Zone 3 dripper flow changed since." });
    await expect(
      undoSupply({ saveSupply: async () => saved, saveDrippers: async () => ({ holds: { 3: 3 } }) }, [
        { zone: 3, before: 4, after: 3, rowId: "dripper:3" },
      ]),
    ).resolves.toBeUndefined();
  });
  test("a refused supply undo changes nothing", async () => {
    await expect(
      undoSupply({ saveSupply: async () => ({ kind: "error", code: "stale_revision", message: "Supply settings changed elsewhere. Reload before saving." }), saveDrippers: null }, []),
    ).rejects.toMatchObject({ reverted: 0, total: 1, message: "Supply settings changed elsewhere. Reload before saving." });
  });
});

describe("the demo supply", () => {
  test("works out the check as the integration does, and refuses a pump over capacity", () => {
    const rooms = [{ room_id: "room:f2_", pump: "switch.p", zones: { "1": 528, "2": 536, "3": 312 } }];
    const section = {
      irrigation_pumps: [{ entity_id: "switch.p", max_flow_lph: 900, max_concurrent_zones: 2, flow_meter: null }],
      water_sources: [],
      zone_groups: { "room:f2_": { "2": "A", "3": "A" } },
      zone_meters: {},
    };
    const check = demoCapacityCheck(section, rooms);
    expect(check).toMatchObject({ ok: false, worst_case_lph: 1064, suggest_max_concurrent: 1 });
    expect(check.pairs.map((p) => [p.zones, p.verdict])).toEqual([
      [[1, 2], "one_after_another"],
      [[1, 3], "together"],
      [[2, 3], "one_after_another"],
    ]);
    resetDemoSupply();
    const refused = answerSupply("supply_save", { ...section, expected_revision: 1 }, rooms, {}, AT);
    expect(refused.answer).toMatchObject({ api: 2, ok: false, error: { code: "invalid" } });
    const message = (refused.answer as { error: { message: string } }).error.message;
    expect(capacityRefusal(message)).toEqual({ text: "The pump can't feed 2 zones at once. Set Zones at once to 1 or less.", suggest: 1 });
    const saved = answerSupply(
      "supply_save",
      { ...section, irrigation_pumps: [{ ...section.irrigation_pumps[0], max_concurrent_zones: 1 }], expected_revision: 1 },
      rooms,
      {},
      AT,
    );
    expect(saved.answer).toMatchObject({ revision: 2, readback: { status: "ok" } });
    expect(saved.states?.["sensor.crop_steering_supply_config"]?.attributes.zone_demand_lph).toEqual({ "room:f2_": rooms[0].zones });
  });
});

describe("the review panel", () => {
  test("a page's own failure sentence, with Try again", () => {
    const html = renderToStaticMarkup(
      createElement(ReviewApplyView, {
        rows: ROWS.slice(1),
        layout: "panel",
        apply: () => Promise.resolve({ kind: "missing" as const }),
        onDiscard: () => {},
        timeZone: "Pacific/Auckland",
        state: {
          phase: "done",
          result: {
            at: AT,
            ok: false,
            failed: [{ id: "dripper:3", holds: "3.0 L/h", label: "Zone 3 dripper flow" }],
            message: "Pump settings were saved. Zone 3 dripper flow was not: controller still holds 3.0 L/h.",
            summary: "Pump max flow 1000 L/h → 900 L/h",
            eventIds: [],
          },
        },
      }),
    );
    expect(html).toContain("Pump settings were saved. Zone 3 dripper flow was not: controller still holds 3.0 L/h.");
    expect(html).toContain("Try again");
    expect(html).not.toContain("Written and read back");
  });
});
