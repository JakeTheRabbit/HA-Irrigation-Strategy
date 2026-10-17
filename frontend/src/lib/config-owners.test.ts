import { CanonicalControls } from "@/components/canonical-controls";
import { settingWords } from "./setting-words";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Features } from "@/pages/features";
import { describe, expect, it } from "vitest";
import { FEATURES, controlsOf, featureRows } from "./features";
import { ownerHref, ownerKey, supplementalRow } from "./config-owners";
import { parseRoute } from "./routes";
import type { Controller, States } from "./types";

const states: States = Object.fromEntries(
  FEATURES.flatMap((f) =>
    controlsOf(f).flatMap((c) =>
      [null, 1]
        .filter((z) => (z === null ? c.scope !== "zone" : c.scope !== "room"))
        .map((z) => {
          const id = `${c.domain}.crop_steering_test_${z === null ? "" : "zone_1_"}${c.key}`;
          return [
            id,
            {
              entity_id: id,
              state: c.domain === "switch" ? "off" : c.domain === "number" ? "1" : "Off",
              attributes: { min: 0, max: 100, step: 1, options: ["Off", "On"] },
            },
          ];
        }),
    ),
  ),
);
const controller = {
  states,
  room: { engine: { entityId: null }, settings: [], room: { prefix: "test_" }, zones: [{ id: 1 }] },
} as unknown as Controller;
const rows = featureRows(states, "test_", [1], null);

describe("capability owners", () => {
  it("every registry feature has a routable canonical workspace", () => {
    for (const f of FEATURES) {
      expect(ownerKey(f)).toBeTruthy();
      expect(parseRoute(ownerHref(f)).canonical, f.id).toBe(true);
    }
  });
  it("keeps registry-only stage, pH correction, AI permissions and probe methods editable", () => {
    for (const id of [
      "stage",
      "ph_auto_correct",
      "ai_power_advance_phase",
      "probe_methods",
      "lf_11",
      "runoff_estimator",
    ]) {
      const row = rows.find((f) => f.feature.id === id)!;
      expect(
        [row.master, ...row.settings]
          .filter(Boolean)
          .some((r) => supplementalRow(row.feature, r!, controller)),
        id,
      ).toBe(true);
    }
  });
  it("uses Setup for zone sizing and retains the distinct room defaults", () => {
    const row = rows.find((f) => f.feature.id === "sizing")!;
    for (const control of row.settings) {
      const result = supplementalRow(row.feature, control, controller);
      expect(result?.zones ?? []).toEqual([]);
      if (control.room) expect(result?.room).toEqual(control.room);
    }
  });
  it("never duplicates a number already rendered by the canonical target or safety form", () => {
    const row = rows.find((f) => f.feature.id === "p1")!;
    const control = row.settings[0];
    const owned = {
      ...controller,
      room: {
        ...controller.room,
        settings: [
          { entityId: control.room!.entityId },
          ...control.zones.map((c) => ({ entityId: c.entityId })),
        ],
      },
    } as unknown as Controller;
    expect(supplementalRow(row.feature, control, owned)).toBeNull();
  });
});

it("capabilities directory exposes status and owner links without control writers", () => {
  const markup = renderToStaticMarkup(createElement(Features, { controller }));
  expect(markup).toContain("Dosing settings");
  expect(markup).toContain("feature=ph_auto_correct");
  expect(markup).not.toContain('role="switch"');
  expect(markup).not.toContain('type="number"');
  expect(markup).not.toContain("Review changes");
});

it("room mode-dependent defaults remain editable when Strategy renders only zone targets", () => {
  for (const key of [
    "vegetative_dryback_target",
    "generative_dryback_target",
    "ec_target_veg_p0",
    "ec_target_gen_p1",
  ]) {
    const feature = rows.find((f) => f.settings.some((r) => r.control.key === key))!;
    const row = feature.settings.find((r) => r.control.key === key)!;
    const settings = [row.room, ...row.zones].flatMap((c) => (c ? [{ entityId: c.entityId }] : []));
    const owner = {
      ...controller,
      room: { ...controller.room, settings },
    } as unknown as Controller;
    const supplemental = supplementalRow(feature.feature, row, owner);
    expect(supplemental?.room?.entityId, key).toBe(row.room?.entityId);
    expect(supplemental?.zones, key).toEqual([]);
  }
});

it("canonical Irrigation actually renders the room default editors omitted from Strategy", () => {
  const settings = rows.flatMap((f) =>
    f.settings.flatMap((r) =>
      [r.room, ...r.zones].flatMap((c) => (c ? [{ entityId: c.entityId }] : [])),
    ),
  );
  const owner = {
    ...controller,
    connection: "demo",
    admin: true,
    room: {
      ...controller.room,
      settings,
      strategy: { engaged: false },
      room: { ...controller.room.room, name: "Test" },
    },
  } as unknown as Controller;
  const markup = renderToStaticMarkup(
    createElement(CanonicalControls, { controller: owner, owner: "irrigation" }),
  );
  for (const key of [
    "vegetative_dryback_target",
    "generative_dryback_target",
    "ec_target_veg_p0",
    "ec_target_gen_p1",
  ]) {
    const label = settingWords(key)?.label ?? key.replaceAll("_", " ");
    expect(markup, key).toContain(`aria-label="${label} Room default"`);
  }
});
