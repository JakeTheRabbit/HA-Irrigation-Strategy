import { useEffect, useId, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  CircleDashed,
  CircleDot,
  CircleStop,
  LoaderCircle,
  SkipForward,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Empty, Heading, number, type Page } from "@/components/dashboard";
import { Pill } from "@/components/mini-visuals";
import { PeristalticPump } from "@/components/peristaltic-pump";
import { StockBottle } from "@/components/stock-bottle";
import { DosingSetup } from "@/components/dosing-setup";
import {
  PUMP_STATES,
  STOCK_STATES,
  batchSteps,
  batchTime,
  blankPump,
  canEdit,
  controllerReach,
  doseDeadline,
  MAX_DOSE_S,
  dosingConfigId,
  dosingError,
  dosingStatusId,
  hardwareLabel,
  leftWords,
  pumpStock,
  pumpView,
  readConfig,
  readStatus,
  recipeRows,
  recipeTotals,
  requestStage,
  requestWaiting,
  resultTone,
  resultWords,
  setupDraft,
  stockTanks,
  type DosingAction,
  type DosingConfig,
  type DosingDocument,
  type DosingPump,
  type DosingRequest,
  type DosingRequestResult,
  type PumpStock,
  type PumpView,
  type SetupDraft,
  type StepView,
  type StockTankReading,
} from "@/lib/dosing";
import { tankTelemetry, type TankReading } from "@/lib/tank-telemetry";
import type { Controller } from "@/lib/types";
import { dayWord, errorText } from "@/lib/utils";
import "./dosing.css";

const mL = (value: number) =>
  value.toLocaleString(undefined, { maximumFractionDigits: value < 100 ? 1 : 0 });
/** A stock tank's level against its capacity: "5.4 L of 20 L". */
const litres = (tank: StockTankReading) =>
  `${tank.level_l.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} L of ${number(tank.capacity_l, 1)} L`;
const bottleLabel = (tank: StockTankReading) =>
  `${tank.name} stock tank: ${litres(tank)}, low mark ${number(tank.low_l, 1)} L`;
const seconds = (value: number) =>
  value < 100 ? `${number(value, 1)} s` : `${number(value / 60, value < 600 ? 1 : 0)} min`;
const when = (iso: string | null, now: number) => {
  const at = Date.parse(iso ?? "");
  if (!Number.isFinite(at)) return "time not reported";
  const time = new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const day = dayWord(at, now);
  return day ? `${day} ${time}` : time;
};
/** A tank reading with its unit, "42%" and a bare pH. */
const reading = (value: TankReading, digits: number) =>
  value.value === null
    ? (value.issue ?? "Unavailable")
    : number(value.value, digits) +
      (value.unit === "%"
        ? "%"
        : value.unit && value.unit.toLowerCase() !== "ph"
          ? ` ${value.unit}`
          : "");

/** Re-renders every `ms` while `active`: a running dose's progress moves between reports. */
function useTicker(active: boolean, ms = 500) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setTick((tick) => tick + 1), ms);
    return () => clearInterval(timer);
  }, [active, ms]);
}

interface RequestReview {
  title: string;
  rows: { label: string; value: string }[];
  note: string;
  confirm: string;
  stop?: boolean;
  data: { action: DosingAction; pump?: string; ml?: number };
}

/** The review before a request: what the controller is asked to do, then `dosing_request`. The page
 * never switches anything itself. */
