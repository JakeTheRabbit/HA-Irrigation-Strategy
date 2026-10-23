import { afterEach, describe, expect, it } from "vitest";
import {
  ACTOR_CHIP,
  changesHash,
  changesQuery,
  changeWords,
  fromSetpointLog,
  revertChange,
  groupByDay,
  toEntries,
  type ChangeWords,
} from "./changes";
import { setDisplayUnits } from "./display-units";
import type { HistoryChange } from "./parity-types";
import type { States } from "./types";

const state = (value: number, unit: string) => ({
  entity_id: "",
  state: String(value),
  attributes: { unit_of_measurement: unit },
  last_changed: "",
  last_updated: "",
});
const states = {
  "number.crop_steering_zone_2_p2_shot_size": state(4.6, "%"),
  "number.crop_steering_zone_1_max_daily_volume": state(10, "L"),
  "number.crop_steering_p1_time_between_shots": state(60, "min"),
} as unknown as States;
const rooms = [{ id: "room:", name: "F2", prefix: "" }];
const words: ChangeWords = changeWords(states, rooms);

const change = (over: Partial<HistoryChange>): HistoryChange => ({
  id: "01J0000000000000000000000A",
  room_id: "room:",
  ts: "2026-10-22T13:42:00Z",
  actor: "manual",
  kind: "setpoint",
  key: "p2_shot_size",
  scope: "zone:2",
  old: 4,
  new: 4.6,
  reason: "Pore EC is over its band.",
  outcome: null,
  limits: null,
  revertible: true,
  user_id: null,
  user_name: null,
  ...over,
});

afterEach(() => setDisplayUnits({ ec: "mS/cm", temp: "C", volume: "L", clock: "24" }));

