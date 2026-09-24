import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ChartLine, LoaderCircle, Settings2 } from "lucide-react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Empty } from "@/components/dashboard";
import { whileVisible } from "@/lib/live";
import { historySpan, latestOnly } from "@/lib/sensor-context";
import {
  MIN_SPAN,
  TANK_RANGES,
  chartDivisor,
  chartRows,
  describeLine,
  gateText,
  mergeWindow,
  rangeTicks,
  sourceGate,
  sparkPath,
  tankAxis,
  tankLine,
  tickLabel,
  type TankKey,
  type TankLine,
} from "@/lib/tank-history";
import type { TankReading } from "@/lib/tank-telemetry";
import type { Controller, Series } from "@/lib/types";
import { errorText } from "@/lib/utils";
import "./tank-history.css";

const HOUR = 3_600_000;
const REFRESH_MS = 60_000;
const KEYS = ["ec", "ph"] as const;
const NAMES: Record<TankKey, { name: string; unit: string; axis: string; units: string }> = {
  ec: { name: "EC", unit: " mS/cm", axis: "left axis, mS/cm", units: "mS/cm, dS/m or µS/cm" },
  ph: { name: "pH", unit: "", axis: "right axis", units: "pH" },
};
/** A gate line's label sits outside the band (recharts' "insideBottom" is above a line), at the
 * end of the line's own axis. */
