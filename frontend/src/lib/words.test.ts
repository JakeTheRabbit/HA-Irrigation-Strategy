import { describe, expect, it } from "vitest";
import { createDemo, demoDay } from "./demo";
import { growDay, timelineEntities, valveShots } from "./day-timeline";
import { jevAnswer, jevChangeText, parseJevSetpoints, parseJevZone, readJev } from "./jev";
import { buildRoom, discoverRooms, eventsForRoom } from "./model";
import { mergeTimeline, timelineResult, timelineText } from "./timeline";
import { growerWords } from "./words";

/** The controller's and the brain's own tokens, which must never reach a grower's screen. */
const TOKENS = /p[0-3]_|_threshold|\bvwc\b|pwec|enter p/;

describe("grower words", () => {
  it("names a setting the way the Irrigation plan does", () => {
    expect(growerWords("setpoint p2_shot_size 4")).toBe("setpoint maintenance shot 4");
    expect(growerWords("p2 vwc threshold 62 -> 61")).toBe("re-water point 62 -> 61");
    expect(growerWords("zone_2_p3_emergency_vwc_threshold below")).toBe("rescue floor below");
    expect(growerWords("vegetative_dryback_target 30")).toBe("P3 dryback target 30");
  });
  it("says what a phase call does", () => {
    expect(growerWords("enter p3 now")).toBe("end the day's watering now");
    expect(growerWords("enter_p3_now")).toBe("end the day's watering now");
    expect(growerWords("continue p2")).toBe("keep watering through the day");
    expect(growerWords("one_more_topup_then_p3")).toBe(
      "one more top-up, then end the day's watering",
    );
    expect(growerWords("enter p1")).toBe("move to P1");
  });
  it("names the controller's rules and the probe's readings", () => {
    expect(growerWords("p2_topup: vwc 58 < 61")).toBe("maintenance shot: moisture 58 < 61");
    expect(growerWords("p3_emergency")).toBe("rescue shot");
    expect(growerWords("pwec 6.2 over the band")).toBe("pore EC 6.2 over the band");
  });
  it("leaves grower words, alert codes, phase badges and the VWC unit alone", () => {
    for (const text of [
      "P1 → P2: target VWC reached (demo).",
      "CS-705: this zone is off the stage's arc",
      "Peak VWC target 64 -> 66",
      "inside the AI assistant's range 3.5–5.5%",
    ])
      expect(growerWords(text)).toBe(text);
  });
});

describe("no engine token reaches the demo's screens", () => {
  // Seven hours after Room A's lights-on: its day has every kind of decision and shot.
  const now = new Date(2026, 8, 23, 17, 0).getTime();
  const states = createDemo(now);
  const rooms = discoverRooms(states);
  it("on the Timeline, Today's changes and a zone's decisions", () => {
    const shown: string[] = [];
    for (const room of rooms) {
      const view = buildRoom(states, room);
      const jev = readJev(states, room.prefix);
      const entries = jev.log?.entries ?? [];
      for (const item of mergeTimeline(eventsForRoom(states, room), entries, now))
        shown.push(timelineText(item), timelineResult(item), item.jev?.reason ?? "");
      for (const entry of entries)
        shown.push(jevAnswer(entry), entry.action, entry.reason, jevChangeText(entry));
      for (const zone of view.zones) {
        const id = `sensor.crop_steering_${room.prefix}zone_${zone.id}_jev`;
        for (const judge of parseJevZone(states[id])?.judges ?? [])
          shown.push(jevAnswer({ verdict: judge.answer, p: judge.p }), judge.directive, judge.why);
        shown.push(parseJevSetpoints(states[id])?.last ?? "");
      }
    }
    expect(shown.filter(Boolean).length).toBeGreaterThan(40);
    expect(shown.filter((text) => TOKENS.test(text))).toEqual([]);
  });
  it("in the day chart's shots", () => {
    const room = buildRoom(
      states,
      rooms.find((item) => item.prefix === "")!,
    );
    const read = timelineEntities(room, states);
    const day = growDay(10, 22, now)!;
    const rows = demoDay(states, { ...read, start: day.start, end: now }, now);
    const reasons = read.zones.flatMap((zone) =>
      valveShots(rows[zone.valve!], rows[read.attributeIds[0]], zone.id, day.start, now).map(
        (shot) => shot.reason ?? "",
      ),
    );
    expect(reasons.filter(Boolean).length).toBeGreaterThan(10);
    expect(reasons.filter((text) => TOKENS.test(text))).toEqual([]);
  });
});
