import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { Probes } from "@/pages/probes";
import { demoController } from "./test-helpers";

/** A static render is the page before calibration_get answers: its effects never run. */
const render = (search: string, states: Record<string, string> = {}) => {
  const controller = demoController(search);
  const next = { ...controller.states };
  for (const [id, state] of Object.entries(states)) next[id] = { ...next[id], state };
  return renderToStaticMarkup(
    createElement(Probes, { controller: { ...controller, states: next }, navigate: () => {} }),
  );
};

describe("Equipment › Probes & offsets", () => {
  test.each(["?demo=1", "?demo=1&backend=3.17"])(
    "offers no Match handheld and no missing note until the stored offsets are read (%s)",
    (search) => {
      const html = render(search);
      expect(html).toContain("data-probe=");
      expect(html).not.toContain("data-match-handheld=");
      expect(html).not.toContain("data-match-handheld-missing");
    },
  );

  test("says what a misplaced probe reads and what to do, without guessing why", () => {
    const html = render("?demo=1", { "sensor.demo_z1_back_vwc": "130" });
    const warning = /data-placement-warning="sensor\.demo_z1_back_vwc"[^>]*>(.*?)<\/p>/.exec(html)?.[1] ?? "";
    expect(warning).toContain("reads 130.0%");
    expect(warning).toContain("outside what a probe can read");
    expect(warning).not.toMatch(/likely|probably|seated|drip/);
  });
});
