import { CanonicalControls } from "@/components/canonical-controls";
import { RunRecords } from "@/components/run-records";
import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Empty, number } from "@/components/dashboard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Pill } from "@/components/mini-visuals";
import { dateInZone } from "@/lib/comparison";
import type { RunRecord, RunsDocument } from "@/lib/comparison-types";
import {
  growPoints,
  growStats,
  TREND_MIN_GROWS,
  yieldFigures,
  type GrowDaysDocument,
  type GrowScope,
  type Harvest,
  type HarvestsDocument,
  type HarvestWeights,
} from "@/lib/grows";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";
import "./grows.css";

const MAX_GROWS = 6;
const colour = (index: number) => `var(--grow-${index % MAX_GROWS})`;
const tooltipStyle = {
  background: "var(--surface)",
  color: "var(--foreground)",
  border: "1px solid var(--border)",
  borderRadius: 8,
};
const axis = { tickLine: false, axisLine: false, stroke: "var(--muted-foreground)" } as const;

interface Metric {
  id: string;
  title: string;
  detail: string;
  keys: {
    key:
      "vwcPeak" | "vwcTrough" | "p0Dryback" | "nightRate" | "ecMean" | "litresPerPlant" | "shots";
    dashed?: boolean;
  }[];
  unit: string;
  digits: number;
}
const METRICS: Metric[] = [
  {
    id: "vwc",
    title: "Moisture",
    detail: "Each grow day’s peak (solid) and trough (dashed), %.",
    keys: [{ key: "vwcPeak" }, { key: "vwcTrough", dashed: true }],
    unit: " %",
    digits: 1,
  },
  {
    id: "p0",
    title: "Morning dryback",
    detail: "From the P1 plateau to where the night landed, % of the plateau.",
    keys: [{ key: "p0Dryback" }],
    unit: " %",
    digits: 1,
  },
  {
    id: "night",
    title: "Night drying",
    detail: "Points of VWC an hour, from lights-off to the first shot.",
    keys: [{ key: "nightRate" }],
    unit: " pts/h",
    digits: 2,
  },
  {
    id: "ec",
    title: "Pore EC",
    detail: "The grow day’s mean, mS/cm.",
    keys: [{ key: "ecMean" }],
    unit: "",
    digits: 2,
  },
  {
    id: "water",
    title: "Water per plant",
    detail: "Litres a plant each grow day.",
    keys: [{ key: "litresPerPlant" }],
    unit: " L",
    digits: 2,
  },
  {
    id: "shots",
    title: "Shots",
    detail: "Shots each grow day.",
    keys: [{ key: "shots" }],
    unit: "",
    digits: 1,
  },
];

/** History › Grows: up to six grows side by side by grow day, from the room's grow-day summaries, with each
 * grow's statistics and its yield. Read-only: nothing here changes watering. */
