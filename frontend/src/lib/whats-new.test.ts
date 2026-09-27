import { describe, expect, it } from "vitest";
import {
  compareVersions,
  MOST,
  readWhatsNew,
  recent,
  releaseUrl,
  unseen,
  type WhatsNewDocument,
} from "./whats-new";

const release = (version: string, date: string) => ({ version, date, items: [`${version} line.`] });
const RELEASES = [
  release("2.30.0", "2026-12-20"),
  release("2.29.0", "2026-12-01"),
  release("2.28.1", "2026-11-28"),
  release("2.28.0", "2026-11-25"),
  release("2.27.0", "2026-11-10"),
  release("2.26.0", "2026-10-30"),
  release("2.25.0", "2026-10-02"),
];
const doc = (seen: string | null, version = "2.30.0"): WhatsNewDocument =>
  readWhatsNew({ version, seen, releases: RELEASES })!;
const shown = (selection: { releases: { version: string }[] }) =>
  selection.releases.map((item) => item.version);

describe("versions", () => {
  it("compare by number, not by text", () => {
    expect(compareVersions("2.10.0", "2.9.0")).toBeGreaterThan(0);
    expect(compareVersions("2.9.9", "2.10.0")).toBeLessThan(0);
    expect(compareVersions("2.24.0", "2.24.0")).toBe(0);
  });
});

describe("what the window shows after an update", () => {
  it("every release since the last one it showed, newest first", () => {
    expect(shown(unseen(doc("2.28.0")))).toEqual(["2.30.0", "2.29.0", "2.28.1"]);
  });
  it("nothing once it has shown the installed release, or on a new installation", () => {
    expect(unseen(doc("2.30.0"))).toEqual({ releases: [], more: 0 });
  });
  it("five at most, and how many more there were", () => {
    expect(unseen(doc("2.20.0"))).toEqual({
      releases: RELEASES.slice(0, MOST),
      more: RELEASES.length - MOST,
    });
  });
  it("the last 30 days where it cannot know what it showed", () => {
    // 20 Dec back to 20 Nov: not 2.27.0 of 10 Nov, although nobody here has seen it either.
    expect(shown(unseen(doc(null)))).toEqual(["2.30.0", "2.29.0", "2.28.1", "2.28.0"]);
  });
  it("nothing newer than what is installed", () => {
    expect(shown(unseen(doc("2.26.0", "2.28.0")))).toEqual(["2.28.0", "2.27.0"]);
  });
});

describe("the integration's answer", () => {
  it("is nothing from an integration without it, or one that answers nonsense", () => {
    expect(readWhatsNew(undefined)).toBeNull();
    expect(readWhatsNew({ message: "Fixture has no workspace API" })).toBeNull();
    expect(readWhatsNew({ version: "latest", seen: null, releases: [] })).toBeNull();
  });
  it("keeps only whole releases, and a seen version only when it is one", () => {
    const read = readWhatsNew({
      version: "2.30.0",
      seen: "yesterday",
      releases: [
        release("2.30.0", "2026-12-20"),
        { version: "2.29.0", date: "soon", items: ["No date."] },
        { version: "2.28.0", date: "2026-11-25", items: [] },
        { version: "2.27.0", date: "2026-11-10", items: [42] },
        null,
      ],
    });
    expect(read?.seen).toBeNull();
    expect(shown(read!)).toEqual(["2.30.0"]);
  });
});

describe("Help & tools", () => {
  it("shows the latest releases, whatever the window has shown", () => {
    expect(shown(recent(doc("2.30.0")))).toEqual(RELEASES.slice(0, MOST).map((r) => r.version));
  });
  it("links each release to its notes", () => {
    expect(releaseUrl("2.24.0")).toBe(
      "https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/releases/tag/v2.24.0",
    );
  });
});
