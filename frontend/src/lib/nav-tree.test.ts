import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, test, vi } from "vitest";
import { NavTree } from "@/components/nav-tree";
import { expandedSections, NAV_TREE, readOpenSections, writeOpenSections } from "./nav-tree";
import { RENDERED_PAGES, type Section } from "./routes";

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
    expect(pages).toHaveLength(21);
    expect(new Set(pages).size).toBe(21);
    // Help sits last under Settings: every page a grower can open is in the tree.
    expect(NAV_TREE.at(-1)!.items.at(-1)).toEqual({ page: "help", label: "Help" });
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
  test("only the current section and explicitly opened ones are expanded", () => {
    const none = new Set<Section>();
    // Visiting History opens it; moving on to an Equipment page collapses it again.
    expect(expandedSections("history", none, none)).toEqual(new Set(["history"]));
    expect(expandedSections("equipment", none, none)).toEqual(new Set(["equipment"]));
    // An explicitly opened section stays open wherever the grower goes.
    expect(expandedSections("history", new Set(["settings"]), none)).toEqual(
      new Set(["settings", "history"]),
    );
    // The current section can still be collapsed.
    expect(expandedSections("history", none, new Set(["history"]))).toEqual(new Set());
  });
  test("a reload renders only the stored explicit toggles plus the current section", () => {
    const store = new Map([["crop-steering.nav-open", JSON.stringify(["settings"])]]);
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
    });
    const html = renderToStaticMarkup(
      createElement(NavTree, { page: "equipment/probes", navigate: () => {} }),
    );
    const expanded = (section: string) =>
      html.match(new RegExp(`<button[^>]*data-nav-section="${section}"[^>]*>`))?.[0].includes(
        'aria-expanded="true"',
      );
    expect(expanded("settings")).toBe(true);
    expect(expanded("equipment")).toBe(true);
    expect(expanded("history")).toBe(false);
    expect(expanded("plan")).toBe(false);
  });
  test("every tree page has a component in App's render chain", () => {
    for (const s of NAV_TREE) for (const i of s.items) expect(RENDERED_PAGES).toContain(i.page);
  });
});

test("the pump page is named for what it does: prime and calibrate", () => {
  const equipment = NAV_TREE.find((s) => s.section === "equipment")!;
  expect(equipment.items.find((i) => i.page === "equipment/pump-calibration")?.label).toBe("Prime & calibrate a pump");
});
