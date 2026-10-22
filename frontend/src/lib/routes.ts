/** The dashboard's pages, the five menu entries they sit under, and the addresses that open them,
 * the old eleven-page menu's included: a bookmark or a notification link from before keeps working
 * and lands where that page's content lives now. */

export interface Route {
  page: Page;
  /** The zone page's zone; null opens the room's first zone. */
  zone?: number | null;
}

/** Every page, each with a component in App's render switch: that switch ends in an exhaustive
 * `never` check, so a page added here without a component fails the type check. */
export const RENDERED_PAGES = [
  "all-zones",
  "today",
  "zone",
  "today/ai",
  "plan/watering",
  "plan/targets",
  "plan/timers",
  "plan/schedule",
  "history/explorer",
  "history/water",
  "history/compare",
  "history/changes",
  "history/grows",
  "history/drivers",
  "equipment/probes",
  "equipment/dosing",
  "equipment/stock",
  "equipment/pump-calibration",
  "equipment/feed-calibration",
  "equipment/setup",
  "settings",
  "settings/alerts",
  "settings/notifications",
  "settings/system",
  "settings/ai",
  "settings/features",
  "help",
] as const;

export type Page = (typeof RENDERED_PAGES)[number];

export const PAGES: readonly Page[] = RENDERED_PAGES;

export type Section = "today" | "plan" | "history" | "equipment" | "settings";

/** The menu entry a page belongs to: a zone and the AI assistant are reached from Today, Help sits with
 * Settings. */
export function sectionOf(page: Page): Section {
  if (page === "all-zones" || page === "today" || page === "zone" || page === "today/ai")
    return "today";
  if (page === "settings" || page === "help") return "settings";
  return page.split("/")[0] as Section;
}

/** Each old page's new home. */
export const LEGACY_PAGES: Readonly<Record<string, Page>> = {
  overview: "today",
  zones: "all-zones",
  strategy: "plan/targets",
  "grow-plan": "plan/schedule",
  compare: "history/compare",
  insights: "equipment/probes",
  activity: "history/explorer",
  log: "history/explorer",
  logs: "history/explorer",
  sensors: "equipment/probes",
  stock: "equipment/stock",
  setup: "equipment/setup",
  "equipment/tank": "equipment/dosing",
  "equipment/feed": "equipment/dosing",
  "history/timeline": "history/explorer",
  settings: "settings",
  help: "help",
};

/** The `?view=` links of the retired single-page dashboards (index.html, f2.html, the classic ones). */
export const LEGACY_VIEWS: Readonly<Record<string, Page>> = {
  dashboard: "today",
  overview: "today",
  zones: "all-zones",
  tune: "plan/targets",
  strategy: "plan/targets",
  timeline: "plan/schedule",
  recipes: "plan/schedule",
  logs: "history/explorer",
  log: "history/explorer",
  activity: "history/explorer",
  sensors: "equipment/probes",
  climate: "equipment/probes",
  substrate: "equipment/probes",
  analyze: "equipment/probes",
  floor: "equipment/setup",
  floorplan: "equipment/setup",
  settings: "settings",
  control: "settings",
  help: "help",
};

/** A menu entry opened on its own opens its first page; the phone's bottom bar opens these too. */
export const SECTION_PAGES: Readonly<Record<string, Page>> = {
  plan: "plan/watering",
  history: "history/explorer",
  equipment: "equipment/probes",
  settings: "settings/alerts",
};

/** The pages that keep a zone in their address (`?zone=2`). */
export const ZONE_FOCUS_PAGES: readonly Page[] = ["plan/targets", "plan/schedule", "history/explorer"];

export function routeHash(route: Route): string {
  if (route.page === "zone" && route.zone) return `#/zone/${route.zone}`;
  return (
    `#/${route.page}` +
    (route.zone && ZONE_FOCUS_PAGES.includes(route.page)
      ? `?zone=${route.zone}`
      : "")
  );
}

export const sameRoute = (a: Route, b: Route) =>
  a.page === b.page &&
  ((a.page !== "zone" && !ZONE_FOCUS_PAGES.includes(a.page)) ||
    (a.zone ?? null) === (b.zone ?? null));

/**
 * The page an address opens. `canonical` is false when the address is an old or short form of it:
 * the caller replaces it with `routeHash(route)`, keeping anything after a "?" in the hash (the Help
 * page's `?code=CS-101`). An empty hash opens a legacy `?view=` page, else Today, and stays as it is.
 */
export function parseRoute(hash: string, search = ""): { route: Route; canonical: boolean } {
  const path = hash.replace(/^#\/?/, "").split("?")[0].replace(/\/+$/, "");
  if (!path) {
    const view = new URLSearchParams(search).get("view") ?? "";
    return { route: { page: LEGACY_VIEWS[view] ?? "today" }, canonical: true };
  }
  const parts = path.split("/");
  if (parts[0] === "zone") {
    const zone = Number(parts[1]);
    const valid = Number.isInteger(zone) && zone >= 1;
    return {
      route: { page: "zone", zone: valid ? zone : null },
      canonical: parts.length === 1 || (parts.length === 2 && valid && String(zone) === parts[1]),
    };
  }
  if ((PAGES as readonly string[]).includes(path)) {
    const zone = Number(new URLSearchParams(hash.split("?")[1] ?? "").get("zone"));
    const focused =
      ZONE_FOCUS_PAGES.includes(path as Page) &&
      Number.isSafeInteger(zone) &&
      zone > 0;
    return {
      route: focused ? { page: path as Page, zone } : { page: path as Page },
      canonical: true,
    };
  }
  const page = SECTION_PAGES[path] ?? LEGACY_PAGES[path] ?? "today";
  return { route: { page }, canonical: false };
}

/** The hash an address should read, or null when it already does: `#/sensors?x=1` becomes
 * `#/equipment/probes?x=1`. */
export function canonicalHash(hash: string, search = ""): string | null {
  const { route, canonical } = parseRoute(hash, search);
  if (canonical) return null;
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?")) : "";
  return routeHash(route) + query;
}
