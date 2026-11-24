import { useEffect, useRef } from "react";
import { NAV_TREE } from "@/lib/nav-tree";
import { sectionOf, type Page, type Section } from "@/lib/routes";
import "./page-tabs.css";

/** The eight workspaces and their horizontal view tabs, shown consistently on both desktop and
 * phone so every section has one clear top-level tab bar. */
export const SECTION_LABELS = Object.fromEntries(
  NAV_TREE.map((group) => [group.section, group.label]),
) as Record<Section, string>;

export const TABS = Object.fromEntries(
  NAV_TREE.map((group) => [group.section, group.items]),
) as Record<Section, { page: Page; label: string; short?: string }[]>;

/** Pages reached via drill-in rather than a fixed tab. */
const OFF_MENU_LABELS: Partial<Record<Page, string>> = {
  zone: "Zone",
  "history/drivers": "Dryback drivers",
};

/** A page's display title, for the mobile topbar and window title. */
export function pageLabel(page: Page): string {
  return (
    OFF_MENU_LABELS[page] ??
    TABS[sectionOf(page)].find((tab) => tab.page === page)?.label ??
    SECTION_LABELS.overview
  );
}

export function PageTabs({
  page,
  navigate,
  badges = {},
  roomName,
  zoneName,
}: {
  page: Page;
  navigate: (page: Page) => void;
  /** A count beside a tab: unsaved changes waiting on it. */
  badges?: Partial<Record<Page, number>>;
  /** Selected room name shown on the Overview › Room tab. */
  roomName?: string;
  /** Active zone name when drilled into a Zone view. */
  zoneName?: string;
}) {
  const section = sectionOf(page);
  const baseTabs = TABS[section];
  const row = useRef<HTMLElement>(null);

  useEffect(() => {
    const nav = row.current;
    const active = nav?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!nav || !active || nav.scrollWidth <= nav.clientWidth) return;
    nav.scrollLeft = active.offsetLeft - (nav.clientWidth - active.offsetWidth) / 2;
  }, [page]);

  const tabs =
    section === "overview"
      ? [
          { page: "all-zones" as Page, label: "All rooms", short: "All rooms" },
          {
            page: "today" as Page,
            label: roomName ? `${roomName}` : "Room view",
            short: roomName || "Room",
          },
          ...(page === "zone" && zoneName
            ? [{ page: "zone" as Page, label: zoneName, short: zoneName }]
            : []),
        ]
      : baseTabs;

  if (tabs.length < 2) return null;

  return (
    <nav
      ref={row}
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
          <span className="page-tab-full">{tab.label}</span>
          <span className="page-tab-short">{tab.short ?? tab.label}</span>
          {!!badges[tab.page] && <i className="page-tab-count">{badges[tab.page]}</i>}
        </button>
      ))}
    </nav>
  );
}
