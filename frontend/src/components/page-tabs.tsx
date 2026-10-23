import { NAV_TREE } from "@/lib/nav-tree";
import { sectionOf, type Page, type Section } from "@/lib/routes";
import "./page-tabs.css";

/** The menu's five sections and the pages under each, as the tree menu lists them: on a phone, one
 * row of tabs above a page whose section has more than one page. A wider window hides them; the
 * tree menu shows the same pages. */
export const SECTION_LABELS = Object.fromEntries(
  NAV_TREE.map((group) => [group.section, group.label]),
) as Record<Section, string>;
export const TABS = Object.fromEntries(
  NAV_TREE.map((group) => [group.section, group.items]),
) as Record<Section, { page: Page; label: string }[]>;
/** Pages reached from another page rather than the menu. */
const OFF_MENU_LABELS: Partial<Record<Page, string>> = {
  today: "Today",
  zone: "Zone",
  "today/ai": "AI assistant",
  "history/grows": "Grows",
  "history/drivers": "Dryback drivers",
  "settings/features": "Capabilities",
};
/** A page's own name, for its tab and the window title. */
export function pageLabel(page: Page): string {
  return (
    OFF_MENU_LABELS[page] ??
    TABS[sectionOf(page)].find((tab) => tab.page === page)?.label ??
    SECTION_LABELS.today
  );
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
  if (tabs.length < 2) return null;
  return (
    <nav
      className="page-tabs"
      data-section={section}
      aria-label={`${SECTION_LABELS[section]} pages`}
    >
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
