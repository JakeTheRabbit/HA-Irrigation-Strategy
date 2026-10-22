import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { Popover } from "radix-ui";
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { toast } from "sonner";
import { Heading } from "@/components/dashboard";
import { NeedsIntegration } from "@/components/needs-integration";
import { ShotTimeline } from "@/components/shot-timeline";
import { Button } from "@/components/ui/button";
import { formatVolume } from "@/lib/display-units";
import { useCsEvents } from "@/lib/events";
import { pickKey } from "@/lib/facility";
import { zoneHref } from "@/lib/facility-view";
import { buildRoom, resolveRequestedRoom } from "@/lib/model";
import { useParity } from "@/lib/parity-api";
import type { CsEvent, TimelineGetData, TimelineSummary } from "@/lib/parity-types";
import type { Page } from "@/lib/routes";
import { toTimelineRows, type TimelineBlock } from "@/lib/shot-timeline";
import { clock, dayKey, dayLabel } from "@/lib/time";
import type { Controller, Room } from "@/lib/types";
import { offerUndo, revertEvents } from "@/lib/undo";
import { useNarrow } from "@/lib/use-narrow";
import { plantAmount, roomPlants } from "@/lib/water-view";
import {
  dayChip,
  dayProblems,
  dayStart,
  defaultSpan,
  keepProblems,
  liveMatch,
  loadRevisions,
  matchQuery,
  shiftDate,
  skipShot,
  spanOf,
  statusLine,
  stripDates,
  wateringHash,
  wateringQuery,
  type WateringQuery,
} from "@/lib/watering";
import "./watering.css";

/** The page's choices outlive a room change (the room tree remounts the page): the address loses
 * its query then, so the last one stands in. Collapsed rooms likewise. */
const memory: { query: WateringQuery | null; room: string | null; collapsed: Set<string> } = {
  query: null,
  room: null,
  collapsed: new Set(),
};

const SOURCES: Record<string, string> = {
  engine: "Steering engine",
  timer: "Timer",
  manual: "Manual",
  ai: "AI assistant",
  plan: "Grow plan",
  safety: "Safety",
};
const pct = (value: number) => `${Number(value.toFixed(1))}%`;
const litresText = (l: number) => formatVolume(l, Math.min(2, (String(l).split(".")[1] ?? "").length));

function stageOf(controller: Controller, room: Room): "flower" | "veg" | null {
  const text = controller.states[`sensor.crop_steering_${room.prefix}stage`]?.state ?? "";
  return /flower|bloom/i.test(text) ? "flower" : /veg|clone|mother/i.test(text) ? "veg" : null;
}
function roomMeta(controller: Controller, room: Room) {
  const state = (key: string) => controller.states[`sensor.crop_steering_${room.prefix}${key}`]?.state;
  const day = Number(state("grow_day"));
  const stage = state("stage");
  return {
    id: room.id,
    name: room.name,
    stage: stage && stage !== "unknown" && stage !== "unavailable" ? stage : "",
    day: Number.isFinite(day) && state("grow_day") ? day : null,
  };
}

function initialQuery(hash: string, width: number): WateringQuery {
  if (!hash.includes("?") && memory.query) return memory.query;
  const q = wateringQuery(hash);
  return /[?&]span=/.test(hash) ? q : { ...q, span: defaultSpan(width) };
}

