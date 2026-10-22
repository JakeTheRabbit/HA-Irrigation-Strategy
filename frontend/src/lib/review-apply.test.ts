import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, test, vi } from "vitest";
import { toast } from "sonner";
import {
  ReviewApplyView,
  closeSheetAfter,
  receiptFromV2,
  runApply,
  runUndo,
  type ApplyReceipt,
  type ApplyState,
  receiptFromWrite,
  type ReviewApplyProps,
  type ReviewRow,
} from "@/components/review-apply";
import { UndoError, offerUndo, revertEvents } from "./undo";
import { fakeController } from "./test-helpers";
import type { V2Outcome } from "./parity-api";

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const NZ = "Pacific/Auckland";
const AT = Date.parse("2026-10-22T14:02:00+13:00");
const row = (id: string, label: string, before: string, after: string): ReviewRow => ({
  id,
  label,
  before,
  after,
  undo: () => {},
});
const ROWS = [row("rewater", "Re-water point", "57%", "56%"), row("dryback", "Dryback by lights-on", "50%", "52%")];
const props = (over: Partial<ReviewApplyProps> = {}): ReviewApplyProps => ({
  rows: ROWS,
  layout: "bar",
  apply: () => Promise.resolve({ kind: "missing" }),
  onDiscard: () => {},
  timeZone: NZ,
  ...over,
});
const render = (p: ReviewApplyProps, state?: Parameters<typeof ReviewApplyView>[0]["state"]) =>
  renderToStaticMarkup(createElement(ReviewApplyView, { ...p, state: state ?? { phase: "idle" } }))
    .replace(/<!-- -->/g, "")
    .replace(/&amp;/g, "&");
type Applied = { target: string; key: string; readback: "verified" | "refused" }[];
const v2ok = (applied: Applied, verified = true): V2Outcome<{ applied?: Applied }> => ({
  kind: "ok",
  data: { applied },
  revision: 8,
  readback: { status: verified ? "verified" : "unverified", at: null },
  eventIds: ["01JB0000000000000000000001", "01JB0000000000000000000002"],
});

afterEach(() => vi.clearAllMocks());

