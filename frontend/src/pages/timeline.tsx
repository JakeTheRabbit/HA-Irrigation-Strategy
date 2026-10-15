import { useState } from "react";
import {
  Bot,
  Check,
  Download,
  Droplets,
  Info,
  Repeat,
  Search,
  SlidersHorizontal,
  TriangleAlert,
  X,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Empty, Heading, time as clock } from "@/components/dashboard";
import { JevTrouble, jevUsage } from "@/components/jev-status";
import { Pill } from "@/components/mini-visuals";
import { jevAnswer, jevResult, outcomeText, readJev } from "@/lib/jev";
import {
  byHand,
  filterTimeline,
  jevActed,
  mergeTimeline,
  NO_FILTER,
  timelineCsv,
  type TimelineFilter,
  type TimelineItem,
  type TimelineKind,
  type TimelineType,
} from "@/lib/timeline";
import type { Controller } from "@/lib/types";
import { dayWord } from "@/lib/utils";
import "./timeline.css";

const KINDS: Record<TimelineKind, { label: string; icon: LucideIcon }> = {
  water: { label: "Water", icon: Droplets },
  phase: { label: "Phase", icon: Repeat },
  setpoint: { label: "Setpoint", icon: SlidersHorizontal },
  alert: { label: "Alert", icon: TriangleAlert },
  jev: { label: "Jev", icon: Bot },
  note: { label: "Note", icon: Info },
};
const TYPES: { type: TimelineType; label: string }[] = [
  { type: "all", label: "All" },
  { type: "water", label: "Water" },
  { type: "phase", label: "Phase" },
  { type: "setpoint", label: "Setpoints" },
  { type: "alert", label: "Alerts" },
  { type: "jev", label: "Jev" },
];

/** History › Timeline: what watered, when and why; phase changes; setpoint changes, the grower's and
 * Jev's; alerts; and Jev's decisions with how they turned out. One list, newest first. */
