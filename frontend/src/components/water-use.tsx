import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { CircleHelp, LoaderCircle } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Empty, number } from "@/components/dashboard";
import { numeric } from "@/lib/model";
import type { StrategyDocument } from "@/lib/operator-types";
import type { Controller, Zone } from "@/lib/types";
import { errorText } from "@/lib/utils";
import {
  growDayOf,
  growDayTotals,
  inferStart,
  mergeDays,
  resolveStart,
  zoneWaterUse,
  type GrowStart,
  type WaterRecord,
  type ZoneWaterUse,
} from "@/lib/water-use";
import "./water-use.css";

/** The zone colours of the history chart. */
const palette = ["#03a9f4", "#e5a43b", "#a57bf3", "#e97d98", "#43bdab"];
const DAY = 86_400_000;
/** How far back to look for the start of a grow that no grow plan dates. */
const LOOKBACK_DAYS = 120;

/** A zone's water-today counters: the one the dashboard shows first, then the controller's sensor
 * and the integration's mirror of it, which can hold grow-days the first one lacks. */
function counterIds(controller: Controller, zone: Zone): string[] {
  const root = `sensor.crop_steering_${controller.room.room.prefix}zone_${zone.id}_daily_water_`;
  return [...new Set([zone.water.entityId, root + "app", root + "usage"])].filter(
    (id): id is string => !!id && !!controller.states[id],
  );
}
const noon = (day: string) => new Date(day + "T12:00:00Z");
function dates(first: string, last: string, today: string) {
  const format = new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    ...(first.slice(0, 4) !== today.slice(0, 4) ? { year: "numeric" } : {}),
    timeZone: "UTC",
  });
  return first === last ? format.format(noon(first)) : format.formatRange(noon(first), noon(last));
}
const clock = (hour: number) => {
  const minutes = Math.round(hour * 60);
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
};
const litres = (value: number | null, digits = 2) =>
  value === null ? "Unavailable" : `${number(value, digits)} L`;
const missing = (count: number) =>
  count ? ` · ${count} ${count === 1 ? "day" : "days"} not recorded` : "";

/** A tooltip on hover and keyboard focus, in CSS: the Radix one would add its positioning library
 * to the bundle for two notes. */
function Hint({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <span className="wu-hint">
      <button type="button" aria-label={label} aria-describedby={id}>
        <CircleHelp size={15} />
      </button>
      <span role="tooltip" id={id}>
        {children}
      </span>
    </span>
  );
}
function startText(start: GrowStart, today: string) {
  const day = dates(start.date, start.date, today);
  return start.source === "plan"
    ? `${day}, from the armed grow plan`
    : start.source === "draft"
      ? `${day}, from the saved grow plan (a draft, not armed)`
      : start.source === "inferred"
        ? `${day}, inferred: the first day with water after ${start.afterDry} days without any`
        : `on or before ${day}, when the records begin`;
}

