import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { ReviewApplyView, type ApplyReceipt } from "@/components/review-apply";
import { callV2, type V2Outcome } from "./parity-api";
import type { PresetResult } from "./parity-types";
import {
  copyReceipt,
  diffRows,
  notCopiedLines,
  parseTarget,
  presetWords,
  skippedLine,
  targetKey,
  type PresetWords,
} from "./presets";
import { DEMO_PRESET_SECTIONS } from "./parity-demo/presets";
import { demoController } from "./test-helpers";
import { revertEvents } from "./undo";

const NZ = "Pacific/Auckland";
const AT = Date.parse("2026-10-23T14:10:00+13:00");
const F1 = { room_id: "room:f1_" };
const WORDS: PresetWords = {
  label: (key) =>
    ({
      p1_target_vwc: "Peak moisture",
      p2_vwc_threshold: "Re-water point",
      timers: "Timer programs",
    })[key] ?? presetWords({}, []).label(key), // else the panel's own words (setting-words)
  value: (_key, value) =>
    typeof value === "number" ? `${value}%` : value == null ? "none" : String(value),
  target: (t) => (t.zone ? `F1 zone ${t.zone}` : "F1"),
};
const DIFF = [
  { target: F1, key: "p1_target_vwc", old: 66, new: 70 },
  { target: F1, key: "p2_vwc_threshold", old: 63, new: 60 },
];
const ok = (data: PresetResult, eventIds = ["01B", "01A"]): V2Outcome<PresetResult> => ({
  kind: "ok",
  data,
  revision: null,
  readback: { status: "verified", at: null },
  eventIds,
});
const isReceipt = (r: unknown): r is ApplyReceipt => !!r && typeof r === "object" && "ok" in r;

describe("diffRows", () => {
  test("diffRows renders old struck and new", () => {
    const rows = diffRows(DIFF, WORDS);
    expect(rows.map((r) => [r.id, r.key, r.target, r.label, r.before, r.after])).toEqual([
      ["room:f1_|p1_target_vwc", "p1_target_vwc", "room:f1_", "Peak moisture", "66%", "70%"],
      ["room:f1_|p2_vwc_threshold", "p2_vwc_threshold", "room:f1_", "Re-water point", "63%", "60%"],
    ]);
    // A copy is all or nothing per section: no row can be taken out on its own.
    expect(rows.every((r) => r.undo === undefined)).toBe(true);
    const html = renderToStaticMarkup(
      createElement(ReviewApplyView, {
        rows,
        layout: "panel",
        apply: () => Promise.resolve({ kind: "missing" as const }),
        onDiscard: () => {},
        timeZone: NZ,
        state: { phase: "idle" },
        applyLabel: "Copy 2 changes to F1",
      }),
    );
    expect(html).toContain("<s>66%</s> → <b>70%</b>");
    expect(html).toContain("<s>63%</s> → <b>60%</b>");
    expect(html).toContain("Copy 2 changes to F1");
    expect(html).not.toContain(">Undo<");
  });

  test("names the target on each row only when the copy has more than one", () => {
    const rows = diffRows(
      [
        ...DIFF,
        { target: { room_id: "room:f1_", zone: 2 }, key: "p1_target_vwc", old: 64, new: 70 },
      ],
      WORDS,
    );
    expect(rows.map((r) => r.label)).toEqual([
      "F1 · Peak moisture",
      "F1 · Re-water point",
      "F1 zone 2 · Peak moisture",
    ]);
    expect(rows[2].target).toBe("room:f1_:2");
  });
});

describe("targets", () => {
  test("a pick key is a room or a zone of it, as the backend expects", () => {
    expect(parseTarget("room:f1_")).toEqual({ room_id: "room:f1_" });
    expect(parseTarget("room:f1_:3")).toEqual({ room_id: "room:f1_", zone: 3 });
    expect(parseTarget("room::2")).toEqual({ room_id: "room:", zone: 2 });
    expect(parseTarget("room:")).toEqual({ room_id: "room:" });
    expect(targetKey({ room_id: "room:", zone: 2 })).toBe("room::2");
  });
});

