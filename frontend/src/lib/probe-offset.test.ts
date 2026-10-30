import { describe, expect, it } from "vitest";
import { createDemo } from "./demo";
import { OperatorDemo } from "./operator-demo";
import { callV2 } from "./parity-api";
import { revertEvents } from "./undo";
import {
  CURVE_ON_PERCENT,
  applyOffset,
  curveDisabledReason,
  handheldOffset,
  previewOffset,
  offsetsBlocked,
  readOffsets,
  signedPoints,
} from "./probe-offset";

const envelope = (data: unknown, extra: Record<string, unknown> = {}) => ({
  api: 2,
  ok: true,
  room_id: "room:room_b_",
  revision: 4,
  readback: { status: "none", at: "2026-10-23T02:02:00Z" },
  event_ids: ["01JEVENT"],
  data,
  ...extra,
});

/** The integration as the panel calls it: probe_offset_set writes, calibration_get reads back. */
function fakeController(stored: number | null, write: Record<string, unknown> = {}) {
  const calls: [string, Record<string, unknown>][] = [];
  return {
    calls,
    operator: async <T,>(action: string, data: Record<string, unknown> = {}): Promise<T> => {
      calls.push([action, data]);
      if (action === "probe_offset_set")
        return envelope({ offset: 3, curve: null, corrected_now: 61.2, fused_before: 63.8, fused_after: 65.3, excluded_after: {}, revision: 4, ...write }) as T;
      return envelope({
        revision: 4,
        probe_user_offsets: stored === null ? {} : { "sensor.f1_z1_back_vwc": { offset: stored, curve: null } },
      }) as T;
    },
  };
}
const request = {
  roomId: "room:room_b_",
  entityId: "sensor.f1_z1_back_vwc",
  offset: 3,
  revision: 3,
  room: "F1",
  zone: "Zone 1",
  probe: "Zone 1 Back",
  now: () => Date.parse("2026-10-23T02:02:00Z"),
};

describe("handheldOffset", () => {
  it("handheldOffset 61.0 vs 64.0 is +3.0", () => {
    expect(handheldOffset(61.0, 64.0)).toBe(3);
    expect(signedPoints(handheldOffset(61.0, 64.0))).toBe("+3.0");
  });
  it("rounds as the integration does, to 3 places, and signs a negative with a minus", () => {
    expect(handheldOffset(61.15, 60.0)).toBe(-1.15);
    expect(signedPoints(-1.3)).toBe("−1.3");
    expect(signedPoints(0)).toBe("0.0");
  });
});

describe("curveDisabledReason", () => {
  it("curveDisabledReason for a VWC-native probe", () => {
    expect(curveDisabledReason({ unit: "%" })).toBe(CURVE_ON_PERCENT);
    expect(curveDisabledReason({ unit: "m³/m³" })).toBe(
      "This probe already converts to moisture. A curve only applies to raw readings.",
    );
  });
  it("lets a permittivity probe take a curve, and names any other unit as the integration does", () => {
    expect(curveDisabledReason({ unit: "ε" })).toBeNull();
    expect(curveDisabledReason({ unit: "Dielectric permittivity" })).toBeNull();
    expect(curveDisabledReason({ unit: "mV" })).toBe(
      "A curve applies only to a probe that reports permittivity (unit ε, permittivity or dielectric). This probe reports 'mV'.",
    );
  });
});

describe("readOffsets", () => {
  it("reads each probe's offset from the calibration store; none on an integration without them", () => {
    expect(readOffsets({ probe_user_offsets: { "sensor.a": { offset: 3, curve: null } } })).toEqual({
      "sensor.a": { offset: 3, curve: null },
    });
    expect(readOffsets({ revision: 1 })).toBeNull();
  });
  it("reads a malformed stored offset as unknown, never 0; an entry without one holds none", () => {
    expect(
      readOffsets({ probe_user_offsets: { "sensor.a": { offset: "bad", curve: null }, "sensor.b": { offset: null }, "sensor.c": { curve: null } } }),
    ).toEqual({
      "sensor.a": { offset: null, curve: null },
      "sensor.b": { offset: null, curve: null },
      "sensor.c": { offset: 0, curve: null },
    });
  });
  it("treats the offsets as unknown when the integration cannot read its store, and says why", () => {
    const message =
      "The stored probe offsets could not be read; they have not been overwritten and the probes read without them: bad";
    const document = { probe_user_offsets: { "sensor.a": { offset: 3, curve: null } }, error: null, offsets_error: message };
    expect(readOffsets(document)).toBeNull();
    expect(offsetsBlocked(document)).toBe(message);
    expect(offsetsBlocked({ probe_user_offsets: {}, error: null, offsets_error: null })).toBeNull();
  });
  it("blocks matching while the calibration history cannot be read: the integration refuses the write", () => {
    const document = { probe_user_offsets: { "sensor.a": { offset: 3, curve: null } }, error: "Stored calibration history could not be loaded", offsets_error: null };
    expect(readOffsets(document)).toEqual({ "sensor.a": { offset: 3, curve: null } });
    expect(offsetsBlocked(document)).toBe("Stored calibration history could not be loaded");
  });
});

