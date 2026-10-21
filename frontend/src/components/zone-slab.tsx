import { useId } from "react";
import type { AttentionLevel } from "@/lib/attention";

// The slab drawn in a 100 x 100 box: a block on top, the slab from y=36 to y=92. Moisture is the
// water's height in the slab, 0 % at the bottom and FULL % at the top.
const TOP = 36,
  BOTTOM = 92,
  FULL = 80;
const y = (vwc: number) => BOTTOM - (Math.max(0, Math.min(FULL, vwc)) / FULL) * (BOTTOM - TOP);
/** A fixed scatter for the salt specks: the same zone draws the same specks on every render. */
const spot = (i: number) => {
  const x = Math.sin(i * 12.9898) * 43758.5453;
  return x - Math.floor(x);
};

/** A zone drawn as its rockwool slab: the water in it is the moisture now, the dashed line today's
 * peak (the gap down to the water is the dryback), the strip at the left the re-water to peak
 * target band, and the white specks the pore EC (more specks, more salt; amber above the stage's
 * band). The edge takes the colour of the zone's most urgent attention. */
export function ZoneSlab({
  vwc,
  peak,
  rewater,
  target,
  ec,
  ecBand,
  level,
  label,
}: {
  vwc: number | null;
  peak: number | null;
  rewater: number | null;
  target: number | null;
  ec: number | null;
  ecBand: readonly [number, number] | null;
  level: AttentionLevel | null;
  label: string;
}) {
  const clip = useId();
  const water = vwc === null ? null : y(vwc);
  const high = ec !== null && ecBand !== null && ec > ecBand[1];
  const specks =
    water === null || ec === null
      ? ""
      : Array.from(
          { length: Math.max(2, Math.min(24, Math.round((ec / (ecBand?.[1] ?? ec * 1.2)) * 14))) },
          (_, i) => {
            const cx = 9 + spot(i + 1) * 82;
            const cy = water + 3 + spot(i + 50) * Math.max(1, BOTTOM - water - 6);
            return `M${(cx - 1.6).toFixed(1)} ${cy.toFixed(1)}a1.6 1.6 0 1 0 3.2 0a1.6 1.6 0 1 0 -3.2 0`;
          },
        ).join("");
  return (
    <svg
      className="zone-slab"
      viewBox="0 0 100 100"
      // Inside a control that already says what the zone is, the drawing is decoration.
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
      data-level={level ?? undefined}
    >
      <defs>
        <clipPath id={clip}>
          <rect x="4" y={TOP} width="92" height={BOTTOM - TOP} rx="5" />
        </clipPath>
      </defs>
      <path className="zone-slab-stem" d="M50 30 V14" />
      <path className="zone-slab-leaf" d="M50 18 C40 10 36 12 34 6 C42 6 48 10 50 18 Z" />
      <path className="zone-slab-leaf" d="M50 15 C58 7 63 8 66 3 C58 3 52 7 50 15 Z" />
      <rect className="zone-slab-block" x="31" y="22" width="38" height="16" rx="2" />
      <rect className="zone-slab-body" x="4" y={TOP} width="92" height={BOTTOM - TOP} rx="5" />
      <g clipPath={`url(#${clip})`}>
        <path className="zone-slab-fibre" d="M4 48 H96 M4 60 H96 M4 72 H96 M4 84 H96" />
        {water !== null && (
          <rect className="zone-slab-water" x="4" y={water} width="92" height={BOTTOM - water} />
        )}
        {specks && <path className="zone-slab-salt" data-high={high || undefined} d={specks} />}
      </g>
      <rect className="zone-slab-edge" x="4" y={TOP} width="92" height={BOTTOM - TOP} rx="5" />
      {rewater !== null && target !== null && target > rewater && (
        <rect className="zone-slab-band" x="0" y={y(target)} width="3" height={y(rewater) - y(target)} />
      )}
      {peak !== null && water !== null && (
        <>
          <line className="zone-slab-peak" x1="4" x2="96" y1={y(peak)} y2={y(peak)} />
          <path className="zone-slab-dryback" d={`M93 ${y(peak).toFixed(1)} H99 V${water.toFixed(1)} H93`} />
        </>
      )}
    </svg>
  );
}

/** A feed tank drawn with its liquid at its level, the controller's minimum dashed across, and its
 * fill float on the lid. */
export function FeedTankDrawing({
  level,
  minimum,
  full,
  low,
  label,
}: {
  level: number | null;
  minimum: number;
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
      <line className="feed-tank-minimum" x1="12" x2="68" y1={ty(minimum)} y2={ty(minimum)} />
      <rect className="feed-tank-lid" x="8" y="8" width="64" height="8" rx="3" />
      <line className="feed-tank-float-rod" x1="58" x2="58" y1="16" y2="24" />
      <circle className="feed-tank-float" cx="58" cy="27" r="3.5" data-full={full === true || undefined} />
    </svg>
  );
}
