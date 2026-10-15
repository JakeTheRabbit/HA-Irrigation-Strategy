import { sectionOf, type Page, type Section } from "@/lib/routes";
import "./page-tabs.css";

/** The menu's five entries and the pages under each: one row of tabs above a page that has more
 * than one view. */
export const SECTION_LABELS: Record<Section, string> = {
  today: "Today",
  plan: "Plan",
  history: "History",
  equipment: "Equipment",
  settings: "Settings & help",
};
export const TABS: Partial<Record<Section, { page: Page; label: string }[]>> = {
  plan: [
    { page: "plan/targets", label: "Targets" },
    { page: "plan/schedule", label: "Schedule" },
  ],
  history: [
    { page: "history/timeline", label: "Timeline" },
    { page: "history/water", label: "Water use" },
    { page: "history/compare", label: "Compare runs" },
  ],
  equipment: [
    { page: "equipment/probes", label: "Probes" },
    { page: "equipment/stock", label: "Stock tanks" },
    { page: "equipment/tank", label: "Tank & pump" },
    { page: "equipment/dosing", label: "Dosing" },
    { page: "equipment/setup", label: "Setup" },
  ],
  settings: [
    { page: "settings", label: "Settings" },
    { page: "settings/notifications", label: "Notifications" },
    { page: "help", label: "Help" },
  ],
};
/** A page's own name, for its tab and the window title. */
export function pageLabel(page: Page): string {
  if (page === "today") return "Today";
  if (page === "zone") return "Zone";
  return TABS[sectionOf(page)]?.find((tab) => tab.page === page)?.label ?? SECTION_LABELS.today;
}

export function PageTabs({
  page,
  navigate,
  badges = {},
}: {
  page: Page;
  navigate: (page: Page) => void;
  /** A count beside a tab: unsaved changes waiting on it. */
  badges?: Partial<Record<Page, number>>;
}) {
  const section = sectionOf(page);
  const tabs = TABS[section];
  if (!tabs) return null;
  return (
    <nav className="page-tabs" aria-label={`${SECTION_LABELS[section]} views`}>
      {tabs.map((tab) => (
        <button
          type="button"
          key={tab.page}
          aria-current={tab.page === page ? "page" : undefined}
          onClick={() => navigate(tab.page)}
        >
          {tab.label}
          {!!badges[tab.page] && <i className="page-tab-count">{badges[tab.page]}</i>}
        </button>
      ))}
    </nav>
  );
}
