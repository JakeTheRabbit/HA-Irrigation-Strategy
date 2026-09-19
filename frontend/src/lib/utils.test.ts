import { describe, expect, it } from "vitest";
import { errorText } from "./utils";

describe("errorText", () => {
  it("uses the message of real errors", () => {
    expect(errorText(new Error("Plan revision changed"))).toBe("Plan revision changed");
    expect(errorText(new TypeError("bad input"))).toBe("bad input");
  });
  it("names missing errors instead of printing null or undefined", () => {
    expect(errorText(null)).toBe("Unknown error");
    expect(errorText(undefined)).toBe("Unknown error");
  });
  it("passes strings through unchanged", () => {
    expect(errorText("Service not found")).toBe("Service not found");
    expect(errorText("")).toBe("");
  });
  it("reads Home Assistant style error objects instead of printing [object Object]", () => {
    expect(errorText({ code: "home_assistant_error", message: "Validation failed" })).toBe(
      "Validation failed",
    );
    expect(errorText({ detail: "Not an administrator" })).toBe("Not an administrator");
    expect(errorText({ error: "Timed out" })).toBe("Timed out");
  });
  it("takes the first non-empty string in message, detail, error order", () => {
    expect(errorText({ message: "", detail: "Use detail", error: "Not this" })).toBe("Use detail");
    expect(errorText({ message: 42, detail: null, error: "Use error" })).toBe("Use error");
    expect(errorText({ message: "First", detail: "Second" })).toBe("First");
  });
  it("serialises objects without a usable text field", () => {
    expect(errorText({ code: 7 })).toBe('{"code":7}');
    expect(errorText({ message: "" })).toBe('{"message":""}');
    expect(errorText([1, 2])).toBe("[1,2]");
  });
  it("falls back when an object cannot be serialised", () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(errorText(circular)).toBe("Request failed");
  });
  it("stringifies every other value", () => {
    expect(errorText(404)).toBe("404");
    expect(errorText(false)).toBe("false");
  });
});