describe("copyReceipt", () => {
  const rows = diffRows(DIFF, WORDS);
  test("every value read back: a green receipt with the event ids for Undo", () => {
    const r = copyReceipt(
      ok({
        diff: DIFF,
        missing: [],
        applied: DIFF.map(({ target, key }) => ({
          target,
          key,
          readback: "verified",
          error: null,
        })),
      }),
      rows,
      WORDS,
      AT,
    );
    expect(isReceipt(r) && r.ok).toBe(true);
    expect(isReceipt(r) && r.eventIds).toEqual(["01B", "01A"]);
    expect(isReceipt(r) && r.summary).toBe("Peak moisture 66% → 70% · Re-water point 63% → 60%");
    expect(isReceipt(r) && r.notCopied).toBeUndefined();
  });

  test("refused readback row stays failed in the receipt", () => {
    const outcome: V2Outcome<PresetResult> = {
      kind: "error",
      code: "guard_refused",
      message: "Not applied: p2_vwc_threshold: waiting for its neighbour",
      data: {
        diff: DIFF,
        missing: [],
        applied: [
          { target: F1, key: "p1_target_vwc", readback: "verified", error: null },
          {
            target: F1,
            key: "p2_vwc_threshold",
            readback: "refused",
            error: "waiting for its neighbour",
          },
        ],
      },
    };
    const r = copyReceipt(outcome, rows, WORDS, AT);
    expect(isReceipt(r)).toBe(true);
    if (!isReceipt(r)) return;
    expect(r.ok).toBe(false);
    expect(r.unconfirmed).toBeUndefined();
    expect(r.failed).toEqual([
      { id: "room:f1_|p2_vwc_threshold", holds: "63%", label: "Re-water point" },
    ]);
    expect(r.summary).toBe("Peak moisture 66% → 70%");
    // The refusal envelope lists no events: nothing to undo by id.
    expect(r.eventIds).toEqual([]);
    const html = renderToStaticMarkup(
      createElement(ReviewApplyView, {
        rows: [],
        layout: "panel",
        apply: () => Promise.resolve(r),
        onDiscard: () => {},
        timeZone: NZ,
        state: { phase: "done", result: r },
      }),
    );
    expect(html).toContain("Re-water point is still 63%.");
    expect(html).toContain("Peak moisture 66% → 70%: written and read back.");
    expect(html).not.toContain("Written and read back");
  });

  test("a timer the source has none of is not copied, the rest is written, and the receipt names it", () => {
    const missing = [{ target: F1, key: "timers", reason: "source room has no timer programs" }];
    const outcome: V2Outcome<PresetResult> = {
      kind: "error",
      code: "guard_refused",
      message: "Not applied: timers: source room has no timer programs",
      data: {
        diff: DIFF,
        missing,
        applied: [
          ...DIFF.map(({ target, key }) => ({
            target,
            key,
            readback: "verified" as const,
            error: null,
          })),
          {
            target: F1,
            key: "timers",
            readback: "refused",
            error: "source room has no timer programs",
          },
        ],
      },
    };
    const r = copyReceipt(outcome, rows, WORDS, AT);
    expect(isReceipt(r) && r.ok).toBe(true);
    expect(isReceipt(r) && r.notCopied).toEqual([
      "Timer programs (source room has no timer programs)",
    ]);
    const html = renderToStaticMarkup(
      createElement(ReviewApplyView, {
        rows: [],
        layout: "panel",
        apply: () => Promise.resolve(r as ApplyReceipt),
        onDiscard: () => {},
        timeZone: NZ,
        state: { phase: "done", result: r as ApplyReceipt },
      }),
    );
    expect(html).toContain("Written and read back 14:10");
    expect(html).toContain("Not copied: Timer programs (source room has no timer programs)");
  });

  test("a row with no read-back, or a refusal that matches no row, claims nothing", () => {
    const partial = copyReceipt(
      {
        kind: "error",
        code: "guard_refused",
        message: "x",
        data: {
          diff: DIFF,
          missing: [],
          applied: [{ target: F1, key: "p2_vwc_threshold", readback: "refused" }],
        },
      },
      rows,
      WORDS,
      AT,
    );
    expect(isReceipt(partial) && partial.unconfirmed).toBe(true);
    const stray = copyReceipt(
      ok({
        diff: DIFF,
        missing: [],
        applied: [...DIFF, { target: F1, key: "maximum_ec" }].map(({ target, key }) => ({
          target,
          key,
          readback: key === "maximum_ec" ? "refused" : "verified",
        })),
      }),
      rows,
      WORDS,
      AT,
    );
    expect(isReceipt(stray) && stray.unconfirmed).toBe(true);
  });

  test("other refusals and an older integration pass through", () => {
    expect(copyReceipt({ kind: "missing" }, rows, WORDS, AT)).toEqual({ kind: "missing" });
    const forbidden: V2Outcome<PresetResult> = {
      kind: "error",
      code: "forbidden",
      message: "Admin only",
    };
    expect(copyReceipt(forbidden, rows, WORDS, AT)).toBe(forbidden);
  });
});

