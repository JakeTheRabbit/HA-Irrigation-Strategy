import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = fileURLToPath(new URL("..", import.meta.url));
const sheets = [
  "styles.css",
  "workspace.css",
  ...readdirSync(`${src}components`)
    .filter((file) => file.endsWith(".css"))
    .map((file) => `components/${file}`),
  ...readdirSync(`${src}pages`)
    .filter((file) => file.endsWith(".css"))
    .map((file) => `pages/${file}`),
];

describe("type scale", () => {
  it("sets no text smaller than 12px", () => {
    const small = sheets.flatMap((sheet) =>
      [
        ...readFileSync(`${src}${sheet}`, "utf8").matchAll(
          /font(?:-size)?:[^;{}]*?(\d+(?:\.\d+)?)px/g,
        ),
      ]
        .filter((match) => Number(match[1]) < 12)
        .map((match) => `${sheet}: ${match[0].replace(/\s+/g, " ")}`),
    );
    expect(small).toEqual([]);
  });
});
