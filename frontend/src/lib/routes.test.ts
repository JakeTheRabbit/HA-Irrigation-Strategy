import { describe, expect, it } from "vitest";
import {
  canonicalHash,
  LEGACY_PAGES,
  PAGES,
  parseRoute,
  routeHash,
  sameRoute,
  sectionOf,
} from "./routes";

describe("the old menu's addresses land on each page's new home", () => {
  it.each([
    ["#/overview", "today"],
    ["#/zones", "today"],
    ["#/strategy", "plan/targets"],
    ["#/grow-plan", "plan/schedule"],
    ["#/compare", "history/compare"],
    ["#/insights", "equipment/probes"],
    ["#/activity", "history/timeline"],
    ["#/sensors", "equipment/probes"],
    ["#/stock", "equipment/stock"],
    ["#/setup", "equipment/setup"],
  ])("%s opens %s and is rewritten", (hash, page) => {
    expect(parseRoute(hash)).toEqual({ route: { page }, canonical: false });
    expect(canonicalHash(hash)).toBe(`#/${page}`);
  });
  it("keeps Settings and Help where they were, with the Help page's code link", () => {
    expect(parseRoute("#/settings")).toEqual({ route: { page: "settings" }, canonical: true });
    expect(parseRoute("#/help?code=CS-605")).toEqual({ route: { page: "help" }, canonical: true });
    expect(canonicalHash("#/help?code=CS-605")).toBeNull();
  });
  it("keeps what follows the ? when it rewrites an old address", () => {
    expect(canonicalHash("#/sensors?filter=vwc")).toBe("#/equipment/probes?filter=vwc");
    expect(canonicalHash("#/grow-plan/")).toBe("#/plan/schedule");
  });
  it("names every old page", () => {
    for (const page of Object.values(LEGACY_PAGES)) expect(PAGES).toContain(page);
  });
});

describe("the new addresses", () => {
  it("open each page as written", () => {
    for (const page of PAGES.filter((item) => item !== "zone"))
      expect(parseRoute(`#/${page}`)).toEqual({ route: { page }, canonical: true });
  });
  it("open a menu entry's first page", () => {
    expect(parseRoute("#/plan").route.page).toBe("plan/targets");
    expect(parseRoute("#/history").route.page).toBe("history/timeline");
    expect(parseRoute("#/equipment").route.page).toBe("equipment/probes");
    expect(canonicalHash("#/plan")).toBe("#/plan/targets");
  });
  it("open a zone by its number, or the room's first zone", () => {
    expect(parseRoute("#/zone/2")).toEqual({ route: { page: "zone", zone: 2 }, canonical: true });
    expect(parseRoute("#/zone")).toEqual({ route: { page: "zone", zone: null }, canonical: true });
    expect(parseRoute("#/zone/nope")).toEqual({
      route: { page: "zone", zone: null },
      canonical: false,
    });
    expect(canonicalHash("#/zone/02")).toBe("#/zone/2");
    expect(routeHash({ page: "zone", zone: 3 })).toBe("#/zone/3");
    expect(routeHash({ page: "zone", zone: null })).toBe("#/zone");
    expect(routeHash({ page: "history/water" })).toBe("#/history/water");
  });
  it("send an unknown address to Today", () => {
    expect(parseRoute("#/no-such-page")).toEqual({ route: { page: "today" }, canonical: false });
    expect(canonicalHash("#/no-such-page")).toBe("#/today");
  });
});

describe("the retired single-page dashboards' ?view= links", () => {
  it.each([
    ["?view=dashboard", "today"],
    ["?view=tune", "plan/targets"],
    ["?view=timeline", "plan/schedule"],
    ["?view=recipes", "plan/schedule"],
    ["?view=logs", "history/timeline"],
    ["?view=climate", "equipment/probes"],
    ["?view=substrate", "equipment/probes"],
    ["?view=floorplan", "equipment/setup"],
    ["?view=control", "settings"],
    ["?view=help", "help"],
    ["?view=unknown", "today"],
    ["", "today"],
  ])("%s opens %s", (search, page) => {
    expect(parseRoute("", search)).toEqual({ route: { page }, canonical: true });
  });
  it("give way to a hash", () => {
    expect(parseRoute("#/stock", "?view=climate").route.page).toBe("equipment/stock");
  });
});

describe("the menu", () => {
  it("files each page under one of five entries", () => {
    expect(new Set(PAGES.map(sectionOf))).toEqual(
      new Set(["today", "plan", "history", "equipment", "settings"]),
    );
    expect(sectionOf("zone")).toBe("today");
    expect(sectionOf("help")).toBe("settings");
    expect(sectionOf("equipment/tank")).toBe("equipment");
    expect(sectionOf("equipment/dosing")).toBe("equipment");
  });
  it("opens each room's batch-tank dosing under Equipment", () => {
    expect(parseRoute("#/equipment/dosing")).toEqual({
      route: { page: "equipment/dosing" },
      canonical: true,
    });
    expect(routeHash({ page: "equipment/dosing" })).toBe("#/equipment/dosing");
    expect(canonicalHash("#/equipment/dosing")).toBeNull();
  });
  it("opens the site's notifications under Settings & help", () => {
    expect(parseRoute("#/settings/notifications")).toEqual({
      route: { page: "settings/notifications" },
      canonical: true,
    });
    expect(sectionOf("settings/notifications")).toBe("settings");
    expect(routeHash({ page: "settings/notifications" })).toBe("#/settings/notifications");
    expect(canonicalHash("#/settings/notifications")).toBeNull();
    // Settings itself stays where it was.
    expect(parseRoute("#/settings").route.page).toBe("settings");
  });
  it("tells two zones apart, and the same page apart from nothing", () => {
    expect(sameRoute({ page: "zone", zone: 1 }, { page: "zone", zone: 2 })).toBe(false);
    expect(sameRoute({ page: "zone", zone: 1 }, { page: "zone", zone: 1 })).toBe(true);
    expect(sameRoute({ page: "today" }, { page: "today", zone: 4 })).toBe(true);
  });
});
