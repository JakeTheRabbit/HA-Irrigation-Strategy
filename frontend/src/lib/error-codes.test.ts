import { describe, expect, it } from "vitest";
import { asCode, codeFromHash, errorCodeGroups, errorCodes, findErrorCodes } from "./error-codes";

describe("error codes", () => {
  it("lists each code once, in order, in exactly one group", () => {
    const codes = errorCodes.map((entry) => entry.code);
    expect(codes).toEqual([...codes].sort());
    expect(new Set(codes).size).toBe(codes.length);
    for (const code of codes) {
      expect(errorCodeGroups.filter((group) => code.startsWith(group.prefix))).toHaveLength(1);
    }
  });

  it("gives every code a cause and a fix", () => {
    for (const entry of errorCodes) {
      expect(entry.causes.length, entry.code).toBeGreaterThan(0);
      expect(entry.fixes.length, entry.code).toBeGreaterThan(0);
    }
  });

  it("finds a code however it is typed", () => {
    for (const typed of ["CS-101", "cs-101", "cs101", "101", " 101 "]) {
      expect(findErrorCodes(typed).map((entry) => entry.code)).toEqual(["CS-101"]);
    }
    expect(asCode("1010")).toBeNull();
    expect(findErrorCodes("999")).toEqual([]);
  });

  it("finds codes by the words in them", () => {
    const moisture = findErrorCodes("moisture reading").map((entry) => entry.code);
    expect(moisture).toContain("CS-101");
    expect(moisture).toContain("CS-103");
    expect(findErrorCodes("no plant").map((entry) => entry.code)).toContain("CS-101");
    expect(findErrorCodes("zzzz")).toEqual([]);
    expect(findErrorCodes("   ")).toHaveLength(errorCodes.length);
  });

  it("reads the code a link asks for", () => {
    expect(codeFromHash("#/help?code=CS-101")).toBe("CS-101");
    expect(codeFromHash("#/help?code=101")).toBe("CS-101");
    expect(codeFromHash("#/help")).toBeNull();
    expect(codeFromHash("#/help?code=nonsense")).toBeNull();
  });
});
