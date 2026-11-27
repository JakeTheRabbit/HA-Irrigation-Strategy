import "./chart-key.css";

/** How a mark is drawn on the chart, so its swatch in the key looks the same. */
export type KeyMark =
  | "line" // solid line
  | "dash" // dashed line (targets, projections, plans)
  | "dot" // dotted line
  | "point" // a dot / marker on the line
  | "band" // shaded range (target band, lights-on, phase)
  | "bar" // a bar or block
  | "tick" // a short vertical tick (a shot, an event)
  | "now"; // the Now line

export interface KeyItem {
  mark: KeyMark;
  /** Any CSS colour, usually a token: "var(--chart-vwc)". The Now line ignores it. */
  color?: string;
  label: string;
  /** Optional detail after the label, muted: "target 30–36 %". */
  detail?: string;
}

/** One chart's key: every line, band and symbol the chart draws, each with a swatch drawn the same
 * way as on the chart. Put it right above or below its chart. */
export function ChartKey({ items, label = "Chart key", className }: { items: KeyItem[]; label?: string; className?: string }) {
  if (!items.length) return null;
  return (
    <ul className={className ? `chart-key ${className}` : "chart-key"} aria-label={label} data-chart-key>
      {items.map((item) => (
        <li key={`${item.mark}-${item.label}`} data-mark={item.mark}>
          <span
            className="chart-key-swatch"
            data-mark={item.mark}
            style={item.mark === "now" ? undefined : { ["--key-color" as string]: item.color ?? "currentColor" }}
            aria-hidden="true"
          />
          <span className="chart-key-label">{item.label}</span>
          {item.detail && <span className="chart-key-detail">{item.detail}</span>}
        </li>
      ))}
    </ul>
  );
}

/** The key entry for the Now line every live chart draws. */
export const NOW_KEY: KeyItem = { mark: "now", label: "Now" };