describe("applyOffset", () => {
  it("receipt line uses fused_before and fused_after", async () => {
    const controller = fakeController(3);
    const receipt = await applyOffset(controller, request);
    // Read back: the stored offset. The zone's value is the integration's own figure, and says so.
    expect(receipt).toMatchObject({
      ok: true,
      summary: "Zone 1 Back offset — → +3.0 · F1 Zone 1 value 63.8% → 65.3% (integration's figure)",
      eventIds: ["01JEVENT"],
    });
    // The write names exactly the offset reviewed and the revision the preview gave; never client or proposal_token.
    expect(controller.calls[0]).toEqual([
      "probe_offset_set",
      { room_id: "room:room_b_", entity_id: "sensor.f1_z1_back_vwc", offset: 3, expected_revision: 3, api: 2 },
    ]);
    expect(controller.calls[1][0]).toBe("calibration_get");
  });
  it("claims nothing when the store does not read the offset back", async () => {
    const receipt = await applyOffset(fakeController(1.5), request);
    expect(receipt).toMatchObject({ ok: false, unconfirmed: true, summary: "" });
  });
  it("claims nothing when the store reads back a malformed offset, even for a write of 0", async () => {
    const controller = fakeController("bad" as unknown as number, { offset: 0 });
    const receipt = await applyOffset(controller, { ...request, offset: 0 });
    expect(receipt).toMatchObject({ ok: false, unconfirmed: true });
  });
  it("names the offset when the zone has no value to show", async () => {
    const receipt = await applyOffset(fakeController(3, { fused_before: null, fused_after: null }), { ...request, before: 0 });
    expect(receipt).toMatchObject({ ok: true, summary: "Zone 1 Back offset 0.0 → +3.0" });
  });
  it("does not invent the offset it replaced when the store could not be read before", async () => {
    const receipt = await applyOffset(fakeController(3, { fused_before: null, fused_after: null }), { ...request, before: null });
    expect(receipt).toMatchObject({ ok: true, summary: "Zone 1 Back offset — → +3.0" });
  });
  it("says Undo is not available here when no Journal event came back", async () => {
    const controller = fakeController(3);
    const operator = controller.operator;
    controller.operator = async <T,>(action: string, data: Record<string, unknown> = {}) => {
      const answer = (await operator(action, data)) as Record<string, unknown>;
      return { ...answer, event_ids: [] } as T;
    };
    expect(await applyOffset(controller, request)).toMatchObject({ ok: true, undoUnavailable: true });
  });
  it("passes the integration's refusal through as given", async () => {
    const controller = {
      operator: async <T,>() =>
        ({ api: 2, ok: false, error: { code: "invalid", message: "The probe would read 104, outside 0 to 100" } }) as T,
    };
    expect(await applyOffset(controller, request)).toEqual({
      kind: "error",
      code: "invalid",
      message: "The probe would read 104, outside 0 to 100",
    });
  });
});

describe("the demo's probe offsets (3.18)", () => {
  it("previews, writes, reads back, and puts back once, refusing a stale write", async () => {
    let states = createDemo(Date.now());
    const demo = new OperatorDemo(() => states, (next) => (states = next), null, null, "3.18");
    const controller = { operator: <T,>(action: string, data: Record<string, unknown> = {}) => demo.call<T>(action as never, { room_id: "room:", ...data }) };
    const probe = "sensor.demo_z1_back_vwc";
    const raw = Number(states[probe].state);
    const preview = await previewOffset(controller, "room:", probe, raw + 3);
    expect(preview).toMatchObject({ kind: "ok", data: { offset: 3 } });
    if (preview.kind !== "ok") return;
    const { fused_before: before, fused_after: after, revision } = preview.data;
    expect(after! - before!).toBeCloseTo(1.5);
    const receipt = await applyOffset(controller, { ...request, roomId: "room:", entityId: probe, revision, room: "Room A" });
    expect(receipt).toMatchObject({
      ok: true,
      summary: `Zone 1 Back offset — → +3.0 · Room A Zone 1 value ${before!.toFixed(1)}% → ${after!.toFixed(1)}% (integration's figure)`,
    });
    expect(Number(states["sensor.crop_steering_vwc_zone_1"].state)).toBeCloseTo(after!, 1);
    // The preview's revision has moved on.
    expect(await applyOffset(controller, { ...request, roomId: "room:", entityId: probe, revision, room: "Room A" })).toMatchObject({
      kind: "error",
      code: "stale_revision",
    });
    const ids = "eventIds" in receipt ? receipt.eventIds : [];
    await revertEvents(controller, ids);
    expect(readOffsets(((await callV2(controller, "calibration_get", {})) as { data: unknown }).data)).toEqual({});
    await expect(revertEvents(controller, ids)).rejects.toThrow("can't be put back");
  });
});
