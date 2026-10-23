import {
  Activity,
  CalendarRange,
  History,
  Settings2,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { Page, Section } from "./routes";

/** The menu: five sections, each with every page under it, in menu order. The desktop tree, the
 * phone's in-page tabs and the bottom bar all read this. */
export interface NavSection {
  section: Section;
  label: string;
  icon: LucideIcon;
  items: { page: Page; label: string }[];
}

export const NAV_TREE: readonly NavSection[] = [
  {
    section: "today",
    label: "Status",
    icon: Activity,
    items: [{ page: "all-zones", label: "All rooms" }],
  },
  {
    section: "plan",
    label: "Irrigation",
    icon: CalendarRange,
    items: [
      { page: "plan/watering", label: "Timeline" },
      { page: "plan/targets", label: "Current day" },
      { page: "plan/timers", label: "Timer programs" },
      { page: "plan/schedule", label: "Grow plan & presets" },
    ],
  },
  {
    section: "history",
    label: "History",
    icon: History,
    items: [
      { page: "history/explorer", label: "Explorer" },
      { page: "history/water", label: "Water & flow" },
      { page: "history/compare", label: "Compare runs" },
      { page: "history/changes", label: "Changes" },
    ],
  },
  {
    section: "equipment",
    label: "Equipment",
    icon: Wrench,
    items: [
      { page: "equipment/probes", label: "Probes & offsets" },
      { page: "equipment/dosing", label: "Feed & dosing" },
      { page: "equipment/stock", label: "Stock" },
      { page: "equipment/pump-calibration", label: "Prime & calibrate a pump" },
      { page: "equipment/feed-calibration", label: "Feed pH/EC calibration" },
      { page: "equipment/setup", label: "Setup: pumps & valves" },
    ],
  },
  {
    section: "settings",
    label: "Settings",
    icon: Settings2,
    items: [
      { page: "settings/alerts", label: "Alert rules" },
      { page: "settings/notifications", label: "Notifications" },
      { page: "settings/system", label: "System status" },
      { page: "settings/ai", label: "AI assistant" },
      { page: "settings", label: "Dashboards & display" },
      { page: "help", label: "Help" },
    ],
  },
];

/** The sections drawn open: the ones the grower opened, and the current page's section unless the
 * grower collapsed it. A section opened only because a page in it was current closes again once
 * the grower moves to another section. */
export function expandedSections(
  current: Section,
  opened: ReadonlySet<Section>,
  collapsed: ReadonlySet<Section>,
): Set<Section> {
  const expanded = new Set(opened);
  if (!collapsed.has(current)) expanded.add(current);
  return expanded;
}

const OPEN_KEY = "crop-steering.nav-open";

/** The sections the grower left open, or none when storage is blocked or holds nothing usable. */
export function readOpenSections(): Set<Section> {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(OPEN_KEY) ?? "[]");
    if (!Array.isArray(stored)) return new Set();
    return new Set(NAV_TREE.map((s) => s.section).filter((section) => stored.includes(section)));
  } catch {
    return new Set();
  }
}

export function writeOpenSections(open: Set<Section>): void {
  try {
    localStorage.setItem(OPEN_KEY, JSON.stringify([...open]));
  } catch {
    // Blocked storage: the tree still opens and closes, it just forgets on reload.
  }
}
