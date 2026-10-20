import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";
function redirected(file: string, search = "", hash = "") {
  const html = readFileSync(new URL(`../../../www/${file}`, import.meta.url), "utf8");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
  if (!script) throw Error("Missing redirect script");
  let next = "";
  runInNewContext(script, {
    URLSearchParams,
    location: {
      search,
      hash,
      replace: (url: string) => {
        next = url;
      },
    },
  });
  return next;
}
describe("packaged landing entries", () => {
  it.each(["index.html", "home.html", "overview.html", "crop_steering.html"])(
    "%s leaves default preference resolution to the dashboard",
    (file) => {
      expect(redirected(file, "?demo=1")).toBe("./dashboard.html?demo=1");
      expect(redirected(file, "?demo=1&view=help")).toBe("./dashboard.html?demo=1#/help");
    },
  );
  it("preserves explicit hashes and legacy edit links", () => {
    expect(redirected("index.html", "?demo=1", "#/history/timeline?zone=2")).toBe(
      "./dashboard.html?demo=1#/history/timeline?zone=2",
    );
    expect(redirected("crop_steering_tune.html", "?demo=1")).toContain("#/strategy");
  });
});
