import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Check, X } from "lucide-react";
import { Empty } from "@/components/dashboard";
import { NeedsIntegration } from "@/components/needs-integration";
import { PeristalticPump } from "@/components/peristaltic-pump";
import { HoldButton } from "@/components/primitives/hold-button";
import { StepRail } from "@/components/primitives/step-rail";
import { ReviewApply, type ApplyReceipt, type ReviewRow } from "@/components/review-apply";
import { StockBottle } from "@/components/stock-bottle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { stockState, stockTanks } from "@/lib/dosing";
import { callV2, type V2Outcome } from "@/lib/parity-api";
import type { PumpCalibrateStart, PumpCalibrationResult, PumpPrecheck, PumpPrimeResult } from "@/lib/parity-types";
import {
  CALIBRATE_EVERY_DAYS,
  FAR_OFF_PCT,
  PRIME_SECONDS,
  RUN_SECONDS,
  SOLUTION_LABELS,
  calibrationDue,
  canStartRun,
  estimateRate,
  headWords,
  lastCalibration,
  nominalOf,
  offBy,
  parseMl,
  primeActions,
  primeLabel,
  pumpHistory,
  pumpMotion,
  rateSentence,
  runState,
  wearNote,
  type CalibrationPump,
  type PumpDosingDocument,
} from "@/lib/pump-calibration";
import { clock, dayMonth } from "@/lib/time";
import { useNarrow } from "@/lib/use-narrow";
import { useWakeLock } from "@/lib/wake-lock";
import type { PageProps } from "./placeholder";
import "./pump-calibration.css";

const STEPS = ["Pick pump", "Prime", "30 s run", "Enter mL", "Save"];
const TITLES = [
  "Which pump are you calibrating?",
  "Prime the line",
  "Run 30 s into a measuring jug",
  "How much did it pull?",
  "Save the new flow",
];
const PRECHECK_MS = 10_000;
const DOSING_POLL_MS = 2_000;
type Blockers = PumpPrecheck["blockers"];
type Load = { state: "loading" } | { state: "missing" } | { state: "error"; message: string } | { state: "ready"; doc: PumpDosingDocument };
/** The flow number's own value, mL/s, as the integration writes it (4 decimals). */
const mlS = (mlMin: number) => Math.round((mlMin / 60) * 10_000) / 10_000;
const writable = (entityId: string) => /^(number|input_number)\./.test(entityId);
const blockersOf = (outcome: V2Outcome<unknown>): Blockers => {
  const data = outcome.kind === "error" ? (outcome.data as { blockers?: Blockers } | undefined) : undefined;
  return Array.isArray(data?.blockers) ? data.blockers : [];
};

