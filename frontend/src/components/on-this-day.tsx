import { useEffect, useState } from "react";
import { ArrowDown, ArrowRight, ArrowUp } from "lucide-react";
import { number } from "@/components/dashboard";
import { dateInZone } from "@/lib/comparison";
import type { RunRecord, RunsDocument } from "@/lib/comparison-types";
import { pickRuns } from "@/lib/history-explorer";
import { dayOf, dayOfRun, type GrowDay, type GrowDaysDocument } from "@/lib/grows";
import type { Controller, Zone } from "@/lib/types";
import "./on-this-day.css";

interface Row {
  label: string;
  unit: string;
  digits: number;
  pick: (d: GrowDay) => number | null | undefined;
}
const ROWS: Row[] = [
  { label: "VWC peak", unit: " %", digits: 1, pick: (d) => d.vwc?.peak },
  { label: "VWC trough", unit: " %", digits: 1, pick: (d) => d.vwc?.trough },
  { label: "Morning dryback", unit: " %", digits: 1, pick: (d) => d.p0?.dryback_pct },
  { label: "Pore EC", unit: "", digits: 2, pick: (d) => d.ec?.mean },
  { label: "Water per plant", unit: " L", digits: 2, pick: (d) => d.litres_per_plant },
];

/** The zone page's "On this day last grow": the last recorded grow day of this grow against the same grow day of
 * the grow picked (the last one by default), from the grow-day summaries. Nothing shows until both have one. */
export function OnThisDay({ controller, zone }: { controller: Controller; zone: Zone }) {
  const [runs, setRuns] = useState<RunsDocument | null>(null);
  const [days, setDays] = useState<GrowDay[]>([]);
  const [other, setOther] = useState<string>("");
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      controller.operator<RunsDocument>("runs_get"),
      controller.operator<GrowDaysDocument>("grow_days_get", { zone: zone.id }),
    ])
      .then(([r, d]) => {
        if (cancelled) return;
        setRuns(r);
        setDays(d.days);
      })
      .catch(() => {
        // An integration without grow-day summaries: the card stays away.
      });
    return () => {
      cancelled = true;
    };
  }, [controller.roomId, controller.operator, zone.id]);
  if (!runs) return null;
  const { current, previous } = pickRuns(runs.runs);
  const choices = runs.runs.filter((r) => !r.archived && r.id !== current?.id);
  const against: RunRecord | null = choices.find((r) => r.id === other) ?? previous;
  if (!current || !against) return null;
  const yesterday = dayOfRun(current, dateInZone(Date.now(), current.time_zone)) - 1;
  const mine = dayOf(current, days, zone.id, yesterday);
  const theirs = dayOf(against, days, zone.id, yesterday);
  if (!mine) return null;
  return (
    <section className="panel on-this-day" aria-labelledby="on-this-day-title" data-on-this-day>
      <div className="panel-heading">
        <h2 id="on-this-day-title">On this day last grow</h2>
        <label className="small">
          Against{" "}
          <select value={against.id} onChange={(e) => setOther(e.target.value)} aria-label="Compare with grow">
            {choices.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="small muted">
        Grow day {yesterday} of {current.name} against grow day {yesterday} of {against.name}.
        {!theirs && " That grow has no summary for this day."}
      </p>
      <table className="on-this-day-table">
        <thead>
          <tr>
            <th scope="col" />
            <th scope="col">This grow</th>
            <th scope="col">{against.name}</th>
            <th scope="col">
              <span className="sr-only">Change</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => {
            const a = row.pick(mine) ?? null,
              b = theirs ? (row.pick(theirs) ?? null) : null;
            const delta = a !== null && b !== null ? a - b : null;
            const Icon =
              delta === null || Math.abs(delta) < 10 ** -row.digits ? ArrowRight : delta > 0 ? ArrowUp : ArrowDown;
            return (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                <td>{a === null ? "—" : `${number(a, row.digits)}${row.unit}`}</td>
                <td>{b === null ? "—" : `${number(b, row.digits)}${row.unit}`}</td>
                <td>
                  {delta !== null && (
                    <span className="on-this-day-delta">
                      <Icon size={14} aria-hidden="true" />
                      {delta > 0 ? "+" : ""}
                      {number(delta, row.digits)}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
