import { describe, expect, it, vi } from "vitest";
import {
  libraryKey,
  readLibrary,
  saveRecipe,
  removeRecipe,
  importRecipePlan,
  exportRecipe,
  prepareRecipeDraft,
  MAX_RECIPES,
} from "./recipe-library";
import type { GrowPlan } from "./operator-types";
class MemoryStorage {
  data = new Map<string, string>();
  writes = 0;
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.writes++;
    this.data.set(key, value);
  }
}
const scope = { roomId: "room:f1_", demo: false };
// Synthetic parser fixture, not a recommended growing profile.
const endpoint = {
  dryback_target: 10,
  ec_target_p0: 1,
  ec_target_p1: 1,
  ec_target_p2: 1,
  p1_target_vwc: 50,
  p2_vwc_threshold: 40,
  p2_shot_size: 1,
  p1_initial_shot_size: 1,
  p3_emergency_vwc_threshold: 30,
  p3_emergency_shot_size: 1,
};
const plan: GrowPlan = {
  schema_version: 1,
  profiles: [
    {
      id: "user-profile",
      name: "User profile",
      vegetative: { ...endpoint },
      generative: { ...endpoint },
    },
  ],
  zones: [
    {
      zone_id: 1,
      start_date: "2026-09-01",
      schedule: [{ start_day: 1, end_day: 7, profile_id: "user-profile", bias: 50 }],
    },
  ],
};
const catalog = {
  "1": Object.fromEntries(
    Object.entries(endpoint).map(([key, value]) => [
      key,
      { value, min: 0, max: 100, step: 1, unit: "", entity_ids: [] },
    ]),
  ),
};

