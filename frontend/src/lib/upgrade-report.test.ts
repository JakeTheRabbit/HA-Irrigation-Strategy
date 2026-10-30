import { describe, expect, it } from "vitest";
import { callV2 } from "./parity-api";
import { demoController } from "./test-helpers";
import { docHref, pageHref, reportView } from "./upgrade-report";

const row = (id: string, status: "carried" | "needs_you", extra: Record<string, unknown> = {}) => ({
  id,
  title: `Title ${id}`,
  status,
  detail: `Detail ${id}`,
  page: "#/equipment/setup",
  doc: `docs/UPGRADING.md#${id}`,
  ...extra,
});

describe("the Upgrade report (migration_report)", () => {
  it("reads both lists, carried across and needs you", () => {
    const view = reportView({
      schema_version: 1,
      release: "3.18.0",
      room_id: "room:f2_",
      acknowledged: null,
      carried: [row("presets.recipe", "carried")],
      needs_you: [row("supply", "needs_you"), row("units", "needs_you")],
    });
    expect(view).not.toBeNull();
    expect(view!.release).toBe("3.18.0");
    expect(view!.carried.map((r) => r.id)).toEqual(["presets.recipe"]);
    expect(view!.needsYou.map((r) => r.id)).toEqual(["supply", "units"]);
    expect(view!.acknowledged).toBeNull();
  });
  it("is hidden for a fresh room: two empty lists", () => {
    expect(reportView({ schema_version: 1, release: "3.18.0", carried: [], needs_you: [] })).toBeNull();
    expect(reportView(null)).toBeNull();
    expect(reportView("garbled")).toBeNull();
  });
  it("drops a row it cannot show, and never invents a link", () => {
    const view = reportView({
      release: "3.18.0",
      carried: [{ id: "x" }, row("ok", "carried", { page: "javascript:alert(1)", doc: "https://evil.example/" })],
      needs_you: [],
    });
    expect(view!.carried).toHaveLength(1);
    expect(view!.carried[0].page).toBeNull();
    expect(view!.carried[0].doc).toBeNull();
  });
  it("links a page by its hash and a section of the upgrade guide on GitHub", () => {
    expect(pageHref("#/equipment/setup")).toBe("#/equipment/setup");
    expect(pageHref("/equipment/setup")).toBeNull();
    expect(docHref("docs/UPGRADING.md#supply")).toBe(
      "https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/UPGRADING.md#supply",
    );
    expect(docHref("../secrets#x")).toBeNull();
  });
  it("is answered by the demo for each room, with something that needs you", async () => {
    const outcome = await callV2<unknown>(demoController("?demo=1"), "migration_report", { room_id: "room:" });
    expect(outcome.kind).toBe("ok");
    const view = outcome.kind === "ok" ? reportView(outcome.data) : null;
    expect(view?.needsYou.length).toBeGreaterThan(0);
    expect(view?.carried.length).toBeGreaterThan(0);
  });
});
