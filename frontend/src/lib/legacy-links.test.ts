import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { resolveRequestedRoom } from "./model";
import type { Room } from "./types";
import { parseRoute, type Page } from "./routes";

/** The pages of the dashboards before this one (frontend/scripts/package.mjs). A bookmark or a Home
 * Assistant panel on an upgraded install still opens one, so each keeps working, unlisted: no menu,
 * doc or screenshot shows it, and none is removed. */
const LEGACY: Record<string, Page> = {
  "index.html": "today",
  "f2.html": "today",
  "f2-classic.html": "plan/schedule",
  "home.html": "today",
  "overview.html": "today",
  "setpoints.html": "plan/schedule",
  "crop_steering.html": "today",
  "crop_steering_tune.html": "plan/targets",
  "crop_steering_rules.html": "help",
  "office.html": "equipment/probes",
  "system-map.html": "equipment/probes",
  "irrigation-manual.html": "help",
  "install.html": "equipment/setup",
  "SYSTEM_GUIDE.html": "help",
};
const FOLDERS = ["www", "addons/f2_control/www/public"];

/** Where a shipped redirect page sends the browser for `search` and `hash`. */
function follow(folder: string, page: string, search = "", hash = ""): string {
  const html = readFileSync(new URL(`../../../${folder}/${page}`, import.meta.url), "utf8");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)![1];
  let target = "";
  new Function("location", script)({ search, hash, replace: (url: string) => (target = url) });
  return target;
}
/** The page the dashboard opens for that address. */
function opens(target: string): Page {
  const url = new URL(target, "http://box/local/");
  expect(url.pathname).toBe("/local/dashboard.html");
  return parseRoute(url.hash, url.search).route.page;
}

describe("the legacy dashboard links keep working", () => {
  it.each(FOLDERS.flatMap((folder) => Object.keys(LEGACY).map((page) => [folder, page])))(
    "%s/%s opens its page",
    (folder, page) => {
      expect(opens(follow(folder, page))).toBe(LEGACY[page]);
    },
  );
  it("keeps an old ?view= link's page and the rest of its query", () => {
    expect(opens(follow("www", "f2.html", "?view=tune"))).toBe("plan/targets");
    const target = follow("www", "f2.html", "?view=logs&demo=1");
    expect(opens(target)).toBe("history/explorer");
    expect(new URL(target, "http://box/").searchParams.get("demo")).toBe("1");
  });
  it("opens the classic page on the room it named", () => {
    const room = (search: string) =>
      new URL(follow("www", "f2-classic.html", search), "http://box/").searchParams.get("room");
    expect(room("")).toBe("room:");
    expect(room("?room=f1")).toBe("room:f1_");
    expect(room("?room=room:b_")).toBe("room:b_");
  });
  it("still maps the f1 and f2 room names", () => {
    const room = (prefix: string): Room => ({ id: `room:${prefix}`, prefix, name: prefix || "x" });
    const unprefixed = room(""),
      f1 = room("f1_"),
      f2 = room("f2_");
    expect(resolveRequestedRoom([unprefixed, f1], "f1")).toBe(f1);
    expect(resolveRequestedRoom([unprefixed, f1], "f2")).toBe(unprefixed);
    expect(resolveRequestedRoom([unprefixed, f1, f2], "f2")).toBe(f2);
    expect(resolveRequestedRoom([unprefixed, f1], "room:f1_")).toBe(f1);
  });
});
