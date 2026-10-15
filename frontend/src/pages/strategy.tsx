import { useEffect, useMemo, useState } from "react";
import { ArrowRight, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Empty,
  Heading,
  ReviewDialog,
  number,
  type Page,
  type ReviewItem,
} from "@/components/dashboard";
import type { Choice, Controller, Setting } from "@/lib/types";
import { PlanningCurve } from "@/components/planning-curve";
import { buildSetpointPreview, validateSetpoint } from "@/lib/setpoint-preview";
import { smoothRecorded } from "@/lib/planning-curve";
import { useSensorContext } from "@/components/sensor-context";
import { AutoSetpointsControl, AutoZoneChip } from "@/components/room-controls";
import { SettingRow } from "@/components/setting-row";
import { managedBy } from "@/lib/auto-setpoints";
import { jevIds, parseJevSetpoints } from "@/lib/jev";
import { setpointParam } from "@/lib/sensor-context";
import { settingWords } from "@/lib/setting-words";
import { jevChip, SETUP_GROUPS, TARGET_GROUPS } from "@/lib/targets";
import "./setpoint-preview.css";
import "./targets.css";

export type Drafts = Record<
  string,
  {
    value: string;
    original: number | string | null;
    label: string;
    zone: string;
  }
>;

/** Plan › Targets: a zone's targets as one compact table by phase, each with Jev's range where Jev
 * manages it, and the day they make beside it while you edit. Nothing is written until reviewed. */
export function Strategy({
  controller,
  drafts,
  setDrafts,
  selectedZone,
  navigate,
}: {
  controller: Controller;
  drafts: Drafts;
  setDrafts: React.Dispatch<React.SetStateAction<Drafts>>;
  selectedZone?: number;
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
  useEffect(() => {
    if (selectedZone !== undefined) setZoneId(String(selectedZone));
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
  const sensor = useSensorContext(controller, sensorZone, connected);
  // The plan graph redraws on every drag step, so the recorder dump is thinned once per load.
  const recorded = useMemo(
    () => ({
      vwc: smoothRecorded(sensor.vwc.points, 10),
      ec: smoothRecorded(sensor.ec.points, 20),
      now: sensor.now,
    }),
    [sensor.vwc.points, sensor.ec.points, sensor.now],
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
  /** One setting as a row, with Jev's range and the probe's hints. */
  const row = (setting: Setting, label: string, unit: string) => {
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
        onEdit={edit}
      />
    );
  };
  const plain = (setting: Setting) => {
    const param = setpointParam(setting.entityId, prefix);
    const words = param ? settingWords(param) : undefined;
    return row(setting, words?.label ?? setting.label, setting.unit);
  };
  return (
    <>
      <Heading
        title="Targets"
        action={
          <div className="heading-actions">
            <AutoSetpointsControl controller={controller} jevManaged={jevManaged} />
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
              </div>
            ))}
          {zone && !planEngaged && (
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
                  {group.rows.map((item) => {
                    const setting = preview.fields[item.key];
                    return setting ? (
                      row(setting, item.label, setting.unit || item.unit)
                    ) : (
                      <tr key={item.key} className="targets-missing">
                        <th scope="row">{item.label}</th>
                        <td colSpan={2}>Not reported by this controller</td>
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
          {!planEngaged && otherMode && otherFields.length > 0 && (
            <details className="targets-more">
              <summary>
                {otherMode === "generative" ? "Generative" : "Vegetative"} targets: the P3 dryback
                and EC targets used while the zone is steered {otherMode}
              </summary>
              <table className="targets-table">
                <tbody>{otherFields.map(plain)}</tbody>
              </table>
            </details>
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
        <aside
          className={`setpoint-preview ${expanded ? "is-expanded" : ""}`}
          aria-label="Setpoint planning preview"
        >
          <div className="setpoint-preview-context">
            <div>
              <strong>
                {room.room.name} ·{" "}
                {room.zones.find((z) => z.id === previewZoneId)?.name ?? "No zone"}
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
              <label htmlFor="setpoint-preview-zone">Preview room changes in</label>
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
            recorded={recorded}
            retention={sensorZone?.auto?.gain}
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
          <p className="setpoint-preview-note">
            Blue and pink are your targets for the whole day; the dark lines are what this zone’s
            probe recorded, today and on earlier days. Nothing is forecast. The P3 boundary is shown
            at lights-off; the engine may stop earlier on measured dryback. P2 can also adjust for
            EC and safety limits.
          </p>
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
