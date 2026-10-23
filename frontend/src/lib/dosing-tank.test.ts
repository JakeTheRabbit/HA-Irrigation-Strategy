import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { BatchDoses, Dosing, GuardMark, MixCheckCard, NextBatchCard } from "@/pages/dosing";
import { dosingConfigId, dosingStatusId, type MixCheck, type RecipeRow } from "./dosing";
import { reservoirView, tankLevelId } from "./reservoir";
import { demoController, fakeController } from "./test-helpers";
import type { States } from "./types";

const render = (search = "?demo=1") =>
  renderToStaticMarkup(
    createElement(Dosing, {
      controller: demoController(search),
      navigate: () => {},
      onDirtyChange: () => {},
    }),
  );

describe("Equipment › Feed & dosing owns the tank", () => {
  test("draws the tank and pump card and the tank minimum in the plumbing, then the level chart", () => {
    const html = render();
    const plumbing = html.slice(html.indexOf("data-plumbing"));
    expect(plumbing).toContain("data-tank-status");
    expect(plumbing).toContain("Tank and pump");
    expect(plumbing).toContain('data-reservoir-guard="ok"');
    expect(plumbing).toContain("Minimum 8%");
    expect(plumbing).toContain("Overfill cut 102%");
    expect(html).toContain("data-tank-level-chart");
    expect(html).toContain("Feed &amp; dosing · Room A");
    // The old tank-minimum panel is gone: its facts live on the drawing.
    expect(html).not.toContain("reservoir-guard-title");
  });
});

describe("Equipment › Feed & dosing: the mix check in place", () => {
  test("a failed mix check sits inside the plumbing, with its hold and the probe's calibration", () => {
    const html = render();
    expect(html).toContain("protections armed 5 of 5");
    const plumbing = html.slice(html.indexOf("data-plumbing"), html.indexOf("data-feed-recipes"));
    expect(plumbing).toContain('data-mix-check="off target"');
    expect(plumbing).toContain("Mix check failed");
    expect(plumbing).toContain("Want EC 2.30–3.50 mS/cm; it read 3.71 mS/cm.");
    expect(plumbing).toContain('data-mode="hold-to-confirm"');
    expect(plumbing).toContain("Top up and re-check");
    expect(plumbing).toContain("Feed EC probe calibrated 9 days ago");
    expect(plumbing).toContain('href="#/equipment/feed-calibration"');
    // No way to release a held feed: no service does it.
    expect(html).not.toContain("Use once anyway");
  });
});

const entity = (entity_id: string, state: string, attributes: Record<string, unknown> = {}) => ({
  entity_id,
  state,
  attributes,
});
const renderWith = (states: States) =>
  renderToStaticMarkup(
    createElement(Dosing, {
      controller: fakeController({ states }),
      navigate: () => {},
      onDirtyChange: () => {},
    }),
  );

describe("Equipment › Feed & dosing: marks and lines", () => {
  test("armed marks are images a screen reader names", () => {
    const html = render();
    expect(html).toMatch(
      /<svg[^>]*role="img"[^>]*aria-label="Armed"|<svg[^>]*aria-label="Armed"[^>]*role="img"/,
    );
  });
  test("without a dosing setup the minimum mark is not armed while the level reads nothing", () => {
    const html = renderWith({
      [tankLevelId("")]: entity(tankLevelId(""), "unavailable", { minimum_pct: 8 }),
    });
    const guard = html.slice(html.indexOf("data-reservoir-guard"));
    expect(guard).toContain('data-protection="off"');
  });
  test("a room with no dosing pumps still says how the last batch ended", () => {
    const html = renderWith({
      [dosingConfigId("")]: entity(dosingConfigId(""), "1", { pumps: [], batch: {} }),
      [dosingStatusId("")]: entity(dosingStatusId(""), "idle", {
        batch: { step: "idle", steps: [], result: "finished" },
        history: [
          {
            kind: "batch",
            at: "2026-10-23T01:00:00Z",
            ended_at: "2026-10-23T01:40:00Z",
            result: "finished",
          },
        ],
      }),
    });
    expect(html).toContain("data-batch-line");
    expect(html).toContain("last batch finished");
  });
});