export function WaterUse({ controller, zones }: { controller: Controller; zones: Zone[] }) {
  const room = controller.room;
  const lightsOn = room.settings.find((field) => field.entityId.endsWith("_lights_on_hour"))?.value;
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const today =
    lightsOn === undefined || lightsOn === null ? null : growDayOf(Date.now(), lightsOn, timeZone);
  const series = room.zones.map((zone) => ({ zone, ids: counterIds(controller, zone) }));
  const key = series.flatMap((item) => item.ids).join("|");
  const connected = ["live", "demo"].includes(controller.connection);
  const [loaded, setLoaded] = useState<{ plan: StrategyDocument | null; record: WaterRecord }>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!connected || !key || !today) return;
    let current = true;
    setError("");
    (async () => {
      // An older integration has no grow plans; the start is then inferred from the record.
      const plan = await controller.operator<StrategyDocument>("strategy_get").catch(() => null);
      const starts = room.zones.map((zone) => resolveStart(plan, zone.id, today, null)?.date);
      const earliest = starts.every(Boolean) ? (starts as string[]).sort()[0] : null;
      const end = Date.now();
      // A day before the earliest start (the counter's level going into it), and at least the
      // eight grow-days the week and the average need; without a dated start, far enough back to
      // find where the grow began.
      const start = Math.max(
        end - 400 * DAY,
        Math.min(
          end - 9 * DAY,
          earliest ? Date.parse(earliest) - 2 * DAY : end - LOOKBACK_DAYS * DAY,
        ),
      );
      const record = await controller.waterRecord({ entityIds: key.split("|"), start, end });
      if (current) setLoaded({ plan, record });
    })().catch((reason) => {
      if (current) setError(errorText(reason));
    });
    return () => {
      current = false;
    };
  }, [controller.roomId, connected, key, today, retry]);
  // Today's value is the live counter; the record supplies every grow-day before it.
  const live = series.flatMap((item) => item.ids.map((id) => controller.states[id]?.state));
  const rows = useMemo(() => {
    if (!loaded || !today || lightsOn === undefined || lightsOn === null) return null;
    const now = Date.now();
    const zoneDays = series.map(({ zone, ids }) => ({
      zone,
      days: mergeDays(
        ...ids.map((id) => {
          const value = numeric(controller.states[id]);
          const samples = loaded.record.samples[id] ?? [];
          return growDayTotals(
            value === null ? samples : [...samples, { time: now, value }],
            lightsOn,
            timeZone,
          );
        }),
      ),
    }));
    const inferred = inferStart(
      zoneDays.map((item) => item.days),
      today,
    );
    return zoneDays.map(({ zone, days }) => {
      const start = resolveStart(loaded.plan, zone.id, today, inferred);
      return { zone, days, start, use: zoneWaterUse(days, today, start) };
    });
  }, [loaded, today, lightsOn, timeZone, key, live.join("|")]);
  if (!zones.length) return null;
  const shown = (rows ?? []).filter((row) => zones.some((zone) => zone.id === row.zone.id));
  const recorded = shown.some((row) => row.days.size);
  return (
    <section className="panel wu-panel" aria-labelledby="water-use-title">
      <div className="panel-heading">
        <div>
          <h2 id="water-use-title">Water use</h2>
          <p>
            Litres per zone, all plants
            {lightsOn !== undefined && lightsOn !== null
              ? `. A grow-day runs from lights-on (${clock(lightsOn)}) to the next lights-on.`
              : "."}
          </p>
        </div>
      </div>
      {!key ? (
        <Empty
          title="No water counters"
          detail="This room’s zones do not report the water they received today, so there is nothing to total."
        />
      ) : !today ? (
        <Empty
          title="Lights-on hour unavailable"
          detail="Water use is counted in grow-days from lights-on, and this room does not report its lights-on hour."
        />
      ) : error ? (
        <Empty
          title="Water records could not load"
          detail={error}
          action={
            <Button variant="outline" onClick={() => setRetry((value) => value + 1)}>
              Retry
            </Button>
          }
        />
      ) : !rows ? (
        <div className="chart-placeholder wu-loading" role="status">
          {connected ? (
            <>
              <LoaderCircle className="spin" /> Loading recorded water…
            </>
          ) : (
            "Connect to Home Assistant to load recorded water."
          )}
        </div>
      ) : !recorded ? (
        <Empty
          title="No water recorded yet"
          detail="Totals appear once Home Assistant has recorded the zones’ water-today counters. Missing days are never counted as zero."
        />
      ) : (
        <WaterUseBody
          rows={shown}
          colours={new Map(room.zones.map((zone, index) => [zone.id, palette[index % 5]]))}
          today={today}
          lightsOn={lightsOn!}
          source={loaded!.record.source}
        />
      )}
    </section>
  );
}

