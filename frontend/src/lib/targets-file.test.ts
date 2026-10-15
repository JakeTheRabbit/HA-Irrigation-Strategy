import { describe, expect, it } from "vitest";
import { exportTargets, loadTargets, readTargets, targetsFileName } from "./targets-file";
import type { Choice, RoomView, Setting, Zone } from "./types";

const setting = (id: string, value: number, extra: Partial<Setting> = {}): Setting => ({
  entityId: `number.crop_steering_${id}`,
  label: id,
  description: "",
  value,
  min: 0,
  max: 100,
  step: 1,
  unit: "%",
  group: "Targets",
  ...extra,
});
const mode = (id: string, value: string): Choice => ({
  entityId: `select.crop_steering_${id}`,
  label: id,
  value,
  options: ["Vegetative", "Generative"],
});
const room = (prefix: string, zoneIds: number[], value = 30): RoomView =>
  ({
    room: { id: prefix || "room", name: `Room ${prefix || "one"}`, prefix },
    zones: zoneIds.map((id) => ({ id, name: `Zone ${id}` }) as Zone),
    settings: [
      setting(`${prefix}lights_on_hour`, 6),
      ...zoneIds.flatMap((id) => [
        setting(`${prefix}zone_${id}_p2_vwc_threshold`, value + id),
        setting(`${prefix}zone_${id}_substrate_volume`, 5),
      ]),
    ],
    choices: zoneIds.map((id) => mode(`${prefix}zone_${id}_steering_mode`, "Vegetative")),
  }) as RoomView;

describe("a targets file", () => {
  it("keeps settings by name and zone number, without hardware sizing", () => {
    const file = readTargets(exportTargets(room("a_", [1, 2]), "2026-10-15T06:00:00Z"));
    expect(file.room_settings).toEqual({ lights_on_hour: 6 });
    expect(file.zones["2"]).toEqual({
      name: "Zone 2",
      settings: { p2_vwc_threshold: 32, steering_mode: "Vegetative" },
    });
  });

  it("loads into another room's draft only what differs, and never its lights hours", () => {
    const source = room("a_", [1, 2], 40);
    source.settings[0].value = 8;
    source.choices[1].value = "Generative";
    const target = room("b_", [1, 2]);
    const loaded = loadTargets(readTargets(exportTargets(source, "")), target);
    expect(Object.keys(loaded.drafts).sort()).toEqual([
      "number.crop_steering_b_zone_1_p2_vwc_threshold",
      "number.crop_steering_b_zone_2_p2_vwc_threshold",
      "select.crop_steering_b_zone_2_steering_mode",
    ]);
    expect(loaded.drafts["number.crop_steering_b_zone_1_p2_vwc_threshold"]).toMatchObject({
      value: "41",
      original: 31,
      zone: "Zone 1",
    });
    expect(loaded.left).toEqual(["b_lights_on_hour"]);
    expect(loaded.zoneMismatch).toBeNull();
  });

  it("warns when the file has more zones than the room, and loads none of the extra", () => {
    const loaded = loadTargets(
      readTargets(exportTargets(room("", [1, 2, 3], 40), "")),
      room("", [1, 2]),
    );
    expect(loaded.zoneMismatch).toBe(
      "The file has 3 zones and this room has 2 zones: the extra zones are not loaded.",
    );
    expect(loaded.missingZones).toEqual(["Zone 3"]);
    expect(Object.keys(loaded.drafts).some((id) => id.includes("zone_3"))).toBe(false);
  });

  it("warns when the file has fewer zones than the room, and leaves the rest alone", () => {
    const loaded = loadTargets(readTargets(exportTargets(room("", [1], 40), "")), room("", [1, 2]));
    expect(loaded.zoneMismatch).toBe(
      "The file has 1 zone and this room has 2 zones: zones not in the file keep their targets.",
    );
    expect(Object.keys(loaded.drafts)).toEqual(["number.crop_steering_zone_1_p2_vwc_threshold"]);
  });

  it("rounds to the room's steps and skips what is outside its limits", () => {
    const source = room("", [1, 2]);
    source.settings[1].value = 33.4;
    source.settings[3].value = 150;
    const loaded = loadTargets(readTargets(exportTargets(source, "")), room("", [1, 2]));
    expect(loaded.rounded).toEqual(["Zone 1 · zone_1_p2_vwc_threshold 33.4 → 33"]);
    expect(loaded.skipped).toEqual([
      "Zone 2 · zone_2_p2_vwc_threshold 150: this room takes 0 to 100",
    ]);
  });

  it("refuses a file that is not a targets file, or from a newer version", () => {
    expect(() => readTargets("not json")).toThrow("isn’t a crop-steering targets file");
    expect(() => readTargets(JSON.stringify({ format: "other" }))).toThrow("targets file");
    expect(() =>
      readTargets(
        JSON.stringify({
          format: "crop-steering-targets",
          version: 2,
          room_settings: {},
          zones: {},
        }),
      ),
    ).toThrow("newer version");
  });

  it("is named after the room and the date", () => {
    expect(targetsFileName("Flower Room 2", "2026-10-15")).toBe(
      "crop-steering-targets-flower-room-2-2026-10-15.json",
    );
  });
});
