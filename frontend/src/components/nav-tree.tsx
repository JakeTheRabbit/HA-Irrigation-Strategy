import type { KeyboardEvent, MouseEvent } from "react";
import { NAV_TREE } from "@/lib/nav-tree";
import { routeHash, sectionOf, SECTION_PAGES, type Page } from "@/lib/routes";
import "./nav-tree.css";

/** The sidebar workspace navigation: eight flat, single-click Home Assistant rows.
 * Sub-views live in the horizontal workspace tab bar inside `<main>`, eliminating
 * deep accordion menus and keeping the live Rooms & Zones tree immediately visible. */
export function NavTree({
  page,
  navigate,
  badges = {},
}: {
  page: Page;
  navigate: (page: Page) => void;
  /** A count beside a page: unsaved changes waiting on it. */
  badges?: Partial<Record<Page, number>>;
}) {
  const current = sectionOf(page);

  function follow(event: MouseEvent, target: Page) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    navigate(target);
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    const items = [...event.currentTarget.querySelectorAll<HTMLElement>("[data-nav-section]")];
    const index = items.indexOf(event.target as HTMLElement);
    if (index < 0) return;
    let target: HTMLElement | undefined;
    if (event.key === "ArrowDown") target = items[index + 1];
    else if (event.key === "ArrowUp") target = items[index - 1];
    else if (event.key === "Home") target = items[0];
    else if (event.key === "End") target = items[items.length - 1];
    else return;
    event.preventDefault();
    target?.focus();
  }

  return (
    <nav aria-label="Main navigation" className="nav-tree" onKeyDown={onKeyDown}>
      <ul>
        {NAV_TREE.map((group) => {
          const Icon = group.icon;
          const active = group.section === current;
          const target = SECTION_PAGES[group.section] ?? group.items[0].page;
          const pending = group.items.reduce((sum, item) => sum + (badges[item.page] ?? 0), 0);
          return (
            <li key={group.section} className="nav-tree-section">
              <a
                href={routeHash({ page: target })}
                className="nav-tree-head"
                data-active={active || undefined}
                data-nav-section={group.section}
                data-nav-page={target}
                aria-current={active ? "page" : undefined}
                onClick={(event) => follow(event, target)}
              >
                <Icon size={18} aria-hidden="true" />
                <span>{group.label}</span>
                {pending > 0 && <i className="nav-draft-count">{pending}</i>}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
