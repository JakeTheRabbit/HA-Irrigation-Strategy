import { useState } from "react";
import { ChevronDown, CircleAlert, TriangleAlert } from "lucide-react";
import type { roomAttention } from "@/lib/facility-view";
import "./needs-attention.css";

type Item = ReturnType<typeof roomAttention>[number];

/** Under a room's heading: what needs a look, counted by severity ("1 fault · 4 warnings") with the
 * room's open alerts said apart from the dashboard's advisories, the worst item under the count,
 * and the count a disclosure that lists them all. Each item is "<place>: <problem>" and a link to
 * where it is fixed. Nothing when all is well, so a calm room stays calm. */
export function NeedsAttention({
  items,
  open,
  alerts = 0,
}: {
  items: Item[];
  open: (item: Item) => void;
  /** The room's open alerts (alarms), counted apart from the advisories. */
  alerts?: number;
}) {
  const [all, setAll] = useState(false);
  if (!items.length && !alerts) return null;
  const faults = items.filter((i) => i.level === "critical").length;
  const warnings = items.length - faults;
  const counts = [
    faults ? `${faults} ${faults === 1 ? "fault" : "faults"}` : null,
    warnings ? `${warnings} ${warnings === 1 ? "warning" : "warnings"}` : null,
  ].filter(Boolean);
  const alertText = alerts ? `${alerts} open ${alerts === 1 ? "alert" : "alerts"}` : "No open alerts";
  const shown = all ? items : items.slice(0, 1);
  const more = items.length > 1;
  const Icon = faults ? CircleAlert : TriangleAlert;
  const summary = (
    <>
      <Icon size={16} aria-hidden="true" />
      <span className="needs-attention-counts">{counts.join(" · ")}</span>
      {counts.length > 0 && <span aria-hidden="true">·</span>}
      <span className="needs-attention-alerts" data-facility-alerts={alerts}>
        {alertText}
      </span>
      {more && <ChevronDown size={16} aria-hidden="true" className="needs-attention-chevron" />}
    </>
  );
  return (
    <div
      className="needs-attention"
      data-needs-attention
      data-level={faults ? "critical" : "warning"}
      data-open={all || undefined}
    >
      {more ? (
        <button
          type="button"
          className="needs-attention-summary"
          aria-expanded={all}
          onClick={() => setAll(!all)}
        >
          {summary}
          <span className="sr-only">{all ? ", hide the list" : ", show all"}</span>
        </button>
      ) : (
        <p className="needs-attention-summary">{summary}</p>
      )}
      {shown.length > 0 && (
        <ul aria-label="Needs attention">
          {shown.map((item) => (
            <li key={item.key} data-level={item.level}>
              <button type="button" className="inline-action" onClick={() => open(item)}>
                {item.level === "critical" ? (
                  <CircleAlert size={15} aria-hidden="true" />
                ) : (
                  <TriangleAlert size={15} aria-hidden="true" />
                )}
                <span className="sr-only">{item.level === "critical" ? "Fault: " : "Warning: "}</span>
                {item.text}
              </button>
              {item.alert && <span className="needs-attention-tag">Open alert</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