describe("review & apply", () => {
  test("receipt says written and read back with zone clock", () => {
    const receipt = receiptFromV2(v2ok([{ target: "zone:1", key: "rewater", readback: "verified" }, { target: "zone:1", key: "dryback", readback: "verified" }]), ROWS, AT);
    expect(receipt).toMatchObject({ at: AT, ok: true, failed: [], eventIds: ["01JB0000000000000000000001", "01JB0000000000000000000002"] });
    const html = render(props({ rows: [], last: { ...receipt, by: "Ben" }, undo: () => Promise.resolve() }));
    expect(html).toContain("Written and read back 14:02");
    expect(html).toContain("Re-water point 57% → 56% · Dryback by lights-on 50% → 52%");
    expect(html).toContain("Controller confirmed every value · by Ben");
    expect(html).toContain("Undo: write back the previous values");
  });
  test("partial apply keeps failed rows in the draft", () => {
    const fromWrite = receiptFromWrite(
      { applied: ["number.f2_z1_rewater"], failed: [{ entityId: "number.f2_z1_dryback", reason: "Readback did not confirm" }] },
      ROWS,
      (entityId) => (entityId.endsWith("dryback") ? "dryback" : "rewater"),
      () => "50%",
      AT,
    );
    expect(fromWrite).toMatchObject({ ok: false, failed: [{ id: "dryback", holds: "50%" }] });
    expect(fromWrite.summary).toBe("Re-water point 57% → 56%");

    const refused = receiptFromV2(v2ok([{ target: "zone:1", key: "rewater", readback: "refused" }]), [ROWS[0]], AT);
    expect(refused).toMatchObject({ ok: false, failed: [{ id: "rewater", holds: "57%" }] });
    const html = render(props({ rows: [ROWS[0]] }), { phase: "done", result: refused });
    expect(html).toContain("Controller still holds 57%. Nothing else was changed.");
    expect(html).toContain("Try again");
    expect(html).not.toContain("Written and read back");

    // Several rows: each named, with what the controller still holds.
    const two = receiptFromV2(
      v2ok([{ target: "zone:1", key: "rewater", readback: "refused" }, { target: "zone:1", key: "dryback", readback: "refused" }]),
      ROWS,
      AT,
    );
    const twoHtml = render(props(), { phase: "done", result: two });
    expect(twoHtml).toContain("Re-water point is still 57%. Dryback by lights-on is still 50%. Nothing else was changed.");
    expect(twoHtml).not.toContain("Controller still holds");
  });
  test("an unverified read-back claims nothing about what the controller holds", () => {
    const unverified = receiptFromV2(v2ok([{ target: "zone:1", key: "rewater", readback: "verified" }], false), ROWS, AT);
    expect(unverified).toMatchObject({ ok: false, unconfirmed: true, summary: "" });
    expect(unverified.failed.map((f) => f.id)).toEqual(["rewater", "dryback"]);
    const html = render(props({ onReload: () => {} }), { phase: "done", result: unverified });
    expect(html).toContain("The controller did not confirm the values. Reload and check before trying again.");
    expect(html).not.toContain("still holds");
    expect(html).not.toContain("is still");
    expect(html).not.toContain("Written and read back");
    expect(html).toContain(">Reload<");
  });
  test("refusals match on target and key: a refused rewater in zone 2 is not missed", () => {
    const zoneRows: ReviewRow[] = [
      { ...row("z1:rewater", "Zone 1 re-water point", "57%", "56%"), target: "zone:1", key: "rewater" },
      { ...row("z2:rewater", "Zone 2 re-water point", "58%", "56%"), target: "zone:2", key: "rewater" },
    ];
    const receipt = receiptFromV2(
      v2ok([{ target: "zone:1", key: "rewater", readback: "verified" }, { target: "zone:2", key: "rewater", readback: "refused" }]),
      zoneRows,
      AT,
    );
    expect(receipt).toMatchObject({ ok: false, failed: [{ id: "z2:rewater", holds: "58%" }], summary: "Zone 1 re-water point 57% → 56%" });
    // Rows that carry no target or key: a refused entry that matches no row fails every row.
    const bare = [row("z1:rewater", "Zone 1 re-water point", "57%", "56%"), row("z2:rewater", "Zone 2 re-water point", "58%", "56%")];
    const unmatched = receiptFromV2(v2ok([{ target: "zone:2", key: "rewater", readback: "refused" }]), bare, AT);
    expect(unmatched.ok).toBe(false);
    expect(unmatched.failed.map((f) => f.id)).toEqual(["z1:rewater", "z2:rewater"]);
    expect(unmatched.summary).toBe("");
  });
  test("stale_revision keeps draft and offers reload", () => {
    const stale: V2Outcome<unknown> = { kind: "error", code: "stale_revision", message: "Revision 7 is stale", currentRevision: 8 };
    const html = render(props({ onReload: () => {} }), { phase: "done", result: stale });
    expect(html).toContain("Someone else changed this since you started editing. Reload their version and reapply your edits.");
    expect(html).toContain(">Reload<");
    // The rows (the draft) are still listed and can still be applied.
    expect(html).toContain("Re-water point");
    expect(html).toContain("Apply 2 changes");
  });
  test("forbidden error shows admin copy", () => {
    const html = render(props(), { phase: "done", result: { kind: "error", code: "forbidden", message: "Unauthorized" }});
    expect(html).toContain("Only a Home Assistant administrator can change this.");
    const guard = render(props(), { phase: "done", result: { kind: "error", code: "guard_refused", message: "Keep or undo the AI change first" } });
    expect(guard).toContain("The controller refused: Keep or undo the AI change first");
    const missing = render(props(), { phase: "done", result: { kind: "missing" } });
    expect(missing).toContain("Needs integration 3.18");
  });
  test("an unknown code gets plain copy and the code as a detail, not the raw message", () => {
    const html = render(props(), { phase: "done", result: { kind: "error", code: "unknown", message: "KeyError: 'zone_9' at line 42" } });
    expect(html).toContain("The controller refused this change.");
    expect(html).toContain("Code: unknown");
    expect(html).not.toContain("KeyError");
    expect(render(props(), { phase: "done", result: { kind: "error", code: "invalid", message: "x" } })).toContain("Code: invalid");
  });
  test("Apply button names the count", () => {
    expect(render(props())).toContain("Apply 2 changes");
    expect(render(props())).toContain("2 changes · Review & apply");
    const one = render(props({ rows: [ROWS[0]] }));
    expect(one).toContain("Apply 1 change<");
    expect(one).toContain("1 change · Review & apply");
    const panel = render(props({ layout: "panel" }));
    expect(panel).toContain("Review & apply");
    expect(panel).toContain("2 unsaved changes, not active until applied");
    expect(render(props({ layout: "panel", rows: [ROWS[0]] }))).toContain("1 unsaved change, not active until applied");
    const sending = render(props(), { phase: "sending" });
    expect(sending).toContain("Sending…");
  });
  test("discardLabel and summary override the defaults", () => {
    expect(render(props())).toContain("Discard edits");
    const html = render(props({ discardLabel: "Discard", summary: "Notify rules · 2 edits" }));
    expect(html).toContain(">Discard<");
    expect(html).toContain("Notify rules · 2 edits");
    expect(html).not.toContain("2 changes · Review & apply");
  });
  test("a failed check blocks apply", () => {
    const html = render(props({ checks: [{ ok: true, text: "Pump keeps up" }, { ok: false, text: "Over the pump" }] }));
    expect(html).toContain("Fix the red check to apply");
    expect(html).not.toContain("Apply 2 changes");
  });
});

