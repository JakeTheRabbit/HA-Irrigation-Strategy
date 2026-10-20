import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = fileURLToPath(new URL("..", import.meta.url));
const files = (dir: string, ext: string) =>
  readdirSync(`${src}${dir}`)
    .filter((file) => file.endsWith(ext))
    .map((file) => `${dir}/${file}`);
const sheets = [
  "styles.css",
  "workspace.css",
  ...files("components", ".css"),
  ...files("pages", ".css"),
];
const read = (file: string) => readFileSync(`${src}${file}`, "utf8");

describe("type scale", () => {
  it("sets no text smaller than 12px", () => {
    const small = sheets.flatMap((sheet) =>
      [...read(sheet).matchAll(/font(?:-size)?:[^;{}]*?(\d+(?:\.\d+)?)px/g)]
        .filter((match) => Number(match[1]) < 12)
        .map((match) => `${sheet}: ${match[0].replace(/\s+/g, " ")}`),
    );
    expect(small).toEqual([]);
  });

  it("sets no relative size that can fall below 12px", () => {
    // rem is the browser's 16px root; em follows its parent, so it needs an explicit floor.
    const risky = sheets.flatMap((sheet) =>
      [...read(sheet).matchAll(/font-size:\s*([^;{}]+)/g)]
        .map((match) => match[1].trim())
        .filter((value) => {
          const rem = /^(\d*\.?\d+)rem$/.exec(value);
          if (rem) return Number(rem[1]) < 0.75;
          return /\d(?:\.\d+)?em\b/.test(value) && !value.startsWith("max(");
        })
        .map((value) => `${sheet}: font-size: ${value}`),
    );
    expect(risky).toEqual([]);
  });

  it("draws no chart text smaller than 12px", () => {
    const small = [...files("components", ".tsx"), ...files("pages", ".tsx")].flatMap((file) =>
      [...read(file).matchAll(/fontSize=(?:"|\{)(\d+(?:\.\d+)?)/g)]
        .filter((match) => Number(match[1]) < 12)
        .map((match) => `${file}: ${match[0]}`),
    );
    expect(small).toEqual([]);
  });
});
