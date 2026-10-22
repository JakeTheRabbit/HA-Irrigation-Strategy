/**
 * Where the verify-* scripts write the screenshots that double as README images.
 * Default: untracked output/playwright/readme/, so a test run leaves the tree clean.
 * UPDATE_README_IMAGES=1 writes straight into the tracked img/ folder.
 * (capture-readme.mjs is the canonical way to refresh img/ and is unaffected.)
 */
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const update = process.env.UPDATE_README_IMAGES === "1";
const dir = fileURLToPath(
  new URL(update ? "../../img/" : "../../output/playwright/readme/", import.meta.url),
);
mkdirSync(dir, { recursive: true });

export const readmeImage = (name) => dir + name;