export function Timeline({ controller, zone }: { controller: Controller; zone?: number }) {
  const [filter, setFilter] = useState<TimelineFilter>({ ...NO_FILTER, zone: zone ?? "all" });
  const { room, states } = controller;
  const jev = readJev(states, room.room.prefix);
  const now = Date.now();
  const items = mergeTimeline(room.events, jev.log?.entries ?? [], now);
  const shown = filterTimeline(items, filter);
  const quiet = items.filter((item) => item.jev && !jevActed(item.jev)).length;
  const names = new Map(room.zones.map((item) => [item.id, item.name]));
  const set = (change: Partial<TimelineFilter>) =>
    setFilter((current) => ({ ...current, ...change }));
  const days = groupByDay(shown, now);
  function exportCsv() {
    const url = URL.createObjectURL(
      new Blob(["﻿", timelineCsv(shown, room.room.name)], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${
      room.room.name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "") || "room"
    }-timeline-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <>
      <Heading
        title="Timeline"
        action={
          <Button variant="outline" disabled={!shown.length} onClick={exportCsv}>
            <Download size={16} />
            Export CSV
          </Button>
        }
      />
      <div className="toolbar timeline-toolbar">
        <div className="search-field">
          <Search size={17} />
          <Input
            aria-label="Search the timeline"
            placeholder="Search the timeline…"
            value={filter.query}
            onChange={(event) => set({ query: event.target.value })}
          />
        </div>
        <select
          aria-label="Timeline zone"
          value={String(filter.zone)}
          onChange={(event) => {
            const value = event.target.value;
            set({ zone: value === "all" || value === "room" ? value : Number(value) });
          }}
        >
          <option value="all">All zones and the room</option>
          <option value="room">The room only</option>
          {room.zones.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <div className="timeline-types" role="group" aria-label="Record type">
          {TYPES.map((item) => (
            <button
              type="button"
              key={item.type}
              aria-pressed={filter.type === item.type}
              onClick={() => set({ type: item.type })}
            >
              {item.label}
            </button>
          ))}
        </div>
        {jev.log && (
          <label className="timeline-all-jev">
            <input
              type="checkbox"
              checked={filter.allJev}
              onChange={(event) => set({ allJev: event.target.checked })}
            />
            All Jev decisions
            {quiet > 0 && <span className="muted">({quiet} that changed nothing)</span>}
          </label>
        )}
        <span className="muted small timeline-count">
          {shown.length} {shown.length === 1 ? "record" : "records"}
        </span>
      </div>
      {jev.room && (
        <div className="timeline-jev-usage">
          <p className="muted small">Jev: {jevUsage(jev.room)}</p>
          <JevTrouble jev={jev.room} />
        </div>
      )}
      <section className="panel timeline-panel" aria-label="Timeline records">
        {!shown.length ? (
          <Empty
            title={items.length ? "Nothing matches this view" : "No records yet"}
            detail={
              items.length
                ? "Change the search or the filters to see more."
                : "The controller has published no activity records and Jev no decisions. This does not confirm that no irrigation occurred."
            }
            action={
              items.length ? (
                <Button variant="outline" onClick={() => setFilter(NO_FILTER)}>
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          days.map((day) => (
            <div className="timeline-day" key={day.label}>
              <h2>{day.label}</h2>
              <ol className="timeline-list">
                {day.items.map((item) => (
                  <Row key={item.key} item={item} names={names} />
                ))}
              </ol>
            </div>
          ))
        )}
      </section>
      <p className="footnote">
        The controller’s own activity records and Jev’s journal, as the controller publishes them.
        Home Assistant’s logbook may hold more. Jev answers; code decides what it may do and refuses
        what it may not.
      </p>
    </>
  );
}

/** Rows under "Today", "Yesterday" or the date; a row without a readable time under its own. */
function groupByDay(items: TimelineItem[], now: number) {
  const days: { label: string; items: TimelineItem[] }[] = [];
  for (const item of items) {
    const label = item.time === null ? "Time not recorded" : dayWord(item.time, now) || "Today";
    const last = days.at(-1);
    if (last?.label === label) last.items.push(item);
    else days.push({ label, items: [item] });
  }
  return days;
}

function Row({ item, names }: { item: TimelineItem; names: Map<number, string> }) {
  const kind = KINDS[item.kind];
  const zone = item.zone === null ? "Room" : (names.get(item.zone) ?? `Zone ${item.zone}`);
  const entry = item.jev;
  const hand = !!entry && byHand(entry);
  return (
    <li className="timeline-row" data-kind={item.kind} data-source={entry ? "jev" : "controller"}>
      <time
        className="timeline-time"
        dateTime={item.time === null ? undefined : new Date(item.time).toISOString()}
      >
        {item.time === null ? "—" : clock(item.time)}
      </time>
      <span className="timeline-kind" data-kind={item.kind}>
        <kind.icon size={14} aria-hidden="true" />
        {kind.label}
      </span>
      <span className="timeline-zone">{zone}</span>
      <span className="timeline-what">
        {entry && hand ? (
          <>
            <span className="timeline-jev-tag" data-by="you">
              You
            </span>{" "}
            <strong>{entry.title}</strong> {entry.action.replaceAll("->", "→")}
            {entry.reason && <span className="timeline-why">{entry.reason}</span>}
          </>
        ) : entry ? (
          <>
            {item.kind !== "jev" && <span className="timeline-jev-tag">Jev</span>}{" "}
            <strong>{entry.title}</strong>{" "}
            {entry.kind === "outcome"
              ? `after “${entry.verdict || "an earlier call"}”`
              : jevAnswer(entry)}
            {entry.action && <> → {entry.action.replaceAll("->", "→")}</>}
            {entry.agreed === false && (
              <span className="timeline-why">The two phrasings of the question disagreed.</span>
            )}
            {entry.reason && entry.kind === "decision" && (
              <span className="timeline-why" data-refused={entry.result === "refused" || undefined}>
                {entry.reason}
              </span>
            )}
          </>
        ) : (
          item.event!.message
        )}
      </span>
      {entry && (
        <span className="timeline-result">
          {hand ? (
            <Pill tone="neutral" data-jev-result="by hand">
              Noted by Jev
            </Pill>
          ) : (
            <Pill tone={jevResult(entry).tone} data-jev-result={entry.result}>
              {jevResult(entry).label}
            </Pill>
          )}
          {item.outcomes.map((outcome) => (
            <span
              key={outcome.key}
              className="timeline-outcome"
              data-worked={outcome.result === "worked"}
              title={outcomeText(outcome)}
            >
              {outcome.result === "worked" ? (
                <Check size={13} aria-hidden="true" />
              ) : (
                <X size={13} aria-hidden="true" />
              )}
              <span className="sr-only">{outcomeText(outcome)}</span>
            </span>
          ))}
        </span>
      )}
    </li>
  );
}
