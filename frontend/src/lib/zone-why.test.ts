import { describe, expect, it } from "vitest";
import { aiRead, zoneReasons } from "./zone-why";
import type { JevZoneJudge } from "./jev";
import type { EntityState } from "./types";

const decision = (fired: string[], blocked: string[]): EntityState => ({
  entity_id: "sensor.crop_steering_current_decision",
  state: "Holding",
  attributes: { fired, blocked },
});
const zone = { id: 2, status: "Holding — within target band", stale: false };
const judge = (name: string, why: string): JevZoneJudge => ({
  judge: name,
  title: name.toUpperCase(),
  answer: "",
  p: null,
  agreed: null,
  directive: "",
  why,
});

describe("why a zone is doing what it is doing", () => {
  it("gives the controller's status, then this zone's shot fired or held, never another zone's", () => {
    expect(
      zoneReasons(zone, decision(["Z1 P1 ramp shot 3/6", "Z2 P2 top-up"], ["Z12 P2 cap"])),
    ).toEqual(["Holding — within target band", "Watered at this check: top-up"]);
    expect(zoneReasons(zone, decision([], ["Z2 P2 daily water cap reached"]))).toEqual([
      "Holding — within target band",
      "Held at this check: daily water cap reached",
    ]);
  });
  it("says a stale status is the last report, and says nothing it was not told", () => {
    expect(zoneReasons({ ...zone, stale: true }, undefined)).toEqual([
      "Last report: Holding — within target band",
    ]);
    expect(zoneReasons({ ...zone, status: "Unavailable" }, decision([], []))).toEqual([]);
  });
});

describe("the AI's read of a zone", () => {
  it("prefers a judge acting on the zone, and is null when no judge gave a reason", () => {
    const judges = [judge("night", "Drying is real."), judge("salt", "Pore EC is climbing.")];
    expect(aiRead(judges, ["salt"])).toEqual({ title: "SALT", why: "Pore EC is climbing." });
    expect(aiRead(judges, [])).toEqual({ title: "NIGHT", why: "Drying is real." });
    expect(aiRead([judge("dawn", "")], ["dawn"])).toBeNull();
  });
});
