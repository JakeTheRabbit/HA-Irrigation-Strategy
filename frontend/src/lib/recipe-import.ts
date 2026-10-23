import { callV2 } from "./parity-api";
import type { PresetSaved } from "./parity-types";
import type { Recipe } from "./recipe-library";
import type { Controller } from "./types";

/** Grow-plan recipes kept only in a browser (3.17's recipe library) imported as server presets
 * (docs/UPGRADING.md#browser-recipes): one "targets" preset for each end of each profile, saved
 * with preset_save's given `values`, one at a time, never silently and never applied. */

/** A strategy setting the controller holds once per steering mode (strategy_model.MODE_KEYS). */
const MODE_KEYS: Record<string, [string, string]> = {
  dryback_target: ["vegetative_dryback_target", "generative_dryback_target"],
  ec_target_p0: ["ec_target_veg_p0", "ec_target_gen_p0"],
  ec_target_p1: ["ec_target_veg_p1", "ec_target_gen_p1"],
  ec_target_p2: ["ec_target_veg_p2", "ec_target_gen_p2"],
};
const NAME_MAX = 60;

export interface PresetDraft {
  name: string;
  recipe: string;
  values: { targets: Record<string, number> };
}
export interface ImportRow {
  draft: PresetDraft;
  /** The controller already has a preset of this name: it is not saved again. */
  exists: boolean;
}
export interface ImportReceipt {
  name: string;
  state: "saved" | "refused" | "exists";
  message: string;
}

const fit = (head: string, tail: string) =>
  head.length + tail.length <= NAME_MAX ? head + tail : head.slice(0, NAME_MAX - tail.length - 1) + "…" + tail;

/** The presets one recipe gives: for each profile, its vegetative and its generative end. A
 * setting the controller holds per mode takes each mode's value from that mode's end. */
export function recipePresets(recipe: Recipe): PresetDraft[] {
  return recipe.plan.profiles.flatMap((profile) =>
    (["vegetative", "generative"] as const).map((end) => {
      const targets: Record<string, number> = {};
      for (const [key, value] of Object.entries(profile[end])) {
        if (!Number.isFinite(value)) continue;
        const mode = MODE_KEYS[key];
        if (!mode) targets[key] = value;
        else {
          const veg = profile.vegetative[key],
            gen = profile.generative[key];
          if (Number.isFinite(veg)) targets[mode[0]] = veg;
          if (Number.isFinite(gen)) targets[mode[1]] = gen;
        }
      }
      return { name: fit(recipe.name, ` · ${profile.name} · ${end}`), recipe: recipe.name, values: { targets } };
    }),
  );
}

/** What an import would save: every recipe's presets, each marked when the controller has one of
 * that name already. */
export function importPreview(recipes: Recipe[], existing: string[]): ImportRow[] {
  const have = new Set(existing);
  return recipes.flatMap(recipePresets).map((draft) => ({ draft, exists: have.has(draft.name) }));
}

/** Saves each new row, one preset_save at a time from `revision`, and answers a receipt per row.
 * A refused row is said and the next is still tried; the revision follows each save. */
export async function importDrafts(
  controller: Pick<Controller, "operator">,
  roomId: string,
  rows: ImportRow[],
  revision: number,
): Promise<ImportReceipt[]> {
  const receipts: ImportReceipt[] = [];
  let at = revision;
  for (const { draft, exists } of rows) {
    if (exists) {
      receipts.push({ name: draft.name, state: "exists", message: "Already a preset: not saved again." });
      continue;
    }
    const outcome = await callV2<PresetSaved>(controller, "preset_save", {
      name: draft.name,
      scope: "targets",
      from: { room_id: roomId },
      expected_revision: at,
      values: draft.values,
    });
    if (outcome.kind === "ok") {
      at = outcome.data?.revision ?? outcome.revision ?? at + 1;
      receipts.push({ name: draft.name, state: "saved", message: "Saved on the controller. Nothing was applied." });
    } else {
      if (outcome.kind === "error" && outcome.currentRevision !== undefined) at = outcome.currentRevision;
      receipts.push({
        name: draft.name,
        state: "refused",
        message: outcome.kind === "missing" ? "Importing needs Crop Steering 3.18 or newer." : outcome.message,
      });
    }
  }
  return receipts;
}
