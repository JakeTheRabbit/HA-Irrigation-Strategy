import { useEffect, useLayoutEffect, useState } from "react";
import { ArrowRight, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ReviewDialog, number, type ReviewItem } from "@/components/dashboard";
import { useSensorContext } from "@/components/sensor-context";
import { SettingRow } from "@/components/setting-row";
import { WaterDelivery } from "@/components/water-delivery";
import { calibrateDripper } from "@/lib/catch-test";
import { buildSetpointPreview, validateSetpoint } from "@/lib/setpoint-preview";
import { setpointParam } from "@/lib/sensor-context";
import { GROUP_HELP, settingWords } from "@/lib/setting-words";
import type { Controller, Setting } from "@/lib/types";
import { waterParameters } from "@/lib/water-delivery";
import "./setting-row.css";

type Drafts = Record<string, { value: string; original: number | string | null }>;

/** Equipment › Setup: the controller's own numbers for what the substrate holds, what turns a
 * shot's percentage into litres and seconds, and the limits that hold or add watering, per zone and
 * for the room; and the water a shot delivers. Plan › Targets keeps the phase targets. Each change
 * is reviewed before it is written. */
export function ControllerSettings({
  controller,
  onDirtyChange,
}: {
  controller: Controller;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { room, states } = controller;
  const [zoneId, setZoneId] = useState(String(room.zones[0]?.id ?? "room"));
  const [drafts, setDrafts] = useState<Drafts>({});
  const [review, setReview] = useState(false);
  const [saved, setSaved] = useState(false);
  // Water & calibration: a catch test tried in the calculation only, never written.
  const [catchMl, setCatchMl] = useState(""),
    [catchMinutes, setCatchMinutes] = useState(""),
    [useCatchFlow, setUseCatchFlow] = useState(false);
  useEffect(() => setUseCatchFlow(false), [zoneId]);
  const dirty = Object.keys(drafts).length > 0;
  useLayoutEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  const zone = room.zones.find((item) => String(item.id) === zoneId);
  const own = (
    zone ? zone.fields : room.settings.filter((field) => field.zoneId === undefined)
  ).filter((field) => ["Substrate", "Hardware sizing", "Safety"].includes(field.group));
  const connected = ["live", "demo"].includes(controller.connection);
  // What the zone's probe recorded: full saturation's suggestion (a learned or typical peak).
  const sensor = useSensorContext(controller, zone, connected);
  const preview = zone ? buildSetpointPreview(room, states, zone.id, drafts) : null;
  const configuredFlow = zone ? waterParameters(controller, zone.id).dripper_flow_rate : null;
  const catchFlow =
    catchMl.trim() && catchMinutes.trim()
      ? calibrateDripper(Number(catchMl), Number(catchMinutes))
      : null;
  // The controller's water today over its shots today: the day's mean shot, in litres.
  const meanShot =
    zone && zone.water.value !== null && zone.shots.value !== null && zone.shots.value > 0
      ? zone.water.value / zone.shots.value
      : null;
  const label = (setting: Setting) => {
    const param = setpointParam(setting.entityId, room.room.prefix);
    return (param && settingWords(param)?.label) || setting.label;
  };
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
        };
      return next;
    });
  }
  const errors = Object.entries(drafts).filter(([id, draft]) => {
    const setting = room.settings.find((item) => item.entityId === id);
    return !setting || validateSetpoint(setting, draft.value);
  });
  const items: ReviewItem[] = Object.entries(drafts).flatMap(([id, draft]) => {
    const setting = room.settings.find((item) => item.entityId === id);
    if (!setting || validateSetpoint(setting, draft.value)) return [];
    const where =
      setting.zoneId === undefined
        ? "Room"
        : (room.zones.find((item) => item.id === setting.zoneId)?.name ?? `Zone ${setting.zoneId}`);
    return [
      {
        change: { entityId: id, value: Number(draft.value) },
        label: `${where} · ${label(setting)}`,
        before: `${number(setting.value)} ${setting.unit}`,
        after: `${number(Number(draft.value))} ${setting.unit}`,
      },
    ];
  });
  const group = (name: string) => own.filter((field) => field.group === name);
  const rows = (fields: Setting[]) =>
    fields.map((setting) => (
      <SettingRow
        key={setting.entityId}
        setting={setting}
        label={label(setting)}
        unit={setting.unit}
        draft={drafts[setting.entityId]}
        prefix={room.room.prefix}
        sensor={zone ? sensor : null}
        learnedPeak={zone?.auto?.learnedPeak}
        disabled={!connected}
        onEdit={edit}
      />
    ));
  return (
    <section
      className="panel workspace-card controller-settings"
      aria-labelledby="controller-settings-title"
    >
      <div className="workspace-section-heading">
        <div>
          <h2 id="controller-settings-title">
            {room.room.name}: substrate, sizing and safety limits
          </h2>
          <p className="muted">
            The numbers the controller works with now, per zone and for the room. Each change is
            reviewed before it is written.
          </p>
        </div>
        <div className="workspace-actions">
          {dirty && (
            <Button
              variant="ghost"
              onClick={() => {
                setDrafts({});
                setSaved(false);
              }}
            >
              Discard draft
            </Button>
          )}
          <Button
            disabled={!items.length || errors.length > 0 || !connected}
            onClick={() => setReview(true)}
          >
            Review {Object.keys(drafts).length || ""}{" "}
            {Object.keys(drafts).length === 1 ? "change" : "changes"} <ArrowRight size={16} />
          </Button>
        </div>
      </div>
      <nav className="zone-switcher controller-settings-zones" aria-label="Settings for">
        {room.zones.map((item) => (
          <button
            type="button"
            key={item.id}
            aria-current={zoneId === String(item.id) ? "page" : undefined}
            onClick={() => setZoneId(String(item.id))}
          >
            {item.name}
          </button>
        ))}
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
      {!own.length ? (
        <p className="muted small">The controller reports no such settings for this selection.</p>
      ) : (
        <>
          {["Substrate", "Hardware sizing"].map(
            (name) =>
              group(name).length > 0 && (
                <div className="controller-settings-group" key={name}>
                  <h3>{name}</h3>
                  <p className="small muted">{GROUP_HELP[name]}</p>
                  <table className="targets-table">
                    <tbody>{rows(group(name))}</tbody>
                  </table>
                </div>
              ),
          )}
          {group("Safety").length > 0 && (
            <details className="controller-settings-group controller-settings-safety">
              <summary>Safety limits: {GROUP_HELP.Safety.toLowerCase()}</summary>
              <table className="targets-table">
                <tbody>{rows(group("Safety"))}</tbody>
              </table>
            </details>
          )}
        </>
      )}
      {zone && preview && (
        <details className="setpoint-water controller-settings-water">
          <summary>Water & calibration: what a shot delivers, and a catch test</summary>
          <WaterDelivery
            controller={controller}
            zoneId={zone.id}
            parameters={preview.draft.parameters}
            fieldOverrides={
              useCatchFlow && catchFlow !== null
                ? { ...preview.fieldOverrides, dripper_flow_rate: catchFlow }
                : preview.fieldOverrides
            }
          />
          {useCatchFlow && (
            <p className="notice-inline">Using your catch-test flow in this calculation only.</p>
          )}
          <div className="calibration">
            <h3>Catch-test calibration</h3>
            <p className="small muted">
              Collect water from a representative dripper for a measured time, and enter what one
              dripper gave.
            </p>
            <div className="calibration-fields">
              <div>
                <Label htmlFor="catch-volume">Collected water per dripper · mL</Label>
                <Input
                  id="catch-volume"
                  type="number"
                  min="0"
                  step="1"
                  placeholder="e.g. 200"
                  value={catchMl}
                  onChange={(event) => {
                    setCatchMl(event.target.value);
                    setUseCatchFlow(false);
                  }}
                />
              </div>
              <div>
                <Label htmlFor="catch-time">Collection time · minutes</Label>
                <Input
                  id="catch-time"
                  type="number"
                  min="0"
                  step="0.1"
                  placeholder="e.g. 3"
                  value={catchMinutes}
                  onChange={(event) => {
                    setCatchMinutes(event.target.value);
                    setUseCatchFlow(false);
                  }}
                />
              </div>
              <div className="calibration-result">
                <span>Estimated flow per dripper</span>
                <strong>
                  {catchFlow === null ? "—" : number(catchFlow, 2)}{" "}
                  <small>{catchFlow !== null ? "L/h" : ""}</small>
                </strong>
                {catchFlow !== null && configuredFlow !== null && configuredFlow > 0 && (
                  <small>
                    {number(Math.abs(((catchFlow - configuredFlow) / configuredFlow) * 100), 1)}%{" "}
                    {catchFlow < configuredFlow ? "below" : "above"} the configured{" "}
                    {number(configuredFlow, 2)} L/h
                  </small>
                )}
              </div>
            </div>
            <div className="calibration-actions">
              <Button
                variant="outline"
                disabled={catchFlow === null}
                onClick={() => setUseCatchFlow(true)}
              >
                Use estimate in the calculation
              </Button>
              {useCatchFlow && (
                <Button variant="ghost" onClick={() => setUseCatchFlow(false)}>
                  Return to configured flow
                </Button>
              )}
            </div>
            <p className="small muted">
              This does not write calibration or operate irrigation: check several drippers, then
              set the flow in the zone's mapping above. The controller's recorded mean shot today:{" "}
              {number(meanShot, 2)} {meanShot !== null ? "L" : ""}, which differs by phase and
              controller adjustment and is not a calibration.
            </p>
          </div>
        </details>
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
    </section>
  );
}