export function PumpCalibration({ controller, navigate, onDirtyChange }: PageProps) {
  const roomId = controller.roomId;
  const tz = controller.timeZone;
  const narrow = useNarrow(720);
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [pumpId, setPumpId] = useState<string | null>(null);
  const [step, setStep] = useState(1);
  const [precheck, setPrecheck] = useState<{ result: PumpPrecheck; at: number } | null>(null);
  const [priming, setPriming] = useState(false);
  const [prime, setPrime] = useState<{ ok: boolean; heldS: number | null; message: string | null; blockers: Blockers } | null>(null);
  const [run, setRun] = useState<{ sessionId: string | null; message: string | null; blockers: Blockers; stopping: boolean } | null>(null);
  const [measured, setMeasured] = useState("");
  const [saved, setSaved] = useState<{ result: PumpCalibrationResult; receipt: ApplyReceipt; before: number | null } | null>(null);
  /** When the current hold began, and how long the last one lasted (s). */
  const heldFrom = useRef<number | null>(null);
  const lastHeld = useRef<number | null>(null);
  const latest = useRef(controller);
  latest.current = controller;

  const read = useCallback(async () => {
    const outcome = await callV2<PumpDosingDocument>(latest.current, "dosing_get", { room_id: roomId });
    if (outcome.kind === "missing") setLoad({ state: "missing" });
    else if (outcome.kind === "error") setLoad((old) => (old.state === "ready" ? old : { state: "error", message: outcome.message }));
    else if (!outcome.data.catalog) setLoad({ state: "missing" });
    else setLoad({ state: "ready", doc: outcome.data });
    return outcome;
  }, [roomId]);
  useEffect(() => {
    void read();
  }, [read]);

  const doc = load.state === "ready" ? load.doc : null;
  const pumps = doc?.config?.pumps ?? [];
  const pump: CalibrationPump | null = pumps.find((p) => p.id === pumpId) ?? pumps[0] ?? null;
  const session = pump?.calibration_session ?? null;
  const ours = session && run?.sessionId === session.session_id ? session : null;
  const ran = runState(ours) === "ran";
  const ranS = ours?.ran_s ?? null;
  const nominal = pump ? nominalOf(pump, doc?.catalog) : null;
  const last = pump ? lastCalibration(pump) : null;
  const previous = pump?.calibrated_ml_min ?? last?.mlMin ?? null;
  const ml = parseMl(measured);
  const rate = ml !== null && ranS ? estimateRate(ml, ranS) : null;
  const waiting = !!run?.sessionId && !ran;
  const admin = controller.admin === false ? "Only a Home Assistant administrator can prime or calibrate a pump." : undefined;

  useWakeLock(step >= 2 && step <= 4);
  // A step change moves focus to the new step's heading, so it is announced (not on first render).
  const stepHeading = useRef<HTMLHeadingElement>(null);
  const shownStep = useRef(step);
  useEffect(() => {
    if (shownStep.current === step) return;
    shownStep.current = step;
    stepHeading.current?.focus();
  }, [step]);
  // Leaving with a run open or a measurement typed asks first (the app's unsaved-changes guard).
  const dirty = !saved && (!!run?.sessionId || measured.trim() !== "");
  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  // Step 2: what stops a prime now, every 10 s.
  useEffect(() => {
    if (step !== 2 || !pump) return;
    let live = true;
    const check = async () => {
      // Our own prime may read as dosing: never check (and so disable the button) mid-hold.
      if (heldFrom.current !== null) return;
      const outcome = await callV2<PumpPrecheck>(latest.current, "pump_precheck", { room_id: roomId, pump: pump.id });
      if (!live) return;
      if (outcome.kind === "ok") setPrecheck({ result: outcome.data, at: Date.now() });
      else if (outcome.kind === "missing") setLoad({ state: "missing" });
    };
    void check();
    const timer = setInterval(() => void check(), PRECHECK_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [step, pump?.id, roomId]);

  // Step 3: dosing_get every 2 s until the controller reports the run.
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => void read(), DOSING_POLL_MS);
    return () => clearInterval(timer);
  }, [waiting, read]);
  // A run that ran moves on to the measurement.
  useEffect(() => {
    if (step === 3 && ran && ranS !== null && ranS > 0) setStep(4);
  }, [step, ran, ranS]);

  const send = useCallback(
    async (action: "pump_prime" | "pump_stop", data: Record<string, unknown>) => {
      if (action === "pump_stop") {
        const heldS = heldFrom.current === null ? null : Math.round((performance.now() - heldFrom.current) / 100) / 10;
        heldFrom.current = null;
        lastHeld.current = heldS;
        setPriming(false);
        setPrime((old) => (old ? { ...old, heldS } : old));
        return callV2(latest.current, action, data);
      }
      heldFrom.current = performance.now();
      lastHeld.current = null;
      setPriming(true);
      setPrime(null);
      const outcome = await callV2<PumpPrimeResult>(latest.current, action, data);
      const blockers = blockersOf(outcome);
      setPrime({
        ok: outcome.kind === "ok",
        // Let go before the answer came: the hold's length is known already.
        heldS: heldFrom.current === null ? lastHeld.current : null,
        message: outcome.kind === "error" && !blockers.length ? outcome.message : outcome.kind === "missing" ? "This integration cannot prime a pump." : null,
        blockers,
      });
      return outcome;
    },
    [],
  );
  const hold = useMemo(() => (pump ? primeActions(send, roomId, pump.id) : null), [send, roomId, pump?.id]);

  const startRun = async () => {
    if (!pump) return;
    setRun({ sessionId: null, message: null, blockers: [], stopping: false });
    const outcome = await callV2<PumpCalibrateStart>(latest.current, "pump_calibrate", { room_id: roomId, pump: pump.id, seconds: RUN_SECONDS });
    if (outcome.kind === "ok" && outcome.data.session_id) {
      setRun({ sessionId: outcome.data.session_id, message: null, blockers: [], stopping: false });
      void read();
      return;
    }
    const blockers = blockersOf(outcome);
    setRun({
      sessionId: null,
      message: outcome.kind === "error" && !blockers.length ? outcome.message : null,
      blockers,
      stopping: false,
    });
  };
  const stopRun = async () => {
    if (!pump) return;
    setRun((old) => (old ? { ...old, stopping: true } : old));
    await callV2(latest.current, "pump_stop", { room_id: roomId, pump: pump.id });
    void read();
  };

  const rows: ReviewRow[] =
    pump && rate !== null && !saved
      ? [
          { id: "flow", label: `${pump.name} flow`, before: previous === null ? "Not calibrated" : `${previous} mL/min`, after: `${rate} mL/min` },
          ...(writable(pump.flow_entity)
            ? [
                {
                  id: "flow_entity",
                  label: String(controller.states[pump.flow_entity]?.attributes.friendly_name ?? pump.flow_entity),
                  before: `${controller.states[pump.flow_entity]?.state ?? "unknown"} mL/s`,
                  after: `${mlS(rate)} mL/s`,
                },
              ]
            : []),
        ]
      : [];

  const apply = async () => {
    const outcome = await callV2<PumpCalibrationResult>(latest.current, "pump_calibration_commit", {
      room_id: roomId,
      session_id: run?.sessionId,
      measured_ml: ml,
    });
    if (outcome.kind !== "ok") return outcome;
    const { ml_min } = outcome.data;
    // Read the stored flow back: the receipt claims only what dosing_get now holds.
    const back = await read();
    const stored = back.kind === "ok" ? back.data.config?.pumps.find((p) => p.id === pump!.id)?.calibrated_ml_min : undefined;
    const notConfirmed = [
      ...(stored === ml_min ? [] : ["flow"]),
      ...(rows.some((r) => r.id === "flow_entity") && !outcome.data.flow_entity_written ? ["flow_entity"] : []),
    ];
    const written = rows.filter((r) => !notConfirmed.includes(r.id));
    const receipt: ApplyReceipt = {
      at: Date.now(),
      ok: !notConfirmed.length,
      failed: [],
      ...(notConfirmed.length ? { notConfirmed } : {}),
      summary: written
        .map((r) => (r.id === "flow" ? `${r.label} ${r.before} → ${ml_min} mL/min` : `${r.label} ${r.before} → ${mlS(ml_min)} mL/s`))
        .join(" · "),
      eventIds: outcome.eventIds,
    };
    setSaved({ result: outcome.data, receipt, before: previous });
    setRun(null);
    return receipt;
  };

  const restart = () => {
    setStep(1);
    setPrime(null);
    setRun(null);
    setMeasured("");
    setSaved(null);
    setPrecheck(null);
  };

  const room = controller.room.room.name;
  const header = (
    <div className="pump-cal-title">
      <button type="button" className="pump-cal-crumb" onClick={() => navigate("equipment/dosing")}>
        Feed &amp; dosing · {room}
      </button>
      <span className="pump-cal-sep" aria-hidden="true">
        ›
      </span>
      <h1>Prime &amp; calibrate a pump</h1>
    </div>
  );
  if (load.state === "missing")
    return (
      <div className="pump-cal">
        {header}
        <section className="panel" aria-labelledby="pump-cal-missing-title">
          <h2 id="pump-cal-missing-title" className="sr-only">
            Pump prime and calibration
          </h2>
          <NeedsIntegration feature="Pump prime and calibration" />
        </section>
      </div>
    );
  if (load.state !== "ready" || !pump)
    return (
      <div className="pump-cal">
        {header}
        <section className="panel">
          {load.state === "loading" ? (
            <Empty title="Reading the dosing pumps…" detail="Asking Home Assistant for this room's dosing setup." />
          ) : load.state === "error" ? (
            <Empty title="The dosing setup could not be read" detail={load.message} action={<Button onClick={() => void read()}>Try again</Button>} />
          ) : (
            <Empty
              title="No dosing pumps in this room"
              detail="Add the room's dosing pumps in Feed & dosing first."
              action={<Button onClick={() => navigate("equipment/dosing")}>Open Feed &amp; dosing</Button>}
            />
          )}
        </section>
      </div>
    );

  const now = Date.now();
  const details = [
    `${pump.name} · ${pump.solution_type ? SOLUTION_LABELS[pump.solution_type] : "pump"}`,
    prime?.ok && prime.heldS !== null ? `held ${prime.heldS} s` : "hold to fill the line",
    ran && ranS !== null ? `ran ${ranS} s` : "into a jug",
    rate !== null && step > 3 ? `${rate} mL/min` : "from the jug",
    saved?.receipt.ok ? `read back ${clock(saved.receipt.at, tz)}` : "write + read back",
  ];
  const primeBlockers = precheck?.result.blockers ?? [];
  const primeDisabled = admin ?? (primeBlockers.length ? primeBlockers.map((b) => b.message).join(". ") : undefined);
  const far = rate !== null ? offBy(rate, nominal ?? previous) : null;
  const farText =
    far !== null && Math.abs(far) > FAR_OFF_PCT
      ? `More than ${FAR_OFF_PCT}% off ${nominal !== null ? "the catalogue figure" : "its last calibration"}: check for air in the line or a worn tube, then run again.`
      : null;
  const history = pumpHistory(pump);
  const wear = wearNote(history, tz);

  const next: { label: string; enabled: boolean; go(): void } | null =
    step === 1
      ? { label: `Next: prime ${pump.name}`, enabled: true, go: () => setStep(2) }
      : step === 2
        ? { label: "Line is full, next", enabled: !!prime?.ok && !priming, go: () => setStep(3) }
        : step === 4
          ? { label: "Next: review and save", enabled: rate !== null, go: () => setStep(5) }
          : null;
  const backOff = step === 1 || priming || waiting || !!saved;

  return (
    <div className="pump-cal" data-step={step}>
      {header}
      <section className="pump-cal-rail panel">
        <StepRail compact={narrow} current={saved ? 5 : step} steps={STEPS.map((title, i) => ({ title, detail: details[i] }))} />
      </section>
      <section className="pump-cal-body panel" aria-labelledby={`pump-cal-step-${step}`}>
        <div className="pump-cal-main">
          <h2 id={`pump-cal-step-${step}`} ref={stepHeading} tabIndex={-1} className="pump-cal-step-title">
            {TITLES[step - 1]}
          </h2>
          {step === 1 && (
            <>
              <div
                className="pump-cal-pumps"
                role="radiogroup"
                aria-label="Pump"
                onKeyDown={(e) => {
                  // Arrow keys move the pick between pumps (one tab stop for the group).
                  const delta = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 0;
                  if (!delta) return;
                  e.preventDefault();
                  const index = (pumps.findIndex((p) => p.id === pump.id) + delta + pumps.length) % pumps.length;
                  setPumpId(pumps[index].id);
                  e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')[index]?.focus();
                }}
              >
                {pumps.map((p, i) => {
                  const lastOf = lastCalibration(p);
                  const due = calibrationDue(lastOf?.at ?? null, CALIBRATE_EVERY_DAYS, now);
                  const on = p.id === pump.id;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      tabIndex={on ? 0 : -1}
                      className="pump-cal-card"
                      data-due={due.due ? "" : undefined}
                      onClick={() => setPumpId(p.id)}
                    >
                      <span className="pump-cal-card-name">
                        <b>{p.name}</b> <small>pump {i + 1}</small>
                      </span>
                      <span>{lastOf ? `Calibrated ${dayMonth(lastOf.at, tz)} · ${lastOf.mlMin} mL/min` : "Not calibrated yet"}</span>
                      <span className="pump-cal-due">
                        {due.days === null
                          ? `Due: calibrate it every ${CALIBRATE_EVERY_DAYS} days`
                          : `${due.days} ${due.days === 1 ? "day" : "days"} ago${due.due ? ` · due, every ${CALIBRATE_EVERY_DAYS} days` : ""}`}
                      </span>
                    </button>
                  );
                })}
              </div>
              <dl className="pump-cal-facts">
                <div>
                  <dt>What this pump doses</dt>
                  <dd>{pump.solution_type ? SOLUTION_LABELS[pump.solution_type] : "Not set"}</dd>
                </div>
                <div>
                  <dt>Pump head</dt>
                  <dd>{headWords(pump, doc?.catalog)}</dd>
                </div>
              </dl>
              <p className="pump-cal-hint">
                The catalogue figure is what your result is compared with. Both are set in{" "}
                <button type="button" className="pump-cal-link" onClick={() => navigate("equipment/dosing")}>
                  Feed &amp; dosing
                </button>
                .
              </p>
            </>
          )}
          {step === 2 && (
            <>
              <p>
                Put the end of the {pump.name} dosing line in a waste cup. Hold the button until liquid runs out with no bubbles. The pump
                stops the moment you let go, and by itself after {PRIME_SECONDS} s.
              </p>
              <ul className="pump-cal-checks" aria-label="Before priming" aria-live="polite">
                {!precheck ? (
                  <li>Checking what could stop the pump…</li>
                ) : primeBlockers.length ? (
                  primeBlockers.map((b) => (
                    <li key={b.code} className="is-bad">
                      <X aria-hidden />
                      {b.message}
                    </li>
                  ))
                ) : (
                  <li className="is-ok">
                    <Check aria-hidden />
                    Nothing stops a prime now
                  </li>
                )}
              </ul>
              {/* Outside the live list, so the time does not re-announce every check. */}
              {precheck && <p className="pump-cal-hint">Checked {clock(precheck.at, tz)}</p>}
              {hold && (
                <HoldButton
                  mode="while-held"
                  label={primeLabel(priming, prime?.ok)}
                  srLabel={`Runs ${pump.name} only while held, at most ${PRIME_SECONDS} s.`}
                  maxSeconds={PRIME_SECONDS}
                  disabledReason={primeDisabled}
                  onStart={hold.onStart}
                  onStop={hold.onStop}
                />
              )}
              <div className="pump-cal-status" role="status">
                {prime?.blockers.length ? (
                  <span className="is-bad">The controller refused the prime: {prime.blockers.map((b) => b.message).join("; ")}.</span>
                ) : prime?.message ? (
                  <span className="is-bad">{prime.message}</span>
                ) : prime?.ok && prime.heldS !== null ? (
                  <span>
                    You held it {prime.heldS} s. Hold again if the line still has air in it.
                  </span>
                ) : null}
              </div>
            </>
          )}
          {step === 3 && (
            <>
              <p>Put the suction line in a measuring jug with at least 250 mL.</p>
              {canStartRun(run?.sessionId, ours) && (
                <HoldButton
                  mode="hold-to-confirm"
                  label={`Run ${RUN_SECONDS} s`}
                  srLabel={`Hold to start: ${pump.name} runs ${RUN_SECONDS} s at full speed, then stops by itself.`}
                  maxSeconds={RUN_SECONDS}
                  disabledReason={admin}
                  onStart={() => void startRun()}
                />
              )}
              <div className="pump-cal-status" role="status">
                {waiting ? (
                  <>
                    <span>Waiting for the controller to report the run…</span>
                    <Button variant="outline" size="sm" disabled={run?.stopping} onClick={() => void stopRun()}>
                      {run?.stopping ? "Stopping…" : "Stop the run"}
                    </Button>
                  </>
                ) : ran && ranS !== null && ranS <= 0 ? (
                  <span className="is-bad">The run did not run: {ours?.result ?? "no time reported"}. Hold Run again.</span>
                ) : run?.blockers.length ? (
                  <span className="is-bad">The controller refused the run: {run.blockers.map((b) => b.message).join("; ")}.</span>
                ) : run?.message ? (
                  <span className="is-bad">{run.message}</span>
                ) : null}
              </div>
              {ours && <p className="pump-cal-hint">Room dosing waits while this run is open, until you save or {clock(Date.parse(ours.expires_at), tz)}.</p>}
            </>
          )}
          {step === 4 && (
            <MeasuredField
              value={measured}
              onChange={setMeasured}
              line={
                ml === null
                  ? "Enter the mL in the jug, a number above 0."
                  : rate !== null
                    ? `${ml} mL in ${ranS} s = ${rate} mL/min`
                    : null
              }
              invalid={measured.trim() !== "" && ml === null}
              warn={farText}
            />
          )}
          {step === 5 && (
            <>
              <ReviewApply
                layout="panel"
                rows={rows}
                summary={saved ? undefined : <span className="review-apply-sub">{`${pump.name}: ${ml} mL in ${ranS} s`}</span>}
                applyLabel={rate !== null ? `Save ${rate} mL/min` : undefined}
                discardLabel="Change the mL"
                onDiscard={() => setStep(4)}
                checks={farText ? [{ ok: "warn", text: farText }] : undefined}
                apply={apply}
                last={saved?.receipt ?? null}
                onReload={() => void read()}
                timeZone={tz}
              />
              {saved && (
                <div className="pump-cal-result">
                  <p className="pump-cal-rate">{rateSentence(saved.result.ml_min, nominal)}</p>
                  {history.length > 1 && <WearSpark history={history} name={pump.name} />}
                  {wear && <p className="pump-cal-wear">{wear}</p>}
                  <Button variant="outline" onClick={restart}>
                    Calibrate another pump
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
        {!narrow && (
          <PumpVisual
            pump={pump}
            motion={pumpMotion(pump.name, { priming, primeOk: prime?.ok, waiting })}
            prefix={roomId.replace(/^room:/, "")}
            states={controller.states}
          />
        )}
      </section>
      <footer className="pump-cal-foot panel">
        <Button variant="outline" disabled={backOff} onClick={() => setStep((s) => Math.max(1, s - 1))}>
          Back
        </Button>
        <span className="pump-cal-count">
          Step {saved ? 5 : step} of {STEPS.length}
        </span>
        {next && (
          <Button disabled={!next.enabled} onClick={next.go}>
            {next.label}
          </Button>
        )}
      </footer>
    </div>
  );
}

function MeasuredField({
  value,
  onChange,
  line,
  invalid,
  warn,
}: {
  value: string;
  onChange(value: string): void;
  line: string | null;
  invalid: boolean;
  warn: string | null;
}) {
  const id = useId();
  return (
    <div className="pump-cal-measure">
      <label htmlFor={id}>mL in the jug</label>
      <span className="pump-cal-ml">
        <Input
          id={id}
          inputMode="decimal"
          value={value}
          aria-invalid={invalid || undefined}
          aria-describedby={`${id}-line`}
          onChange={(e) => onChange(e.target.value)}
        />
        <span aria-hidden="true">mL</span>
      </span>
      <p id={`${id}-line`} className={invalid ? "is-bad" : undefined}>
        {line}
      </p>
      {warn && <p className="pump-cal-warn">{warn}</p>}
    </div>
  );
}

/** The pump's calibrated flow over its kept calibrations, oldest to newest. */
function WearSpark({ history, name }: { history: { at: number; mlMin: number }[]; name: string }) {
  const values = history.map((h) => h.mlMin);
  const lo = Math.min(...values),
    hi = Math.max(...values);
  const span = hi - lo || 1;
  const points = history
    .map((h, i) => `${((i / (history.length - 1)) * 116 + 2).toFixed(1)},${(30 - ((h.mlMin - lo) / span) * 26).toFixed(1)}`)
    .join(" ");
  return (
    <svg
      className="pump-cal-spark"
      viewBox="0 0 120 34"
      role="img"
      aria-label={`${name} flow over its last ${history.length} calibrations: ${values[0]} to ${values[values.length - 1]} mL/min`}
    >
      <polyline points={points} />
    </svg>
  );
}

/** The pump drawn beside its stock bottle; it turns only while an accepted prime runs. */
function PumpVisual({
  pump,
  motion,
  prefix,
  states,
}: {
  pump: CalibrationPump;
  motion: { active: boolean; text: string };
  prefix: string;
  states: PageProps["controller"]["states"];
}) {
  const tank = pump.stock_tank ? stockTanks(states, prefix).find((t) => t.id === pump.stock_tank) : undefined;
  return (
    <aside className="pump-cal-visual" aria-label={`${pump.name} pump`}>
      <div className="pump-cal-rig">
        {tank && <StockBottle tank={tank} state={stockState(tank)} label={`${tank.name} stock`} />}
        <PeristalticPump state={motion.active ? "dosing" : "idle"} label={motion.active ? `${pump.name} running` : `${pump.name} idle`} />
      </div>
      <p>{motion.text}</p>
    </aside>
  );
}
