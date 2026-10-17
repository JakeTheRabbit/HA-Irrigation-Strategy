import { useEffect, useId, useState, type ReactElement } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Page } from "@/lib/routes";
import { dateInZone } from "@/lib/comparison";
import type { RunsDocument } from "@/lib/comparison-types";
import { planState } from "@/lib/grow-plan";
import { readJev } from "@/lib/jev";
import type { StrategyDocument } from "@/lib/operator-types";
import { currentRun, feedToday, runProgress, type RunPhase } from "@/lib/run-progress";
import type { Controller } from "@/lib/types";
import "./run-progress.css";

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;
const dateText = (date: string) =>
  new Date(date + "T00:00:00").toLocaleDateString([], { day: "numeric", month: "short" });
const SOURCE: Record<string, string> = {
  schedule: "The feed schedule selects this recipe for this week.",
  held: "A person selected this recipe. It stays until the next week of the feed schedule.",
  hand: "A person selected this recipe. No feed schedule runs.",
  batch: "The batch tank uses its own recipe. No feed schedule runs.",
};
const END_FROM = {
  run: "The end date of the run sets this date.",
  plan: "The last day of the grow plan sets this date.",
  stage: "The flower length from the controller sets this date.",
};

/** A tooltip on one element: shown on hover and on keyboard focus. */
function Tip({ text, children }: { text: string; children: ReactElement }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="top" className="run-progress-tip">
        {text}
      </TooltipContent>
    </Tooltip>
  );
}

/** Today's run strip: the room's run from day 1 to its last day, by the phases of the grow, and the
 * grow plan and feed recipe that run today. A room with no run says so and links to the run records. */
