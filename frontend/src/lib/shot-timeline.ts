import { formatVolume } from "./display-units";
import { pickKey } from "./facility";
import type { TimelineBlock as ApiBlock, TimelineGetData } from "./parity-types";
import { clock } from "./time";

/** The ShotTimeline's model: timeline_get folded into rows (a room row, then one per zone) of
 * blocks drawn by glyph. Pure, so the glyph rules, placement and keys are tested on their own. */

export type BlockGlyph = "done" | "planned" | "expected" | "failed" | "warning" | "queued";
export interface TimelineBlock {
  id: string;
  glyph: BlockGlyph;
  start: number;
  end: number;
  requestedAt: number | null;
  pumpWaitS: number | null;
  litres: number | null;
  meteredL: number | null;
  litresPerPlant: number | null;
  reason: string | null;
  phase: string | null;
  vwcBefore: number | null;
  vwcExpected: number | null;
  source: string;
  code: string | null;
  eventId: string | null;
  skippable: boolean;
  zone: number;
  roomId: string;
  /** A shot open now, inside its expected window (glyph done): "watering now". */
  running: boolean;
  /** A planned slot already skipped (glyph planned), drawn faded and struck through. */
  skipped: boolean;
}
export interface TimelineRow {
  key: string;
  roomId: string;
  /** Null on a room's own row. */
  zone: number | null;
  label: string;
  sublabel: string;
  blocks: TimelineBlock[];
  lights: { on: number; off: number }[];
  tone?: "warn" | "bad";
  /** Room row: the controller gave no planned shots for this room. */
  plannedUnavailable?: boolean;
}

function glyphOf(b: ApiBlock): BlockGlyph {
  if (b.skipped) return "planned";
  if (b.expected === true) return "expected";
  if (b.kind === "planned") return "planned";
  if (b.kind === "queued") return "queued";
  if (b.kind === "held" || b.status === "error") return "failed";
  if (b.kind === "shot" && b.status === "done") return "done";
  return "warning";
}
const ms = (text: string | null) => (text ? Date.parse(text) : null);
const toneOf = (blocks: TimelineBlock[]): TimelineRow["tone"] =>
  blocks.some((b) => b.glyph === "failed")
    ? "bad"
    : blocks.some((b) => b.glyph === "warning")
      ? "warn"
      : undefined;

/** Rows in the answer's room order: each room's row, then its zones'. `plantsByZone` is keyed by
 * `pickKey(roomId, zone)`; water per plant is the metered litres, else the commanded ones. */
export function toTimelineRows(
  data: TimelineGetData,
  plantsByZone: Record<string, number>,
  rooms: { id: string; name: string; stage: string; day: number | null }[],
): TimelineRow[] {
  return data.rooms.flatMap((room) => {
    const meta = rooms.find((r) => r.id === room.room_id);
    const lights = room.lights.map((l) => ({ on: Date.parse(l.on), off: Date.parse(l.off) }));
    const zones = room.rows.map(({ zone, blocks: raw }): TimelineRow => {
      const plants = plantsByZone[pickKey(room.room_id, zone)];
      const blocks = raw
        .map((b): TimelineBlock => {
          const water = b.metered_l ?? b.litres;
          return {
            id: b.id,
            glyph: glyphOf(b),
            start: Date.parse(b.start),
            end: Date.parse(b.end ?? b.start),
            requestedAt: ms(b.requested_at),
            pumpWaitS: b.pump_wait_s,
            litres: b.litres,
            meteredL: b.metered_l,
            litresPerPlant: water !== null && plants > 0 ? water / plants : null,
            reason: b.reason,
            phase: b.phase,
            vwcBefore: b.vwc_before,
            vwcExpected: b.vwc_expected,
            source: b.source ?? "",
            code: b.code,
            eventId: b.event_id,
            skippable: b.skippable,
            zone,
            roomId: room.room_id,
            running: b.running === true,
            skipped: b.skipped === true,
          };
        })
        .sort((a, b) => a.start - b.start);
      const phase = blocks
        .filter((b) => b.phase && b.glyph !== "planned" && b.glyph !== "expected")
        .at(-1)?.phase;
      return {
        key: pickKey(room.room_id, zone),
        roomId: room.room_id,
        zone,
        label: `Zone ${zone}`,
        sublabel: phase ?? "",
        blocks,
        lights,
        tone: toneOf(blocks),
      };
    });
    const head: TimelineRow = {
      key: room.room_id,
      roomId: room.room_id,
      zone: null,
      label: meta?.name ?? room.room_id,
      sublabel: meta ? (meta.day === null ? meta.stage : `${meta.stage} · day ${meta.day}`) : "",
      blocks: [],
      lights,
      tone: toneOf(zones.flatMap((z) => z.blocks)),
      ...(room.planned_source === "unavailable" ? { plannedUnavailable: true } : {}),
    };
    return [head, ...zones];
  });
}