describe("undo", () => {
  test("offerUndo calls sonner with a 10 s Undo action", async () => {
    const undo = vi.fn(() => Promise.resolve());
    offerUndo({ message: "Rule deleted", undo });
    expect(toast).toHaveBeenCalledWith("Rule deleted", expect.objectContaining({ duration: 10_000, action: expect.objectContaining({ label: "Undo" }) }));
    const options = vi.mocked(toast).mock.calls[0][1] as unknown as { action: { onClick: () => void } };
    options.action.onClick();
    await Promise.resolve();
    expect(undo).toHaveBeenCalledOnce();
  });
  test("offerUndo says so when the undo is refused", async () => {
    offerUndo({ message: "Saved", undo: () => Promise.reject(new Error("This change can't be put back")) });
    (vi.mocked(toast).mock.calls[0][1] as unknown as { action: { onClick: () => void } }).action.onClick();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(toast.error).toHaveBeenCalledWith("This change can't be put back");
  });
  test("revertEvents calls history_revert newest first", async () => {
    const calls: unknown[] = [];
    const controller = fakeController({
      operator: (action, data) => {
        calls.push([action, data]);
        return Promise.resolve({ api: 2, ok: true, readback: { status: "verified", at: null }, event_ids: [], data: { reverted_event_id: data?.event_id, new_event_id: "n", readback: "verified" } });
      },
    });
    await revertEvents(controller, ["01JB0000000000000000000001", "01JB0000000000000000000003", "01JB0000000000000000000002"]);
    expect(calls.map((c) => (c as [string, { event_id: string }])[1].event_id)).toEqual([
      "01JB0000000000000000000003",
      "01JB0000000000000000000002",
      "01JB0000000000000000000001",
    ]);
    expect(calls.every((c) => (c as [string])[0] === "history_revert")).toBe(true);
    for (const [, data] of calls as [string, Record<string, unknown>][]) {
      expect(data).not.toHaveProperty("client");
      expect(data).not.toHaveProperty("proposal_token");
    }
  });
  test("revertEvents stops at the first refusal and never claims undone", async () => {
    const seen: string[] = [];
    const controller = fakeController({
      operator: (_action, data) => {
        seen.push(String(data?.event_id));
        return Promise.resolve({ api: 2, ok: false, error: { code: "guard_refused", message: "Keep or undo the AI change first" } });
      },
    });
    await expect(revertEvents(controller, ["a1", "a2"])).rejects.toThrow("Keep or undo the AI change first");
    expect(seen).toEqual(["a2"]);
    const unverified = fakeController({
      operator: () => Promise.resolve({ api: 2, ok: true, readback: { status: "unverified", at: null }, event_ids: [], data: {} }),
    });
    await expect(revertEvents(unverified, ["a1"])).rejects.toThrow(/did not confirm/);
    const missing = fakeController({ operator: () => Promise.reject(Object.assign(new Error("Service crop_steering.history_revert not found."), { code: "not_found" })) });
    await expect(revertEvents(missing, ["a1"])).rejects.toThrow(/3\.18/);
  });
});