export function Grows({
  controller,
  onDirtyChange,
}: {
  controller: Controller;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [recordsDirty, setRecordsDirty] = useState(false);
  const [recordingDirty, setRecordingDirty] = useState(false);
  useLayoutEffect(() => {
    onDirtyChange?.(recordsDirty || recordingDirty);
    return () => onDirtyChange?.(false);
  }, [recordsDirty, recordingDirty, onDirtyChange]);
  const [runs, setRuns] = useState<RunsDocument | null>(null);
  const [days, setDays] = useState<GrowDaysDocument | null>(null);
  const [harvests, setHarvests] = useState<HarvestsDocument | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<string[] | null>(null);
  const [scope, setScope] = useState<GrowScope>("room");
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setError("");
    Promise.all([
      controller.operator<RunsDocument>("runs_get"),
      controller.operator<GrowDaysDocument>("grow_days_get"),
      controller.operator<HarvestsDocument>("harvests_get"),
    ])
      .then(([r, d, h]) => {
        if (cancelled) return;
        setRuns(r);
        setDays(d);
        setHarvests(h);
      })
      .catch((e) => !cancelled && setError(errorText(e)));
    return () => {
      cancelled = true;
    };
  }, [controller.roomId, controller.operator, reload]);
  const open = (runs?.runs ?? [])
    .filter((run) => !run.archived)
    .sort((a, b) => b.start_date.localeCompare(a.start_date));
  const chosen = (picked ?? open.slice(0, 2).map((r) => r.id))
    .map((id) => open.find((r) => r.id === id))
    .filter((r): r is RunRecord => !!r);
  const rows = days?.days ?? [];

  const series = useMemo(
    () =>
      chosen.map((run) => ({
        run,
        points: growPoints(run, rows, scope),
        stats: growStats(run, rows, scope),
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [chosen.map((r) => r.id).join(), rows, scope],
  );
  const maxDay = Math.max(0, ...series.flatMap((s) => s.points.map((p) => p.day)));
  const chartRows = Array.from({ length: maxDay }, (_, i) => {
    const row: Record<string, number | null> = { day: i + 1 };
    series.forEach((s, g) => {
      const point = s.points.find((p) => p.day === i + 1);
      for (const metric of METRICS)
        for (const { key } of metric.keys) row[`g${g}_${key}`] = point ? point[key] : null;
    });
    return row;
  });
  async function backfill(run: RunRecord) {
    setBusy(run.id);
    setError("");
    try {
      const today = dateInZone(Date.now(), run.time_zone);
      await controller.operator("grow_days_backfill", {
        start: run.start_date,
        end: run.end_date && run.end_date < today ? run.end_date : today,
      });
      setReload((n) => n + 1);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  if (!runs && !error) return <p className="muted">Reading the grows of this room…</p>;
  const yields = series.map((s) => ({
    ...s,
    harvest: harvests?.harvests[s.run.id],
    figures: yieldFigures(harvests?.harvests[s.run.id], s.run, scope, s.stats.litres),
  }));
  return (
    <div className="grows">
      <header className="workspace-section-heading">
        <div>
          <h1>Grows</h1>
          <p className="muted small">
            Grows side by side by grow day, from the summary the controller records at each
            lights-on. Summary recording and run records are managed here; they do not change
            watering.
          </p>
        </div>
      </header>
      {error && (
        <p role="alert" className="grows-notice">
          {error}
        </p>
      )}
      <RunRecords controller={controller} onDirtyChange={setRecordsDirty} />
      <CanonicalControls
        controller={controller}
        owner="history"
        onDirtyChange={setRecordingDirty}
      />
      <section className="panel grows-pick">
        <fieldset>
          <legend>Grows (2 to {MAX_GROWS})</legend>
          {!open.length && (
            <p className="small muted">No runs yet. Add a run in Run records above.</p>
          )}
          {open.map((run) => {
            const on = chosen.some((r) => r.id === run.id);
            return (
              <label key={run.id} className="grows-check">
                <input
                  type="checkbox"
                  checked={on}
                  disabled={!on && chosen.length >= MAX_GROWS}
                  onChange={() =>
                    setPicked(
                      on
                        ? chosen.filter((r) => r.id !== run.id).map((r) => r.id)
                        : [...chosen.map((r) => r.id), run.id],
                    )
                  }
                />
                {run.name}
                <span className="muted small">
                  {run.start_date} → {run.end_date ?? "ongoing"}
                </span>
              </label>
            );
          })}
        </fieldset>
        <label className="grows-scope">
          Zone
          <select
            value={String(scope)}
            onChange={(e) => setScope(e.target.value === "room" ? "room" : Number(e.target.value))}
          >
            <option value="room">Room average</option>
            {controller.room.zones.map((zone) => (
              <option key={zone.id} value={zone.id}>
                {zone.name}
              </option>
            ))}
          </select>
        </label>
      </section>
      {!chosen.length ? null : !maxDay ? (
        <Empty
          title="No grow-day summaries for these grows yet"
          detail="Days appear here from the first lights-on after recording starts. For a grow before that, fill its days from Home Assistant’s long-term statistics (moisture, EC and water only)."
        />
      ) : (
        <>
          <div className="grows-legend" aria-label="Grows">
            {series.map((s, g) => (
              <span key={s.run.id}>
                <i style={{ background: colour(g) }} aria-hidden="true" />
                {s.run.name}
              </span>
            ))}
          </div>
          <div className="grows-charts">
            {METRICS.map((metric) => (
              <figure className="panel grows-chart" key={metric.id} data-grow-chart={metric.id}>
                <figcaption>
                  <strong>{metric.title}</strong>
                  <span className="muted small">{metric.detail}</span>
                </figcaption>
                <ResponsiveContainer width="100%" height={170}>
                  <LineChart
                    data={chartRows}
                    margin={{ top: 6, right: 8, bottom: 0, left: 0 }}
                    accessibilityLayer={false}
                  >
                    <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--border)" />
                    <XAxis dataKey="day" {...axis} interval="preserveStartEnd" minTickGap={12} />
                    <YAxis
                      {...axis}
                      width={40}
                      domain={["auto", "auto"]}
                      tickFormatter={(v) => number(Number(v), metric.digits)}
                    />
                    <Tooltip
                      contentStyle={tooltipStyle}
                      labelFormatter={(label) => `Grow day ${label}`}
                      formatter={(value) => [
                        value === null || value === undefined
                          ? "—"
                          : `${number(Number(value), metric.digits)}${metric.unit}`,
                      ]}
                    />
                    {series.flatMap((s, g) =>
                      metric.keys.map(({ key, dashed }) => (
                        <Line
                          key={`${g}-${key}`}
                          dataKey={`g${g}_${key}`}
                          name={s.run.name}
                          stroke={colour(g)}
                          strokeDasharray={dashed ? "4 3" : undefined}
                          strokeWidth={dashed ? 1.5 : 2}
                          dot={false}
                          connectNulls={false}
                          isAnimationActive={false}
                        />
                      )),
                    )}
                  </LineChart>
                </ResponsiveContainer>
              </figure>
            ))}
          </div>
          <p className="small muted">
            {series
              .map((s) => {
                const rescue = s.points.filter((p) => p.rescue).map((p) => p.day);
                const stall = s.points.filter((p) => p.stall).map((p) => p.day);
                const filled = s.points.filter((p) => p.backfilled).length;
                return `${s.run.name}: rescue days ${rescue.join(", ") || "none"}; stalled ramps ${stall.join(", ") || "none"}${filled ? `; ${filled} day(s) filled from statistics` : ""}.`;
              })
              .join(" ")}
          </p>
        </>
      )}
      {!!chosen.length && (
        <section className="panel grows-stats">
          <h2>Statistics</h2>
          <div className="grows-table-wrap">
            <table className="grows-table">
              <thead>
                <tr>
                  <th scope="col">Grow</th>
                  <th scope="col">Days</th>
                  <th scope="col">L/plant</th>
                  <th scope="col">L/plant a day</th>
                  <th scope="col">P0 dryback</th>
                  <th scope="col">Night drying</th>
                  <th scope="col">EC min–max (median)</th>
                  <th scope="col">VWC peak / trough</th>
                  <th scope="col">Rescues</th>
                  <th scope="col">Stalls</th>
                  <th scope="col">Alerts</th>
                  <th scope="col">Mode</th>
                  <th scope="col" />
                </tr>
              </thead>
              <tbody>
                {series.map(({ run, stats }) => (
                  <tr key={run.id}>
                    <th scope="row">{run.name}</th>
                    <td>{stats.days}</td>
                    <td>{number(stats.litresPerPlant, 1)}</td>
                    <td>
                      {number(stats.dailyLitresPerPlant, 2)}
                      {stats.dailyLitresSpread !== null &&
                        ` ± ${number(stats.dailyLitresSpread, 2)}`}
                    </td>
                    <td>{number(stats.p0Dryback, 1)} %</td>
                    <td>{number(stats.nightRate, 2)} pts/h</td>
                    <td>
                      {number(stats.ecMin, 1)}–{number(stats.ecMax, 1)} ({number(stats.ecMedian, 1)}
                      )
                    </td>
                    <td>
                      {number(stats.vwcPeakMedian, 1)} / {number(stats.vwcTroughMedian, 1)}
                    </td>
                    <td>{stats.rescues}</td>
                    <td>{stats.stallDays}</td>
                    <td className="small">
                      {Object.entries(stats.alerts)
                        .map(([code, n]) => `${code} ×${n}`)
                        .join(", ") || "none"}
                    </td>
                    <td className="small">
                      {Object.entries(stats.modes)
                        .map(
                          ([mode, n]) =>
                            `${mode} ${Math.round(
                              (n /
                                Math.max(
                                  1,
                                  Object.values(stats.modes).reduce((a, b) => a + b, 0),
                                )) *
                                100,
                            )} %`,
                        )
                        .join(", ") || "—"}
                    </td>
                    <td>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={!!busy}
                        onClick={() => void backfill(run)}
                      >
                        {busy === run.id ? "Filling…" : "Fill from statistics"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {!!chosen.length && (
        <section className="panel grows-yield">
          <h2>Yield against water and steering</h2>
          <p className="small muted">
            Grams are dry weight. g/L divides it by the litres fed over the grow. Yields differ by
            cultivar, plant count, season and much else: these figures show what happened, not why.
          </p>
          <div className="grows-table-wrap">
            <table className="grows-table" data-yield-table>
              <thead>
                <tr>
                  <th scope="col">Grow</th>
                  <th scope="col">Harvest</th>
                  <th scope="col">Dry g</th>
                  <th scope="col">g/plant</th>
                  <th scope="col">g/m²</th>
                  <th scope="col">g/L</th>
                  <th scope="col">Dry/wet</th>
                  <th scope="col">L/plant</th>
                  <th scope="col">P0 dryback</th>
                  <th scope="col">EC median</th>
                  <th scope="col">Rescues</th>
                  <th scope="col">Stalls</th>
                  <th scope="col">Days</th>
                  <th scope="col" />
                </tr>
              </thead>
              <tbody>
                {yields.map(({ run, stats, harvest, figures }) => (
                  <tr key={run.id}>
                    <th scope="row">{run.name}</th>
                    <td>
                      {harvest?.harvest_date ?? "—"}
                      {harvest?.quality && <Pill tone="neutral">{harvest.quality}</Pill>}
                    </td>
                    <td>{number(figures.dryG, 0)}</td>
                    <td>{number(figures.gramsPerPlant, 1)}</td>
                    <td>{number(figures.gramsPerM2, 0)}</td>
                    <td>{number(figures.gramsPerLitre, 2)}</td>
                    <td>{number(figures.dryWetRatio, 2)}</td>
                    <td>{number(stats.litresPerPlant, 1)}</td>
                    <td>{number(stats.p0Dryback, 1)} %</td>
                    <td>{number(stats.ecMedian, 1)}</td>
                    <td>{stats.rescues}</td>
                    <td>{stats.stallDays}</td>
                    <td>{stats.days}</td>
                    <td>
                      <Button variant="outline" size="sm" onClick={() => setEditing(run.id)}>
                        {harvest ? "Edit harvest" : "Enter harvest"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {yields.filter((y) => y.figures.dryG !== null).length < TREND_MIN_GROWS && (
            <p className="small muted" data-record-not-trend>
              Fewer than {TREND_MIN_GROWS} grows with a yield: this is a record, not a trend. No fit
              line is drawn.
            </p>
          )}
          <div className="grows-scatters">
            <YieldScatter
              title="g/plant against L/plant"
              points={yields.map((y, g) => ({
                name: y.run.name,
                g,
                x: y.stats.litresPerPlant,
                y: y.figures.gramsPerPlant,
              }))}
              xUnit="L/plant"
              yUnit="g/plant"
            />
            <YieldScatter
              title="g/plant against P0 dryback"
              points={yields.map((y, g) => ({
                name: y.run.name,
                g,
                x: y.stats.p0Dryback,
                y: y.figures.gramsPerPlant,
              }))}
              xUnit="% dryback"
              yUnit="g/plant"
            />
            <YieldScatter
              title="g/L against EC median"
              points={yields.map((y, g) => ({
                name: y.run.name,
                g,
                x: y.stats.ecMedian,
                y: y.figures.gramsPerLitre,
              }))}
              xUnit="mS/cm"
              yUnit="g/L"
            />
          </div>
        </section>
      )}
      {editing && harvests && (
        <HarvestForm
          run={open.find((r) => r.id === editing)!}
          harvest={harvests.harvests[editing]}
          revision={harvests.revision}
          controller={controller}
          onDone={(doc) => {
            if (doc) setHarvests(doc);
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}

function YieldScatter({
  title,
  points,
  xUnit,
  yUnit,
}: {
  title: string;
  points: { name: string; g: number; x: number | null; y: number | null }[];
  xUnit: string;
  yUnit: string;
}) {
  const data = points.filter((p) => p.x !== null && p.y !== null);
  return (
    <figure className="grows-scatter">
      <figcaption className="small">{title}</figcaption>
      {data.length ? (
        <ResponsiveContainer width="100%" height={180}>
          <ScatterChart
            margin={{ top: 10, right: 16, bottom: 4, left: 0 }}
            accessibilityLayer={false}
          >
            <CartesianGrid strokeDasharray="3 5" stroke="var(--border)" />
            <XAxis
              type="number"
              dataKey="x"
              name={xUnit}
              {...axis}
              domain={["auto", "auto"]}
              unit={` ${xUnit}`}
            />
            <YAxis
              type="number"
              dataKey="y"
              name={yUnit}
              {...axis}
              width={44}
              domain={["auto", "auto"]}
            />
            <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: "var(--border)" }} />
            {data.map((p) => (
              <Scatter
                key={p.g}
                name={p.name}
                data={[p]}
                fill={colour(p.g)}
                isAnimationActive={false}
              >
                <LabelList
                  dataKey="name"
                  position="top"
                  fill="var(--muted-foreground)"
                  fontSize={12}
                />
              </Scatter>
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      ) : (
        <p className="small muted">Enter a harvest to plot it.</p>
      )}
    </figure>
  );
}

type Draft = Record<string, string>;
const WEIGHT_FIELDS: [keyof HarvestWeights, string][] = [
  ["dry_weight_g", "Dry g"],
  ["wet_weight_g", "Wet g"],
  ["plants_harvested", "Plants"],
  ["canopy_m2", "Canopy m²"],
];
const toText = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v));
const toNumber = (v: string | undefined) => (v === undefined || v.trim() === "" ? null : Number(v));

/** Enter or correct a run's harvest: the room's weights and each zone's, a grade, notes and lab results. */
function HarvestForm({
  run,
  harvest,
  revision,
  controller,
  onDone,
}: {
  run: RunRecord;
  harvest: Harvest | undefined;
  revision: number;
  controller: Controller;
  onDone: (doc: HarvestsDocument | null) => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => {
    const out: Draft = {
      harvest_date: harvest?.harvest_date ?? run.end_date ?? "",
      quality: harvest?.quality ?? "",
      notes: harvest?.notes ?? "",
      thc_pct: toText(harvest?.lab.thc_pct),
      terpenes: Object.entries(harvest?.lab.terpenes ?? {})
        .map(([k, v]) => `${k}=${v}`)
        .join(", "),
    };
    for (const [key] of WEIGHT_FIELDS) {
      out[`room.${key}`] = toText(harvest?.room?.[key]);
      for (const zone of run.zones)
        out[`${zone.zone_id}.${key}`] = toText(harvest?.zones[String(zone.zone_id)]?.[key]);
    }
    return out;
  });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const weights = (prefix: string) =>
    Object.fromEntries(WEIGHT_FIELDS.map(([key]) => [key, toNumber(draft[`${prefix}.${key}`])]));
  async function save(remove = false) {
    setSaving(true);
    setError("");
    try {
      const terpenes = Object.fromEntries(
        draft.terpenes
          .split(",")
          .map((pair) => pair.split("=").map((s) => s.trim()))
          .filter(([name, value]) => name && value)
          .map(([name, value]) => [name, Number(value)]),
      );
      const doc = await controller.operator<HarvestsDocument>("runs_set_harvest", {
        run_id: run.id,
        expected_revision: revision,
        harvest: remove
          ? null
          : {
              harvest_date: draft.harvest_date || null,
              room: weights("room"),
              zones: Object.fromEntries(
                run.zones.map((zone) => [String(zone.zone_id), weights(String(zone.zone_id))]),
              ),
              plants: harvest?.plants ?? [],
              quality: draft.quality || null,
              notes: draft.notes || null,
              lab: { thc_pct: toNumber(draft.thc_pct), terpenes },
            },
      });
      onDone(doc);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }
  const field = (key: string, label: string, props: Record<string, unknown> = {}) => (
    <label className="grows-field">
      <span className="small">{label}</span>
      <Input
        aria-label={label}
        value={draft[key] ?? ""}
        onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
        {...props}
      />
    </label>
  );
  return (
    <section className="panel grows-harvest" aria-label={`Harvest of ${run.name}`}>
      <h2>Harvest · {run.name}</h2>
      <p className="small muted">
        Every field is optional. Grams per plant, per m² and per litre are worked out from these.
      </p>
      <div className="grows-form">
        {field("harvest_date", "Harvest date", { type: "date" })}
        {field("quality", "Quality grade", { maxLength: 40 })}
        {field("thc_pct", "THC %", { inputMode: "decimal" })}
        {field("terpenes", "Terpenes (name=%, …)")}
      </div>
      <h3 className="small">Room</h3>
      <div className="grows-form">
        {WEIGHT_FIELDS.map(([key, label]) =>
          field(`room.${key}`, `Room ${label}`, { inputMode: "decimal" }),
        )}
      </div>
      {run.zones.map((zone) => (
        <div key={zone.zone_id}>
          <h3 className="small">{zone.name}</h3>
          <div className="grows-form">
            {WEIGHT_FIELDS.map(([key, label]) =>
              field(`${zone.zone_id}.${key}`, `${zone.name} ${label}`, { inputMode: "decimal" }),
            )}
          </div>
        </div>
      ))}
      <label className="grows-field grows-notes">
        <span className="small">Notes</span>
        <textarea
          maxLength={500}
          value={draft.notes}
          onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
        />
      </label>
      {error && (
        <p role="alert" className="grows-notice">
          {error}
        </p>
      )}
      <div className="grows-actions">
        <Button disabled={saving} onClick={() => void save()}>
          {saving ? "Saving…" : "Save harvest"}
        </Button>
        {harvest && (
          <Button variant="outline" disabled={saving} onClick={() => void save(true)}>
            Remove
          </Button>
        )}
        <Button variant="ghost" disabled={saving} onClick={() => onDone(null)}>
          Cancel
        </Button>
      </div>
    </section>
  );
}
