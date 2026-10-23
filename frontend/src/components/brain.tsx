import { CanonicalControls } from "@/components/canonical-controls";
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Heading, time as clock, type Page } from "@/components/dashboard";
import { UiTip } from "@/components/info-tip";
import { Meter } from "@/components/mini-visuals";
import {
  AI_POWERS,
  BRAIN_DEMO_STATES,
  BRAIN_JUDGES,
  confidenceWords,
  judgeCount,
  judgeMatrix,
  judgeTitle,
  keyWords,
  listWords,
  modeWords,
  modelKey,
  money,
  outcomes,
  outcomesFromLog,
  parsePowers,
  providerWords,
  setDemoBrain,
  useBrain,
  type AiOutcome,
  type BrainDemoState,
  type BrainPanel,
  type BrainView,
  type JudgeRow,
  undoStale,
} from "@/lib/brain";
import { jevAnswer, jevIds, jevResult, readJev } from "@/lib/jev";
import { openAlerts } from "@/lib/open-alerts";
import { pagedQuery, useParity } from "@/lib/parity-api";
import type { CsEvent, SystemStatus } from "@/lib/parity-types";
import { SETTING_COPY } from "@/lib/ste-copy";
import { clock as wallClock, dayKey, dayLabel, daysBefore } from "@/lib/time";
import type { Controller, Room } from "@/lib/types";
import { offerUndo } from "@/lib/undo";
import "./brain.css";
import "./room-controls.css";
import { BrainInstructions } from "./brain-instructions";

type Navigate = (page: Page, zone?: number) => void;

/** The header's AI chip: the brain's state in a few words. It opens the AI assistant page. */
export function BrainChip({ controller, open }: { controller: Controller; open: () => void }) {
  const { view } = useBrain(controller);
  if (!controller.roomId) return null;
  return (
    <button
      type="button"
      className="brain-chip"
      data-tone={view.tone}
      onClick={open}
      aria-label={`${view.chip}: open the AI assistant`}
    >
      <span className="brain-chip-dot" aria-hidden="true" />
      {view.chip}
    </button>
  );
}

function Status({ view }: { view: BrainView }) {
  return (
    <div className="brain-status" data-tone={view.tone}>
      <strong>{view.headline}</strong>
      <p>{view.body}</p>
      {view.declined && <p>{view.declined}</p>}
    </div>
  );
}

function budgetLine(panel: BrainPanel): string | null {
  if (panel.budgetUsd === null) return null;
  return `${money(panel.spentUsd ?? 0)} of ${money(panel.budgetUsd)} today`;
}

function decisionLine(panel: BrainPanel, names: Map<number, string>): string | null {
  const last = panel.lastDecision;
  if (!last) return null;
  const where = last.zone === null ? "Room" : (names.get(last.zone) ?? `Zone ${last.zone}`);
  const at = last.time === null ? "" : `${clock(last.time)} · `;
  return `${at}${where} · ${judgeTitle(last.judge)}: ${last.answer || "no answer"}`;
}

/** Today's AI assistant card: its state, today's spend in one line, and its last decision in one line. */
export function BrainCard({
  controller,
  navigate,
  showLastDecision = true,
}: {
  controller: Controller;
  navigate: Navigate;
  showLastDecision?: boolean;
}) {
  const { panel, view } = useBrain(controller);
  const names = new Map(controller.room.zones.map((zone) => [zone.id, zone.name]));
  const budget = panel && budgetLine(panel);
  const last = panel && decisionLine(panel, names);
  return (
    <section className="panel brain-card" aria-labelledby="brain-card-title" data-brain-card>
      <div className="panel-heading">
        <h2 id="brain-card-title">AI assistant</h2>
        <Button variant="ghost" size="sm" onClick={() => navigate("today/ai")}>
          Open <ArrowRight size={15} aria-hidden="true" />
        </Button>
      </div>
      <div className="brain-body">
        <Status view={view} />
        {panel?.plan && <p className="brain-line">{panel.plan.headline}</p>}
        {budget && <p className="brain-line">{budget}</p>}
        {showLastDecision && last && <p className="brain-line">Last decision: {last}</p>}
      </div>
    </section>
  );
}

