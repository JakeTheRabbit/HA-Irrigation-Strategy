import { describe, expect, test } from "vitest";
import { DRAFT_PREFIX, draftStore, isSameDraft } from "./drafts";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  } as unknown as Storage & { data: Map<string, string> };
}

describe("drafts", () => {
  test("useDraft persists to sessionStorage and survives a throwing storage", () => {
    const storage = memoryStorage();
    const store = draftStore(() => storage);
    expect(store.read("targets:f2_:1")).toBeUndefined();
    store.write("targets:f2_:1", { rewater: 56 });
    expect(storage.data.get(DRAFT_PREFIX + "targets:f2_:1")).toBe('{"rewater":56}');
    expect(store.read("targets:f2_:1")).toEqual({ rewater: 56 });
    store.clear("targets:f2_:1");
    expect(store.read("targets:f2_:1")).toBeUndefined();

    const throwing = draftStore(() => {
      throw new Error("SecurityError: storage is disabled");
    });
    expect(() => throwing.write("k", 1)).not.toThrow();
    expect(throwing.read("k")).toBeUndefined();
    expect(() => throwing.clear("k")).not.toThrow();

    const broken = memoryStorage();
    broken.setItem(DRAFT_PREFIX + "k", "{not json");
    expect(draftStore(() => broken).read("k")).toBeUndefined();
  });
  test("a draft equal to the saved value is not dirty", () => {
    expect(isSameDraft({ a: 1, b: [2] }, { a: 1, b: [2] })).toBe(true);
    expect(isSameDraft({ a: 1 }, { a: 2 })).toBe(false);
  });
});
