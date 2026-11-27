import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { AlertCodeText, codeTooltip } from "./alert-code-text";

describe("alert codes", () => {
  test("the hover text says what the code means and what it does to watering", () => {
    const text = codeTooltip("CS-301");
    expect(text).toMatch(/^CS-301 · Hardware fault latch/);
    expect(text).toContain("did not read back off");
    expect(text).toContain("Watering: No shot starts");
  });

  test("an unknown code still opens the list", () => {
    expect(codeTooltip("CS-999")).toContain("not in this version's code list");
  });

  test("each code in a message links to Help with its meaning on hover", () => {
    const html = renderToStaticMarkup(createElement(AlertCodeText, { text: "F1 · Zone 1: plan ends soon (CS-713)" }));
    expect(html).toContain('href="#/settings/help?code=CS-713"');
    expect(html).toContain("Room differs from grow plan");
  });
});
