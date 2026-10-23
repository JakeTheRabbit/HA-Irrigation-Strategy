import { buildRoom } from "./model";
import { NAV_TREE } from "./nav-tree";
import { routeHash } from "./routes";
import type { Controller } from "./types";

/** One place the jump-to palette opens: a menu page, a room, a zone or an action's page. */
export interface PaletteEntry {
  label: string;
  /** Where it sits, in menu words ("History", "Zone in F1"). */
  hint: string;
  /** The page's address (`#/zone/2`, `#/settings/alerts?rule=new`). */
  hash: string;
  keywords: string[];
  /** The room it opens in; absent: the selected room. A room's zones share one address
   * (`#/zone/2`), so the room travels beside it. */
  room?: string;
}

/** Everything the palette can open: every menu page, then each room (the selected one first) with
 * its zones, then the actions. */
export function paletteEntries(controller: Controller): PaletteEntry[] {
  const pages = NAV_TREE.flatMap((section) =>
    section.items.map((item) => ({
      label: item.label,
      hint: section.label,
      hash: routeHash({ page: item.page }),
      keywords: [section.label, ...item.page.split("/")],
    })),
  );
  const rooms = [...controller.rooms].sort(
    (a, b) => Number(b.id === controller.roomId) - Number(a.id === controller.roomId),
  );
  const places = rooms.flatMap((room) => [
    { label: room.name, hint: "Room", hash: "#/today", keywords: ["room"], room: room.id },
    ...buildRoom(controller.states, room).zones.map((zone) => ({
      label: `${room.name} · ${zone.name}`,
      hint: `Zone in ${room.name}`,
      hash: routeHash({ page: "zone", zone: zone.id }),
      keywords: ["zone"],
      room: room.id,
    })),
  ]);
  // Only the feed probes a room maps (engine_config `feed_ph_sensor` / `feed_ec_sensor`).
  const calibrate = rooms.flatMap((room) => {
    const config = controller.states[`sensor.crop_steering_${room.prefix}engine_config`]?.attributes ?? {};
    const mapped = (reading: "pH" | "EC") => {
      const entity = config[`feed_${reading.toLowerCase()}_sensor`];
      return typeof entity === "string" && entity !== "";
    };
    return (["pH", "EC"] as const).filter(mapped).map((reading) => ({
      label: `Calibrate ${room.name} feed ${reading}`,
      hint: "Equipment › Feed pH/EC calibration",
      hash: routeHash({ page: "equipment/feed-calibration" }),
      keywords: ["probe", "sensor", "buffer"],
      room: room.id,
    }));
  });
  const actions: PaletteEntry[] = [
    ...calibrate,
    {
      label: "Prime a dosing pump",
      hint: "Equipment › Prime & calibrate a pump",
      hash: routeHash({ page: "equipment/pump-calibration" }),
      keywords: ["dose", "fill", "air"],
    },
    {
      label: "New alert rule",
      hint: "Settings › Alert rules",
      hash: `${routeHash({ page: "settings/alerts" })}?rule=new`,
      keywords: ["alarm", "notify", "add"],
    },
    {
      label: "New timer program",
      hint: "Irrigation › Timer programs",
      hash: routeHash({ page: "plan/timers" }),
      keywords: ["schedule", "add"],
    },
  ];
  return [...pages, ...places, ...actions];
}

const words = (text: string) => text.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);

/** The entries every typed word starts a word of, best first: the label holding every word, then
 * the label starting with the first word; otherwise in `entries` order. An empty query lists all. */
export function searchPalette(entries: PaletteEntry[], q: string): PaletteEntry[] {
  const typed = words(q);
  if (typed.length === 0) return entries;
  const has = (pool: string[], word: string) => pool.some((w) => w.startsWith(word));
  return entries
    .map((entry, index) => {
      const label = words(entry.label);
      const all = [...label, ...words(entry.hint), ...entry.keywords.flatMap(words)];
      if (!typed.every((word) => has(all, word))) return null;
      const inLabel = typed.every((word) => has(label, word)) ? 0 : 1;
      const leads = label[0]?.startsWith(typed[0]) ? 0 : 1;
      return { entry, rank: [inLabel, leads, index] };
    })
    .filter((hit) => hit !== null)
    .sort((a, b) => a.rank[0] - b.rank[0] || a.rank[1] - b.rank[1] || a.rank[2] - b.rank[2])
    .map((hit) => hit.entry);
}

/** A modal already open (the palette itself, Stop all, a review sheet, the phone's room drawer):
 * the shortcut leaves it alone rather than stacking another on top. */
const OPEN_MODAL = 'dialog[open], [role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]';

/** Whether a key press opens the palette: Ctrl/⌘ K with focus in the dashboard (or on nothing),
 * or "/" there when focus is not in a field, where it is a character; never while another modal
 * is open. */
export function paletteKey(
  e: { key: string; ctrlKey: boolean; metaKey: boolean; target: EventTarget | null },
  panel: Element,
): "open" | null {
  const target = e.target as (Node & { tagName?: string; isContentEditable?: boolean }) | null;
  if (!target) return null;
  const inside = panel.contains(target) || target === panel.ownerDocument?.body;
  if (!inside) return null;
  if (panel.ownerDocument?.querySelector(OPEN_MODAL)) return null;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") return "open";
  if (e.key !== "/" || e.ctrlKey || e.metaKey) return null;
  const field =
    target.isContentEditable === true ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName ?? "");
  return field ? null : "open";
}

/** The shortcut as the keyboard prints it: ⌘ K on a Mac, iPhone or iPad, Ctrl K elsewhere. */
export function shortcutHint(platform: string): string {
  return /Mac|iPhone|iPad|iPod/.test(platform) ? "⌘ K" : "Ctrl K";
}

/** Where focus goes when the palette closes: back where it was, unless a jump took that element
 * off the page with its old page; then the Jump to… button. */
export function focusAfterClose(opener: HTMLElement | null, button: HTMLElement | null): HTMLElement | null {
  return opener?.isConnected ? opener : button;
}