/** Zone detail's AI assistant section: the room's brain state, and its last decision when it was on this zone. */
export function BrainOnZone({
  controller,
  zone,
  navigate,
}: {
  controller: Controller;
  zone: number;
  navigate: Navigate;
}) {
  const { panel, view } = useBrain(controller);
  const last = panel?.lastDecision?.zone === zone ? panel.lastDecision : null;
  return (
    <section className="panel brain-card" aria-labelledby="brain-zone-title" data-brain-zone>
      <div className="panel-heading">
        <div>
          <h2 id="brain-zone-title">AI assistant</h2>
          <p>{view.headline}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => navigate("today/ai")}>
          Open <ArrowRight size={15} aria-hidden="true" />
        </Button>
      </div>
      {last && (
        <div className="brain-body">
          <p className="brain-line">
            {last.time === null ? "" : `${clock(last.time)} · `}
            {judgeTitle(last.judge)}: {last.answer || "no answer"}
            {last.why ? `. ${last.why}` : ""}
          </p>
        </div>
      )}
    </section>
  );
}

/** What the brain may do: each judge the controller built, what it may change, and whether it acts or only
 * advises. Code publishes the lists; this only shows them. */
function MayDo({ panel }: { panel: BrainPanel | null }) {
  const rows = [
    ...(panel?.judgesActing ?? []).map((judge) => [judge, "Acts"] as const),
    ...(panel?.judgesAdvising ?? []).map((judge) => [judge, "Advises"] as const),
  ];
  if (!rows.length) return <p className="brain-line">Nothing while rules run.</p>;
  return (
    <div className="brain-table-wrap">
      <table className="brain-table">
        <thead>
          <tr>
            <th scope="col">Judge</th>
            <th scope="col">May change</th>
            <th scope="col">Acts or advises</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([judge, role]) => (
            <tr key={judge}>
              <th scope="row">{judgeTitle(judge)}</th>
              <td>{BRAIN_JUDGES[judge]?.may ?? ""}</td>
              <td>{role}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What the AI assistant may do in the room: a checkbox per power switch. Home Assistant decides who may switch
 * one; a refused or failed write shows inline and the box stays at the switch's real state. */
function AiPowers({ controller }: { controller: Controller }) {
  const powers = parsePowers(controller.states, controller.room.room.prefix);
  return (
    <section className="panel" data-brain-powers>
      <div className="panel-heading">
        <h2>Permitted AI actions</h2>
        <a href="#/settings/ai">Manage permissions</a>
      </div>
      <ul className="brain-powers">
        {powers.map((power) => (
          <li key={power.key}>
            <strong>{power.label}</strong>
            <span>
              {power.missing ? " · Unavailable" : power.on ? " · Allowed" : " · Disabled"}
            </span>
            <p>{SETTING_COPY[`ai_power_${power.key}`]?.tooltip}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DemoSwitcher({ demo }: { demo: BrainDemoState }) {
  const id = useId();
  return (
    <div className="brain-demo">
      <label htmlFor={id}>Sample AI state</label>
      <UiTip copyKey="demo brain state" />
      <select
        id={id}
        value={demo}
        onChange={(event) => setDemoBrain(event.target.value as BrainDemoState)}
      >
        {BRAIN_DEMO_STATES.map(([key, label]) => (
          <option key={key} value={key}>
            {label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** The AI assistant page: its state, budget, last decision, what it may do and its latest decisions. */
export function BrainPage({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: Navigate;
}) {
  const { panel, view, demo } = useBrain(controller);
  const { room, states } = controller;
  const names = new Map(room.zones.map((zone) => [zone.id, zone.name]));
  const log = readJev(states, room.room.prefix).log;
  const last = panel?.lastDecision ?? null;
  const budget = panel && budgetLine(panel);
  return (
    <div className="brain-page" data-brain-page={panel?.state ?? "none"}>
      <Heading title="AI assistant" />
      {controller.demo && <DemoSwitcher demo={demo} />}
      <section className="panel" aria-labelledby="brain-status-title">
        <div className="panel-heading">
          <h2 id="brain-status-title">Status</h2>
        </div>
        <div className="brain-body">
          <p className="brain-line">
            {providerWords(panel)}
            {panel?.model ? ` · ${panel.model}` : ""} · {modeWords(panel)}
          </p>
          <Status view={view} />
        </div>
      </section>
      {panel?.plan && (
        <section className="panel" aria-labelledby="brain-plan-title" data-brain-plan>
          <div className="panel-heading">
            <h2 id="brain-plan-title">Grow plan</h2>
          </div>
          <div className="brain-body">
            <p className="brain-line">
              <strong>{panel.plan.headline}</strong>
            </p>
            {panel.plan.drifts.map((drift, i) => (
              <div key={`${drift.kind}-${drift.zone ?? "room"}-${i}`} className="brain-line">
                <p>{drift.suggestion || drift.line}</p>
                {drift.why && <p className="muted">{drift.why}</p>}
              </div>
            ))}
          </div>
        </section>
      )}
      {panel && budget && (
        <section className="panel" aria-labelledby="brain-budget-title">
          <div className="panel-heading">
            <h2 id="brain-budget-title">AI budget</h2>
          </div>
          <div className="brain-body">
            <p className="brain-line">
              <strong>{budget}</strong>
            </p>
            <Meter
              value={panel.spentUsd ?? 0}
              max={panel.budgetUsd || 1}
              tone={panel.budgetLeftUsd === 0 ? "high" : "normal"}
              label={budget}
            />
            {panel.resetsAt !== null && (
              <p className="brain-line">Resets at lights-on {clock(panel.resetsAt)}</p>
            )}
            {panel.projectedUsd !== null && (
              <p className="brain-line">At today's pace about {money(panel.projectedUsd)} a day</p>
            )}
            {(panel.calls !== null || panel.cacheHitRatio !== null) && (
              <details className="brain-details">
                <summary>Details</summary>
                <p>
                  {panel.calls === null ? "" : `${panel.calls} questions today`}
                  {panel.cacheHitRatio === null
                    ? ""
                    : ` · ${Math.round(panel.cacheHitRatio * 100)} % read from the cache`}
                </p>
              </details>
            )}
          </div>
        </section>
      )}
      <section className="panel" aria-labelledby="brain-last-title">
        <div className="panel-heading">
          <h2 id="brain-last-title">Last decision</h2>
        </div>
        <div className="brain-body">
          {last ? (
            <>
              <p className="brain-line">{decisionLine(panel!, names)}</p>
              {last.result === "refused" ? (
                <p className="brain-line">Refused by limits{last.why ? `: ${last.why}` : "."}</p>
              ) : (
                <>
                  {last.result && <p className="brain-line">Outcome: {last.result}</p>}
                  {last.why && <p className="brain-line">{last.why}</p>}
                </>
              )}
              {last.p !== null && (
                <p className="brain-line">{confidenceWords(last.p, last.agreed)}</p>
              )}
            </>
          ) : (
            <p className="brain-line">No decision yet.</p>
          )}
        </div>
      </section>
      <section className="panel" aria-labelledby="brain-may-title">
        <div className="panel-heading">
          <h2 id="brain-may-title">What each judge can do</h2>
        </div>
        <div className="brain-body">
          <MayDo panel={panel} />
        </div>
      </section>
      <AiPowers controller={controller} />
      <section className="panel" aria-labelledby="brain-list-title">
        <div className="panel-heading">
          <h2 id="brain-list-title">Decisions</h2>
          <Button variant="ghost" size="sm" onClick={() => navigate("history/explorer")}>
            History <ArrowRight size={15} aria-hidden="true" />
          </Button>
        </div>
        <div className="brain-body">
          {log?.entries.length ? (
            <ol className="brain-list">
              {log.entries.slice(0, 20).map((entry) => (
                <li key={entry.key}>
                  <span>{entry.time === null ? "" : clock(entry.time)}</span>
                  <span>
                    {entry.zone === null ? "Room" : (names.get(entry.zone) ?? `Zone ${entry.zone}`)}
                  </span>
                  <span>
                    <strong>{entry.title}</strong>: {jevAnswer(entry)}
                  </span>
                  <span>{jevResult(entry).label}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="brain-line">No decisions recorded.</p>
          )}
        </div>
      </section>
    </div>
  );
}

const WHERE = {
  addon: [
    "Open the controller app in Home Assistant (Settings › Apps) and its Configuration tab.",
    "Paste the key into Anthropic API key (a password field).",
    "Set AI assistant (brain_provider) to claude_haiku. With the default, auto, a new install uses the rules.",
    "Save the configuration. Then restart the app.",
  ],
  docker: [
    "Put the key alone in a file next to docker-compose.yml, for example anthropic_key.txt. Never in the compose file or .env: docker inspect shows environment values.",
    "Add that file as a Docker secret, and set F2_OPT_ANTHROPIC_API_KEY_FILE=/run/secrets/anthropic_key and F2_OPT_BRAIN_PROVIDER=claude_haiku.",
    "Run docker compose up -d.",
  ],
} as const;

/** Where the key goes, for the app and for Docker. The dashboard never shows, takes or stores it. */
function WhereTheKeyGoes() {
  const [tab, setTab] = useState<keyof typeof WHERE>("addon");
  const id = useId();
  const tabs = [
    ["addon", "Home Assistant app"],
    ["docker", "Docker"],
  ] as const;
  return (
    <div className="brain-where">
      <div role="tablist" aria-label="Where to put the key">
        {tabs.map(([key, label]) => (
          <button
            type="button"
            role="tab"
            key={key}
            id={`${id}-${key}`}
            aria-selected={tab === key}
            aria-controls={`${id}-panel`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${tab}`}>
        <ol>
          {WHERE[tab].map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>
    </div>
  );
}

const AI_KINDS = ["ai.judgement", "ai.outcome"];
const POWER_FEATURES = AI_POWERS.map((power) => `ai_power_${power.key}`);
const TAG = { act: "Can act", alerts: "Alerts", advice: "Advice" } as const;

/** Every judge with one switch per room. A switch writes at once and offers Undo; a judge without a
 * switch shows whether the controller asks it, read only. */
export function JudgesCard({ controller }: { controller: Controller }) {
  const { rooms, timeZone } = controller;
  const rows = judgeMatrix(controller.states, rooms);
  const count = judgeCount(rows);
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const latest = useRef(controller);
  latest.current = controller;
  const locked =
    controller.admin === false
      ? "Only a Home Assistant administrator can change these switches."
      : !["live", "demo"].includes(controller.connection)
        ? "Connect to Home Assistant to change these switches."
        : null;
  const id = useId();
  // Why a room's cell has no switch, said once below the table; "Not asked" has its own line.
  const why = (note: string | undefined, room: Room) =>
    note === "stacking off"
      ? `EC stacking is off in ${room.name}, so this judge never asks there.`
      : note === "No switch"
        ? `This integration has no switch for it in ${room.name}.`
        : note === "Not reported"
          ? `${room.name} does not report the judges it asks.`
          : null;
  const reasons = [
    ...new Set(rows.flatMap((row) => rooms.map((room) => why(row.perRoom[room.id].note, room)))),
  ].filter((reason): reason is string => reason !== null);
  const reasonId = (reason: string) => `${id}-why-${reasons.indexOf(reason)}`;
  const write = async (entityId: string, on: boolean) => {
    const result = await latest.current.write([{ entityId, value: on }]);
    return result.applied.includes(entityId)
      ? null
      : (result.failed[0]?.reason ?? "The controller did not confirm the change.");
  };
  const flip = async (row: JudgeRow, room: Room, entityId: string, on: boolean) => {
    // One switch turns both judges on it, but only the ones this room asks.
    const partner = rows.find((other) => other.name === row.shares)?.perRoom[room.id];
    const what = row.shares && partner?.note !== "Not asked" ? `${row.name} and ${row.shares}` : row.name;
    const word = (value: boolean) => (value ? "on" : "off");
    const before = latest.current.states[entityId]?.last_updated;
    setBusy(entityId);
    setFailed(null);
    const refused = await write(entityId, on).finally(() => setBusy(null));
    if (refused) {
      setFailed(`${what} in ${room.name} was not turned ${word(on)}: ${refused}`);
      return;
    }
    offerUndo({
      message: `${what} ${word(on)} in ${room.name}. Written and read back ${wallClock(Date.now(), timeZone)}.`,
      undo: async () => {
        // Put back only what this change left: a newer change since then is someone else's.
        if (undoStale(latest.current.states[entityId], on, before))
          throw new Error(`${what} in ${room.name} changed since. Nothing was put back.`);
        setBusy(entityId);
        const back = await write(entityId, !on).finally(() => setBusy(null));
        if (back) throw new Error(`${what} in ${room.name} was not put back: ${back}`);
        toast(
          `${what} ${word(!on)} again in ${room.name}. Written and read back ${wallClock(Date.now(), timeZone)}.`,
        );
      },
    });
  };
  const roomNames = listWords(rooms.map((room) => room.name));
  const notAsked = rows.some((row) => Object.values(row.perRoom).some((cell) => cell.note === "Not asked"));
  return (
    <section className="panel ai-card ai-judges" aria-labelledby="ai-judges-title" data-ai-judges>
      <div className="ai-card-head">
        <h2 id="ai-judges-title">Judges</h2>
        <span>
          {count.on} of {count.of} on{roomNames ? ` · ${roomNames}` : ""}
        </span>
      </div>
      <p className="brain-line">
        Each judge is one question about one decision. The controller keeps the pump, valves and every
        safety limit; a judge can only move inside them.
      </p>
      {locked && (
        <p className="brain-line" id={`${id}-locked`}>
          {locked}
        </p>
      )}
      {failed && (
        <p className="ai-failed" role="alert">
          {failed}
        </p>
      )}
      <div className="ai-judges-wrap">
        <table className="ai-judges-table">
          <thead>
            <tr>
              <th scope="col">Judge</th>
              <th scope="col">Can it act?</th>
              {rooms.map((room) => (
                <th scope="col" key={room.id} className="ai-room-col">
                  {room.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} data-judge={row.id}>
                <th scope="row">
                  <div className="ai-judge-name">
                    <strong>
                      {row.name}
                      {row.shares && <small> · one switch with {row.shares}</small>}
                    </strong>
                    <span title={row.blurb}>{row.blurb}</span>
                    {row.hint && (
                      <span className="brain-line" id={`${id}-hint-${row.id}`}>
                        {row.hint}
                      </span>
                    )}
                  </div>
                </th>
                <td>
                  <span className="ai-tag" data-power={row.power}>
                    {TAG[row.power]}
                  </span>
                </td>
                {rooms.map((room) => {
                  const cell = row.perRoom[room.id];
                  const label = `${row.name} in ${room.name}`;
                  let body: ReactNode;
                  if (cell.entityId && cell.note === undefined)
                    body = (
                      <button
                        type="button"
                        role="switch"
                        className="switch"
                        aria-checked={cell.on}
                        aria-label={label}
                        aria-describedby={
                          [locked && `${id}-locked`, row.hint && `${id}-hint-${row.id}`]
                            .filter(Boolean)
                            .join(" ") || undefined
                        }
                        disabled={locked !== null || busy === cell.entityId}
                        onClick={() => void flip(row, room, cell.entityId!, !cell.on)}
                      >
                        <span className="switch-thumb" aria-hidden="true" />
                      </button>
                    );
                  else if (cell.note === "Set in the controller app")
                    body = (
                      <span
                        className="switch ai-fixed"
                        data-on={cell.on}
                        role="img"
                        aria-label={`${label}: ${cell.on ? "asked" : "not asked"}. Set in the controller app.`}
                        title="Set in the controller app's options (ai_judges)"
                      >
                        <span className="switch-thumb" aria-hidden="true" />
                      </span>
                    );
                  else {
                    const reason = why(cell.note, room);
                    body = (
                      <span
                        className="ai-note"
                        aria-describedby={reason ? reasonId(reason) : `${id}-not-asked`}
                      >
                        {cell.note}
                      </span>
                    );
                  }
                  return (
                    <td key={room.id} className="ai-room-col">
                      {body}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {reasons.map((reason) => (
        <p className="brain-line" key={reason} id={reasonId(reason)}>
          {reason}
        </p>
      ))}
      {notAsked && (
        <p className="brain-line" id={`${id}-not-asked`} data-ai-not-asked>
          Not asked: the controller app's judge list (ai_judges) leaves it out, so its switch does nothing
          there. Change the list in the controller app's options.
        </p>
      )}
    </section>
  );
}

/** The day's calls and spend: system_status_get.ai on 3.18, else the room's brain sensor. */
function useCalls(controller: Controller) {
  const status = useParity<SystemStatus>(controller, "system_status_get", {}, []);
  const ai = status.state === "ready" ? status.data?.ai : null;
  const attrs = controller.states[jevIds(controller.room.room.prefix).room]?.attributes ?? {};
  const num = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : null);
  const calls = ai ? num(ai.calls_today) : num(attrs.calls_today);
  const cap = ai ? num(ai.daily_budget) : num(attrs.daily_budget);
  const pct = ai ? num(ai.pct_used) : calls !== null && cap ? (calls / cap) * 100 : null;
  return { calls, cap, pct };
}

function BudgetCard({ controller, panel }: { controller: Controller; panel: BrainPanel | null }) {
  const { timeZone } = controller;
  const { calls, cap, pct } = useCalls(controller);
  const warning = openAlerts(controller).find((alert) => alert.code === "CS-706");
  const spent = panel?.spentUsd ?? null;
  const budget = panel?.budgetUsd ?? null;
  return (
    <section className="panel ai-card" aria-labelledby="ai-budget-title" data-ai-budget>
      <div className="ai-card-head">
        <h2 id="ai-budget-title">Budget today</h2>
        <strong className="ai-spent">{spent === null ? "—" : money(spent)}</strong>
        <span>of {budget === null ? "—" : money(budget)}</span>
      </div>
      {pct !== null && (
        <div
          className="ai-bar"
          role="meter"
          aria-label="AI calls used today"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.min(100, pct)}
          aria-valuetext={`${pct.toFixed(1)} %`}
          data-warn={warning !== undefined}
        >
          <span style={{ width: `${Math.min(100, pct)}%` }} />
        </div>
      )}
      <div className="ai-bar-legend">
        <span>
          {calls === null ? "Calls not reported" : `${calls}${cap === null ? "" : ` of ${cap}`} calls`}
          {pct === null ? "" : ` (${pct.toFixed(1)} %)`}
          {panel?.resetsAt == null ? "" : ` · resets at lights-on ${wallClock(panel.resetsAt, timeZone)}`}
        </span>
        <span>
          CS-706 warns at the share set in the controller app (80 % unless changed) · rules take over at 100 %
        </span>
      </div>
      {warning && (
        <p className="ai-warning" data-code="CS-706">
          <b>CS-706</b> raised{warning.at === null ? "" : ` ${wallClock(warning.at, timeZone)}`}:{" "}
          {warning.title}. <a href="#/help?code=CS-706">What to do →</a>
        </p>
      )}
      <p className="ai-budget-set">
        <span>Daily budget US$</span>
        <strong>{budget === null ? "—" : budget.toFixed(2)}</strong>
        <span className="brain-line">
          Set in the controller app's options (anthropic_daily_budget_usd). This page cannot change it.
        </span>
      </p>
    </section>
  );
}

const MODELS = [
  ["claude-haiku-5-5", "Haiku 5.5"],
  ["claude-sonnet-5-5", "Sonnet 5.5"],
  ["claude-opus-5-5", "Opus 5.5"],
] as const;

/** Dry run and the model, as the controller reports them (calls and spend: Budget today). Both are
 * controller options: shown, not switched here. */
export function ModelCard({ panel }: { panel: BrainPanel | null }) {
  const model = panel?.model ?? null;
  const current = model ? modelKey(model) : null;
  const dry = panel?.mode === "dry_run";
  const legacy = panel?.state === "legacy";
  return (
    <section className="panel ai-card" aria-labelledby="ai-model-title" data-ai-model>
      <div className="ai-dry">
        <span className="switch ai-fixed" data-on={dry} hidden={legacy} aria-hidden="true">
          <span className="switch-thumb" />
        </span>
        <span>
          <strong id="ai-model-title">
            {legacy ? "First AI route" : panel?.mode ? `Dry run ${dry ? "on" : "off"}` : "Not running"}
          </strong>
          <span className="brain-line">
            {legacy
              ? "An older controller app runs it and does not report dry run or the model. Update the controller app."
              : !panel?.mode
                ? "The rules decide every zone."
                : dry
                  ? "The judges answer and the ledger shows what it would do. Nothing changes in the rooms."
                  : "The assistant acts inside its limits."}
          </span>
        </span>
      </div>
      <div className="ai-models" role="group" aria-label="Model">
        {MODELS.map(([key, name]) => (
          <span key={key} data-current={key === current} aria-current={key === current ? "true" : undefined}>
            {name}
          </span>
        ))}
      </div>
      <p className="brain-line">
        {model && !current ? `Model ${model}. ` : ""}
        Dry run and the model are set in the controller app's options.
      </p>
    </section>
  );
}

const VERDICT = {
  worked: "Worked",
  measuring: "Measuring",
  "did not work": "Did not work",
  "not checked": "Not checked",
} as const;

/** The AI assistant's decisions over the last week and what each check found: the Journal on 3.18, each
 * room's decision log on 3.17. */
function OutcomesCard({ controller }: { controller: Controller }) {
  const { rooms, timeZone, states } = controller;
  const [read, setRead] = useState<
    { state: "loading" } | { state: "missing" } | { state: "error"; error: string } | { state: "ready"; events: CsEvent[] }
  >({ state: "loading" });
  const roomsKey = rooms.map((room) => room.id).join(",");
  const latest = useRef(controller);
  latest.current = controller;
  useEffect(() => {
    let live = true;
    const since = new Date(daysBefore(Date.now(), 7, latest.current.timeZone)).toISOString();
    void Promise.all(
      roomsKey
        .split(",")
        .filter(Boolean)
        .map((room_id) => pagedQuery(latest.current, { room_id, since, kinds: AI_KINDS }, 500)),
    ).then((pages) => {
      if (!live) return;
      const failed = pages.find((page) => page.kind !== "ok");
      if (failed?.kind === "missing") setRead({ state: "missing" });
      else if (failed?.kind === "error") setRead({ state: "error", error: failed.message });
      else setRead({ state: "ready", events: pages.flatMap((page) => (page.kind === "ok" ? page.data.events : [])) });
    });
    return () => {
      live = false;
    };
  }, [roomsKey]);
  const since = daysBefore(Date.now(), 7, timeZone);
  const notCheckedId = useId();
  const liveEvents = controller.recentEvents.filter((event) => AI_KINDS.includes(event.kind));
  const rows =
    read.state === "ready"
      ? outcomes([...new Map([...read.events, ...liveEvents].map((event) => [event.id, event])).values()]).filter(
          (row) => row.at >= since,
        )
      : read.state === "missing"
        ? rooms
            .flatMap((room) => outcomesFromLog(readJev(states, room.prefix).log?.entries ?? [], room.id, since))
            .sort((a, b) => b.at - a.at)
        : [];
  const shown = rows.slice(0, 6);
  const today = dayKey(Date.now(), timeZone);
  const where = (row: AiOutcome) => {
    const room = rooms.find((r) => r.id === row.roomId);
    const zone =
      row.zone === null
        ? ""
        : row.roomId === controller.roomId
          ? (controller.room.zones.find((z) => z.id === row.zone)?.name ?? `Zone ${row.zone}`)
          : `Zone ${row.zone}`;
    return [room?.name ?? row.roomId, zone].filter(Boolean).join(" ");
  };
  return (
    <section className="panel ai-card ai-ledger" aria-labelledby="ai-ledger-title" data-ai-ledger>
      <div className="ai-card-head">
        <h2 id="ai-ledger-title">What it did, and what happened</h2>
        <a href="#/history/changes?actor=ai">Full ledger in History →</a>
      </div>
      {read.state === "loading" ? (
        <p className="brain-line">Reading the ledger…</p>
      ) : read.state === "error" ? (
        <p className="ai-failed">The ledger could not be read: {read.error}</p>
      ) : !rows.length ? (
        <p className="brain-line">Nothing in the last 7 days.</p>
      ) : (
        <ol className="ai-outcomes">
          {shown.map((row) => (
            <li key={row.id} data-verdict={row.verdict}>
              <span className="ai-when">
                <b>{wallClock(row.at, timeZone)}</b>
                {dayKey(row.at, timeZone) === today ? "today" : dayLabel(row.at, timeZone)}
              </span>
              <span className="ai-what">
                <span>
                  <b>{where(row)}</b>
                  <span className="brain-line"> · {judgeTitle(row.judge)}</span>
                </span>
                <span>{row.text}</span>
                {row.result && <span className="brain-line">→ {row.result}</span>}
              </span>
              <span className="ai-verdict">
                {row.verdict === "not checked" ? (
                  <span className="brain-line" aria-describedby={notCheckedId}>
                    {VERDICT[row.verdict]}
                  </span>
                ) : (
                  <span className="ai-pill" data-verdict={row.verdict}>
                    {VERDICT[row.verdict]}
                  </span>
                )}
                {row.band && row.value !== null && <BandTick band={row.band} value={row.value} />}
              </span>
            </li>
          ))}
        </ol>
      )}
      {shown.some((row) => row.verdict === "not checked") && (
        <p className="brain-line" id={notCheckedId}>
          Not checked: the controller does not check this kind of decision later.
        </p>
      )}
    </section>
  );
}

/** The check's target band and where the value landed, both as the controller sent them. */
function BandTick({ band, value }: { band: [number, number]; value: number }) {
  const span = band[1] - band[0] || 1;
  const min = Math.min(band[0] - span, value);
  const max = Math.max(band[1] + span, value);
  const at = (v: number) => `${((v - min) / (max - min)) * 100}%`;
  return (
    <span className="ai-band" aria-hidden="true">
      <span style={{ left: at(band[0]), width: `${(span / (max - min)) * 100}%` }} />
      <i style={{ left: at(value) }} />
    </span>
  );
}

/** Settings › AI assistant: the judges with a switch per room, today's budget, dry run and model, what it
 * did and what happened, and below them the room's instructions and permissions. Provider credentials stay
 * in controller options. */
export function AiSettings({
  controller,
  onDirtyChange,
}: {
  controller: Controller;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [instructionsDirty, setInstructionsDirty] = useState(false);
  const [permissionsDirty, setPermissionsDirty] = useState(false);
  useLayoutEffect(() => {
    onDirtyChange?.(instructionsDirty || permissionsDirty);
    return () => onDirtyChange?.(false);
  }, [instructionsDirty, permissionsDirty, onDirtyChange]);
  const { panel } = useBrain(controller);
  const row = (title: string, body: ReactNode, detail?: string) => (
    <section className="panel settings-section">
      <div className="settings-label">
        <h2>{title}</h2>
        {detail && <p>{detail}</p>}
      </div>
      <div className="brain-body">{body}</div>
    </section>
  );
  return (
    <>
      <Heading title="AI assistant" />
      <div className="ai-settings" data-ai-settings>
        <div className="ai-grid">
          <JudgesCard controller={controller} />
          <div className="ai-side">
            <BudgetCard controller={controller} panel={panel} />
            <ModelCard panel={panel} />
            <OutcomesCard controller={controller} />
          </div>
        </div>
        <section className="ai-instructions" aria-labelledby="ai-instructions-title">
          <h2 id="ai-instructions-title">Instructions and permissions</h2>
          <div className="settings-stack brain-settings">
            <BrainInstructions controller={controller} onDirtyChange={setInstructionsDirty} />
            <CanonicalControls
              controller={controller}
              owner="ai"
              hide={POWER_FEATURES}
              onDirtyChange={setPermissionsDirty}
            />
            {row("Provider", <p className="brain-line">{providerWords(panel)}</p>)}
            {row(
              "Anthropic key",
              <>
                <p className="brain-line" data-brain-key>
                  {keyWords(panel)}
                </p>
                <WhereTheKeyGoes />
              </>,
              "The key stays in the controller. This page only shows whether one is saved.",
            )}
            {row(
              "Privacy",
              <p className="brain-line">
                What is sent: each zone's readings and settings, the day's stage, and the room and zone
                names you typed, plus any saved room context and house notes. Automatically collected
                evidence excludes entity ids and credentials. Keep credentials and personal information
                out of notes; they are sent as entered to the AI provider.
              </p>,
            )}
          </div>
        </section>
      </div>
    </>
  );
}
