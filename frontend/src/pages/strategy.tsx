import { useEffect, useState } from "react";
import { ArrowRight, Check, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Empty, Heading, ReviewDialog, number, type ReviewItem } from "@/components/dashboard";
import type { Controller, Setting } from "@/lib/types";

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
  const groups = [...new Set(fields.map((field) => field.group))];
  const invalid = (setting: Setting, raw: string) =>
    !raw.trim() || !Number.isFinite(Number(raw))
      ? "Enter a number."
      : Number(raw) < setting.min || Number(raw) > setting.max
        ? `Use a value between ${setting.min} and ${setting.max}.`
        : setting.step > 0 &&
            Math.abs(
              (Number(raw) - setting.min) / setting.step -
                Math.round((Number(raw) - setting.min) / setting.step),
            ) > 0.00001
          ? `Use increments of ${setting.step} from ${setting.min}.`
          : "";
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
          zone: zone?.name || "Room settings",
        };
      return next;
    });
  }
  return (
    <>
      <Heading
        title="Manual setpoints"
        description="Advanced controller settings, organized by zone and phase. Every change stays in draft until reviewed."
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
      <div className="strategy-layout">
        <aside className="strategy-zone-picker">
          <span className="eyebrow">Configure</span>
          {controller.room.zones.map((z) => (
            <button
              key={z.id}
              className={zoneId === String(z.id) ? "selected" : ""}
              onClick={() => setZoneId(String(z.id))}
            >
              <span>{z.name}</span>
              <span className="small">
                {Object.values(drafts).filter((d) => d.zone === z.name).length || z.phase}
              </span>
            </button>
          ))}
          <button className={zoneId === "room" ? "selected" : ""} onClick={() => setZoneId("room")}>
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
          {choices.length > 0 && (
            <section className="panel settings-group">
              <div className="settings-group-heading">
                <span className="phase-marker">
                  <SlidersHorizontal size={16} />
                </span>
                <div>
                  <h3>Steering mode</h3>
                  <p>Choose an existing controller mode for this selection.</p>
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
                        Uses modes reported by Home Assistant. Review the change before applying.
                      </p>
                    </div>
                    <div>
                      <select
                        id={`choice-${choice.entityId}`}
                        value={drafts[choice.entityId]?.value ?? choice.value ?? ""}
                        disabled={planEngaged || !["live", "demo"].includes(controller.connection)}
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
          {!fields.length && !choices.length ? (
            <section className="panel">
              <Empty
                title="No editable settings available"
                detail="This controller has not exposed editable number entities for this selection. Sensor readings cannot be edited."
              />
            </section>
          ) : (
            groups.map((group) => (
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
                              ? "Manage the overnight dryback window."
                              : "Configuration reported by the controller."}
                    </p>
                  </div>
                </div>
                <div className="setting-fields">
                  {fields
                    .filter((field) => field.group === group)
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
                                  planEngaged || !["live", "demo"].includes(controller.connection)
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
