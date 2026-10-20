import { describe, expect, it } from "vitest";
import { changeEvents, type SetpointChange, type SetpointLogDocument } from "./setpoint-log";
import { filterTimeline, mergeTimeline, NO_FILTER } from "./timeline";

const change = (who: SetpointChange["who"], at: string, zone: number | null = 1): SetpointChange => ({
  at,
  entity_id: "number.crop_steering_zone_1_p2_vwc_threshold",
  field: "p2_vwc_threshold",
  zone,
  old: 40.4,
  new: 41.4,
  who,
});
const doc = (changes: SetpointChange[]): SetpointLogDocument => ({
  schema_version: 1,
  room_id: "room:",
  changes,
  error: null,
  max_changes: 2000,
});

describe("the setpoint change log on the Timeline", () => {
  it("names every writer in words, with the setting and its old and new value", () => {
    const rows = changeEvents(
      doc([
        change("operator", "2026-10-15T08:00:00+00:00"),
        change("learner", "2026-10-15T09:00:00+00:00"),
        change("brain", "2026-10-15T10:00:00+00:00"),
        change("safety", "2026-10-15T11:00:00+00:00", null),
      ]),
    );
    expect(rows.map((row) => row.message)).toEqual([
      "By hand: p2 vwc threshold 40.4 → 41.4",
      "Auto setpoints: p2 vwc threshold 40.4 → 41.4",
      "AI assistant: p2 vwc threshold 40.4 → 41.4",
      "Put back for safety: p2 vwc threshold 40.4 → 41.4",
    ]);
    expect(rows.map((row) => row.zoneId)).toEqual([1, 1, 1, undefined]);
  });
  it("is a setpoint row, newest first, whatever the words say", () => {
    const now = Date.parse("2026-10-15T12:00:00Z");
    const items = mergeTimeline(
      changeEvents(
        doc([change("operator", "2026-10-15T08:00:00Z"), change("brain", "2026-10-15T10:00:00Z")]),
      ),
      [],
      now,
    );
    expect(items.map((item) => [item.kind, item.event?.message.split(":")[0]])).toEqual([
      ["setpoint", "AI assistant"],
      ["setpoint", "By hand"],
    ]);
    expect(filterTimeline(items, { ...NO_FILTER, type: "setpoint" })).toHaveLength(2);
  });
  it("is empty for an integration with no change log", () => {
    expect(changeEvents(null)).toEqual([]);
    expect(changeEvents(doc([]))).toEqual([]);
  });
});
