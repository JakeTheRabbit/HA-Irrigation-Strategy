import { describe, expect, it } from "vitest";
import {
  canonicalHash,
  LEGACY_PAGES,
  PAGES,
  parseRoute,
  zoneOnPage,
  routeHash,
  sameRoute,
  sectionOf,
} from "./routes";

describe("the old menu's addresses land on each page's new home", () => {
  it.each([
    ["#/overview", "today"],
    ["#/zones", "all-zones"],
    ["#/strategy", "plan/targets"],
    ["#/grow-plan", "plan/schedule"],
    ["#/compare", "history/compare"],
    ["#/insights", "equipment/probes"],
    ["#/activity", "history/explorer"],
    ["#/log", "history/explorer"],
    ["#/logs", "history/explorer"],
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
    expect(parseRoute("#/plan").route.page).toBe("plan/watering");
    expect(parseRoute("#/history").route.page).toBe("history/explorer");
    expect(parseRoute("#/equipment").route.page).toBe("equipment/probes");
    expect(canonicalHash("#/plan")).toBe("#/plan/watering");
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
    ["?view=logs", "history/explorer"],
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
    expect(sectionOf("equipment/pump-calibration")).toBe("equipment");
    expect(sectionOf("settings/alerts")).toBe("settings");
    expect(sectionOf("equipment/dosing")).toBe("equipment");
  });
  it("old addresses land on their new homes", () => {
    expect(canonicalHash("#/history/timeline?zone=2")).toBe("#/history/explorer?zone=2");
    expect(parseRoute("#/equipment/feed").route.page).toBe("equipment/dosing");
    expect(parseRoute("#/plan").route.page).toBe("plan/watering");
    expect(parseRoute("#/equipment/tank")).toEqual({
      route: { page: "equipment/dosing" },
      canonical: false,
    });
  });
  it("opens each room's batch-tank dosing under Equipment", () => {
    expect(parseRoute("#/equipment/dosing")).toEqual({
      route: { page: "equipment/dosing" },
      canonical: true,
    });
    expect(routeHash({ page: "equipment/dosing" })).toBe("#/equipment/dosing");
    expect(canonicalHash("#/equipment/dosing")).toBeNull();
  });
  it("opens the site's notifications under Settings", () => {
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

describe("zone context survives reload", () => {
  it.each(["plan/targets", "plan/schedule", "history/explorer"] as const)(
    "keeps selected zone on %s",
    (page) => {
      const route = { page, zone: 2 };
      expect(parseRoute(routeHash(route)).route).toEqual(route);
      expect(sameRoute(route, { page, zone: 1 })).toBe(false);
    },
  );
});

describe("zoneOnPage", () => {
  const zones = [{ id: 1 }, { id: 2 }];
  it("shows the addressed zone, or the room's first for a bare #/zone", () => {
    expect(zoneOnPage(zones, 2)).toEqual({ id: 2 });
    expect(zoneOnPage(zones, null)).toEqual({ id: 1 });
  });
  it("shows no zone for a zone the room does not have, never its first", () => {
    expect(zoneOnPage(zones, 99)).toBeUndefined();
  });
});
