import type { HistoryPoint, HistoryRequest, HistoryWindow, WindowSeries } from "./comparison-types";
import { dateInZone, daysBetween, downsample, mergeDaily, summarize } from "./comparison";
type Reader = (path: string, signal?: AbortSignal) => Promise<unknown>;
function check(signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException("History request cancelled.", "AbortError");
}
export async function loadHistoryWindow(
  read: Reader,
  request: HistoryRequest,
): Promise<HistoryWindow> {
  const start = Date.parse(request.start),
    end = Date.parse(request.end),
    ids = [...new Set(request.entityIds)];
  if (
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    end <= start ||
    end - start > 367 * 86400000 ||
    end > Date.now()
  )
    throw new Error("History needs an elapsed range of at most 366 calendar days.");
  new Intl.DateTimeFormat("en", { timeZone: request.timeZone });
  if (daysBetween(dateInZone(start, request.timeZone), dateInZone(end - 1, request.timeZone)) > 365)
    throw new Error("History needs an elapsed range of at most 366 calendar days.");
  if (!ids.length || ids.length > 4 || ids.some((id) => !/^sensor\.[a-z0-9_]+$/.test(id)))
    throw new Error("Select 1–4 explicitly registered sensor entities.");
  const chunks: { start: number; end: number }[] = [];
  for (let from = start; from < end; from += 7 * 86400000)
    chunks.push({ start: from, end: Math.min(end, from + 7 * 86400000) });
  const result: HistoryWindow = {
    start: new Date(start).toISOString(),
    end: new Date(end).toISOString(),
    series: ids.map((entityId) => ({ entityId, points: [], daily: [] })),
    warnings: [],
  };
  const batches: { series: WindowSeries[]; warning?: string }[] = new Array(chunks.length);
  let next = 0,
    stopped = false;
  async function worker() {
    while (next < chunks.length && !stopped) {
      check(request.signal);
      const index = next++,
        chunk = chunks[index];
      const query = new URLSearchParams({
        filter_entity_id: ids.join(","),
        end_time: new Date(chunk.end).toISOString(),
        minimal_response: "",
        no_attributes: "",
      });
      try {
        const payload = await read(
          `history/period/${new Date(chunk.start).toISOString()}?${query}`,
          request.signal,
        );
        check(request.signal);
        if (!Array.isArray(payload)) throw new Error("Recorder returned invalid history.");
        const series = ids.map((entityId) => {
          const rows =
            payload.find((group) => Array.isArray(group) && group[0]?.entity_id === entityId) || [];
          if (rows.length > 200_000)
            throw new Error("Recorder response is too dense; choose a shorter range.");
          const points: HistoryPoint[] = [];
          for (const raw of rows) {
            if (!raw || typeof raw !== "object") continue;
            const time = Date.parse(raw.last_changed || raw.last_updated);
            // Recorder carry-in is context, not a new observation at every chunk boundary.
            if (!Number.isFinite(time) || time < chunk.start || time >= chunk.end) continue;
            const state = typeof raw.state === "string" ? raw.state.trim() : "";
            const value = state && Number.isFinite(Number(state)) ? Number(state) : null;
            points.push({ time, value });
          }
          const unique = [...new Map(points.map((p) => [p.time, p])).values()];
          return {
            entityId,
            points: downsample(unique, 800),
            daily: summarize(unique, request.timeZone),
          };
        });
        batches[index] = { series };
      } catch (error) {
        check(request.signal);
        // Embedded HA callApi cannot abort its underlying request. Stop dispatching on
        // any transport/protocol failure, so a timeout cannot fan out pending calls.
        stopped = true;
        batches[index] = {
          series: [],
          warning: `${new Date(chunk.start).toISOString().slice(0, 10)}: ${error instanceof Error ? error.message : "Recorder unavailable"}. Remaining chunks were not requested.`,
        };
      }
    }
  }
  await Promise.all([worker(), worker()]);
  check(request.signal);
  let missingChunks = 0;
  for (let index = 0; index < chunks.length; index++) {
    const batch = batches[index],
      chunk = chunks[index];
    if (batch?.warning) result.warnings.push(batch.warning);
    if (!batch) missingChunks++;
    for (const target of result.series) {
      const series = batch?.series.find((s) => s.entityId === target.entityId);
      if (!series?.points.length) {
        target.points.push(
          { time: chunk.start, value: null },
          { time: chunk.end - 1, value: null },
        );
        continue;
      }
      const last = target.points.at(-1),
        first = series.points[0];
      if (last && first.time - last.time > 30 * 60_000)
        target.points.push({ time: last.time + 1, value: null });
      target.points.push(...series.points);
      target.daily.push(...series.daily);
    }
  }
  if (missingChunks)
    result.warnings.push(
      `${missingChunks} history chunks were not requested after a Recorder error. Coverage is partial.`,
    );
  for (const series of result.series) {
    // Existing nulls already encode gaps. Decimated sample spacing must not create new gaps.
    series.points = downsample(series.points, 1600, Infinity);
    series.daily = mergeDaily(series.daily);
    if (!series.daily.length)
      result.warnings.push(
        `No retained readings for ${series.entityId}. Recorder may be disabled, the sensor excluded, or retention expired.`,
      );
    else
      result.warnings.push(
        `${series.entityId}: ${series.daily.reduce((sum, row) => sum + row.records, 0)} retained numeric state changes across ${series.daily.length} local dates. Coverage between samples is unknown.`,
      );
  }
  return result;
}
