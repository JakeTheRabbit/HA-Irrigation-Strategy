import { useEffect, useRef, useState } from "react";

type HaHost = HTMLElement & { hass?: { kioskMode?: boolean } };

/** HA's temporary kiosk event and ingress messaging, also used by Music Assistant.
 * No persisted sidebar preference or parent styles are changed.
 */
export function connectHaShell(win: Window, onAvailable: (available: boolean) => void) {
  let cleanup = () => {};
  let toggle = () => {};
  try {
    const parent = win.parent;
    if (parent === win || parent.location.origin !== win.location.origin)
      return { cleanup, toggle };
    const host = parent.document.querySelector<HaHost>("home-assistant");
    if (!host) return { cleanup, toggle };
    const panelHost = (win.frameElement?.getRootNode() as ShadowRoot | undefined)?.host;
    const ingress =
      panelHost?.tagName === "HA-PANEL-APP" || panelHost?.tagName === "HASSIO-INGRESS";
    const initialPath = parent.location.pathname;
    let enabledHere = false,
      disposed = false;
    const event = (type: string, detail?: unknown) =>
      new CustomEvent(type, { detail, bubbles: true, composed: true });
    if (ingress) {
      parent.postMessage(
        { type: "home-assistant/subscribe-properties", kioskMode: true },
        win.location.origin,
      );
      onAvailable(true);
      toggle = () =>
        parent.postMessage({ type: "home-assistant/toggle-menu" }, win.location.origin);
    } else if (typeof host.hass?.kioskMode === "boolean") {
      // The built-in iframe panel has no ingress message handler. Use the same
      // temporary HA event directly for this trusted, same-origin embedding.
      enabledHere = !host.hass.kioskMode;
      if (enabledHere) parent.dispatchEvent(event("hass-kiosk-mode", { enable: true }));
      const main = host.shadowRoot?.querySelector("home-assistant-main");
      if (!main) {
        if (enabledHere) parent.dispatchEvent(event("hass-kiosk-mode", { enable: false }));
        return { cleanup, toggle };
      }
      toggle = () => main.dispatchEvent(event("hass-toggle-menu"));
      onAvailable(true);
    } else return { cleanup, toggle };
    const routeChanged = () => {
      if (parent.location.pathname !== initialPath) cleanup();
    };
    cleanup = () => {
      if (disposed) return;
      disposed = true;
      if (ingress)
        parent.postMessage({ type: "home-assistant/unsubscribe-properties" }, win.location.origin);
      else if (enabledHere) parent.dispatchEvent(event("hass-kiosk-mode", { enable: false }));
      parent.removeEventListener("location-changed", routeChanged);
      parent.removeEventListener("popstate", routeChanged);
      win.removeEventListener("pagehide", cleanup);
      onAvailable(false);
    };
    parent.addEventListener("location-changed", routeChanged);
    parent.addEventListener("popstate", routeChanged);
    win.addEventListener("pagehide", cleanup);
  } catch {
    /* Standalone and cross-origin embeds retain normal host navigation. */
  }
  return { cleanup, toggle: () => toggle() };
}

export function useHaShell() {
  const [available, setAvailable] = useState(false);
  const toggle = useRef(() => {});
  useEffect(() => {
    const bridge = connectHaShell(window, setAvailable);
    toggle.current = bridge.toggle;
    return bridge.cleanup;
  }, []);
  return { available, toggle: () => toggle.current() };
}
