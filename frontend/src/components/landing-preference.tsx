import { useState } from "react";
import { LANDING_VIEWS, landingView, readLandingView, saveLandingView } from "@/lib/landing-view";
export function LandingPreference() {
  const [value, setValue] = useState(readLandingView);
  const [error, setError] = useState("");
  return (
    <section className="panel settings-section" aria-labelledby="landing-title">
      <div className="settings-label">
        <h2 id="landing-title">Default view</h2>
        <p>
          Choose what opens when you enter Crop Steering. Direct page links still open their
          requested view.
        </p>
      </div>
      <div className="settings-controls">
        <label htmlFor="landing-view">Landing page</label>
        <select
          id="landing-view"
          value={value}
          onChange={(event) => {
            const next = landingView(event.target.value);
            if (saveLandingView(next)) {
              setValue(next);
              setError("");
            } else setError("This browser blocked storage. The default remains All zones.");
          }}
        >
          {LANDING_VIEWS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <p className="muted">
          Saved in this browser only. This does not change irrigation or room settings.
        </p>
        {error && <p role="alert">{error}</p>}
      </div>
    </section>
  );
}
