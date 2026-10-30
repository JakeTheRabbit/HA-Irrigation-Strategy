import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, test, vi } from "vitest";
import { RoomTree } from "@/components/room-tree";
import { createDemo } from "./demo";
import { pickKey } from "./facility";
import { discoverRooms } from "./model";
import { fakeController } from "./test-helpers";
import type { States } from "./types";

function controller(extra: States = {}) {
  const states = { ...createDemo(Date.now()), ...extra };
  return fakeController({ states, rooms: discoverRooms(states), roomId: "room:" });
}
const noop = () => {};
const tree = (extra: Record<string, unknown> = {}, states: States = {}) =>
  renderToStaticMarkup(
    createElement(RoomTree, {
      controller: controller(states),
      allRooms: false,
      currentZone: null,
      openRoom: noop,
      openZone: noop,
      ...extra,
    }),
  );
const pick = (selected: string[]) => ({
  title: "Copy to which room?",
  selected: new Set(selected),
  onChange: noop,
  onDone: noop,
  onCancel: noop,
});

afterEach(() => vi.unstubAllGlobals());

describe("RoomTree", () => {
  test("timer-mode zone shows T badge", () => {
    const out = tree(
      {},
      {
        "select.crop_steering_zone_2_irrigation_mode": {
          entity_id: "select.crop_steering_zone_2_irrigation_mode",
          state: "timer",
          attributes: { options: ["steering", "timer", "off"] },
        },
      },
    );
    expect(out).toMatch(/data-mode="timer"[^>]*>T</);
    expect(out.match(/data-mode="timer"/g)).toHaveLength(1);
  });

  test("room rows flag open alerts", () => {
    const out = tree(
      {},
      {
        "sensor.crop_steering_alerts_open": {
          entity_id: "sensor.crop_steering_alerts_open",
          state: "1",
          attributes: {
            alerts: [
              {
                event_id: "e",
                ts: "2026-10-22T10:00:00Z",
                code: null,
                title: "Feed pH high",
                zone: null,
                entity_id: null,
                acknowledged: false,
              },
            ],
          },
        },
      },
    );
    expect(out).toMatch(
      /data-room="room:"[^>]*data-alerts="1"|data-alerts="1"[^>]*data-room="room:"/,
    );
    expect(out).toContain("1 open alert");
    expect(out).not.toMatch(/data-room="room:room_b_"[^>]*data-alerts/);
  });

  test("room tree pick mode renders checkboxes and Done", () => {
    const out = tree({ pick: pick(["room:room_b_", pickKey("room:", 1)]) });
    expect(out).toContain("Copy to which room?");
    expect(out.match(/type="checkbox"/g)!.length).toBeGreaterThanOrEqual(4);
    expect(out).toMatch(
      /<input type="checkbox"[^>]*checked=""[^>]*value="room:room_b_"|value="room:room_b_"[^>]*checked=""/,
    );
    expect(out).toContain(">Done<");
    expect(out).toContain(">Cancel<");
    expect(out).not.toContain("<dialog");
  });

  test("pick mode on phone renders a dialog", () => {
    vi.stubGlobal("window", { matchMedia: () => ({ matches: true }) });
    const out = tree({ pick: pick([]) });
    expect(out).toMatch(/<dialog[^>]*class="room-tree-sheet"/);
    expect(out).toContain('type="checkbox"');
    expect(out).toContain(">Done<");
    // Out of pick mode the phone tree stays an ordinary list.
    expect(tree()).not.toContain("<dialog");
  });
});
