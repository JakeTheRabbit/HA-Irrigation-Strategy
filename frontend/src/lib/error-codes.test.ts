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

  it("finds the code in a line pasted from a notification or a Repairs card", () => {
    // Word search found other entries here: CS-207's text mentions CS-606, CS-103's CS-102.
    for (const [pasted, code] of [
      ["(CS-606)", "CS-606"],
      ["CS-102.", "CS-102"],
      ["Code CS-101. What it means and what to do", "CS-101"],
      ["Zone 2: moisture reading hasn't changed (CS-101)", "CS-101"],
      ["Crop Steering: grow strategy plan is holding irrigation (CS-606)", "CS-606"],
      // A body names another code on the way; it ends with its own.
      ["It latches a hardware hold (CS-301) … Code CS-302. What it means and what to do", "CS-302"],
    ]) {
      expect(findErrorCodes(pasted).map((entry) => entry.code)).toEqual([code]);
    }
    expect(asCode("cs1010")).toBeNull();
  });

  it("finds a Repairs card by the words on the card", () => {
    const codes = findErrorCodes("grow strategy plan").map((entry) => entry.code);
    expect(codes).toContain("CS-606");
    expect(codes).toContain("CS-607");
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
