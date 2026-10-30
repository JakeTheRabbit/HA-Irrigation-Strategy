import { useEffect, useState, type ReactElement } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { planState } from "@/lib/grow-plan";
import type { StrategyDocument } from "@/lib/operator-types";
import { feedToday } from "@/lib/run-progress";
import type { Controller } from "@/lib/types";
import "./run-progress.css";

const SOURCE: Record<string, string> = {
  schedule: "The feed schedule selects this recipe for this week.",
  held: "A person selected this recipe. It stays until the next week of the feed schedule.",
  hand: "A person selected this recipe. No feed schedule runs.",
  batch: "The batch tank uses its own recipe. No feed schedule runs.",
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

/** The room page's grow plan and feed recipe today. The run's day, stage and harvest are the page
 * header's; the run records live in History › Grows and the plan's phases in Irrigation › Grow plan. */
export function PlanAndFeed({ controller }: { controller: Controller }) {
  const { roomId, operator, room, states } = controller;
  const [loaded, setLoaded] = useState<{ roomId: string; plan: StrategyDocument | null } | null>(
    null,
  );
  useEffect(() => {
    if (!roomId) return;
    let live = true;
    // An older integration has no grow plans: the plan reads None.
    operator<StrategyDocument>("strategy_get")
      .catch(() => null)
      .then((plan) => {
        if (live) setLoaded({ roomId, plan });
      });
    return () => {
      live = false;
    };
  }, [roomId, operator]);
  if (!loaded || loaded.roomId !== roomId) return null;
  const plan = loaded.plan?.plan;
  const status = loaded.plan ? planState(loaded.plan) : null;
  const feed = feedToday(states[`sensor.crop_steering_${room.room.prefix}dosing_config`]);
  return (
    <section className="panel run-progress" aria-label="Grow plan and feed" data-plan-feed>
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