describe("partial undo", () => {
  const answers = (...outcomes: unknown[]) => {
    let i = 0;
    return fakeController({ operator: () => (outcomes[i] instanceof Error ? Promise.reject(outcomes[i++]) : Promise.resolve(outcomes[i++])) });
  };
  const ok = { api: 2, ok: true, readback: { status: "verified", at: null }, event_ids: [], data: {} };
  const guard = { api: 2, ok: false, error: { code: "guard_refused", message: "Keep or undo the AI change first" } };
  const missing = Object.assign(new Error("Service crop_steering.history_revert not found."), { code: "not_found" });

  test("revertEvents says how many it put back before the refusal", async () => {
    const error = await revertEvents(answers(ok, guard, ok), ["a1", "a2", "a3"]).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(UndoError);
    expect(error).toMatchObject({ reverted: 1, total: 3, message: "1 of 3 put back: Keep or undo the AI change first" });
    const first = await revertEvents(answers(guard), ["a1", "a2"]).catch((e: unknown) => e);
    expect(first).toMatchObject({ reverted: 0, total: 2, message: "Keep or undo the AI change first" });
  });
  test("missing says nothing was changed only when nothing was put back", async () => {
    const none = await revertEvents(answers(missing), ["a1", "a2"]).catch((e: Error) => e);
    expect((none as Error).message).toBe("Undo needs Crop Steering 3.18 or newer. Nothing was changed.");
    const some = await revertEvents(answers(ok, missing), ["a1", "a2"]).catch((e: Error) => e);
    expect((some as Error).message).toBe("1 of 2 put back: Undo needs Crop Steering 3.18 or newer.");
    expect((some as Error).message).not.toContain("Nothing was changed");
  });
  test("a partial undo drops the green receipt; a refused first step keeps it", () => {
    const receipt: ApplyReceipt = { at: AT, ok: true, failed: [], summary: "Re-water point 57% → 56%", eventIds: ["a1", "a2"] };
    const partial = render(props({ rows: [], undo: () => Promise.resolve() }), {
      phase: "undo-failed",
      receipt,
      reverted: 1,
      message: "1 of 2 put back: Keep or undo the AI change first",
    });
    expect(partial).toContain("1 of 2 put back: Keep or undo the AI change first");
    expect(partial).not.toContain("Written and read back");
    expect(partial).not.toContain("Undo: write back the previous values");
    const none = render(props({ rows: [], undo: () => Promise.resolve() }), {
      phase: "undo-failed",
      receipt,
      reverted: 0,
      message: "Keep or undo the AI change first",
    });
    expect(none).toContain("Written and read back 14:02");
    expect(none).toContain("Keep or undo the AI change first");
  });
});

describe("ReviewApply states", () => {
  const receipt: ApplyReceipt = { at: AT, ok: true, failed: [], summary: "Re-water point 57% → 56%", eventIds: ["a1"] };
  test("apply goes sending → done with the receipt, and a thrown apply is an error, not a receipt", async () => {
    const states: ApplyState[] = [];
    expect(await runApply(() => Promise.resolve(receipt), (s) => states.push(s))).toBe(receipt);
    expect(states.map((s) => s.phase)).toEqual(["sending", "done"]);
    expect(states[1]).toMatchObject({ phase: "done", result: receipt });
    const thrown: ApplyState[] = [];
    await runApply(() => Promise.reject(new Error("socket closed")), (s) => thrown.push(s));
    expect(thrown[1]).toMatchObject({ phase: "done", result: { kind: "error", code: "unknown" } });
  });
  test("undo goes undoing → undone, or undo-failed carrying the number put back", async () => {
    const states: ApplyState[] = [];
    await runUndo(() => Promise.resolve(), receipt, (s) => states.push(s), () => AT);
    expect(states).toEqual([{ phase: "undoing", receipt }, { phase: "undone", at: AT }]);
    expect(render(props({ rows: [] }), states[1])).toContain("Previous values written back 14:02");
    const failed: ApplyState[] = [];
    await runUndo(() => Promise.reject(new UndoError("1 of 2 put back: nope", 1, 2)), receipt, (s) => failed.push(s));
    expect(failed[1]).toEqual({ phase: "undo-failed", receipt, reverted: 1, message: "1 of 2 put back: nope" });
    const plain: ApplyState[] = [];
    await runUndo(() => Promise.reject(new Error("Write failed")), receipt, (s) => plain.push(s));
    expect(plain[1]).toMatchObject({ phase: "undo-failed", reverted: 0, message: "Write failed" });
  });
  test("a successful apply closes the phone sheet and returns focus to its trigger", () => {
    const calls: string[] = [];
    const sheet = { close: () => calls.push("close") };
    const trigger = { focus: () => calls.push("focus") };
    closeSheetAfter(receipt, sheet, trigger);
    expect(calls).toEqual(["close", "focus"]);
    calls.length = 0;
    closeSheetAfter({ ...receipt, ok: false, failed: [{ id: "rewater", holds: "57%" }] }, sheet, trigger);
    closeSheetAfter({ kind: "error", code: "forbidden", message: "" }, sheet, trigger);
    expect(calls).toEqual([]);
  });
});
