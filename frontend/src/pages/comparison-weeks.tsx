import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { Empty, number } from "@/components/dashboard";
import { Pill } from "@/components/mini-visuals";
import { counterIds } from "@/components/water-use";
import { addDays, dateInZone, midnight } from "@/lib/comparison";
import type { DailyRanges, RunRecord } from "@/lib/comparison-types";
import { biggestDifferences, NOTICE, runWeeks, type RunWeek } from "@/lib/run-weeks";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";
import { waterParameters } from "@/lib/water-delivery";
import { growDayTotals, mergeDays } from "@/lib/water-use";

const DAY = 86_400_000;
const SOURCES: Record<DailyRanges["source"], string> = {
  statistics: "Home Assistant’s long-term statistics",
  history:
    "Home Assistant’s recorded history, which reaches back only as far as the recorder keeps it",
  demo: "generated demo readings",
};

interface RunData {
  run: RunRecord;
  weeks: RunWeek[];
  /** Where the weeks' figures came from, and what is missing, in words. */
  notes: string[];
}

/** One run's grow weeks for one zone: its daily lows and highs over the run, and its water. A part
 * that cannot load leaves its column empty and says why. */
async function loadRun(
  controller: Controller,
  run: RunRecord,
  zoneId: number,
  signal: AbortSignal,
): Promise<RunData> {
  const notes: string[] = [];
  const registered = run.zones.find((zone) => zone.zone_id === zoneId);
  const live = controller.room.zones.find((zone) => zone.id === zoneId);
  const vwc = registered ? registered.vwc_sensor : (live?.vwc.entityId ?? null);
  const ec = registered ? registered.ec_sensor : (live?.ec.entityId ?? null);
  const now = Date.now();
  const today = dateInZone(now, run.time_zone);
  const last = run.end_date && run.end_date < today ? run.end_date : today;
  if (run.start_date > today) return { run, weeks: [], notes: [`${run.name} starts later.`] };
  const start = midnight(run.start_date, run.time_zone);
  const end = Math.min(now, midnight(addDays(last, 1), run.time_zone));
  let ranges: DailyRanges | null = null;
  const ids = [vwc, ec].filter((id): id is string => !!id);
  if (!ids.length)
    notes.push(`${run.name}: no moisture or pore EC sensor registered for this zone.`);
  else
    try {
      ranges = await controller.dailyRanges({
        entityIds: ids,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        timeZone: run.time_zone,
        signal,
      });
      notes.push(`${run.name}: moisture and pore EC from ${SOURCES[ranges.source]}.`);
      notes.push(...ranges.warnings.map((warning) => `${run.name}: ${warning}`));
    } catch (error) {
      notes.push(`${run.name}: moisture and pore EC could not load: ${errorText(error)}`);
    }
  let water = new Map<string, number>();
  const counters = live ? counterIds(controller, live) : [];
  const lightsOn =
    run.lights.on ??
    controller.room.settings.find((field) => field.entityId.endsWith("_lights_on_hour"))?.value ??
    null;
  if (counters.length && lightsOn !== null)
    try {
      const record = await controller.waterRecord({ entityIds: counters, start: start - DAY, end });
      water = mergeDays(
        ...counters.map((id) => growDayTotals(record.samples[id] ?? [], lightsOn, run.time_zone)),
      );
    } catch (error) {
      notes.push(`${run.name}: water could not load: ${errorText(error)}`);
    }
  else
    notes.push(`${run.name}: this zone has no water counter or lights-on hour to count water by.`);
  const plants =
    registered?.plant_count ?? (live ? waterParameters(controller, zoneId).plant_count : null);
  if (!plants) notes.push(`${run.name}: no plant count, so no water per plant.`);
  const daily = (id: string | null) =>
    ranges?.series.find((series) => series.entityId === id)?.daily ?? [];
  return {
    run,
    weeks: runWeeks({
      start: run.start_date,
      last,
      today,
      vwc: daily(vwc),
      ec: daily(ec),
      water,
      plants: plants ?? null,
    }),
    notes,
  };
}

/** "14–20 Sep": a week's dates, as calendar dates (no time zone of their own). */
const span = (first: string, last: string) =>
  new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).formatRange(new Date(first + "T12:00:00Z"), new Date(last + "T12:00:00Z"));
const range = (value: [number, number] | null, digits: number) =>
  value ? `${number(value[0], digits)}–${number(value[1], digits)}` : null;

/** A figure for this run, and under it the compared run's in grey. */
function Figure({
  mine,
  theirs,
  unit,
  compared,
}: {
  mine: string | null;
  theirs: string | null | undefined;
  unit: string;
  compared: boolean;
}) {
  return (
    <td>
      <span className="rw-this">{mine === null ? "—" : `${mine}${unit}`}</span>
      {compared && (
        <span className="rw-other">
          <span className="sr-only">Compared run: </span>
          {theirs === null || theirs === undefined ? "—" : `${theirs}${unit}`}
        </span>
      )}
    </td>
  );
}

