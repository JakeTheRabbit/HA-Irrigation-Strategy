import { ChevronDown, ChevronRight } from "lucide-react";
import { useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import {
  blockSentence,
  nextFocus,
  place,
  type TimelineBlock,
  type TimelineRow,
} from "@/lib/shot-timeline";
import { clock, startOfDay } from "@/lib/time";
import "./shot-timeline.css";

type Key = "ArrowLeft" | "ArrowRight" | "ArrowUp" | "ArrowDown" | "Home";
const KEYS: Key[] = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home"];
/** Vertical: time runs down and rooms are columns, so the keys turn with the axes. */
const TURNED: Record<Key, Key> = {
  ArrowLeft: "ArrowUp",
  ArrowRight: "ArrowDown",
  ArrowUp: "ArrowLeft",
  ArrowDown: "ArrowRight",
  Home: "Home",
};
const HOUR = 3_600_000;

/** A collapsed room's row carries every block of its zones; its zone rows are left out. */
function visibleRows(rows: TimelineRow[], collapsed: Set<string> | undefined): TimelineRow[] {
  return rows.flatMap((row) => {
    if (!collapsed?.has(row.roomId)) return [row];
    if (row.zone !== null) return [];
    const blocks = rows.filter((r) => r.roomId === row.roomId).flatMap((r) => r.blocks);
    return [{ ...row, blocks: blocks.sort((a, b) => a.start - b.start) }];
  });
}

function ticks(span: { start: number; end: number }, timeZone: string) {
  const hours = (span.end - span.start) / HOUR;
  const step = hours <= 12 ? 1 : hours <= 24 ? 2 : 4;
  const out: number[] = [];
  for (let t = Math.ceil(span.start / HOUR) * HOUR; t < span.end; t += HOUR)
    if (Math.round((t - startOfDay(t, timeZone)) / HOUR) % step === 0) out.push(t);
  return out;
}

/** Each zone's shots, holds, alerts and planned shots over a span, on one shared time axis.
 * `full` is the Timeline page (room toggles, legend), `preview` a compact read-only copy, `strip`
 * the bare track (no labels or axis). Every block is a button that says what it is. */
export function ShotTimeline({
  rows,
  span,
  now,
  mode,
  orientation = "horizontal",
  timeZone,
  stale = false,
  onBlock,
  focusIds,
  collapsedRooms,
  onToggleRoom,
}: {
  rows: TimelineRow[];
  span: { start: number; end: number };
  now: number;
  mode: "full" | "preview" | "strip";
  orientation?: "horizontal" | "vertical";
  timeZone: string;
  stale?: boolean;
  onBlock?(b: TimelineBlock, anchor: HTMLElement): void;
  focusIds?: string[];
  collapsedRooms?: Set<string>;
  onToggleRoom?(roomId: string): void;
}) {
  const vertical = orientation === "vertical";
  // A strip is bare tracks: a room's own row (which names the room) draws nothing there.
  const visible = useMemo(
    () =>
      visibleRows(rows, collapsedRooms).filter(
        (r) => mode !== "strip" || r.zone !== null || r.blocks.length,
      ),
    [rows, collapsedRooms, mode],
  );
  const names = new Map(rows.filter((r) => r.zone === null).map((r) => [r.roomId, r.label]));
  const maxWater = Math.max(
    0,
    ...visible.flatMap((r) => r.blocks.map((b) => b.litresPerPlant ?? 0)),
  );
  const buttons = useRef(new Map<string, HTMLButtonElement>());

  const [chosen, setChosen] = useState<string | null>(null);
  const position = (id: string | null | undefined) => {
    for (let row = 0; row < visible.length; row++) {
      const block = visible[row].blocks.findIndex((b) => b.id === id);
      if (block >= 0) return { row, block };
    }
    return null;
  };
  const first = visible.findIndex((r) => r.blocks.length);
  const focus =
    position(chosen) ??
    position(focusIds?.[0]) ??
    (first >= 0 ? nextFocus(visible, { row: first, block: 0 }, "Home", now) : null);
  const focusId = focus ? visible[focus.row].blocks[focus.block].id : null;

  const onKey = (event: KeyboardEvent) => {
    const key = event.key as Key;
    if (!focus || !KEYS.includes(key)) return;
    event.preventDefault();
    const next = nextFocus(visible, focus, vertical ? TURNED[key] : key, now);
    const id = visible[next.row].blocks[next.block].id;
    setChosen(id);
    buttons.current.get(id)?.focus();
  };

  const length = span.end - span.start;
  const pct = (t: number) =>
    ((Math.min(span.end, Math.max(span.start, t)) - span.start) / length) * 100;
  const nowShown = now >= span.start && now <= span.end;
  const unavailable = span.end > now ? rows.filter((r) => r.plannedUnavailable) : [];
  const roomCount = rows.filter((r) => r.zone === null).length;
  const labelled = mode !== "strip";

  const blockButton = (block: TimelineBlock) => {
    const { offsetPct, sizePct } = place(block, span);
    const style = {
      "--o": `${offsetPct}%`,
      "--s": `${sizePct}%`,
      "--w": maxWater > 0 && block.litresPerPlant !== null ? block.litresPerPlant / maxWater : 0.5,
    } as CSSProperties;
    return (
      <button
        type="button"
        key={block.id}
        ref={(el) => {
          if (el) buttons.current.set(block.id, el);
          else buttons.current.delete(block.id);
        }}
        className="st-block"
        data-id={block.id}
        data-glyph={block.glyph}
        data-running={block.running || undefined}
        data-skipped={block.skipped || undefined}
        data-stale={(stale && block.start > now) || undefined}
        data-focus={focusIds?.includes(block.id) || undefined}
        tabIndex={block.id === focusId ? 0 : -1}
        aria-label={blockSentence(block, names.get(block.roomId) ?? block.roomId, timeZone)}
        style={style}
        onFocus={() => setChosen(block.id)}
        onKeyDown={onKey}
        onClick={(event) => onBlock?.(block, event.currentTarget)}
      />
    );
  };

  const lightsBands = (row: TimelineRow) =>
    row.lights.map((l) => (
      <span
        key={l.on}
        className="st-lights"
        style={{ "--o": `${pct(l.on)}%`, "--s": `${pct(l.off) - pct(l.on)}%` } as CSSProperties}
      >
        {row.zone === null && mode === "full" && (
          <span className="st-lights-label">
            Lights on {clock(l.on, timeZone)}–{clock(l.off, timeZone)}
          </span>
        )}
      </span>
    ));
  const nowLine = nowShown && (
    <span
      className="st-now"
      style={{ "--o": `${pct(now)}%` } as CSSProperties}
      aria-hidden="true"
    />
  );
  const nowChip = nowShown && (
    <span className="st-now-chip" style={{ "--o": `${pct(now)}%` } as CSSProperties}>
      <span className="st-long">Now </span>
      {clock(now, timeZone)}
    </span>
  );
  const tickMarks = ticks(span, timeZone).map((t) => (
    <span
      key={t}
      className="st-tick"
      style={{ "--o": `${pct(t)}%` } as CSSProperties}
      aria-hidden="true"
    >
      {clock(t, timeZone)}
    </span>
  ));
  const toggle = (row: TimelineRow) => {
    if (row.zone !== null || mode !== "full" || !onToggleRoom) return null;
    const open = !collapsedRooms?.has(row.roomId);
    return (
      <button
        type="button"
        className="st-toggle"
        aria-expanded={open}
        aria-label={`${open ? "Collapse" : "Expand"} ${row.label}`}
        onClick={() => onToggleRoom(row.roomId)}
      >
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
    );
  };
  const label = (row: TimelineRow) =>
    row.zone === null ? (
      <span className="st-name">
        <b>{row.label}</b>
        {row.sublabel && <small>{row.sublabel}</small>}
      </span>
    ) : (
      <span className="st-name">
        <span className="st-long">{row.label}</span>
        <span className="st-short">Z{row.zone}</span>
        {row.sublabel && <small>{row.sublabel}</small>}
      </span>
    );
  const trackName = (row: TimelineRow) =>
    row.zone === null ? row.label : `${names.get(row.roomId) ?? row.roomId} ${row.label}`;

  const range = new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone,
  }).format(span.start);

  let body;
  if (!vertical)
    body = (
      <div className="st-grid">
        {labelled && (
          <div className="st-row st-head">
            <div className="st-label">
              {range} · {Math.round(length / HOUR)} h
            </div>
            <div className="st-track st-axis">
              {tickMarks}
              {nowChip}
            </div>
          </div>
        )}
        {visible.map((row) => (
          <div
            key={row.key}
            className="st-row"
            data-kind={row.zone === null ? "room" : "zone"}
            data-tone={row.tone}
          >
            {labelled && (
              <div className="st-label">
                {toggle(row)}
                {label(row)}
              </div>
            )}
            <div className="st-track" role="group" aria-label={trackName(row)}>
              {lightsBands(row)}
              {nowLine}
              {row.blocks.map(blockButton)}
            </div>
          </div>
        ))}
      </div>
    );
  else {
    const groups = [...new Set(visible.map((r) => r.roomId))].map((roomId) => {
      const mine = visible.filter((r) => r.roomId === roomId);
      const head = mine.find((r) => r.zone === null);
      const columns = mine.filter((r) => r.zone !== null || r.blocks.length);
      return { roomId, head, columns };
    });
    body = (
      <div className="st-vgrid" style={{ "--hours": length / HOUR } as CSSProperties}>
        {labelled && (
          <div className="st-vaxis" aria-hidden="true">
            <div className="st-vhead" />
            <div className="st-vtrack">
              {tickMarks}
              {nowChip}
            </div>
          </div>
        )}
        <div className="st-vscroll">
          {groups.map(({ roomId, head, columns }) => (
            <div key={roomId} className="st-vroom" data-tone={head?.tone}>
              {labelled && head && (
                <div className="st-vroom-head">
                  {toggle(head)}
                  {label(head)}
                </div>
              )}
              <div className="st-vcols">
                {columns.map((row) => (
                  <div key={row.key} className="st-vcol" data-tone={row.tone}>
                    {labelled && (
                      <div className="st-vhead">{row.zone === null ? "All" : `Z${row.zone}`}</div>
                    )}
                    <div className="st-vtrack" role="group" aria-label={trackName(row)}>
                      {lightsBands(row)}
                      {nowLine}
                      {row.blocks.map(blockButton)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <section
      className="shot-timeline"
      data-mode={mode}
      data-orientation={orientation}
      aria-label="Shot timeline"
    >
      {unavailable.length > 0 && (
        <p className="st-note">
          Planned shots not available from the controller
          {unavailable.length < roomCount ? ` (${unavailable.map((r) => r.label).join(", ")})` : ""}
        </p>
      )}
      {body}
      {mode === "full" && (
        <div className="st-legend" aria-label="Legend">
          <span data-glyph="done">Done</span>
          <span data-glyph="planned">Planned</span>
          <span data-glyph="expected">Expected</span>
          <span data-glyph="failed">Failed</span>
          <span data-glyph="warning">Warning</span>
          <span data-glyph="queued">Waiting for pump</span>
          <span data-glyph="lights">Lights on</span>
          <span className="st-scale">
            {vertical ? "Width = water" : "Bar height = water per plant"}
          </span>
        </div>
      )}
    </section>
  );
}
