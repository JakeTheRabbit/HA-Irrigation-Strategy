import { useId, useState, type ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Heading, time as clock, type Page } from "@/components/dashboard";
import { Meter } from "@/components/mini-visuals";
import {
  BRAIN_DEMO_STATES,
  BRAIN_JUDGES,
  confidenceWords,
  judgeTitle,
  keyWords,
  modeWords,
  money,
  providerWords,
  setDemoBrain,
  useBrain,
  type BrainDemoState,
  type BrainPanel,
  type BrainView,
} from "@/lib/brain";
import { jevAnswer, jevResult, readJev } from "@/lib/jev";
import type { Controller } from "@/lib/types";
import "./brain.css";

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
export function BrainCard({ controller, navigate }: { controller: Controller; navigate: Navigate }) {
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
        {budget && <p className="brain-line">{budget}</p>}
        {last && <p className="brain-line">Last decision: {last}</p>}
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

function DemoSwitcher({ demo }: { demo: BrainDemoState }) {
  const id = useId();
  return (
    <div className="brain-demo">
      <label htmlFor={id}>Demo brain state</label>
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
export function BrainPage({ controller, navigate }: { controller: Controller; navigate: Navigate }) {
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
      {panel && budget && (
        <section className="panel" aria-labelledby="brain-budget-title">
          <div className="panel-heading">
            <h2 id="brain-budget-title">Budget</h2>
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
          <h2 id="brain-may-title">What it may do</h2>
        </div>
        <div className="brain-body">
          <MayDo panel={panel} />
        </div>
      </section>
      <section className="panel" aria-labelledby="brain-list-title">
        <div className="panel-heading">
          <h2 id="brain-list-title">Decisions</h2>
          <Button variant="ghost" size="sm" onClick={() => navigate("history/timeline")}>
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
    "Set Brain provider to claude_haiku. The default, auto, stays on rules for a new install.",
    "Save, then restart the app.",
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

/** Settings › AI assistant: read-only. Provider, key, model, budget and mode are set in the controller's own
 * options, the one place they live. */
export function AiSettings({ controller }: { controller: Controller }) {
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
      <div className="settings-stack brain-settings">
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
        {row("Model", <p className="brain-line">{panel?.model ?? "None while rules run"}</p>)}
        {row(
          "Daily budget",
          <p className="brain-line">
            {panel?.budgetUsd === null || panel?.budgetUsd === undefined
              ? "Not reported while rules run"
              : `${money(panel.budgetUsd)} a day, resets at lights-on`}
          </p>,
        )}
        {row("Mode", <p className="brain-line">{modeWords(panel)}</p>)}
        {row("What it may do", <MayDo panel={panel} />)}
        {row(
          "Privacy",
          <p className="brain-line">
            What is sent: each zone's readings and settings, the day's stage, and the room and zone
            names you typed. What is never sent: your key (it stays in the controller), entity ids,
            Home Assistant tokens or personal data.
          </p>,
        )}
      </div>
    </>
  );
}
