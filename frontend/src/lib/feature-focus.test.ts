import { describe, expect, it } from "vitest";
import { featureLabel, featureOf, featureTargets, roomOnlyFeature } from "./feature-focus";

describe("feature links", () => {
  it("reads the feature an address names", () => {
    expect(featureOf("#/settings?feature=water_today_view")).toBe("water_today_view");
    expect(featureOf("#/today")).toBeNull();
  });
  it("lands on the feature's card first, then its controls' editors in this room", () => {
    const ids = featureTargets("steering_mode", "room_b_", [1, 2]);
    expect(ids[0]).toBe("config-steering_mode");
    expect(ids).toContain("choice-select.crop_steering_room_b_steering_mode");
    expect(ids).toContain("choice-select.crop_steering_room_b_zone_2_steering_mode");
    expect(featureTargets("p0", "", [1])).toContain(
      "setting-number.crop_steering_zone_1_p0_maximum_wait_time",
    );
  });
  it("knows a feature with only room controls, which a room view shows", () => {
    expect(roomOnlyFeature("photoperiod")).toBe(true);
    expect(roomOnlyFeature("steering_mode")).toBe(false);
    expect(roomOnlyFeature(null)).toBe(false);
  });
  it("names the feature it opened at, for a screen reader", () => {
    expect(featureLabel("photoperiod")).toBe("Lights schedule");
    expect(featureLabel("nothing")).toBeNull();
  });
});