/** A table cell: the figure, and underneath what it covers. */
function Figure({ label, value, notes }: { label: string; value: string; notes: string[] }) {
  return (
    <td data-label={label}>
      <div className="wu-value">
        <strong>{value}</strong>
        {notes.map((note) => (
          <small key={note}>{note}</small>
        ))}
      </div>
    </td>
  );
}
type Row = {
  zone: Zone;
  days: Map<string, number>;
  start: GrowStart | null;
  use: ZoneWaterUse;
};
function WaterUseBody({
  rows,
  colours,
  today,
  lightsOn,
  source,
}: {
  rows: Row[];
  colours: Map<number, string>;
  today: string;
  lightsOn: number;
  source: WaterRecord["source"];
}) {
  const starts = [...new Set(rows.map((row) => (row.start ? startText(row.start, today) : "")))];
  const shared = starts.length === 1 ? rows[0].start : undefined;
  const firstRecorded = rows
    .flatMap((row) => [...row.days.keys()])
    .sort()
    .at(0);
  const weeks = Math.max(0, ...rows.map((row) => row.use.weeks.length));
  const chart = Array.from({ length: weeks }, (_, index) => {
    const values = rows.map((row) => row.use.weeks[index]);
    return {
      label: `Wk ${index + 1}`,
      week: index + 1,
      // The week still running (a zone with a later start reaches it at a lower index).
      partial: values.some((week) => week?.last === today),
      span: shared && values[0] ? dates(values[0].first, values[0].last, today) : "",
      ...Object.fromEntries(
        rows.map((row, zone) => [
          `z${row.zone.id}`,
          values[zone] && values[zone].missing < values[zone].days ? values[zone].litres : null,
        ]),
      ),
    };
  });
  return (
    <>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Water use by zone">
        <table className="data-table wu-table">
          <thead>
            <tr>
              <th scope="col">Zone</th>
              <th scope="col">Today</th>
              <th scope="col">
                <span className="wu-th">
                  This week
                  <Hint label="How this week is counted">
                    {rows.every((row) => row.use.week.growWeek)
                      ? "The current grow week: grow-days counted in sevens from the grow start, today included."
                      : rows.some((row) => row.use.week.growWeek)
                        ? "The current grow week where a zone has a grow start, otherwise the last 7 grow-days, today included."
                        : "The last 7 grow-days, today included: there is no grow start to count weeks from."}
                  </Hint>
                </span>
              </th>
              <th scope="col">Since grow start</th>
              <th scope="col">
                <span className="wu-th">
                  Estimated total
                  <Hint label="How the estimate is made">
                    Used so far plus the last 7 full grow-days’ average for every grow-day left in
                    the grow plan. Without a plan length: that average for 7 days, per week.
                  </Hint>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ zone, use }) => (
              <tr key={zone.id}>
                <td data-label="Zone" className="wu-zone">
                  <span>
                    <i style={{ background: colours.get(zone.id) }} />
                    {zone.name}
                  </span>
                </td>
                <Figure
                  label="Today"
                  value={litres(use.today.litres)}
                  notes={[`${dates(use.today.day, use.today.day, today)} from ${clock(lightsOn)}`]}
                />
                <Figure
                  label="This week"
                  value={litres(use.week.litres)}
                  notes={[
                    `${use.week.growWeek ? `Week ${use.week.growWeek}` : "Last 7 grow-days"} · ${dates(use.week.first, use.week.last, today)}${missing(use.week.missing)}`,
                  ]}
                />
                <Figure
                  label="Since grow start"
                  {...(use.sinceStart
                    ? {
                        value: litres(use.sinceStart.litres),
                        notes: [
                          `${dates(use.sinceStart.first, use.sinceStart.last, today)} · grow-day ${use.growDay}${use.sinceStart.recordsBegin ? " · earlier days not recorded" : ""}${missing(use.sinceStart.missing)}`,
                        ],
                      }
                    : { value: "Unavailable", notes: ["No grow start"] })}
                />
                <Figure
                  label="Estimated total"
                  {...(use.average && (use.estimate || use.perWeek !== null)
                    ? {
                        value: use.estimate
                          ? `≈ ${litres(use.estimate.total, 0)}`
                          : `≈ ${litres(use.perWeek, 0)} a week`,
                        notes: [
                          `At the last 7 days’ average, ${number(use.average.perDay, 1)} L/day`,
                          use.estimate
                            ? `${use.estimate.planDays}-day plan, ${use.estimate.daysLeft} grow-days left`
                            : "The plan length is missing",
                        ],
                      }
                    : { value: "Not yet", notes: ["Needs one full recorded grow-day"] })}
                />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="wu-notes">
        <p>
          {shared
            ? `Grow start: ${startText(shared, today)}.`
            : starts.length > 1
              ? `Grow start by zone: ${rows
                  .map(
                    (row) => `${row.zone.name} ${row.start ? startText(row.start, today) : "none"}`,
                  )
                  .join("; ")}.`
              : "No grow start: no zone has had water recently and no grow plan is armed."}{" "}
          {rows.some((row) => !row.start || ["inferred", "records"].includes(row.start.source))
            ? "To count from the grow’s real start, save it as a grow plan’s start date on the Irrigation plan page; the plan does not need arming."
            : ""}
        </p>
        <p>
          {source === "statistics"
            ? "From Home Assistant’s hourly long-term statistics of each zone’s water-today counter."
            : source === "history"
              ? `From Home Assistant’s recorded history, which reaches back only to ${firstRecorded ? dates(firstRecorded, firstRecorded, today) : "today"} here; inside Home Assistant this panel reads its long-term statistics instead.`
              : "Demo data."}{" "}
          The controller’s recorded delivery; a grow-day with no record adds nothing and is flagged
          as not recorded.
        </p>
      </div>
      {weeks > 0 && (
        <div className="wu-chart">
          <div className="wu-chart-head">
            <h3>Litres per grow week</h3>
            <div className="chart-legend wu-legend">
              {rows.map((row) => (
                <span key={row.zone.id}>
                  <i style={{ background: colours.get(row.zone.id) }} />
                  {row.zone.name}
                </span>
              ))}
            </div>
          </div>
          <div
            className="chart-wrap wu-bars"
            role="img"
            aria-label={`Litres per grow week for ${rows.map((row) => row.zone.name).join(", ")}, weeks 1 to ${weeks}; the current week so far.`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart} margin={{ top: 8, right: 4, bottom: 0, left: 4 }}>
                <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="label"
                  tickLine={false}
                  axisLine={false}
                  stroke="var(--muted-foreground)"
                  interval="preserveStartEnd"
                  minTickGap={8}
                />
                <YAxis
                  width={60}
                  tickLine={false}
                  axisLine={false}
                  stroke="var(--muted-foreground)"
                  tickFormatter={(value) => litres(Number(value), 0)}
                />
                <Tooltip
                  cursor={{ fill: "var(--muted)" }}
                  contentStyle={{
                    background: "var(--surface)",
                    color: "var(--foreground)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                  }}
                  itemStyle={{ color: "var(--foreground)" }}
                  labelFormatter={(_, items) => {
                    const row = items?.[0]?.payload as (typeof chart)[number] | undefined;
                    return row
                      ? `Week ${row.week}${row.span ? ` · ${row.span}` : ""}${row.partial ? " (so far)" : ""}`
                      : "";
                  }}
                  formatter={(value, name) => [litres(Number(value)), name]}
                />
                {rows.map((row) => (
                  <Bar
                    key={row.zone.id}
                    dataKey={`z${row.zone.id}`}
                    name={row.zone.name}
                    fill={colours.get(row.zone.id)}
                    radius={[3, 3, 0, 0]}
                    maxBarSize={44}
                    isAnimationActive={false}
                  >
                    {chart.map((week, index) => {
                      const running = row.use.weeks[index]?.last === today;
                      return (
                        <Cell
                          key={week.week}
                          fillOpacity={running ? 0.4 : 1}
                          stroke={running ? colours.get(row.zone.id) : undefined}
                          strokeDasharray={running ? "4 3" : undefined}
                        />
                      );
                    })}
                  </Bar>
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="wu-caption">
            Weeks count seven grow-days from the grow start. The current week is still running
            (pale, outlined bars).
          </p>
        </div>
      )}
    </>
  );
}
