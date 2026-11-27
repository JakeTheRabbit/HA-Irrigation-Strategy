import { AlertTriangle, ChevronLeft, ChevronRight, Droplets, Layers, TriangleAlert, X } from "lucide-react";
import { Popover } from "radix-ui";
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { toast } from "sonner";
import { Heading } from "@/components/dashboard";
import { KpiCard, KpiGrid } from "@/components/ha-primitives";
import { NeedsIntegration } from "@/components/needs-integration";
import { ShotTimeline } from "@/components/shot-timeline";
import { Button } from "@/components/ui/button";
import { formatVolume } from "@/lib/display-units";
import { useCsEvents } from "@/lib/events";
import { irrigationMode, pickKey } from "@/lib/facility";
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
  bodyState,
  dayChip,
  dayProblems,
  dayStart,
  defaultSpan,
  failedTap,
  keepProblems,
  keptData,
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

/** A pick in the room tree remounts the page in the picked room; the address keeps the query
 * (openRoomPage), and the collapsed rooms stand in from here then, and only then (any other way in
 * starts clean). `treeAt` is when the room tree was last clicked; a header room switch is not a pick. */
const memory: { room: string | null; collapsed: Set<string>; treeAt: number } = {
  room: null,
  collapsed: new Set(),
  treeAt: 0,
};
const markTree = (event: Event) => {
  if (event.target instanceof Element && event.target.closest(".room-tree")) memory.treeAt = Date.now();
};
/** Whether the page mounted from a room-tree pick of another room (pure: a render may run twice). */
const treePicked = (roomId: string) =>
  memory.room !== null && memory.room !== roomId && Date.now() - memory.treeAt < 2000;

