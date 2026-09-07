import { createUuid } from "./uuid";
import type { HistoryRequest, RunRecord, RunsDocument } from "./comparison-types";
import type { States } from "./types";
import { buildRoom, discoverRooms } from "./model";
import { daysBetween, validDate } from "./comparison";
import { buildSetpointPreview } from "./setpoint-preview";
import { loadHistoryWindow } from "./comparison-history";
// Keep the demo's exported metadata compatible with RunStore's strategy-only schema.
const runParameterKeys = new Set([
  "dryback_target",
  "ec_target_p0",
  "ec_target_p1",
  "ec_target_p2",
  "p1_target_vwc",
  "p2_vwc_threshold",
  "p2_shot_size",
  "p1_initial_shot_size",
  "p3_emergency_vwc_threshold",
  "p3_emergency_shot_size",
  "p1_shot_size_increment",
  "p1_maximum_shots",
  "p1_time_between_shots",
  "p0_maximum_wait_time",
  "max_daily_volume",
  "field_capacity",
  "maximum_ec",
  "watchdog_hours",
]);
export async function demoHistoryWindow(request: HistoryRequest) {
  const result = await loadHistoryWindow(async (path) => {
    const url = new URL(path, "https://demo.invalid/");
    const start = Date.parse(url.pathname.split("/period/")[1]),
      end = Date.parse(url.searchParams.get("end_time")!);
    return request.entityIds.map((entity_id, index) => {
      const rows = [];
      for (let time = start; time < end; time += 15 * 60_000) {
        const ec = entity_id.includes("ec_zone") || entity_id.endsWith("_ec");
        rows.push({
          entity_id,
          last_changed: new Date(time).toISOString(),
          state: String((ec ? 3.5 : 58) + (ec ? 0.7 : 8) * Math.sin(time / 3_600_000 + index)),
        });
      }
      return rows;
    });
  }, request);
  result.warnings.unshift("Demo history is generated example data, not recorded sensor evidence.");
  return result;
}
export class RunDemo {
  private documents = new Map<string, RunsDocument>();
  constructor(private states: () => States) {}
  call(action: string, data: Record<string, unknown>): RunsDocument {
    const room = discoverRooms(this.states()).find((r) => r.id === data.room_id);
    if (!room) throw new Error("Unknown demo room.");
    const prior = this.documents.get(room.id) || {
      schema_version: 1 as const,
      room_id: room.id,
      revision: 0,
      time_zone: "Pacific/Auckland",
      runs: [],
      error: null,
      max_runs: 100,
    };
    const doc = structuredClone(prior);
    if (action === "runs_get") return doc;
    if (data.expected_revision !== doc.revision)
      throw new Error("Runs changed. Reload before saving.");
    if (action === "runs_save") {
      const raw = data.record as Partial<RunRecord>;
      if (
        !raw ||
        !raw.name?.trim() ||
        raw.name.length > 80 ||
        !validDate(raw.start_date || "") ||
        (raw.end_date &&
          (!validDate(raw.end_date) ||
            daysBetween(raw.start_date!, raw.end_date) < 0 ||
            daysBetween(raw.start_date!, raw.end_date) > 365))
      )
        throw new Error("Enter a name and 1–366 valid calendar days.");
      const existing = doc.runs.find((r) => r.id === raw.id);
      if (raw.id && !existing) throw new Error("Unknown run.");
      if (existing)
        Object.assign(existing, {
          name: raw.name.trim(),
          start_date: raw.start_date!,
          end_date: raw.end_date || null,
        });
      else {
        const view = buildRoom(this.states(), room);
        const previews = view.zones.map((zone) => ({
          zone,
          preview: buildSetpointPreview(view, this.states(), zone.id, {}),
        }));
        const first = previews[0]?.preview.draft;
        doc.runs.push({
          id: createUuid(),
          room_id: room.id,
          name: raw.name.trim(),
          start_date: raw.start_date!,
          end_date: raw.end_date || null,
          time_zone: doc.time_zone,
          archived: false,
          captured_at: new Date().toISOString(),
          reference_source: "Demo configuration captured at registration",
          lights: {
            on: Number.isFinite(first?.lightsOn) ? first!.lightsOn : null,
            off: Number.isFinite(first?.lightsOff) ? first!.lightsOff : null,
          },
          zones: previews.map(({ zone, preview }) => {
            const count = preview.fields.plant_count?.value;
            return {
              zone_id: zone.id,
              name: zone.name,
              vwc_sensor: zone.vwc.entityId,
              ec_sensor: zone.ec.entityId,
              plant_count: count && Number.isInteger(count) && count > 0 ? count : null,
              reference_source: `Demo ${preview.source} reference`,
              parameters: Object.fromEntries(
                Object.entries(preview.draft.parameters).filter(([key]) =>
                  runParameterKeys.has(key),
                ),
              ),
            };
          }),
        });
      }
    } else if (action === "runs_archive") {
      const record = doc.runs.find((r) => r.id === data.id);
      if (!record || typeof data.archived !== "boolean") throw new Error("Unknown run.");
      record.archived = data.archived;
    } else if (action === "runs_import") {
      const incoming = data.runs as RunRecord[];
      if (!Array.isArray(incoming) || incoming.length > 100)
        throw new Error("Import at most 100 runs.");
      for (const run of incoming) {
        if (
          run.room_id !== room.id ||
          !run.id ||
          !run.name ||
          run.name.length > 80 ||
          !validDate(run.start_date) ||
          !Array.isArray(run.zones) ||
          !run.zones.length ||
          run.zones.length > 24
        )
          throw new Error("Invalid room-scoped run import.");
        if (
          run.end_date &&
          (!validDate(run.end_date) ||
            daysBetween(run.start_date, run.end_date) < 0 ||
            daysBetween(run.start_date, run.end_date) > 365)
        )
          throw new Error("Invalid run duration.");
        new Intl.DateTimeFormat("en", { timeZone: run.time_zone });
        for (const zone of run.zones) {
          if (
            !Number.isInteger(zone.zone_id) ||
            zone.zone_id < 1 ||
            zone.zone_id > 24 ||
            !zone.parameters ||
            Object.entries(zone.parameters).some(
              ([key, value]) => !runParameterKeys.has(key) || !Number.isFinite(value),
            )
          )
            throw new Error("Invalid run zone reference.");
          for (const metric of ["vwc", "ec"] as const) {
            const id = zone[`${metric}_sensor`];
            if (
              id &&
              ![
                `sensor.crop_steering_${room.prefix}${metric}_zone_${zone.zone_id}`,
                `sensor.crop_steering_${room.prefix}zone_${zone.zone_id}_${metric}`,
              ].includes(id)
            )
              throw new Error("Imported sensor belongs to another room.");
          }
        }
        doc.runs = doc.runs.filter((r) => r.id !== run.id).concat(structuredClone(run));
      }
    } else throw new Error("Unsupported run metadata action.");
    if (doc.runs.length > 100) throw new Error("At most 100 runs per room.");
    doc.revision++;
    this.documents.set(room.id, doc);
    return structuredClone(doc);
  }
}
