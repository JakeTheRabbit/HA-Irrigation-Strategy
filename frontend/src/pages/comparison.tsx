import { useEffect, useRef, useState } from "react";
import { ArrowRight, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Heading, type Page } from "@/components/dashboard";
import type { Controller } from "@/lib/types";
import type { HistoryWindow, RunsDocument, RunZone } from "@/lib/comparison-types";
import { addDays, boundedRange, comparisonRange, dateInZone } from "@/lib/comparison";
import { ComparisonChart, ComparisonSummary, format, type Loaded } from "./comparison-views";
import { RunWeeks } from "./comparison-weeks";
import { buildSetpointPreview } from "@/lib/setpoint-preview";
import { buildComparisonTarget } from "@/lib/comparison-target";
import "./comparison.css";
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

/** History › Compare runs: is this crop tracking the last good one, and where did it differ, week
 * by week? The full-resolution chart and the record's quality are one tap down; the run records
 * themselves are kept in Settings. */
export function Comparison({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: (page: Page) => void;
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
  const [loaded, setLoaded] = useState<Loaded | null>(null),
    [historyError, setHistoryError] = useState<string | null>(null),
    [loading, setLoading] = useState(false);
  const [weekNotes, setWeekNotes] = useState<string[]>([]);
  const roomRef = useRef(controller.roomId);
  roomRef.current = controller.roomId;
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
  useEffect(() => {
    setDocument(null);
    setCurrentId("");
    setPreviousId("");
    setLoaded(null);
    setZoneId(0);
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
        if (cancelled) return;
        setDocument(value);
        setMetadataError(value.error);
        // The run in progress, and the latest one before it: what a grower compares first.
        const open = value.runs.filter((run) => !run.archived);
        const current = open.find((run) => !run.end_date) ?? open[0];
        const previous = open
          .filter((run) => run.id !== current?.id && run.end_date)
          .sort((a, b) => b.start_date.localeCompare(a.start_date))[0];
        setCurrentId((selected) => selected || current?.id || "");
        setPreviousId((selected) => selected || previous?.id || "");
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
  const openRecords = () => {
    navigate("settings");
    setTimeout(() => window.document.getElementById("run-records")?.scrollIntoView(), 0);
  };
  const zoneName =
    zoneChoices.find((zone) => zone.zone_id === effectiveZone)?.name ?? `Zone ${effectiveZone}`;
  return (
    <div className="comparison-page">
      <Heading
        title="Compare runs"
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
          This run
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
          Compare with
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
        <div className="comparison-records-link">
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
          <Button variant="ghost" size="sm" onClick={openRecords}>
            Run records <ArrowRight size={15} aria-hidden="true" />
          </Button>
        </div>
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
          <p>
            No runs are recorded for this room yet. Record this crop and a past one, each with its
            real start date, to compare them week by week. The chart below works on dates without a
            run; Recorder history already purged cannot be recovered by adding one.
          </p>
          <Button variant="outline" onClick={openRecords}>
            Record a run
          </Button>
        </div>
      )}
      <RunWeeks
        controller={controller}
        current={currentRun}
        previous={previousRun}
        zoneId={effectiveZone}
        zoneName={zoneName}
        refresh={refresh}
        onNotes={setWeekNotes}
      />
      <details className="comparison-more" data-section="chart">
        <summary>Full-resolution chart, with a target reference</summary>
        <div className="comparison-more-body">
          <section className="panel comparison-range">
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
            <p className="small comparison-wide">
              Calendar: {timeZone}
              {!doc && !currentRun ? " (browser time zone until run metadata loads)" : ""}. Windows
              end at the request time; the previous run stops at the same grow age. Run records
              never enable or arm irrigation.
            </p>
          </section>
          {loading && <p role="status">Loading selected-zone Recorder history…</p>}
          {historyError && (
            <p className="comparison-notice" role="alert">
              {historyError}
            </p>
          )}
          {loaded && (
            <>
              <section className="panel comparison-reference">
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
                    readings. Registering past dates captures today's reference; editing dates keeps
                    the original capture.
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
                {loaded.timeZone}); loaded {new Date(loaded.loadedAt).toLocaleTimeString()}. Use
                Refresh history to advance this window. Raw retained state changes are summarized
                before chart downsampling.
              </p>
            </>
          )}
        </div>
      </details>
      <details className="comparison-more" data-section="quality">
        <summary>Data quality: daily ranges and history coverage</summary>
        <div className="comparison-more-body">
          {!!weekNotes.length && (
            <section className="comparison-notice" aria-label="Where the weekly figures come from">
              <h2>Where the weekly figures come from</h2>
              {weekNotes.map((note) => (
                <p key={note}>{note}</p>
              ))}
            </section>
          )}
          {loaded && (
            <>
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
                Available samples do not establish complete coverage. Recorder exclusion, outages
                and retention limits can leave partial history.
              </p>
            </section>
          )}
        </div>
      </details>
    </div>
  );
}