/** Failed or warning shots dismissed from the strip above the timeline (block ids, newest 500). */
const DISMISSED_KEY = "crop-steering.watering-dismissed";

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
  const [picked] = useState(() => treePicked(controller.roomId));
  const [q, setQ] = useState(() =>
    initialQuery(
      typeof window === "undefined" ? "" : window.location.hash,
      typeof window === "undefined" ? 1440 : window.innerWidth,
    ),
  );
  // Any way in but a tree pick starts clean.
  useEffect(() => {
    if (!picked) memory.collapsed = new Set();
    memory.treeAt = 0;
  }, []);
  useEffect(() => {
    document.addEventListener("click", markTree, true);
    return () => document.removeEventListener("click", markTree, true);
  }, []);
  const change = (next: Partial<WateringQuery>) => {
    const merged = { ...q, ...next };
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

  // The rooms shown: a link's rooms, else the room picked in the room list (every room with "All
  // rooms"), the picked room first; then the stages chosen.
  const stages = new Map(controller.rooms.map((room) => [room.id, stageOf(controller, room)]));
  const linked = q.rooms.flatMap((name) => resolveRequestedRoom(controller.rooms, name) ?? []);
  const current = controller.rooms.find((room) => room.id === controller.roomId);
  const rooms = (linked.length ? linked : !q.all && current ? [current] : controller.rooms)
    .slice()
    .sort((a, b) =>
      a.id === controller.roomId ? -1 : b.id === controller.roomId ? 1 : a.name.localeCompare(b.name, undefined, { numeric: true }),
    )
    .filter(
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
  // What was last read, kept through a failed read of the same rooms and span (never drawn under
  // another date).
  const readKey = JSON.stringify([ids, span.start, span.end]);
  const lastGood = useRef<{ key: string; data: TimelineGetData; at: number } | null>(null);
  if (timeline.data && lastGood.current?.data !== timeline.data)
    lastGood.current = { key: readKey, data: timeline.data, at: Date.now() };
  const kept = timeline.state === "error" ? keptData(lastGood.current, readKey) : null;
  const data = timeline.data ?? kept?.data ?? null;

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
  const all = useMemo(() => {
    if (!data) return [];
    // Each zone's chip is its phase or mode now, as the room list shows it, whatever day is drawn.
    const built = new Map(rooms.map((room) => [room.id, { room, zones: buildRoom(controller.states, room).zones }]));
    return toTimelineRows(data, plants, rooms.map((room) => roomMeta(controller, room))).map((row) => {
      const at = built.get(row.roomId);
      if (row.zone === null || !at) return row;
      if (irrigationMode(controller.states, at.room, row.zone) === "timer") return { ...row, sublabel: "Timer" };
      const phase = at.zones.find((zone) => zone.id === row.zone)?.phase ?? "";
      return { ...row, sublabel: /^P[0-3]$/.test(phase) ? phase : "" };
    });
  }, [data, controller.states]);
  const rows = matchQuery(q.problemsOnly ? keepProblems(all) : all, q.q);
  const names = new Map(rooms.map((room) => [room.id, room.name]));

  // Collapsed rooms; a room chosen in the room tree opens and comes into view.
  const [collapsed, setCollapsed] = useState(() => {
    const next = new Set(picked ? memory.collapsed : []);
    next.delete(controller.roomId);
    return next;
  });
  const scrollPending = useRef(picked);
  useEffect(() => {
    memory.room = controller.roomId;
  }, [controller.roomId]);
  useEffect(() => {
    memory.collapsed = collapsed;
  }, [collapsed]);
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!scrollPending.current || !rows.length) return;
    scrollPending.current = false;
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
  const [dismissed, setDismissed] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(DISMISSED_KEY) ?? "[]") as string[]);
    } catch {
      return new Set();
    }
  });
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
  // The phone's day line counts the whole day: its "N failed" opens 24 h, then the first failed shot.
  const [failedPending, setFailedPending] = useState(false);
  const tapFailed = () => {
    cycle.current = 0;
    const next = failedTap(q);
    if (next === q) return nextFailed();
    change(next);
    setFailedPending(true);
  };
  useEffect(() => {
    // Only once the wider span's answer is in (the old one stays while it loads).
    if (!failedPending || timeline.state !== "ready" || lastGood.current?.key !== readKey) return;
    setFailedPending(false);
    // None in the wider span (the day line counted another span's): nothing to focus.
    if (markers.length) nextFailed();
  }, [failedPending, timeline.state, timeline.data, readKey, markers.length]);

  // The block popover.
  const [open, setOpen] = useState<{ block: TimelineBlock; anchor: HTMLElement } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const shown = open ? (rows.flatMap((r) => r.blocks).find((b) => b.id === open.block.id) ?? open.block) : null;
  const where = (b: TimelineBlock) => `${names.get(b.roomId) ?? b.roomId} ${b.zone === 0 ? "room" : `Zone ${b.zone}`}`;
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
      if (!result.verified) return void toast("Skip sent, not confirmed. Check the timeline.");
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

  const shows = timeline.state === "ready" ? bodyState(rows, all, q.problemsOnly, q.q) : "timeline";
  // Surface failed/warning shots inline above the timeline so operators immediately see which zone
  // failed and when, without hunting for a narrow bar (plain array: safe after the early return).
  const problemBlocks: { block: TimelineBlock; roomName: string }[] = [];
  for (const row of rows) {
    if (row.zone === null) continue;
    for (const b of row.blocks) {
      if (b.glyph === "failed" || b.glyph === "warning") {
        problemBlocks.push({ block: b, roomName: names.get(b.roomId) ?? b.roomId });
      }
    }
  }
  problemBlocks.sort((a, b) =>
    a.block.glyph === b.block.glyph ? b.block.start - a.block.start : a.block.glyph === "failed" ? -1 : 1,
  );
  // A shot dismissed from the strip stays on the timeline; only the strip forgets it.
  const stripShown = problemBlocks.filter((p) => !dismissed.has(p.block.id));
  const dismiss = (blockIds: string[]) => {
    const next = [...dismissed, ...blockIds].slice(-500);
    setDismissed(new Set(next));
    try {
      localStorage.setItem(DISMISSED_KEY, JSON.stringify(next));
    } catch {
      /* private mode: dismissed for this visit only */
    }
  };
  const jumpToBlock = (b: TimelineBlock) => {
    if (collapsed.has(b.roomId)) toggleRoom(b.roomId);
    setFocusIds([b.id]);
    requestAnimationFrame(() =>
      body.current?.querySelector<HTMLButtonElement>(`.st-block[data-id="${CSS.escape(b.id)}"]`)?.focus(),
    );
  };
  const totalShots = rows.reduce((sum, r) => (r.zone === null ? sum : sum + r.blocks.length), 0);
  const failedInView = problemBlocks.filter((p) => p.block.glyph === "failed").length;
  const warnInView = problemBlocks.filter((p) => p.block.glyph === "warning").length;
  return (
    <>
      <Heading title="Timeline" description={phone ? "All rooms · swipe for more" : undefined} action={phone ? spanToggle : undefined} />
      <KpiGrid>
        <KpiCard
          icon={Droplets}
          tone="primary"
          label="Shots in window"
          value={totalShots}
          detail={`${spanHours} h window · ${dayWords(date)}`}
        />
        <KpiCard
          icon={AlertTriangle}
          tone={failedInView > 0 ? "error" : "success"}
          label="Failed shots"
          value={failedInView}
          detail={failedInView > 0 ? "Click to focus failed" : "None failed"}
          onClick={failedInView > 0 ? tapFailed : undefined}
        />
        <KpiCard
          icon={TriangleAlert}
          tone={warnInView > 0 ? "warning" : "neutral"}
          label="Warnings"
          value={warnInView}
          detail={warnInView > 0 ? "Review highlighted shots" : "No warnings"}
        />
        <KpiCard
          icon={Layers}
          tone="neutral"
          label="Rooms shown"
          value={rooms.length}
          detail={rooms.map((r) => r.name).join(" · ")}
        />
      </KpiGrid>
      <section className="panel watering" aria-label="Watering timeline" data-watering>
        {phone ? (
          <div className="wt-dayline" data-watering-day>
            <button type="button" aria-label="Day before" onClick={() => change({ date: shiftDate(date, -1) })}>
              <ChevronLeft size={20} />
            </button>
            <p>
              <strong>{dayWords(date)}</strong>
              <span data-tone={problemWords.length ? "problem" : undefined}>
                {problems.failed > 0 && (
                  <button type="button" className="wt-dayfailed" onClick={tapFailed} data-watering-day-failed>
                    {problems.failed} failed
                  </button>
                )}
                {problems.failed > 0 && problems.warnings > 0 && " · "}
                {problems.warnings > 0 && `${problems.warnings} warning${problems.warnings === 1 ? "" : "s"}`}
                {!problemWords.length && (summary.data ? "No problems" : " ")}
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
          {!linked.length && controller.rooms.length > 1 && (
            <button type="button" className="wt-chip" aria-pressed={!!q.all} onClick={() => change({ all: !q.all })} data-watering-all>
              All rooms
            </button>
          )}
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
              {kept && ` Showing what we had at ${clock(kept.at, timeZone)}.`}
            </p>
            <Button variant="outline" size="sm" onClick={timeline.reload}>
              Try again
            </Button>
          </div>
        )}
        {data?.truncated && <p className="wt-note">Showing the newest shots only</p>}
        {stripShown.length > 0 && (
          <ul className="wt-problem-strip" aria-label="Shots with problems">
            {stripShown.slice(0, 4).map(({ block, roomName }) => (
              <li key={block.id} data-glyph={block.glyph}>
                <button type="button" onClick={() => jumpToBlock(block)}>
                  <strong>
                    {roomName} {block.zone === 0 ? "Room" : `Zone ${block.zone}`}
                  </strong>{" "}
                  <span>
                    {clock(block.start, timeZone)} · {block.glyph === "failed" ? "failed" : "warning"}
                    {block.reason ? ` — ${block.reason}` : ""}
                  </span>
                </button>
                <button
                  type="button"
                  className="wt-problem-dismiss"
                  aria-label={`Dismiss ${roomName} ${clock(block.start, timeZone)}`}
                  onClick={() => dismiss([block.id])}
                >
                  <X size={14} aria-hidden="true" />
                </button>
              </li>
            ))}
            <li className="wt-problem-more">
              {stripShown.length > 4 && <span>+{stripShown.length - 4} more · </span>}
              <button type="button" onClick={() => dismiss(stripShown.map((p) => p.block.id))} data-watering-dismiss-all>
                Dismiss all
              </button>
            </li>
          </ul>
        )}

        <div className="wt-body" ref={body}>
          {!data && timeline.state !== "error" ? (
            <div className="wt-skeleton" role="status" aria-busy="true" aria-label="Loading the watering plan">
              {Array.from({ length: 6 }, (_, i) => (
                <span key={i} />
              ))}
            </div>
          ) : shows === "empty" ? (
            <div className="wt-empty">
              <p>No watering planned for this day.</p>
              <Button variant="outline" onClick={() => navigate("plan/timers")}>
                Set up a timer
              </Button>
            </div>
          ) : shows === "no-match" ? (
            <p className="wt-note" data-watering-no-match>
              No rooms or zones match
            </p>
          ) : shows === "no-problems" ? (
            <p className="wt-note" data-watering-no-problems>
              No problems on this day.
            </p>
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