const LABEL_AT = {
  ec: { max: "insideBottomLeft", min: "insideTopLeft" },
  ph: { max: "insideBottomRight", min: "insideTopRight" },
} as const;
const trim = (value: number) => String(Number(value.toFixed(2)));
const clock = (time: number) =>
  new Date(time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const moment = (time: number) =>
  new Date(time).toLocaleString([], {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

export interface TankHistoryData {
  /** Null until something is loaded for this room, these probes and this range. */
  series: Series[] | null;
  /** When `series` was loaded. */
  at: number | null;
  loading: boolean;
  error: string;
  retry: () => void;
}
/** Recorded tank readings over one range: the whole range first, then each minute the page is
 * visible only what was recorded since. Loads only while connected and `enabled`; what it loaded
 * stays on screen after a disconnect, as the last known readings. */
export function useTankHistory(
  controller: Controller,
  ids: string[],
  hours: number,
  enabled: boolean,
): TankHistoryData {
  const [held, setHeld] = useState<{ key: string; series: Series[]; at: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [guard] = useState(() => latestOnly<Series[]>());
  const probes = ids.join("|");
  const key = `${controller.roomId}|${probes}|${hours}`;
  const history = controller.history;
  const active = enabled && !!probes && ["live", "demo"].includes(controller.connection);
  useEffect(() => {
    if (!active) {
      guard.cancel();
      setLoading(false);
      return;
    }
    // Ends whatever this run started, the rest of a month's day-sized requests included.
    const abort = new AbortController();
    let loadedAt: number | null = null,
      busy = false;
    const load = () => {
      // A month of a busy probe can take longer than the refresh interval to arrive.
      if (busy) return;
      busy = true;
      const since = loadedAt;
      // Stamped when asked, not when answered: the window then starts no later than the one the
      // recorder read, and the next slice starts no later than this one ended.
      const at = Date.now();
      setLoading(true);
      if (since === null) setError("");
      guard.run(
        () => history(probes.split("|"), historySpan(hours, since, at), abort.signal),
        (result) => {
          busy = false;
          setLoading(false);
          if (!result.ok) return setError(errorText(result.error));
          loadedAt = at;
          setHeld((current) =>
            since === null || current?.key !== key
              ? { key, series: result.value, at }
              : { key, series: mergeWindow(current.series, result.value, at - hours * HOUR), at },
          );
          setError("");
        },
      );
    };
    load();
    // Only while the page is visible; showing it again catches up at once.
    const stop = whileVisible(load, REFRESH_MS);
    return () => {
      guard.cancel();
      abort.abort();
      stop();
    };
  }, [active, key, probes, hours, attempt, history, guard]);
  const current = held?.key === key ? held : null;
  return {
    series: current?.series ?? null,
    at: current?.at ?? null,
    loading,
    error,
    retry: () => setAttempt((value) => value + 1),
  };
}

/** Each mapped reading's recorded line in chart units, thinned to `maximum` points; null when it
 * is unmapped, not loaded, or in a unit the chart's axis cannot take. */
export function useTankLines(
  controller: Controller,
  readings: Record<TankKey, TankReading>,
  data: TankHistoryData,
  hours: number,
  maximum: number,
): Record<TankKey, TankLine | null> {
  const ecId = readings.ec.entityId,
    phId = readings.ph.entityId;
  // Divisors, not the states they come from: a live update must not re-read a month of history.
  const ecDivisor = ecId ? chartDivisor("ec", controller.states[ecId]) : null,
    phDivisor = phId ? chartDivisor("ph", controller.states[phId]) : null;
  const { series, at } = data;
  return useMemo(() => {
    const line = (id: string | null, divisor: number | null) =>
      id && divisor !== null && series && at !== null
        ? tankLine(
            series.find((item) => item.entityId === id),
            hours,
            at,
            divisor,
            maximum,
          )
        : null;
    return { ec: line(ecId, ecDivisor), ph: line(phId, phDivisor) };
  }, [series, at, hours, maximum, ecId, phId, ecDivisor, phDivisor]);
}

const SPARK = { width: 64, height: 20 };
/** The last day of one tank reading, drawn small beside its value. */
export function TankSparkline({
  which,
  line,
  end,
}: {
  which: TankKey;
  line: TankLine | null;
  end: number | null;
}) {
  if (!line?.lowest || !line.highest || end === null) return null;
  const path = sparkPath(
    line.plot,
    end - 24 * HOUR,
    end,
    SPARK.width,
    SPARK.height,
    MIN_SPAN[which],
  );
  if (!path) return null;
  const { name, unit } = NAMES[which];
  return (
    <svg
      className="tank-spark"
      data-tank-spark={which}
      viewBox={`0 0 ${SPARK.width} ${SPARK.height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`${name} over the last 24 h: ${trim(line.lowest.value)} to ${trim(line.highest.value)}${unit}`}
    >
      <path d={path} />
    </svg>
  );
}

/** Tank EC and pH over time, in a panel beside the Overview: the Overview itself carries no full
 * graphs. The last day is the card's own load; a week or a month loads while the panel is open. */
export function TankHistory({
  controller,
  ec,
  ph,
  recent,
  onConfigure,
}: {
  controller: Controller;
  ec: TankReading;
  ph: TankReading;
  recent: TankHistoryData;
  onConfigure: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [hours, setHours] = useState<number>(TANK_RANGES[0].hours);
  const ids = [ec.entityId, ph.entityId].filter((id): id is string => !!id);
  const longer = useTankHistory(controller, ids, hours, open && hours !== 24);
  const data = hours === 24 ? recent : longer;
  const connected = ["live", "demo"].includes(controller.connection);
  const mapSensors = (
    <Button
      variant="outline"
      onClick={() => {
        setOpen(false);
        onConfigure();
      }}
    >
      <Settings2 size={16} /> Map sensors
    </Button>
  );
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      {/* The trigger gets focus back when the panel closes and announces open or closed. */}
      <SheetTrigger asChild>
        <Button variant="ghost">
          <ChartLine size={16} /> History
        </Button>
      </SheetTrigger>
      <SheetContent className="tank-history-sheet">
        <SheetHeader>
          <SheetTitle>Tank EC and pH</SheetTitle>
          <SheetDescription>
            {controller.room.room.name} · batch tank readings over time
          </SheetDescription>
        </SheetHeader>
        <div className="tank-history-body" data-tank-history>
          <div className="tank-history-range" role="group" aria-label="History range">
            {TANK_RANGES.map((option) => (
              <button
                type="button"
                key={option.hours}
                aria-pressed={hours === option.hours}
                onClick={() => setHours(option.hours)}
              >
                {option.label}
              </button>
            ))}
          </div>
          {!ids.length ? (
            <Empty
              title="Tank EC and pH are not mapped"
              detail="Map the tank’s EC and pH sensors in Rooms & setup to chart them here."
              action={mapSensors}
            />
          ) : data.series === null ? (
            data.error ? (
              <Empty
                title="History could not load"
                detail={data.error}
                action={
                  <Button variant="outline" onClick={data.retry}>
                    Retry history
                  </Button>
                }
              />
            ) : !connected ? (
              <Empty
                title="Not connected to Home Assistant"
                detail="Recorded history loads while Home Assistant is connected. Nothing was loaded for this range before the connection dropped."
              />
            ) : (
              <div className="chart-placeholder tank-history-loading" role="status">
                <LoaderCircle className="spin" />
                Loading recorded history…
              </div>
            )
          ) : (
            <TankChart
              controller={controller}
              readings={{ ec, ph }}
              data={data}
              hours={hours}
              connected={connected}
              mapSensors={mapSensors}
            />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function TankChart({
  controller,
  readings,
  data,
  hours,
  connected,
  mapSensors,
}: {
  controller: Controller;
  readings: Record<TankKey, TankReading>;
  data: TankHistoryData;
  hours: number;
  connected: boolean;
  mapSensors: ReactNode;
}) {
  const lines = useTankLines(controller, readings, data, hours, 800);
  const rows = useMemo(
    () => chartRows(lines.ec?.plot ?? [], lines.ph?.plot ?? []),
    [lines.ec, lines.ph],
  );
  const end = data.at!,
    start = end - hours * HOUR;
  const range = TANK_RANGES.find((option) => option.hours === hours)?.label ?? `${hours} h`;
  const gates = {
    ec: sourceGate(controller.states, controller.room.room, "ec"),
    ph: sourceGate(controller.states, controller.room.room, "ph"),
  };
  const gateNotes = {
    ec: gateText(gates.ec, "ec", readings.ec.entityId),
    ph: gateText(gates.ph, "ph", readings.ph.entityId),
  };
  const drawn = KEYS.filter((key) => lines[key]?.latest);
  const axes = {} as Record<TankKey, ReturnType<typeof tankAxis>>;
  for (const key of KEYS)
    axes[key] = tankAxis(
      (lines[key]?.plot ?? []).flatMap((point) => (point.value === null ? [] : [point.value])),
      gateNotes[key].active
        ? [gates[key].min, gates[key].max].filter((limit): limit is number => limit !== null)
        : [],
      MIN_SPAN[key],
    );
  // A limit far from the readings is not drawn (it would flatten them); the gate list names it.
  const gateLines = KEYS.flatMap((key) =>
    (["min", "max"] as const).flatMap((bound) => {
      const value = gates[key][bound];
      return value !== null && axes[key]?.limits.includes(value)
        ? [{ key, bound, value, label: `${NAMES[key].name} ${bound} ${trim(value)}` }]
        : [];
    }),
  );
  const first = Math.min(...drawn.map((key) => lines[key]!.readings[0].time));
  const notes = KEYS.flatMap((key) => {
    const { name, units } = NAMES[key],
      id = readings[key].entityId;
    if (!id) return [{ key, text: `Tank ${name} is not mapped.`, map: true }];
    if (!lines[key]) {
      const unit = String(controller.states[id]?.attributes.unit_of_measurement ?? "");
      return [
        {
          key,
          text: `Tank ${name} is not charted: ${id} reports in “${unit}”, not ${units}.`,
          map: true,
        },
      ];
    }
    return !lines[key]!.latest && drawn.length
      ? [{ key, text: `No recorded ${name} readings in this range.`, map: false }]
      : [];
  });
  const summary = [
    `Tank EC and pH over the last ${range}`,
    ...KEYS.filter((key) => readings[key].entityId).map((key) =>
      describeLine(NAMES[key].name, NAMES[key].unit, lines[key]),
    ),
    ...(gateLines.length ? ["Dashed lines mark the source-water gate"] : []),
  ].join(". ");
  return (
    <>
      {!drawn.length ? (
        <Empty
          title="No recorded readings in this range"
          detail={`Home Assistant has no stored tank EC or pH readings for the last ${range}. Nothing is drawn in their place.`}
        />
      ) : (
        <>
          <div className="tank-history-key" aria-hidden="true">
            {drawn.map((key) => (
              <span key={key}>
                <i className={`tank-key-${key}`} />
                {NAMES[key].name} · {NAMES[key].axis}
              </span>
            ))}
            {gateLines.length > 0 && (
              <span>
                <i className="tank-key-gate" />
                Source-water gate
              </span>
            )}
          </div>
          <div className="tank-history-chart" role="img" aria-label={summary} data-tank-chart>
            <ResponsiveContainer width="100%" height="100%">
              {/* The chart is one image with a text alternative and a table: no keyboard stop in it. */}
              <ComposedChart
                data={rows}
                margin={{ top: 14, right: 4, bottom: 2, left: 4 }}
                accessibilityLayer={false}
              >
                <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="time"
                  type="number"
                  scale="time"
                  domain={[start, end]}
                  ticks={rangeTicks(start, end, hours)}
                  tickFormatter={(value) => tickLabel(Number(value), hours)}
                  minTickGap={16}
                  tickLine={false}
                  axisLine={false}
                  stroke="var(--muted-foreground)"
                />
                {KEYS.map((key) => {
                  const axis = axes[key];
                  return (
                    axis &&
                    drawn.includes(key) && (
                      <YAxis
                        key={key}
                        yAxisId={key}
                        orientation={key === "ec" ? "left" : "right"}
                        domain={[axis.min, axis.max]}
                        ticks={axis.ticks}
                        width={key === "ec" ? 40 : 34}
                        tickFormatter={(value) => trim(Number(value))}
                        tickLine={false}
                        axisLine={false}
                        stroke="var(--muted-foreground)"
                      />
                    )
                  );
                })}
                <Tooltip
                  labelFormatter={(value) => moment(Number(value))}
                  formatter={(value, name) => [
                    `${Number(value).toFixed(2)}${name === "EC" ? " mS/cm" : ""}`,
                    name,
                  ]}
                  contentStyle={{
                    background: "var(--surface)",
                    color: "var(--foreground)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                  }}
                  // The series hues are for lines; text stays on the text colour.
                  itemStyle={{ color: "var(--foreground)" }}
                />
                {gateLines.map((line) => (
                  <ReferenceLine
                    key={`${line.key}-${line.bound}`}
                    yAxisId={line.key}
                    y={line.value}
                    stroke={`var(--tank-${line.key})`}
                    strokeDasharray="6 4"
                    strokeWidth={1.25}
                    label={{
                      value: line.label,
                      position: LABEL_AT[line.key][line.bound],
                      className: "tank-gate-label",
                    }}
                  />
                ))}
                {drawn.map((key) => (
                  <Line
                    key={key}
                    yAxisId={key}
                    dataKey={key}
                    name={NAMES[key].name}
                    className={`tank-line-${key}`}
                    type="linear"
                    stroke={`var(--tank-${key})`}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          {first - start > Math.max(2 * HOUR, hours * HOUR * 0.05) && (
            <p className="tank-history-note">
              Readings start {moment(first)}: Home Assistant holds none earlier in this range.
            </p>
          )}
          <table className="tank-history-summary">
            <caption>Last {range}</caption>
            <thead>
              <tr>
                <th scope="col">Reading</th>
                <th scope="col">Latest</th>
                <th scope="col">Lowest</th>
                <th scope="col">Highest</th>
              </tr>
            </thead>
            <tbody>
              {KEYS.filter((key) => readings[key].entityId).map((key) => {
                const line = lines[key];
                const show = (value: number | undefined) =>
                  value === undefined ? "—" : value.toFixed(2);
                return (
                  <tr key={key} data-tank-summary={key}>
                    <th scope="row">
                      {NAMES[key].name}
                      {NAMES[key].unit && <span className="unit">{NAMES[key].unit}</span>}
                    </th>
                    <td>{show(line?.latest?.value)}</td>
                    <td>{show(line?.lowest?.value)}</td>
                    <td>{show(line?.highest?.value)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
      {notes.map((note) => (
        <p className="tank-history-note" key={note.key} data-tank-note={note.key}>
          {note.text}
          {note.map && mapSensors}
        </p>
      ))}
      {!connected && (
        <p className="tank-history-note tank-history-stale" role="status">
          Disconnected: showing the readings loaded at {clock(end)}.
        </p>
      )}
      {connected && data.error && (
        <p className="tank-history-note tank-history-stale" role="status">
          Last refresh failed: {data.error} Showing the readings loaded at {clock(end)}.
        </p>
      )}
      <section className="tank-history-gate">
        <h3>Source-water gate</h3>
        <dl>
          {KEYS.map((key) => (
            <div key={key} data-tank-gate={key} data-active={gateNotes[key].active || undefined}>
              <dt>{NAMES[key].name}</dt>
              <dd>{gateNotes[key].text}</dd>
            </div>
          ))}
        </dl>
        {/* Only the default room, and only until its first save, reads the app options. */}
        {gates.ec.option && (
          <p className="tank-history-note" data-tank-gate-option>
            Until this room is saved in Rooms &amp; setup, the controller app’s own feed_ec_sensor
            and feed_ph_sensor options, when set, name these probes instead.
          </p>
        )}
      </section>
      <p className="tank-history-caption">
        {controller.demo ? "Generated demo history" : "Home Assistant recorder history"} · loaded{" "}
        {clock(end)}
        {connected ? (data.loading ? " · refreshing…" : " · refreshes every minute") : ""}
      </p>
    </>
  );
}
