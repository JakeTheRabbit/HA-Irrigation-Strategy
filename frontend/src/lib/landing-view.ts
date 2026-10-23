import { LEGACY_PAGES, parseRoute, type Page, type Route } from "./routes";
export const LANDING_KEY = "crop-steering-landing-view";
export const LANDING_VIEWS = [
  { value: "all-zones", label: "Status · all rooms" },
  { value: "today", label: "Status · selected room" },
  { value: "plan/targets", label: "Irrigation · current day" },
  { value: "plan/schedule", label: "Irrigation · calendar" },
  { value: "history/explorer", label: "History · explorer" },
  { value: "history/water", label: "History · water use" },
  { value: "equipment/setup", label: "Equipment · rooms and zones" },
] as const satisfies readonly { value: Page; label: string }[];
export type LandingView = (typeof LANDING_VIEWS)[number]["value"];
/** A saved choice, moved to its new home if its page moved (`history/timeline` opens Explorer). */
export function landingView(value: string | null): LandingView {
  const moved = value === null ? null : (LEGACY_PAGES[value] ?? value);
  return LANDING_VIEWS.some((item) => item.value === moved) ? (moved as LandingView) : "all-zones";
}
export function readLandingView(storage?: Pick<Storage, "getItem">): LandingView {
  try {
    return landingView((storage ?? localStorage).getItem(LANDING_KEY));
  } catch {
    return "all-zones";
  }
}
export function saveLandingView(value: LandingView, storage?: Pick<Storage, "setItem">): boolean {
  try {
    (storage ?? localStorage).setItem(LANDING_KEY, value);
    return true;
  } catch {
    return false;
  }
}
/** A direct bookmark/notification always wins; only an unaddressed app entry uses the preference. */
export function initialRoute(hash: string, search: string, preference: string | null): Route {
  const addressed = hash.replace(/^#\/?/, "").length > 0 || new URLSearchParams(search).has("view");
  return addressed ? parseRoute(hash, search).route : { page: landingView(preference) };
}
