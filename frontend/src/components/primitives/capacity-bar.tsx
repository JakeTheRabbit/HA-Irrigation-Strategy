import "./primitives.css";

const pct = (n: number) => `${Number(n.toFixed(3))}%`;

/** What each part asks of a supply, side by side against its capacity line. Anything past the
 * line is hatched and marked ▲. Layout only: the caller writes the caption and any verdict. */
export function CapacityBar({
  segments,
  capacityLph,
  caption,
}: {
  segments: { id: string; label: string; lph: number; tone: string }[];
  capacityLph: number;
  caption: string;
}) {
  const total = segments.reduce((sum, s) => sum + Math.max(0, s.lph), 0);
  const scale = Math.max(total, capacityLph) || 1;
  const over = total > capacityLph;
  return (
    <span className="capacity-bar" role="img" aria-label={caption} data-over={over ? "" : undefined}>
      {segments.map((s) => (
        <span
          key={s.id}
          className="capacity-segment"
          data-tone={s.tone}
          title={s.label}
          style={{ width: pct((Math.max(0, s.lph) / scale) * 100) }}
        />
      ))}
      {over && (
        <span
          className="capacity-overflow"
          style={{ left: pct((capacityLph / scale) * 100), width: pct(((total - capacityLph) / scale) * 100) }}
        >
          ▲
        </span>
      )}
      <span className="capacity-line" style={{ left: pct((capacityLph / scale) * 100) }} />
    </span>
  );
}
