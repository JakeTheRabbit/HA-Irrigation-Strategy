import {
  Bell,
  Cpu,
  Droplets,
  FlaskConical,
  LayoutDashboard,
  LineChart,
  Settings2,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import type { Page, Section } from "./routes";

/** The eight focused workspaces: flat single-click entries in the sidebar, with horizontal
 * workspace tabs inside each view. Command palette, sidebar, mobile tabs and bottom bar all read
 * this single source of truth. */
export interface NavSection {
  section: Section;
  label: string;
  /** Short label for the mobile bottom bar where space is tight. */
  shortLabel?: string;
  icon: LucideIcon;
  /** `short`: compact tab label for narrow screens. */
  items: { page: Page; label: string; short?: string }[];
}

export const NAV_TREE: readonly NavSection[] = [
  {
    section: "overview",
    label: "Overview",
    icon: LayoutDashboard,
    items: [
      { page: "all-zones", label: "All rooms" },
      { page: "today", label: "Room view", short: "Room" },
    ],
  },
  {
    section: "watering",
    label: "Watering",
    icon: Droplets,
    items: [
      { page: "plan/watering", label: "Timeline" },
      { page: "plan/targets", label: "Targets" },
      { page: "plan/timers", label: "Timers" },
      { page: "plan/schedule", label: "Grow plan" },
    ],
  },
  {
    section: "dosing",
    label: "Dosing & Tank",
    shortLabel: "Dosing",
    icon: FlaskConical,
    items: [
      { page: "equipment/dosing", label: "Batch & pumps", short: "Batch" },
      { page: "equipment/stock", label: "Stock tanks", short: "Stock" },
      { page: "equipment/pump-calibration", label: "Pump calibration", short: "Pump cal." },
      { page: "equipment/feed-calibration", label: "Feed pH/EC cal.", short: "Feed cal." },
    ],
  },
  {
    section: "hardware",
    label: "Hardware",
    icon: Cpu,
    items: [
      { page: "equipment/probes", label: "Probes & offsets", short: "Probes" },
      { page: "equipment/setup", label: "Setup & supply", short: "Setup" },
    ],
  },
  {
    section: "history",
    label: "History",
    icon: LineChart,
    items: [
      { page: "history/explorer", label: "Explorer" },
      { page: "history/water", label: "Water & flow", short: "Water" },
      { page: "history/compare", label: "Compare runs", short: "Compare" },
      { page: "history/grows", label: "Grows" },
      { page: "history/changes", label: "Changes" },
    ],
  },
  {
    section: "ai",
    label: "AI Assistant",
    shortLabel: "AI",
    icon: Sparkles,
    items: [
      { page: "today/ai", label: "Status & decisions", short: "Status" },
      { page: "settings/ai", label: "Judges & settings", short: "Settings" },
    ],
  },
  {
    section: "alerts",
    label: "Alerts",
    icon: Bell,
    items: [
      { page: "settings/notifications", label: "Notifications" },
      { page: "settings/alerts", label: "Alert rules", short: "Rules" },
    ],
  },
  {
    section: "system",
    label: "System",
    icon: Settings2,
    items: [
      { page: "settings/system", label: "Status & upgrades", short: "Status" },
      { page: "settings", label: "Display & HA", short: "Display" },
      { page: "settings/features", label: "Capabilities" },
      { page: "help", label: "Help & codes", short: "Help" },
    ],
  },
];

/** The four primary daily-driver sections pinned in the mobile bottom bar (plus "More" drawer). */
export const MOBILE_PRIMARY_SECTIONS: readonly Section[] = [
  "overview",
  "watering",
  "dosing",
  "history",
];

/** Kept exported for backwards compatibility with storage helpers and tests. */
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
    // Blocked storage: ignore.
  }
}
