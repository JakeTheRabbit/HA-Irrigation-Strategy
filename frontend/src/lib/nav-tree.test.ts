import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, test, vi } from "vitest";
import { NavTree } from "@/components/nav-tree";
import { expandedSections, NAV_TREE, readOpenSections, writeOpenSections } from "./nav-tree";
import { RENDERED_PAGES, type Section } from "./routes";

afterEach(() => vi.unstubAllGlobals());

describe("the workspace menu", () => {
  test("lists eight focused workspaces with every tab once", () => {
    expect(NAV_TREE.map((s) => s.label)).toEqual([
      "Overview",
      "Watering",
      "Dosing & Tank",
      "Hardware",
      "History",
      "AI Assistant",
      "Alerts",
      "System",
    ]);
    const pages = NAV_TREE.flatMap((s) => s.items.map((i) => i.page));
    expect(pages).toHaveLength(25);
    expect(new Set(pages).size).toBe(25);
    // Help sits last under System: every workspace page is reachable in one click + tab.
    expect(NAV_TREE.at(-1)!.items.at(-1)).toEqual({ page: "help", label: "Help & codes", short: "Help" });
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
    expect(() => writeOpenSections(new Set(["watering"]))).not.toThrow();
  });
  test("open state round-trips through localStorage", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
    });
    writeOpenSections(new Set(["watering", "system"]));
    expect(store.has("crop-steering.nav-open")).toBe(true);
    expect(readOpenSections()).toEqual(new Set(["watering", "system"]));
  });
  test("current page's workspace renders active with aria-current", () => {
    const html = renderToStaticMarkup(
      createElement(NavTree, { page: "history/changes", navigate: () => {} }),
    );
    expect(html).toMatch(
      /data-nav-section="history"[^>]*aria-current="page"|aria-current="page"[^>]*data-nav-section="history"/,
    );
    expect(html).not.toMatch(
      /data-nav-section="hardware"[^>]*aria-current="page"|aria-current="page"[^>]*data-nav-section="hardware"/,
    );
  });
  test("expandedSections keeps explicitly opened workspaces plus current", () => {
    const none = new Set<Section>();
    expect(expandedSections("history", none, none)).toEqual(new Set(["history"]));
    expect(expandedSections("hardware", none, none)).toEqual(new Set(["hardware"]));
    expect(expandedSections("history", new Set(["system"]), none)).toEqual(
      new Set(["system", "history"]),
    );
    expect(expandedSections("history", none, new Set(["history"]))).toEqual(new Set());
  });
  test("every workspace tab has a component in App's render chain", () => {
    for (const s of NAV_TREE) for (const i of s.items) expect(RENDERED_PAGES).toContain(i.page);
  });
});

test("pump calibration lives in the Dosing & Tank workspace", () => {
  const dosing = NAV_TREE.find((s) => s.section === "dosing")!;
  expect(dosing.items.find((i) => i.page === "equipment/pump-calibration")?.label).toBe("Pump calibration");
});
