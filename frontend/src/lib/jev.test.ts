import { describe, expect, it } from "vitest";
import {
  attachOutcomes,
  jevAnswer,
  jevChange,
  jevChanges,
  jevChangeText,
  jevCost,
  jevResult,
  outcomeText,
  parseJevEntry,
  parseJevLog,
  parseJevRoom,
  parseJevSetpoints,
  parseJevStage,
  parseJevZone,
} from "./jev";
import type { EntityState } from "./types";

const entity = (
  entity_id: string,
  state: string,
  attributes: Record<string, unknown> = {},
): EntityState => ({ entity_id, state, attributes });
const decision = {
  t: "2026-09-28T10:05:12",
  zone: 1,
  judge: "salt",
  title: "Pore EC",
  kind: "decision",
  verdict: "below band vegetative",
  p: 0.72,
  agreed: true,
  action: "hold the EC steer",
  result: "acted",
  reason: "the EC steer stays inside its own clamp",
};

describe("the Jev log sensor", () => {
  it("reads every field of a published decision, in the controller's naive local time", () => {
    const entry = parseJevEntry(decision)!;
    expect(entry).toMatchObject({
      zone: 1,
      judge: "salt",
      title: "Pore EC",
      kind: "decision",
      verdict: "below band vegetative",
      p: 0.72,
      agreed: true,
      action: "hold the EC steer",
      result: "acted",
      reason: "the EC steer stays inside its own clamp",
    });
    expect(entry.time).toBe(new Date(2026, 8, 28, 10, 5, 12).getTime());
  });
  it("is null without the sensor: a room without Jev, or a controller from before the log", () => {
    expect(parseJevLog(undefined)).toBeNull();
    expect(parseJevLog(entity("sensor.crop_steering_jev_log", "no decisions yet"))).toEqual({
      headline: "no decisions yet",
      entries: [],
    });
  });
  it("keeps what it can of malformed entries and drops what is not an entry at all", () => {
    const log = parseJevLog(
      entity("sensor.crop_steering_jev_log", "unavailable", {
        entries: [
          null,
          "a line of text",
          42,
          [1, 2],
          { judge: "dawn" },
          { ...decision, zone: "2", p: "72", agreed: "false", t: "not a time" },
          { ...decision, zone: null, judge: "alerts", title: "", p: 1.7e9, agreed: "maybe" },
        ],
      }),
    )!;
    expect(log.headline).toBe("");
    expect(log.entries).toHaveLength(3);
    const [alert, bare, odd] = log.entries;
    // Readable times first, newest first; the unreadable time goes last.
    expect(alert).toMatchObject({ zone: null, title: "Alert triage", p: null, agreed: null });
    expect(bare).toMatchObject({
      title: "Morning start",
      verdict: "",
      p: null,
      agreed: null,
      action: "",
      result: "unknown",
      reason: "",
      time: null,
    });
    expect(odd).toMatchObject({ zone: 2, p: 0.72, agreed: false, time: null });
    expect(new Set(log.entries.map((entry) => entry.key)).size).toBe(3);
  });
  it("is not an array: no entries, never an error", () => {
    expect(
      parseJevLog(entity("sensor.crop_steering_jev_log", "x", { entries: { 0: decision } }))!
        .entries,
    ).toEqual([]);
  });
  it('accepts `note` for `reason`, and splits a legacy "refused: why" result', () => {
    const { reason, ...rest } = decision;
    expect(parseJevEntry({ ...rest, note: reason })!.reason).toBe(reason);
    const legacy = parseJevEntry({
      ...rest,
      result: "refused: VWC 58.2 more than 3 points under the ramp ceiling 64.0",
    })!;
    expect(legacy.result).toBe("refused");
    expect(legacy.reason).toBe("VWC 58.2 more than 3 points under the ramp ceiling 64.0");
    // A reason given on its own wins over the one in the result.
    expect(parseJevEntry({ ...decision, result: "refused: old words" })!.reason).toBe(reason);
    expect(parseJevEntry({ ...decision, result: "no_action" })!.result).toBe("no action");
  });
  it("sorts newest first whatever order it was published in", () => {
    const log = parseJevLog(
      entity("sensor.crop_steering_jev_log", "x", {
        entries: [
          { ...decision, t: "2026-09-28T09:00:00" },
          { ...decision, t: "2026-09-28T11:30:00" },
          { ...decision, t: "2026-09-28T10:15:00" },
        ],
      }),
    )!;
    expect(log.entries.map((entry) => new Date(entry.time!).getHours())).toEqual([11, 10, 9]);
  });
  it("tells an outcome from a decision, and a judge's alert (advice) from code acting", () => {
    const outcome = parseJevEntry({
      ...decision,
      kind: "outcome",
      verdict: "slab_full",
      p: null,
      agreed: null,
      action: "",
      result: "did not work",
    })!;
    expect(outcome).toMatchObject({ kind: "outcome", verdict: "slab full" });
    expect(jevResult(outcome)).toEqual({ label: "Didn’t work", tone: "off", acted: false });
    const advice = parseJevEntry({
      ...decision,
      judge: "stage",
      action: "CS-705: this zone is off the stage's arc",
    })!;
    expect(advice.result).toBe("advice");
    expect(jevResult(advice)).toMatchObject({ label: "Advice", acted: false });
    // The alert-triage judge's own call (push or card) is code acting on its answer.
    const triage = parseJevEntry({ ...decision, judge: "alerts", action: "CS-705: card only" })!;
    expect(jevResult(triage)).toMatchObject({ label: "Acted", acted: true });
    expect(jevResult(parseJevEntry({ ...decision, result: "refused" })!)).toMatchObject({
      label: "Refused",
      tone: "warn",
    });
    expect(jevResult(parseJevEntry({ ...decision, result: "sleeping" })!)).toMatchObject({
      label: "Sleeping",
      tone: "neutral",
    });
  });
  it("says Jev's answer with how sure it was", () => {
    expect(jevAnswer(parseJevEntry(decision)!)).toBe("below band vegetative, 72%");
    expect(jevAnswer({ verdict: "", p: null })).toBe("no answer");
  });
});

