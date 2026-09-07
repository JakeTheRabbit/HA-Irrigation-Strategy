import { useLayoutEffect, useEffect, useRef, useState } from "react";
import {
  CalendarRange,
  Download,
  Upload,
  Save,
  Play,
  Pause,
  Plus,
  Copy,
  RefreshCw,
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
import { Heading, Empty, number } from "@/components/dashboard";
import { WaterDelivery } from "@/components/water-delivery";
import { PlanningCurve } from "@/components/planning-curve";
import { RecipeLibrary } from "@/components/recipe-library";
import { syncPlanZones } from "@/lib/sync-plan-zones";
import type { Controller } from "@/lib/types";
import type {
  GrowPlan,
  StrategyDocument,
  SteeringProfile,
  ScheduleBlock,
} from "@/lib/operator-types";
import {
  blockForDay,
  dateForDay,
  growDay,
  interpolate,
  localDate,
  parameterHelp,
  parameterLabels,
  parsePlanImport,
  planErrors,
  replaceRange,
} from "@/lib/grow-plan";

export function GrowPlanner({
  controller,
  onDirtyChange,
}: {
  controller: Controller;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [document, setDocument] = useState<StrategyDocument | null>(null);
  const [plan, setPlan] = useState<GrowPlan | null>(null);
  const [zoneId, setZoneId] = useState(controller.room.zones[0]?.id || 1);
  const [day, setDay] = useState(1);
  const [granularity, setGranularity] = useState<"week" | "day">("week");
  const [tab, setTab] = useState<"calendar" | "profiles">("calendar");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [review, setReview] = useState<"save" | "activate" | "disarm" | null>(null);
  const [libraryDirty, setLibraryDirty] = useState(false);
  const [preview, setPreview] = useState<StrategyDocument | null>(null);
  const importRef = useRef<HTMLInputElement>(null);
  const dirty = !!plan && !!document && JSON.stringify(plan) !== JSON.stringify(document.plan);
  useLayoutEffect(() => {
    onDirtyChange(dirty || libraryDirty);
    return () => onDirtyChange(false);
  }, [dirty, libraryDirty, onDirtyChange]);
  async function load() {
    if (!controller.roomId) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const value = await controller.operator<StrategyDocument>("strategy_get");
      if (!value.plan || !value.catalog)
        throw new Error("Update the integration to use grow plans.");
      setDocument(value);
      setPlan(structuredClone(value.plan));
      const first = value.plan.zones.find((z) => z.zone_id === zoneId) || value.plan.zones[0];
      if (first) {
        setZoneId(first.zone_id);
        setDay(Math.max(1, Math.min(366, growDay(first.start_date, localDate()))));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!document && ["live", "demo"].includes(controller.connection)) void load();
  }, [controller.roomId, controller.connection]);
  const statusContext = useRef({ document, dirty, busy, review });
  statusContext.current = { document, dirty, busy, review };
  useEffect(() => {
    if (!document || dirty || !["live", "demo"].includes(controller.connection)) return;
    let cancelled = false,
      reading = false;
    const refreshStatus = async () => {
      const before = statusContext.current;
      if (cancelled || reading || !before.document || before.dirty || before.busy || before.review)
        return;
      reading = true;
      try {
        const next = await controller.operator<StrategyDocument>("strategy_get");
        const current = statusContext.current;
        // Reads cannot be allowed to replace edits or a newer explicit load/save result.
        if (
          cancelled ||
          current.dirty ||
          current.busy ||
          current.review ||
          current.document !== before.document
        )
          return;
        if (next.room_id !== controller.roomId || !next.plan || !next.catalog) return;
        setDocument(next);
        setPlan(structuredClone(next.plan));
        // Deliberately retain the selected zone, preview day, tab and local review messages.
      } catch {
        // The normal connection monitor reports transport outages. Retry quietly next interval.
      } finally {
        reading = false;
      }
    };
    const timer = window.setInterval(() => void refreshStatus(), 20_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [controller.roomId, controller.connection, Boolean(document), dirty]);
  const zonePlan = plan?.zones.find((z) => z.zone_id === zoneId);
  const currentBlock = blockForDay(zonePlan, day);
  const profile =
    plan?.profiles.find((p) => p.id === currentBlock?.profile_id) || plan?.profiles[0];
  const limits = document?.catalog[String(zoneId)] || {};
  const params = interpolate(profile, currentBlock?.bias ?? 50, limits);
  const errors = plan && document ? planErrors(plan, document.catalog) : [];
  const editable = document?.status === "draft";
  const connected = ["live", "demo"].includes(controller.connection);
  const disabled = busy || !editable || !connected;
  const activeZoneIds = controller.room.zones.map((zone) => zone.id);
  const zoneMismatch =
    !!plan &&
    (activeZoneIds.length !== plan.zones.length ||
      activeZoneIds.some((id) => !plan.zones.some((zone) => zone.zone_id === id)));
  function updateZonesFromSetup() {
    if (!plan || !document || disabled) return;
    const result = syncPlanZones(plan, activeZoneIds, document.catalog, localDate());
    setPlan(result.plan);
    setPreview(null);
    if (!activeZoneIds.includes(zoneId)) {
      setZoneId(activeZoneIds[0] || 1);
      setDay(1);
    }
    setNotice(
      `Local draft updated: ${result.added.length} zone assignments added; ${result.removed.length} archived assignments removed. Existing profiles are retained. Review and save before arming.${result.unseeded.length ? " Current values are unavailable for zones " + result.unseeded.join(", ") + "; supply their endpoints before saving." : ""}`,
    );
  }
  const firstDay = granularity === "week" ? Math.floor((day - 1) / 7) * 7 + 1 : day;
  const lastDay = granularity === "week" ? Math.min(366, firstDay + 6) : day;
  const lastScheduled = Math.max(
    84,
    ...(plan?.zones.flatMap((z) => z.schedule.map((b) => b.end_day)) || []),
  );
  const columns =
    granularity === "week" ? Math.ceil(lastScheduled / 7) : Math.min(lastScheduled, 366);
  const selectedZone = controller.room.zones.find((z) => z.id === zoneId);
  const configuredLightsOn = controller.room.settings.find((f) =>
    f.entityId.endsWith("_lights_on_hour"),
  )?.value;
  const configuredLightsOff = controller.room.settings.find((f) =>
    f.entityId.endsWith("_lights_off_hour"),
  )?.value;
  const lightsOn = configuredLightsOn ?? 0,
    lightsOff = configuredLightsOff ?? 12;
  function setZone(next: number) {
    setZoneId(next);
    setPreview(null);
  }
  function updateBlock(patch: Partial<ScheduleBlock>) {
    if (!plan || !zonePlan || !profile || disabled) return;
    const block = {
      start_day: firstDay,
      end_day: lastDay,
      profile_id: currentBlock?.profile_id || profile.id,
      bias: currentBlock?.bias ?? 50,
      ...patch,
    };
    setPlan({
      ...plan,
      zones: plan.zones.map((z) =>
        z.zone_id === zoneId ? { ...z, schedule: replaceRange(z.schedule, block) } : z,
      ),
    });
    setNotice("");
    setPreview(null);
  }
  function editProfile(side: "vegetative" | "generative", key: string, value: number) {
    if (!plan || !profile || disabled) return;
    setPlan({
      ...plan,
      profiles: plan.profiles.map((p) =>
        p.id === profile.id ? { ...p, [side]: { ...p[side], [key]: value } } : p,
      ),
    });
    setPreview(null);
    setNotice("");
  }
  function curveEdit(key: string, value: number) {
    // Moving a target makes the effective value explicit at both endpoints for this profile.
    if (!plan || !profile || disabled) return;
    setPlan({
      ...plan,
      profiles: plan.profiles.map((p) =>
        p.id === profile.id
          ? {
              ...p,
              vegetative: { ...p.vegetative, [key]: value },
              generative: { ...p.generative, [key]: value },
            }
          : p,
      ),
    });
    setNotice("Curve target updated at both endpoints of this profile. Review before saving.");
    setPreview(null);
  }
  async function previewPlan() {
    if (!plan || !zonePlan) return;
    setBusy(true);
    setError("");
    try {
      const result = await controller.operator<StrategyDocument>("strategy_preview", {
        plan,
        date: dateForDay(zonePlan.start_date, day),
      });
      setPreview(result);
      setReview("save");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function commit() {
    if (!document || !plan || !review) return;
    setBusy(true);
    setError("");
    try {
      const result = await controller.operator<StrategyDocument>(
        review === "save"
          ? "strategy_save"
          : review === "activate"
            ? "strategy_activate"
            : "strategy_disarm",
        review === "save"
          ? { plan, expected_revision: document.revision }
          : review === "activate"
            ? { expected_revision: document.revision }
            : {},
      );
      setDocument(result);
      setPlan(structuredClone(result.plan));
      setReview(null);
      setNotice(
        review === "save"
          ? "Draft saved to Home Assistant. It is not active."
          : review === "activate"
            ? "Plan armed for the next lights-on boundary."
            : "Plan disarm requested; active targets remain until the next boundary.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  function exportPlan() {
    if (!plan) return;
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            { format: "crop-steering-plan", room_name: controller.room.room.name, plan },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const a = window.document.createElement("a");
    a.href = url;
    a.download = "crop-steering-plan.json";
    a.click();
    URL.revokeObjectURL(url);
  }
  async function importPlan(file?: File) {
    if (!file) return;
    setError("");
    try {
      const value = parsePlanImport(await file.text());
      if (value.zones.some((z) => !controller.room.zones.some((actual) => actual.id === z.zone_id)))
        throw new Error("The file contains zones not present in this room. Map the room first.");
      setPlan(value);
      setNotice(
        "Plan imported as a local draft. Check endpoints and zone assignments before saving.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    if (importRef.current) importRef.current.value = "";
  }
  if (!controller.roomId)
    return (
      <>
        <Heading
          title="Grow plan"
          description="Plan the complete grow, separately for each zone."
        />
        <Empty
          title="Add or select a room"
          detail="Room and zone configuration comes first."
          action={
            <Button asChild>
              <a href="#/setup">Open room setup</a>
            </Button>
          }
        />
      </>
    );
  return (
    <>
      <Heading
        title="Grow plan"
        description="Plan each zone day by day. Your steering curve, endpoint profiles and delivery estimates update together."
        action={
          <div className="workspace-actions">
            <Button variant="outline" onClick={exportPlan} disabled={!plan}>
              <Download size={16} />
              Export
            </Button>
            <Button
              variant="outline"
              disabled={disabled || !plan}
              onClick={() => importRef.current?.click()}
            >
              <Upload size={16} />
              Import
            </Button>
          </div>
        }
      />
      <input
        ref={importRef}
        type="file"
        accept="application/json,.json"
        className="sr-only"
        aria-label="Import grow plan"
        onChange={(e) => void importPlan(e.target.files?.[0])}
      />
      {error && (
        <div className="workspace-message error" role="alert">
          {error}
          {dirty && (
            <p>
              Your local draft is retained. Export it before discarding changes and reloading the
              stored plan.
            </p>
          )}
        </div>
      )}
      {notice && (
        <div className="workspace-message" role="status">
          {notice}
        </div>
      )}
      {!plan || !document ? (
        <section className="panel workspace-card">
          <Empty
            title={busy ? "Loading grow plan" : "Grow planner needs the updated integration"}
            detail="Install the current Crop Steering integration and controller to store and run zone plans. You can explore the complete workflow in demo mode."
            action={
              <div className="workspace-actions">
                <Button onClick={() => void load()} disabled={busy}>
                  <RefreshCw size={16} />
                  Retry
                </Button>
                <Button asChild variant="outline">
                  <a href="#/setup">Installation & setup</a>
                </Button>
              </div>
            }
          />
        </section>
      ) : (
        <>
          <RecipeLibrary
            key={`${controller.roomId}:${controller.demo ? "demo" : "live"}`}
            roomId={controller.roomId}
            roomName={controller.room.room.name}
            demo={controller.demo}
            plan={plan}
            catalog={document.catalog}
            activeZoneIds={activeZoneIds}
            dirty={dirty}
            canLoad={!disabled && !controller.room.strategy.engaged}
            onDirtyChange={setLibraryDirty}
            onLoad={(next) => {
              if (disabled || controller.room.strategy.engaged)
                throw new Error(
                  "The grow plan cannot accept a recipe while active, armed, busy or disconnected.",
                );
              setPlan(next);
              setPreview(null);
              setError("");
              setNotice(
                "Recipe loaded into the local draft. Current zone start dates are retained. Review and save before arming.",
              );
            }}
          />
          <section className="panel workspace-card plan-toolbar">
            <div>
              <span className="eyebrow">Plan status</span>
              <strong className="plan-state">
                {document.status}
                {dirty ? " · unsaved changes" : ""}
              </strong>
              <p className="muted small">
                Revision {document.revision} ·{" "}
                {controller.demo ? "Isolated sample plan" : "Stored in Home Assistant"}
              </p>
            </div>
            <div className="workspace-actions">
              <Button
                variant="outline"
                disabled={busy || dirty || !connected}
                onClick={() => void load()}
                title={
                  dirty
                    ? "Export or discard your local draft before reloading"
                    : "Fetch the latest stored revision"
                }
              >
                <RefreshCw size={16} />
                Reload stored plan
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setPlan(structuredClone(document.plan));
                  setNotice("");
                }}
                disabled={!dirty || busy}
              >
                Discard draft
              </Button>
              <Button onClick={() => void previewPlan()} disabled={disabled || errors.length > 0}>
                <Save size={16} />
                {dirty ? "Review & save" : "Validate preview"}
              </Button>
              {document.status === "draft" ? (
                <Button
                  variant="outline"
                  disabled={
                    busy ||
                    dirty ||
                    errors.length > 0 ||
                    !document.capabilities.controller_supported ||
                    !connected
                  }
                  onClick={() => setReview("activate")}
                >
                  <Play size={16} />
                  Arm plan
                </Button>
              ) : (
                <Button
                  variant="outline"
                  disabled={busy || document.status === "disarming" || !connected}
                  onClick={() => setReview("disarm")}
                >
                  <Pause size={16} />
                  Disarm plan
                </Button>
              )}
            </div>
          </section>
          {zoneMismatch && (
            <div className="workspace-message">
              <p>
                Setup's active zones differ from this stored plan. Export first if you need a copy.
                Updating creates a local draft, preserves existing active schedules, removes
                archived assignments and starts new zones from their current values at both
                endpoints.
              </p>
              <Button variant="outline" disabled={disabled} onClick={updateZonesFromSetup}>
                Update zones from setup
              </Button>
              {!editable && (
                <p>Disarm and wait for draft status before updating zone assignments.</p>
              )}
            </div>
          )}
          {!document.capabilities.controller_supported && (
            <div className="workspace-message">
              Controller update required before activation. Plans can still be drafted and
              previewed.
            </div>
          )}
          {!editable && (
            <div className="workspace-message">
              This plan is {document.status}. Disarm it before editing. Active targets change only
              at the next lights-on boundary.
            </div>
          )}
          {!!errors.length && (
            <details className="workspace-message error">
              <summary>
                {errors.length} item{errors.length === 1 ? "" : "s"} to resolve before saving
              </summary>
              <ul>
                {errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </details>
          )}
          <div className="workspace-tabs" role="tablist" aria-label="Grow planner view">
            <button
              role="tab"
              aria-selected={tab === "calendar"}
              onClick={() => setTab("calendar")}
            >
              Schedule & curve
            </button>
            <button
              role="tab"
              aria-selected={tab === "profiles"}
              onClick={() => setTab("profiles")}
            >
              Endpoint profiles
            </button>
          </div>
          {tab === "calendar" && (
            <>
              <section className="panel workspace-card">
                <div className="workspace-section-heading">
                  <div>
                    <h2>Whole-grow overview</h2>
                    <p className="muted">
                      Each row is a zone. Select a day or week to edit its steering balance.
                    </p>
                  </div>
                  <div className="workspace-actions">
                    <Button
                      variant={granularity === "week" ? "default" : "outline"}
                      onClick={() => setGranularity("week")}
                    >
                      Weeks
                    </Button>
                    <Button
                      variant={granularity === "day" ? "default" : "outline"}
                      onClick={() => setGranularity("day")}
                    >
                      Days
                    </Button>
                  </div>
                </div>
                <div
                  className="plan-calendar-scroll"
                  tabIndex={0}
                  role="region"
                  aria-label="Grow schedule"
                >
                  <div
                    className="plan-calendar"
                    style={{
                      gridTemplateColumns:
                        "150px repeat(" +
                        columns +
                        ", minmax(" +
                        (granularity === "week" ? 76 : 45) +
                        "px, 1fr))",
                    }}
                  >
                    <div className="calendar-label">Zone / grow age</div>
                    {Array.from({ length: columns }, (_, i) => (
                      <div key={i} className="calendar-heading">
                        {granularity === "week" ? "Week " + (i + 1) : "D" + (i + 1)}
                      </div>
                    ))}
                    {plan.zones.map((z) => (
                      <div className="calendar-row" key={z.zone_id}>
                        <button className="calendar-label" onClick={() => setZone(z.zone_id)}>
                          {controller.room.zones.find((x) => x.id === z.zone_id)?.name ||
                            "Zone " + z.zone_id}
                          <small>{z.start_date}</small>
                        </button>
                        {Array.from({ length: columns }, (_, i) => {
                          const d = granularity === "week" ? i * 7 + 1 : i + 1;
                          const b = blockForDay(z, d);
                          const selected =
                            z.zone_id === zoneId &&
                            day >= d &&
                            day < d + (granularity === "week" ? 7 : 1);
                          const end = granularity === "week" ? Math.min(d + 6, 366) : d;
                          const mixed = z.schedule.some(
                            (s) => s.start_day > d && s.start_day <= end,
                          );
                          return (
                            <button
                              key={i}
                              className={"calendar-cell" + (selected ? " selected" : "")}
                              onClick={() => {
                                setZone(z.zone_id);
                                setDay(d);
                              }}
                              aria-label={
                                (controller.room.zones.find((x) => x.id === z.zone_id)?.name ||
                                  "Zone " + z.zone_id) +
                                ", " +
                                (granularity === "week" ? "week " + (i + 1) : "day " + d) +
                                ", " +
                                (mixed
                                  ? "mixed steering"
                                  : b
                                    ? b.bias + " percent generative"
                                    : "unscheduled")
                              }
                              style={{ "--bias": String(b?.bias ?? 0) } as React.CSSProperties}
                            >
                              <span>{mixed ? "Mixed" : b ? b.bias + "%" : "—"}</span>
                              <small>{b ? "G" : "No plan"}</small>
                            </button>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                </div>
              </section>
              <section className="panel workspace-card">
                <div className="workspace-section-heading">
                  <div>
                    <h2>
                      {selectedZone?.name || "Zone " + zoneId} ·{" "}
                      {granularity === "week" ? "days " + firstDay + "–" + lastDay : "day " + day}
                    </h2>
                    <p className="muted">
                      {zonePlan ? dateForDay(zonePlan.start_date, firstDay) : ""} ·{" "}
                      {profile?.name || "Choose a profile"}
                    </p>
                  </div>
                  <div className="workspace-actions">
                    <Label htmlFor="preview-grow-day">Preview day</Label>
                    <Input
                      id="preview-grow-day"
                      type="number"
                      min={1}
                      max={366}
                      value={day}
                      onChange={(e) => {
                        const n = Number(e.target.value);
                        if (Number.isInteger(n) && n >= 1 && n <= 366) setDay(n);
                      }}
                      className="short-input"
                    />
                  </div>
                </div>
                <div className="workspace-form-grid">
                  <div>
                    <Label htmlFor="zone-start-date">Zone grow start date</Label>
                    <Input
                      id="zone-start-date"
                      type="date"
                      disabled={disabled}
                      value={zonePlan?.start_date || ""}
                      onChange={(e) =>
                        setPlan({
                          ...plan,
                          zones: plan.zones.map((z) =>
                            z.zone_id === zoneId ? { ...z, start_date: e.target.value } : z,
                          ),
                        })
                      }
                    />
                  </div>
                  <div>
                    <Label htmlFor="block-profile">Endpoint profile</Label>
                    <select
                      id="block-profile"
                      value={profile?.id || ""}
                      disabled={disabled}
                      onChange={(e) => updateBlock({ profile_id: e.target.value })}
                    >
                      {plan.profiles.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="steering-control">
                  <div className="workspace-section-heading">
                    <Label htmlFor="steering-balance">Steering balance</Label>
                    <strong>{currentBlock?.bias ?? 50}% generative</strong>
                  </div>
                  <input
                    id="steering-balance"
                    type="range"
                    min={0}
                    max={100}
                    step={1}
                    value={currentBlock?.bias ?? 50}
                    disabled={disabled}
                    onChange={(e) => updateBlock({ bias: Number(e.target.value) })}
                  />
                  <div className="range-labels">
                    <span>Vegetative endpoint</span>
                    <span>Generative endpoint</span>
                  </div>
                </div>
                {(configuredLightsOn == null || configuredLightsOff == null) && (
                  <p className="workspace-message">
                    Light schedule unavailable: this illustration assumes{" "}
                    {configuredLightsOn == null
                      ? "00:00 lights-on"
                      : "the configured lights-on time"}{" "}
                    and{" "}
                    {configuredLightsOff == null
                      ? "12:00 lights-off"
                      : "the configured lights-off time"}
                    . Supply readable room light hours before relying on these planning windows.
                  </p>
                )}
                <PlanningCurve
                  parameters={params}
                  lightsOn={lightsOn}
                  lightsOff={lightsOff}
                  onChange={disabled ? undefined : curveEdit}
                />
                <p className="muted small">
                  The curve is a setpoint planning model. Actual moisture, EC and shot timing depend
                  on sensor feedback. Editing a curve target updates both endpoints of this profile.
                </p>
                <WaterDelivery controller={controller} zoneId={zoneId} parameters={params} />
              </section>
              <section className="panel workspace-card">
                <div className="workspace-section-heading">
                  <div>
                    <h2>Zone schedule blocks</h2>
                    <p className="muted">
                      Exact inclusive grow-day ranges. Editing a day or week splits its block
                      without changing neighboring days.
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    disabled={disabled}
                    onClick={() => {
                      if (!zonePlan || !profile) return;
                      const start = Math.max(0, ...zonePlan.schedule.map((b) => b.end_day)) + 1;
                      if (start <= 366) {
                        setDay(start);
                        setPlan({
                          ...plan,
                          zones: plan.zones.map((z) =>
                            z.zone_id === zoneId
                              ? {
                                  ...z,
                                  schedule: [
                                    ...z.schedule,
                                    {
                                      start_day: start,
                                      end_day: Math.min(start + 6, 366),
                                      profile_id: profile.id,
                                      bias: 50,
                                    },
                                  ],
                                }
                              : z,
                          ),
                        });
                      }
                    }}
                  >
                    <Plus size={16} />
                    Add week
                  </Button>
                </div>
                <div className="schedule-blocks">
                  {zonePlan?.schedule.map((block, i) => (
                    <button
                      key={i}
                      className={day >= block.start_day && day <= block.end_day ? "selected" : ""}
                      onClick={() => setDay(block.start_day)}
                    >
                      <strong>
                        Days {block.start_day}–{block.end_day}
                      </strong>
                      <span>
                        {plan.profiles.find((p) => p.id === block.profile_id)?.name} · {block.bias}%
                        G
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            </>
          )}
          {tab === "profiles" && (
            <section className="panel workspace-card">
              <div className="workspace-section-heading">
                <div>
                  <h2>Vegetative and generative endpoints</h2>
                  <p className="muted">
                    The slider blends between these values. Set appropriate targets for your
                    substrate, cultivar and grow stage.
                  </p>
                </div>
                <Button
                  variant="outline"
                  disabled={disabled || !profile}
                  onClick={() => {
                    if (!profile) return;
                    const id = "profile-" + Date.now().toString(36);
                    const copy = { ...structuredClone(profile), id, name: profile.name + " copy" };
                    setPlan({
                      ...plan,
                      profiles: [...plan.profiles, copy],
                      zones: plan.zones.map((z) =>
                        z.zone_id === zoneId
                          ? {
                              ...z,
                              schedule: replaceRange(z.schedule, {
                                start_day: firstDay,
                                end_day: lastDay,
                                bias: 50,
                                profile_id: id,
                              }),
                            }
                          : z,
                      ),
                    });
                  }}
                >
                  <Copy size={16} />
                  Duplicate profile
                </Button>
              </div>
              <div className="workspace-form-grid">
                <div>
                  <Label htmlFor="profile-zone">Zone limits</Label>
                  <select
                    id="profile-zone"
                    value={zoneId}
                    onChange={(e) => setZone(Number(e.target.value))}
                  >
                    {plan.zones.map((z) => (
                      <option key={z.zone_id} value={z.zone_id}>
                        {controller.room.zones.find((x) => x.id === z.zone_id)?.name ||
                          "Zone " + z.zone_id}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label htmlFor="profile-name">Profile name</Label>
                  <Input
                    id="profile-name"
                    value={profile?.name || ""}
                    disabled={disabled}
                    onChange={(e) =>
                      setPlan({
                        ...plan,
                        profiles: plan.profiles.map((p) =>
                          p.id === profile?.id ? { ...p, name: e.target.value } : p,
                        ),
                      })
                    }
                  />
                </div>
              </div>
              <div className="profile-grid profile-heading">
                <strong>Parameter</strong>
                <strong>Vegetative</strong>
                <strong>Generative</strong>
              </div>
              {Object.entries(limits).map(([key, limit]) => (
                <div className="profile-grid" key={key}>
                  <div>
                    <strong>{parameterLabels[key] || key.replaceAll("_", " ")}</strong>
                    <p className="muted small">
                      {parameterHelp[key] || "Configured controller parameter."}
                    </p>
                    <small className="muted">
                      {limit.min}–{limit.max} {limit.unit}
                    </small>
                  </div>
                  {(["vegetative", "generative"] as const).map((side) => (
                    <div key={side}>
                      <Label className="sr-only" htmlFor={side + "-" + key}>
                        {side + " " + (parameterLabels[key] || key)}
                      </Label>
                      <Input
                        id={side + "-" + key}
                        type="number"
                        min={limit.min}
                        max={limit.max}
                        step={limit.step || "any"}
                        disabled={disabled}
                        value={Number.isFinite(profile?.[side][key]) ? profile![side][key] : ""}
                        onChange={(e) =>
                          editProfile(
                            side,
                            key,
                            e.target.value === "" ? NaN : Number(e.target.value),
                          )
                        }
                      />
                      <small className="muted">{limit.unit}</small>
                    </div>
                  ))}
                </div>
              ))}
              <div className="workspace-message">
                New live profiles start from current setpoints at both ends. Changing pot size does
                not choose crop targets. Demo endpoints are illustrative.
              </div>
            </section>
          )}
        </>
      )}
      <Dialog
        open={!!review}
        onOpenChange={(open) => {
          if (!open && !busy) setReview(null);
        }}
      >
        <DialogContent className="plan-review-dialog">
          <DialogHeader>
            <DialogTitle>
              {review === "save"
                ? "Review grow plan"
                : review === "activate"
                  ? "Arm this grow plan?"
                  : "Disarm this grow plan?"}
            </DialogTitle>
            <DialogDescription>
              {controller.room.room.name} only.{" "}
              {review === "save"
                ? "Saving stores a draft and does not change active irrigation."
                : review === "activate"
                  ? "The validated plan will become eligible at the next local lights-on boundary. It never enables pumps or the engine."
                  : "Active targets remain until the next lights-on boundary, then the controller returns to legacy setpoints."}
            </DialogDescription>
          </DialogHeader>
          {review === "save" && (
            <>
              <p>
                {plan?.zones.length} zone plans · {plan?.profiles.length} endpoint profiles ·
                revision {document?.revision}
              </p>
              <div className="plan-review-zones">
                {preview?.preview?.zones.map((z) => (
                  <div className="workspace-message" key={z.zone_id}>
                    <strong>
                      Zone {z.zone_id} · grow day {z.day} · {z.bias ?? "—"}% G
                    </strong>
                    {z.errors?.length ? (
                      <p>{z.errors.join(" ")}</p>
                    ) : (
                      <p>
                        VWC target {number(z.parameters.p1_target_vwc ?? null)}% · P2 trigger{" "}
                        {number(z.parameters.p2_vwc_threshold ?? null)}% · P2 EC{" "}
                        {number(z.parameters.ec_target_p2 ?? null)} mS/cm
                      </p>
                    )}
                    {z.hydraulics && (
                      <p>
                        First shot:{" "}
                        {number(z.hydraulics.shots.p1_initial_shot_size?.volume_l ?? null)} L ·{" "}
                        {number(
                          z.hydraulics.shots.p1_initial_shot_size?.capped_duration_s ?? null,
                          0,
                        )}{" "}
                        s after cap
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
          {error && (
            <p role="alert" className="error-text">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setReview(null)}>
              Back to editing
            </Button>
            <Button
              disabled={busy || !connected || (review === "save" && errors.length > 0)}
              onClick={() => void commit()}
            >
              {busy
                ? "Working…"
                : review === "save"
                  ? "Save draft"
                  : review === "activate"
                    ? "Arm for next lights-on"
                    : "Confirm disarm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
