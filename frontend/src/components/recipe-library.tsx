import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { BookOpen, Download, Plus, Trash2, Upload, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { GrowPlan } from "@/lib/operator-types";
import {
  exportRecipe,
  importRecipePlan,
  libraryKey,
  MAX_PLAN_BYTES,
  MAX_RECIPES,
  prepareRecipeDraft,
  readLibrary,
  removeRecipe,
  saveRecipe,
  type LibrarySnapshot,
  type Recipe,
  type RecipeCatalog,
} from "@/lib/recipe-library";
import "./recipe-library.css";

type LibraryDialog =
  | { kind: "save"; plan: GrowPlan; imported: boolean }
  | { kind: "preview" | "remove"; recipe: Recipe };
export interface RecipeLibraryProps {
  roomId: string;
  roomName: string;
  demo: boolean;
  plan: GrowPlan;
  catalog: RecipeCatalog;
  activeZoneIds: number[];
  canLoad: boolean;
  dirty: boolean;
  onLoad: (plan: GrowPlan) => void;
  onDirtyChange?: (dirty: boolean) => void;
}
const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error));
function download(text: string, name: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function RecipeLibrary({
  roomId,
  roomName,
  demo,
  plan,
  catalog,
  activeZoneIds,
  canLoad,
  dirty,
  onLoad,
  onDirtyChange,
}: RecipeLibraryProps) {
  const scope = { roomId, demo };
  const key = libraryKey(scope);
  const [library, setLibrary] = useState<LibrarySnapshot | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState<LibraryDialog | null>(null);
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [source, setSource] = useState("");
  const [replace, setReplace] = useState(false);
  const [reading, setReading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const scopeRef = useRef(key);
  scopeRef.current = key;
  const readGeneration = useRef(0);
  useLayoutEffect(() => {
    onDirtyChange?.(dialog?.kind === "save");
    return () => onDirtyChange?.(false);
  }, [dialog?.kind, onDirtyChange]);
  function reload() {
    try {
      setLibrary(readLibrary(window.localStorage, scope));
      setError("");
    } catch (e) {
      setError(`Recipe storage is unavailable. ${errorText(e)}`);
      setLibrary(null);
    }
  }
  useEffect(() => {
    setDialog(null);
    setLibrary(null);
    setNotice("");
    setReading(false);
    reload();
    const changed = (event: StorageEvent) => {
      if (event.key === key || event.key === null)
        setError(
          "The recipe library changed in another tab. Reload it before saving or removing recipes.",
        );
    };
    window.addEventListener("storage", changed);
    return () => {
      readGeneration.current++;
      window.removeEventListener("storage", changed);
    };
  }, [key]);
  const available = library?.key === key ? library : null;
  const storageError = available?.error;
  const blocked = !available || !!storageError;
  function openSave(candidate: GrowPlan, imported = false) {
    setName("");
    setNotes("");
    setSource("");
    setError("");
    setNotice("");
    setDialog({ kind: "save", plan: structuredClone(candidate), imported });
  }
  async function importFile(file?: File) {
    if (!file) return;
    const generation = ++readGeneration.current,
      startedKey = key;
    setError("");
    setReading(true);
    try {
      if (file.size > MAX_PLAN_BYTES) throw new Error("Plan file is too large (maximum 500 KB).");
      const candidate = importRecipePlan(await file.text());
      if (generation !== readGeneration.current || scopeRef.current !== startedKey) return;
      openSave(candidate, true);
    } catch (e) {
      if (generation === readGeneration.current && scopeRef.current === startedKey)
        setError(errorText(e));
    } finally {
      if (generation === readGeneration.current && scopeRef.current === startedKey)
        setReading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }
  let candidate: GrowPlan | null = null,
    validation = "";
  if (dialog?.kind === "preview" || dialog?.kind === "save") {
    try {
      candidate = prepareRecipeDraft(
        dialog.kind === "save" ? dialog.plan : dialog.recipe.plan,
        plan,
        catalog,
        activeZoneIds,
      );
    } catch (e) {
      validation = errorText(e);
    }
  }
  function persistRecipe() {
    if (!available || dialog?.kind !== "save" || !candidate || validation) return;
    try {
      // Keep original recipe dates as metadata. Only load adapts dates to the current grow.
      setLibrary(
        saveRecipe(window.localStorage, available, {
          name,
          notes,
          sourceUrl: source,
          plan: dialog.plan,
        }),
      );
      setDialog(null);
      setError("");
      setNotice("Recipe saved in this browser for this room. Home Assistant was not changed.");
    } catch (e) {
      setError(errorText(e));
    }
  }
  function loadRecipe() {
    if (dialog?.kind !== "preview" || !canLoad || !candidate || validation || (dirty && !replace))
      return;
    try {
      const prepared = prepareRecipeDraft(dialog.recipe.plan, plan, catalog, activeZoneIds);
      onLoad(prepared);
      setDialog(null);
      setError("");
      setNotice("Recipe loaded into the local draft. Review and save in the planner when ready.");
    } catch (e) {
      setError(errorText(e));
    }
  }
  function deleteRecipe() {
    if (!available || dialog?.kind !== "remove") return;
    try {
      setLibrary(removeRecipe(window.localStorage, available, dialog.recipe.id));
      setDialog(null);
      setError("");
      setNotice("Recipe removed from this browser library.");
    } catch (e) {
      setError(errorText(e));
    }
  }
  const message = error || storageError;
  return (
    <>
      <details className="panel recipe-library" data-recipe-library>
        <summary>
          <BookOpen size={18} />
          <strong>Recipe library</strong>
          <span>{available?.recipes.length ?? 0} saved</span>
        </summary>
        <div className="recipe-library-body">
          <p className="muted small">
            Your own reusable plans for {roomName}. Stored only in this browser
            {demo ? " · demo library" : ""}; export copies to keep a backup. The library starts
            empty.
          </p>
          <div className="recipe-library-actions">
            <Button
              variant="outline"
              size="sm"
              onClick={() => openSave(plan)}
              disabled={blocked || reading}
            >
              <Plus size={15} />
              Save current as recipe
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileRef.current?.click()}
              disabled={blocked || reading}
            >
              <Upload size={15} />
              {reading ? "Reading file…" : "Import recipe file"}
            </Button>
            <Button variant="ghost" size="sm" onClick={reload}>
              <RefreshCw size={15} />
              Reload library
            </Button>
            {available?.raw && storageError && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => download(available.raw!, "recipe-library-recovery.json")}
              >
                Download stored data
              </Button>
            )}
          </div>
          <input
            className="sr-only"
            type="file"
            accept="application/json,.json"
            aria-label="Import recipe file"
            ref={fileRef}
            onChange={(event) => void importFile(event.target.files?.[0])}
          />
          {message && (
            <p className="workspace-message error" role="alert">
              {message}
            </p>
          )}
          {notice && (
            <p className="workspace-message" role="status">
              {notice}
            </p>
          )}
          {!blocked && !available.recipes.length && (
            <p className="recipe-empty">
              No saved recipes yet. Save a plan you have configured or import your own plan export.
            </p>
          )}
          {!!available?.recipes.length && (
            <ul className="recipe-list">
              {available.recipes.map((recipe) => (
                <li key={recipe.id}>
                  <div>
                    <strong>{recipe.name}</strong>
                    <span>
                      {recipe.plan.zones.length} zones · {recipe.plan.profiles.length} profiles ·
                      saved {new Date(recipe.createdAt).toLocaleDateString()}
                    </span>
                  </div>
                  <div className="recipe-list-actions">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setDialog({ kind: "preview", recipe });
                        setReplace(false);
                        setError("");
                      }}
                    >
                      Preview recipe<span className="sr-only"> {recipe.name}</span>
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        download(exportRecipe(recipe, roomName), "crop-steering-plan.json")
                      }
                      aria-label={`Export recipe ${recipe.name}`}
                    >
                      <Download size={16} />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={blocked}
                      onClick={() => {
                        setDialog({ kind: "remove", recipe });
                        setError("");
                      }}
                      aria-label={`Remove recipe ${recipe.name}`}
                    >
                      <Trash2 size={16} />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <p className="muted small">
            Up to {MAX_RECIPES} recipes per room. Loading changes a local draft; it does not
            activate irrigation.
          </p>
        </div>
      </details>
      <Dialog
        open={!!dialog}
        onOpenChange={(open) => {
          if (!open) {
            setDialog(null);
            setError("");
          }
        }}
      >
        <DialogContent className="recipe-dialog">
          <DialogHeader>
            <DialogTitle>
              {dialog?.kind === "save"
                ? "Save recipe"
                : dialog?.kind === "remove"
                  ? "Remove saved recipe?"
                  : "Preview recipe"}
            </DialogTitle>
            <DialogDescription>
              {dialog?.kind === "remove"
                ? "This removes the browser copy. Your current plan and Home Assistant settings stay unchanged."
                : dialog?.kind === "save"
                  ? "Save your named plan in this room's browser library."
                  : "Inspect the recipe before loading it into a local draft. Current zone start dates will be kept."}
            </DialogDescription>
          </DialogHeader>
          {dialog?.kind === "save" && (
            <div className="recipe-form">
              <div>
                <Label htmlFor="recipe-name">Recipe name</Label>
                <Input
                  id="recipe-name"
                  value={name}
                  maxLength={80}
                  onChange={(event) => setName(event.target.value)}
                  autoFocus
                />
              </div>
              <div>
                <Label htmlFor="recipe-notes">Notes (optional)</Label>
                <textarea
                  id="recipe-notes"
                  value={notes}
                  maxLength={1000}
                  onChange={(event) => setNotes(event.target.value)}
                  rows={3}
                />
              </div>
              <div>
                <Label htmlFor="recipe-source">Source URL (optional)</Label>
                <Input
                  id="recipe-source"
                  type="url"
                  value={source}
                  maxLength={500}
                  onChange={(event) => setSource(event.target.value)}
                  placeholder="https://…"
                />
              </div>
              <p className="muted small">
                {dialog.plan.zones.length} zone schedules · {dialog.plan.profiles.length} endpoint
                profiles
                {dialog.imported ? " · imported user plan" : " · copy of the current local plan"}.
              </p>
            </div>
          )}
          {dialog?.kind === "preview" && (
            <div className="recipe-inspection">
              <h3>{dialog.recipe.name}</h3>
              {dialog.recipe.notes && <p className="recipe-notes">{dialog.recipe.notes}</p>}
              {dialog.recipe.sourceUrl && (
                <a href={dialog.recipe.sourceUrl} target="_blank" rel="noopener noreferrer">
                  User-provided source
                </a>
              )}
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="Recipe zone schedules"
              >
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Zone</th>
                      <th>Start date kept</th>
                      <th>Schedule</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dialog.recipe.plan.zones.map((zone) => (
                      <tr key={zone.zone_id}>
                        <td>Zone {zone.zone_id}</td>
                        <td>
                          {plan.zones.find((current) => current.zone_id === zone.zone_id)
                            ?.start_date ?? "Not in this room"}
                        </td>
                        <td>
                          {zone.schedule
                            .map((block) => `Days ${block.start_day}–${block.end_day}`)
                            .join(", ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary>Inspect saved profiles and schedules</summary>
                <pre tabIndex={0} role="region" aria-label="Saved recipe JSON">
                  {JSON.stringify(dialog.recipe.plan, null, 2)}
                </pre>
              </details>
              {!canLoad && (
                <p className="workspace-message">
                  Loading is unavailable while the plan is active, armed, busy or disconnected.
                  Exporting a recipe remains available.
                </p>
              )}
              {dirty && (
                <label className="recipe-replace">
                  <input
                    type="checkbox"
                    checked={replace}
                    onChange={(event) => setReplace(event.target.checked)}
                  />
                  Replace the current unsaved planner draft with this recipe.
                </label>
              )}
            </div>
          )}
          {dialog?.kind === "remove" && (
            <p>
              <strong>{dialog.recipe.name}</strong> will be removed. Export it first if you need a
              backup.
            </p>
          )}
          {validation && dialog?.kind !== "remove" && (
            <p className="workspace-message error" role="alert">
              {validation}
            </p>
          )}
          {message && (
            <p className="workspace-message error" role="alert">
              {message}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              {dialog?.kind === "preview" ? "Keep current draft" : "Cancel"}
            </Button>
            {dialog?.kind === "save" && (
              <Button onClick={persistRecipe} disabled={blocked || !name.trim() || !!validation}>
                Save to library
              </Button>
            )}
            {dialog?.kind === "preview" && (
              <Button
                onClick={loadRecipe}
                disabled={!canLoad || !candidate || !!validation || (dirty && !replace)}
              >
                Load into local draft
              </Button>
            )}
            {dialog?.kind === "remove" && (
              <Button variant="destructive" onClick={deleteRecipe} disabled={blocked}>
                Remove recipe
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