describe("the room's Jev sensor", () => {
  const stage = {
    day: 37,
    days: 56,
    name: "flower bulk",
    steering: "vegetative",
    stage_days: [22, 42],
    peak: "at or above field capacity",
    pore_ec: [3.5, 6.0],
    dryback_points: [10, 15],
    runoff_pct: [8, 16],
  };
  it("reads usage and today's stage", () => {
    const room = parseJevRoom(
      entity("sensor.crop_steering_jev", "on", {
        calls_today: 46,
        input_tokens_today: 131_400,
        errors_today: 1,
        last_error: "TimeoutError",
        judges: ["salt", "dawn"],
        judge_errors: { shot: "KeyError: 'rise'", dawn: "" },
        stage,
      }),
    )!;
    expect(room).toMatchObject({
      state: "on",
      calls: 46,
      tokens: 131_400,
      errors: 1,
      lastError: "TimeoutError",
      judges: ["salt", "dawn"],
      judgeErrors: { shot: "KeyError: 'rise'" },
    });
    expect(room.stage).toEqual({
      day: 37,
      days: 56,
      name: "flower bulk",
      steering: "vegetative",
      stageDays: [22, 42],
      peak: "at or above field capacity",
      poreEc: [3.5, 6],
      drybackPoints: [10, 15],
      runoffPct: [8, 16],
    });
  });
  it("an older controller without a stage, or an unknown flower day, has none", () => {
    expect(parseJevRoom(entity("sensor.crop_steering_jev", "on", {}))).toMatchObject({
      calls: null,
      tokens: null,
      stage: null,
      judges: [],
      judgeErrors: {},
    });
    expect(parseJevRoom(entity("sensor.crop_steering_jev", "on", { stage: null }))!.stage).toBe(
      null,
    );
    expect(parseJevRoom(undefined)).toBeNull();
  });
  it("a stage with odd numbers keeps what is sound", () => {
    expect(
      parseJevStage({
        ...stage,
        day: "x",
        pore_ec: [6, 3.5],
        dryback_points: [10],
        runoff_pct: ["8", "16"],
      }),
    ).toMatchObject({ day: null, poreEc: [3.5, 6], drybackPoints: null, runoffPct: [8, 16] });
    expect(parseJevStage({ day: 3 })).toBeNull();
    expect(parseJevStage("flower bulk")).toBeNull();
  });
  it("costs input tokens at $0.042 a million", () => {
    expect(jevCost(null)).toBeNull();
    expect(jevCost(131_400)).toBe("under $0.01");
    expect(jevCost(3_000_000)).toBe("≈ $0.13");
    expect(jevCost(40_000_000)).toBe("≈ $1.7");
  });
});

