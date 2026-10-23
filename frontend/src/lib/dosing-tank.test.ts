import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { Dosing } from "@/pages/dosing";
import { demoController } from "./test-helpers";

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
