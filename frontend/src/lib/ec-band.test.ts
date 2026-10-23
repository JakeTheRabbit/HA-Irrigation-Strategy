import { describe, expect, it } from "vitest";
import { ecTargetBand, poreEcNeutral } from "./ec-band";

const beat = (attributes: Record<string, unknown>) => ({
  "sensor.crop_steering_room_b_ai_heartbeat": {
    entity_id: "sensor.crop_steering_room_b_ai_heartbeat",
    state: "healthy",
    attributes,
  },
});

describe("the pore-EC band around a target", () => {
  it("is where the controller leaves a shot's size alone, as its heartbeat publishes it", () => {
    const neutral = poreEcNeutral(beat({ pore_ec_neutral: [0.8, 1.0] }), "room_b_");
    expect(neutral).toEqual([0.8, 1.0]);
    expect(ecTargetBand(neutral, 3)).toEqual([2.4000000000000004, 3]);
  });
  it("is one band for every page, never a width the dashboard picks", () => {
    expect(poreEcNeutral(beat({}), "room_b_")).toBeNull();
    expect(poreEcNeutral(beat({ pore_ec_neutral: [1.2, 0.8] }), "room_b_")).toBeNull();
    expect(ecTargetBand(null, 3)).toBeNull();
    expect(ecTargetBand([0.8, 1], 0)).toBeNull();
    expect(ecTargetBand([0.8, 1], NaN)).toBeNull();
  });
});
