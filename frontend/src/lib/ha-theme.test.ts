import { describe, expect, it } from "vitest";
import { resolveTheme, themePreference } from "./ha-theme";

describe("Home Assistant theme resolution", () => {
  it("defaults to following Home Assistant and retains explicit saved choices", () => {
    expect(themePreference(null)).toBe("auto");
    expect(themePreference("dark")).toBe("dark");
    expect(themePreference("light")).toBe("light");
    expect(themePreference("invalid")).toBe("auto");
  });
  it("follows the system when no HA palette is available", () => {
    expect(resolveTheme("auto", true, {}).dark).toBe(true);
    expect(resolveTheme("auto", false, {}).dark).toBe(false);
    expect(resolveTheme("auto", true, {}).source).toBe("system");
  });
  it("matches the parent palette and infers dark mode from its canvas", () => {
    const result = resolveTheme("auto", false, {
      "--primary-background-color": "#111111",
      "--card-background-color": "#1c1c1c",
      "--primary-color": "#03a9f4",
      "--primary-text-color": "#e1e1e1",
    });
    expect(result.dark).toBe(true);
    expect(result.source).toBe("home-assistant");
    expect(result.variables["--ha-native-canvas"]).toBe("#111111");
    expect(result.variables["--ha-native-primary"]).toBe("#03a9f4");
  });
  it("explicit light or dark ignores inherited palette while preserving the preference", () => {
    const inherited = {
      "--primary-background-color": "rgb(17, 17, 17)",
      "--primary-color": "cyan",
    };
    expect(resolveTheme("light", true, inherited)).toEqual({
      dark: false,
      source: "override",
      variables: {},
    });
    expect(resolveTheme("dark", false, inherited)).toEqual({
      dark: true,
      source: "override",
      variables: {},
    });
  });
  it("does not treat unrelated embedded page CSS as a Home Assistant palette", () => {
    expect(resolveTheme("auto", false, { "--primary-color": "red" }).source).toBe("system");
  });
});
