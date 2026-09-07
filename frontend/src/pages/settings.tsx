import { useState } from "react";
import { ArrowUpRight, Check, LoaderCircle, Moon, Sun, Monitor } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Heading, ReviewDialog, Status } from "@/components/dashboard";
import type { Controller } from "@/lib/types";
import type { ThemePreference, ThemeSource } from "@/lib/ha-theme";

export function workspaceLink(view: string): string {
  const routes: Record<string, string> = {
    timeline: "grow-plan",
    recipes: "grow-plan",
    tune: "strategy",
    climate: "sensors",
    floor: "setup",
    substrate: "insights",
  };
  return "#/" + (routes[view] || "help");
}
export function Settings({
  controller,
  theme,
  setTheme,
  themeSource,
}: {
  controller: Controller;
  theme: ThemePreference;
  setTheme: (value: ThemePreference) => void;
  themeSource: ThemeSource;
}) {
  const [base, setBase] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const [review, setReview] = useState(false);
  async function connect(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setConnected(false);
    try {
      await controller.connect(base.trim(), token.trim());
      setToken("");
      setConnected(true);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        title="Settings"
        description="Manage this tab’s connection, appearance and room scheduling."
      />
      <div className="settings-stack">
        <section className="panel settings-section">
          <div className="settings-label">
            <h2>Home Assistant connection</h2>
            <p>Use the current Home Assistant session or connect with a long-lived access token.</p>
            <Status
              enabled={controller.connection === "live" || controller.connection === "demo"}
              label={controller.connection === "demo" ? "Demo mode" : controller.connection}
            />
          </div>
          <form onSubmit={connect} className="connection-form">
            <div>
              <Label htmlFor="ha-url">Home Assistant URL</Label>
              <Input
                id="ha-url"
                type="url"
                placeholder="http://homeassistant.local:8123"
                value={base}
                onChange={(e) => setBase(e.target.value)}
              />
              <p className="small muted">
                Leave blank to use the current origin and available session.
              </p>
            </div>
            <div>
              <Label htmlFor="ha-token">Long-lived access token</Label>
              <Input
                id="ha-token"
                type="password"
                autoComplete="off"
                placeholder="Paste token for this tab"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
              <p className="small muted">
                Kept only for the current tab session. Never added to a URL.
              </p>
            </div>
            {controller.demo && (
              <p className="notice-inline">
                This tab is in isolated demo mode. Open a copy without the demo parameter to connect
                to a live controller.
              </p>
            )}
            {(error || controller.error) && (
              <p className="form-error" role="alert">
                {error || controller.error}
              </p>
            )}
            {connected && controller.connection === "live" && (
              <p className="success-text" role="status">
                <Check size={16} />
                Connection verified.
              </p>
            )}
            <div className="form-actions">
              <Button type="submit" disabled={busy || controller.demo}>
                {busy && <LoaderCircle size={16} className="spin" />}
                {busy ? "Connecting…" : "Connect"}
              </Button>
              {controller.connection === "live" && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    controller.disconnect();
                    setConnected(false);
                  }}
                >
                  Disconnect this tab
                </Button>
              )}
            </div>
          </form>
        </section>
        <section className="panel settings-section">
          <div className="settings-label">
            <h2>Room scheduling</h2>
            <p>Applies only to {controller.room.room.name}.</p>
          </div>
          <div>
            <div className="split-row">
              <Status enabled={controller.room.engine.enabled} />
              <Button
                variant="outline"
                disabled={
                  !controller.room.engine.entityId ||
                  controller.room.engine.enabled === null ||
                  !["live", "demo"].includes(controller.connection)
                }
                onClick={() => setReview(true)}
              >
                {controller.room.engine.enabled ? "Pause scheduling…" : "Enable scheduling…"}
              </Button>
            </div>
            <p className="small muted mt-3">
              Pausing may prevent future cycles. An active shot may continue; this control is not an
              emergency stop.
            </p>
          </div>
        </section>
        <section className="panel settings-section">
          <div className="settings-label">
            <h2>Appearance</h2>
            <p>
              {themeSource === "home-assistant"
                ? "Matching your Home Assistant theme, including live changes."
                : theme === "auto"
                  ? "Following your device appearance until embedded in Home Assistant."
                  : "Using your saved appearance override."}
            </p>
          </div>
          <div className="theme-options" aria-label="Appearance preference">
            {[
              { value: "auto", label: "Home Assistant / system", icon: Monitor },
              { value: "light", label: "Light", icon: Sun },
              { value: "dark", label: "Dark", icon: Moon },
            ].map((option) => (
              <button
                key={option.value}
                className={theme === option.value ? "chosen" : ""}
                aria-pressed={theme === option.value}
                onClick={() => setTheme(option.value as ThemePreference)}
              >
                <option.icon size={20} />
                <span>{option.label}</span>
                {theme === option.value && <Check size={16} />}
              </button>
            ))}
          </div>
        </section>
        <section className="panel settings-section">
          <div className="settings-label">
            <h2>Advanced workflows</h2>
            <p>Planning, diagnostics and room configuration share this workspace.</p>
          </div>
          <div className="tool-link-list">
            {!workspaceLink("tune") && (
              <p className="notice-inline">{"Open the matching workflow in this dashboard."}</p>
            )}
            <a href={workspaceLink("tune")} aria-disabled={!workspaceLink("tune")}>
              Manual setpoints <ArrowUpRight size={16} />
            </a>
            <a href={workspaceLink("climate")} aria-disabled={!workspaceLink("climate")}>
              Climate detail <ArrowUpRight size={16} />
            </a>
            <a href={workspaceLink("floor")} aria-disabled={!workspaceLink("floor")}>
              Room floor plan <ArrowUpRight size={16} />
            </a>
            <p className="small muted">
              Classic controls retain their existing behavior. Manual-shot events and phase
              overrides are not verified commands for this add-on.
            </p>
          </div>
        </section>
      </div>
      <ReviewDialog
        open={review}
        onOpenChange={setReview}
        controller={controller}
        title="Review room scheduling"
        items={
          controller.room.engine.entityId
            ? [
                {
                  change: {
                    entityId: controller.room.engine.entityId,
                    value: !controller.room.engine.enabled,
                  },
                  label: `${controller.room.room.name} scheduling`,
                  before: controller.room.engine.enabled ? "Enabled" : "Paused",
                  after: controller.room.engine.enabled ? "Paused" : "Enabled",
                },
              ]
            : []
        }
        note="An active irrigation shot may continue. Use the appropriate physical or controller safety procedure for an emergency."
      />
    </>
  );
}
