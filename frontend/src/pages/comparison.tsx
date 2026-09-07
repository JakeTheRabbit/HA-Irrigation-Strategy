import { useLayoutEffect, useEffect, useRef, useState } from "react";
import { Download, RefreshCw, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Heading } from "@/components/dashboard";
import type { Controller } from "@/lib/types";
import type { HistoryWindow, RunRecord, RunsDocument, RunZone } from "@/lib/comparison-types";
import { addDays, boundedRange, comparisonRange, dateInZone } from "@/lib/comparison";
import { ComparisonChart, ComparisonSummary, format, type Loaded } from "./comparison-views";
import { buildSetpointPreview } from "@/lib/setpoint-preview";
import { buildComparisonTarget } from "@/lib/comparison-target";
import "./comparison.css";
type Form = { id?: string; name: string; start_date: string; end_date: string };
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Comparison request failed.";
const sensorIds = (zone: RunZone) =>
  [zone.vwc_sensor, zone.ec_sensor].filter((id): id is string => !!id);
function liveZone(controller: Controller, id: number): RunZone | null {
  const zone = controller.room.zones.find((z) => z.id === id);
  return zone
    ? {
        zone_id: zone.id,
        name: zone.name,
        vwc_sensor: zone.vwc.entityId,
        ec_sensor: zone.ec.entityId,
        plant_count: null,
        parameters: {},
      }
    : null;
}
export function Comparison({
  controller,
  onDirtyChange,
}: {
  controller: Controller;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [document, setDocument] = useState<RunsDocument | null>(null),
    [metadataError, setMetadataError] = useState<string | null>(null),
    [metadataLoading, setMetadataLoading] = useState(false),
    [metadataReload, setMetadataReload] = useState(0);
  const [currentId, setCurrentId] = useState(""),
    [previousId, setPreviousId] = useState(""),
    [zoneId, setZoneId] = useState(0),
    [archived, setArchived] = useState(false);
  const [period, setPeriod] = useState("week"),
    [customStart, setCustomStart] = useState(""),
    [customEnd, setCustomEnd] = useState(""),
    [refresh, setRefresh] = useState(0),
    [monthly, setMonthly] = useState(false),
    [reference, setReference] = useState("current");
  const [form, setForm] = useState<Form | null>(null),
    [saving, setSaving] = useState(false),
    [formError, setFormError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null),
    [historyError, setHistoryError] = useState<string | null>(null),
    [loading, setLoading] = useState(false);
  const roomRef = useRef(controller.roomId);
  roomRef.current = controller.roomId;
  const fileRef = useRef<HTMLInputElement>(null);
  const doc = document?.room_id === controller.roomId ? document : null;
  const currentRun = doc?.runs.find((run) => run.id === currentId) || null,
    previousRun = doc?.runs.find((run) => run.id === previousId) || null;
  const timeZone =
    currentRun?.time_zone ||
    doc?.time_zone ||
    Intl.DateTimeFormat().resolvedOptions().timeZone ||
    "UTC";
  const zoneChoices =
    currentRun?.zones ||
    controller.room.zones.map((zone) => ({ zone_id: zone.id, name: zone.name }));
  const effectiveZone = zoneChoices.some((zone) => zone.zone_id === zoneId)
    ? zoneId
    : zoneChoices[0]?.zone_id || 0;
  const currentZone = controller.room.zones.find((zone) => zone.id === effectiveZone);
  const runChoices = doc?.runs.filter((run) => archived || !run.archived) || [];
  useLayoutEffect(() => {
    onDirtyChange?.(Boolean(form));
    return () => onDirtyChange?.(false);
  }, [form, onDirtyChange]);
  useEffect(() => {
    setDocument(null);
    setCurrentId("");
    setPreviousId("");
    setForm(null);
    setLoaded(null);
    setFormError(null);
    setZoneId(0);
    setSaving(false);
    setReference("current");
  }, [controller.roomId]);
  useEffect(() => {
    let cancelled = false;
    if (!controller.roomId) return;
    setMetadataLoading(true);
    setMetadataError(null);
    controller
      .operator<RunsDocument>("runs_get")
      .then((value) => {
        if (!cancelled) {
          setDocument(value);
          setMetadataError(value.error);
        }
      })
      .catch((error) => {
        if (!cancelled) setMetadataError(errorText(error));
      })
      .finally(() => {
        if (!cancelled) setMetadataLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [controller.roomId, controller.operator, metadataReload]);
  const runKey = JSON.stringify([currentRun, previousRun]);
  const sensorKey = JSON.stringify([currentZone?.vwc.entityId, currentZone?.ec.entityId]);
  useEffect(() => {
    const abort = new AbortController();
    setLoaded(null);
    setHistoryError(null);
    setLoading(true);
    async function load() {
      if (!controller.roomId || !effectiveZone)
        throw new Error("Select an available room and zone.");
      const now = Date.now(),
        today = dateInZone(now, timeZone);
      let anchor =
        currentRun?.end_date && currentRun.end_date < today ? currentRun.end_date : today;
      let first =
        period === "day"
          ? anchor
          : period === "month"
            ? anchor.slice(0, 7) + "-01"
            : addDays(anchor, -6);
      if (period === "run") {
        if (!currentRun) throw new Error("Register and select a run to use run-to-date.");
        first = currentRun.start_date;
      }
      if (period === "custom") {
        first = customStart;
        anchor = customEnd;
      }
      if (currentRun) {
        if (first < currentRun.start_date) first = currentRun.start_date;
        if (currentRun.end_date && anchor > currentRun.end_date) anchor = currentRun.end_date;
      }
      const window = boundedRange(first, anchor, timeZone, now);
      const zone =
        currentRun?.zones.find((z) => z.zone_id === effectiveZone) ||
        liveZone(controller, effectiveZone);
      if (!zone || !sensorIds(zone).length)
        throw new Error("No VWC/EC sensor IDs were registered for this zone.");
      const current = await controller.historyWindow({
        entityIds: sensorIds(zone),
        start: new Date(window.start).toISOString(),
        end: new Date(window.end).toISOString(),
        timeZone,
        signal: abort.signal,
      });
      let previous: HistoryWindow | null = null,
        previousZone: RunZone | null = null,
        warning: string | null = null;
      if (previousRun && currentRun) {
        previousZone = previousRun.zones.find((z) => z.zone_id === effectiveZone) || null;
        const range = comparisonRange(currentRun, previousRun, window.start, window.end, now);
        if (!previousZone || !sensorIds(previousZone).length)
          warning =
            "The previous run has no registered sensors for this zone; its curve is unavailable.";
        else if (!range)
          warning = "The previous run has no elapsed data range at the selected grow age.";
        else
          previous = await controller.historyWindow({
            entityIds: sensorIds(previousZone),
            start: new Date(range.start).toISOString(),
            end: new Date(range.end).toISOString(),
            timeZone: previousRun.time_zone,
            signal: abort.signal,
          });
      }
      if (!abort.signal.aborted)
        setLoaded({
          current,
          previous,
          ...window,
          loadedAt: Date.now(),
          currentRun,
          previousRun,
          zone,
          previousZone,
          timeZone,
          warning,
        });
    }
    void load()
      .catch((error) => {
        if (!abort.signal.aborted) setHistoryError(errorText(error));
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
    // Long windows refresh only on selection or explicit Refresh, never the 30s live snapshot.
  }, [
    controller.roomId,
    controller.historyWindow,
    effectiveZone,
    sensorKey,
    runKey,
    period,
    customStart,
    customEnd,
    timeZone,
    refresh,
  ]);
  async function save() {
    if (!form || !doc) return;
    const room = controller.roomId;
    setSaving(true);
    setFormError(null);
    try {
      const next = await controller.operator<RunsDocument>("runs_save", {
        record: form,
        expected_revision: doc.revision,
      });
      if (roomRef.current === room) {
        setDocument(next);
        if (!form.id)
          setCurrentId(
            next.runs.find((run) => !doc.runs.some((old) => old.id === run.id))?.id || "",
          );
        setForm(null);
      }
    } catch (error) {
      if (roomRef.current === room) setFormError(errorText(error));
    } finally {
      if (roomRef.current === room) setSaving(false);
    }
  }
  async function archiveRun(run: RunRecord) {
    if (!doc) return;
    const room = controller.roomId;
    setSaving(true);
    setFormError(null);
    try {
      const next = await controller.operator<RunsDocument>("runs_archive", {
        id: run.id,
        archived: !run.archived,
        expected_revision: doc.revision,
      });
      if (roomRef.current !== room) return;
      setDocument(next);
      if (!run.archived) {
        if (currentId === run.id) {
          setCurrentId("");
          setReference("current");
        }
        if (previousId === run.id) setPreviousId("");
      }
    } catch (error) {
      if (roomRef.current === room) setFormError(errorText(error));
    } finally {
      if (roomRef.current === room) setSaving(false);
    }
  }
  function exportRuns() {
    if (!doc) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }),
    );
    const link = window.document.createElement("a");
    link.href = url;
    link.download = "crop-steering-run-metadata.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function importRuns(file?: File) {
    if (!file || !doc) return;
    const room = controller.roomId;
    setFormError(null);
    setSaving(true);
    try {
      if (file.size > 2_000_000) throw new Error("Metadata import is limited to 2 MB.");
      const value = JSON.parse(await file.text());
      if (roomRef.current !== room) throw new Error("Room changed; import cancelled.");
      if (value.schema_version !== 1 || value.room_id !== room || !Array.isArray(value.runs))
        throw new Error("Import a version 1 export for this exact room.");
      const next = await controller.operator<RunsDocument>("runs_import", {
        runs: value.runs,
        expected_revision: doc.revision,
      });
      if (roomRef.current === room) setDocument(next);
    } catch (error) {
      if (roomRef.current === room) setFormError(errorText(error));
    } finally {
      if (roomRef.current === room) setSaving(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }
  const savedZone = currentRun?.zones.find((zone) => zone.zone_id === effectiveZone);
  const preview = currentZone
    ? buildSetpointPreview(controller.room, controller.states, effectiveZone, {})
    : null;
  const targetParameters =
    reference === "saved" ? savedZone?.parameters : preview?.draft.parameters;
  const lights =
    reference === "saved"
      ? { on: currentRun?.lights.on, off: currentRun?.lights.off }
      : { on: preview?.draft.lightsOn, off: preview?.draft.lightsOff };
  const dailyTarget =
    loaded && reference !== "phase"
      ? buildComparisonTarget({
          parameters: targetParameters || {},
          lightsOn: lights.on ?? NaN,
          lightsOff: lights.off ?? NaN,
          start: loaded.start,
          end: loaded.end,
          now: loaded.loadedAt,
          timeZone: loaded.timeZone,
          runStartDate: currentRun?.start_date || dateInZone(loaded.start, loaded.timeZone),
        })
      : undefined;
  const targets =
    reference === "saved"
      ? {
          vwc: savedZone?.parameters.p2_vwc_threshold ?? null,
          ec: savedZone?.parameters.ec_target_p2 ?? null,
        }
      : { vwc: currentZone?.target.value ?? null, ec: currentZone?.ecTarget.value ?? null };
  const targetLabel =
    reference === "saved"
      ? "Saved run daily reference"
      : reference === "phase"
        ? "Current phase reference"
        : "Current configured daily plan";
  const warnings = [
    ...(loaded?.current.warnings || []),
    ...(loaded?.previous?.warnings || []),
    ...(loaded?.warning ? [loaded.warning] : []),
    ...(dailyTarget?.warnings || []),
    ...(reference === "current" ? preview?.issues || [] : []),
  ];
  return (
    <div className="comparison-page">
      <Heading
        title="Compare runs"
        description="Recorded VWC and EC, aligned by grow age with explicit planning references."
        action={
          <Button
            variant="outline"
            onClick={() => setRefresh((value) => value + 1)}
            disabled={loading}
          >
            <RefreshCw size={15} /> Refresh history
          </Button>
        }
      />
      <section className="panel comparison-controls">
        <label>
          Current run
          <select
            aria-label="Current run"
            value={currentId}
            onChange={(event) => {
              setCurrentId(event.target.value);
              setPreviousId("");
              if (!event.target.value) setReference("current");
            }}
          >
            <option value="">Date range · no run selected</option>
            {runChoices.map((run) => (
              <option key={run.id} value={run.id}>
                {run.name}
                {run.archived ? " · archived" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          Previous run
          <select
            aria-label="Previous run"
            value={previousId}
            disabled={!currentRun}
            onChange={(event) => setPreviousId(event.target.value)}
          >
            <option value="">No comparison run</option>
            {runChoices
              .filter((run) => run.id !== currentId)
              .map((run) => (
                <option key={run.id} value={run.id}>
                  {run.name}
                  {run.archived ? " · archived" : ""}
                </option>
              ))}
          </select>
        </label>
        <label>
          Zone
          <select
            aria-label="Comparison zone"
            value={effectiveZone}
            onChange={(event) => setZoneId(Number(event.target.value))}
          >
            {zoneChoices.map((zone) => (
              <option key={zone.zone_id} value={zone.zone_id}>
                {zone.name}
                {currentRun && !controller.room.zones.some((live) => live.id === zone.zone_id)
                  ? " · historical zone"
                  : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          History range
          <select
            aria-label="Comparison history range"
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
          >
            <option value="day">Day</option>
            <option value="week">Week · 7 days</option>
            <option value="month">Calendar month</option>
            <option value="run" disabled={!currentRun}>
              Run to date
            </option>
            <option value="custom">Custom dates</option>
          </select>
        </label>
        {period === "custom" && (
          <>
            <label>
              From date
              <Input
                aria-label="Comparison from date"
                type="date"
                value={customStart}
                onChange={(event) => setCustomStart(event.target.value)}
              />
            </label>
            <label>
              Through date
              <Input
                aria-label="Comparison through date"
                type="date"
                value={customEnd}
                onChange={(event) => setCustomEnd(event.target.value)}
              />
            </label>
          </>
        )}
        <label className="comparison-check">
          <input
            type="checkbox"
            checked={archived}
            onChange={(event) => {
              setArchived(event.target.checked);
              if (!event.target.checked) {
                if (currentRun?.archived) {
                  setCurrentId("");
                  setPreviousId("");
                }
                if (previousRun?.archived) setPreviousId("");
              }
            }}
          />{" "}
          Include archived run records
        </label>
        <p className="small comparison-wide">
          Calendar: {timeZone}
          {!doc && !currentRun ? " (browser time zone until run metadata loads)" : ""}. Windows end
          at the request time; the previous run stops at the same grow age. Run records never enable
          or arm irrigation.
        </p>
      </section>
      {metadataLoading && <p role="status">Loading run records…</p>}
      {metadataError && (
        <div className="comparison-notice" role="alert">
          {metadataError}
          <Button variant="outline" onClick={() => setMetadataReload((value) => value + 1)}>
            Reload run records
          </Button>
        </div>
      )}
      {doc && !doc.runs.length && (
        <div className="comparison-notice">
          No runs have been registered for this room. Add a run with its actual start date to
          compare grow ages. Date-range history works without a run; past Recorder retention cannot
          be recovered by adding one.
        </div>
      )}
      {loading && <p role="status">Loading selected-zone Recorder history…</p>}
      {historyError && (
        <p className="comparison-notice" role="alert">
          {historyError}
        </p>
      )}
      {loaded && (
        <>
          <section className="panel comparison-reference">
            <label>
              Target reference
              <select
                aria-label="Target reference"
                value={reference}
                onChange={(event) => setReference(event.target.value)}
              >
                <option value="current">Current configured daily plan</option>
                <option value="saved" disabled={!currentRun}>
                  Saved run daily reference
                </option>
                <option value="phase">Current phase reference</option>
              </select>
            </label>
            <div>
              <h2>{targetLabel}</h2>
              <p>
                {reference === "phase"
                  ? `VWC ${format(targets.vwc)}% · EC ${format(targets.ec)} mS/cm`
                  : `P0–P3 VWC / EC illustration · lights ${format(lights.on)} → ${format(lights.off)} h`}
              </p>
              <p className="small">
                {reference === "saved" && currentRun
                  ? `${savedZone?.reference_source || currentRun.reference_source}. Captured ${new Date(currentRun.captured_at).toLocaleString(undefined, { timeZone: currentRun.time_zone })} (${currentRun.time_zone}). Saved lights on/off: ${format(currentRun.lights.on)} / ${format(currentRun.lights.off)} h.`
                  : `Current configuration observed ${controller.lastUpdated ? new Date(controller.lastUpdated).toLocaleString() : "at this page snapshot"}; source: ${preview?.source || "selected live zone unavailable"}.`}
              </p>
              <p className="small">
                This is a reference illustration, not the historical targets used during these
                readings. Registering past dates captures today's reference; editing dates keeps the
                original capture.
              </p>
            </div>
          </section>
          <ComparisonChart
            loaded={loaded}
            targets={reference === "phase" ? targets : { vwc: null, ec: null }}
            dailyTarget={dailyTarget}
            label={targetLabel}
          />
          <p className="small">
            History requested through{" "}
            {new Date(loaded.end).toLocaleString(undefined, { timeZone: loaded.timeZone })} (
            {loaded.timeZone}); loaded {new Date(loaded.loadedAt).toLocaleTimeString()}. Use Refresh
            history to advance this window. Raw retained state changes are summarized before chart
            downsampling.
          </p>
          <label className="comparison-check">
            <input
              type="checkbox"
              checked={monthly}
              onChange={(event) => setMonthly(event.target.checked)}
            />{" "}
            Group recorded ranges by month
          </label>
          <ComparisonSummary loaded={loaded} monthly={monthly} />
        </>
      )}
      {!!warnings.length && (
        <section className="comparison-notice" aria-label="History coverage">
          <h2>History coverage</h2>
          {[...new Set(warnings)].map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
          <p>
            Available samples do not establish complete coverage. Recorder exclusion, outages and
            retention limits can leave partial history.
          </p>
        </section>
      )}
      <section className="panel comparison-records">
        <div className="comparison-record-heading">
          <div>
            <h2>Run records</h2>
            <p className="small">
              Store up to 100 runs per room, with 1–366 inclusive calendar days per completed run.
              Metadata export contains no Recorder readings.
            </p>
          </div>
          <Button
            onClick={() => {
              setForm({ name: "", start_date: dateInZone(Date.now(), timeZone), end_date: "" });
              setFormError(null);
            }}
            disabled={!doc || !!doc.error || saving || !!form}
          >
            <Plus size={15} /> Add run
          </Button>
        </div>
        <div className="comparison-actions">
          <Button variant="outline" onClick={exportRuns} disabled={!doc}>
            <Download size={15} /> Export metadata
          </Button>
          <Button
            variant="outline"
            onClick={() => fileRef.current?.click()}
            disabled={!doc || !!doc.error || saving || !!form}
          >
            Import metadata
          </Button>
          <input
            ref={fileRef}
            hidden
            type="file"
            accept="application/json,.json"
            aria-label="Import run metadata"
            onChange={(event) => void importRuns(event.target.files?.[0])}
          />
        </div>
        {form && (
          <form
            className="comparison-form"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <label>
              Run name
              <Input
                aria-label="Run name"
                required
                maxLength={80}
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            </label>
            <label>
              Start date
              <Input
                aria-label="Run start date"
                type="date"
                required
                value={form.start_date}
                onChange={(event) => setForm({ ...form, start_date: event.target.value })}
              />
            </label>
            <label>
              End date · blank while ongoing
              <Input
                aria-label="Run end date"
                type="date"
                value={form.end_date}
                onChange={(event) => setForm({ ...form, end_date: event.target.value })}
              />
            </label>
            <p className="small comparison-wide">
              {form.id
                ? "Changing the name or dates preserves the original reference, sensors, plants and lights schedule."
                : "Registration captures this room's configured sensors, plant counts, targets and lights schedule now. Past dates do not imply a historical configuration snapshot."}
            </p>
            <div className="comparison-actions comparison-wide">
              <Button type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save run record"}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={saving}
                onClick={() => setForm(null)}
              >
                Cancel
              </Button>
            </div>
          </form>
        )}
        {formError && (
          <p role="alert" className="comparison-notice">
            {formError}
          </p>
        )}
        <div className="comparison-run-list">
          {runChoices.map((run) => (
            <article key={run.id}>
              <div>
                <h3>
                  {run.name}
                  {run.archived ? " · archived" : ""}
                </h3>
                <p>
                  {run.start_date} → {run.end_date || "ongoing"} · {run.time_zone}
                </p>
                <p className="small">
                  Reference captured{" "}
                  {new Date(run.captured_at).toLocaleString(undefined, { timeZone: run.time_zone })}
                  . {run.reference_source}.
                </p>
                <details>
                  <summary>Registered zones and sensors</summary>
                  {run.zones.map((zone) => (
                    <p className="small" key={zone.zone_id}>
                      {zone.name} · plants at registration: {zone.plant_count ?? "unknown"} · VWC{" "}
                      {zone.vwc_sensor || "unavailable"} · EC {zone.ec_sensor || "unavailable"}
                    </p>
                  ))}
                </details>
              </div>
              <div className="comparison-actions">
                <Button
                  variant="outline"
                  disabled={saving || !!form || !!doc?.error}
                  onClick={() => {
                    setForm({
                      id: run.id,
                      name: run.name,
                      start_date: run.start_date,
                      end_date: run.end_date || "",
                    });
                    setFormError(null);
                  }}
                >
                  Edit dates/name
                </Button>
                <Button
                  variant="outline"
                  disabled={saving || !!form || !!doc?.error}
                  onClick={() => void archiveRun(run)}
                >
                  {run.archived ? "Restore" : "Archive"}
                </Button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
