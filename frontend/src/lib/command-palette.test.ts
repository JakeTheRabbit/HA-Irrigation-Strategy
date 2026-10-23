import { describe, expect, test } from "vitest";
import { buildRoom } from "./model";
import { NAV_TREE } from "./nav-tree";
import { routeHash } from "./routes";
import { demoController } from "./test-helpers";
import { focusAfterClose, paletteEntries, paletteKey, searchPalette, shortcutHint } from "./command-palette";

/** The demo, with its two rooms named as the mockups name them: F2 (selected) and F1. */
function controller() {
  const demo = demoController("?demo=1");
  const names = ["F2", "F1"];
  const rooms = demo.rooms.map((room, i) => ({ ...room, name: names[i] ?? room.name }));
  return { ...demo, rooms, room: buildRoom(demo.states, rooms[0]), roomId: rooms[0].id };
}

const key = (k: string, target: unknown, mods: { ctrlKey?: boolean; metaKey?: boolean } = {}) => ({
  key: k,
  ctrlKey: mods.ctrlKey ?? false,
  metaKey: mods.metaKey ?? false,
  target: target as EventTarget | null,
});

describe("the jump-to palette", () => {
  test('searchPalette "cal ph" finds Calibrate F2 feed pH first', () => {
    const found = searchPalette(paletteEntries(controller()), "cal ph");
    expect(found[0].label).toBe("Calibrate F2 feed pH");
    expect(found[0].hash).toBe("#/equipment/feed-calibration");
    // Every word must match: "cal ph" never offers a pump.
    expect(found.some((e) => e.label === "Prime a dosing pump")).toBe(false);
  });

  test("entries include every NAV_TREE page and every zone", () => {
    const c = controller();
    const entries = paletteEntries(c);
    for (const item of NAV_TREE.flatMap((s) => s.items))
      expect(entries.some((e) => e.label === item.label && e.hash === routeHash({ page: item.page })), item.label).toBe(true);
    let zones = 0;
    for (const room of c.rooms)
      for (const zone of buildRoom(c.states, room).zones) {
        zones += 1;
        const entry = entries.find((e) => e.label === `${room.name} · ${zone.name}`);
        expect(entry, `${room.name} ${zone.name}`).toBeDefined();
        expect(entry!.hash).toBe(`#/zone/${zone.id}`);
        expect(entry!.room).toBe(room.id);
      }
    expect(zones).toBeGreaterThanOrEqual(4);
    for (const action of ["Calibrate F2 feed pH", "Prime a dosing pump", "New alert rule", "New timer program"])
      expect(entries.some((e) => e.label === action), action).toBe(true);
    expect(entries.find((e) => e.label === "New alert rule")!.hash).toBe("#/settings/alerts?rule=new");
  });

  test("searchPalette: an empty query lists everything, a word no entry has finds nothing", () => {
    const entries = paletteEntries(controller());
    expect(searchPalette(entries, "  ")).toEqual(entries);
    expect(searchPalette(entries, "zzzz")).toEqual([]);
    expect(searchPalette(entries, "changes")[0].hash).toBe("#/history/changes");
    expect(searchPalette(entries, "f1 zone 2")[0].label).toBe("F1 · Zone 2");
  });

  test("paletteKey ignores Ctrl K outside the panel and / inside an input", () => {
    const inside = { tagName: "BUTTON" };
    const input = { tagName: "INPUT" };
    const outside = { tagName: "DIV" };
    const panel = { contains: (t: unknown) => t === inside || t === input } as unknown as Element;
    expect(paletteKey(key("k", inside, { ctrlKey: true }), panel)).toBe("open");
    expect(paletteKey(key("K", inside, { metaKey: true }), panel)).toBe("open");
    expect(paletteKey(key("k", outside, { ctrlKey: true }), panel)).toBeNull();
    expect(paletteKey(key("k", inside), panel)).toBeNull();
    expect(paletteKey(key("/", inside), panel)).toBe("open");
    expect(paletteKey(key("/", input), panel)).toBeNull();
    expect(paletteKey(key("/", { tagName: "TEXTAREA" }), panel)).toBeNull();
    expect(paletteKey(key("/", { tagName: "SELECT" }), panel)).toBeNull();
    expect(paletteKey(key("/", { tagName: "DIV", isContentEditable: true }), panel)).toBeNull();
    expect(paletteKey(key("/", outside), panel)).toBeNull();
    // Ctrl K from a field still opens it: the shortcut is no character a field takes.
    expect(paletteKey(key("k", input, { ctrlKey: true }), panel)).toBe("open");
  });

  test("paletteKey opens from the document body, outside the panel's own element", () => {
    const body = { tagName: "BODY" };
    const panel = { contains: () => false, ownerDocument: { body, querySelector: () => null } } as unknown as Element;
    expect(paletteKey(key("k", body, { ctrlKey: true }), panel)).toBe("open");
    expect(paletteKey(key("/", body), panel)).toBe("open");
    expect(paletteKey(key("/", { tagName: "DIV" }), panel)).toBeNull();
  });

  test("paletteKey does nothing while another modal (Stop all, a review) is open", () => {
    const inside = { tagName: "BUTTON" };
    const selectors: string[] = [];
    const panel = {
      contains: () => true,
      ownerDocument: {
        querySelector: (selector: string) => {
          selectors.push(selector);
          return {};
        },
      },
    } as unknown as Element;
    expect(paletteKey(key("k", inside, { ctrlKey: true }), panel)).toBeNull();
    expect(paletteKey(key("/", inside), panel)).toBeNull();
    expect(selectors[0]).toContain("dialog[open]");
  });

  test("Calibrate <room> feed pH/EC is listed only for a room mapping that feed probe", () => {
    const c = controller();
    const labels = paletteEntries(c).map((e) => e.label);
    // F2 (Room A) maps both feed probes; F1 (Room B) maps none.
    expect(labels).toContain("Calibrate F2 feed pH");
    expect(labels).toContain("Calibrate F2 feed EC");
    expect(labels.filter((l) => l.startsWith("Calibrate F1"))).toEqual([]);
    const config = `sensor.crop_steering_${c.rooms[0].prefix}engine_config`;
    const state = c.states[config];
    const onlyEc = {
      ...c,
      states: { ...c.states, [config]: { ...state, attributes: { ...state.attributes, feed_ph_sensor: "" } } },
    };
    const calibrate = paletteEntries(onlyEc).filter((e) => e.label.startsWith("Calibrate"));
    expect(calibrate.map((e) => e.label)).toEqual(["Calibrate F2 feed EC"]);
  });

  test("shortcutHint names Cmd on a Mac and Ctrl elsewhere", () => {
    expect(shortcutHint("MacIntel")).toBe("⌘ K");
    expect(shortcutHint("iPad")).toBe("⌘ K");
    expect(shortcutHint("Win32")).toBe("Ctrl K");
    expect(shortcutHint("Linux x86_64")).toBe("Ctrl K");
    expect(shortcutHint("")).toBe("Ctrl K");
  });

  test("focusAfterClose returns to the opener while it is still on the page, else the Jump to… button", () => {
    const button = { isConnected: true } as HTMLElement;
    const kept = { isConnected: true } as HTMLElement;
    const gone = { isConnected: false } as HTMLElement;
    expect(focusAfterClose(kept, button)).toBe(kept);
    expect(focusAfterClose(gone, button)).toBe(button);
    expect(focusAfterClose(null, button)).toBe(button);
  });
});

test("the prime action names the pump page as the menu does", () => {
  const prime = paletteEntries(demoController("?demo=1")).find((e) => e.label === "Prime a dosing pump");
  expect(prime?.hint).toBe("Equipment › Prime & calibrate a pump");
});