/** Compare runs' main view: this run against a chosen one by grow week (moisture, pore EC and water
 * per plant a day), and the few weeks where they differ most. */
export function RunWeeks({
  controller,
  current,
  previous,
  zoneId,
  zoneName,
  refresh,
  onNotes,
}: {
  controller: Controller;
  current: RunRecord | null;
  previous: RunRecord | null;
  zoneId: number;
  zoneName: string;
  refresh: number;
  /** Where the figures came from, for the page's Data quality section. */
  onNotes: (notes: string[]) => void;
}) {
  const [data, setData] = useState<{ mine: RunData; theirs: RunData | null } | null>(null);
  const [loading, setLoading] = useState(false);
  const key = JSON.stringify(
    [current, previous].map((run) => run && [run.id, run.start_date, run.end_date]),
  );
  useEffect(() => {
    setData(null);
    onNotes([]);
    if (!current || !zoneId) return;
    const abort = new AbortController();
    setLoading(true);
    Promise.all([
      loadRun(controller, current, zoneId, abort.signal),
      previous ? loadRun(controller, previous, zoneId, abort.signal) : Promise.resolve(null),
    ])
      .then(([mine, theirs]) => {
        if (abort.signal.aborted) return;
        setData({ mine, theirs });
        onNotes([...mine.notes, ...(theirs?.notes ?? [])]);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [controller.roomId, controller.dailyRanges, controller.waterRecord, key, zoneId, refresh]);
  if (!current)
    return (
      <section className="panel run-weeks">
        <Empty
          title="Choose this run"
          detail="Pick the run in progress above, and a past one to compare it with, to see them week by week."
        />
      </section>
    );
  const weeks = Math.max(data?.mine.weeks.length ?? 0, data?.theirs?.weeks.length ?? 0);
  const differences = data?.theirs ? biggestDifferences(data.mine.weeks, data.theirs.weeks) : [];
  return (
    <section className="panel run-weeks" aria-labelledby="run-weeks-title">
      <div className="panel-heading">
        <div>
          <h2 id="run-weeks-title">By grow week</h2>
          <p>
            {zoneName}: each week’s typical day, the median of its daily lows and of its daily
            highs.
          </p>
        </div>
        <div className="rw-key" aria-hidden="true">
          <span>
            <i className="rw-key-this" />
            {current.name}
          </span>
          {previous && (
            <span>
              <i className="rw-key-other" />
              {previous.name}
            </span>
          )}
        </div>
      </div>
      {loading || !data ? (
        <div className="chart-placeholder" role="status">
          <LoaderCircle className="spin" /> Loading both runs’ records…
        </div>
      ) : (
        <>
          {data.theirs && (
            <div className="rw-differences" aria-label="Biggest differences">
              <h3>Biggest differences</h3>
              {differences.length ? (
                <ul>
                  {differences.map((item) => (
                    <li key={`${item.week}-${item.metric}`} data-metric={item.metric}>
                      {item.text}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">
                  No week differs by {NOTICE.moisture} points of moisture, {NOTICE.poreEc} of pore
                  EC or a fifth of the water per plant.
                </p>
              )}
            </div>
          )}
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Runs by grow week">
            <table className="data-table rw-table">
              <thead>
                <tr>
                  <th scope="col">Grow week</th>
                  <th scope="col">Moisture, low–high</th>
                  <th scope="col">Pore EC, low–high</th>
                  <th scope="col">Water per plant a day</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: weeks }, (_, index) => {
                  const mine = data.mine.weeks[index];
                  const theirs = data.theirs?.weeks[index];
                  const compared = !!data.theirs;
                  return (
                    <tr key={index} data-current={mine?.current || undefined}>
                      <th scope="row">
                        Week {index + 1}
                        {mine?.current && (
                          <>
                            {" "}
                            <Pill tone="water">This week</Pill>
                          </>
                        )}
                        <small>
                          {mine
                            ? `${span(mine.first, mine.last)}${mine.recorded < mine.days ? ` · ${mine.recorded} of ${mine.days} days recorded` : ""}`
                            : "not reached yet"}
                        </small>
                      </th>
                      <Figure
                        mine={mine ? range(mine.moisture, 0) : null}
                        theirs={theirs && range(theirs.moisture, 0)}
                        unit=" %"
                        compared={compared}
                      />
                      <Figure
                        mine={mine ? range(mine.poreEc, 1) : null}
                        theirs={theirs && range(theirs.poreEc, 1)}
                        unit=""
                        compared={compared}
                      />
                      <Figure
                        mine={mine?.water == null ? null : number(mine.water, 2)}
                        theirs={theirs?.water == null ? null : number(theirs.water, 2)}
                        unit=" L"
                        compared={compared}
                      />
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="small">
            Weeks count seven days from each run’s start date. A dash is a week with no record,
            never a zero. Water per plant averages the week’s recorded grow-days, today’s unfinished
            one left out. Where the figures come from is under Data quality.
          </p>
        </>
      )}
    </section>
  );
}