describe("a zone's Jev sensor", () => {
  it("names the judges acting on it, or none while it watches", () => {
    const acting = parseJevZone(
      entity("sensor.crop_steering_zone_2_jev", "salt, stage", {
        judges: {
          salt: {
            verdicts: { salt_cause: { answer: "below_band_vegetative", p: 0.72, agreed: true } },
            directive: "ec_mode hold",
            why: "the EC steer stays inside its own clamp",
            streak: 2,
          },
          stage: "not an object",
        },
      }),
    )!;
    expect(acting.acting).toEqual(["salt", "stage"]);
    expect(acting.judges).toEqual([
      {
        judge: "salt",
        title: "Pore EC",
        answer: "below band vegetative",
        p: 0.72,
        agreed: true,
        directive: "ec mode hold",
        why: "the EC steer stays inside its own clamp",
      },
    ]);
    expect(parseJevZone(entity("sensor.crop_steering_zone_1_jev", "watching"))).toEqual({
      acting: [],
      judges: [],
    });
    expect(parseJevZone(undefined)).toBeNull();
  });
});

describe("what changed something", () => {
  const at = (hour: number, minute = 0) =>
    `2026-09-28T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00`;
  const entry = (raw: Record<string, unknown>, index = 0) =>
    parseJevEntry({ ...decision, ...raw }, index)!;
  it("is a phase brought forward, a setpoint moved, a probe set aside, the EC steer's mode or an alert", () => {
    expect(jevChange(entry({ judge: "dawn", action: "start the ramp now" }))).toBe("phase");
    expect(jevChange(entry({ judge: "ramp", action: "hand over to maintenance" }))).toBe("phase");
    expect(jevChange(entry({ judge: "dusk", action: "end the day's watering" }))).toBe("phase");
    expect(
      jevChange(
        entry({ judge: "setpoints", verdict: "smaller shots", action: "P2 shot 5% -> 4.5%" }),
      ),
    ).toBe("setpoint");
    expect(jevChange(entry({ judge: "probe", action: "set the probe aside (reads flat)" }))).toBe(
      "probe",
    );
    expect(jevChange(entry({ action: "hold the EC steer" }))).toBe("ec");
    expect(jevChange(entry({ judge: "alerts", zone: null, action: "CS-608: card only" }))).toBe(
      "alert",
    );
    expect(
      jevChange(entry({ judge: "stage", action: "CS-705: this zone is off the stage's arc" })),
    ).toBe("alert");
  });
  it("is not an answer that asked for nothing, a refusal, an outcome, or the grower's own edit", () => {
    expect(jevChange(entry({ result: "no action", action: "" }))).toBeNull();
    expect(jevChange(entry({ result: "refused" }))).toBeNull();
    expect(jevChange(entry({ result: "waiting" }))).toBeNull();
    expect(jevChange(entry({ kind: "outcome", result: "worked", action: "" }))).toBeNull();
    expect(
      jevChange(
        entry({ judge: "setpoints", verdict: "set by hand", action: "p2 shot size 5 -> 4" }),
      ),
    ).toBeNull();
  });
  it("lists today's changes newest first, one row per alert however many judges raised it", () => {
    const log = parseJevLog(
      entity("sensor.crop_steering_jev_log", "x", {
        entries: [
          {
            ...decision,
            t: at(15, 2),
            zone: 2,
            judge: "alerts",
            title: "Alert triage",
            action: "CS-705: card only",
            reason: "this zone is off the stage's arc",
          },
          {
            ...decision,
            t: at(15),
            zone: 2,
            judge: "stage",
            action: "CS-705: this zone is off the stage's arc",
          },
          { ...decision, t: at(14), zone: 1, result: "no action", action: "" },
          { ...decision, t: at(12), zone: 1, judge: "ramp", action: "hand over to maintenance" },
          {
            ...decision,
            t: "2026-09-27T21:00:00",
            zone: 3,
            judge: "dusk",
            action: "end the day's watering",
          },
        ],
      }),
    )!;
    const today = jevChanges(log.entries, new Date(2026, 8, 28, 10).getTime());
    expect(today.map((item) => [item.judge, item.zone])).toEqual([
      ["alerts", 2],
      ["ramp", 1],
    ]);
    expect(jevChangeText(today[0])).toBe("CS-705: this zone is off the stage's arc (card only)");
    expect(jevChangeText(today[1])).toBe("hand over to maintenance");
  });
});