describe("words", () => {
  test("not copied and not saved lines", () => {
    expect(
      notCopiedLines(
        [
          { target: F1, key: "p2_dilute_ratio" },
          { target: F1, key: "timers", reason: "source room has no timer programs" },
        ],
        WORDS,
      ),
    ).toEqual([
      "P2 dilute ratio (F1 has no such setting)",
      "Timer programs (source room has no timer programs)",
    ]);
    expect(skippedLine(["p1_target_vwc", "timers"], WORDS)).toBe(
      "Not saved: Peak moisture, Timer programs (no reading)",
    );
    expect(skippedLine([], WORDS)).toBe("");
  });

  test("presetWords reads the unit from the room's own entity and names rooms and zones", () => {
    const words = presetWords(
      {
        "number.crop_steering_f1_zone_1_p1_target_vwc": {
          entity_id: "",
          state: "64",
          attributes: { unit_of_measurement: "%" },
          last_changed: "",
          last_updated: "",
        },
        "number.crop_steering_f1_max_shot_duration": {
          entity_id: "",
          state: "120",
          attributes: { unit_of_measurement: "s" },
          last_changed: "",
          last_updated: "",
        },
      },
      [{ id: "room:f1_", name: "F1", prefix: "f1_" }],
    );
    expect(words.value("p1_target_vwc", 70)).toBe("70%");
    expect(words.value("max_shot_duration", 90)).toBe("90 s");
    expect(words.value("timers", [{}, {}])).toBe("2 programs");
    expect(words.value("timers", [])).toBe("none");
    expect(words.value("timer", { name: "Day timer" })).toBe("Day timer");
    expect(words.target({ room_id: "room:f1_", zone: 2 })).toBe("F1 zone 2");
    expect(words.label("p1_target_vwc")).not.toBe("p1_target_vwc");
    expect(words.label("p2_dilute_ratio")).toBe("P2 dilute ratio");
  });
});

