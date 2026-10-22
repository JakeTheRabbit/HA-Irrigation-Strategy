import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, test, vi } from "vitest";
import { NavTree } from "@/components/nav-tree";
import { NAV_TREE, readOpenSections, writeOpenSections } from "./nav-tree";
import { RENDERED_PAGES } from "./routes";

afterEach(() => vi.unstubAllGlobals());

describe("the tree menu", () => {
  test("tree lists every sub-page once in menu order", () => {
    expect(NAV_TREE.map((s) => s.label)).toEqual([
      "Status",
      "Irrigation",
      "History",
      "Equipment",
      "Settings",
    ]);
    const pages = NAV_TREE.flatMap((s) => s.items.map((i) => i.page));
    expect(pages).toHaveLength(20);
    expect(new Set(pages).size).toBe(20);
  });
  test("open state survives a throwing localStorage", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    expect(readOpenSections()).toEqual(new Set());
    expect(() => writeOpenSections(new Set(["plan"]))).not.toThrow();
  });
  test("open state round-trips through localStorage", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
    });
    writeOpenSections(new Set(["plan", "settings"]));
    expect(store.has("crop-steering.nav-open")).toBe(true);
    expect(readOpenSections()).toEqual(new Set(["plan", "settings"]));
  });
  test("current page's section renders open with aria-current", () => {
    const html = renderToStaticMarkup(
      createElement(NavTree, { page: "history/changes", navigate: () => {} }),
    );
    expect(html).toMatch(
      /data-nav-section="history"[^>]*aria-expanded="true"|aria-expanded="true"[^>]*data-nav-section="history"/,
    );
    expect(html).toMatch(
      /data-nav-section="equipment"[^>]*aria-expanded="false"|aria-expanded="false"[^>]*data-nav-section="equipment"/,
    );
    expect(html).toMatch(
      /data-nav-page="history\/changes"[^>]*aria-current="page"|aria-current="page"[^>]*data-nav-page="history\/changes"/,
    );
  });
  test("every tree page has a component in App's render chain", () => {
    for (const s of NAV_TREE) for (const i of s.items) expect(RENDERED_PAGES).toContain(i.page);
  });
});