function RequestDialog({
  controller,
  review,
  onClose,
}: {
  controller: Controller;
  review: RequestReview | null;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sent = useRef(false);
  // Shown while the dialog closes, after `review` is gone.
  const last = useRef<RequestReview | null>(null);
  if (review) last.current = review;
  const shown = review ?? last.current;
  useEffect(() => setError(""), [review]);
  async function send() {
    if (!review) return;
    setBusy(true);
    setError("");
    try {
      const result = await controller.operator<DosingRequestResult>("dosing_request", review.data);
      // The request is the room's now: the page follows it on the configuration sensor.
      if (result.error) setError(dosingError(result.error));
      else {
        sent.current = true;
        onClose();
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={!!review} onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent
        className="review-dialog"
        onCloseAutoFocus={(event) => {
          // The button that opened it may be gone (Make a batch becomes Stop the batch): go on
          // from the line that follows the request instead.
          const line = document.querySelector<HTMLElement>("[data-request-stage]");
          if (!sent.current || !line) return;
          sent.current = false;
          event.preventDefault();
          line.focus({ preventScroll: true });
        }}
      >
        <DialogHeader>
          <DialogTitle>{shown?.title}</DialogTitle>
          <DialogDescription>
            {controller.demo ? "Demo only. " : ""}This asks the controller to act in{" "}
            {controller.room.room.name} only. It takes a request within a few seconds, and drops one
            it could not take within two minutes.
          </DialogDescription>
        </DialogHeader>
        <div className="review-list">
          {shown?.rows.map((row) => (
            <div className="review-row" key={row.label}>
              <strong>{row.label}</strong>
              <span>
                <b>{row.value}</b>
              </span>
            </div>
          ))}
        </div>
        {shown?.note && <p className="notice-inline">{shown.note}</p>}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>
            Back
          </Button>
          <Button
            variant={shown?.stop ? "destructive" : "default"}
            disabled={busy || !["live", "demo"].includes(controller.connection)}
            onClick={() => void send()}
          >
            {busy && <LoaderCircle className="spin" size={16} />}
            {busy ? "Sending…" : shown?.confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The pump's stock tank on its card: the bottle to scale (`largest`: the room's largest linked
 * tank's capacity; a bottle of the same shape holding an eighth as much stands half as tall), the
 * litres left and about how many batches, or doses, that is. */
function CardStock({
  pump,
  stock,
  largest,
}: {
  pump: DosingPump;
  stock: PumpStock | null;
  largest: number;
}) {
  if (!stock?.tank)
    return (
      <p className="dosing-pump-stock dosing-stock-none" data-pump-stock="">
        {stock ? `Stock tank ${stock.id} not found` : "No stock tank linked"}
      </p>
    );
  const { tank } = stock;
  return (
    <div className="dosing-pump-stock" data-pump-stock={tank.id} data-level={stock.state}>
      <StockBottle
        tank={tank}
        state={stock.state}
        scale={largest > 0 ? Math.cbrt(tank.capacity_l / largest) : 1}
        label={bottleLabel(tank)}
      />
      <p className="dosing-stock-lines">
        {tank.name.toLowerCase() !== pump.name.toLowerCase() && (
          <span className="dosing-stock-name">{tank.name}</span>
        )}
        <span className="dosing-stock-litres">{litres(tank)}</span>
        {stock.left && <span className="dosing-stock-left">{leftWords(stock.left)}</span>}
        {stock.state !== "ok" && (
          <span className="dosing-stock-state">{STOCK_STATES[stock.state]}</span>
        )}
      </p>
    </div>
  );
}

function PumpCard({
  view,
  index,
  selected,
  onSelect,
  stock,
  largest,
  now,
}: {
  view: PumpView;
  index: number;
  selected: boolean;
  onSelect: () => void;
  stock: PumpStock | null;
  largest: number;
  now: number;
}) {
  const { pump, progress, last } = view;
  const pill = PUMP_STATES[view.state];
  const hardware = hardwareLabel(pump);
  return (
    <article
      className="dosing-pump"
      data-dosing-pump={pump.id}
      data-state={view.state}
      data-selected={selected || undefined}
      data-hue={index % 8}
    >
      <div className="dosing-pump-art">
        <PeristalticPump state={view.state} label={`${pump.name}: ${pill.label.toLowerCase()}`} />
      </div>
      <span className="dosing-strip" aria-hidden="true" />
      <div className="dosing-pump-head">
        <h3>
          <button
            type="button"
            className="dosing-pump-select"
            aria-pressed={selected}
            onClick={onSelect}
          >
            {pump.name}
          </button>
        </h3>
        <Pill tone={pill.tone} dot={view.state === "dosing"} data-pump-state={view.state}>
          {pill.label}
        </Pill>
      </div>
      <code className="dosing-mono dosing-hardware" title={hardware}>
        {hardware}
      </code>
      <p className="dosing-figure">
        {progress ? (
          <>
            <span className="dosing-mono dosing-big">{mL(progress.ml)}</span>
            <span className="dosing-of"> / {mL(progress.target)} mL</span>
          </>
        ) : last ? (
          <>
            <span className="dosing-mono dosing-big">{mL(last.ml)}</span>
            <span className="dosing-of"> mL</span>
          </>
        ) : (
          <span className="dosing-mono dosing-big dosing-none">—</span>
        )}
      </p>
      <p className="dosing-caption">
        {progress
          ? `dosing · ${seconds(progress.elapsed)} of ${seconds(progress.expected)}`
          : view.state === "dosing"
            ? "dosing"
            : last
              ? `last dose · ${when(last.at, now)}${last.result && last.result !== "finished" ? ` · ${last.result}` : ""}`
              : "no dose yet"}
      </p>
      {progress ? (
        <div
          className="dosing-bar"
          role="progressbar"
          aria-label={`${pump.name} dose`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress.share * 100)}
        >
          <span style={{ width: `${progress.share * 100}%` }} />
        </div>
      ) : (
        <div className="dosing-bar" aria-hidden="true">
          <span style={{ width: 0 }} />
        </div>
      )}
      <dl className="dosing-pump-facts">
        <div>
          <dt>Flow</dt>
          <dd>{view.flow === null ? "—" : `${number(view.flow, 2)} mL/s`}</dd>
        </div>
      </dl>
      <CardStock pump={pump} stock={stock} largest={largest} />
      {view.reason && view.state !== "idle" && <p className="dosing-reason">{view.reason}</p>}
    </article>
  );
}

/** Every linked stock tank, in pump order, as a labelled bottle with its low mark. */
function StockStrip({
  items,
  navigate,
  headingId,
}: {
  items: { pump: DosingPump; stock: PumpStock; tank: StockTankReading; index: number }[];
  navigate: (page: Page) => void;
  headingId: string;
}) {
  return (
    <section className="panel dosing-stock" aria-labelledby={headingId} data-stock-strip>
      <div className="panel-heading">
        <div>
          <h2 id={headingId}>Stock</h2>
          <p>Each pump’s stock tank, drawn down by what the pump doses</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => navigate("equipment/stock")}>
          Stock tanks <ArrowRight size={15} aria-hidden="true" />
        </Button>
      </div>
      <ul className="dosing-stock-list">
        {items.map(({ pump, stock, tank, index }) => (
          <li
            key={tank.id}
            className="dosing-stock-item"
            data-stock-gauge={tank.id}
            data-level={stock.state}
            data-hue={index % 8}
          >
            <StockBottle tank={tank} state={stock.state} label={bottleLabel(tank)} />
            <p className="dosing-stock-lines">
              <strong>{tank.name}</strong>
              {tank.name.toLowerCase() !== pump.name.toLowerCase() && (
                <span className="dosing-stock-name">for {pump.name}</span>
              )}
              <span className="dosing-stock-percent dosing-mono">
                {number(Math.min(100, (tank.level_l / tank.capacity_l) * 100), 0)}%
              </span>
              <span className="dosing-stock-litres">{litres(tank)}</span>
              {stock.left && <span className="dosing-stock-left">{leftWords(stock.left)}</span>}
              {stock.state !== "ok" && (
                <span className="dosing-stock-state">{STOCK_STATES[stock.state]}</span>
              )}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

const STEP_WORDS: Record<StepView["state"], string> = {
  done: "Done",
  running: "Now",
  skipped: "Passed by",
  failed: "Stopped",
  waiting: "To come",
};
function StepMark({ state }: { state: StepView["state"] }) {
  if (state === "done") return <Check size={14} />;
  if (state === "running") return <CircleDot size={14} />;
  if (state === "skipped") return <SkipForward size={13} />;
  if (state === "failed") return <X size={14} />;
  return <CircleDashed size={14} />;
}

export function Dosing({
  controller,
  navigate,
  onDirtyChange,
}: {
  controller: Controller;
  navigate: (page: Page) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { room, states } = controller;
  const prefix = room.room.prefix;
  const formId = useId();
  const [doc, setDoc] = useState<DosingDocument | null>(null);
  const [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [amount, setAmount] = useState("25");
  const [review, setReview] = useState<RequestReview | null>(null);
  const [draft, setDraft] = useState<SetupDraft | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const [reads, setReads] = useState(0);
  const connected = ["live", "demo"].includes(controller.connection);
  useEffect(() => {
    setDoc(null);
    setLoadError("");
  }, [controller.roomId, controller.connection]);
  useEffect(() => {
    let current = true;
    if (controller.connection === "connecting") return;
    controller
      .operator<DosingDocument>("dosing_get")
      .then((result) => {
        if (!current) return;
        setDoc(result);
        setLoadError(result.error ?? "");
      })
      .catch((err) => current && setLoadError(errorText(err)));
    return () => {
      current = false;
    };
  }, [controller.roomId, controller.connection, reads]);
  const live = readConfig(states[dosingConfigId(prefix)]);
  // Saved elsewhere: read the setup again, so an edit is saved against what the room runs now.
  useEffect(() => {
    if (doc?.config && live && live.revision !== doc.config.revision)
      setReads((count) => count + 1);
  }, [live?.revision, doc?.config?.revision]);

  const config: DosingConfig | null = live ?? doc?.config ?? null;
  const status = readStatus(states[dosingStatusId(prefix)]);
  const now = Date.now();
  const reach = controllerReach(states, prefix, status, now);
  const views = (config?.pumps ?? []).map((pump) => pumpView(pump, status, reach, states, now));
  const running = views.some((view) => view.state === "dosing");
  const batchRunning = !!status && status.batch.step !== "idle";
  useTicker(running || batchRunning);
  const stage = requestStage(config, status, now);
  const waiting = requestWaiting(stage);
  const admin = canEdit(doc, controller.admin);
  const may = connected && admin;
  const canAct = may && reach.live && !waiting;
  const view = views.find((item) => item.pump.id === selected) ?? views[0] ?? null;
  const name = (id: string | null) =>
    config?.pumps.find((pump) => pump.id === id)?.name ?? id ?? "a pump";
  const rows = config ? recipeRows(config, states) : [];
  // Each pump's stock tank, by its stock_tank: the cards draw theirs to scale against the largest.
  const tanks = stockTanks(states, prefix);
  const stocks = views.map((item) => pumpStock(item.pump, tanks, rows, item.last));
  const linked = views.flatMap((item, index) => {
    const stock = stocks[index];
    return stock?.tank ? [{ pump: item.pump, stock, tank: stock.tank, index }] : [];
  });
  const largest = Math.max(0, ...linked.map((item) => item.tank.capacity_l));

  const loading = !config && !loadError;
  /** Opens the setup; `edit` starts an administrator's draft, with a first pump when there is none. */
  const openSetup = (edit: boolean) => {
    setSetupOpen(true);
    if (edit && doc && !draft && admin) {
      const next = setupDraft(doc.config);
      if (!next.pumps.length) next.pumps.push(blankPump("new-first"));
      setDraft(next);
    }
    requestAnimationFrame(() =>
      document.getElementById(`${formId}-setup`)?.scrollIntoView({ block: "start" }),
    );
  };

  // The dose form.
  const ml = amount.trim() === "" ? Number.NaN : Number(amount);
  const max = view?.pump.max_ml ?? 0;
  const validMl = Number.isFinite(ml) && ml > 0 && ml <= max;
  const expected = view && validMl && view.flow && view.flow > 0 ? ml / view.flow : null;
  const doseBlock = !view
    ? null
    : !connected
      ? "Connect to Home Assistant to dose."
      : !admin
        ? "Only a Home Assistant administrator can dose."
        : !reach.live
          ? reach.reason
          : batchRunning
            ? "A batch is running: wait for it to finish."
            : waiting
              ? "Another request is waiting for the controller."
              : view.state === "dosing"
                ? `${view.pump.name} is dosing.`
                : view.state !== "idle"
                  ? view.reason
                  : !validMl
                    ? `Enter more than 0 and at most ${mL(max)} mL.`
                    : expected !== null && expected > MAX_DOSE_S
                      ? `That dose would take ${seconds(expected)}: the controller refuses a dose longer than 20 minutes.`
                      : null;
  const reviewDose = () => {
    if (!view || !validMl) return;
    setReview({
      title: `Dose ${view.pump.name}?`,
      rows: [
        { label: "Pump", value: `${view.pump.name} (${hardwareLabel(view.pump)})` },
        { label: "Amount", value: `${mL(ml)} mL, into the tank as it is` },
        {
          label: "Expected time",
          value: expected
            ? `about ${seconds(expected)} at ${number(view.flow, 2)} mL/s`
            : "unknown: the flow reads nothing",
        },
        {
          label: "It stops",
          value: expected
            ? `by itself: the pump times the dose. Still running after ${seconds(doseDeadline(expected))}, its power is switched off.`
            : "by itself: the pump times the dose.",
        },
      ],
      note: "Watering carries on while a single dose runs.",
      confirm: `Start ${view.pump.name}`,
      data: { action: "dose", pump: view.pump.id, ml },
    });
  };

  // The batch.
  const totals = recipeTotals(rows);
  const time = config ? batchTime(config, rows) : { seconds: null, fillMax: 0 };
  const steps = config ? batchSteps(config, status, states) : [];
  const holdOn = !!config?.batch.hold_entity && states[config.batch.hold_entity]?.state === "on";
  // The controller refuses a batch whose amount entity reads nothing, before anything moves.
  const unreadable = rows.find((row) => row.unreadable);
  const batchBlock = !connected
    ? "Connect to Home Assistant to make a batch."
    : !admin
      ? "Only a Home Assistant administrator can make a batch."
      : !reach.live
        ? reach.reason
        : batchRunning
          ? "A batch is running."
          : running
            ? "A pump is dosing: wait for it to finish."
            : waiting
              ? "Another request is waiting for the controller."
              : holdOn
                ? `${config!.batch.hold_entity} is already on: something else is dosing.`
                : unreadable
                  ? `${unreadable.name}'s amount comes from ${unreadable.entity}, which reads nothing: the controller would refuse the batch.`
                  : !totals.pumps
                    ? "The recipe doses nothing: set it up below."
                    : null;
  const expectedBatch =
    time.seconds === null
      ? "unknown until every dosed pump reads its flow"
      : `about ${seconds(time.seconds)}${time.fillMax ? `, plus the fill (up to ${seconds(time.fillMax)})` : ""}`;
  // A dosed pump that cannot run now: the controller refuses the batch before anything moves.
  // Said here, not refused here: the controller decides.
  const unready = rows
    .filter((row) => !row.skipped)
    .flatMap((row) => {
      const item = views.find((candidate) => candidate.pump.id === row.pump);
      return item && item.state !== "idle" && item.state !== "dosing"
        ? [`${item.pump.name} is ${PUMP_STATES[item.state].label.toLowerCase()}`]
        : [];
    });
  const batchWarning = unready.length
    ? `${unready.join("; ")}: the controller would refuse a batch now.`
    : null;
  const reviewBatch = () =>
    config &&
    setReview({
      title: `Make a batch in ${room.room.name}?`,
      rows: [
        {
          label: "Steps",
          value: steps
            .filter((step) => step.state !== "skipped")
            .map((step) => step.label)
            .join(" → "),
        },
        {
          label: "Recipe",
          value:
            rows
              .filter((row) => !row.skipped)
              .map((row) => `${row.name} ${mL(row.ml)} mL`)
              .join(", ") + ` (${totals.ml === null ? "?" : mL(totals.ml)} mL)`,
        },
        { label: "Expected time", value: expectedBatch },
      ],
      note:
        (batchWarning ? batchWarning + " " : "") +
        `Watering in ${room.room.name}, and in any room whose pump or valves the batch uses, is held until the batch finishes or is stopped.`,
      confirm: "Make the batch",
      data: { action: "batch" },
    });
  const reviewStop = () =>
    setReview({
      title: `Stop dosing in ${room.room.name}?`,
      rows: [
        { label: "Pumps", value: `Every dosing pump in ${room.room.name} is switched off.` },
        ...(batchRunning
          ? [
              {
                label: "The batch",
                value:
                  "Ends now: the fill valve closed, the mixing pump off and watering released.",
              },
            ]
          : []),
      ],
      note: "Stop replaces any request still waiting.",
      confirm: "Send stop",
      stop: true,
      data: { action: "stop" },
    });
  // Stopping is for anyone signed in (the integration allows it); starting stays with administrators.
  const stopAvailable = connected && (running || batchRunning || waiting);

  const tank = tankTelemetry(states, room.room);
  const fullId = config?.batch.full_entity ?? null;
  const full = fullId
    ? !states[fullId] || ["unknown", "unavailable"].includes(states[fullId].state)
      ? "Unavailable"
      : states[fullId].state === config!.batch.full_state
        ? "Full"
        : "Not full"
    : null;
  const current = steps.find((step) => step.state === "running");
  const dosingNow = views.find((item) => item.state === "dosing");
  const lastBatch = status?.history.find((entry) => entry.kind === "batch");
  // "finished 02:00 PM", "stopped 04:10 PM (stop requested during fill the tank)".
  const lastBatchWords = lastBatch
    ? (() => {
        const [head, ...reason] = lastBatch.result.split(":");
        return `${head.trim().toLowerCase() || "ended"} ${when(lastBatch.ended_at ?? lastBatch.at, now)}${reason.length ? ` (${reason.join(":").trim()})` : ""}`;
      })()
    : null;
  const batchLine = !status
    ? reach.reason
    : batchRunning && current
      ? `Making a batch: ${current.label.toLowerCase()}${current.step === "dose" ? ` (${current.detail.replace(/^Dosing /, "")})` : ""}, step ${steps.indexOf(current) + 1} of ${steps.length}`
      : dosingNow
        ? `${dosingNow.pump.name} is dosing`
        : lastBatchWords
          ? `No batch running · last batch ${lastBatchWords}`
          : "No batch running";
  const describe = (request: DosingRequest) =>
    request.action === "dose"
      ? `dose ${name(request.pump)} ${request.ml === null ? "" : `${mL(request.ml)} mL`}`.trim()
      : request.action === "batch"
        ? "make a batch"
        : "stop";
  const recent = stage && now - Date.parse(stage.request.at ?? "") < 10 * 60_000;

  return (
    <div className="dosing-page">
      <Heading
        title="Dosing"
        action={
          config && (
            <Button variant="outline" onClick={() => openSetup(false)}>
              Dosing setup
            </Button>
          )
        }
      />
      {loadError && !config && (
        <Empty
          title="Dosing is not available"
          detail={`${loadError} Dosing needs the Crop Steering integration and controller app with batch-tank dosing.`}
        />
      )}
      {loadError && config && (
        <p className="workspace-message error" role="alert">
          {loadError}
        </p>
      )}
      {loading && <p className="muted">Loading dosing…</p>}
      {config && (
        <section className="panel dosing-tank" aria-label={`${room.room.name} batch tank`}>
          <h2 className="dosing-tank-title">Batch tank</h2>
          <dl className="dosing-tank-facts">
            <div>
              <dt>Level</dt>
              <dd>{reading(tank.level, 0)}</dd>
            </div>
            {full && (
              <div>
                <dt>Float</dt>
                <dd>{full}</dd>
              </div>
            )}
            <div>
              <dt>EC</dt>
              <dd>{reading(tank.ec, 2)}</dd>
            </div>
            <div>
              <dt>pH</dt>
              <dd>{reading(tank.ph, 2)}</dd>
            </div>
            <div>
              <dt>Temperature</dt>
              <dd>{reading(tank.temperature, 1)}</dd>
            </div>
          </dl>
          <p className="dosing-tank-batch" data-batch-line>
            {batchLine}
          </p>
        </section>
      )}
      {stage && recent && (
        <p
          className="dosing-request"
          data-request-stage={stage.stage}
          data-tone={
            stage.stage === "expired" || /^refused|too old/i.test(stage.result ?? "")
              ? "warn"
              : undefined
          }
          role="status"
          tabIndex={-1}
        >
          {stage.stage === "waiting"
            ? `Sent at ${when(stage.request.at, now)}: ${describe(stage.request)}. Waiting for the controller to take it…`
            : stage.stage === "expired"
              ? `The request to ${describe(stage.request)} was not taken within two minutes, so it will not run. Check that the controller is running.`
              : `The controller took the request to ${describe(stage.request)}${stage.result ? `: ${stage.result}` : "."}`}
        </p>
      )}
      {config && !reach.live && (
        <p className="workspace-message" role="status" data-dosing-unreachable>
          {reach.reason} Requests wait for it, and one it cannot take within two minutes is dropped.
        </p>
      )}
      {config && !config.pumps.length && (
        <Empty
          title={`No dosing pumps in ${room.room.name}`}
          detail="Dosing makes a batch of nutrient solution in this room's tank: it fills the tank, mixes it, doses each nutrient in order, mixes again and stamps the fill. It can also dose one pump by hand. It drives dosing pumps whose own firmware times each dose; Home Assistant sets the amount and presses start."
          action={
            admin ? (
              <Button onClick={() => openSetup(true)} disabled={!doc || !connected}>
                Set up dosing
              </Button>
            ) : (
              <p className="muted small">A Home Assistant administrator sets up dosing.</p>
            )
          }
        />
      )}
      {config && !!views.length && (
        <>
          {!!linked.length && (
            <StockStrip items={linked} navigate={navigate} headingId={`${formId}-stock`} />
          )}
          <section className="dosing-pumps-section" aria-labelledby={`${formId}-pumps`}>
            <h2 id={`${formId}-pumps`} className="sr-only">
              Pumps
            </h2>
            <div className="dosing-pumps">
              {views.map((item, index) => (
                <PumpCard
                  key={item.pump.id}
                  view={item}
                  index={index}
                  selected={item.pump.id === view?.pump.id}
                  onSelect={() => setSelected(item.pump.id)}
                  stock={stocks[index]}
                  largest={largest}
                  now={now}
                />
              ))}
            </div>
          </section>
          {view && (
            <div className="dosing-work">
              <section
                className="panel dosing-panel dosing-dose"
                aria-labelledby={`${formId}-dose`}
                data-hue={views.indexOf(view) % 8}
              >
                <div className="dosing-panel-head">
                  <span className="eyebrow">
                    Pump · <span className="dosing-mono">{hardwareLabel(view.pump)}</span>
                  </span>
                  <h2 id={`${formId}-dose`}>Dose {view.pump.name}</h2>
                </div>
                <div className="dosing-mode" role="group" aria-label="Dose by">
                  <span className="dosing-mode-tile" data-chosen>
                    <Check size={15} aria-hidden="true" />
                    <span>
                      <strong>Volume</strong>
                      <small>A set amount</small>
                    </span>
                  </span>
                </div>
                <form
                  className="dosing-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!doseBlock) reviewDose();
                  }}
                >
                  <div className="dosing-field">
                    <Label htmlFor={`${formId}-ml`}>Amount (mL)</Label>
                    <Input
                      id={`${formId}-ml`}
                      type="number"
                      inputMode="decimal"
                      min={0.1}
                      max={max || undefined}
                      step={0.1}
                      value={amount}
                      aria-invalid={!validMl}
                      aria-describedby={`${formId}-ml-help`}
                      onChange={(event) => setAmount(event.target.value)}
                    />
                    <small id={`${formId}-ml-help`} className="muted">
                      Up to {mL(max)} mL
                      {view.flow && view.flow > 0
                        ? ` · ${number(view.flow, 2)} mL/s`
                        : " · the flow reads nothing"}
                    </small>
                  </div>
                  <p className="dosing-summary" data-dose-summary>
                    Your request: <strong>{validMl ? `${mL(ml)} mL` : "—"}</strong>
                    {validMl && ` of ${view.pump.name}`}
                    {expected !== null && `, about ${seconds(expected)}`}
                  </p>
                  <Button type="submit" size="lg" disabled={!!doseBlock}>
                    Start {view.pump.name} <ArrowRight size={17} />
                  </Button>
                  <p className="muted small" data-dose-note>
                    {doseBlock ?? "The pump must be idle. You review the dose before it is sent."}
                  </p>
                </form>
              </section>
              <section
                className="panel dosing-panel dosing-live"
                aria-labelledby={`${formId}-live`}
                data-dosing-live={view.pump.id}
              >
                <div className="dosing-panel-head">
                  <span className="eyebrow">Live telemetry</span>
                  <h2 id={`${formId}-live`}>{view.pump.name} status</h2>
                </div>
                <p className="dosing-huge">
                  <span className="dosing-mono">
                    {view.progress ? mL(view.progress.ml) : view.last ? mL(view.last.ml) : "0"}
                  </span>
                  <small>mL</small>
                </p>
                <p className="muted small dosing-huge-caption">
                  {view.progress
                    ? "dosed this run, estimated from the time and the flow"
                    : view.state === "dosing"
                      ? "dosing: the controller has not said how much"
                      : view.last
                        ? `the last dose, ${when(view.last.at, now)}`
                        : "nothing dosed yet"}
                </p>
                {view.progress && (
                  <div
                    className="dosing-bar dosing-bar-wide"
                    role="progressbar"
                    aria-label={`${view.pump.name} dose`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(view.progress.share * 100)}
                  >
                    <span style={{ width: `${view.progress.share * 100}%` }} />
                  </div>
                )}
                <dl className="dosing-rows">
                  <div>
                    <dt>Target</dt>
                    <dd className="dosing-mono">
                      {view.progress ? `${mL(view.progress.target)} mL` : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt>Elapsed</dt>
                    <dd className="dosing-mono">
                      {view.progress
                        ? `${seconds(view.progress.elapsed)} of ${seconds(view.progress.expected)}`
                        : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt>Flow</dt>
                    <dd className="dosing-mono">
                      {view.flow === null ? "—" : `${number(view.flow, 2)} mL/s`}
                    </dd>
                  </div>
                  <div>
                    <dt>Maximum</dt>
                    <dd className="dosing-mono">{mL(view.pump.max_ml)} mL</dd>
                  </div>
                  <div>
                    <dt>Last result</dt>
                    <dd>
                      {view.last ? (
                        <Pill tone={resultTone(view.last.result)}>
                          {resultWords(view.last.result)}
                        </Pill>
                      ) : (
                        "—"
                      )}
                    </dd>
                  </div>
                </dl>
                <Button
                  variant="outline"
                  className="dosing-stop"
                  disabled={!stopAvailable}
                  onClick={reviewStop}
                >
                  <CircleStop size={16} /> Stop dosing
                </Button>
                <p className="muted small">
                  Stop switches off every dosing pump in {room.room.name}
                  {batchRunning ? " and ends the batch" : ""}.
                </p>
              </section>
            </div>
          )}
          <section className="panel dosing-batch" aria-labelledby={`${formId}-batch`}>
            <div className="panel-heading">
              <div>
                <h2 id={`${formId}-batch`}>Make a batch</h2>
                <p data-batch-summary>
                  {batchRunning
                    ? `Running since ${when(status!.batch.started_at, now)}`
                    : lastBatchWords
                      ? `Last batch ${lastBatchWords}`
                      : "No batch made yet"}
                </p>
              </div>
              <div className="heading-actions">
                {batchRunning ? (
                  <Button
                    variant="outline"
                    className="dosing-stop"
                    disabled={!connected}
                    onClick={reviewStop}
                  >
                    <CircleStop size={16} /> Stop the batch
                  </Button>
                ) : (
                  <Button disabled={!!batchBlock || !canAct} onClick={reviewBatch}>
                    Make a batch
                  </Button>
                )}
              </div>
            </div>
            {!batchRunning && batchBlock && (
              <p className="muted small dosing-batch-note">{batchBlock}</p>
            )}
            {!batchRunning && batchWarning && (
              <p className="small dosing-batch-note dosing-batch-warning" data-batch-warning>
                {batchWarning}
              </p>
            )}
            <div className="dosing-batch-body">
              <ol className="dosing-steps" aria-label="Batch steps">
                {steps.map((step) => (
                  <li key={step.step} data-step={step.step} data-state={step.state}>
                    <span className="dosing-step-mark" aria-hidden="true">
                      <StepMark state={step.state} />
                    </span>
                    <span className="dosing-step-text">
                      <strong>{step.label}</strong>
                      <span>
                        {step.detail}
                        {step.note ? ` · ${step.note}` : ""}
                      </span>
                    </span>
                    <span className="dosing-step-state">{STEP_WORDS[step.state]}</span>
                  </li>
                ))}
              </ol>
              <div className="dosing-recipe">
                <h3>Recipe</h3>
                {rows.length ? (
                  <div className="table-scroll" tabIndex={0} aria-label="Recipe">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Pump</th>
                          <th className="numeric">mL</th>
                          <th className="numeric">Time</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((row) => (
                          <tr key={row.pump} data-recipe-pump={row.pump}>
                            <td>
                              {row.name}
                              {(row.fromEntity || row.unreadable) && (
                                <span className="cell-subtext">
                                  from {row.entity}
                                  {row.unreadable ? ", which reads nothing" : ""}
                                </span>
                              )}
                              {row.unknown && (
                                <span className="cell-subtext">not a pump of this room</span>
                              )}
                            </td>
                            <td className="numeric dosing-mono">
                              {row.unreadable ? "?" : row.skipped ? "passed by" : mL(row.ml)}
                            </td>
                            <td className="numeric dosing-mono">
                              {row.skipped
                                ? "—"
                                : row.seconds === null
                                  ? "?"
                                  : seconds(row.seconds)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                      <tfoot>
                        <tr>
                          <th scope="row">Total</th>
                          <td className="numeric dosing-mono">
                            {totals.ml === null ? "?" : mL(totals.ml)}
                          </td>
                          <td className="numeric dosing-mono">
                            {totals.seconds === null ? "?" : seconds(totals.seconds)}
                          </td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                ) : (
                  <p className="muted small">No pump is in the recipe.</p>
                )}
                <p className="muted small" data-batch-time>
                  Expected time: {expectedBatch}, with {config.batch.premix_min} min of mixing
                  before dosing and {config.batch.postmix_min} min after.
                </p>
              </div>
            </div>
          </section>
          <section className="panel dosing-history" aria-labelledby={`${formId}-history`}>
            <div className="panel-heading">
              <h2 id={`${formId}-history`}>History</h2>
            </div>
            {status?.history.length ? (
              <div className="table-scroll" tabIndex={0} aria-label="Dosing history">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>What</th>
                      <th>Result</th>
                      <th>Amounts</th>
                      <th>By</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.history.map((entry, index) => (
                      <tr key={`${entry.at}-${index}`} data-history-kind={entry.kind}>
                        <td>{when(entry.at, now)}</td>
                        <td>
                          {entry.kind === "batch"
                            ? "Batch"
                            : `Dose ${Object.keys(entry.doses).map(name).join(", ")}`}
                        </td>
                        <td>
                          <Pill tone={resultTone(entry.result)}>{resultWords(entry.result)}</Pill>
                        </td>
                        <td className="dosing-amounts">
                          {Object.entries(entry.doses)
                            .map(([id, amount]) => `${name(id)} ${mL(amount)} mL`)
                            .join(" · ") || "—"}
                        </td>
                        <td>{entry.by ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted dosing-empty-history">No doses or batches yet.</p>
            )}
          </section>
        </>
      )}
      {(config || doc) && (
        <details
          id={`${formId}-setup`}
          className="panel dosing-setup"
          open={setupOpen || !!draft}
          onToggle={(event) => setSetupOpen((event.currentTarget as HTMLDetailsElement).open)}
        >
          <summary>
            <h2>Dosing setup</h2>
            <span className="muted small">
              {config
                ? `${config.pumps.length} ${config.pumps.length === 1 ? "pump" : "pumps"} · revision ${config.revision}`
                : "not set up"}
            </span>
          </summary>
          <DosingSetup
            controller={controller}
            doc={doc}
            config={config}
            draft={draft}
            setDraft={setDraft}
            onSaved={(saved) => setDoc(saved)}
            onDirtyChange={onDirtyChange}
          />
        </details>
      )}
      <RequestDialog controller={controller} review={review} onClose={() => setReview(null)} />
    </div>
  );
}
