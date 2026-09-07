import { interpolate, parsePlanImport, planErrors, validDate } from "./grow-plan";
import { createUuid } from "./uuid";
import type { GrowPlan, ParameterLimit } from "./operator-types";

export const MAX_RECIPES = 20;
export const MAX_PLAN_BYTES = 500_000;
const MAX_LIBRARY_BYTES = 2_000_000;
// Version-1 schema keys from strategy_model.py; these are not parameter presets.
const REQUIRED_PARAMETERS = [
  "dryback_target",
  "ec_target_p0",
  "ec_target_p1",
  "ec_target_p2",
  "p1_target_vwc",
  "p2_vwc_threshold",
  "p2_shot_size",
  "p1_initial_shot_size",
  "p3_emergency_vwc_threshold",
  "p3_emergency_shot_size",
];
const ALLOWED_PARAMETERS = new Set([
  ...REQUIRED_PARAMETERS,
  "p1_shot_size_increment",
  "p1_maximum_shots",
  "p1_time_between_shots",
  "p0_maximum_wait_time",
  "max_daily_volume",
  "field_capacity",
  "maximum_ec",
  "watchdog_hours",
]);
function profileId(value: unknown): string {
  if (typeof value !== "string" || !/^[a-zA-Z0-9_-]{1,64}$/.test(value))
    throw new Error("Profile IDs must use 1–64 letters, numbers, underscores or hyphens.");
  return value;
}
function validateRelationships(values: Record<string, number>) {
  if (values.p2_vwc_threshold >= values.p1_target_vwc)
    throw new Error("P2 VWC threshold must be below the P1 target.");
  if (values.p3_emergency_vwc_threshold + 3 > values.p2_vwc_threshold)
    throw new Error("P2 threshold must be at least 3 points above the emergency floor.");
  if ("field_capacity" in values && values.p1_target_vwc > values.field_capacity)
    throw new Error("P1 target exceeds field capacity.");
  if (
    "maximum_ec" in values &&
    Math.max(values.ec_target_p0, values.ec_target_p1, values.ec_target_p2) > values.maximum_ec
  )
    throw new Error("Phase EC target exceeds maximum EC.");
}
export interface RecipeScope {
  roomId: string;
  demo: boolean;
}
export interface Recipe {
  id: string;
  name: string;
  notes: string;
  sourceUrl: string;
  createdAt: string;
  plan: GrowPlan;
}
export interface LibrarySnapshot {
  scope: RecipeScope;
  key: string;
  raw: string | null;
  recipes: Recipe[];
  error: string | null;
}
export type RecipeStorage = Pick<Storage, "getItem" | "setItem">;
export type RecipeCatalog = Record<string, Record<string, ParameterLimit>>;
const bytes = (text: string) => new TextEncoder().encode(text).length;
const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const text = (value: unknown, label: string, maximum: number, required = true): string => {
  if (typeof value !== "string" || value.length > maximum || (required && !value.trim()))
    throw new Error(`${label} must contain ${required ? "1" : "0"}–${maximum} characters.`);
  return value.trim();
};
export function libraryKey(scope: RecipeScope) {
  if (
    typeof scope.roomId !== "string" ||
    !scope.roomId.startsWith("room:") ||
    scope.roomId.length > 128 ||
    typeof scope.demo !== "boolean"
  )
    throw new Error("Select a valid room for this library.");
  return `crop-steering.recipe-library.v1:${scope.demo ? "demo" : "live"}:${encodeURIComponent(scope.roomId)}`;
}
function sourceUrl(value: unknown) {
  const raw = text(value ?? "", "Source URL", 500, false);
  if (!raw) return "";
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("Use an http or https source URL.");
  }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password)
    throw new Error("Use an http or https source URL without embedded credentials.");
  return url.href;
}
export function importRecipePlan(raw: string): GrowPlan {
  if (bytes(raw) > MAX_PLAN_BYTES) throw new Error("Plan file is too large (maximum 500 KB).");
  let plan: GrowPlan;
  try {
    plan = parsePlanImport(raw);
  } catch {
    throw new Error("Choose a valid version 1 Crop Steering plan export.");
  }
  if (plan.profiles.length > 64)
    throw new Error("A recipe can contain at most 64 endpoint profiles.");
  if (!plan.profiles.length || !plan.zones.length)
    throw new Error("A recipe needs endpoint profiles and zone schedules.");
  const ids = new Set<string>(),
    zoneIds = new Set<number>();
  const profiles = plan.profiles.map((profile) => {
    const id = profileId(profile.id),
      name = text(profile.name, "Profile name", 100);
    if (ids.has(id)) throw new Error("Recipe profile IDs must be unique.");
    ids.add(id);
    const endpoints = {} as Pick<typeof profile, "vegetative" | "generative">;
    for (const side of ["vegetative", "generative"] as const) {
      if (Array.isArray(profile[side]) || Object.keys(profile[side]).length > 64)
        throw new Error("Invalid endpoint parameters.");
      endpoints[side] = Object.fromEntries(
        Object.entries(profile[side]).map(([key, value]) => {
          if (
            !/^[a-z][a-z0-9_]{0,63}$/.test(key) ||
            ["constructor", "prototype", "__proto__"].includes(key) ||
            typeof value !== "number" ||
            !Number.isFinite(value)
          )
            throw new Error("Endpoint parameters must be finite numbers with valid keys.");
          return [key, value];
        }),
      );
    }
    const a = Object.keys(endpoints.vegetative).sort().join(),
      b = Object.keys(endpoints.generative).sort().join();
    if (!a || a !== b) throw new Error("Both recipe endpoints need matching parameters.");
    if (!REQUIRED_PARAMETERS.every((key) => key in endpoints.vegetative))
      throw new Error("Recipe endpoints must include all required steering parameters.");
    if (Object.keys(endpoints.vegetative).some((key) => !ALLOWED_PARAMETERS.has(key)))
      throw new Error("Recipe endpoints contain unsupported steering parameters.");
    validateRelationships(endpoints.vegetative);
    validateRelationships(endpoints.generative);
    return { id, name, ...endpoints };
  });
  const zones = plan.zones.map((zone) => {
    if (
      zone.zone_id < 1 ||
      zone.zone_id > 24 ||
      zoneIds.has(zone.zone_id) ||
      !validDate(zone.start_date)
    )
      throw new Error("Recipe zones need unique IDs and valid saved dates.");
    zoneIds.add(zone.zone_id);
    return {
      zone_id: zone.zone_id,
      start_date: zone.start_date,
      schedule: [...zone.schedule]
        .sort((a, b) => a.start_day - b.start_day)
        .map((block) => ({
          start_day: block.start_day,
          end_day: block.end_day,
          profile_id: profileId(block.profile_id),
          bias: block.bias,
        })),
    };
  });
  const result: GrowPlan = { schema_version: 1, profiles, zones };
  const keys = [
    ...new Set(
      profiles.flatMap((profile) => [
        ...Object.keys(profile.vegetative),
        ...Object.keys(profile.generative),
      ]),
    ),
  ];
  const structuralCatalog = Object.fromEntries(
    zones.map((zone) => [
      String(zone.zone_id),
      Object.fromEntries(
        keys.map((key) => [
          key,
          {
            value: null,
            min: -Number.MAX_VALUE,
            max: Number.MAX_VALUE,
            step: 1,
            unit: "",
            entity_ids: [],
          },
        ]),
      ),
    ]),
  );
  const errors = planErrors(result, structuralCatalog);
  if (errors.length) throw new Error(`Invalid recipe structure: ${errors.slice(0, 4).join(" ")}`);
  return result;
}
function normalizeRecipe(value: unknown): Recipe {
  if (!value || typeof value !== "object") throw new Error("Invalid stored recipe.");
  const record = value as Recipe;
  const id = text(record.id, "Recipe ID", 80);
  if (!/^[a-zA-Z0-9_-]+$/.test(id)) throw new Error("Invalid recipe ID.");
  if (typeof record.createdAt !== "string" || !Number.isFinite(Date.parse(record.createdAt)))
    throw new Error("Invalid recipe timestamp.");
  return {
    id,
    name: text(record.name, "Recipe name", 80),
    notes: text(record.notes ?? "", "Notes", 1000, false),
    sourceUrl: sourceUrl(record.sourceUrl),
    createdAt: record.createdAt,
    plan: importRecipePlan(JSON.stringify(record.plan)),
  };
}
function decode(raw: string | null, scope: RecipeScope): Recipe[] {
  if (raw === null) return [];
  if (bytes(raw) > MAX_LIBRARY_BYTES) throw new Error("Stored recipe library exceeds 2 MB.");
  const document = JSON.parse(raw);
  if (
    !document ||
    document.schema_version !== 1 ||
    document.room_id !== scope.roomId ||
    document.demo !== scope.demo ||
    !Array.isArray(document.recipes) ||
    document.recipes.length > MAX_RECIPES
  )
    throw new Error("Invalid room-scoped recipe library.");
  const recipes = document.recipes.map(normalizeRecipe) as Recipe[];
  if (
    new Set(recipes.map((recipe) => recipe.id)).size !== recipes.length ||
    new Set(recipes.map((recipe) => recipe.name.toLowerCase())).size !== recipes.length
  )
    throw new Error("Stored recipe names and IDs must be unique.");
  return recipes;
}
export function readLibrary(storage: RecipeStorage, scope: RecipeScope): LibrarySnapshot {
  const key = libraryKey(scope);
  let raw: string | null = null;
  try {
    raw = storage.getItem(key);
    return { scope: { ...scope }, key, raw, recipes: decode(raw, scope), error: null };
  } catch (error) {
    return {
      scope: { ...scope },
      key,
      raw,
      recipes: [],
      error: `Recipe storage could not be read. Existing data has not been changed. ${message(error)}`,
    };
  }
}
/** Seed only a never-used DEMO key. Existing empty, edited or corrupt libraries are preserved. */
export function initializeDemoLibrary(
  storage: RecipeStorage,
  scope: RecipeScope,
  samplePlan: GrowPlan,
  now = Date.now(),
): LibrarySnapshot {
  const prior = readLibrary(storage, scope);
  if (!scope.demo || prior.raw !== null || prior.error) return prior;
  const plan = importRecipePlan(JSON.stringify(samplePlan));
  const examples = [
    { id: "demo-steady", name: "Demo • steady schedule", weekly: false },
    { id: "demo-weekly", name: "Demo • week-by-week changes", weekly: true },
  ].map(({ id, name, weekly }) => {
    const copy = structuredClone(plan);
    for (const zone of copy.zones) {
      const original = zone.schedule;
      const end = Math.min(84, Math.max(...original.map((block) => block.end_day)));
      zone.schedule = weekly
        ? Array.from({ length: Math.ceil(end / 7) }, (_, index) => {
            const start = index * 7 + 1;
            const block =
              original.find((item) => item.start_day <= start && item.end_day >= start) ||
              original[0];
            return {
              start_day: start,
              end_day: Math.min(end, start + 6),
              profile_id: block.profile_id,
              bias: block.bias,
            };
          })
        : [{ start_day: 1, end_day: end, profile_id: original[0].profile_id, bias: 50 }];
    }
    return normalizeRecipe({
      id,
      name,
      notes:
        "Synthetic interface example using the existing demo endpoints. Not a cultivation recommendation or a source-guide recipe. Loading changes only the demo draft.",
      sourceUrl: "",
      createdAt: new Date(now).toISOString(),
      plan: copy,
    });
  });
  // One validated write with the same stale-read guard as user saves.
  return persist(storage, prior, examples);
}
function persist(
  storage: RecipeStorage,
  prior: LibrarySnapshot,
  recipes: Recipe[],
): LibrarySnapshot {
  if (prior.error) throw new Error(prior.error);
  if (recipes.length > MAX_RECIPES)
    throw new Error(
      `The library limit is ${MAX_RECIPES} recipes. Remove one before adding another.`,
    );
  const raw = JSON.stringify({
    schema_version: 1,
    room_id: prior.scope.roomId,
    demo: prior.scope.demo,
    recipes,
  });
  if (bytes(raw) > MAX_LIBRARY_BYTES)
    throw new Error(
      "Recipe library storage is limited to 2 MB. Export or remove an old recipe first.",
    );
  decode(raw, prior.scope);
  try {
    if (storage.getItem(prior.key) !== prior.raw)
      throw new Error(
        "The library changed in another tab. Reload the library before trying again.",
      );
    storage.setItem(prior.key, raw);
  } catch (error) {
    throw new Error(`Recipe storage was not updated: ${message(error)}`);
  }
  return {
    scope: { ...prior.scope },
    key: prior.key,
    raw,
    recipes: decode(raw, prior.scope),
    error: null,
  };
}
export function saveRecipe(
  storage: RecipeStorage,
  prior: LibrarySnapshot,
  value: { name: string; plan: GrowPlan; notes?: string; sourceUrl?: string },
): LibrarySnapshot {
  const name = text(value.name, "Recipe name", 80);
  if (prior.recipes.some((recipe) => recipe.name.toLowerCase() === name.toLowerCase()))
    throw new Error("That recipe name already exists. Choose a different name.");
  const recipe = normalizeRecipe({
    id: createUuid(),
    name,
    plan: value.plan,
    notes: value.notes ?? "",
    sourceUrl: value.sourceUrl ?? "",
    createdAt: new Date().toISOString(),
  });
  return persist(storage, prior, [...prior.recipes, recipe]);
}
export function removeRecipe(
  storage: RecipeStorage,
  prior: LibrarySnapshot,
  id: string,
): LibrarySnapshot {
  if (!prior.recipes.some((recipe) => recipe.id === id))
    throw new Error("Recipe is no longer in this library. Reload it first.");
  return persist(
    storage,
    prior,
    prior.recipes.filter((recipe) => recipe.id !== id),
  );
}
export function exportRecipe(recipe: Recipe, roomName: string): string {
  return JSON.stringify(
    {
      format: "crop-steering-plan",
      room_name: roomName,
      recipe_name: recipe.name,
      notes: recipe.notes,
      source_url: recipe.sourceUrl,
      plan: recipe.plan,
    },
    null,
    2,
  );
}
/** Only schedules/profiles are reused. Room zone IDs and current dates remain authoritative. */
export function prepareRecipeDraft(
  recipe: GrowPlan,
  current: GrowPlan,
  catalog: RecipeCatalog,
  activeZoneIds: number[],
): GrowPlan {
  const candidate = importRecipePlan(JSON.stringify(recipe));
  const sorted = (values: number[]) => JSON.stringify([...values].sort((a, b) => a - b));
  if (
    !activeZoneIds.length ||
    sorted(candidate.zones.map((z) => z.zone_id)) !== sorted(activeZoneIds) ||
    sorted(current.zones.map((z) => z.zone_id)) !== sorted(activeZoneIds)
  )
    throw new Error(
      "Recipe and current plan must contain exactly the room's active zone IDs. Update zone assignments first.",
    );
  candidate.zones = candidate.zones.map((zone) => ({
    ...zone,
    start_date: current.zones.find((existing) => existing.zone_id === zone.zone_id)!.start_date,
  }));
  const errors = planErrors(candidate, catalog);
  if (errors.length) throw new Error(errors.slice(0, 6).join(" "));
  const byId = new Map(candidate.profiles.map((profile) => [profile.id, profile]));
  for (const zone of candidate.zones) {
    const limits = catalog[String(zone.zone_id)];
    const effective = Object.fromEntries(
      Object.entries(limits).flatMap(([key, limit]) =>
        typeof limit.value === "number" && Number.isFinite(limit.value) ? [[key, limit.value]] : [],
      ),
    );
    for (const block of zone.schedule) {
      const profile = byId.get(block.profile_id)!;
      for (const side of ["vegetative", "generative"] as const) {
        validateRelationships({ ...effective, ...profile[side] });
        for (const [key, value] of Object.entries(profile[side])) {
          const limit = limits[key];
          if (key === "p1_maximum_shots" && !Number.isInteger(value))
            throw new Error("Maximum shots must be an integer.");
          if (!Number.isFinite(limit.step) || limit.step <= 0)
            throw new Error(`Zone ${zone.zone_id} ${key}: HA step is unavailable.`);
          const steps = (value - limit.min) / limit.step;
          if (Math.abs(steps - Math.round(steps)) > 1e-6)
            throw new Error(
              `Zone ${zone.zone_id} ${key}: endpoint must align to HA step ${limit.step}.`,
            );
        }
      }
      validateRelationships({ ...effective, ...interpolate(profile, block.bias, limits) });
    }
  }
  return candidate;
}
