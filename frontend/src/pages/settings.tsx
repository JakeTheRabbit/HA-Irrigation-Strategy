import { useState } from "react";
import { Check, Droplets, LoaderCircle, Moon, Sprout, Sun, Monitor } from "lucide-react";
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
import { Heading } from "@/components/dashboard";
import { UiTip } from "@/components/info-tip";
import { Pill, type PillTone } from "@/components/mini-visuals";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";
import { SizingUnitPickers, useSizingUnits } from "@/components/zone-sizing";
import { DisplaySettings, UnitSettings } from "@/components/display-settings";
import { NeedsIntegration } from "@/components/needs-integration";
import { LANDING_VIEWS, landingView, readLandingView, saveLandingView } from "@/lib/landing-view";
import { callV2, useParity } from "@/lib/parity-api";
import type { DashboardList } from "@/lib/parity-types";
import { clock, dayLabel } from "@/lib/time";
import { useKeepAwake, wakeLockSupported } from "@/lib/wake-lock";
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
}: {
  controller: Controller;
  theme: ThemePreference;
  setTheme: (value: ThemePreference) => void;
  themeSource: ThemeSource;
  /** A run record's form is open: leaving the page would lose it. */
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const wakeSupported = wakeLockSupported(typeof navigator === "undefined" ? undefined : navigator);
  const [awake, setAwake] = useKeepAwake();
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
  const [base, setBase] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
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
      <Heading title="Dashboards & display" />
      <div className="display-top">
        <section className="panel display-units" aria-labelledby="units-title">
          <UnitSettings controller={controller} />
        </section>
        <WhereAppOpens timeZone={controller.timeZone} />
      </div>
      <WallDashboards controller={controller} />
      {wakeSupported && (
        <label className="keep-awake">
          <input type="checkbox" checked={awake} onChange={(e) => setAwake(e.target.checked)} />
          Keep this screen on while open
        </label>
      )}
      <details className="more-display">
        <summary>More display options</summary>
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
          <section className="panel settings-section" id="display">
            <div className="settings-label">
              <h2>Display</h2>
              <p>
                Extra panels for {controller.room.room.name}. Each one is off until you set it to on.
                Everyone who opens this room sees the same choice.
              </p>
            </div>
            <div>
              <DisplaySettings controller={controller} />
            </div>
          </section>

          <section className="panel settings-section">
            <div className="settings-label">
              <h2>Pot and dripper units</h2>
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
      </details>
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
    </>
  );
}

/** Where the app opens in this browser (the landing preference), read back after each save. */
function WhereAppOpens({ timeZone }: { timeZone: string }) {
  const [value, setValue] = useState(readLandingView);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <section className="panel where-opens" aria-labelledby="opens-title">
      <h2 id="opens-title">Where the app opens</h2>
      <label htmlFor="landing-view">On this browser</label>
      <select
        id="landing-view"
        value={value}
        onChange={(event) => {
          const next = landingView(event.target.value);
          if (saveLandingView(next) && readLandingView() === next) {
            setValue(next);
            setNote({ ok: true, text: `Saved and read back ${clock(Date.now(), timeZone)}` });
          } else
            setNote({
              ok: false,
              text: "This browser blocked storage. The app opens on Status · all rooms.",
            });
        }}
      >
        {LANDING_VIEWS.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
      {note && (
        <p className={note.ok ? "success-text" : "error-text"} role={note.ok ? "status" : "alert"}>
          {note.text}
        </p>
      )}
      <p className="small muted where-opens-foot">
        A link to a page still opens that page. A wall screen or tablet opens its own dashboard
        instead. Make one below.
      </p>
    </section>
  );
}

type WallDashboard = DashboardList["dashboards"][number];
type WallTemplate = DashboardList["templates"][number];

/** Wall and tablet dashboards: one card per template the integration offers (dashboard_list), each
 * writing a Home Assistant dashboard for the chosen rooms (dashboard_create). */
function WallDashboards({ controller }: { controller: Controller }) {
  const list = useParity<DashboardList>(controller, "dashboard_list", {}, []);
  return (
    <section className="wall-dashboards" aria-labelledby="wall-title" data-wall-dashboards>
      <div className="wall-head">
        <h2 id="wall-title">Wall and tablet dashboards</h2>
        <p>
          Each button writes a normal Home Assistant dashboard from our card pack. Change it later
          in Home Assistant’s own editor.
        </p>
      </div>
      {list.state === "missing" ? (
        <NeedsIntegration feature="Wall and tablet dashboards" />
      ) : list.state === "error" ? (
        <p className="error-text" role="alert">
          {list.error}
        </p>
      ) : !list.data ? (
        <p className="small muted">Reading the dashboards…</p>
      ) : (
        <div className="wall-cards">
          {list.data.templates.map((template) => (
            <DashboardCard
              // A room switch starts the card again on the room now selected.
              key={`${template.id}:${controller.roomId}`}
              controller={controller}
              template={template}
              dashboards={list.data!.dashboards}
              onCreated={list.reload}
            />
          ))}
        </div>
      )}
    </section>
  );
}

