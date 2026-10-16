import { describe, expect, it } from "vitest";
import { climateBands, cleanReference, withReference, type Reference } from "./plan-reference";
import type { SteeringProfile } from "./operator-types";

const profile: SteeringProfile = { id: "a", name: "A", vegetative: {}, generative: {} };
describe("plan reference rows", () => {
  it("keeps whole bands inside their range only", () => {
    expect(
      cleanReference({ humidity: [55, 65], vpd: [2, 1], co2: [0, 9000], feed_ph: [5.6, 6.2] }),
    ).toEqual({ humidity: [55, 65], feed_ph: [5.6, 6.2] });
  });
  it("leaves a profile without bands as a plan from before them", () => {
    expect(withReference(profile, {})).toEqual(profile);
    expect("reference" in withReference({ ...profile, reference: { vpd: [1, 1.2] } }, {})).toBe(false);
    expect(withReference(profile, { vpd: [1, 1.2] }).reference).toEqual({ vpd: [1, 1.2] });
  });
  it("gives the day or night temperature by the lights", () => {
    const reference: Reference = { temp_day: [24, 28], temp_night: [19, 22] };
    expect(climateBands({ ...reference }, true).temperature).toEqual([24, 28]);
    expect(climateBands({ ...reference }, false).temperature).toEqual([19, 22]);
  });
});
