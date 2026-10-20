import { useEffect, useState } from "react";
import type { ProbeSnapshot, RunRecord } from "./comparison-types";
import type { Controller } from "./types";
import { alignGrid, chunks, previousWindow, runDayAt, SeriesGrid, type Choice, type ExplorerSensor, type Span } from "./history-explorer";
import { dayOfRun, type GrowDay, type GrowDaysDocument } from "./grows";
import { dateInZone } from "./comparison";

export interface ProbeMatch { entityId: string | null; candidates: ProbeSnapshot[]; }
/** Never guess between duplicate labels or positions. A manual choice must belong to this grow. */
export function matchProbe(current: ProbeSnapshot, past: ProbeSnapshot[], manual?: string): ProbeMatch {
  const candidates = past.filter((p) => !p.kind || !current.kind || p.kind === current.kind);
  if (manual && candidates.some((p) => p.entity_id === manual)) return { entityId: manual, candidates };
  const sameRow = current.row_label ? candidates.filter((p) => p.row_label === current.row_label) : [];
  if (sameRow.length === 1) return { entityId: sameRow[0].entity_id, candidates };
  if (sameRow.length > 1) return { entityId: null, candidates: sameRow };
  const sameEntity = candidates.find((p) => p.entity_id === current.entity_id);
  if (sameEntity) return { entityId: sameEntity.entity_id, candidates };
  const position = current.position === null ? [] : candidates.filter((p) => p.position === current.position);
  return { entityId: position.length === 1 ? position[0].entity_id : null, candidates };
}
export function chosenGrow(sensor: ExplorerSensor, choice: Choice, current: RunRecord, previous: RunRecord | null, runs: RunRecord[]) {
  const id = choice.probeCompare?.[sensor.entityId];
  if (id === undefined) return !choice.compare ? null : choice.compareRun
    ? runs.find((r) => r.id === choice.compareRun && r.id !== current.id && !r.archived) ?? null : previous;
  const runId = id.startsWith("run:") ? id.slice(4) : id;
  return id === "off" ? null : id === "last" ? previous : runs.find((r) => r.id === runId && r.id !== current.id && !r.archived) ?? null;
}
export function fallbackReading(raw: number | null, hourly?: { mean: number | null; min: number | null; max: number | null }, daily?: { mean: number | null; min: number | null; max: number | null }) {
  if (raw !== null && Number.isFinite(raw)) return { value: raw, min: null, max: null, source: "recorded history" };
  const band = hourly?.mean !== null && typeof hourly?.mean === "number" && Number.isFinite(hourly.mean) ? hourly : daily;
  return typeof band?.mean === "number" && Number.isFinite(band.mean)
    ? { value: band.mean, min: typeof band.min === "number" && Number.isFinite(band.min) ? band.min : null, max: typeof band.max === "number" && Number.isFinite(band.max) ? band.max : null, source: band === hourly ? "hourly statistics" : "daily summary" }
    : { value: null, min: null, max: null, source: null };
}
export interface ProbeOverlay {
  grow: RunRecord; values: (number | null)[]; low: (number | null)[]; high: (number | null)[];
  sources: string[]; match: ProbeMatch; error?: string;
}
export function summaryBand(days: GrowDay[], grow: RunRecord, sensor: ExplorerSensor, historicalId: string | null, rowLabel: string, day: number) {
  const row = days.find((d) => d.zone === sensor.zone && dayOfRun(grow, d.date) === day);
  if (!row) return null;
  const zone = grow.zones.find((z) => z.zone_id === sensor.zone);
  if (historicalId === zone?.vwc_sensor) return row.vwc ? { min: row.vwc.trough, max: row.vwc.peak, mean: row.vwc.mean } : null;
  if (historicalId === zone?.ec_sensor) return row.ec;
  const probes = row.probes ?? [];
  const exact = probes.find((p) => p.entity_id === historicalId || p.entity_id === sensor.entityId);
  const names = probes.filter((p) => p.name === rowLabel);
  const probe = exact ?? (names.length === 1 ? names[0] : null);
  return probe ? { min: probe.trough, max: probe.peak, mean: probe.mean } : null;
}

/** At most two sensor jobs, day-sized raw reads, then one capped statistics request per sensor.
 * Late responses never enter another room or a different range. Old records work by entity ID. */
