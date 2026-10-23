import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Check, Download, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, ReviewDialog, number, type Page, type ReviewItem } from "@/components/dashboard";
import { WorkspaceHeading } from "@/components/irrigation-workspace";
import { CanonicalControls } from "@/components/canonical-controls";
import type { ReactNode } from "react";
import type { Choice, Controller, Setting } from "@/lib/types";
import { PlanningCurve } from "@/components/planning-curve";
import { publishedDryback } from "@/lib/published";
import { buildSetpointPreview, validateSetpoint } from "@/lib/setpoint-preview";
import { smoothRecorded } from "@/lib/planning-curve";
import { useSensorContext } from "@/components/sensor-context";
import { AutoSetpointsControl, AutoZoneChip } from "@/components/room-controls";
import { SettingRow } from "@/components/setting-row";
import { UiTip } from "@/components/info-tip";
import { managedBy } from "@/lib/auto-setpoints";
import { jevIds, parseJevSetpoints, readJev } from "@/lib/jev";
import { setpointParam } from "@/lib/sensor-context";
import { settingWords } from "@/lib/setting-words";
import {
  jevChip,
  planSteering,
  SETUP_GROUPS,
  steeringConsequence,
  TARGET_GROUPS,
} from "@/lib/targets";
import {
  exportTargets,
  loadTargets,
  readTargets,
  targetsFileName,
  type LoadedTargets,
} from "@/lib/targets-file";
import "./setpoint-preview.css";
import "./targets.css";

