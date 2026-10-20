import { useEffect, useState } from "react";
import robotoLicense from "@fontsource-variable/roboto/LICENSE?raw";

export type ThemePreference = "auto" | "light" | "dark";
export type ThemeSource = "home-assistant" | "system" | "override";
export interface ResolvedTheme {
  dark: boolean;
  source: ThemeSource;
  variables: Record<string, string>;
}
const mappings: Record<string, string[]> = {
  "--ha-native-canvas": ["--primary-background-color"],
  "--ha-native-surface": ["--ha-card-background", "--card-background-color"],
  "--ha-native-text": ["--primary-text-color"],
  "--ha-native-muted": ["--secondary-text-color"],
  "--ha-native-primary": ["--primary-color"],
  "--ha-native-border": ["--ha-card-border-color", "--divider-color"],
  "--ha-native-sidebar": ["--sidebar-background-color", "--card-background-color"],
  "--ha-native-sidebar-text": ["--sidebar-text-color", "--primary-text-color"],
  "--ha-native-sidebar-selected": ["--sidebar-selected-icon-color", "--primary-color"],
  "--ha-native-input": ["--input-fill-color", "--secondary-background-color"],
  "--ha-native-radius": ["--ha-card-border-radius"],
  "--ha-native-shadow": ["--ha-card-box-shadow"],
  "--ha-native-font": ["--ha-font-family-body", "--primary-font-family"],
  "--ha-native-success": ["--success-color"],
  "--ha-native-error": ["--error-color"],
};
const sourceVariables = [...new Set(Object.values(mappings).flat())];
export function themePreference(value: string | null): ThemePreference {
  return value === "light" || value === "dark" ? value : "auto";
}
function brightness(color: string): number | null {
  let rgb: number[] | undefined;
  const hex = color.trim().match(/^#([a-f\d]{3}|[a-f\d]{6})$/i)?.[1];
  if (hex) {
    const full =
      hex.length === 3
        ? hex
            .split("")
            .map((c) => c + c)
            .join("")
        : hex;
    rgb = [0, 2, 4].map((offset) => parseInt(full.slice(offset, offset + 2), 16));
  } else if (/^rgba?\(/.test(color.trim()))
    rgb = color
      .match(/[\d.]+/g)
      ?.slice(0, 3)
      .map(Number);
  return rgb?.length === 3 ? (rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114) / 255 : null;
}
export function resolveTheme(
  preference: ThemePreference,
  systemDark: boolean,
  inherited: Record<string, string>,
): ResolvedTheme {
  if (preference !== "auto")
    return { dark: preference === "dark", source: "override", variables: {} };
  if (!inherited["--primary-background-color"] || !inherited["--primary-color"])
    return { dark: systemDark, source: "system", variables: {} };
  const variables: Record<string, string> = {};
  for (const [target, candidates] of Object.entries(mappings)) {
    const value = candidates.map((name) => inherited[name]?.trim()).find(Boolean);
    if (value) variables[target] = value;
  }
  const canvasBrightness = brightness(inherited["--primary-background-color"]);
  const primaryBrightness = brightness(inherited["--primary-color"]);
  if (primaryBrightness !== null)
    variables["--ha-native-primary-foreground"] = primaryBrightness > 0.5 ? "#111111" : "#ffffff";
  return {
    dark: canvasBrightness === null ? systemDark : canvasBrightness < 0.5,
    source: "home-assistant",
    variables,
  };
}
function parentTheme(): { values: Record<string, string>; documents: Document[] } {
  const values: Record<string, string> = {};
  const documents: Document[] = [];
  let current: Window = window;
  for (let depth = 0; depth < 5; depth++) {
    try {
      if (current.parent === current) break;
      const parent = current.parent;
      const doc = parent.document;
      documents.push(doc);
      const source =
        current.frameElement || doc.querySelector("home-assistant") || doc.documentElement;
      const styles = parent.getComputedStyle(source);
      for (const name of sourceVariables)
        if (!values[name]) values[name] = styles.getPropertyValue(name).trim();
      // Reuse already-loaded native fonts without a CDN or additional font requests.
      doc.fonts?.forEach((font) => {
        if (font.status === "loaded" && /roboto/i.test(font.family) && !document.fonts.has(font))
          document.fonts.add(font);
      });
      current = parent;
    } catch {
      break;
    } // Cross-origin frames deliberately fall back to the system palette.
  }
  return { values, documents };
}
export function useHaTheme() {
  const [preference, setPreferenceState] = useState<ThemePreference>(() => {
    try {
      return themePreference(localStorage.getItem("irrigation-theme"));
    } catch {
      return "auto";
    }
  });
  const [resolved, setResolved] = useState<ResolvedTheme>({
    dark: false,
    source: "system",
    variables: {},
  });
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const root = document.documentElement;
    if (!document.querySelector("script[data-font-license=Roboto]")) {
      const license = document.createElement("script");
      license.type = "text/plain";
      license.dataset.fontLicense = "Roboto";
      license.textContent = robotoLicense;
      document.head.append(license);
    }
    let last = "";
    const sync = () => {
      const next = resolveTheme(
        preference,
        media.matches,
        preference === "auto" ? parentTheme().values : {},
      );
      const signature = JSON.stringify(next);
      if (signature === last) return;
      last = signature;
      for (const name of [...Object.keys(mappings), "--ha-native-primary-foreground"])
        root.style.removeProperty(name);
      for (const [name, value] of Object.entries(next.variables))
        root.style.setProperty(name, value);
      root.classList.toggle("dark", next.dark);
      root.dataset.themeSource = next.source;
      root.dataset.themePreference = preference;
      setResolved(next);
    };
    sync();
    media.addEventListener("change", sync);
    const observers =
      preference === "auto"
        ? parentTheme().documents.map((doc) => {
            const observer = new MutationObserver(sync);
            observer.observe(doc.documentElement, {
              attributes: true,
              attributeFilter: ["style", "class"],
              subtree: true,
            });
            return observer;
          })
        : [];
    // Theme styles inside HA shadow roots may not emit ancestor attribute mutations.
    const interval = preference === "auto" ? window.setInterval(sync, 1000) : undefined;
    return () => {
      media.removeEventListener("change", sync);
      observers.forEach((observer) => observer.disconnect());
      if (interval) clearInterval(interval);
    };
  }, [preference]);
  const setPreference = (value: ThemePreference) => {
    setPreferenceState(value);
    try {
      localStorage.setItem("irrigation-theme", value);
    } catch {
      /* Selection still applies in this tab. */
    }
  };
  return { preference, setPreference, dark: resolved.dark, source: resolved.source };
}