describe("demo copy (3.18)", () => {
  const roomA = { room_id: "room:" },
    roomB = { room_id: "room:room_b_" };
  const sections = ["targets", "phase_timing", "water_limits", "timers"];
  test("Room A to Room B: real diffs, one setting Room B has no entity for, applied, read back and undone", async () => {
    const c = demoController("?demo=1");
    const preview = await callV2<PresetResult>(c, "copy_config", {
      from: roomA,
      to: [roomB],
      sections,
      preview: true,
    });
    if (preview.kind !== "ok") throw new Error("not ok");
    expect(
      preview.data.diff.map((d) => [d.key, d.old, Array.isArray(d.new) ? d.new.length : d.new]),
    ).toEqual([
      ["p1_target_vwc", 66, 70],
      ["p2_vwc_threshold", 63, 60],
      ["timers", [], 2],
    ]);
    expect(preview.data.missing).toEqual([{ target: roomB, key: "p2_dilute_ratio" }]);
    const words = presetWords(c.states, c.rooms);
    const rows = diffRows(preview.data.diff, words);
    expect(rows.map((r) => `${r.label}: ${r.before} → ${r.after}`)).toEqual([
      "Peak VWC target: 66% → 70%",
      "Maintenance shot when below: 63% → 60%",
      "Timer programs: none → 2 programs",
    ]);
    const applied = await callV2<PresetResult>(c, "copy_config", {
      from: roomA,
      to: [roomB],
      sections,
    });
    const receipt = copyReceipt(applied, rows, words, AT);
    if (!isReceipt(receipt)) throw new Error("no receipt");
    expect(receipt.ok).toBe(true);
    expect(receipt.eventIds).toHaveLength(3);
    expect(receipt.notCopied).toEqual(["P2 dilute ratio (Room B has no such setting)"]);
    const again = await callV2<PresetResult>(c, "copy_config", {
      from: roomA,
      to: [roomB],
      sections,
      preview: true,
    });
    expect(again.kind === "ok" && again.data.diff).toEqual([]);
    expect(await revertEvents(c, receipt.eventIds)).toHaveLength(3);
    const back = await callV2<PresetResult>(c, "copy_config", {
      from: roomA,
      to: [roomB],
      sections,
      preview: true,
    });
    expect(back.kind === "ok" && back.data.diff.map((d) => d.key)).toEqual([
      "p1_target_vwc",
      "p2_vwc_threshold",
      "timers",
    ]);
  });

  test("Room B to Room A: no timer programs to copy, so the apply is refused for that row and the rest stands", async () => {
    const c = demoController("?demo=1");
    const words = presetWords(c.states, c.rooms);
    const preview = await callV2<PresetResult>(c, "copy_config", {
      from: roomB,
      to: [roomA],
      sections,
      preview: true,
    });
    if (preview.kind !== "ok") throw new Error("not ok");
    expect(preview.data.missing).toEqual([
      { target: roomA, key: "timers", reason: "source room has no timer programs" },
    ]);
    const rows = diffRows(preview.data.diff, words);
    const applied = await callV2<PresetResult>(c, "copy_config", {
      from: roomB,
      to: [roomA],
      sections,
    });
    expect(applied.kind === "error" && applied.code).toBe("guard_refused");
    const receipt = copyReceipt(applied, rows, words, AT);
    expect(isReceipt(receipt) && receipt.ok).toBe(true);
    expect(isReceipt(receipt) && receipt.eventIds).toEqual([]);
    expect(isReceipt(receipt) && receipt.notCopied).toEqual([
      "Timer programs (source room has no timer programs)",
    ]);
  });

  test("3.17 has no presets", async () => {
    expect((await callV2(demoController("?demo=1&backend=3.17"), "preset_list", {})).kind).toBe(
      "missing",
    );
  });
});

