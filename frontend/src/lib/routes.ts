/** The dashboard's pages, the eight focused workspaces they live under, and the addresses that
 * open them (every legacy URL and HA notification/Repairs link keeps working without breaking). */

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

export type Section =
  | "overview"
  | "watering"
  | "dosing"
  | "hardware"
  | "history"
  | "ai"
  | "alerts"
  | "system";

/** Which of the eight focused workspaces owns a given page. */
export function sectionOf(page: Page): Section {
  switch (page) {
    case "all-zones":
    case "today":
    case "zone":
      return "overview";
    case "plan/watering":
    case "plan/targets":
    case "plan/timers":
    case "plan/schedule":
      return "watering";
    case "equipment/dosing":
    case "equipment/stock":
    case "equipment/pump-calibration":
    case "equipment/feed-calibration":
      return "dosing";
    case "equipment/probes":
    case "equipment/setup":
      return "hardware";
    case "history/explorer":
    case "history/water":
    case "history/compare":
    case "history/grows":
    case "history/changes":
    case "history/drivers":
      return "history";
    case "today/ai":
    case "settings/ai":
      return "ai";
    case "settings/notifications":
    case "settings/alerts":
      return "alerts";
    case "settings/system":
    case "settings":
    case "settings/features":
    case "help":
      return "system";
  }
}

/** Each old page's home. */
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

/** A workspace or legacy section opened on its own lands on its default view.
 * Note: "overview" intentionally stays in LEGACY_PAGES ("today") so legacy #/overview & f2.html
 * links still open the room view, while the Overview sidebar workspace opens its first tab (all-zones). */
export const SECTION_PAGES: Readonly<Record<string, Page>> = {
  watering: "plan/watering",
  dosing: "equipment/dosing",
  hardware: "equipment/probes",
  history: "history/explorer",
  ai: "today/ai",
  alerts: "settings/notifications",
  system: "settings/system",
  // Legacy 5-section shorthands kept working:
  plan: "plan/watering",
  equipment: "equipment/probes",
  settings: "settings/alerts",
};

/** The pages that keep a zone in their address (`?zone=2`). */
export const ZONE_FOCUS_PAGES: readonly Page[] = ["plan/targets", "plan/schedule", "history/explorer"];

export function routeHash(route: Route): string {
  if (route.page === "zone" && route.zone) return `#/zone/${route.zone}`;
  return (
    `#/${route.page}` +
    (route.zone && ZONE_FOCUS_PAGES.includes(route.page) ? `?zone=${route.zone}` : "")
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
      ZONE_FOCUS_PAGES.includes(path as Page) && Number.isSafeInteger(zone) && zone > 0;
    return {
      route: focused ? { page: path as Page, zone } : { page: path as Page },
      canonical: true,
    };
  }
  const page = SECTION_PAGES[path] ?? LEGACY_PAGES[path] ?? "today";
  return { route: { page }, canonical: false };
}

/** The canonical `#/...` when `hash` is an old or short address, else null. Query parameters stay. */
export function canonicalHash(hash: string, search = ""): string | null {
  const parsed = parseRoute(hash, search);
  if (parsed.canonical) return null;
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?")) : "";
  return `${routeHash(parsed.route)}${query}`;
}

/** The zone the zone page shows: the named one when the room has it, the first when none was asked
 * for, or undefined when the named zone does not exist in this room. */
export function zoneOnPage<T extends { id: number }>(
  zones: readonly T[],
  requested: number | null,
): T | undefined {
  return requested === null ? zones[0] : zones.find((zone) => zone.id === requested);
}