/** A small drawing of what the template shows; the words say it too. */
function TemplateSketch({ id, rooms, zones }: { id: string; rooms: number; zones: number }) {
  const slabs = (n: number) =>
    Array.from({ length: n }, (_, i) => <span key={i} className="sketch-slab" />);
  return (
    <div className={`wall-sketch sketch-${id}`} aria-hidden="true">
      {id === "facility_wall" &&
        Array.from({ length: Math.max(1, rooms) }, (_, i) => (
          <span key={i} className="sketch-room">
            {slabs(3)}
          </span>
        ))}
      {id === "room_tablet" &&
        Array.from({ length: Math.min(4, Math.max(1, zones)) }, (_, i) => (
          <span key={i} className="sketch-gauge" />
        ))}
      {id === "dosing_station" && (
        <>
          <span className="sketch-tank" />
          {slabs(4)}
        </>
      )}
    </div>
  );
}

function DashboardCard({
  controller,
  template,
  dashboards,
  onCreated,
}: {
  controller: Controller;
  template: WallTemplate;
  dashboards: WallDashboard[];
  onCreated: () => void;
}) {
  // A room tablet shows one room; the others any number of rooms.
  const single = template.id === "room_tablet";
  const [rooms, setRooms] = useState<string[]>([controller.roomId]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  /** The dashboard whose cards Home Assistant did not confirm: listed, but not shown as done. */
  const [unconfirmed, setUnconfirmed] = useState("");
  const latest = dashboards
    .filter((d) => d.template === template.id && d.exists)
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
  const admin = controller.admin !== false;
  const toggle = (id: string) =>
    setRooms((now) =>
      single
        ? [id]
        : now.includes(id)
          ? now.length > 1
            ? now.filter((r) => r !== id)
            : now
          : [...now, id],
    );
  async function create() {
    setBusy(true);
    setProblem("");
    setUnconfirmed("");
    const done = await callV2<{ url_path: string; title: string }>(controller, "dashboard_create", {
      template: template.id,
      rooms,
    });
    setBusy(false);
    if (done.kind === "missing") return setProblem("Needs integration 3.18.");
    if (done.kind === "error") return setProblem(done.message);
    // A verified create read its cards back; the list then shows it as created.
    if (done.readback.status !== "verified") {
      setUnconfirmed(done.data.url_path);
      setProblem(
        `Home Assistant did not confirm the cards of /${done.data.url_path}. Open it to check.`,
      );
    }
    onCreated();
  }
  const created = latest ? Date.parse(latest.created_at) : NaN;
  const confirmed = latest?.url_path !== unconfirmed;
  return (
    <article className="panel wall-card" data-template={template.id}>
      <TemplateSketch id={template.id} rooms={rooms.length} zones={controller.room.zones.length} />
      <h3>{template.name}</h3>
      <p className="wall-card-copy">{template.description}</p>
      <div className="wall-card-actions">
        <div className="wall-rooms" role="group" aria-label={`${template.name}: rooms`}>
          {controller.rooms.map((room) => (
            <button
              key={room.id}
              type="button"
              aria-pressed={rooms.includes(room.id)}
              className={rooms.includes(room.id) ? "chosen" : ""}
              onClick={() => toggle(room.id)}
            >
              {room.name}
            </button>
          ))}
        </div>
        <Button disabled={busy || !admin} onClick={() => void create()}>
          {busy && <LoaderCircle size={16} className="spin" />}
          {latest ? "Create again" : "Create in Home Assistant"}
        </Button>
      </div>
      {latest && Number.isFinite(created) && (
        <p
          className={`${confirmed ? "success-text" : "muted"} wall-created`}
          data-created={latest.url_path}
          data-confirmed={confirmed}
          role="status"
        >
          Created {dayLabel(created, controller.timeZone)} {clock(created, controller.timeZone)} for{" "}
          {latest.rooms
            .map((id) => controller.rooms.find((room) => room.id === id)?.name ?? id)
            .join(", ")}{" "}
          as /{latest.url_path}
          {!confirmed && ", not confirmed"}
          <a href={`/${latest.url_path}`} target="_blank" rel="noreferrer">
            Open in Home Assistant
          </a>
        </p>
      )}
      {!admin && <p className="small muted">Only an administrator can create a dashboard.</p>}
      {problem && (
        <p className="error-text" role="alert">
          {problem}
        </p>
      )}
    </article>
  );
}
