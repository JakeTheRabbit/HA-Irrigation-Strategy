import { useId } from "react";

/** A feed tank drawn with its liquid at its level, the controller's minimum dashed across (when it
 * publishes one), and its fill float on the lid. */
export function FeedTankDrawing({
  level,
  minimum,
  full,
  low,
  label,
}: {
  level: number | null;
  minimum: number | null;
  full: boolean | null;
  low: boolean;
  label: string;
}) {
  const clip = useId();
  const ty = (pct: number) => 92 - (Math.max(0, Math.min(100, pct)) / 100) * 78;
  return (
    <svg className="feed-tank" viewBox="0 0 80 100" role="img" aria-label={label} data-low={low || undefined}>
      <defs>
        <clipPath id={clip}>
          <rect x="12" y="14" width="56" height="78" rx="8" />
        </clipPath>
      </defs>
      <path className="feed-tank-leg" d="M18 92 V98 M62 92 V98" />
      <rect className="feed-tank-body" x="12" y="14" width="56" height="78" rx="8" />
      {level !== null && (
        <g clipPath={`url(#${clip})`}>
          <rect className="feed-tank-liquid" x="12" y={ty(level)} width="56" height={92 - ty(level)} />
        </g>
      )}
      <rect className="feed-tank-edge" x="12" y="14" width="56" height="78" rx="8" />
      {minimum !== null && (
        <line className="feed-tank-minimum" x1="12" x2="68" y1={ty(minimum)} y2={ty(minimum)} />
      )}
      <rect className="feed-tank-lid" x="8" y="8" width="64" height="8" rx="3" />
      <line className="feed-tank-float-rod" x1="58" x2="58" y1="16" y2="24" />
      <circle className="feed-tank-float" cx="58" cy="27" r="3.5" data-full={full === true || undefined} />
    </svg>
  );
}
