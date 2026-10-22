import { describe, expect, it, vi } from "vitest";
import { overlayLabel, overlayText, undoKept, zoneOverlays, type Overlay } from "./overlays";

const at = (hour: number, day = 15) => new Date(2026, 9, day, hour, 48).toISOString();
const overlay = (zone: number | null, field = "p2_shot_size"): Overlay => ({
  entity_id: `number.crop_steering_zone_${zone}_${field}`,
  zone,
  field,
  old: 4.5,
  new: 4,
  by: "brain",
  at: at(22, 14),
  expires: at(6),
});
const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const doc = (overlays: Overlay[]) => ({
  schema_version: 1,
  room_id: "room:",
  overlays,
  error: null,
});

describe("AI overlays on a zone", () => {
  it("names the setting in grower words, not its key", () => {
    expect(overlayLabel(overlay(1))).toBe("Maintenance shot size");
    expect(overlayLabel(overlay(1, "made_up_field"))).toBe("made up field");
  });
  it("says when the AI set it and when it goes back", () => {
    const now = new Date(2026, 9, 14, 23, 0).getTime();
    expect(overlayText(overlay(1), now)).toBe(
      `Set by AI ${clock(at(22, 14))} · goes back at lights-on tomorrow ${clock(at(6))}`,
    );
    const morning = new Date(2026, 9, 15, 1, 0).getTime();
    expect(overlayText(overlay(1), morning)).toBe(
      `Set by AI Yesterday ${clock(at(22, 14))} · goes back at lights-on ${clock(at(6))}`,
    );
  });
  it("lists only this zone's overlays in this room", () => {
    const rows = doc([overlay(1), overlay(2), overlay(null)]);
    expect(zoneOverlays(rows, "room:", 2).map((row) => row.zone)).toEqual([2]);
    expect(zoneOverlays(rows, "room:other_", 2)).toEqual([]);
    expect(zoneOverlays(null, "room:", 1)).toEqual([]);
  });
});

describe("undoing a kept AI change", () => {
  const kept = overlay(2);
  const states = (value: string) => ({
    [kept.entity_id]: { entity_id: kept.entity_id, state: value, attributes: {} },
  });
  it("writes the grower's own value back while the setting still holds the AI's", async () => {
    const write = vi.fn(async () => ({ applied: [kept.entity_id], failed: [] }));
    await undoKept(kept, () => states("4"), write);
    expect(write).toHaveBeenCalledWith([{ entityId: kept.entity_id, value: 4.5 }]);
  });
  it("refuses, writing nothing, once the value has changed since", async () => {
    const write = vi.fn(async () => ({ applied: [kept.entity_id], failed: [] }));
    await expect(undoKept(kept, () => states("3.8"), write)).rejects.toThrow(
      "This value has changed since you applied it. Nothing was undone.",
    );
    expect(write).not.toHaveBeenCalled();
  });
  it("says why when the write is not read back", async () => {
    const write = vi.fn(async () => ({ applied: [], failed: [{ entityId: kept.entity_id, reason: "Read back 4." }] }));
    await expect(undoKept(kept, () => states("4"), write)).rejects.toThrow("Read back 4.");
  });
});

describe("undoing a kept AI change, as Home Assistant reads it back", () => {
  const kept = { ...overlay(2, "ec_target_veg_p2"), old: 3.8, new: 3.4000000000000004 };
  const states = (value: string) => ({
    [kept.entity_id]: { entity_id: kept.entity_id, state: value, attributes: { step: 0.1 } },
  });
  it("takes the rounded state as the AI's value", async () => {
    const write = vi.fn(async () => ({ applied: [kept.entity_id], failed: [] }));
    await undoKept(kept, () => states("3.4"), write);
    expect(write).toHaveBeenCalledOnce();
  });
  it("refuses a state that is not a number", async () => {
    const write = vi.fn(async () => ({ applied: [kept.entity_id], failed: [] }));
    await expect(undoKept(kept, () => states("unavailable"), write)).rejects.toThrow(
      "This value has changed since you applied it. Nothing was undone.",
    );
    expect(write).not.toHaveBeenCalled();
  });
});
