import { number } from "@/components/dashboard";
import type { Metric, Zone } from "@/lib/types";
import type { ParameterLimit, SteeringProfile, ZonePlan } from "@/lib/operator-types";
import {
  blockForDay,
  columnRange,
  growDay,
  localDate,
  rangeBlock,
  replaceRange,
  setpointRows,
} from "@/lib/grow-plan";

const value = (v?: number) => (v === undefined ? "—" : number(v, 2));
const reading = (m: Metric, digits = 1) =>
  m.value === null
    ? "Unavailable"
    : number(m.value, digits) + (m.unit === "%" ? "%" : " " + m.unit);
const change = (from: number | null, to: number | null) =>
  from === null || to === null
    ? ""
    : to === from
      ? " (no change)"
      : ` (${to > from ? "+" : "−"}${Math.abs(to - from)} points)`;

/** What a steering balance means before it is applied: the blended setpoints beside both
 * endpoints, the balance either side, the zone right now and the whole grow's shape. */
export function PlanCellContext({
  zone,
  name,
  live,
  profile,
  limits,
  granularity,
  column,
  columns,
  typed,
  readOnly,
}: {
  zone: ZonePlan;
  name: string;
  live?: Zone;
  profile?: SteeringProfile;
  limits: Record<string, ParameterLimit>;
  granularity: "week" | "day";
  column: number;
  columns: number;
  /** A valid balance being typed into the selected cell, not yet applied. */
  typed: number | null;
  readOnly: boolean;
}) {
  const { start, end } = columnRange(granularity, column);
  const { block, mixed } = rangeBlock(zone, start, end);
  const saved = mixed ? null : (block?.bias ?? null);
  const bias = typed ?? saved;
  // The saved balance, shown beside a different one being typed.
  const now = typed !== null && typed !== saved ? saved : null;
  const rows = setpointRows(profile, bias, limits, now);
  const moving = rows.filter((r) => r.vegetative !== r.generative),
    fixed = rows.filter((r) => r.vegetative === r.generative);
  const unit = (c: number) => (granularity === "week" ? "Week " : "Day ") + (c + 1);
  const shown = (b: number | null, isMixed: boolean) =>
    b !== null ? b + "%" : isMixed ? "mixed" : "no plan";
  const side = (c: number) => {
    if (c < 0 || c >= columns) return null;
    const range = columnRange(granularity, c),
      other = rangeBlock(zone, range.start, range.end);
    const b = other.mixed ? null : (other.block?.bias ?? null);
    return { name: unit(c), bias: b, text: shown(b, other.mixed) };
  };
  const before = side(column - 1),
    after = side(column + 1),
    here = shown(bias, mixed);
  // The grow's shape per day, with the typed balance already in place.
  const days = granularity === "week" ? Math.min(366, columns * 7) : columns;
  const shaped =
    typed === null
      ? zone
      : {
          ...zone,
          schedule: replaceRange(zone.schedule, {
            start_day: start,
            end_day: end,
            profile_id: profile?.id ?? "",
            bias: typed,
          }),
        };
  const today = growDay(zone.start_date, localDate());
  return (
    <section className="plan-cell" aria-labelledby="plan-cell-title">
      <div className="plan-cell-head">
        <h3 id="plan-cell-title">
          {name} · {unit(column)}
          {granularity === "week" ? `, days ${start}–${end}` : ""}
        </h3>
        <p className="muted small">
          {typed !== null
            ? `Preview at ${typed}%${now !== null ? `, now ${now}%` : mixed ? ", now mixed" : saved === null ? ", no plan yet" : ""}. Enter applies it to the draft, Esc cancels.`
            : mixed
              ? `Mixed balance. One entry sets all ${end - start + 1} days.`
              : saved === null
                ? "No plan covers these days. Type a balance to add one."
                : `${saved}% generative.`}{" "}
          {profile ? `Endpoints: ${profile.name}.` : ""}
          {readOnly ? " Read only." : ""}
        </p>
      </div>
      <div className="plan-cell-body">
        <div>
          {moving.length > 0 && (
            <table className="plan-cell-table">
              <caption>
                {bias === null ? "Setpoints" : `Setpoints at ${bias}% generative`} · planning model
              </caption>
              <thead>
                <tr>
                  <th scope="col">Setpoint</th>
                  <th scope="col">Vegetative 0%</th>
                  {now !== null && <th scope="col">Now {now}%</th>}
                  {bias !== null && <th scope="col">At {bias}%</th>}
                  <th scope="col">Generative 100%</th>
                </tr>
              </thead>
              <tbody>
                {moving.map((r) => (
                  <tr key={r.key}>
                    <th scope="row">
                      {r.label} <small>{r.unit}</small>
                    </th>
                    <td>{value(r.vegetative)}</td>
                    {now !== null && <td>{value(r.now)}</td>}
                    {bias !== null && <td className="plan-cell-at">{value(r.value)}</td>}
                    <td>{value(r.generative)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {fixed.length > 0 && (
            <p className="plan-cell-note">
              The same at every balance:{" "}
              {fixed.map((r) => `${r.label} ${value(r.vegetative)} ${r.unit}`.trim()).join(" · ")}.
            </p>
          )}
          <p className="plan-cell-note">
            A planning model: each setpoint is blended between the two endpoints and rounded to its
            step. % VWC is absolute water content; dryback is a drop relative to the detected peak.
            The controller still steers by what the sensors read.
          </p>
        </div>
        <div className="plan-cell-side">
          <div>
            <h4>Balance either side</h4>
            <ul className="plan-cell-steps">
              {before && (
                <li>
                  {before.name} → {unit(column).toLowerCase()}: {before.text} → {here}
                  {change(before.bias, bias)}
                </li>
              )}
              {after && (
                <li>
                  {unit(column)} → {after.name.toLowerCase()}: {here} → {after.text}
                  {change(bias, after.bias)}
                </li>
              )}
            </ul>
          </div>
          <figure className="plan-cell-shape">
            <figcaption>
              <h4>Whole grow, {name}</h4>
            </figcaption>
            <svg
              viewBox={`0 0 ${days} 100`}
              preserveAspectRatio="none"
              shapeRendering="crispEdges"
              role="img"
              aria-label={`Steering balance by grow day, days 1 to ${days}, ${unit(column).toLowerCase()} highlighted`}
            >
              <rect
                className="plan-cell-window"
                x={start - 1}
                width={end - start + 1}
                height={100}
              />
              {Array.from({ length: days }, (_, i) => {
                const b = blockForDay(shaped, i + 1)?.bias;
                if (b === undefined) return null;
                const height = Math.max(b, 2);
                return (
                  <rect
                    key={i}
                    className={i + 1 >= start && i + 1 <= end ? "plan-cell-edit" : undefined}
                    x={i}
                    y={100 - height}
                    width={1}
                    height={height}
                  />
                );
              })}
              {now !== null && (
                <line
                  className="plan-cell-was"
                  x1={start - 1}
                  x2={end}
                  y1={100 - now}
                  y2={100 - now}
                />
              )}
            </svg>
            <div className="plan-cell-axis">
              <span>{granularity === "week" ? "Week 1" : "Day 1"}</span>
              <span>bar height = % generative</span>
              <span>{unit(columns - 1)}</span>
            </div>
          </figure>
          <div>
            <h4>
              {name} now{today >= 1 && today <= 366 ? ` · grow day ${today}` : ""}
            </h4>
            {live ? (
              <dl className="plan-cell-live">
                <div>
                  <dt>VWC</dt>
                  <dd>{reading(live.vwc)}</dd>
                </div>
                <div>
                  <dt>EC</dt>
                  <dd>{reading(live.ec, 2)}</dd>
                </div>
                <div>
                  <dt>Water today</dt>
                  <dd>{reading(live.water)}</dd>
                </div>
              </dl>
            ) : (
              <p className="muted small">No live readings for this zone.</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