describe("user-authored recipe library", () => {
  it.each(["contains space", "x".repeat(65)])(
    "rejects backend-invalid profile identifiers: %s",
    (id) => {
      const invalid = structuredClone(plan);
      invalid.profiles[0].id = id;
      invalid.zones[0].schedule[0].profile_id = id;
      expect(() => importRecipePlan(JSON.stringify(invalid))).toThrow(/profile.*ID/i);
    },
  );
  it("rejects more than 64 profiles and missing or unsupported endpoint keys", () => {
    const invalid = structuredClone(plan);
    invalid.profiles = Array.from({ length: 65 }, (_, i) => ({
      ...plan.profiles[0],
      id: `profile_${i}`,
    }));
    expect(() => importRecipePlan(JSON.stringify(invalid))).toThrow(/64/);
    const missing = structuredClone(plan);
    delete missing.profiles[0].vegetative.ec_target_p0;
    delete missing.profiles[0].generative.ec_target_p0;
    expect(() => importRecipePlan(JSON.stringify(missing))).toThrow(/required/i);
    const extra = structuredClone(plan);
    extra.profiles[0].vegetative.unsupported = 1;
    extra.profiles[0].generative.unsupported = 1;
    expect(() => importRecipePlan(JSON.stringify(extra))).toThrow(/supported/i);
  });
  it("checks backend relationships and actual HA step alignment before local load", () => {
    const invalid = structuredClone(plan);
    invalid.profiles[0].vegetative.p2_vwc_threshold = 50;
    expect(() => prepareRecipeDraft(invalid, plan, catalog, [1])).toThrow(/below/i);
    invalid.profiles[0].vegetative.p2_vwc_threshold = 40;
    invalid.profiles[0].vegetative.p1_target_vwc = 50.5;
    expect(() => prepareRecipeDraft(invalid, plan, catalog, [1])).toThrow(/step/i);
  });

  it("fails visibly without cryptographic randomness and never writes an unsafe ID", () => {
    const storage = new MemoryStorage();
    vi.stubGlobal("crypto", {});
    try {
      expect(() =>
        saveRecipe(storage, readLibrary(storage, scope), { name: "Unsupported browser", plan }),
      ).toThrow(/secure record IDs/i);
      expect(storage.writes).toBe(0);
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it("bounds oversized persisted data before parsing and keeps it available for recovery", () => {
    const storage = new MemoryStorage();
    const raw = " ".repeat(2_000_001);
    storage.setItem(libraryKey(scope), raw);
    const prior = readLibrary(storage, scope);
    expect(prior.error).toMatch(/2 MB/);
    expect(prior.raw).toBe(raw);
    expect(() => saveRecipe(storage, prior, { name: "Replace", plan })).toThrow(/2 MB/);
    expect(storage.writes).toBe(1);
  });

  it("saves on HTTP LAN origins without crypto.randomUUID", () => {
    const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto);
    vi.stubGlobal("crypto", { getRandomValues });
    try {
      const storage = new MemoryStorage();
      const saved = saveRecipe(storage, readLibrary(storage, scope), { name: "HTTP recipe", plan });
      expect(saved.recipes[0].id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      );
      expect(readLibrary(storage, scope).recipes).toEqual(saved.recipes);
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it.each(["overlap", "gap", "mismatched endpoints", "unused mismatched endpoints"])(
    "rejects structurally corrupt recipes: %s",
    (kind) => {
      const invalid = structuredClone(plan);
      if (kind === "overlap")
        invalid.zones[0].schedule.push({
          ...invalid.zones[0].schedule[0],
          start_day: 7,
          end_day: 8,
        });
      if (kind === "gap") invalid.zones[0].schedule[0].start_day = 2;
      if (kind === "mismatched endpoints") invalid.profiles[0].generative = {};
      if (kind === "unused mismatched endpoints")
        invalid.profiles.push({ ...invalid.profiles[0], id: "unused", generative: {} });
      expect(() => importRecipePlan(JSON.stringify(invalid))).toThrow(/structure|matching/i);
    },
  );

  it("starts empty without writing or manufacturing recipes", () => {
    const storage = new MemoryStorage();
    const library = readLibrary(storage, scope);
    expect(library.recipes).toEqual([]);
    expect(library.error).toBeNull();
    expect(storage.writes).toBe(0);
  });
  it("separates named/default rooms and demo/live namespaces", () => {
    expect(
      new Set([
        libraryKey(scope),
        libraryKey({ ...scope, demo: true }),
        libraryKey({ ...scope, roomId: "room:" }),
      ]).size,
    ).toBe(3);
    const storage = new MemoryStorage();
    saveRecipe(storage, readLibrary(storage, scope), { name: "My recipe", plan });
    expect(readLibrary(storage, { ...scope, demo: true }).recipes).toHaveLength(0);
    expect(readLibrary(storage, { ...scope, roomId: "room:" }).recipes).toHaveLength(0);
  });
  it("round-trips named user data and existing plan export format", () => {
    const storage = new MemoryStorage();
    const library = saveRecipe(storage, readLibrary(storage, scope), {
      name: "  My recipe  ",
      plan,
      notes: "User notes",
      sourceUrl: "https://example.com/reference",
    });
    const saved = library.recipes[0];
    expect(saved.name).toBe("My recipe");
    expect(readLibrary(storage, scope).recipes).toEqual(library.recipes);
    expect(importRecipePlan(exportRecipe(saved, "Room name"))).toEqual(plan);
    expect(saved.notes).toBe("User notes");
    expect(saved.sourceUrl).toBe("https://example.com/reference");
  });
  it("does not mutate the source plan or transplant recipe dates while loading", () => {
    const current = structuredClone(plan);
    current.zones[0].start_date = "2026-10-20";
    const recipe = structuredClone(plan);
    recipe.zones[0].schedule[0].bias = 40;
    const result = prepareRecipeDraft(recipe, current, catalog, [1]);
    expect(result.zones[0].start_date).toBe("2026-10-20");
    expect(result.zones[0].schedule[0].bias).toBe(40);
    expect(recipe.zones[0].start_date).toBe("2026-09-01");
    expect(current.zones[0].schedule[0].bias).toBe(50);
  });
  it("requires exact current room zone identities and checks current HA limits", () => {
    expect(() => prepareRecipeDraft(plan, plan, catalog, [1, 2])).toThrow(/zone/i);
    const other = structuredClone(plan);
    other.zones[0].zone_id = 2;
    expect(() => prepareRecipeDraft(other, plan, catalog, [1])).toThrow(/zone/i);
    const invalid = structuredClone(plan);
    invalid.profiles[0].vegetative.p1_target_vwc = 101;
    expect(() => prepareRecipeDraft(invalid, plan, catalog, [1])).toThrow(/limits/i);
  });
  it.each([
    "not json",
    '{"schema_version":2}',
    JSON.stringify({ schema_version: 1, room_id: "room:other_", demo: false, recipes: [] }),
  ])("preserves corrupt stored data (%s) and blocks writes", (raw) => {
    const storage = new MemoryStorage();
    storage.setItem(libraryKey(scope), raw);
    const writes = storage.writes;
    const library = readLibrary(storage, scope);
    expect(library.error).toBeTruthy();
    expect(() => saveRecipe(storage, library, { name: "Replace", plan })).toThrow();
    expect(storage.getItem(libraryKey(scope))).toBe(raw);
    expect(storage.writes).toBe(writes);
  });
  it("does not overwrite changes from another tab", () => {
    const storage = new MemoryStorage();
    const stale = readLibrary(storage, scope);
    const current = saveRecipe(storage, stale, { name: "First", plan });
    expect(() => saveRecipe(storage, stale, { name: "Second", plan })).toThrow(/changed/i);
    expect(readLibrary(storage, scope).recipes).toEqual(current.recipes);
  });
  it("reports storage denial and quota errors without losing the last good snapshot", () => {
    const denied = {
      getItem: () => {
        throw new Error("Denied");
      },
      setItem: () => {
        throw new Error("Denied");
      },
    };
    expect(readLibrary(denied, scope).error).toMatch(/storage/i);
    const storage = new MemoryStorage();
    const prior = saveRecipe(storage, readLibrary(storage, scope), { name: "First", plan });
    const raw = storage.getItem(libraryKey(scope));
    storage.setItem = () => {
      throw new Error("Quota exceeded");
    };
    expect(() => saveRecipe(storage, prior, { name: "Second", plan })).toThrow(/storage|quota/i);
    expect(storage.getItem(libraryKey(scope))).toBe(raw);
  });
  it("bounds records and text, rejects duplicate names and unsafe source URLs", () => {
    const storage = new MemoryStorage();
    let state = readLibrary(storage, scope);
    state = saveRecipe(storage, state, { name: "First", plan });
    expect(() => saveRecipe(storage, state, { name: " FIRST ", plan })).toThrow(/name/i);
    expect(() => saveRecipe(storage, state, { name: "x".repeat(81), plan })).toThrow();
    expect(() =>
      saveRecipe(storage, state, { name: "URL", plan, sourceUrl: "javascript:alert(1)" }),
    ).toThrow(/http/i);
    expect(() =>
      saveRecipe(storage, state, {
        name: "URL",
        plan,
        sourceUrl: "https://user:password@example.com",
      }),
    ).toThrow();
    for (let i = 1; i < MAX_RECIPES; i++)
      state = saveRecipe(storage, state, { name: `Recipe ${i}`, plan });
    expect(() => saveRecipe(storage, state, { name: "Too many", plan })).toThrow(/20|limit/i);
  });
  it("removes only the selected recipe and rejects stale removal", () => {
    const storage = new MemoryStorage();
    const initial = readLibrary(storage, scope);
    const first = saveRecipe(storage, initial, { name: "First", plan });
    const both = saveRecipe(storage, first, { name: "Second", plan });
    expect(() => removeRecipe(storage, first, first.recipes[0].id)).toThrow(/changed/i);
    expect(removeRecipe(storage, both, first.recipes[0].id).recipes.map((r) => r.name)).toEqual([
      "Second",
    ]);
  });
  it("rejects oversized/malformed imports and nonfinite endpoint data", () => {
    expect(() => importRecipePlan(" ".repeat(500001))).toThrow(/large/i);
    expect(() => importRecipePlan("null")).toThrow();
    expect(() =>
      importRecipePlan(
        JSON.stringify({
          ...plan,
          profiles: [{ ...plan.profiles[0], vegetative: { p1_target_vwc: null } }],
        }),
      ),
    ).toThrow();
  });
});
