import { describe, expect, it } from "vitest";
import { dayWord, errorText, trimNumber, unreadableState } from "./utils";
import { numeric, readable } from "./model";
import { FEATURES, valueOf } from "./features";

describe("errorText", () => {
  it("shows the REST response body from an inherited Home Assistant session", () => {
    const reason = "input_boolean.f2_control_enabled must read OFF before changing setup";
    expect(errorText({ message: "Response error: 500", body: { message: reason } })).toBe(reason);
    expect(
      errorText(
        Object.assign(new Error("Response error: 400"), {
          body: { message: reason },
        }),
      ),
    ).toBe(reason);
  });
  it("keeps the original error when the response body has no usable message", () => {
    for (const body of [null, "server failed", { message: "" }, { message: 500 }]) {
      expect(errorText({ message: "Response error: 500", body })).toBe("Response error: 500");
    }
  });
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

describe("dayWord", () => {
  const now = new Date(2026, 8, 28, 2, 10).getTime();
  it("says nothing for today and Yesterday for the day before, by the calendar", () => {
    expect(dayWord(new Date(2026, 8, 28, 0, 5).getTime(), now)).toBe("");
    expect(dayWord(new Date(2026, 8, 27, 22, 48).getTime(), now)).toBe("Yesterday");
    expect(dayWord(new Date(2026, 8, 27, 0, 0).getTime(), now)).toBe("Yesterday");
  });
  it("names an older day by its date", () => {
    const at = new Date(2026, 8, 25, 14, 0).getTime();
    expect(dayWord(at, now)).toBe(
      new Date(at).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }),
    );
  });
});

describe("unreadableState", () => {
  it("is the integration's one test: missing, blank, unknown, unavailable or none, any case", () => {
    for (const state of [undefined, null, "", "  ", "unknown", "unavailable", "none", "None", "UNAVAILABLE"])
      expect(unreadableState(state), String(state)).toBe(true);
    for (const state of ["0", "on", "off", "42.5", "Vegetative"])
      expect(unreadableState(state), state).toBe(false);
  });
  it("is what every page asks, so one entity is never live on one page and missing on another", () => {
    const none = { entity_id: "sensor.x", state: "none", attributes: {} };
    expect(readable(none)).toBe(false);
    expect(numeric(none)).toBeNull();
    const control = FEATURES.flatMap((f) => f.settings).find((c) => c.domain === "select")!;
    expect(valueOf(control, { ...none, entity_id: "select.x" })).toBeNull();
  });
});

describe("trimNumber", () => {
  it("keeps at most the digits asked for, without trailing zeros", () => {
    expect(trimNumber(1.5)).toBe("1.5");
    expect(trimNumber(2)).toBe("2");
    expect(trimNumber(3.14159, 3)).toBe("3.142");
  });
});
