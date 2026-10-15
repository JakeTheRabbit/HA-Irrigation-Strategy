import { useState } from "react";
import {
  Check,
  Droplets,
  EyeOff,
  LoaderCircle,
  Moon,
  Sprout,
  Sun,
  Monitor,
  Telescope,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Heading, ReviewDialog, Status } from "@/components/dashboard";
import { UiTip } from "@/components/info-tip";
import { Pill, type PillTone } from "@/components/mini-visuals";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";
import { AllZonesSwitch, RoomPower } from "@/components/room-controls";
import { SizingUnitPickers, useSizingUnits } from "@/components/zone-sizing";
import { RunRecords } from "@/components/run-records";
import type { ThemePreference, ThemeSource } from "@/lib/ha-theme";
import { useWaterView, type WaterView } from "@/lib/water-view";
import "./settings.css";

/** The connection in the top bar's words, with the colour of its state. */
const CONNECTION: Record<Controller["connection"], { label: string; tone: PillTone }> = {
  live: { label: "Connected", tone: "on" },
  demo: { label: "Demo mode", tone: "warn" },
  connecting: { label: "Connection pending", tone: "warn" },
  offline: { label: "Offline", tone: "off" },
};

export function Settings({
  controller,
  theme,
  setTheme,
  themeSource,
  onDirtyChange,
}: {
  controller: Controller;
  theme: ThemePreference;
  setTheme: (value: ThemePreference) => void;
  themeSource: ThemeSource;
  /** A run record's form is open: leaving the page would lose it. */
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const water = useWaterView();
  const units = useSizingUnits();
  const [waterBusy, setWaterBusy] = useState(false);
  const [waterError, setWaterError] = useState("");
  async function chooseWater(view: WaterView) {
    setWaterBusy(true);
    setWaterError("");
    try {
      await water.setView(view);
    } catch (error) {
      setWaterError(errorText(error));
    } finally {
      setWaterBusy(false);
    }
  }
  const predictions = controller.room.notifyPredictions;
  const [predictBusy, setPredictBusy] = useState(false);
  const [predictError, setPredictError] = useState("");
  async function choosePredictions(include: boolean) {
    if (!predictions.entityId || predictions.enabled === include) return;
    setPredictBusy(true);
    setPredictError("");
    try {
      const result = await controller.write([{ entityId: predictions.entityId, value: include }]);
      if (result.failed.length) setPredictError(result.failed.map((f) => f.reason).join(" "));
    } catch (error) {
      setPredictError(errorText(error));
    } finally {
      setPredictBusy(false);
    }
  }
  const [base, setBase] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const [review, setReview] = useState(false);
  const [resetDemo, setResetDemo] = useState(false);
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
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading title="Settings" />
      <div className="settings-stack">
        <section className="panel settings-section">
          <div className="settings-label">
            <h2>Home Assistant connection</h2>
            <p>Use the current Home Assistant session or connect with a long-lived access token.</p>
            <Pill
              dot
              tone={CONNECTION[controller.connection].tone}
              data-connection={controller.connection}
            >
              {CONNECTION[controller.connection].label}
            </Pill>
          </div>
          <form onSubmit={connect} className="connection-form">
            <div>
              <span className="label-with-tip">
                <Label htmlFor="ha-url">Home Assistant URL</Label>
                <UiTip copyKey="home assistant url" />
              </span>
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
              <span className="label-with-tip">
                <Label htmlFor="ha-token">Long-lived access token</Label>
                <UiTip copyKey="long-lived access token" />
              </span>
              <Input
                id="ha-token"
                type="password"
                autoComplete="off"
                placeholder="Token for this tab"
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
        {controller.room.roomActiveEntity && (
          <section className="panel settings-section">
            <div className="settings-label">
              <h2>
                Room on or off <UiTip copyKey="room on / off" />
              </h2>
              <p>
                Switch {controller.room.room.name} off when nothing is growing in it, and on again
                when the next crop goes in.
              </p>
            </div>
            <div>
              <RoomPower controller={controller} />
              <p className="small muted mt-3">
                Off: the controller will not water this room and raises no alerts for it, and a shot
                already running stops within a few seconds. On within a day: it carries on where it
                was. On after longer: daily counters and learned phase state reset for a fresh run.
                This is not an emergency stop.
              </p>
            </div>
          </section>
        )}
        <section className="panel settings-section">
          <div className="settings-label">
            <h2>
              Watering <UiTip copyKey="watering" />
            </h2>
            <p>
              Lets the controller water {controller.room.room.name}. This is the room’s engine
              switch
              {controller.room.engine.entityId ? ` (${controller.room.engine.entityId})` : ""}.
            </p>
          </div>
          <div>
            <div className="split-row">
              <Status
                enabled={controller.room.engine.enabled}
                label={
                  controller.room.engine.enabled === true
                    ? "Watering on"
                    : controller.room.engine.enabled === false
                      ? "Watering off"
                      : undefined
                }
              />
              <Button
                variant="outline"
                disabled={
                  !controller.room.engine.entityId ||
                  controller.room.engine.enabled === null ||
                  !["live", "demo"].includes(controller.connection)
                }
                onClick={() => setReview(true)}
              >
                {controller.room.engine.enabled ? "Switch watering off…" : "Switch watering on…"}
              </Button>
            </div>
            <p className="small muted mt-3">
              Off: the controller opens no valve in this room, and a shot already running stops
              within a few seconds. It keeps reading the probes and following the phases. A new room
              starts with watering off, so nothing is watered before its hardware has been checked.
              This is not an emergency stop.
            </p>
            {controller.room.zones.length > 0 && (
              <div className="settings-zones">
                <h3>All zone switches</h3>
                <AllZonesSwitch controller={controller} />
                <p className="small muted">
                  Pause or switch on every zone of {controller.room.room.name} at once, through a
                  review. Each zone also has its own switch on its page.
                </p>
              </div>
            )}
          </div>
        </section>
        <section className="panel settings-section">
          <div className="settings-label">
            <h2>
              Run records <UiTip copyKey="run records" />
            </h2>
            <p>
              Each crop in {controller.room.room.name}, from its start date: what History › Compare
              runs lines up by grow week.
            </p>
          </div>
          <RunRecords controller={controller} onDirtyChange={onDirtyChange} />
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
          <div className="appearance-options">
            <div className="theme-options" aria-label="Theme">
              {[
                { value: "auto", label: "Home Assistant or system", icon: Monitor },
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
            <div>
              <div className="label-with-tip">
                <h3 id="water-view-label">Water today display</h3>
                <UiTip copyKey="water today, shown as" />
              </div>
              <div
                className="theme-options water-view-options"
                role="group"
                aria-labelledby="water-view-label"
              >
                {(
                  [
                    { value: "zone", label: "Zone total", icon: Droplets },
                    { value: "plant", label: "For each plant", icon: Sprout },
                  ] as const
                ).map((option) => (
                  <button
                    key={option.value}
                    className={water.view === option.value ? "chosen" : ""}
                    aria-pressed={water.view === option.value}
                    disabled={
                      !water.available ||
                      waterBusy ||
                      !["live", "demo"].includes(controller.connection)
                    }
                    onClick={() => void chooseWater(option.value)}
                  >
                    <option.icon size={20} />
                    <span>{option.label}</span>
                    {water.view === option.value && <Check size={16} />}
                  </button>
                ))}
              </div>
              {waterError && (
                <p className="small error-text" role="alert">
                  {waterError}
                </p>
              )}
              <p className="small muted mt-3">
                {water.available
                  ? `For ${controller.room.room.name}: everyone who opens a zone’s page sees water today this way, and the controller’s vitals notification follows it. `
                  : "This needs the updated Crop Steering integration. "}
                Per plant is each zone’s water today divided by its plant count from Equipment ›
                Setup, as if every plant got the same. Today compares the zones per plant either
                way; water use over the grow stays in litres per zone.
              </p>
            </div>
          </div>
        </section>
        <section className="panel settings-section">
          <div className="settings-label">
            <h2>Notifications</h2>
            <p>The controller&rsquo;s vitals report, for {controller.room.room.name}.</p>
          </div>
          <div>
            <div className="label-with-tip">
              <h3 id="predictions-label">Next action of each zone</h3>
              <UiTip copyKey="include what each zone does next" />
            </div>
            <div
              className="theme-options water-view-options"
              role="group"
              aria-labelledby="predictions-label"
            >
              {(
                [
                  { value: true, label: "Included", icon: Telescope },
                  { value: false, label: "Not included", icon: EyeOff },
                ] as const
              ).map((option) => (
                <button
                  key={option.label}
                  className={predictions.enabled === option.value ? "chosen" : ""}
                  aria-pressed={predictions.enabled === option.value}
                  disabled={
                    !predictions.entityId ||
                    predictions.enabled === null ||
                    predictBusy ||
                    !["live", "demo"].includes(controller.connection)
                  }
                  onClick={() => void choosePredictions(option.value)}
                >
                  <option.icon size={20} />
                  <span>{option.label}</span>
                  {predictions.enabled === option.value && <Check size={16} />}
                </button>
              ))}
            </div>
            {predictError && (
              <p className="small error-text" role="alert">
                {predictError}
              </p>
            )}
            <p className="small muted mt-3">
              {predictions.entityId
                ? "Under each zone, what the controller will do next, as the zone’s Next: line says it: for example “shot when VWC < 61% (now 58%) · P3 by 22:00”. Which phones get the report is ticked under Notifications (Vitals)."
                : "This needs the updated Crop Steering integration. Until then the controller includes them."}
            </p>
          </div>
        </section>
        <section className="panel settings-section">
          <div className="settings-label">
            <h2>Units</h2>
            <p>How pot volume and dripper flow are shown and typed in this browser.</p>
          </div>
          <SizingUnitPickers units={units} disabled={false} />
        </section>
        {controller.demo && (
          <section className="panel settings-section">
            <div className="settings-label">
              <h2>Sample workspace</h2>
              <p>
                Synthetic sensor readings, example plans and historical runs let you explore the
                interface.
              </p>
            </div>
            <div>
              <Button variant="outline" onClick={() => setResetDemo(true)}>
                Reset demo session…
              </Button>
              <p className="small muted mt-3">
                Restore the sample rooms and runs. Saved recipes stay in this browser.
              </p>
            </div>
          </section>
        )}
      </div>
      {controller.demo && (
        <Dialog open={resetDemo} onOpenChange={setResetDemo}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Reset demo session?</DialogTitle>
              <DialogDescription>
                Reload the example rooms, sensor readings, run records and planner drafts. Unsaved
                demo work and changes to demo runs or room settings will be lost. Saved recipe
                libraries and live connection data will be kept.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setResetDemo(false)}>
                Keep exploring
              </Button>
              <Button
                onClick={() => {
                  if (controller.demo) window.location.reload();
                }}
              >
                Reset demo session
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
      <ReviewDialog
        open={review}
        onOpenChange={setReview}
        controller={controller}
        title="Review the kill switch"
        items={
          controller.room.engine.entityId
            ? [
                {
                  change: {
                    entityId: controller.room.engine.entityId,
                    value: !controller.room.engine.enabled,
                  },
                  label: `${controller.room.room.name} watering`,
                  before: controller.room.engine.enabled ? "On" : "Off",
                  after: controller.room.engine.enabled ? "Off" : "On",
                },
              ]
            : []
        }
        note="Switching watering off also stops a running shot within a few seconds. It is not an emergency stop: use the installation's physical shut-off for that."
      />
    </>
  );
}