describe("Equipment › Feed & dosing: the mix check names its probe", () => {
  const bands: States = Object.fromEntries(
    (
      [
        ["ec_min", "2.3"],
        ["ec_max", "3.5"],
        ["ph_min", "5.6"],
        ["ph_max", "6.2"],
      ] as const
    ).map(([key, value]) => {
      const id = `number.crop_steering_irrigation_${key}`;
      return [id, entity(id, value)];
    }),
  );
  const card = (mix: Partial<MixCheck>) =>
    renderToStaticMarkup(
      createElement(MixCheckCard, {
        mix: {
          batch: null,
          due: null,
          verdict: "off target",
          checked_at: null,
          why: null,
          gave_up_at: null,
          ec: null,
          ph: null,
          probes: ["ec", "ph"],
          ...mix,
        },
        states: bands,
        prefix: "",
        calibration: {
          ec: Date.parse("2026-10-14T00:00:00Z"),
          ph: Date.parse("2026-10-20T00:00:00Z"),
        },
        now: Date.parse("2026-10-23T00:00:00Z"),
        tz: "UTC",
        block: null,
        room: "Room A",
        warning: null,
        onTopUp: () => {},
        error: "",
      }),
    );
  test("only pH off: the pH probe's calibration, not the EC probe's", () => {
    const html = card({
      ec: 2.8,
      ph: 7.2,
      why: "its pH reads 7.2, outside the feed pH band of the room (5.6 to 6.2)",
    });
    expect(html).toContain("Want pH 5.60–6.20; it read 7.20.");
    expect(html).toContain("Feed pH probe calibrated 3 days ago");
    expect(html).not.toContain("Feed EC probe");
    // The hold makes a batch at once: the card says watering is held while it runs.
    expect(html).toContain(
      "While the batch runs, watering in Room A, and in any room whose pump or valves the batch uses, is held.",
    );
  });
  test("a dosed pump that is not ready is said under the hold", () => {
    const html = renderToStaticMarkup(
      createElement(MixCheckCard, {
        mix: {
          batch: null,
          due: null,
          verdict: "off target",
          checked_at: null,
          why: null,
          gave_up_at: null,
          ec: 3.7,
          ph: 5.8,
          probes: ["ec", "ph"],
        },
        states: bands,
        prefix: "",
        calibration: { ec: null, ph: null },
        now: Date.parse("2026-10-23T00:00:00Z"),
        tz: "UTC",
        block: null,
        room: "Room A",
        warning: "Part B is not calibrated: the controller would refuse a batch now.",
        onTopUp: () => {},
        error: "",
      }),
    );
    const after = html.slice(html.indexOf("Top up and re-check"));
    expect(after).toContain("Part B is not calibrated: the controller would refuse a batch now.");
  });
  test("not read: the unreadable probe stays named beside an off-band reading", () => {
    const html = card({
      verdict: "not read",
      ec: null,
      ph: 7.2,
      why: "its EC probe (sensor.feed_ec) is not readable (it reads unavailable); its pH reads 7.2, outside the feed pH band of the room (5.6 to 6.2)",
    });
    expect(html).toContain("Want pH 5.60–6.20; it read 7.20.");
    expect(html).toContain("its EC probe (sensor.feed_ec) is not readable (it reads unavailable)");
    // The off-band reading is said once, in display units.
    expect(html).not.toContain("outside the feed pH band");
    expect(html).toContain("Feed EC probe calibrated 9 days ago");
    expect(html).toContain("Feed pH probe calibrated 3 days ago");
  });
  test("a pH-only room's unread check names only the pH probe", () => {
    const html = card({
      verdict: "not read",
      ph: null,
      probes: ["ph"],
      why: "its pH probe (sensor.feed_ph) is not readable (it reads unavailable)",
    });
    expect(html).toContain('data-mix-gauge="pH"');
    expect(html).not.toContain('data-mix-gauge="EC"');
    expect(html).not.toContain("EC not read");
    expect(html).not.toContain("feed EC probe");
    expect(html).not.toContain("Feed EC probe");
    expect(html).toContain("Feed pH probe calibrated 3 days ago");
  });
  test("a check given up on draws no probe it never read", () => {
    const html = card({
      verdict: null,
      gave_up_at: "2026-10-22T10:00:00Z",
      why: "the dosing setup could not be read",
      probes: [],
    });
    expect(html).toContain("Mix check not done");
    expect(html).not.toContain("data-mix-gauge");
    expect(html).not.toContain("data-mix-probe");
  });
});

describe("Equipment › Feed & dosing: the batch card and the marks say what each line does", () => {
  test("the batch lists passed-by pumps, unknown pumps, amounts from an entity and each line's time", () => {
    const row = (over: Partial<RecipeRow>): RecipeRow => ({
      pump: "a",
      name: "Part A",
      ml: 40,
      fixed: 40,
      entity: null,
      fromEntity: false,
      unreadable: false,
      flow: 1,
      seconds: 40,
      skipped: false,
      unknown: false,
      ...over,
    });
    const html = renderToStaticMarkup(
      createElement(BatchDoses, {
        rows: [
          row({}),
          row({ pump: "b", name: "Part B", ml: 0, fixed: 0, skipped: true, seconds: null }),
          row({ pump: "ghost", name: "ghost", unknown: true, flow: null, seconds: null }),
          row({
            pump: "c",
            name: "Cal",
            entity: "number.cal_ml",
            unreadable: true,
            ml: 0,
            seconds: null,
          }),
        ],
      }),
    );
    expect(html).toContain("40 mL");
    expect(html).toContain("40 s");
    expect(html).toContain("passed by");
    expect(html).toContain("not a pump of this room");
    expect(html).toContain("from number.cal_ml, which reads nothing");
  });
  test("the minimum mark says when the litres per 1% are not learned yet", () => {
    const id = tankLevelId("");
    const guard = reservoirView({ [id]: entity(id, "64", { minimum_pct: 8 }) }, "");
    expect(guard.state).toBe("ok");
    const html = renderToStaticMarkup(
      createElement(GuardMark, {
        guard,
        item: { label: "Minimum 8%", ok: true },
        onConfigure: () => {},
      }),
    );
    expect(html).toContain("litres per 1% not learned yet");
  });
  test("the next batch's stock warning links to the stock tanks; its missing time says why", () => {
    const html = renderToStaticMarkup(
      createElement(NextBatchCard, {
        next: {
          at: null,
          litres: null,
          doses: [],
          steps: [],
          stockWarning: "Part A runs low after this batch.",
        },
        atPct: 8,
        why: "Not known yet: the recorded tank level is still loading",
        now: 0,
        tz: "UTC",
        navigate: () => {},
      }),
    );
    expect(html).toContain('href="#/equipment/stock"');
    expect(html).toContain("Not known yet: the recorded tank level is still loading");
  });
});
