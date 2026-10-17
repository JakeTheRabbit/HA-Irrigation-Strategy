import { describe, expect, it } from "vitest";
import {
  initialRoute,
  landingView,
  readLandingView,
  saveLandingView,
  LANDING_KEY,
} from "./landing-view";
import { facilityRooms } from "./facility";
import { createDemo } from "./demo";
import { discoverRooms } from "./model";

describe("default landing view", () => {
  it("defaults to every zone and rejects invalid or retired saved values", () => {
    expect(landingView(null)).toBe("all-zones");
    expect(landingView("bad")).toBe("all-zones");
    expect(landingView("plan/schedule")).toBe("plan/schedule");
    expect(initialRoute("", "", null).page).toBe("all-zones");
  });
  it("uses a preference only on an unaddressed entry and preserves explicit links", () => {
    expect(initialRoute("", "", "history/water").page).toBe("history/water");
    expect(initialRoute("#/zone/2", "", "history/water")).toEqual({ page: "zone", zone: 2 });
    expect(initialRoute("", "?view=help", "history/water").page).toBe("help");
    expect(initialRoute("#/plan/schedule", "", "all-zones").page).toBe("plan/schedule");
  });
  it("does not break startup if browser storage is denied", () => {
    const blocked = {
      getItem() {
        throw Error("blocked");
      },
      setItem() {
        throw Error("blocked");
      },
    };
    expect(readLandingView(blocked)).toBe("all-zones");
    expect(saveLandingView("today", blocked)).toBe(false);
  });
  it("persists exactly the selected browser preference", () => {
    const map = new Map<string, string>();
    const storage = {
      getItem: (k: string) => map.get(k) ?? null,
      setItem: (k: string, v: string) => {
        map.set(k, v);
      },
    };
    expect(saveLandingView("today", storage)).toBe(true);
    expect(map.get(LANDING_KEY)).toBe("today");
    expect(readLandingView(storage)).toBe("today");
  });
});
describe("facility zones", () => {
  it("includes inactive rooms and duplicate zone numbers without cross-room mixing", () => {
    const states = createDemo();
    const rooms = discoverRooms(states);
    const roomActiveId = `switch.crop_steering_${rooms[1].prefix}room_active`;
    states[roomActiveId] = { entity_id: roomActiveId, state: "off", attributes: {} };
    const views = facilityRooms(states, rooms);
    expect(views[1].view.roomActive).toBe(false);
    expect(views).toHaveLength(rooms.length);
    expect(views.length).toBeGreaterThan(1);
    for (const item of views) {
      expect(item.view.room.id).toBe(item.room.id);
      expect(item.view.zones.length).toBeGreaterThan(0);
    }
    expect(
      new Set(views.flatMap((r) => r.view.zones.map((z) => `${r.room.id}/${z.id}`))).size,
    ).toBe(views.reduce((n, r) => n + r.view.zones.length, 0));
  });
});
