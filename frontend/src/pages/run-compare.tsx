import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ReviewApply, type ApplyReceipt, type ReviewRow } from "@/components/review-apply";
import type { ComparedRun, RunsDocument } from "@/lib/comparison-types";
import {
  addDays,
  comparedRun,
  dateLabel,
  daysBetween,
  harvestCleared,
  harvestResult,
  kgText,
  parseDryKg,
  runCallout,
  runResult,
  stageWord,
  type CalloutMetric,
} from "@/lib/comparison";
import { formatEc, formatVolume, getDisplayUnits } from "@/lib/display-units";
import type { GrowDaysDocument, Harvest, HarvestsDocument } from "@/lib/grows";
import { NOMINAL_FLOWER_DAYS, stageArc, type Stage } from "@/lib/stage-arc";
import { dayKey } from "@/lib/time";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";

/** The four small multiples. `say` is a value with its unit, for the chart's text alternative. */
export const RUN_METRICS: {
  metric: CalloutMetric;
  title: string;
  unit: () => string;
  band: ((stage: Stage) => [number, number]) | null;
  tick: (value: number, digits: number) => string;
  say: (value: number, digits: number) => string;
}[] = [
  {
    metric: "vwc",
    title: "VWC, daily mean",
    unit: () => "%",
    band: null,
    tick: (v, d) => `${v.toFixed(d)}%`,
    say: (v, d) => `${v.toFixed(d)}%`,
  },
  {
    metric: "dryback",
    title: "Overnight dryback",
    unit: () => "VWC points lost lights-off",
    band: (stage) => stage.drybackPoints,
    tick: (v, d) => v.toFixed(d),
    say: (v, d) => `${v.toFixed(d)} points`,
  },
  {
    metric: "pore_ec",
    title: "Pore EC, daily mean",
    unit: () => formatEc(1, 0).split(" ").slice(1).join(" "),
    band: (stage) => stage.poreEc,
    tick: (v, d) => formatEc(v, d).split(" ")[0],
    say: (v, d) => formatEc(v, d),
  },
  {
    metric: "water",
    title: "Water per plant",
    unit: () => (getDisplayUnits().volume === "gal" ? "gallons a day" : "litres a day"),
    band: null,
    tick: (v, d) => formatVolume(v, d),
    say: (v, d) => `${formatVolume(v, d)} a plant a day`,
  },
];
/** A run keeps its colour while others are ticked and unticked: its card's place. */
const runColour = (index: number) => `var(--rw-run-${Math.min(index, 3)})`;
/** Neutral greys (comparison.css), so a stage strip never reads as a run swatch. */
const stageColour = (index: number) => `var(--rc-stage-${index % 3})`;
const MAX_TICKED = 3;
function niceStep(range: number) {
  const raw = range / 4 || 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  const m = raw / power;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * power;
}
const percent = (x: number) => `${(x * 100).toFixed(3)}%`;
const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** One small multiple: each ticked run's daily line, the plan's band stage by stage where the
 * stage arc has one, today's line, and the chart's one callout with the box it was measured over. */
