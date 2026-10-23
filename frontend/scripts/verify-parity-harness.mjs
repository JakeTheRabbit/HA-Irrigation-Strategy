/** Proves the parity harness itself: runs it against the all-rooms page and checks it writes the
 * compare files. Run after `vite build`. */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runParity } from "./parity-harness.mjs";

await runParity({
  id: "harness",
  route: "/all-zones",
  mockup: "02-S1-AllRooms.png",
  phoneMockup: "24-P1-AllRooms.png",
  check: async (p, c) => {
    // Desktop shows the menu tree; the phone shows the bottom bar (the tree sits in a drawer).
    await p.getByRole("navigation", { name: c.width > 720 ? "Main navigation" : "Sections" }).waitFor();
    c.region("main navigation");
  },
});

const json = JSON.parse(
  await readFile(new URL("../../output/playwright/parity/harness-compare.json", import.meta.url)),
);
assert.equal(json.id, "harness");
assert.deepEqual(json.regions, ["main navigation"]);
assert.equal(json.shots.length, 4);
console.log("PASS: parity harness (2 viewports x 2 backends, axe, overflow, compare page)");
