import { describe, expect, it } from "vitest";
import { discoverRooms, runningVersions } from "./model";
import type { States } from "./types";

const entity = (entity_id: string, attributes: Record<string, unknown>) => ({
  entity_id,
  state: "ok",
  attributes,
  last_updated: new Date().toISOString(),
});

function states(
  prefix: string,
  descriptor: Record<string, unknown>,
  heartbeat: Record<string, unknown>,
): States {
  const list = [
    entity(`sensor.crop_steering_${prefix}engine_config`, { prefix, num_zones: 1, ...descriptor }),
    entity(`sensor.crop_steering_${prefix}ai_heartbeat`, heartbeat),
  ];
  return Object.fromEntries(list.map((e) => [e.entity_id, e])) as States;
}

describe("running versions", () => {
  it("reads the integration from the room descriptor and the controller from its heartbeat", () => {
    const s = states("", { integration_version: "2.19.1" }, { controller_version: "0.16.1" });
    const [room] = discoverRooms(s);
    expect(runningVersions(s, room)).toEqual({ integration: "2.19.1", controller: "0.16.1" });
  });

  it("keeps rooms apart: a named room reports its own entities", () => {
    const s = {
      ...states("", { integration_version: "2.19.1" }, { controller_version: "0.16.1" }),
      ...states("veg_", { integration_version: "2.19.1", slug: "veg" }, {}),
    } as States;
    const veg = discoverRooms(s).find((room) => room.prefix === "veg_")!;
    expect(runningVersions(s, veg)).toEqual({ integration: "2.19.1", controller: null });
  });

  it("says nothing rather than guessing when a half does not report", () => {
    // an integration or controller from before this existed, or a controller that is not running
    const s = states("", {}, { controller_version: "unknown" });
    const [room] = discoverRooms(s);
    expect(runningVersions(s, room)).toEqual({ integration: null, controller: null });
    const junk = states("", { integration_version: 2 }, { controller_version: "  " });
    expect(runningVersions(junk, discoverRooms(junk)[0])).toEqual({
      integration: null,
      controller: null,
    });
  });
});
