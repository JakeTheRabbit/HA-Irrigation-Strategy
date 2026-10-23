import { Check, X } from "lucide-react";
import { AskWhy } from "@/components/ask-why";
import { DayLanes } from "@/components/day-lanes";
import { HistoryExplorer, RoomExplorer } from "@/components/history-explorer";
import { Pill } from "@/components/mini-visuals";
import { OnThisDay } from "@/components/on-this-day";
import { RecordedBehaviour } from "@/components/recorded-behaviour";
import { attachOutcomes, jevAnswer, jevResult, outcomeText, readJev } from "@/lib/jev";
import { clock } from "@/lib/time";
import type { Controller } from "@/lib/types";
import { dayWord } from "@/lib/utils";
import "./explorer.css";

/** History › Explorer (mockup 09): the room's readings on stacked charts under its phase and shot
 * lanes, notes where something happened, one crosshair, the last run beside it and a CSV of what is
 * charted. A zone picked in the room list adds its probes, its targets and its other grows below.
 * Who changed which setting is on History › Changes. */
export function Explorer({ controller, zone }: { controller: Controller; zone?: number }) {
  const { room } = controller;
  const picked = room.zones.find((item) => item.id === zone);
  return (
    <>
      <RoomExplorer key={controller.roomId} controller={controller} zone={picked?.id} />
      {room.display.options.show_equipment_lanes && <DayLanes controller={controller} mode="equipment" />}
      {room.display.options.show_room_day_lanes && <DayLanes controller={controller} mode="zones" />}
      {picked ? (
        <details className="explorer-zone" open data-zone-detail={picked.id}>
          <summary>{picked.name}: each probe, its targets and other grows</summary>
          <HistoryExplorer key={`${controller.roomId}-${picked.id}`} controller={controller} zone={picked} />
          <RecordedBehaviour key={`targets-${controller.roomId}-${picked.id}`} controller={controller} zone={picked} />
          <OnThisDay key={`on-this-day-${controller.roomId}-${picked.id}`} controller={controller} zone={picked} />
        </details>
      ) : (
        <p className="muted small explorer-zone-hint">
          Pick a zone in the room list to see each of its probes, its targets and its other grows.
        </p>
      )}
      <AiDecisions controller={controller} zone={picked?.id} />
      <AskWhy controller={controller} zone={picked?.id} />
    </>
  );
}

/** The AI assistant's decisions that did something or tried to, newest first, each with how it
 * turned out: kept here until the AI assistant's own page lists them in full. */
function AiDecisions({ controller, zone }: { controller: Controller; zone?: number }) {
  const { log } = readJev(controller.states, controller.room.room.prefix);
  if (!log) return null;
  const { rest, outcomes } = attachOutcomes(log.entries);
  const acted = rest
    .filter((entry) => !["no action", "waiting", "unknown"].includes(entry.result))
    .filter((entry) => zone === undefined || entry.zone === zone)
    .slice(0, 30);
  const names = new Map(controller.room.zones.map((item) => [item.id, item.name]));
  const now = Date.now();
  return (
    <section className="panel explorer-ai" aria-labelledby="explorer-ai-title">
      <div className="panel-heading">
        <h2 id="explorer-ai-title">AI assistant decisions</h2>
      </div>
      {acted.length ? (
        <ol className="explorer-ai-list">
          {acted.map((entry) => {
            const result = jevResult(entry);
            const checked = outcomes.get(entry.key)?.at(-1);
            return (
              <li key={entry.key} data-ai-decision={entry.result}>
                <time>
                  {entry.time === null ? "—" : `${dayWord(entry.time, now) ? `${dayWord(entry.time, now)} ` : ""}${clock(entry.time, controller.timeZone)}`}
                </time>
                <span className="muted">{entry.zone === null ? "Room" : (names.get(entry.zone) ?? `Zone ${entry.zone}`)}</span>
                <span>
                  <strong>{entry.title}</strong>{" "}
                  {entry.kind === "outcome" ? `after “${entry.verdict || "an earlier call"}”` : jevAnswer(entry)}
                  {entry.action && <> → {entry.action.replaceAll("->", "→")}</>}
                </span>
                <span className="explorer-ai-result">
                  <Pill tone={result.tone}>{result.label}</Pill>
                  {checked && (
                    <span className="explorer-outcome" data-worked={checked.result === "worked"} title={outcomeText(checked)}>
                      {checked.result === "worked" ? <Check size={13} aria-hidden="true" /> : <X size={13} aria-hidden="true" />}
                      <span className="sr-only">{outcomeText(checked)}</span>
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="muted small">No AI assistant decision acted in this {zone === undefined ? "room" : "zone"} yet.</p>
      )}
    </section>
  );
}
