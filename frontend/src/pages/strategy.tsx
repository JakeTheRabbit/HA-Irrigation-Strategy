import { useEffect, useState } from "react";
import { ArrowRight, Check, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Empty, Heading, ReviewDialog, number, type ReviewItem } from "@/components/dashboard";
import type { Controller, Setting } from "@/lib/types";
import { PlanningCurve } from "@/components/planning-curve";
import { WaterDelivery } from "@/components/water-delivery";
import { buildSetpointPreview, validateSetpoint } from "@/lib/setpoint-preview";
import type { PlanningPhaseId } from "@/lib/planning-curve";
import "./setpoint-preview.css";

const phaseGroups = ["P0 · Morning dryback", "P1 · Ramp-up", "P2 · Maintenance", "P3 · Overnight"];
function fieldGroup(setting: Setting) {
  const ecPhase = setting.entityId.match(/_ec_target_(?:veg|gen)_p([012])$/);
  return ecPhase ? phaseGroups[Number(ecPhase[1])] : setting.group;
}

export type Drafts = Record<
  string,
  {
    value: string;
    original: number | string | null;
    label: string;
    zone: string;
  }
>;
export function Strategy({
  controller,
  drafts,
  setDrafts,
  selectedZone,
}: {
  controller: Controller;
  drafts: Drafts;
  setDrafts: React.Dispatch<React.SetStateAction<Drafts>>;
  selectedZone?: number;
}) {
  const [zoneId, setZoneId] = useState<string>(
    selectedZone === undefined
      ? String(controller.room.zones[0]?.id ?? "room")
      : String(selectedZone),
  );
  const [review, setReview] = useState(false);
  const [saved, setSaved] = useState(false);
  const [phase, setPhase] = useState("All");
  const [showInactive, setShowInactive] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [roomPreviewZone, setRoomPreviewZone] = useState(controller.room.zones[0]?.id);
  useEffect(() => {
    if (selectedZone !== undefined) setZoneId(String(selectedZone));
  }, [selectedZone]);
  const planEngaged = controller.room.strategy.engaged;
  const allSettings = controller.room.settings;
  const zone = controller.room.zones.find((z) => String(z.id) === zoneId);
  const fields =
    zoneId === "room"
      ? allSettings.filter((field) => field.zoneId === undefined)
      : zone?.fields || [];
  const choices = (controller.room.choices || []).filter((choice) =>
    zoneId === "room" ? choice.zoneId === undefined : String(choice.zoneId) === zoneId,
  );
  const previewZoneId =
    zone?.id ??
    controller.room.zones.find((z) => z.id === roomPreviewZone)?.id ??
    controller.room.zones[0]?.id;
  const preview = buildSetpointPreview(
    controller.room,
    controller.states,
    previewZoneId ?? 0,
    drafts,
  );
  const activeMode =
    preview.draft.mode === "Vegetative"
      ? "veg"
      : preview.draft.mode === "Generative"
        ? "gen"
        : null;
  const visibleFields = fields.filter((setting) => {
    if (showInactive || !activeMode) return true;
    const mode = setting.entityId.match(
      /_(vegetative|generative)_dryback_target$|_ec_target_(veg|gen)_p[012]$/,
    );
    return !mode || (mode[1]?.slice(0, 3) ?? mode[2]) === activeMode;
  });
  const groups = [...new Set(visibleFields.map(fieldGroup))];
  const shownGroups = groups.filter(
    (group) =>
      phase === "All" || (phase === "Other" ? !/^P[0-3]/.test(group) : group.startsWith(phase)),
  );
  const invalid = validateSetpoint;
  const canEdit = !planEngaged && ["live", "demo"].includes(controller.connection);
  const errors = Object.entries(drafts)
    .map(([id, draft]) => {
      const setting = allSettings.find((s) => s.entityId === id);
      const choice = controller.room.choices.find((c) => c.entityId === id);
      return setting
        ? invalid(setting, draft.value)
        : choice
          ? choice.options.includes(draft.value)
            ? ""
            : "Select an available mode."
          : "A draft setting is no longer available. Discard it before continuing.";
    })
    .filter(Boolean);
  const items: ReviewItem[] = Object.entries(drafts).flatMap<ReviewItem>(([id, draft]) => {
    const setting = allSettings.find((s) => s.entityId === id);
    const choice = controller.room.choices.find((c) => c.entityId === id);
    if (choice && choice.options.includes(draft.value))
      return [
        {
          change: { entityId: id, value: draft.value },
          label: `${draft.zone} · ${draft.label}`,
          before: choice.value || "Unavailable",
          after: draft.value,
        },
      ];
    return !setting || invalid(setting, draft.value)
      ? []
      : [
          {
            change: { entityId: id, value: Number(draft.value) },
            label: `${draft.zone} · ${draft.label}`,
            before: `${number(setting.value)} ${setting.unit}`,
            after: `${number(Number(draft.value))} ${setting.unit}`,
          },
        ];
  });
  function edit(setting: Setting, value: string) {
    setSaved(false);
    setDrafts((current) => {
      const next = { ...current };
      if (value.trim() && Number(value) === (current[setting.entityId]?.original ?? setting.value))
        delete next[setting.entityId];
      else
        next[setting.entityId] = {
          value,
          original: current[setting.entityId]?.original ?? setting.value,
          label: setting.label,
          zone:
            setting.zoneId === undefined
              ? "Room settings"
              : (controller.room.zones.find((item) => item.id === setting.zoneId)?.name ??
                `Zone ${setting.zoneId}`),
        };
      return next;
    });
  }
  return (
    <>
      <Heading
        title="Manual setpoints"
        description="Adjust a zone beside its daily VWC and EC plan. Draft changes appear immediately; review before applying."
        action={
          <Button
            disabled={
              !items.length ||
              Boolean(errors.length) ||
              planEngaged ||
              !["live", "demo"].includes(controller.connection)
            }
            onClick={() => setReview(true)}
          >
            Review {Object.keys(drafts).length || ""}{" "}
            {Object.keys(drafts).length === 1 ? "change" : "changes"} <ArrowRight size={16} />
          </Button>
        }
      />
      {planEngaged && (
        <div className="workspace-message">
          The active grow plan owns this room's targets. These are stored manual fallback values.{" "}
          <Button asChild variant="outline">
            <a href="#/grow-plan">Open grow plan</a>
          </Button>
        </div>
      )}
      <div className="workflow-steps">
        <span className="active">
          <i>1</i>Edit draft
        </span>
        <span>
          <i>2</i>Review changes
        </span>
        <span>
          <i>3</i>Apply & verify
        </span>
      </div>
      <div className="strategy-layout setpoint-workspace">
        <aside className="strategy-zone-picker">
          <span className="eyebrow">Configure</span>
          {controller.room.zones.map((z) => (
            <button
              key={z.id}
              className={zoneId === String(z.id) ? "selected" : ""}
              onClick={() => {
                setZoneId(String(z.id));
                setPhase("All");
              }}
            >
              <span>{z.name}</span>
              <span className="small">
                {Object.values(drafts).filter((d) => d.zone === z.name).length || z.phase}
              </span>
            </button>
          ))}
          <button
            className={zoneId === "room" ? "selected" : ""}
            onClick={() => {
              setZoneId("room");
              setPhase("All");
            }}
          >
            <span>Room settings</span>
            <SlidersHorizontal size={16} />
          </button>
          <p>Each setting uses the limits and units reported by your controller.</p>
        </aside>
        <div className="strategy-content">
          <div className="section-title">
            <div>
              <h2>{zone?.name || "Room settings"}</h2>
              <p>
                {zone
                  ? "Phase targets, timing and limits for this zone."
                  : "Shared controller settings for this room."}
              </p>
            </div>
          </div>
          {saved && (
            <div className="success-banner" role="status">
              <Check size={18} />
              Changes applied and verified by controller readback.
            </div>
          )}
          <div className="setpoint-editor-grid">
            <div className="setpoint-controls">
              <nav className="setpoint-phase-picker" aria-label="Setpoint phase">
                {["All", "P0", "P1", "P2", "P3", "Other"]
                  .filter(
                    (item) =>
                      item === "All" ||
                      (item === "Other"
                        ? groups.some((group) => !/^P[0-3]/.test(group))
                        : groups.some((group) => group.startsWith(item))),
                  )
                  .map((item) => (
                    <button
                      type="button"
                      key={item}
                      aria-pressed={phase === item}
                      onClick={() => setPhase(item)}
                    >
                      {item === "Other" ? "Room & limits" : item === "All" ? "All settings" : item}
                    </button>
                  ))}
              </nav>
              {choices.length > 0 && (
                <section className="panel settings-group">
                  <div className="settings-group-heading">
                    <span className="phase-marker">
                      <SlidersHorizontal size={16} />
                    </span>
                    <div>
                      <h3>Steering mode</h3>
                      <p>
                        {zone
                          ? "The selected mode supplies the EC and morning dryback targets below."
                          : "The current engine uses each zone's mode, with legacy growth stage as fallback."}
                      </p>
                    </div>
                  </div>
                  <div className="setting-fields">
                    {choices.map((choice) => (
                      <div className="setting-field" key={choice.entityId}>
                        <div>
                          <Label htmlFor={`choice-${choice.entityId}`}>
                            {choice.label}
                            {drafts[choice.entityId] && <span className="draft-dot" />}
                          </Label>
                          <p>
                            Uses modes reported by Home Assistant. Review the change before
                            applying.
                          </p>
                        </div>
                        <div>
                          <select
                            id={`choice-${choice.entityId}`}
                            value={drafts[choice.entityId]?.value ?? choice.value ?? ""}
                            disabled={
                              planEngaged || !["live", "demo"].includes(controller.connection)
                            }
                            onChange={(event) => {
                              const value = event.target.value;
                              setSaved(false);
                              setDrafts((current) => {
                                const next = { ...current };
                                if (value === (current[choice.entityId]?.original ?? choice.value))
                                  delete next[choice.entityId];
                                else
                                  next[choice.entityId] = {
                                    value,
                                    original: current[choice.entityId]?.original ?? choice.value,
                                    label: choice.label,
                                    zone: zone?.name || "Room settings",
                                  };
                                return next;
                              });
                            }}
                          >
                            <option value="" disabled>
                              Select a mode
                            </option>
                            {choice.options.map((option) => (
                              <option key={option} value={option}>
                                {option}
                              </option>
                            ))}
                          </select>
                          {drafts[choice.entityId] && (
                            <p className="small muted">Currently {choice.value || "unavailable"}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}
              {zone && activeMode && (
                <label className="setpoint-mode-visibility">
                  <input
                    type="checkbox"
                    checked={showInactive}
                    onChange={(event) => setShowInactive(event.target.checked)}
                  />
                  Show targets for both steering modes
                </label>
              )}
              {!fields.length && !choices.length ? (
                <section className="panel">
                  <Empty
                    title="No editable settings available"
                    detail="This controller has not exposed editable number entities for this selection. Sensor readings cannot be edited."
                  />
                </section>
              ) : (
                shownGroups.map((group) => (
                  <section className="panel settings-group" key={group}>
                    <div className="settings-group-heading">
                      <span className="phase-marker">{group.match(/^P[0-3]/)?.[0] || "•"}</span>
                      <div>
                        <h3>{group}</h3>
                        <p>
                          {group.startsWith("P0")
                            ? "Morning preparation before ramp-up."
                            : group.startsWith("P1")
                              ? "Bring the substrate toward its daily target."
                              : group.startsWith("P2")
                                ? "Maintain moisture through the active window."
                                : group.startsWith("P3")
                                  ? "Emergency watering only. The controller determines the cutoff from live dryback."
                                  : "Configuration reported by the controller."}
                        </p>
                      </div>
                    </div>
                    <div className="setting-fields">
                      {visibleFields
                        .filter((field) => fieldGroup(field) === group)
                        .map((setting) => {
                          const draft = drafts[setting.entityId];
                          const error = draft ? invalid(setting, draft.value) : "";
                          const stale = draft && draft.original !== setting.value;
                          return (
                            <div
                              className={`setting-field ${draft ? "is-draft" : ""}`}
                              key={setting.entityId}
                            >
                              <div>
                                <Label htmlFor={`setting-${setting.entityId}`}>
                                  {setting.label}
                                  {draft && <span className="draft-dot" title="Unsaved draft" />}
                                </Label>
                                <p>
                                  {setting.description ||
                                    `Allowed range: ${setting.min}–${setting.max}${setting.unit ? ` ${setting.unit}` : ""}.`}
                                </p>
                                <span className="setting-limit">
                                  {setting.min}–{setting.max} {setting.unit} · step {setting.step}
                                </span>
                              </div>
                              <div className="setting-input">
                                <div>
                                  <Input
                                    id={`setting-${setting.entityId}`}
                                    type="number"
                                    min={setting.min}
                                    max={setting.max}
                                    step={setting.step}
                                    value={draft?.value ?? setting.value ?? ""}
                                    placeholder={setting.value === null ? "Unavailable" : undefined}
                                    aria-invalid={Boolean(error)}
                                    aria-describedby={`hint-${setting.entityId}`}
                                    disabled={
                                      planEngaged ||
                                      !["live", "demo"].includes(controller.connection)
                                    }
                                    onChange={(e) => edit(setting, e.target.value)}
                                  />
                                  <span>{setting.unit}</span>
                                </div>
                                <p
                                  id={`hint-${setting.entityId}`}
                                  className={error ? "field-error" : "small muted"}
                                >
                                  {error ||
                                    (stale
                                      ? `Controller now reports ${number(setting.value)}. Review before applying.`
                                      : draft
                                        ? `Currently ${number(setting.value)} ${setting.unit}`
                                        : "")}
                                </p>
                              </div>
                            </div>
                          );
                        })}
                    </div>
                  </section>
                ))
              )}
            </div>
            <aside
              className={`setpoint-preview ${expanded ? "is-expanded" : ""}`}
              aria-label="Setpoint planning preview"
            >
              <div className="setpoint-preview-context">
                <div>
                  <strong>
                    {controller.room.room.name} ·{" "}
                    {controller.room.zones.find((z) => z.id === previewZoneId)?.name ?? "No zone"}
                  </strong>
                  <span>
                    {preview.readOnly
                      ? "Active grow plan · read only"
                      : `${preview.draft.mode ?? "Mode unavailable"} · local draft`}
                  </span>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="setpoint-expand"
                  onClick={() => setExpanded(!expanded)}
                  aria-expanded={expanded}
                >
                  {expanded ? "Compact preview" : "Expand preview"}
                </Button>
              </div>
              {zoneId === "room" && (
                <div className="setpoint-preview-zone">
                  <Label htmlFor="setpoint-preview-zone">Preview room changes in</Label>
                  <select
                    id="setpoint-preview-zone"
                    value={previewZoneId ?? ""}
                    onChange={(event) => setRoomPreviewZone(Number(event.target.value))}
                  >
                    {controller.room.zones.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                  <p>Zone-specific values take precedence over room defaults.</p>
                </div>
              )}
              <PlanningCurve
                parameters={preview.draft.parameters}
                lightsOn={preview.draft.lightsOn}
                lightsOff={preview.draft.lightsOff}
                baseline={preview.readOnly ? undefined : preview.saved}
                bounds={preview.bounds}
                showEditors={false}
                selectedPhase={/^P[0-3]$/.test(phase) ? (phase as PlanningPhaseId) : undefined}
                description={
                  preview.readOnly
                    ? "Current grow-plan targets. Manual fallback controls are read only."
                    : "Drag a target or adjust the controls beside this graph. Nothing is written until you review and apply."
                }
                onChange={
                  canEdit
                    ? (key, value) => {
                        const setting = preview.fields[key];
                        if (setting) edit(setting, String(value));
                      }
                    : undefined
                }
              />
              <p className="setpoint-preview-note">
                Whole-day setpoint illustration, not measured or forecast sensor data. The P3
                boundary is shown at lights-off; the engine may stop earlier based on measured
                dryback. P2 can also adjust for EC and safety limits.
              </p>
              {preview.notes.map((note) => (
                <p className="setpoint-preview-note" key={note}>
                  {note}
                </p>
              ))}
              {preview.issues.length > 0 && (
                <div className="workspace-message" role="status">
                  {preview.issues.map((issue) => (
                    <p key={issue}>{issue}</p>
                  ))}
                </div>
              )}
              {previewZoneId !== undefined && (
                <div className="setpoint-water">
                  <WaterDelivery
                    controller={controller}
                    zoneId={previewZoneId}
                    parameters={preview.draft.parameters}
                    fieldOverrides={preview.fieldOverrides}
                  />
                </div>
              )}
            </aside>
          </div>
        </div>
      </div>
      {Object.keys(drafts).length > 0 && (
        <div className="draft-bar" role="status">
          <div>
            <strong>
              {Object.keys(drafts).length} unsaved{" "}
              {Object.keys(drafts).length === 1 ? "change" : "changes"}
            </strong>
            <span>
              {errors.length
                ? "Fix invalid values before review."
                : "Drafts are local to this tab until applied."}
            </span>
          </div>
          <Button
            variant="ghost"
            onClick={() => {
              setDrafts({});
              setSaved(false);
            }}
          >
            Discard draft
          </Button>
          <Button
            disabled={
              Boolean(errors.length) ||
              !items.length ||
              planEngaged ||
              !["live", "demo"].includes(controller.connection)
            }
            onClick={() => setReview(true)}
          >
            Review changes <ArrowRight size={16} />
          </Button>
        </div>
      )}
      <ReviewDialog
        open={review}
        onOpenChange={setReview}
        controller={controller}
        items={items}
        onApplied={(applied) => {
          setDrafts((current) =>
            Object.fromEntries(Object.entries(current).filter(([id]) => !applied.includes(id))),
          );
          if (applied.length) setSaved(true);
        }}
      />
    </>
  );
}