/** Where a block sits in the span, in % of it; a block crossing an edge is cut at it. An empty
 * span places everything at 0/0. */
export function place(
  block: TimelineBlock,
  span: { start: number; end: number },
): { offsetPct: number; sizePct: number } {
  const length = span.end - span.start;
  if (length <= 0) return { offsetPct: 0, sizePct: 0 };
  const clamp = (t: number) => Math.min(span.end, Math.max(span.start, t));
  const start = clamp(block.start);
  return {
    offsetPct: ((start - span.start) / length) * 100,
    sizePct: ((clamp(block.end) - start) / length) * 100,
  };
}

const nearest = (blocks: TimelineBlock[], t: number) =>
  blocks.reduce(
    (best, b, i) => (Math.abs(b.start - t) < Math.abs(blocks[best].start - t) ? i : best),
    0,
  );

/** The roving focus after a key: Left/Right along the row, Up/Down to the next row with blocks
 * (the block nearest in time), Home to the row's block nearest now. Edges hold. */
export function nextFocus(
  rows: TimelineRow[],
  current: { row: number; block: number },
  key: "ArrowLeft" | "ArrowRight" | "ArrowUp" | "ArrowDown" | "Home",
  now: number,
): { row: number; block: number } {
  const blocks = rows[current.row]?.blocks ?? [];
  if (!blocks.length) return current;
  if (key === "ArrowLeft") return { ...current, block: Math.max(0, current.block - 1) };
  if (key === "ArrowRight")
    return { ...current, block: Math.min(blocks.length - 1, current.block + 1) };
  if (key === "Home") return { ...current, block: nearest(blocks, now) };
  const step = key === "ArrowDown" ? 1 : -1;
  for (let row = current.row + step; row >= 0 && row < rows.length; row += step)
    if (rows[row].blocks.length)
      return { row, block: nearest(rows[row].blocks, blocks[current.block].start) };
  return current;
}

const WORD: Record<BlockGlyph, string> = {
  done: "done",
  planned: "planned",
  expected: "expected",
  failed: "failed",
  warning: "warning",
  queued: "waiting for pump",
};
const decimals = (value: number) => Math.min(2, (String(value).split(".")[1] ?? "").length);

/** What a block button says: "F2 zone 3, 10:40, 2.4 litres, done." */
export function blockSentence(block: TimelineBlock, roomName: string, timeZone: string): string {
  const water = block.meteredL ?? block.litres;
  const volume =
    water === null
      ? null
      : formatVolume(water, decimals(water)).replace(/ L$/, " litres").replace(/ gal$/, " gallons");
  const word = block.running ? "watering now" : block.skipped ? "skipped" : WORD[block.glyph];
  return (
    [`${roomName} zone ${block.zone}`, clock(block.start, timeZone), volume, word]
      .filter(Boolean)
      .join(", ") + "."
  );
}