export function RunChart({
  spec,
  runs,
  colours,
  stages,
  maxDay,
  today,
}: {
  spec: (typeof RUN_METRICS)[number];
  runs: ComparedRun[];
  colours: Map<string, string>;
  stages: Stage[];
  maxDay: number;
  today: number | null;
}) {
  const values = runs.flatMap((r) => (r.days[spec.metric] ?? []).map((d) => d.value));
  const bands = spec.band ? stages.map((s) => ({ stage: s, range: spec.band!(s) })) : [];
  const unit = spec.unit();
  const header = (
    <header>
      <h2>{spec.title}</h2>
      <span>{unit}</span>
      {!!bands.length && (
        <span className="rc-band-key">
          <i aria-hidden="true" />
          Guide range
        </span>
      )}
    </header>
  );
  if (!values.length)
    return (
      <section className="rc-chart" aria-label={spec.title} data-compare-chart={spec.metric}>
        {header}
        <p className="rc-empty">
          {runs.length
            ? "No grow-day summary of the ticked runs has this. Nothing is drawn in its place."
            : "Tick a run to compare."}
        </p>
      </section>
    );
  const callout = runCallout(spec.metric, runs, stages);
  const all = [...values, ...bands.flatMap((b) => b.range)];
  const step = niceStep(Math.max(...all) - Math.min(...all));
  const lo = Math.floor(Math.min(...all) / step) * step;
  const hi = Math.max(Math.ceil(Math.max(...all) / step) * step, lo + step);
  const digits = Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 1e6; v += step) ticks.push(Number(v.toFixed(6)));
  const x = (day: number) => (maxDay > 1 ? (day - 1) / (maxDay - 1) : 0);
  const y = (v: number) => 1 - (v - lo) / (hi - lo);
  const path = (points: { day: number; value: number }[]) =>
    points
      .map(
        (p, i) =>
          `${i && points[i - 1].day === p.day - 1 ? "L" : "M"}${(x(p.day) * 1000).toFixed(1)} ${(y(p.value) * 100).toFixed(2)}`,
      )
      .join("");
  let box = null;
  if (callout) {
    const { fromDay, toDay } = callout.box;
    const inside = runs.flatMap((r) =>
      (r.days[spec.metric] ?? []).filter((d) => d.day >= fromDay && d.day <= toDay).map((d) => d.value),
    );
    const pad = (hi - lo) * 0.04;
    box = {
      left: percent(Math.max(0, x(fromDay) - 0.008)),
      width: percent(x(toDay) - x(fromDay) + 0.016),
      top: percent(y(Math.max(...inside) + pad)),
      height: percent(y(Math.min(...inside) - pad) - y(Math.max(...inside) + pad)),
    };
  }
  const axis = [1];
  for (let d = 15; d <= maxDay - 5; d += 14) axis.push(d);
  if (maxDay > 1) axis.push(maxDay);
  const means = runs.flatMap((r) => {
    const days = r.days[spec.metric] ?? [];
    return days.length
      ? [`${r.name} averages ${spec.say(days.reduce((a, d) => a + d.value, 0) / days.length, r.digits?.[spec.metric] ?? 1)}`]
      : [];
  });
  const summary = `${spec.title} by day of run: ${means.join("; ")}.${callout ? " " + callout.text : ""}`;
  return (
    <section className="rc-chart" aria-label={spec.title} data-compare-chart={spec.metric}>
      {header}
      <p className="rc-callout" data-callout="" hidden={!callout}>
        {callout?.text}
      </p>
      <div className="rc-plot" role="img" aria-label={summary}>
        {ticks.map((t) => (
          <span key={t} className="rc-tick" style={{ top: percent(y(t)) }}>
            <span>{spec.tick(t, digits)}</span>
          </span>
        ))}
        {bands.map(({ stage, range }) => (
          <span
            key={stage.name}
            className="rc-band"
            style={{
              left: percent(x(stage.first)),
              width: percent(x(Math.min(stage.last, maxDay)) - x(stage.first)),
              top: percent(y(range[1])),
              height: percent(y(range[0]) - y(range[1])),
            }}
          />
        ))}
        {today !== null && <span className="rc-today" style={{ left: percent(x(today)) }} />}
        <svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
          {[...runs].reverse().map((run) => (
            <path
              key={run.id}
              d={path(run.days[spec.metric] ?? [])}
              data-run-line={run.id}
              fill="none"
              stroke={colours.get(run.id)}
              strokeWidth={run.current ? 3 : 2}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
        {box && <span className="rc-box" data-callout-box="" style={box} />}
        <div className="rc-stages" aria-hidden="true">
          {stages.map((s, i) => (
            <span
              key={s.name}
              style={{
                left: percent(x(s.first)),
                width: percent(x(Math.min(s.last, maxDay)) - x(s.first)),
                background: stageColour(i),
              }}
            />
          ))}
        </div>
        <div className="rc-axis" aria-hidden="true">
          {axis.map((d) => (
            <span key={d} style={{ left: percent(x(d)) }} data-edge={d === 1 ? "start" : d === maxDay ? "end" : undefined}>
              Day {d}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

/** History › Compare runs, room-wide (mockup 11): a card per run with what it ended with, up to
 * three runs ticked, and four small multiples of whole-room daily values from the room's grow-day
 * summaries, each with one callout where two runs differ past the metric's floor. A finished run
 * without a harvest result takes its dry weight here, through review and apply. `refresh` is the
 * page's Refresh history count: each press reloads the grow days and harvests. */
export function RunCompare({
  controller,
  runs,
  refresh,
}: {
  controller: Controller;
  runs: RunsDocument | null;
  refresh: number;
}) {
  const [growDays, setGrowDays] = useState<GrowDaysDocument | null>(null),
    [harvests, setHarvests] = useState<HarvestsDocument | null>(null),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0);
  const [ticked, setTicked] = useState<string[] | null>(null),
    [limit, setLimit] = useState<string | null>(null);
  const [adding, setAdding] = useState<{ runId: string; kg: string } | null>(null),
    [saved, setSaved] = useState<{ runId: string; stored: Harvest | undefined; receipt: ApplyReceipt } | null>(null),
    // A new Add starts a fresh review panel: no receipt or undo outcome from the last one.
    [session, setSession] = useState(0);
  useEffect(() => {
    let live = true;
    setError("");
    Promise.all([
      controller.operator<GrowDaysDocument>("grow_days_get"),
      controller.operator<HarvestsDocument>("harvests_get"),
    ])
      .then(([days, h]) => {
        if (!live) return;
        setGrowDays(days);
        setHarvests(h);
      })
      .catch((e) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [controller.roomId, controller.operator, reload, refresh]);
  const doc = runs?.room_id === controller.roomId ? runs : null;
  const open = (doc?.runs ?? []).filter((run) => !run.archived);
  const current = open.find((run) => !run.end_date) ?? null;
  const cards = [
    ...(current ? [current] : []),
    ...open.filter((run) => run !== current).sort((a, b) => b.start_date.localeCompare(a.start_date)),
  ];
  const chosen = (ticked ?? cards.slice(0, MAX_TICKED).map((run) => run.id)).filter((id) =>
    cards.some((run) => run.id === id),
  );
  const colours = new Map(cards.map((run, i) => [run.id, runColour(i)]));
  const cardKey = JSON.stringify(cards.map((r) => [r.id, r.name, r.start_date, r.end_date]));
  const compared = useMemo(
    () =>
      cards
        .filter((run) => chosen.includes(run.id))
        .map((run) => comparedRun(run, growDays?.days ?? [], run === current)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cardKey, chosen.join(), growDays],
  );
  // The arc as long as the longest finished ticked run, else the guide's nominal flower.
  const lengths = cards
    .filter((run) => chosen.includes(run.id) && run.end_date)
    .map((run) => daysBetween(run.start_date, run.end_date!) + 1);
  const stages = stageArc(lengths.length ? Math.max(...lengths) : NOMINAL_FLOWER_DAYS);
  const dataDays = compared.flatMap((r) => Object.values(r.days).flatMap((d) => (d ?? []).map((p) => p.day)));
  const maxDay = Math.max(stages.at(-1)?.last ?? 1, ...dataDays);
  const todayKey = current ? dayKey(Date.now(), current.time_zone) : null;
  const today = current && todayKey ? daysBetween(current.start_date, todayKey) + 1 : null;
  // Today's line, drawn only on this run's own chart days; the legend names it only when drawn.
  const todayDrawn = today !== null && current && chosen.includes(current.id) && today <= maxDay ? today : null;
  const leftState = controller.states[`sensor.crop_steering_${controller.room.room.prefix}days_to_harvest`]?.state;
  const left = leftState === undefined || leftState === "" ? NaN : Number(leftState);
  const harvestDue = todayKey && Number.isInteger(left) && left >= 0 ? addDays(todayKey, left) : null;

  function toggle(id: string, name: string) {
    if (chosen.includes(id)) {
      setTicked(chosen.filter((x) => x !== id));
      setLimit(null);
    } else if (chosen.length >= MAX_TICKED) setLimit(name);
    else {
      setTicked([...chosen, id]);
      setLimit(null);
    }
  }
  const addingRun = adding ? cards.find((run) => run.id === adding.runId) : undefined;
  const grams = adding ? parseDryKg(adding.kg) : null;
  const kgHint = !!adding?.kg.trim() && !(grams !== null && grams > 0);
  const rows: ReviewRow[] =
    addingRun && grams !== null && grams > 0
      ? [{ id: "dry", label: `${addingRun.name} dry weight`, before: "none", after: kgText(grams) }]
      : [];
  /** Saves the dry weight and reads it back from the harvests the service answers with. */
  async function saveHarvest(): Promise<ApplyReceipt> {
    const run = addingRun!,
      written = grams!;
    const answer = await controller.operator<HarvestsDocument>("runs_set_harvest", {
      run_id: run.id,
      expected_revision: harvests!.revision,
      harvest: harvestResult(written),
    });
    setHarvests(answer);
    const held = answer.harvests[run.id]?.room?.dry_weight_g ?? null;
    const receipt: ApplyReceipt =
      held === written
        ? { at: Date.now(), ok: true, failed: [], summary: `${rows[0].label} none → ${kgText(written)}`, eventIds: [] }
        : {
            at: Date.now(),
            ok: false,
            failed: [{ id: "dry", holds: held === null ? "none" : kgText(held) }],
            summary: "",
            eventIds: [],
          };
    setSaved({ runId: run.id, stored: answer.harvests[run.id], receipt });
    if (receipt.ok) setAdding(null);
    return receipt;
  }
  /** Takes the harvest result back out, only while it is still the one saved here. */
  async function undoHarvest() {
    const { runId, stored } = saved!;
    const now = await controller.operator<HarvestsDocument>("harvests_get");
    // Every field, not just the dry weight: anything added elsewhere since would go with harvest: null.
    if (!stored || JSON.stringify(now.harvests[runId]) !== JSON.stringify(stored)) {
      setHarvests(now);
      throw new Error("The harvest result changed since it was saved here. Reload and check before trying again.");
    }
    const answer = await controller.operator<HarvestsDocument>("runs_set_harvest", {
      run_id: runId,
      expected_revision: now.revision,
      harvest: null,
    });
    setHarvests(answer);
    harvestCleared(answer, runId);
  }

  if (!doc || !cards.length) return null;
  return (
    <section className="run-compare" aria-label="Runs side by side" data-run-compare="">
      <div className="rc-head">
        <p className="rc-scope">{controller.room.room.name} · whole-room daily values</p>
        <label htmlFor="rc-align">Line runs up by</label>
        <select id="rc-align" defaultValue="run">
          <option value="run">Day of run</option>
          <option value="flower" disabled>
            Day of flower (no flip dates recorded)
          </option>
        </select>
      </div>
      <div className="rc-cards" role="group" aria-label="Runs to compare, up to three">
        {cards.map((run) => {
          const on = chosen.includes(run.id);
          const result = runResult(run, harvests?.harvests[run.id], run === current ? harvestDue : null);
          return (
            <div key={run.id} className="rc-card" data-run-card={run.id} data-on={on ? "" : undefined}>
              <span className="rc-card-top">
                <label className="rc-tick-run">
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={run === current}
                    onChange={() => toggle(run.id, run.name)}
                  />
                  <i aria-hidden="true" style={{ background: colours.get(run.id) }} />
                  {run.name}
                  {run === current ? " · this run" : ""}
                </label>
                <span className="rc-dates">from {dateLabel(run.start_date)}</span>
              </span>
              <span className="rc-result" data-missing={result.missing ? "" : undefined}>
                {harvests ? result.text : error ? "Harvest results could not load" : "Reading harvest results…"}
              </span>
              {harvests && result.missing && adding?.runId !== run.id && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setAdding({ runId: run.id, kg: "" });
                    setSaved(null);
                    setSession((n) => n + 1);
                  }}
                >
                  Add harvest result
                </Button>
              )}
              {adding?.runId === run.id && (
                <span className="rc-add">
                  <label htmlFor={`rc-kg-${run.id}`}>Dry kg</label>
                  <Input
                    id={`rc-kg-${run.id}`}
                    inputMode="decimal"
                    autoFocus
                    aria-describedby={kgHint ? `rc-kg-hint-${run.id}` : undefined}
                    aria-invalid={kgHint || undefined}
                    value={adding.kg}
                    onChange={(e) => setAdding({ runId: run.id, kg: e.target.value })}
                  />
                  {kgHint && (
                    <span id={`rc-kg-hint-${run.id}`} className="rc-kg-hint">
                      Type kilograms as a number, like 38.4
                    </span>
                  )}
                  {!rows.length && (
                    <Button variant="outline" size="sm" onClick={() => setAdding(null)}>
                      Cancel
                    </Button>
                  )}
                </span>
              )}
            </div>
          );
        })}
      </div>
      {limit && (
        <p className="rc-limit" role="status">
          Three runs is the most that stays readable. Untick one to add {limit}.
        </p>
      )}
      {(addingRun || saved) && (
        <ReviewApply
          key={session}
          layout="panel"
          rows={rows}
          applyLabel={addingRun ? `Save to ${addingRun.name}` : undefined}
          discardLabel="Cancel"
          apply={saveHarvest}
          onDiscard={() => setAdding(null)}
          last={saved?.receipt ?? null}
          onReload={() => setReload((n) => n + 1)}
          timeZone={controller.timeZone}
          undo={undoHarvest}
          confirmation="Harvest records hold the value written"
        />
      )}
      {error && (
        <p className="comparison-notice" role="alert">
          {error}
        </p>
      )}
      <div className="rc-grid">
        {RUN_METRICS.map((spec) => (
          <RunChart
            key={spec.metric}
            spec={spec}
            runs={compared}
            colours={colours}
            stages={stages}
            maxDay={maxDay}
            today={todayDrawn}
          />
        ))}
      </div>
      <div className="rc-legend">
        {stages.map((s, i) => (
          <span key={s.name}>
            <i aria-hidden="true" style={{ background: stageColour(i) }} />
            {capital(stageWord(s.name))} · days {s.first}–{s.last}
          </span>
        ))}
        <span className="rc-hedge">Stages and guide ranges assume run day 1 was flower day 1: no flip dates are recorded.</span>
        {todayDrawn !== null && (
          <span>
            <i aria-hidden="true" className="rc-today-key" />
            Today, day {todayDrawn} of this run
          </span>
        )}
      </div>
    </section>
  );
}
