/** The demo's grow-day summaries and harvests: generated example data, one summary per zone and grow day of each
 * demo run, so History › Grows and the zone page's "On this day last grow" have something to show. */
import { addDays, dateInZone, daysBetween } from "./comparison";
import type { RunRecord, RunsDocument } from "./comparison-types";
import type { GrowDay, GrowDaysDocument, Harvest, HarvestsDocument } from "./grows";

const round = (v: number, digits = 2) => Math.round(v * 10 ** digits) / 10 ** digits;

function demoDay(run: RunRecord, date: string, zone: number, salt: number): GrowDay {
  const n = daysBetween(run.start_date, date) + 1;
  const wave = Math.sin(n / 6 + zone + salt);
  const peak = 62 + 4 * wave - salt;
  const trough = peak - (9 + 3 * Math.cos(n / 9 + zone) + salt);
  const plants = run.zones.find((z) => z.zone_id === zone)?.plant_count ?? 12;
  const lpp = 0.35 + n * 0.012 + 0.05 * wave + salt * 0.04;
  const rescue = (n + zone * 3 + salt) % 23 === 0;
  return {
    date,
    zone,
    partial: false,
    backfilled: null,
    vwc: { peak: round(peak), trough: round(trough), mean: round((peak + trough) / 2) },
    ec: { min: round(3 + 0.3 * wave + salt * 0.2), max: round(4.6 + 0.4 * wave + salt * 0.2), mean: round(3.8 + 0.35 * wave + salt * 0.2) },
    p0: { dryback_pct: round(6 + 2 * Math.cos(n / 7 + zone) + salt), drop_pts: round(3 + wave), landing: round(trough) },
    night: { rate: round(0.35 + 0.1 * Math.sin(n / 5 + zone), 3), shots: 0 },
    p1_stall: (n + zone + salt) % 31 === 0,
    shots: { ramp: 5, extra: 1, topup: 6 + Math.round(3 + 3 * wave), ...(rescue ? { rescue: 1 } : {}) },
    rescues: rescue ? 1 : 0,
    litres: round(lpp * plants, 2),
    plant_count: plants,
    litres_per_plant: round(lpp, 3),
    alerts: rescue ? ["CS-207"] : [],
    mode: n < 20 ? "Vegetative" : "Generative",
  };
}

export class GrowsDemo {
  private harvests = new Map<string, HarvestsDocument>();
  constructor(
    private runs: (roomId: string) => RunsDocument,
    private now: () => number = Date.now,
  ) {}
  call(action: string, data: Record<string, unknown>): GrowDaysDocument | HarvestsDocument {
    const roomId = String(data.room_id);
    const doc = this.runs(roomId);
    if (action === "grow_days_get" || action === "grow_days_backfill") {
      const days: GrowDay[] = [];
      doc.runs
        .filter((run) => !run.archived)
        .forEach((run, index) => {
          const yesterday = addDays(dateInZone(this.now(), run.time_zone), -1);
          const last = run.end_date && run.end_date < yesterday ? run.end_date : yesterday;
          for (let date = run.start_date; date <= last; date = addDays(date, 1))
            for (const zone of run.zones) days.push(demoDay(run, date, zone.zone_id, index));
        });
      const zone = typeof data.zone === "number" ? data.zone : null;
      const rows = days.filter((d) => zone === null || d.zone === zone);
      const dates = rows.map((d) => d.date).sort();
      return { room_id: roomId, days: rows, first: dates[0] ?? null, last: dates.at(-1) ?? null, count: rows.length };
    }
    let harvests = this.harvests.get(roomId);
    if (!harvests) {
      const finished = doc.runs.filter((run) => run.end_date && !run.archived);
      harvests = {
        room_id: roomId,
        revision: 0,
        harvests: Object.fromEntries(
          finished.map((run, index): [string, Harvest] => [
            run.id,
            {
              harvest_date: run.end_date,
              room: { wet_weight_g: 21_400 - index * 1800, dry_weight_g: 4_820 - index * 420, plants_harvested: null, canopy_m2: 9.6 },
              zones: {},
              plants: [],
              quality: index ? "B" : "A",
              notes: "Demo harvest: generated example data.",
              lab: { thc_pct: 22.4 - index, terpenes: { myrcene: 0.6 } },
            },
          ]),
        ),
      };
      this.harvests.set(roomId, harvests);
    }
    if (action === "runs_set_harvest") {
      if (data.expected_revision !== harvests.revision) throw new Error("Harvests changed. Reload before saving.");
      const next = structuredClone(harvests);
      if (data.harvest === null) delete next.harvests[String(data.run_id)];
      else next.harvests[String(data.run_id)] = data.harvest as Harvest;
      next.revision += 1;
      this.harvests.set(roomId, next);
      harvests = next;
    }
    return structuredClone(harvests);
  }
}