function download(text: string, name: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
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

/** Plan › Targets: a zone's targets as one compact table by phase, each with the AI assistant's range where the AI assistant
 * manages it, and the day they make beside it while you edit. Nothing is written until reviewed. */
export function Strategy({
  controller,
  drafts,
  setDrafts,
  selectedZone,
  navigate,
  embedded = false,
  active = true,
  renderCurve,
  onCanonicalDirtyChange,
}: {
  controller: Controller;
  drafts: Drafts;
  setDrafts: React.Dispatch<React.SetStateAction<Drafts>>;
  selectedZone?: number | "room";
  embedded?: boolean;
  active?: boolean;
  renderCurve?: (curve: ReactNode) => ReactNode;
  onCanonicalDirtyChange?: (dirty: boolean) => void;
  navigate: (page: Page) => void;
}) {
  const { room, states } = controller;
  const [zoneId, setZoneId] = useState<string>(
    selectedZone === undefined ? String(room.zones[0]?.id ?? "room") : String(selectedZone),
  );
  const [review, setReview] = useState(false);
  const [saved, setSaved] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [roomPreviewZone, setRoomPreviewZone] = useState(room.zones[0]?.id);
  // What the last targets file loaded into the draft, or why it could not be read.
  const [loaded, setLoaded] = useState<{ from: string; result: LoadedTargets } | null>(null);
  const [fileError, setFileError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (selectedZone !== undefined) setZoneId(String(selectedZone));
    if (typeof selectedZone === "number") setRoomPreviewZone(selectedZone);
  }, [selectedZone]);
  const planEngaged = room.strategy.engaged;
  const connected = ["live", "demo"].includes(controller.connection);
  const canEdit = !planEngaged && connected;
  const allSettings = room.settings;
  const zone = room.zones.find((z) => String(z.id) === zoneId);
  const previewZoneId =
    zone?.id ?? room.zones.find((z) => z.id === roomPreviewZone)?.id ?? room.zones[0]?.id;
  const preview = buildSetpointPreview(room, states, previewZoneId ?? 0, drafts);
  const prefix = room.room.prefix;
  const setpoints = zone ? parseJevSetpoints(states[jevIds(prefix).zone(zone.id)]) : null;
  const jevManaged = room.zones.some(
    (item) => parseJevSetpoints(states[jevIds(prefix).zone(item.id)]) !== null,
  );
  const choices = (room.choices || []).filter((choice) =>
    zoneId === "room" ? choice.zoneId === undefined : String(choice.zoneId) === zoneId,
  );
  // The table's settings, as the steering mode resolves them; the other mode's own targets; and
  // what is neither a target nor Setup's (hardware, substrate, safety).
  const tableIds = new Set(
    zone
      ? TARGET_GROUPS.flatMap((group) => group.rows.map((row) => preview.fields[row.key]?.entityId))
      : [],
  );
  const own = zone ? zone.fields : allSettings.filter((field) => field.zoneId === undefined);
  const otherMode =
    preview.draft.mode === "Vegetative"
      ? "generative"
      : preview.draft.mode === "Generative"
        ? "vegetative"
        : null;
  const otherFields = own.filter((field) =>
    otherMode
      ? new RegExp(
          `_(${otherMode}_dryback_target|ec_target_${otherMode.slice(0, 3)}_p[012])$`,
        ).test(field.entityId)
      : false,
  );
  /** The other mode's value of a mode-dependent target, shown muted beside the one in use. */
  const otherValue = (key: string) => {
    const suffix =
      key === "dryback_target"
        ? `_${otherMode}_dryback_target`
        : /^ec_target_p[012]$/.test(key)
          ? `_ec_target_${otherMode?.slice(0, 3)}_${key.slice(-2)}`
          : null;
    const field = suffix ? otherFields.find((item) => item.entityId.endsWith(suffix)) : undefined;
    const value = field ? (drafts[field.entityId]?.value ?? field.value) : null;
    return value === null || value === "" ? null : `${number(Number(value))} ${field?.unit ?? ""}`;
  };
  const planSteers = zone
    ? planSteering(states[`sensor.crop_steering_${prefix}strategy_plan`]?.attributes, zone.id)
    : null;
  const step = review ? 1 : saved && !Object.keys(drafts).length ? 2 : 0;
  const restFields = own.filter(
    (field) =>
      !tableIds.has(field.entityId) &&
      !otherFields.includes(field) &&
      !SETUP_GROUPS.includes(field.group) &&
      !/_(vegetative|generative)_dryback_target$|_ec_target_(veg|gen)_p[012]$/.test(field.entityId),
  );
  // Recorded probe behaviour for the zone being previewed: the dark lines on the day, and the
  // hints under a field being edited.
  const sensorZone = room.zones.find((z) => z.id === previewZoneId);
  const sensor = useSensorContext(controller, sensorZone, connected && active);
  // The plan graph redraws on every drag step, so the recorder dump is thinned once per load.
  const recorded = useMemo(
    () => ({
      vwc: smoothRecorded(sensor.vwc.points, 10),
      ec: smoothRecorded(sensor.ec.points, 20),
      now: sensor.now,
      timeZone: controller.timeZone,
    }),
    [sensor.vwc.points, sensor.ec.points, sensor.now, controller.timeZone],
  );
  const supervisors = room.zones.map((z) => z.auto);
  const errors = Object.entries(drafts)
    .map(([id, draft]) => {
      const setting = allSettings.find((s) => s.entityId === id);
      const choice = room.choices.find((c) => c.entityId === id);
      return setting
        ? validateSetpoint(setting, draft.value)
        : choice
          ? choice.options.includes(draft.value)
            ? ""
            : "Select an available mode."
          : "A draft setting is no longer available. Discard it before continuing.";
    })
    .filter(Boolean);
  const items: ReviewItem[] = Object.entries(drafts).flatMap<ReviewItem>(([id, draft]) => {
    const setting = allSettings.find((s) => s.entityId === id);
    const choice = room.choices.find((c) => c.entityId === id);
    if (choice && choice.options.includes(draft.value))
      return [
        {
          change: { entityId: id, value: draft.value },
          label: `${draft.zone} · ${draft.label}`,
          before: choice.value || "Unavailable",
          after: draft.value,
        },
      ];
    return !setting || validateSetpoint(setting, draft.value)
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
  const zoneLabel = (id: number | undefined) =>
    id === undefined
      ? "Room settings"
      : (room.zones.find((item) => item.id === id)?.name ?? `Zone ${id}`);
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
          zone: zoneLabel(setting.zoneId),
        };
      return next;
    });
  }
  function choose(choice: Choice, value: string) {
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
  }
  function exportFile() {
    const now = new Date();
    const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    download(exportTargets(room, now.toISOString()), targetsFileName(room.room.name, date));
  }
  async function importFile(file: File | undefined) {
    if (fileRef.current) fileRef.current.value = "";
    if (!file) return;
    setLoaded(null);
    setFileError("");
    try {
      const targets = readTargets(await file.text());
      const result = loadTargets(targets, room);
      setSaved(false);
      setDrafts(result.drafts);
      setLoaded({ from: `${targets.room || "another room"}’s targets`, result });
    } catch (e) {
      setFileError(e instanceof Error ? e.message : String(e));
    }
  }
  /** One setting as a row, with the AI assistant's range and the probe's hints. */
  const row = (setting: Setting, label: string, unit: string, other?: string | null) => {
    const param = setpointParam(setting.entityId, prefix);
    return (
      <SettingRow
        key={setting.entityId}
        setting={setting}
        label={label}
        unit={unit}
        draft={drafts[setting.entityId]}
        prefix={prefix}
        sensor={sensor}
        learnedPeak={sensorZone?.auto?.learnedPeak}
        chip={param ? jevChip(setpoints, param, unit) : null}
        auto={managedBy(supervisors, setting.entityId)}
        readOnly={planEngaged}
        disabled={!canEdit}
        other={other}
        onEdit={edit}
      />
    );
  };
  const plain = (setting: Setting) => {
    const param = setpointParam(setting.entityId, prefix);
    const words = param ? settingWords(param) : undefined;
    return row(setting, words?.label ?? setting.label, setting.unit);
  };
  const curve = (
    <aside
      className={`setpoint-preview ${expanded ? "is-expanded" : ""}`}
      aria-label="Setpoint preview"
    >
      <div className="setpoint-preview-context">
        <div>
          <strong>
            {room.room.name} · {room.zones.find((z) => z.id === previewZoneId)?.name ?? "No zone"}
          </strong>
          <span>
            {preview.readOnly
              ? "Armed grow plan · read only"
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
          <span className="label-with-tip">
            <label htmlFor="setpoint-preview-zone">Preview room changes in</label>
            <UiTip copyKey="preview room changes in" />
          </span>
          <select
            id="setpoint-preview-zone"
            value={previewZoneId ?? ""}
            onChange={(event) => setRoomPreviewZone(Number(event.target.value))}
          >
            {room.zones.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <p>Zone-specific values take precedence over room defaults.</p>
        </div>
      )}
      <PlanningCurve
        initialShowEc={embedded}
        recorded={recorded}
        retention={sensorZone?.auto?.gain}
        zoneName={sensorZone?.name}
        phase={sensorZone?.phase}
        ecBand={readJev(states, room.room.prefix).room?.stage?.poreEc ?? null}
        drybackPoints={readJev(states, room.room.prefix).room?.stage?.drybackPoints ?? null}
        dryback={sensorZone && publishedDryback(states, room.room.prefix, sensorZone.id)}
        parameters={preview.draft.parameters}
        lightsOn={preview.draft.lightsOn}
        lightsOff={preview.draft.lightsOff}
        baseline={preview.readOnly ? undefined : preview.saved}
        bounds={preview.bounds}
        showEditors={false}
        description={
          preview.readOnly
            ? "Today’s targets from the armed grow plan. Open Schedule to change the plan."
            : "Drag a target, or type it in the table. Nothing is written until you review and apply."
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
      {preview.notes.map((item) => (
        <p className="setpoint-preview-note" key={item}>
          {item}
        </p>
      ))}
      {preview.issues.length > 0 && (
        <div className="workspace-message" role="status">
          {preview.issues.map((issue) => (
            <p key={issue}>{issue}</p>
          ))}
        </div>
      )}
    </aside>
  );
  return (
    <>
      <WorkspaceHeading
        embedded={embedded}
        title="Current day"
        action={
          <div className="heading-actions">
            <AutoSetpointsControl controller={controller} jevManaged={jevManaged} />
            <Button
              variant="outline"
              onClick={exportFile}
              disabled={planEngaged || !allSettings.length}
              title={
                planEngaged
                  ? "While a grow plan is armed the room follows it: export the plan instead"
                  : "Save these targets to a file, both steering modes, for another room"
              }
            >
              <Download size={16} /> Export
            </Button>
            <Button
              variant="outline"
              onClick={() => fileRef.current?.click()}
              disabled={!canEdit || Object.keys(drafts).length > 0}
              title={
                Object.keys(drafts).length
                  ? "Review or discard your draft first"
                  : "Load a targets file into the draft, to review before anything changes"
              }
            >
              <Upload size={16} /> Import
            </Button>
            <UiTip copyKey="import targets" />
            <Button
              disabled={!items.length || Boolean(errors.length) || !canEdit}
              onClick={() => setReview(true)}
            >
              Review {Object.keys(drafts).length || ""}{" "}
              {Object.keys(drafts).length === 1 ? "change" : "changes"} <ArrowRight size={16} />
            </Button>
          </div>
        }
      />
      {planEngaged && (
        <div className="workspace-message">
          The armed grow plan sets these targets. Change them in its schedule.{" "}
          <Button asChild variant="outline">
            <a href="#/plan/schedule">Open schedule</a>
          </Button>
        </div>
      )}
      <input
        ref={fileRef}
        type="file"
        accept="application/json,.json"
        className="sr-only"
        aria-label="Import targets"
        onChange={(e) => void importFile(e.target.files?.[0])}
      />
      {fileError && (
        <div className="workspace-message error" role="alert">
          {fileError}
        </div>
      )}
      {loaded && (
        <div className="workspace-message targets-loaded" role="status">
          <p>
            <strong>
              {Object.keys(loaded.result.drafts).length
                ? `Loaded ${Object.keys(loaded.result.drafts).length} ${
                    Object.keys(loaded.result.drafts).length === 1 ? "change" : "changes"
                  } from ${loaded.from}.`
                : `Nothing to change: ${loaded.from} match this room’s.`}
            </strong>{" "}
            {Object.keys(loaded.result.drafts).length > 0 &&
              "They’re in your draft: nothing changes until you review and apply them."}
          </p>
          {loaded.result.zoneMismatch && <p>{loaded.result.zoneMismatch}</p>}
          {loaded.result.left.length > 0 && (
            <p>Left as this room has them: {loaded.result.left.join(", ")}.</p>
          )}
          {loaded.result.rounded.length > 0 && (
            <p>Rounded to this room’s steps: {loaded.result.rounded.join("; ")}.</p>
          )}
          {loaded.result.skipped.length > 0 && <p>Skipped: {loaded.result.skipped.join("; ")}.</p>}
          {loaded.result.missingZones.length > 0 && (
            <p>Not in this room: {loaded.result.missingZones.join(", ")}.</p>
          )}
        </div>
      )}
      {!planEngaged && (
        <ol className="workflow-steps" aria-label="Steps to change targets">
          {["Edit draft", "Review changes", "Apply & verify"].map((label, index) => (
            <li key={label} aria-current={step === index ? "step" : undefined}>
              <i>{index + 1}</i>
              {label}
            </li>
          ))}
        </ol>
      )}
      {!embedded && (
        <nav className="zone-switcher targets-zones" aria-label="Targets for">
          {room.zones.map((item) => {
            const count = Object.values(drafts).filter((d) => d.zone === item.name).length;
            return (
              <button
                type="button"
                key={item.id}
                aria-current={zoneId === String(item.id) ? "page" : undefined}
                onClick={() => setZoneId(String(item.id))}
              >
                {item.name}
                {count > 0 && <i className="nav-draft-count">{count}</i>}
              </button>
            );
          })}
          <button
            type="button"
            aria-current={zoneId === "room" ? "page" : undefined}
            onClick={() => setZoneId("room")}
          >
            Room
          </button>
        </nav>
      )}
      {saved && (
        <div className="success-banner" role="status">
          <Check size={18} />
          Changes applied and verified by controller readback.
        </div>
      )}
      <div className="setpoint-editor-grid targets-grid">
        <section className="panel targets-panel" aria-labelledby="targets-title">
          <div className="panel-heading">
            <div>
              <h2 id="targets-title">{zone?.name || "Room settings"}</h2>
              <p>
                {zone
                  ? preview.draft.mode
                    ? `${preview.draft.mode} steering: its dryback and EC targets below.`
                    : "Steering mode unavailable."
                  : "The room’s day: a zone’s own value, where it has one, takes precedence."}
              </p>
              {zone?.auto && <AutoZoneChip status={zone.auto} />}
            </div>
          </div>
          {!planEngaged &&
            choices.map((choice) => (
              <div className="targets-choice" key={choice.entityId}>
                <label htmlFor={`choice-${choice.entityId}`}>
                  {choice.label}
                  {drafts[choice.entityId] && <span className="draft-dot" />}
                </label>
                <select
                  id={`choice-${choice.entityId}`}
                  value={drafts[choice.entityId]?.value ?? choice.value ?? ""}
                  disabled={!canEdit}
                  onChange={(event) => choose(choice, event.target.value)}
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
                  <span className="small muted">Currently {choice.value || "unavailable"}</span>
                )}
                {zone && /_steering_mode$/.test(choice.entityId) && preview.draft.mode && (
                  <p className="targets-consequence">
                    {steeringConsequence(
                      preview.draft.mode,
                      preview.draft.parameters.dryback_target,
                    )}
                  </p>
                )}
              </div>
            ))}
          {zone && planEngaged && (
            <div className="targets-choice">
              <p>
                Steering comes from the grow plan{planSteers ? ` (${planSteers})` : ""}. Change it
                in Schedule.
              </p>
            </div>
          )}
          {zone && !planEngaged && (
            <table className="targets-table">
              {otherMode && (
                <thead>
                  <tr>
                    <th scope="col">Setting</th>
                    <th scope="col">{preview.draft.mode} · in use</th>
                    <th scope="col" className="targets-other">
                      {otherMode === "generative" ? "Generative" : "Vegetative"}
                    </th>
                    <th scope="col">
                      <span className="sr-only">Ranges</span>
                    </th>
                  </tr>
                </thead>
              )}
              {TARGET_GROUPS.map((group) => (
                <tbody key={group.phase}>
                  <tr className="targets-phase">
                    <th colSpan={otherMode ? 4 : 3} scope="colgroup">
                      <span className="pill" data-phase={group.phase}>
                        {group.phase}
                      </span>{" "}
                      {group.title.split(" · ")[1]}
                    </th>
                  </tr>
                  {group.rows.map((item) => {
                    const setting = preview.fields[item.key];
                    return setting ? (
                      row(
                        setting,
                        item.label,
                        setting.unit || item.unit,
                        otherMode ? otherValue(item.key) : undefined,
                      )
                    ) : (
                      <tr key={item.key} className="targets-missing">
                        <th scope="row">{item.label}</th>
                        <td colSpan={otherMode ? 3 : 2}>Not reported by this controller</td>
                      </tr>
                    );
                  })}
                </tbody>
              ))}
            </table>
          )}
          {zone && planEngaged && preview.source === "unavailable-plan" && (
            <p className="workspace-message targets-unavailable">
              Scheduled targets are unavailable. Reconnect to verify the active schedule.
            </p>
          )}
          {zone && planEngaged && (
            <table className="targets-table">
              {TARGET_GROUPS.map((group) => (
                <tbody key={group.phase}>
                  <tr className="targets-phase">
                    <th colSpan={3} scope="colgroup">
                      <span className="pill" data-phase={group.phase}>
                        {group.phase}
                      </span>{" "}
                      {group.title.split(" · ")[1]}
                    </th>
                  </tr>
                  {group.rows.map((item) => (
                    <tr key={item.key}>
                      <th scope="row">{item.label}</th>
                      <td className="targets-input">
                        <strong>
                          {number(preview.draft.parameters[item.key] ?? null, item.digits ?? 1)}
                        </strong>
                        <span className="targets-unit">{item.unit}</span>
                      </td>
                      <td />
                    </tr>
                  ))}
                </tbody>
              ))}
            </table>
          )}
          {!planEngaged && restFields.length > 0 && (
            <div className="targets-rest">
              {zone && <h3>Other settings</h3>}
              <table className="targets-table">
                <tbody>{restFields.map(plain)}</tbody>
              </table>
            </div>
          )}
          {!zone && !restFields.length && !choices.length && (
            <Empty
              title="No room targets"
              detail="This room’s shared settings are its hardware and safety limits, in Equipment › Setup."
            />
          )}
          <p className="targets-setup-link">
            Substrate, plants, drippers, flow and safety limits are set up in Equipment.{" "}
            <Button variant="ghost" size="sm" onClick={() => navigate("equipment/setup")}>
              Equipment › Setup <ArrowRight size={15} aria-hidden="true" />
            </Button>
          </p>
        </section>
        {renderCurve ? renderCurve(curve) : curve}
      </div>
      <CanonicalControls
        controller={controller}
        owner="irrigation"
        onDirtyChange={onCanonicalDirtyChange}
      />
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
              setLoaded(null);
            }}
          >
            Discard draft
          </Button>
          <Button
            disabled={Boolean(errors.length) || !items.length || !canEdit}
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