export function Watering({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: (page: Page, zone?: number) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { timeZone } = controller;
  const phone = useNarrow(720);
  const [q, setQ] = useState(() =>
    initialQuery(typeof window === "undefined" ? "" : window.location.hash, typeof window === "undefined" ? 1440 : window.innerWidth),
  );
  const change = (next: Partial<WateringQuery>) => {
    const merged = { ...q, ...next };
    memory.query = merged;
    setQ(merged);
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}${wateringHash(merged)}`);
  };
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  const today = dayKey(now, timeZone);
  const date = q.date || today;
  // A phone has no 48 h.
  const span = spanOf(phone && q.span === 48 ? { ...q, span: 24 } : q, now, timeZone, today);
  const spanHours = (span.end - span.start) / 3_600_000;

  // The rooms shown: a link's rooms, then the stages chosen.
  const stages = new Map(controller.rooms.map((room) => [room.id, stageOf(controller, room)]));
  const linked = q.rooms.flatMap((name) => resolveRequestedRoom(controller.rooms, name) ?? []);
  const rooms = (linked.length ? linked : controller.rooms).filter(
    (room) => !q.stages.length || q.stages.includes(stages.get(room.id) ?? ""),
  );
  const ids = rooms.map((room) => room.id);

  const timeline = useParity<TimelineGetData>(
    controller,
    "timeline_get",
    ids.length ? { rooms: ids, start: new Date(span.start).toISOString(), end: new Date(span.end).toISOString() } : null,
    [ids, span.start, span.end],
  );
  const week = stripDates(date);
  const summary = useParity<TimelineSummary>(
    controller,
    "timeline_summary",
    ids.length ? { rooms: ids, days: week } : null,
    [ids, date],
  );
  // What was last read, kept through a failed read.
  const lastGood = useRef<{ data: TimelineGetData; at: number } | null>(null);
  if (timeline.data && lastGood.current?.data !== timeline.data) lastGood.current = { data: timeline.data, at: Date.now() };
  const data = timeline.data ?? (timeline.state === "error" ? (lastGood.current?.data ?? null) : null);

  // Each room's timer revision, for a skip; read again when a skip finds it stale.
  const [revisions, setRevisions] = useState<Record<string, number> | null>(null);
  const readRevisions = useCallback(() => {
    void loadRevisions(controller).then(setRevisions);
  }, [controller.operator]);
  useEffect(readRevisions, [readRevisions]);

  // Live: a shot or intent in a room and span shown reloads, two seconds after the last one.
  const match = useCallback((e: CsEvent) => liveMatch(e, ids, span), [ids.join(), span.start, span.end]);
  const live = useCsEvents(controller, match);
  const newest = live.at(-1)?.id ?? null;
  const seen = useRef(newest);
  useEffect(() => {
    if (newest === seen.current) return;
    seen.current = newest;
    const timer = setTimeout(() => {
      timeline.reload();
      summary.reload();
    }, 2000);
    return () => clearTimeout(timer);
  }, [newest]);

  const plants: Record<string, number> = {};
  for (const room of rooms) {
    const scoped = { ...controller, room: buildRoom(controller.states, room), roomId: room.id };
    for (const [zone, count] of Object.entries(roomPlants(scoped))) plants[pickKey(room.id, Number(zone))] = count ?? 0;
  }
  const all = useMemo(
    () => (data ? toTimelineRows(data, plants, rooms.map((room) => roomMeta(controller, room))) : []),
    [data, controller.states],
  );
  const rows = matchQuery(q.problemsOnly ? keepProblems(all) : all, q.q);
  const names = new Map(rooms.map((room) => [room.id, room.name]));

  // Collapsed rooms; a room chosen in the room tree opens and comes into view.
  const [collapsed, setCollapsed] = useState(() => {
    const next = new Set(memory.collapsed);
    if (memory.room !== null && memory.room !== controller.roomId) next.delete(controller.roomId);
    return next;
  });
  const picked = useRef(memory.room !== null && memory.room !== controller.roomId);
  useEffect(() => {
    memory.room = controller.roomId;
  }, [controller.roomId]);
  useEffect(() => {
    memory.collapsed = collapsed;
  }, [collapsed]);
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!picked.current || !rows.length) return;
    picked.current = false;
    const index = rows.filter((r) => r.zone === null).findIndex((r) => r.roomId === controller.roomId);
    if (index <= 0) return;
    const label = phone ? ".st-vroom" : '.st-row[data-kind="room"]';
    body.current?.querySelectorAll<HTMLElement>(label)[index]?.scrollIntoView({ block: "start", inline: "start" });
  }, [rows.length]);
  const toggleRoom = (roomId: string) =>
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (!next.delete(roomId)) next.add(roomId);
      return next;
    });

  // The failed chip cycles focus through the failed shots.
  const markers = (data?.errors.markers ?? []).map((m) => String(m.block_id ?? "")).filter(Boolean);
  const failedCount = data?.errors.count ?? 0;
  const [focusIds, setFocusIds] = useState<string[]>([]);
  const cycle = useRef(0);
  const nextFailed = () => {
    if (!markers.length) return;
    const id = markers[cycle.current++ % markers.length];
    const marker = data?.errors.markers.find((m) => m.block_id === id);
    if (marker && collapsed.has(String(marker.room_id))) toggleRoom(String(marker.room_id));
    setFocusIds([id]);
    requestAnimationFrame(() =>
      body.current?.querySelector<HTMLButtonElement>(`.st-block[data-id="${CSS.escape(id)}"]`)?.focus(),
    );
  };

  // The block popover.
  const [open, setOpen] = useState<{ block: TimelineBlock; anchor: HTMLElement } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const shown = open ? (rows.flatMap((r) => r.blocks).find((b) => b.id === open.block.id) ?? open.block) : null;
  const where = (b: TimelineBlock) => `${names.get(b.roomId) ?? b.roomId} Zone ${b.zone}`;
  const goZone = (b: TimelineBlock, page: Page) => {
    setOpen(null);
    if (b.roomId !== controller.roomId) controller.changeRoom(b.roomId);
    navigate(page, b.zone);
  };
  const skip = async (b: TimelineBlock) => {
    setNote(null);
    setBusy(true);
    try {
      const current = revisions ?? (await loadRevisions(controller));
      if (!current) return setNote("Couldn't read the timers. Try again.");
      const result = await skipShot(controller, b, current);
      if (result.kind === "stale") {
        readRevisions();
        return setNote("The timers changed since you opened this. Try again.");
      }
      if (result.kind === "missing") return setNote("Skipping a shot needs Crop Steering 3.18 or newer.");
      if (result.kind === "error") return setNote(result.message);
      setOpen(null);
      readRevisions();
      timeline.reload();
      const what = `${where(b)} ${clock(b.start, timeZone)}`;
      if (!result.eventIds.length) return void toast(`Skipped ${what}.`);
      offerUndo({
        message: `Skipped ${what}.`,
        undo: async () => {
          await revertEvents(controller, result.eventIds);
          readRevisions();
          timeline.reload();
          toast(`${what} is back on the plan.`);
        },
      });
    } finally {
      setBusy(false);
    }
  };

  const problems = dayProblems(summary.data, date, ids);
  const stale = controller.connection === "offline";
  const stagesShown: string[] = [
    ...new Set(controller.rooms.flatMap((room) => stages.get(room.id) ?? [])),
  ];
  const toggleStage = (stage: string) => {
    const on = q.stages.length ? q.stages : stagesShown;
    const next = on.includes(stage) ? on.filter((s) => s !== stage) : [...on, stage];
    change({ stages: next.length === stagesShown.length ? [] : next });
  };
  const stageCount = (stage: string) => controller.rooms.filter((room) => stages.get(room.id) === stage).length;

  const spanChoices: (12 | 24 | 48)[] = phone ? [12, 24] : [12, 24, 48];
  const spanToggle = (
    <div className="wt-span" role="group" aria-label="Hours shown">
      {spanChoices.map((hours) => (
        <button
          key={hours}
          type="button"
          aria-pressed={spanHours === hours}
          onClick={() => change({ span: hours })}
        >
          {hours} h
        </button>
      ))}
    </div>
  );
  const dayWords = (d: string) => (d === today ? `Today, ${dayLabel(dayStart(d, timeZone), timeZone)}` : dayLabel(dayStart(d, timeZone), timeZone));
  const problemWords = [
    problems.failed && `${problems.failed} failed`,
    problems.warnings && `${problems.warnings} warning${problems.warnings === 1 ? "" : "s"}`,
  ].filter(Boolean);

  if (timeline.state === "missing" || summary.state === "missing")
    return (
      <>
        <Heading title="Timeline" />
        <section className="panel watering" aria-labelledby="watering-title">
          <h2 id="watering-title" className="sr-only">
            Watering timeline
          </h2>
          <NeedsIntegration feature="The watering timeline" />
        </section>
      </>
    );

  const empty = timeline.state === "ready" && !rows.some((r) => r.blocks.length);
  return (
    <>
      <Heading title="Timeline" description={phone ? "All rooms · swipe for more" : undefined} action={phone ? spanToggle : undefined} />
      <section className="panel watering" aria-label="Watering timeline" data-watering>
        {phone ? (
          <div className="wt-dayline" data-watering-day>
            <button type="button" aria-label="Day before" onClick={() => change({ date: shiftDate(date, -1) })}>
              <ChevronLeft size={20} />
            </button>
            <p>
              <strong>{dayWords(date)}</strong>
              <span data-tone={problemWords.length ? "problem" : undefined}>
                {problemWords.length ? problemWords.join(" · ") : summary.data ? "No problems" : " "}
              </span>
            </p>
            <button type="button" aria-label="Day after" onClick={() => change({ date: shiftDate(date, 1) })}>
              <ChevronRight size={20} />
            </button>
          </div>
        ) : (
          <div className="wt-days">
            <button type="button" className="wt-step" aria-label="Week before" onClick={() => change({ date: shiftDate(date, -7) })}>
              <ChevronLeft size={18} />
            </button>
            <ul className="wt-week" aria-label="Days">
              {week.map((d) => {
                const chip = summary.data ? dayChip(summary.data, d, ids, today) : null;
                return (
                  <li key={d}>
                    <button
                      type="button"
                      aria-pressed={d === date}
                      data-tone={chip?.tone}
                      onClick={() => change({ date: d === today ? "" : d })}
                    >
                      <b>{dayLabel(dayStart(d, timeZone), timeZone).replace(/ \w+$/, "")}</b>
                      <small>{chip?.label ?? " "}</small>
                    </button>
                  </li>
                );
              })}
            </ul>
            <button type="button" className="wt-step" aria-label="Week after" onClick={() => change({ date: shiftDate(date, 7) })}>
              <ChevronRight size={18} />
            </button>
            <Button variant="outline" onClick={() => change({ date: "" })} disabled={date === today}>
              Today
            </Button>
            {spanToggle}
          </div>
        )}

        <div className="wt-filters">
          {!phone &&
            stagesShown.map((stage) => {
              const on = !q.stages.length || q.stages.includes(stage);
              const n = stageCount(stage);
              const label = `${stage === "flower" ? "Flower" : "Veg"} room${n === 1 ? "" : "s"}`;
              return (
                <button
                  key={stage}
                  type="button"
                  className="wt-chip"
                  aria-pressed={on}
                  disabled={on && (q.stages.length === 1 || stagesShown.length === 1)}
                  onClick={() => toggleStage(stage)}
                >
                  {label}
                </button>
              );
            })}
          {linked.length > 0 && (
            <button type="button" className="wt-chip" aria-pressed="true" onClick={() => change({ rooms: [] })} aria-label="Show every room">
              Only {linked.map((room) => room.name).join(", ")} <X size={14} aria-hidden="true" />
            </button>
          )}
          <button type="button" className="wt-chip" aria-pressed={q.problemsOnly} onClick={() => change({ problemsOnly: !q.problemsOnly })}>
            Problems only
          </button>
          {failedCount > 0 && (
            <button type="button" className="wt-chip wt-failed" onClick={nextFailed} data-watering-failed>
              {failedCount === 1 ? "1 shot failed" : `${failedCount} shots failed`} <ChevronRight size={14} aria-hidden="true" />
            </button>
          )}
        </div>

        {stale && (
          <p className="wt-note" role="status">
            Live updates paused — reconnecting
          </p>
        )}
        {timeline.state === "error" && (
          <div className="wt-error" role="alert">
            <p>
              Couldn't load the watering plan.
              {lastGood.current && ` Showing what we had at ${clock(lastGood.current.at, timeZone)}.`}
            </p>
            <Button variant="outline" size="sm" onClick={timeline.reload}>
              Try again
            </Button>
          </div>
        )}
        {data?.truncated && <p className="wt-note">Showing the newest shots only</p>}

        <div className="wt-body" ref={body}>
          {!data && timeline.state !== "error" ? (
            <div className="wt-skeleton" aria-busy="true" aria-label="Loading the watering plan">
              {Array.from({ length: 6 }, (_, i) => (
                <span key={i} />
              ))}
            </div>
          ) : empty ? (
            <div className="wt-empty">
              <p>No watering planned for this day.</p>
              <Button variant="outline" onClick={() => navigate("plan/timers")}>
                Set up a timer
              </Button>
            </div>
          ) : (
            data && (
              <ShotTimeline
                rows={rows}
                span={span}
                now={now}
                mode="full"
                orientation={phone ? "vertical" : "horizontal"}
                timeZone={timeZone}
                stale={stale}
                focusIds={focusIds}
                collapsedRooms={collapsed}
                onToggleRoom={toggleRoom}
                onBlock={(block, anchor) => {
                  setNote(null);
                  setOpen({ block, anchor });
                }}
              />
            )
          )}
        </div>
      </section>

      <Popover.Root open={!!open} onOpenChange={(next) => !next && setOpen(null)}>
        <Popover.Anchor virtualRef={{ current: open?.anchor ?? null }} />
        <Popover.Portal>
          {shown && open && (
            <Popover.Content
              className="wt-pop"
              aria-label={`${where(shown)}, ${clock(shown.start, timeZone)}`}
              side={phone ? "bottom" : "right"}
              align="start"
              sideOffset={8}
              collisionPadding={12}
              onCloseAutoFocus={(event) => {
                event.preventDefault();
                open.anchor.isConnected && open.anchor.focus();
              }}
            >
              <BlockDetails
                block={shown}
                where={where(shown)}
                when={dayKey(shown.start, timeZone) === today ? "Today" : dayLabel(shown.start, timeZone)}
                timeZone={timeZone}
                href={zoneHref(window.location.search, shown.roomId, shown.zone)}
                busy={busy}
                note={note}
                onOpenZone={(event) => {
                  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
                  event.preventDefault();
                  goZone(shown, "zone");
                }}
                onSkip={() => void skip(shown)}
                onHistory={() => goZone(shown, "history/explorer")}
              />
            </Popover.Content>
          )}
        </Popover.Portal>
      </Popover.Root>
    </>
  );
}

function BlockDetails({
  block,
  where,
  when,
  timeZone,
  href,
  busy,
  note,
  onOpenZone,
  onSkip,
  onHistory,
}: {
  block: TimelineBlock;
  where: string;
  when: string;
  timeZone: string;
  href: string;
  busy: boolean;
  note: string | null;
  onOpenZone(event: MouseEvent<HTMLAnchorElement>): void;
  onSkip(): void;
  onHistory(): void;
}) {
  const planned = block.glyph === "planned" || block.glyph === "expected";
  const perPlant = block.litresPerPlant === null ? null : plantAmount(block.litresPerPlant * 1000);
  const water = [
    perPlant && `${perPlant.value.toFixed(perPlant.digits)} ${perPlant.unit} per plant`,
    block.meteredL !== null && block.litres !== null
      ? `${litresText(block.meteredL)} arrived of ${litresText(block.litres)}`
      : block.meteredL !== null
        ? `${litresText(block.meteredL)} arrived`
        : block.litres !== null && `${litresText(block.litres)} for the zone`,
  ].filter(Boolean);
  const vwc =
    block.vwcBefore === null && block.vwcExpected === null
      ? null
      : [
          block.vwcBefore !== null && `${planned ? "now" : "before"} ${pct(block.vwcBefore)}`,
          block.vwcExpected !== null && `expected ${pct(block.vwcExpected)}`,
        ]
          .filter(Boolean)
          .join(" → ");
  const source = block.source ? (SOURCES[block.source] ?? block.source[0].toUpperCase() + block.source.slice(1)) : null;
  const time = block.end > block.start ? `${clock(block.start, timeZone)} – ${clock(block.end, timeZone)}` : clock(block.start, timeZone);
  return (
    <div className="wt-pop-body" data-watering-popover>
      <div className="wt-pop-head">
        <div>
          <small>
            {where} · {when}
          </small>
          <strong>{time}</strong>
        </div>
        <Popover.Close className="wt-pop-close" aria-label="Close">
          <X size={18} />
        </Popover.Close>
      </div>
      <p className="wt-pop-status" data-glyph={block.glyph} data-running={block.running || undefined}>
        {statusLine(block)}
      </p>
      {block.reason && <p className="wt-pop-reason">{block.reason}</p>}
      <dl className="wt-pop-rows">
        {water.length > 0 && (
          <div>
            <dt>Water</dt>
            <dd>{water.join(" · ")}</dd>
          </div>
        )}
        {vwc && (
          <div>
            <dt>VWC</dt>
            <dd>{vwc}</dd>
          </div>
        )}
        {source && (
          <div>
            <dt>Source</dt>
            <dd>
              <span className="wt-source">{source}</span>
              {block.code && <code>{block.code}</code>}
            </dd>
          </div>
        )}
      </dl>
      {note && (
        <p className="wt-pop-note" role="alert">
          {note}
        </p>
      )}
      <div className="wt-pop-foot">
        <a href={href} onClick={onOpenZone}>
          Open {where}
        </a>
        {block.glyph === "failed" && (
          <Button variant="outline" size="sm" onClick={onHistory}>
            See what happened
          </Button>
        )}
        {block.skippable && !block.skipped && (
          <Button variant="outline" size="sm" onClick={onSkip} disabled={busy}>
            Skip this shot
          </Button>
        )}
      </div>
    </div>
  );
}
