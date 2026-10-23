import { describe, expect, it, vi } from "vitest";
import type { GrowPlan } from "./operator-types";
import type { Recipe } from "./recipe-library";
import { importDrafts, importPreview, recipePresets } from "./recipe-import";
import { demoController } from "./test-helpers";

const endpoint = (vwc: number, dryback: number) => ({
  dryback_target: dryback,
  ec_target_p0: 3,
  ec_target_p1: 3.2,
  ec_target_p2: 3.4,
  p1_target_vwc: vwc,
  p2_vwc_threshold: vwc - 8,
  p2_shot_size: 4,
  p1_initial_shot_size: 3,
  p3_emergency_vwc_threshold: 40,
  p3_emergency_shot_size: 2,
});
const plan: GrowPlan = {
  schema_version: 1,
  profiles: [{ id: "flower", name: "Flower", vegetative: endpoint(66, 8), generative: endpoint(60, 18) }],
  zones: [],
};
const recipe: Recipe = { id: "r1", name: "Week 3 flower", notes: "", sourceUrl: "", createdAt: "2026-10-01T00:00:00Z", plan };

describe("importing a browser recipe as presets", () => {
  it("makes one targets preset per end of each profile, mode settings from their own end", () => {
    const drafts = recipePresets(recipe);
    expect(drafts.map((d) => d.name)).toEqual(["Week 3 flower · Flower · vegetative", "Week 3 flower · Flower · generative"]);
    const veg = drafts[0].values.targets;
    expect(veg.p1_target_vwc).toBe(66);
    expect(veg.vegetative_dryback_target).toBe(8);
    expect(veg.generative_dryback_target).toBe(18);
    expect(veg.ec_target_veg_p1).toBe(3.2);
    expect(veg).not.toHaveProperty("dryback_target");
    expect(drafts[1].values.targets.p1_target_vwc).toBe(60);
    for (const d of drafts) expect(d.name.length).toBeLessThanOrEqual(60);
  });
  it("previews what is new and what the controller already has, by name", () => {
    const rows = importPreview([recipe], ["Week 3 flower · Flower · generative"]);
    expect(rows.map((r) => [r.draft.name, r.exists])).toEqual([
      ["Week 3 flower · Flower · vegetative", false],
      ["Week 3 flower · Flower · generative", true],
    ]);
  });
  it("saves each new row on its own and gives a receipt per row", async () => {
    const answers = [
      { api: 2, ok: true, data: { preset: { id: "p1" }, revision: 5, skipped: [] }, revision: 5 },
      { api: 2, ok: false, error: { code: "invalid", message: "p2_shot_size must be a finite number" } },
    ];
    const operator = vi.fn(() => Promise.resolve(answers.shift()));
    const rows = importPreview([recipe], []);
    const receipts = await importDrafts({ operator } as never, "room:f2_", rows, 4);
    expect(receipts.map((r) => [r.name, r.state])).toEqual([
      ["Week 3 flower · Flower · vegetative", "saved"],
      ["Week 3 flower · Flower · generative", "refused"],
    ]);
    expect(receipts[1].message).toContain("finite");
    expect(operator).toHaveBeenNthCalledWith(1, "preset_save", expect.objectContaining({ expected_revision: 4, scope: "targets", from: { room_id: "room:f2_" } }));
    expect(operator).toHaveBeenNthCalledWith(2, "preset_save", expect.objectContaining({ expected_revision: 5 }));
  });
  it("never saves a row the controller already has", async () => {
    const operator = vi.fn();
    const rows = importPreview([recipe], ["Week 3 flower · Flower · vegetative", "Week 3 flower · Flower · generative"]);
    const receipts = await importDrafts({ operator } as never, "room:", rows, 1);
    expect(receipts.every((r) => r.state === "exists")).toBe(true);
    expect(operator).not.toHaveBeenCalled();
  });
  it("the demo saves given values as the integration does", async () => {
    const controller = demoController("?demo=1");
    const list = (await controller.operator<{ api: 2; data: { revision: number } }>("preset_list", { api: 2 })).data;
    const receipts = await importDrafts(controller, "room:", importPreview([recipe], []), list.revision);
    expect(receipts.map((r) => r.state)).toEqual(["saved", "saved"]);
  });
});
