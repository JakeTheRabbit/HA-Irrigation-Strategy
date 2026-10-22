import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { Dosing } from "@/pages/dosing";
import { demoController } from "./test-helpers";

describe("Equipment › Feed & dosing owns the tank", () => {
  test("shows the tank and pump card, the tank minimum and the level chart", () => {
    const html = renderToStaticMarkup(
      createElement(Dosing, {
        controller: demoController("?demo=1"),
        navigate: () => {},
        onDirtyChange: () => {},
      }),
    );
    expect(html).toContain("data-tank-status");
    expect(html).toContain("Tank and pump");
    expect(html).toContain('data-reservoir-guard="');
    expect(html).toContain("Tank minimum");
    expect(html).toContain("data-tank-level-chart");
  });
});
