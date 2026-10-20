import { describe, expect, it } from "vitest";
import { allZones, allZonesChanges } from "./all-zones";
import type { Zone } from "./types";

const zone = (id: number, enabled: boolean | null, entity = true) =>
  ({
    id,
    name: `Zone ${id}`,
    enabled,
    enabledEntity: entity ? `switch.crop_steering_zone_${id}_enabled` : null,
  }) as Zone;

describe("the room's switch over every zone", () => {
  it("is on while any zone is on, as the entities card's header toggle is", () => {
    expect(allZones([zone(1, true), zone(2, false)])).toEqual({ checked: true, on: 1, known: 2 });
    expect(allZones([zone(1, false), zone(2, false)])).toEqual({ checked: false, on: 0, known: 2 });
  });
  it("counts only zones whose switch reads on or off, and knows nothing without one", () => {
    expect(allZones([zone(1, true), zone(2, null), zone(3, true, false)])).toEqual({
      checked: true,
      on: 1,
      known: 1,
    });
    expect(allZones([zone(1, null)]).checked).toBeNull();
    expect(allZones([]).checked).toBeNull();
  });
  it("switched off, pauses every zone that is on", () => {
    expect(allZonesChanges([zone(1, true), zone(2, false), zone(3, true)], false)).toEqual([
      {
        change: { entityId: "switch.crop_steering_zone_1_enabled", value: false },
        label: "Zone 1 scheduling",
        before: "Enabled",
        after: "Paused",
      },
      {
        change: { entityId: "switch.crop_steering_zone_3_enabled", value: false },
        label: "Zone 3 scheduling",
        before: "Enabled",
        after: "Paused",
      },
    ]);
  });
  it("switched on, switches every zone on, one paused on purpose included", () => {
    const changes = allZonesChanges([zone(1, false), zone(2, false), zone(3, null)], true);
    expect(changes.map((item) => [item.change.entityId, item.change.value, item.before])).toEqual([
      ["switch.crop_steering_zone_1_enabled", true, "Paused"],
      ["switch.crop_steering_zone_2_enabled", true, "Paused"],
    ]); // an unreadable switch is not written blind
  });
});
