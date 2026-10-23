import { describe, expect, test } from "vitest";
import { buildRoom } from "./model";
import { NAV_TREE } from "./nav-tree";
import { routeHash } from "./routes";
import { demoController } from "./test-helpers";
import { paletteEntries, paletteKey, searchPalette } from "./command-palette";

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
});
