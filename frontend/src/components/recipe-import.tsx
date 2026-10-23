import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { useParity } from "@/lib/parity-api";
import type { PresetList } from "@/lib/parity-types";
import { importDrafts, importPreview, type ImportReceipt, type ImportRow } from "@/lib/recipe-import";
import { readLibrary, type Recipe } from "@/lib/recipe-library";
import type { Controller } from "@/lib/types";

const RECEIPT_WORDS: Record<ImportReceipt["state"], string> = { saved: "Saved", refused: "Not saved", exists: "Already saved" };

function browserRecipes(roomId: string, demo: boolean): Recipe[] {
  try {
    return readLibrary(window.localStorage, { roomId, demo }).recipes;
  } catch {
    return [];
  }
}

/** Grow plan & presets › Recipes: grow-plan recipes kept only in this browser, imported as presets
 * on the controller with one click (docs/UPGRADING.md#browser-recipes). A preview names every
 * preset first; each is saved on its own, with a receipt per row. Nothing is applied. */
export function RecipeImport({ controller }: { controller: Pick<Controller, "operator" | "roomId" | "demo"> }) {
  // Read after the library beside it has set up its own (a demo library is seeded on mount).
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  useEffect(() => setRecipes(browserRecipes(controller.roomId, controller.demo)), [controller.roomId, controller.demo]);
  const list = useParity<PresetList>(controller, "preset_list", recipes.length ? {} : null, [controller.roomId]);
  const [preview, setPreview] = useState<ImportRow[] | null>(null);
  const [receipts, setReceipts] = useState<ImportReceipt[] | null>(null);
  const [busy, setBusy] = useState(false);
  if (!recipes.length || list.state === "missing" || list.state === "idle") return null;
  const names = (list.data?.presets ?? []).map((preset) => preset.name);
  const fresh = preview?.filter((row) => !row.exists).length ?? 0;

  async function save() {
    if (!preview || !list.data) return;
    setBusy(true);
    setReceipts(await importDrafts(controller, controller.roomId, preview, list.data.revision));
    setBusy(false);
    setPreview(null);
    list.reload();
  }

  return (
    <section className="panel recipe-import" aria-labelledby="recipe-import-title" data-recipe-import>
      <h3 id="recipe-import-title">Import as presets</h3>
      <p className="muted small">
        {recipes.length} recipe{recipes.length === 1 ? " is" : "s are"} saved on this browser only. Import{" "}
        {recipes.length === 1 ? "it" : "them"} as presets on the controller, one for each end (vegetative and
        generative) of each profile, so every browser and phone can use them. Nothing is applied.
      </p>
      {!preview && (
        <Button
          size="sm"
          variant="outline"
          disabled={list.state !== "ready" || busy}
          onClick={() => {
            const now = browserRecipes(controller.roomId, controller.demo);
            setRecipes(now);
            setReceipts(null);
            setPreview(importPreview(now, names));
          }}
        >
          Preview the import
        </Button>
      )}
      {list.state === "error" && (
        <p className="workspace-message error" role="alert">
          The presets could not be read: {list.error}
        </p>
      )}
      {preview && (
        <>
          <table className="recipe-import-table" data-recipe-import-preview>
            <thead>
              <tr>
                <th scope="col">Preset</th>
                <th scope="col">Settings</th>
                <th scope="col">Import</th>
              </tr>
            </thead>
            <tbody>
              {preview.map((row) => (
                <tr key={row.draft.name} data-exists={row.exists ? "" : undefined}>
                  <td>{row.draft.name}</td>
                  <td>{Object.keys(row.draft.values.targets).length}</td>
                  <td>{row.exists ? "Already saved" : "New"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="recipe-library-actions">
            <Button size="sm" disabled={!fresh || busy} onClick={() => void save()}>
              {busy ? "Saving…" : `Save ${fresh} preset${fresh === 1 ? "" : "s"}`}
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>
              Cancel
            </Button>
          </div>
        </>
      )}
      {receipts && (
        <div role="status" aria-label="Import receipts">
          <ul className="recipe-import-receipts">
            {receipts.map((receipt) => (
              <li key={receipt.name} data-receipt={receipt.state}>
                <strong>{RECEIPT_WORDS[receipt.state]}:</strong> {receipt.name}. {receipt.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