export function RunProgress({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: (page: Page) => void;
}) {
  const titleId = useId();
  const { roomId, operator, room, states } = controller;
  const [loaded, setLoaded] = useState<{
    roomId: string;
    runs: RunsDocument | null;
    plan: StrategyDocument | null;
  } | null>(null);
  useEffect(() => {
    if (!roomId) return;
    let live = true;
    Promise.all([
      operator<RunsDocument>("runs_get").catch(() => null),
      // An older integration has no grow plans: the strip then has no plan phases.
      operator<StrategyDocument>("strategy_get").catch(() => null),
    ]).then(([runs, plan]) => {
      if (live) setLoaded({ roomId, runs, plan });
    });
    return () => {
      live = false;
    };
  }, [roomId, operator]);
  const stage = readJev(states, room.room.prefix).room?.stage ?? null;
  const stageSummary = stage ? (
    <span>
      {stage.name.charAt(0).toUpperCase() + stage.name.slice(1)}
      {stage.day !== null
        ? ` · flower day ${stage.day}${stage.days !== null ? ` of ${stage.days}` : ""}`
        : ""}
    </span>
  ) : null;
  // Nothing until this room's runs are read; nothing at all from an integration without runs.
  if (!loaded || loaded.roomId !== roomId || !loaded.runs)
    return stageSummary ? (
      <section className="panel run-progress" aria-label="Room growing context">
        {stageSummary}
      </section>
    ) : null;
  const timeZone = loaded.runs.time_zone || controller.timeZone || "UTC";
  const today = dateInZone(Date.now(), timeZone);
  const run = currentRun(loaded.runs.runs, today);
  if (!run)
    return (
      <section className="panel run-progress" aria-labelledby={titleId} data-run-progress="none">
        <p className="run-progress-empty">
          <span id={titleId}>No run is active in this room. {stageSummary}</span>
          <Button size="sm" variant="outline" onClick={() => navigate("settings")}>
            Add a run
          </Button>
        </p>
      </section>
    );
  const view = runProgress({
    run,
    today,
    plan: loaded.plan,
    zoneIds: room.zones.map((zone) => zone.id),
    stage,
  });
  const feed = feedToday(states[`sensor.crop_steering_${room.room.prefix}dosing_config`]);
  const plan = loaded.plan?.plan;
  const status = loaded.plan ? planState(loaded.plan) : null;
  const total = view.days;
  const share = (days: number) => (total ? `${(Math.min(days, total) / total) * 100}%` : "0%");
  const past = total !== null && view.day > total;
  const stageName = stage?.name ?? view.phase?.label ?? null;
  return (
    <section
      className="panel run-progress"
      aria-labelledby={titleId}
      data-run-progress={past ? "past" : "running"}
    >
      <div className="run-progress-head">
        <h2 id={titleId}>
          <Tip text={`The run record of this room. It started on ${dateText(view.start)}.`}>
            <span tabIndex={0}>{run.name}</span>
          </Tip>
        </h2>
        <dl className="run-progress-numbers">
          <Tip
            text={`Today is day ${view.day} of the run. Day 1 is the start date, ${dateText(view.start)}.`}
          >
            <div tabIndex={0} data-run-figure="day">
              <dt>Day</dt>
              <dd>
                {view.day}
                {total !== null && <small> of {total}</small>}
              </dd>
            </div>
          </Tip>
          <Tip text={`The run has ${plural(view.done, "completed day")}. Today is not included.`}>
            <div tabIndex={0} data-run-figure="done">
              <dt>Done</dt>
              <dd>{view.done}</dd>
            </div>
          </Tip>
          <Tip
            text={
              view.left === null
                ? "Set an end date for the run or a grow plan to show the days that stay."
                : `${plural(view.left, "day")} stay in the run. This number includes today.`
            }
          >
            <div tabIndex={0} data-run-figure="left">
              <dt>Left</dt>
              <dd>{view.left ?? "–"}</dd>
            </div>
          </Tip>
          <Tip
            text={
              view.end && view.endFrom
                ? `The last day of the run is ${dateText(view.end)}. ${END_FROM[view.endFrom]}`
                : "No end date is set. Set it in Settings, Run records, or in a grow plan."
            }
          >
            <div tabIndex={0} data-run-figure="end" data-tone={past ? "warn" : undefined}>
              <dt>{past ? "Ended" : "Harvest"}</dt>
              <dd>{view.end ? dateText(view.end) : "not set"}</dd>
            </div>
          </Tip>
        </dl>
      </div>
      {total !== null && (
        <div className="run-bar-wrap">
          <div
            className="run-bar"
            role="progressbar"
            aria-label="Run progress"
            aria-valuemin={0}
            aria-valuemax={total}
            aria-valuenow={view.done}
            aria-valuetext={`Day ${view.day} of ${total}: ${plural(view.done, "day")} done, ${plural(view.left ?? 0, "day")} left`}
          >
            {view.phases.map((phase) => (
              <span
                key={phase.first}
                className="run-bar-phase"
                data-current={phase === view.phase || undefined}
                style={{ left: share(phase.first - 1), width: share(phase.last - phase.first + 1) }}
              />
            ))}
            <span className="run-bar-done" style={{ width: share(view.done) }} />
            {!past && <span className="run-bar-today" style={{ left: share(view.done) }} />}
          </div>
          {view.phases.length > 0 && (
            <ol className="run-phases" aria-label="Phases of the grow">
              {view.phases.map((phase, index) => (
                <PhaseLabel
                  key={phase.first}
                  phase={phase}
                  index={index}
                  total={total}
                  current={phase === view.phase}
                  from={view.phasesFrom}
                />
              ))}
            </ol>
          )}
        </div>
      )}
      <dl className="run-progress-recipes">
        <Tip
          text={
            plan
              ? `This grow plan sets the targets of each zone for each day. ${status?.sentence ?? ""}`
              : "No grow plan is saved for this room. The room uses its own targets."
          }
        >
          <div tabIndex={0} data-run-recipe="plan">
            <dt>Grow plan</dt>
            <dd>
              {plan ? plan.name?.trim() || "Unnamed plan" : "None"}
              {plan && status && status.label !== "Active" && <small> · {status.label}</small>}
            </dd>
          </div>
        </Tip>
        <Tip
          text={
            stage
              ? `The controller reports this stage of the flower${stage.day !== null ? `, flower day ${stage.day}` : ""}.`
              : "The phase of the grow plan for today."
          }
        >
          <div tabIndex={0} data-run-recipe="stage">
            <dt>Stage</dt>
            <dd>
              {stageSummary ??
                (stageName ? stageName.charAt(0).toUpperCase() + stageName.slice(1) : "–")}
            </dd>
          </div>
        </Tip>
        <Tip
          text={
            feed
              ? `The batch tank mixes this feed recipe today. ${SOURCE[feed.source] ?? ""}`
              : "No feed recipe is set. Set the feed schedule in Equipment, Feed and dosing."
          }
        >
          <div tabIndex={0} data-run-recipe="feed">
            <dt>Feed</dt>
            <dd>
              {feed ? feed.recipe : "None"}
              {feed?.week != null && (
                <small>
                  {" "}
                  · week {feed.week}
                  {feed.weeks ? ` of ${feed.weeks}` : ""}
                </small>
              )}
              {feed?.ec != null && <small> · EC {feed.ec} mS/cm</small>}
            </dd>
          </div>
        </Tip>
      </dl>
    </section>
  );
}

/** One phase under the bar, as wide as its days: its label, a short one on a narrow screen, and
 * none on a phase too narrow to hold one (the tooltip still names it). */
function PhaseLabel({
  phase,
  index,
  total,
  current,
  from,
}: {
  phase: RunPhase;
  index: number;
  total: number;
  current: boolean;
  from: "plan" | "stage" | null;
}) {
  const first = Math.min(phase.first, total);
  const last = Math.min(phase.last, total);
  const days = last - first + 1;
  return (
    <Tip
      text={`Phase ${index + 1}, days ${first} to ${last}: ${phase.label}. ${from === "plan" ? "The grow plan sets this phase." : "The stage arc of the controller sets this phase."}`}
    >
      <li
        tabIndex={0}
        aria-current={current ? "step" : undefined}
        data-narrow={days / total < 0.09 || undefined}
        style={{ left: `${((first - 1) / total) * 100}%`, width: `${(days / total) * 100}%` }}
      >
        <span className="run-phase-full">{phase.label}</span>
        <span className="run-phase-short" aria-hidden="true">
          {phase.short}
        </span>
      </li>
    </Tip>
  );
}