export function useProbeComparisons(controller: Controller, sensors: ExplorerSensor[], allSensors: ExplorerSensor[], choice: Choice,
  current: RunRecord | null, previous: RunRecord | null, runs: RunRecord[], span: Span | null, step: number) {
  const [rows, setRows] = useState(new Map<string, ProbeOverlay>());
  const [busy, setBusy] = useState(false);
  const key = JSON.stringify([controller.roomId, current?.id, span, step, sensors.map((s) => s.entityId), choice.compare,
    choice.compareRun, choice.probeCompare, choice.probeMatch, runs]);
  useEffect(() => {
    const abort = new AbortController();
    setRows(new Map());
    if (!current || !span) return () => abort.abort();
    const wanted = sensors.filter((s) => chosenGrow(s, choice, current, previous, runs));
    if (!wanted.length) { setBusy(false); return () => abort.abort(); }
    setBusy(true);
    let next = 0;
    const result = new Map<string, ProbeOverlay>();
    const read = async (sensor: ExplorerSensor) => {
      const grow = chosenGrow(sensor, choice, current, previous, runs)!;
      const window = previousWindow(current, grow, span.start, span.end, Date.now());
      if (!window) return;
      const zone = grow.zones.find((z) => z.zone_id === sensor.zone);
      const liveZone = controller.room.zones.find((z) => z.id === sensor.zone);
      const currentZone = current.zones.find((z) => z.zone_id === sensor.zone);
      const snapshot = currentZone?.probes?.find((p) => p.entity_id === sensor.entityId) ?? {
        entity_id: sensor.entityId, row_label: String(controller.states[sensor.entityId]?.attributes.row_label || sensor.label),
        position: typeof controller.states[sensor.entityId]?.attributes.row_position === "number" ? Number(controller.states[sensor.entityId].attributes.row_position) : null,
        kind: sensor.kind === "vwc" || sensor.kind === "ec" ? sensor.kind : null,
      };
      const fused = sensor.entityId === liveZone?.vwc.entityId ? zone?.vwc_sensor : sensor.entityId === liveZone?.ec.entityId ? zone?.ec_sensor : null;
      const match: ProbeMatch = fused ? { entityId: fused, candidates: [] } : (sensor.kind === "vwc" || sensor.kind === "ec") && zone?.probes?.length
        ? matchProbe(snapshot, zone.probes, choice.probeMatch?.[sensor.entityId])
        : { entityId: sensor.entityId, candidates: [] };
      const grid = new SeriesGrid(window.start, window.end, step);
      const target = new SeriesGrid(span.start, span.end, step);
      const aligned = (values: (number | null)[]) => alignGrid(values, { grid, run: grow }, { ...target, run: current });
      let values = new Array<number | null>(target.length).fill(null);
      let low = [...values], high = [...values];
      const sources = new Set<string>();
      let error = "";
      if (match.entityId) {
        try {
          for (const day of chunks(window)) {
            if (abort.signal.aborted) return;
            const raw = await controller.timeline({ entityIds: [match.entityId], attributeIds: [], ...day });
            grid.add(raw[match.entityId] ?? []);
          }
          values = aligned(grid.values());
          if (values.some((v) => v !== null)) sources.add("recorded history");
        } catch (e) { error = e instanceof Error ? e.message : "Recorded history unavailable."; }
        if (values.some((v) => v === null) && controller.sensorStatistics && !abort.signal.aborted) {
          try {
            const statistics = await controller.sensorStatistics({ entityIds: [match.entityId], start: new Date(window.start).toISOString(),
              end: new Date(window.end).toISOString(), timeZone: grow.time_zone, signal: abort.signal });
            const points = statistics[match.entityId] ?? [];
            const meanGrid = new SeriesGrid(window.start, window.end, step);
            const minGrid = new SeriesGrid(window.start, window.end, step), maxGrid = new SeriesGrid(window.start, window.end, step);
            const hours = new Map(points.map((point) => [Math.floor((typeof point.start === "string" ? Date.parse(point.start) : point.start < 1e12 ? point.start * 1000 : point.start) / 3600000), point]));
            // Each hourly statistic represents its hour, not a fabricated minute-by-minute measurement.
            for (let i = 0; i < grid.length; i++) {
              const t = grid.timeAt(i), point = hours.get(Math.floor(t / 3600000));
              const add = (g: SeriesGrid, v: number | null | undefined) => g.add([{ time: t, state: typeof v === "number" && Number.isFinite(v) ? String(v) : "unknown" }]);
              add(meanGrid, point?.mean); add(minGrid, point?.min); add(maxGrid, point?.max);
            }
            const means = aligned(meanGrid.values()), mins = aligned(minGrid.values()), maxs = aligned(maxGrid.values());
            values = values.map((v, i) => { const reading = fallbackReading(v, { mean: means[i], min: mins[i], max: maxs[i] }); if (reading.source === "hourly statistics") { sources.add(reading.source); low[i] = reading.min; high[i] = reading.max; } return reading.value; });
          } catch { /* A probe with no state_class may have only daily summaries. */ }
        }
      }
      if (values.some((v) => v === null) && !abort.signal.aborted) {
        try {
          const doc = await controller.operator<GrowDaysDocument>("grow_days_get", {
            start: dateInZone(window.start, grow.time_zone), end: dateInZone(window.end, grow.time_zone) });
          values = values.map((v, i) => {
            if (v !== null) return v;
            const band = summaryBand(doc.days, grow, sensor, match.entityId, snapshot.row_label, Math.floor(runDayAt(current, target.timeAt(i))));
            const reading = fallbackReading(v, undefined, band ?? undefined);
            if (reading.source) { sources.add(reading.source); low[i] = reading.min; high[i] = reading.max; }
            return reading.value;
          });
        } catch { /* Absence of old summaries is shown as missing data, never zero. */ }
      }
      if (!abort.signal.aborted) { result.set(sensor.entityId, { grow, values, low, high, sources: [...sources], match,
        error: !match.entityId && match.candidates.length ? "Choose the matching historical probe." : !sources.size ? error || "No recorded data for these grow days." : undefined }); setRows(new Map(result)); }
    };
    const worker = async () => { while (next < wanted.length && !abort.signal.aborted) await read(wanted[next++]); };
    void Promise.all([worker(), worker()]).finally(() => !abort.signal.aborted && setBusy(false));
    return () => abort.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, controller.timeline, controller.operator, controller.sensorStatistics]);
  return { rows, busy };
}