describe("an outcome, on the decision it checks", () => {
  const log = (entries: Record<string, unknown>[]) =>
    parseJevLog(entity("sensor.crop_steering_jev_log", "x", { entries }))!.entries;
  const hold = { ...decision, t: "2026-09-28T01:56:00", zone: 3 };
  const checked = {
    ...decision,
    t: "2026-09-28T05:56:00",
    zone: 3,
    kind: "outcome",
    verdict: "hold the EC steer",
    action: "",
    result: "worked",
    reason: "four hours after, pore EC read 3.95 (was 3.93)",
    of: "2026-09-28T01:56:00",
  };
  it("is found by judge, zone and the decision's time, and leaves the list", () => {
    const entries = log([hold, checked, { ...hold, zone: 1 }]);
    const { rest, outcomes } = attachOutcomes(entries);
    expect(rest.map((item) => [item.kind, item.zone])).toEqual([
      ["decision", 3],
      ["decision", 1],
    ]);
    const on = outcomes.get(rest[0].key)!;
    expect(on.map((item) => item.result)).toEqual(["worked"]);
    expect(outcomeText(on[0])).toBe(
      "After “hold the EC steer”: worked. four hours after, pore EC read 3.95 (was 3.93)",
    );
    expect(outcomes.has(rest[1].key)).toBe(false);
  });
  it("matches a time written another way, and not another judge's or zone's decision", () => {
    const { rest, outcomes } = attachOutcomes(log([hold, { ...checked, of: "2026-09-28T01:56" }]));
    expect(rest).toHaveLength(1);
    expect(outcomes.size).toBe(1);
    expect(attachOutcomes(log([hold, { ...checked, judge: "dusk" }])).rest).toHaveLength(2);
    expect(attachOutcomes(log([hold, { ...checked, zone: 2 }])).rest).toHaveLength(2);
  });
  it("stays a row of its own when it names no decision on the list, or none at all", () => {
    const orphan = attachOutcomes(log([{ ...checked, of: "2026-09-27T01:00:00" }]));
    expect(orphan.rest.map((item) => item.kind)).toEqual(["outcome"]);
    const { of: _of, ...older } = checked;
    const before = attachOutcomes(log([hold, older]));
    expect(before.rest.map((item) => item.kind)).toEqual(["outcome", "decision"]);
    expect(before.outcomes.size).toBe(0);
  });
});

describe("the setpoints Jev manages on a zone", () => {
  const zone = (setpoints: unknown) =>
    parseJevSetpoints(entity("sensor.crop_steering_zone_1_jev", "watching", { setpoints }));
  it("reads the range, the grower's home value and the last change", () => {
    expect(
      zone({
        managed: true,
        home: { p2_shot_size: 5.0, p2_vwc_threshold: 30.5 },
        range: { p2_shot_size: [4.0, 6.0], p2_vwc_threshold: [28.5, 31.5] },
        current: { p2_shot_size: 4.5, p2_vwc_threshold: 30.5 },
        last: "2026-09-28 22:30: P2 shot 5% -> 4.5%",
        paused_until: null,
      }),
    ).toEqual({
      managed: true,
      home: { p2_shot_size: 5, p2_vwc_threshold: 30.5 },
      range: { p2_shot_size: [4, 6], p2_vwc_threshold: [28.5, 31.5] },
      current: { p2_shot_size: 4.5, p2_vwc_threshold: 30.5 },
      last: "2026-09-28 22:30: P2 shot 5% -> 4.5%",
      pausedUntil: null,
    });
  });
  it("reads a pause after a revert, in the controller's local time", () => {
    expect(zone({ managed: true, paused_until: "2026-09-29T09:30:00" })!.pausedUntil).toBe(
      new Date(2026, 8, 29, 9, 30).getTime(),
    );
  });
  it("keeps what is sound, and is null from a controller that does not publish it", () => {
    expect(
      zone({ managed: "yes", range: { p2_shot_size: [6, "4"], p2_vwc_threshold: [1] }, home: 5 }),
    ).toEqual({
      managed: false,
      home: {},
      range: { p2_shot_size: [4, 6] },
      current: {},
      last: null,
      pausedUntil: null,
    });
    expect(zone(undefined)).toBeNull();
    expect(zone("managed")).toBeNull();
    expect(parseJevSetpoints(undefined)).toBeNull();
  });
});
