import { useState } from "react";
import { CircleAlert, TriangleAlert } from "lucide-react";
import type { roomAttention } from "@/lib/facility-view";
import { useNarrow } from "@/lib/use-narrow";
import "./needs-attention.css";


/** One line under a room's heading: what needs a look, each "<place>: <problem>" and a link to where
 * it is fixed, the worst first. Nothing when all is well, so a calm room stays calm. */
export function NeedsAttention({
  items,
  open,
  alerts = 0,
}: {
  items: ReturnType<typeof roomAttention>;
  open: (item: ReturnType<typeof roomAttention>[number]) => void;
  /** The room's open alerts, counted at the start of the line. */
  alerts?: number;
}) {
  const [all, setAll] = useState(false);
  // Before "+N more": the worst three, the worst one on a phone (a line each there).
  const narrow = useNarrow(720);
  if (!items.length && !alerts) return null;
  const shown = all ? items : items.slice(0, narrow ? 1 : 3);
  return (
    <ul className="needs-attention" data-needs-attention aria-label="Needs attention">
      {alerts > 0 && (
        <li className="needs-attention-alerts" data-facility-alerts={alerts}>
          <TriangleAlert size={13} aria-hidden="true" /> {alerts} open {alerts === 1 ? "alert" : "alerts"}
        </li>
      )}
      {shown.map((item) => (
        <li key={item.key} data-level={item.level}>
          <button type="button" className="inline-action" onClick={() => open(item)}>
            {item.level === "critical" ? (
              <CircleAlert size={15} aria-hidden="true" />
            ) : (
              <TriangleAlert size={15} aria-hidden="true" />
            )}
            <span className="sr-only">{item.level === "critical" ? "Critical: " : "Warning: "}</span>
            {item.text}
          </button>
        </li>
      ))}
      {shown.length < items.length && (
        <li>
          <button type="button" className="inline-action needs-attention-more" onClick={() => setAll(true)}>
            +{items.length - shown.length} more
          </button>
        </li>
      )}
    </ul>
  );
}
