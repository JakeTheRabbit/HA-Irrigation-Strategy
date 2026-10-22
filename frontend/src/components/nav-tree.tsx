import { useEffect, useId, useState, type KeyboardEvent, type MouseEvent } from "react";
import { ChevronRight } from "lucide-react";
import { NAV_TREE, readOpenSections, writeOpenSections } from "@/lib/nav-tree";
import { routeHash, sectionOf, type Page, type Section } from "@/lib/routes";
import "./nav-tree.css";

/** The desktop menu: a disclosure tree of every section and the pages under it. A section with one
 * page (Status) is a plain link. Sections open and close by click or arrow keys; the open set is
 * remembered, and the current page's section is always opened. */
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
  const id = useId();
  const current = sectionOf(page);
  const [open, setOpen] = useState(() => new Set([...readOpenSections(), current]));
  useEffect(() => {
    setOpen((now) => (now.has(current) ? now : new Set([...now, current])));
  }, [current]);
  function toggle(section: Section, next = !open.has(section)) {
    const updated = new Set(open);
    if (next) updated.add(section);
    else updated.delete(section);
    setOpen(updated);
    writeOpenSections(updated);
  }
  function follow(event: MouseEvent, target: Page) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    navigate(target);
  }
  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    const items = [
      ...event.currentTarget.querySelectorAll<HTMLElement>("[data-nav-section], [data-nav-page]"),
    ].filter((item) => !item.closest("[hidden]"));
    const here = event.target as HTMLElement;
    const index = items.indexOf(here);
    if (index < 0) return;
    const section = here.dataset.navSection as Section | undefined;
    const button = here.tagName === "BUTTON";
    let target: HTMLElement | undefined;
    if (event.key === "ArrowDown") target = items[index + 1];
    else if (event.key === "ArrowUp") target = items[index - 1];
    else if (event.key === "Home") target = items[0];
    else if (event.key === "End") target = items[items.length - 1];
    else if (event.key === "ArrowRight" && button && section) toggle(section, true);
    else if (event.key === "ArrowLeft" && button && section) toggle(section, false);
    else if (event.key === "ArrowLeft" && !button)
      target =
        here
          .closest(".nav-tree-section")
          ?.querySelector<HTMLElement>("button[data-nav-section]") ?? undefined;
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
          if (group.items.length === 1) {
            const only = group.items[0];
            return (
              <li key={group.section} className="nav-tree-section">
                <a
                  href={routeHash({ page: only.page })}
                  className="nav-tree-head"
                  data-active={active || undefined}
                  data-nav-section={group.section}
                  data-nav-page={only.page}
                  aria-current={page === only.page ? "page" : undefined}
                  onClick={(event) => follow(event, only.page)}
                >
                  <Icon size={19} aria-hidden="true" />
                  <span>{group.label}</span>
                </a>
              </li>
            );
          }
          const expanded = open.has(group.section);
          const listId = `${id}-${group.section}`;
          const pending = group.items.reduce((sum, item) => sum + (badges[item.page] ?? 0), 0);
          return (
            <li key={group.section} className="nav-tree-section">
              <button
                type="button"
                className="nav-tree-head"
                data-active={active || undefined}
                data-nav-section={group.section}
                aria-expanded={expanded}
                aria-controls={listId}
                onClick={() => toggle(group.section)}
              >
                <Icon size={19} aria-hidden="true" />
                <span>{group.label}</span>
                {!expanded && pending > 0 && <i className="nav-draft-count">{pending}</i>}
                <ChevronRight size={16} className="nav-tree-chevron" aria-hidden="true" />
              </button>
              <ul id={listId} className="nav-tree-items" hidden={!expanded}>
                {group.items.map((item) => (
                  <li key={item.page}>
                    <a
                      href={routeHash({ page: item.page })}
                      data-nav-page={item.page}
                      aria-current={page === item.page ? "page" : undefined}
                      onClick={(event) => follow(event, item.page)}
                    >
                      {item.label}
                      {!!badges[item.page] && (
                        <i className="nav-draft-count">{badges[item.page]}</i>
                      )}
                    </a>
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