describe("changes", () => {
  it("toEntries builds Revert to <old> with unit", () => {
    const [entry] = toEntries([change({})], words);
    expect(entry.before).toBe("4%");
    expect(entry.after).toBe("4.6%");
    expect(entry.revertLabel).toBe("Revert to 4%");
    expect(entry.scope).toBe("F2 · Zone 2");
    expect(entry.revertible).toBe(true);
    // A volume goes through the display units.
    setDisplayUnits({ volume: "gal" });
    const [litres] = toEntries([change({ key: "max_daily_volume", scope: "zone:1", old: 9, new: 10 })], words);
    expect(litres.revertLabel).toBe("Revert to 2 gal");
  });

  it("non-revertible plan row has the edit-the-plan line", () => {
    const [plan, other] = toEntries(
      [
        change({ id: "a", kind: "plan", key: undefined, section: "plan", scope: "room", old: null, new: "activated", revertible: false, actor: "plan" }),
        change({ id: "b", revertible: false }),
      ],
      words,
    );
    expect(plan.revertLabel).toBe("Plan step. Edit the plan to change it.");
    expect(plan.revertible).toBe(false);
    expect(other.revertLabel).toBe("This change can't be put back");
  });

  it("calibration and left-out probe rows have their own put-back words", () => {
    const [cal, probe] = toEntries(
      [
        change({ id: "c", kind: "calibration", key: "feed_ph", section: "calibration", scope: "room", old: "r1", new: "r2" }),
        change({ id: "d", kind: "setup", key: undefined, section: "probes", scope: "zone:2", old: { back: "in reading" }, new: { back: "left out" } }),
      ],
      words,
    );
    expect(cal.revertLabel).toBe("Restore previous calibration");
    // Record ids are not values to show.
    expect(cal.before).toBe("");
    expect(probe.revertLabel).toBe("Put back in reading");
  });

  it("actor manual maps to You and ai to AI judge", () => {
    expect(ACTOR_CHIP.manual).toBe("You");
    expect(ACTOR_CHIP.ai).toBe("AI judge");
    const [you, ai] = toEntries([change({ id: "a" }), change({ id: "b", actor: "ai" })], words);
    expect(you.chip).toBe("You");
    expect(ai.chip).toBe("AI judge");
  });

  it("learner limits read in the setting's unit", () => {
    const [entry] = toEntries(
      [change({ actor: "learner", key: "p1_time_between_shots", scope: "room", old: 50, new: 60, limits: { writer: "learner", min: 30, max: 90, step_scope: "zone" } })],
      words,
    );
    expect(entry.limits).toBe("learner may move it between 30 min and 90 min");
    expect(entry.scope).toBe("F2 · all zones");
  });

  it("changesQuery round-trips actor kind room", () => {
    const query = { since: "2026-10-15T00:00:00.000Z", actor: "learner", kind: "setpoint", room: "room:f1_:2", id: "01J" };
    const hash = changesHash(query);
    expect(hash.startsWith("#/history/changes?")).toBe(true);
    expect(changesQuery(hash)).toEqual(query);
    expect(changesQuery("#/history/changes")).toEqual({ since: "" });
    expect(changesQuery("#/history/changes?actor=ai")).toEqual({ since: "", actor: "ai" });
  });

  it("fromSetpointLog gives setpoint entries", () => {
    const entries = fromSetpointLog(
      [
        { at: "2026-10-21T21:30:00+00:00", entity_id: "number.crop_steering_zone_2_p2_shot_size", field: "p2_shot_size", zone: 2, old: 4, new: 4.6, who: "learner", reason: "Ran short" },
        { at: "2026-10-22T09:00:00+00:00", entity_id: "number.crop_steering_p1_time_between_shots", field: "p1_time_between_shots", zone: null, old: 50, new: 60, who: "operator" },
      ],
      "room:",
      words,
    );
    // Newest first.
    expect(entries.map((e) => e.chip)).toEqual(["You", "Learner"]);
    expect(entries.every((e) => e.kind === "setpoint" && e.revertible)).toBe(true);
    expect(entries[1]).toMatchObject({ entityId: "number.crop_steering_zone_2_p2_shot_size", revertLabel: "Revert to 4%", reason: "Ran short", zone: 2 });
  });

  it("revertChange claims a write only when the controller read it back", async () => {
    const [entry] = toEntries([change({})], words);
    const answer = (status: string) => ({
      operator: async () => ({ api: 2, ok: true, readback: { status, at: "2026-10-22T14:00:05Z" }, event_ids: ["n"], data: { reverted_event_id: entry.id, new_event_id: "n", readback: status } }),
      write: async () => ({ applied: [], failed: [] }),
    }) as unknown as Parameters<typeof revertChange>[0];
    const verified = await revertChange(answer("verified"), states, entry);
    expect(verified).toMatchObject({ ok: true, eventIds: ["n"], summary: `${entry.label} 4.6% → 4%`, at: Date.parse("2026-10-22T14:00:05Z") });
    const unverified = await revertChange(answer("unverified"), states, entry);
    expect(unverified).toMatchObject({ ok: false, unconfirmed: true });
  });

  it("a 3.17 put-back refuses a setting that moved since, and writes the old value otherwise", async () => {
    const [entry] = fromSetpointLog(
      [{ at: "2026-10-22T09:00:00Z", entity_id: "number.crop_steering_zone_2_p2_shot_size", field: "p2_shot_size", zone: 2, old: 4, new: 4.6, who: "operator" }],
      "room:",
      words,
    );
    const written: unknown[] = [];
    const controller = {
      operator: async () => ({}),
      write: async (changes: unknown[]) => (written.push(...changes), { applied: ["x"], failed: [] }),
    } as unknown as Parameters<typeof revertChange>[0];
    const moved = { ...states, "number.crop_steering_zone_2_p2_shot_size": state(5, "%") } as unknown as States;
    expect(await revertChange(controller, moved, entry)).toMatchObject({ kind: "error", code: "stale_revision" });
    expect(written).toEqual([]);
    expect(await revertChange(controller, states, entry)).toMatchObject({ ok: true });
    expect(written).toEqual([{ entityId: "number.crop_steering_zone_2_p2_shot_size", value: 4 }]);
  });

  it("entries group by zoned day", () => {
    const now = Date.parse("2026-10-22T14:00:00Z");
    const entries = toEntries(
      [
        change({ id: "a", ts: "2026-10-22T13:00:00Z" }),
        // 23:30 UTC on the 21st is midday on the 22nd in Auckland (UTC+13).
        change({ id: "b", ts: "2026-10-21T23:30:00Z" }),
        change({ id: "c", ts: "2026-10-21T09:00:00Z" }),
        change({ id: "d", ts: "2026-10-19T09:00:00Z" }),
      ],
      words,
    );
    const auckland = groupByDay(entries, "Pacific/Auckland", now);
    expect(auckland.map((d) => d.title)).toEqual(["Today · Fri 23 Oct", "Yesterday · Thu 22 Oct", "Wed 21 Oct", "Mon 19 Oct"]);
    expect(auckland.map((d) => d.entries.map((e) => e.id))).toEqual([["a"], ["b"], ["c"], ["d"]]);
    const utc = groupByDay(entries, "UTC", now);
    expect(utc.map((d) => d.title)).toEqual(["Today · Thu 22 Oct", "Yesterday · Wed 21 Oct", "Mon 19 Oct"]);
    expect(utc.map((d) => d.entries.map((e) => e.id))).toEqual([["a"], ["b", "c"], ["d"]]);
  });
});