describe("fix round 1: a copy never claims more than it did", () => {
  const rows = diffRows(DIFF, WORDS);
  const view = (r: ApplyReceipt) =>
    renderToStaticMarkup(
      createElement(ReviewApplyView, {
        rows: [],
        layout: "panel",
        apply: () => Promise.resolve(r),
        onDiscard: () => {},
        timeZone: NZ,
        state: { phase: "done", result: r },
      }),
    );
  const verified = DIFF.map(({ target, key }) => ({
    target,
    key,
    readback: "verified" as const,
    error: null,
  }));
  const NO_UNDO = "Undo not available here: put the written values back from History";

  test("written and read back but no event ids: Undo is explained, with a link to History › Changes", () => {
    const r = copyReceipt(
      ok({ diff: DIFF, missing: [], applied: verified }, []),
      rows,
      WORDS,
      AT,
    ) as ApplyReceipt;
    expect(r.ok).toBe(true);
    expect(r.undoUnavailable).toBe(true);
    const html = view(r);
    expect(html).toContain(NO_UNDO);
    expect(html).toContain('href="#/history/changes"');
    // With event ids the Undo button does the job: no note.
    const undoable = copyReceipt(
      ok({ diff: DIFF, missing: [], applied: verified }),
      rows,
      WORDS,
      AT,
    ) as ApplyReceipt;
    expect(undoable.undoUnavailable).toBeUndefined();
    expect(view(undoable)).not.toContain(NO_UNDO);
  });

  test("a partial copy names the refused setting by its words and explains Undo", () => {
    const r = copyReceipt(
      {
        kind: "error",
        code: "guard_refused",
        message: "Not applied",
        data: {
          diff: DIFF,
          missing: [],
          applied: [verified[0], { ...verified[1], readback: "refused", error: "x" }],
        },
      },
      rows,
      WORDS,
      AT,
    ) as ApplyReceipt;
    expect(r.ok).toBe(false);
    expect(r.undoUnavailable).toBe(true);
    const html = view(r);
    expect(html).toContain("Re-water point is still 63%.");
    expect(html).not.toContain("room:f1_|");
    expect(html).toContain(NO_UNDO);
  });

  test("skipped source keys are not copied, in the preview and the receipt, and no full copy is claimed", () => {
    expect(notCopiedLines([], WORDS, ["p1_target_vwc"])).toEqual(["Peak moisture (no reading)"]);
    const r = copyReceipt(
      ok({ diff: DIFF, missing: [], applied: verified, skipped: ["p1_target_vwc"] }),
      rows,
      WORDS,
      AT,
    ) as ApplyReceipt;
    expect(r.notCopied).toEqual(["Peak moisture (no reading)"]);
    const html = view(r);
    expect(html).toContain("Not copied: Peak moisture (no reading).");
    expect(html).toContain("Controller confirmed every value written");
    expect(html).not.toContain("Controller confirmed every value</small>");
  });

  test("an extra row the controller did not read back is named too, and the receipt claims nothing", () => {
    const r = copyReceipt(
      ok({
        diff: DIFF,
        missing: [],
        applied: [...verified, { target: F1, key: "maximum_ec", readback: "refused", error: "x" }],
      }),
      rows,
      WORDS,
      AT,
    ) as ApplyReceipt;
    expect(r.ok).toBe(false);
    expect(r.unconfirmed).toBe(true);
    expect(r.alsoWritten).toEqual(["Maximum pore EC (not read back)"]);
    const html = view(r);
    expect(html).toContain("Also written: Maximum pore EC (not read back).");
    expect(html).not.toContain("Written and read back");
  });

  test("an apply that wrote a row the preview did not show names it and claims nothing", () => {
    const r = copyReceipt(
      ok({
        diff: DIFF,
        missing: [],
        applied: [
          ...verified,
          { target: F1, key: "maximum_ec", readback: "verified", error: null },
        ],
      }),
      rows,
      WORDS,
      AT,
    ) as ApplyReceipt;
    expect(r.ok).toBe(false);
    expect(r.unconfirmed).toBe(true);
    expect(r.alsoWritten).toEqual(["Maximum pore EC"]);
    const html = view(r);
    expect(html).toContain("The copy changed more than the preview showed. Check History.");
    expect(html).toContain("Also written: Maximum pore EC.");
    expect(html).toContain('href="#/history/changes"');
    expect(html).not.toContain("Written and read back");
  });
});

test("every setting a preset or a copy can hold is named in words, never by its key", () => {
  const words = presetWords({}, []);
  for (const keys of Object.values(DEMO_PRESET_SECTIONS))
    for (const key of keys) {
      const label = words.label(key);
      expect(label, key).not.toMatch(/_/);
      expect(label, key).toMatch(/^[A-Z]/);
    }
  // The words the integration and the setting pages use, not the key with its underscores dropped.
  expect(words.label("maximum_ec")).toBe("Maximum pore EC");
  expect(words.label("p1_rise_pts")).toBe("Extra shot minimum rise");
  expect(words.label("min_daily_ml_per_plant")).toBe("Daily minimum water per plant");
});
