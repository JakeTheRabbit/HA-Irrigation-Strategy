// The Crop Steering dashboard as a Home Assistant panel (setup_panel.py). Home Assistant draws its
// own title bar above an iframe panel and none above a custom panel, so this element holds the
// dashboard in a frame the size of the panel. The dashboard finds Home Assistant through its frame as
// it always has (frontend/src/lib/ha-shell.ts): it hides Home Assistant's sidebar while it is open,
// and its own Home Assistant button opens it.
class CropSteeringPanel extends HTMLElement {
  set panel(panel) {
    this._url = panel && panel.config ? panel.config.url : undefined;
    this._render();
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    if (!this.isConnected || !this._url || this._frame) return;
    this.style.display = "block";
    const frame = document.createElement("iframe");
    frame.title = "Crop Steering";
    frame.src = this._url;
    frame.setAttribute("allow", "fullscreen");
    Object.assign(frame.style, {
      display: "block",
      width: "100%",
      border: "0",
      backgroundColor: "var(--primary-background-color)",
    });
    // The panel's height, less the safe-area padding Home Assistant puts around a custom panel.
    const inset = "var(--safe-area-inset-top, 0px) - var(--safe-area-inset-bottom, 0px)";
    frame.style.height = `calc(100vh - ${inset})`;
    frame.style.height = `calc(100dvh - ${inset})`;
    this.append(frame);
    this._frame = frame;
  }
}

if (!customElements.get("crop-steering-panel"))
  customElements.define("crop-steering-panel", CropSteeringPanel);
