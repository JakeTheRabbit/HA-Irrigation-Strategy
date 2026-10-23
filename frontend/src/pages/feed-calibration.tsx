import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, X } from "lucide-react";
import { Empty } from "@/components/dashboard";
import { NeedsIntegration } from "@/components/needs-integration";
import { ProbeCalibration } from "@/components/probe-calibration";
import { StabilityRing } from "@/components/primitives/ring";
import { StepRail } from "@/components/primitives/step-rail";
import { ReviewApply, type ApplyReceipt, type ReviewRow } from "@/components/review-apply";
import { Button } from "@/components/ui/button";
import { evaluate, type CalibrationDocument, type CalibrationResult } from "@/lib/calibration";
import { formatTemp } from "@/lib/display-units";
import {
  KIND_OF,
  NAME_OF,
  WINDOW_MS,
  appliedRecord,
  bufferName,
  captureState,
  confirmStored,
  digitsOf,
  dueLine,
  dueState,
  feedValue,
  forcedLine,
  isApplied,
  looksSteady,
  proofLine,
  refusalView,
  sessionStore,
  spanOver,
  steadyFor,
  verdictWords,
  type FeedKind,
  type FeedProbe,
  type Reading,
  type StoredSession,
} from "@/lib/feed-calibration";
import { callV2, type V2Outcome } from "@/lib/parity-api";
import type { CalibrationCommitResult, CalibrationSession, CalibrationStatus, CaptureResult } from "@/lib/parity-types";
import { clock, shortDate } from "@/lib/time";
import { revertEvents } from "@/lib/undo";
import { useNarrow } from "@/lib/use-narrow";
import { useWakeLock } from "@/lib/wake-lock";
import type { PageProps } from "./placeholder";
import "./feed-calibration.css";

const STEPS = ["Choose probe", "Buffer 1", "Buffer 2", "Result", "Apply"];
const PROBE_ORDER: FeedProbe[] = ["feed_ph", "feed_ec"];
const STATUS_MS = 5_000;
const TRACE_MS = 60_000;
const GRADES = [
  { verdict: "pass", word: "Pass" },
  { verdict: "drifting", word: "Drift" },
  { verdict: "fail", word: "Fail" },
] as const;
type Load = { state: "loading" } | { state: "missing" } | { state: "error"; message: string } | { state: "ready"; doc: CalibrationDocument };
type CaptureNote = { point: number; kind: "captured" | "moving" | "other"; text: string } | null;
const signed = (value: number, kind: FeedKind) => (value > 0 ? "+" : value < 0 ? "−" : "") + feedValue(Math.abs(value), kind, 2);
const correction = (r: { slope_pct: number; offset: number }, kind: FeedKind) =>
  `Response ${r.slope_pct}% · offset ${signed(r.offset, kind)}${kind === "ph" ? " pH" : ""}`;

export function FeedCalibration({ controller, navigate }: PageProps) {
  const roomId = controller.roomId;
  const prefix = roomId.replace(/^room:/, "");
  const tz = controller.timeZone;
  const room = controller.room.room.name;
  const narrow = useNarrow(720);
  const store = useMemo(() => sessionStore(), []);
  const latest = useRef(controller);
  latest.current = controller;

  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [probe, setProbe] = useState<FeedProbe | null>(null);
  const [session, setSessionState] = useState<StoredSession | null>(null);
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [note, setNote] = useState<CaptureNote>(null);
  // calibration_status said the probe has no reading (raw: null), as capture would refuse.
  const [silent, setSilent] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [done, setDone] = useState<{ session: StoredSession; result: CalibrationCommitResult; receipt: ApplyReceipt; undone: boolean } | null>(
    null,
  );
  const [now, setNow] = useState(() => Date.now());

  const read = useCallback(async () => {
    const outcome = await callV2<CalibrationDocument>(latest.current, "calibration_get", { room_id: roomId });
    if (outcome.kind === "missing") setLoad({ state: "missing" });
    else if (outcome.kind === "error") setLoad({ state: "error", message: outcome.message });
    else setLoad({ state: "ready", doc: outcome.data });
    return outcome;
  }, [roomId]);
  useEffect(() => {
    void read();
  }, [read]);

  /** The session in state and in this browser's store, so it can be resumed. */
  const setSession = useCallback(
    (next: StoredSession | null) => {
      setSessionState(next);
      if (next) store.set(next);
      else store.clear();
    },
    [store],
  );
  /** A change onto the latest session (not the one read before an await), if it is still that one. */
  const patchSession = useCallback(
    (id: string, change: (s: StoredSession) => StoredSession) =>
      setSessionState((s) => {
        if (!s || s.session_id !== id) return s;
        const next = change(s);
        store.set(next);
        return next;
      }),
    [store],
  );
  /** The session ended on the integration (EXPIRED): its hold on dosing went with it. The probe
   * stays chosen for Start again. */
  const sessionExpired = useCallback(
    (which: FeedProbe) => {
      setProbe(which);
      setSession(null);
      setExpired(true);
    },
    [setSession],
  );
  /** Asks the integration when the session ends now (a capture restarts its 30 min). */
  const refreshExpiry = useCallback(
    async (id: string) => {
      const outcome = await callV2<CalibrationStatus>(latest.current, "calibration_status", { session_id: id });
      if (outcome.kind === "ok") patchSession(id, (s) => ({ ...s, expires_at: outcome.data.expires_at }));
    },
    [patchSession],
  );
  // Sessions being abandoned: not offered for Resume while the integration answers.
  const abandoning = useRef(new Set<string>());
  const [recheck, setRecheck] = useState(0);
  /** Ends the session without a record, so it no longer holds dosing until it expires. The stored
   * session goes only once the integration says it ended: unanswered, it is still offered for Resume. */
  const abandon = (open: StoredSession | null) => {
    if (!open) return;
    abandoning.current.add(open.session_id);
    void callV2(latest.current, "calibration_abandon", { session_id: open.session_id }).then((outcome) => {
      // Gone either way (ended now, or expired already): nothing left to resume.
      if (outcome.kind === "ok" || (outcome.kind === "error" && refusalView(outcome).kind === "expired")) store.clear();
      abandoning.current.delete(open.session_id);
      setRecheck((n) => n + 1);
    });
  };
  const goto = (n: number) => {
    setStep(n);
    if (session) setSession({ ...session, step: n });
  };

  const doc = load.state === "ready" ? load.doc : null;
  const probes = PROBE_ORDER.filter((p) => doc?.sensors?.[p]);
  const chosen: FeedProbe | null = session?.probe ?? done?.session.probe ?? (probe && probes.includes(probe) ? probe : (probes[0] ?? null));
  const kind: FeedKind = chosen ? KIND_OF[chosen] : "ph";
  const name = NAME_OF[kind];
  const point = step === 2 ? 0 : step === 3 ? 1 : null;
  // The session in progress, or the one just applied (its points stay on the rail).
  const shown = session ?? done?.session ?? null;
  const buffers = shown?.solutions.map((s) => bufferName(s, kind)) ?? [];
  const admin = controller.admin === false ? "Only a Home Assistant administrator can calibrate a probe." : null;

  // The probe's own reports, as the subscription brings them (the controller subscribes to every
  // sensor the room's descriptor names, the feed probes and the tank temperature among them).
  const raw = session ? controller.states[session.raw_entity_id] : undefined;
  const rawValue = raw && raw.state !== "" ? Number(raw.state) : NaN;
  const readings = useRef<Reading[]>([]);
  useEffect(() => {
    readings.current = [];
    setSilent(false);
  }, [session?.session_id]);
  useEffect(() => {
    if (!raw) return;
    if (!Number.isFinite(rawValue)) {
      // Unavailable: steady again only after a whole window of readings (as the integration).
      readings.current = [];
      return;
    }
    const at = Date.parse(raw.last_updated ?? raw.last_changed ?? "") || Date.now();
    const last = readings.current[readings.current.length - 1];
    if (last && (last.value === rawValue || last.at >= at)) return;
    readings.current = [...readings.current.filter((r) => r.at > at - 10 * WINDOW_MS), { at, value: rawValue }];
  }, [raw?.state, raw?.last_updated]);

  // A clock for the stability window while a point is being read.
  useEffect(() => {
    if (point === null || !session) return;
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, [point, session]);

  // The open session, every 5 s: when it ends, and whether it still exists.
  useEffect(() => {
    if (!session || done || expired) return;
    let live = true;
    const check = async () => {
      const outcome = await callV2<CalibrationStatus>(latest.current, "calibration_status", { session_id: session.session_id });
      if (!live) return;
      if (outcome.kind === "ok") {
        setSilent(outcome.data.raw === null);
        const expires = outcome.data.expires_at;
        if (expires !== session.expires_at) patchSession(session.session_id, (s) => ({ ...s, expires_at: expires }));
      } else if (outcome.kind === "error" && refusalView(outcome).kind === "expired") sessionExpired(session.probe);
    };
    const timer = setInterval(() => void check(), STATUS_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [session, done, expired, patchSession, sessionExpired]);

  useWakeLock(step >= 2 && step <= 4 && !!session);

  // The session this browser left open, offered on step 1 (and its hold on dosing claimed) only
  // while calibration_status confirms the integration still has it: a restart, an Undo, or a commit or
  // abandon on another device ends it there. Asked again every 5 s.
  const [held, setHeld] = useState<StoredSession | null>(null);
  useEffect(() => {
    if (session || done || step !== 1) {
      setHeld(null);
      return;
    }
    let live = true;
    const check = async () => {
      const stored = store.resumable(roomId, Date.now());
      if (!stored || abandoning.current.has(stored.session_id)) {
        if (live) setHeld(null);
        return;
      }
      const outcome = await callV2<CalibrationStatus>(latest.current, "calibration_status", { session_id: stored.session_id });
      if (!live) return;
      const confirmed = confirmStored(stored, outcome);
      if (confirmed.held) store.set(confirmed.held);
      else if (confirmed.clear) store.clear();
      setHeld(confirmed.held);
    };
    void check();
    const timer = setInterval(() => void check(), STATUS_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [session, done, step, roomId, store, recheck]);

  const start = async (which: FeedProbe) => {
    setBusy(true);
    setStartError(null);
    const outcome = await callV2<CalibrationSession>(latest.current, "calibration_start", { room_id: roomId, probe: which });
    setBusy(false);
    if (outcome.kind === "missing") return setLoad({ state: "missing" });
    if (outcome.kind === "error") return setStartError(outcome.message);
    const d = outcome.data;
    setSession({
      session_id: d.session_id,
      expires_at: d.expires_at,
      step: 2,
      room_id: roomId,
      probe: which,
      kind: KIND_OF[which],
      solutions: d.solutions,
      raw_entity_id: d.raw_entity_id,
      temperature_entity_id: d.temperature_entity_id,
      dosing_paused: d.dosing_paused,
      points: [null, null],
      forced: [false, false],
    });
    setExpired(false);
    setNote(null);
    setFailed(null);
    setDone(null);
    setStep(2);
  };
  const resume = async (stored: StoredSession) => {
    setBusy(true);
    const outcome = await callV2<CalibrationStatus>(latest.current, "calibration_status", { session_id: stored.session_id });
    setBusy(false);
    const confirmed = confirmStored(stored, outcome);
    if (confirmed.held) {
      setProbe(stored.probe);
      setSession(confirmed.held);
      setStep(Math.min(Math.max(stored.step, 2), 4));
    } else {
      if (confirmed.clear) store.clear();
      setHeld(null);
      if (outcome.kind === "error" && refusalView(outcome).kind === "expired") {
        setProbe(stored.probe);
        setExpired(true);
      } else setStartError(outcome.kind === "error" ? outcome.message : "This integration has no guided calibration.");
    }
  };
  const capture = async (index: number, force = false) => {
    if (!session) return;
    setBusy(true);
    const outcome = await callV2<CaptureResult>(latest.current, "calibration_capture", {
      session_id: session.session_id,
      point: index,
      ...(force ? { force: true } : {}),
    });
    setBusy(false);
    if (outcome.kind === "ok" && outcome.data.raw !== null) {
      const value = outcome.data.raw;
      const forced = force && !outcome.data.stable;
      patchSession(session.session_id, (s) => ({
        ...s,
        points: s.points.map((p, i) => (i === index ? value : p)),
        forced: [0, 1].map((i) => (i === index ? forced : !!s.forced?.[i])),
      }));
      const captured = `Captured ${feedValue(value, kind, digitsOf(raw?.state))}`;
      setNote({ point: index, kind: "captured", text: forced ? `${captured} while still moving` : captured });
      void refreshExpiry(session.session_id);
      return;
    }
    if (outcome.kind === "ok") return setNote({ point: index, kind: "other", text: "The controller had no reading to capture." });
    const view = refusalView(outcome);
    if (view.kind === "expired") return sessionExpired(session.probe);
    if (view.kind === "missing") return setLoad({ state: "missing" });
    setNote({ point: index, kind: view.kind === "moving" ? "moving" : "other", text: view.text });
    // A capture refused only because the reading moves still restarted the session's 30 min.
    if (view.kind === "moving") void refreshExpiry(session.session_id);
  };

  const points = shown?.points ?? [null, null];
  const local: CalibrationResult | { error: string } | null =
    shown && points[0] !== null && points[1] !== null
      ? evaluate(kind, [
          { reference: shown.solutions[0], reading: points[0] },
          { reference: shown.solutions[1], reading: points[1] },
        ])
      : null;
  const result = local && !("error" in local) ? local : null;
  const inForce = chosen ? appliedRecord(doc, chosen) : null;

  const recordFail = async () => {
    if (!session) return;
    setBusy(true);
    const outcome = await callV2<CalibrationCommitResult>(latest.current, "calibration_commit", { session_id: session.session_id });
    if (outcome.kind === "ok") {
      // The integration passed what the page read as a fail, and applied it: its receipt and Undo.
      await committed(session, outcome);
      setBusy(false);
      return setStep(5);
    }
    setBusy(false);
    if (outcome.kind === "error" && refusalView(outcome).kind === "expired") return sessionExpired(session.probe);
    // The integration's own words (a fail is recorded, never applied) on step 1, to start again.
    setFailed(outcome.kind === "error" ? outcome.message : "This integration has no guided calibration.");
    setSession(null);
    setStep(1);
    void read();
  };

  const rows: ReviewRow[] =
    result && session && !done
      ? [
          {
            id: "calibration",
            label: `${room} feed ${name} correction`,
            before: inForce ? correction(inForce, kind) : "None, raw reading",
            after: correction(result, kind),
          },
        ]
      : [];
  const apply = async (): Promise<ApplyReceipt> => {
    const s = session!;
    const outcome = await callV2<CalibrationCommitResult>(latest.current, "calibration_commit", { session_id: s.session_id });
    if (outcome.kind !== "ok") {
      const view = outcome.kind === "missing" ? null : refusalView(outcome);
      if (view?.kind === "expired") sessionExpired(s.probe);
      return {
        at: Date.now(),
        ok: false,
        failed: [],
        summary: "",
        eventIds: [],
        message: view ? view.text : "This integration has no guided calibration.",
      };
    }
    return committed(s, outcome);
  };
  /** A commit the integration accepted. Its own read-back is "none": the receipt claims only what
   * calibration_get now holds. */
  const committed = async (s: StoredSession, outcome: Extract<V2Outcome<CalibrationCommitResult>, { kind: "ok" }>): Promise<ApplyReceipt> => {
    const label = `${room} feed ${NAME_OF[s.kind]} correction`;
    const before = inForce ? correction(inForce, s.kind) : "None, raw reading";
    const back = await read();
    const verified = back.kind === "ok" && isApplied(back.data, outcome.data.record_id);
    const receipt: ApplyReceipt = {
      at: Date.now(),
      ok: verified,
      ...(verified ? {} : { unconfirmed: true }),
      failed: [],
      summary: verified ? `${label} ${before} → ${correction(outcome.data, s.kind)}` : "",
      eventIds: outcome.eventIds,
      ...(outcome.eventIds.length ? {} : { undoUnavailable: true }),
    };
    setDone({ session: s, result: outcome.data, receipt, undone: false });
    setSession(null);
    return receipt;
  };
  const undo = async (receipt: ApplyReceipt) => {
    await revertEvents(latest.current, receipt.eventIds);
    const back = await read();
    if (back.kind !== "ok" || (done && isApplied(back.data, done.result.record_id)))
      throw new Error("The controller did not confirm the previous calibration. Reload and check it before trying again.");
    setDone((d) => (d ? { ...d, undone: true } : d));
  };

  const startAgain = () => {
    setExpired(false);
    if (chosen) void start(chosen);
  };

  // ---- header (desktop: crumb and title; phone: a full-screen bar with ✕)
  const paused = !expired && !!(session ?? held)?.dosing_paused;
  const shownStep = done ? 5 : step;
  const title = narrow ? `Calibrate ${room} feed ${name}` : `Calibrate feed ${name} probe`;
  const header = narrow ? (
    <div className="feed-cal-phonebar">
      <div>
        <h1>{title}</h1>
        <p>{`Equipment · step ${shownStep} of 5${paused ? " · dosing paused" : ""}`}</p>
      </div>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Close calibration, back to Feed & dosing"
        onClick={() => {
          abandon(session);
          navigate("equipment/dosing");
        }}
      >
        <X aria-hidden />
      </Button>
    </div>
  ) : (
    <div className="feed-cal-title">
      <button
        type="button"
        className="feed-cal-crumb"
        onClick={() => {
          abandon(session);
          navigate("equipment/dosing");
        }}
      >
        Feed &amp; dosing · {room}
      </button>
      <span className="feed-cal-sep" aria-hidden="true">
        ›
      </span>
      <h1>{title}</h1>
    </div>
  );

  if (load.state === "missing")
    return (
      <div className="feed-cal">
        <div className="feed-cal-title">
          <h1>Feed pH/EC calibration</h1>
        </div>
        <NeedsIntegration feature="Guided calibration that corrects the feed reading" compact />
        <ProbeCalibration controller={controller} />
      </div>
    );
  if (load.state !== "ready" || !chosen)
    return (
      <div className="feed-cal">
        {header}
        <section className="panel">
          {load.state === "loading" ? (
            <Empty title="Reading the feed probes…" detail="Asking Home Assistant for this room's calibrations." />
          ) : load.state === "error" ? (
            <Empty title="The calibrations could not be read" detail={load.message} action={<Button onClick={() => void read()}>Try again</Button>} />
          ) : (
            <Empty
              title="No feed-water probe is mapped"
              detail="Map the feed pH or EC probe in Rooms and setup to calibrate it here."
              action={<Button onClick={() => navigate("equipment/setup")}>Open Rooms and setup</Button>}
            />
          )}
        </section>
      </div>
    );

  // ---- the live reading
  const series: Reading[] =
    session && Number.isFinite(rawValue) ? [...readings.current.filter((r) => r.at < now), { at: now, value: rawValue }] : [];
  const span = spanOver(series);
  const steady = series.length > 0 && looksSteady(span, kind);
  const heldMs = steadyFor(series, kind);
  const buffer = point !== null ? buffers[point] : "";
  const cap = captureState(Number.isFinite(rawValue) && !silent, steady, { buffer, kind });
  const captured = point !== null && points[point] !== null;
  const ringState: "settling" | "steady" | "offline" = cap.reason ? "offline" : steady ? "steady" : "settling";
  const temp = session?.temperature_entity_id ? controller.states[session.temperature_entity_id] : undefined;
  const tempText = temp && temp.state !== "" && Number.isFinite(Number(temp.state)) ? formatTemp(Number(temp.state), digitsOf(temp.state)) : null;
  const liveText = Number.isFinite(rawValue) ? feedValue(rawValue, kind, digitsOf(raw?.state)) : "—";
  const stabWord = cap.reason
    ? "Offline"
    : steady
      ? "Steady"
      : heldMs >= 1_000 && series.length > 1
        ? `Stable ${Math.floor(heldMs / 1000)} s of 30 s`
        : "Settling…";
  const thresholdText = kind === "ph" ? "±0.01" : "±0.5%";
  const words = result ? verdictWords(result, kind) : null;
  const forcedText = forcedLine(shown?.forced, buffers);

  const details = [
    `${room} feed ${name}`,
    points[0] !== null ? `read ${feedValue(points[0], kind, 2)}` : `buffer ${buffers[0] ?? "1"}`,
    points[1] !== null ? `read ${feedValue(points[1], kind, 2)}` : `buffer ${buffers[1] ?? "2"}`,
    result ? `${GRADES.find((g) => g.verdict === result.verdict)!.word} · response ${result.slope_pct}%` : "slope and offset",
    done?.receipt.ok ? `read back ${clock(done.receipt.at, tz)}` : "raw vs corrected",
  ];
  const railSteps = STEPS.map((t, i) => ({
    title: narrow && (i === 1 || i === 2) && buffers[i - 1] ? `Buffer ${buffers[i - 1]}` : t,
    detail: details[i],
  }));

  const next: { label: string; enabled: boolean; go(): void } | null = expired
    ? null
    : step === 1
      ? { label: busy ? "Starting…" : "Start calibration", enabled: !busy && !admin, go: () => void start(chosen) }
      : step === 2
        ? { label: `Next: rinse, into ${buffers[1]}`, enabled: points[0] !== null && !busy, go: () => goto(3) }
        : step === 3
          ? { label: "Next: see the result", enabled: points[1] !== null && !busy, go: () => goto(4) }
          : step === 4 && result && result.verdict !== "fail"
            ? { label: "Next: apply", enabled: true, go: () => goto(5) }
            : null;
  // On a phone the one button at the bottom captures, then moves on.
  const phonePrimary =
    point !== null && !captured && !expired
      ? {
          label: cap.enabled ? cap.label : cap.reason ? "No probe reading" : "Waiting for a steady reading",
          enabled: cap.enabled && !busy && !admin,
          go: () => void capture(point),
        }
      : next;
  const backOff = step === 1 || busy || !!done || !!failed;
  const back = () => {
    if (step === 2 || expired) {
      // Back to choosing a probe ends the session, so it no longer holds dosing. The stored copy
      // stays until the integration confirms (see abandon).
      abandon(session);
      setSessionState(null);
      setExpired(false);
      setStep(1);
    } else goto(step - 1);
  };

  return (
    <div className="feed-cal" data-step={shownStep}>
      {header}
      <section className="feed-cal-rail panel">
        <StepRail compact={narrow} current={shownStep} steps={railSteps} />
      </section>
      <section className="feed-cal-body panel" aria-label={`Step ${shownStep}: ${STEPS[shownStep - 1]}`}>
        <div className="feed-cal-main">
          {expired ? (
            <div className="feed-cal-expired" role="alert">
              <p>Your last calibration session expired. Start again from buffer 1.</p>
              <Button onClick={startAgain} disabled={busy}>
                Start again
              </Button>
            </div>
          ) : step === 1 ? (
            <>
              {!narrow && <h2 className="feed-cal-step-title">Which probe are you calibrating?</h2>}
              {held && (
                <div className="feed-cal-resume">
                  <span>{`A calibration of the ${room} feed ${NAME_OF[held.kind]} probe is still open.${held.dosing_paused ? ` Dosing for ${room} stays paused until ${clock(Date.parse(held.expires_at), tz)}.` : ` It ends at ${clock(Date.parse(held.expires_at), tz)}.`}`}</span>
                  <Button variant="outline" disabled={busy} onClick={() => void resume(held)}>
                    Resume calibration
                  </Button>
                </div>
              )}
              <div
                className="feed-cal-probes"
                role="radiogroup"
                aria-label="Probe"
                onKeyDown={(e) => {
                  const delta = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 0;
                  if (!delta || probes.length < 2) return;
                  e.preventDefault();
                  const index = (probes.indexOf(chosen) + delta + probes.length) % probes.length;
                  setProbe(probes[index]);
                  e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')[index]?.focus();
                }}
              >
                {probes.map((p) => {
                  const k = KIND_OF[p];
                  const entity = controller.states[doc!.sensors[p]!];
                  const value = entity && entity.state !== "" && Number.isFinite(Number(entity.state)) ? Number(entity.state) : null;
                  // As the integration's calibration_due sensor: the newest check that did not fail.
                  const last = dueState(doc!.records, p);
                  const due = last?.dueAt != null ? dueLine(last.dueAt, Date.now(), tz) : null;
                  const on = p === chosen;
                  return (
                    <button
                      key={p}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      tabIndex={on ? 0 : -1}
                      className="feed-cal-card"
                      data-feed-probe={p}
                      onClick={() => setProbe(p)}
                    >
                      <b>{`${room} feed ${NAME_OF[k]}`}</b>
                      <span>
                        {value === null ? "No reading" : `Reads ${feedValue(value, k, digitsOf(entity?.state))} raw`}
                        {last ? ` · last checked ${shortDate(last.at, tz)}` : " · not checked yet"}
                      </span>
                      {due && (
                        <span className="feed-cal-due" data-due={due.overdue ? "" : undefined}>
                          {due.text}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
              <p>You need the two buffers, clean water and a tissue. About 10 minutes.</p>
              <p className="feed-cal-hint">
                The probe's raw reading is always kept; the correction goes on top as a separate corrected reading, and you can undo it.
              </p>
              {failed && <p className="feed-cal-bad">{failed}</p>}
              {startError && (
                <p className="feed-cal-bad" role="alert">
                  {startError}
                </p>
              )}
              {admin && <p className="feed-cal-hint">{admin}</p>}
            </>
          ) : point !== null && session ? (
            <>
              {!narrow && (
                <h2 className="feed-cal-step-title">{`${point === 0 ? "First" : "Second"} point: ${buffer} buffer`}</h2>
              )}
              <p>{`Rinse the probe, dab it dry and stand it in the ${buffer} buffer. Leave it still; the reading settles by itself.`}</p>
              {narrow ? (
                <div className="feed-cal-ring">
                  <StabilityRing
                    value={liveText}
                    caption={`${name} in ${buffer} buffer`}
                    state={ringState}
                    progress={Math.min(1, heldMs / WINDOW_MS)}
                  />
                  <p>{[cap.reason ? cap.reason : steady ? "Reading is steady" : "Reading is still moving", tempText].filter(Boolean).join(" · ")}</p>
                </div>
              ) : (
                <>
                  <div className="feed-cal-live">
                    <div>
                      <span className="feed-cal-label">Live reading</span>
                      <span className="feed-cal-value" data-live-reading>
                        {liveText}
                      </span>
                      <span className="feed-cal-caption">
                        {`${name} · buffer ${buffer}${tempText ? ` · ${tempText}` : ""}`}
                      </span>
                    </div>
                    <Trace series={series.filter((r) => r.at >= now - TRACE_MS)} kind={kind} now={now} />
                  </div>
                  <div className="feed-cal-stab" data-state={ringState} data-stability>
                    <b>{stabWord}</b>
                    <span className="feed-cal-bar" aria-hidden="true">
                      <span style={{ width: `${(steady ? 1 : Math.min(1, heldMs / WINDOW_MS)) * 100}%` }} />
                    </span>
                    <span>{`Capture unlocks after the reading holds within ${thresholdText} for 30 s.`}</span>
                  </div>
                </>
              )}
              {!narrow && !captured && (
                <Button className="feed-cal-capture" disabled={!cap.enabled || busy || !!admin} onClick={() => void capture(point)}>
                  {cap.label}
                </Button>
              )}
              {cap.reason && !narrow && <p className="feed-cal-bad">{cap.reason}</p>}
              <div className="feed-cal-status" role="status">
                {note?.point === point && (
                  <>
                    <span className={note.kind === "captured" ? "feed-cal-ok" : "feed-cal-bad"}>{note.text}</span>
                    {note.kind === "captured" && (
                      <Button variant="link" size="sm" disabled={busy} onClick={() => void capture(point)}>
                        Read again
                      </Button>
                    )}
                    {note.kind === "moving" && (
                      <details className="feed-cal-more">
                        <summary>More</summary>
                        <Button variant="outline" size="sm" disabled={busy} onClick={() => void capture(point, true)}>
                          Capture anyway
                        </Button>
                      </details>
                    )}
                  </>
                )}
              </div>
              {paused && (
                <p className="feed-cal-hint">{`Dosing for ${room} stays paused until you apply, or until ${clock(Date.parse(session.expires_at), tz)}.`}</p>
              )}
            </>
          ) : step === 4 ? (
            <>
              {!narrow && <h2 className="feed-cal-step-title">Result</h2>}
              {local && "error" in local ? (
                <p className="feed-cal-bad">{local.error}</p>
              ) : result && words ? (
                <>
                  <p className="feed-cal-headline" data-verdict-headline>
                    {words.headline}
                  </p>
                  <ul className="feed-cal-grades" aria-label="Verdict">
                    {GRADES.map((g) => (
                      <li key={g.verdict} data-grade={g.verdict} aria-current={g.verdict === result.verdict ? "true" : undefined}>
                        {g.word}
                      </li>
                    ))}
                  </ul>
                  {forcedText && <p className="feed-cal-bad">{forcedText}</p>}
                  {result.verdict === "fail" ? (
                    <>
                      <p>A failed result is kept in the history but never applied. Clean or replace the probe and calibrate it again.</p>
                      <Button variant="outline" disabled={busy} onClick={() => void recordFail()}>
                        Record the failed check
                      </Button>
                    </>
                  ) : (
                    <p className="feed-cal-hint">The integration checks the two points again when you apply.</p>
                  )}
                </>
              ) : null}
            </>
          ) : step === 5 && (session || done) ? (
            <>
              <ReviewApply
                layout="panel"
                rows={rows}
                applyLabel="Apply calibration"
                checks={admin && !done ? [{ ok: false, text: admin }] : undefined}
                discardLabel="Back to the result"
                onDiscard={() => goto(4)}
                consequence={
                  kind === "ph"
                    ? "The mix check and pH auto-correct will use the corrected value. Raw stays recorded."
                    : "The mix check will use the corrected value. Raw stays recorded."
                }
                apply={apply}
                last={done?.receipt ?? null}
                onReload={() => void read()}
                timeZone={tz}
                undo={undo}
                confirmation="The integration holds this calibration as the one in force"
              />
              {done?.receipt.ok && !done.undone && <Proof done={done} states={controller.states} prefix={prefix} kind={done.session.kind} />}
              {done && (
                <div className="feed-cal-actions">
                  <Button onClick={() => navigate("equipment/dosing")}>Done</Button>
                  {probes.length > 1 && (
                    <Button
                      variant="outline"
                      onClick={() => {
                        setProbe(probes.find((p) => p !== done.session.probe) ?? null);
                        setDone(null);
                        setStep(1);
                      }}
                    >
                      Calibrate the other probe
                    </Button>
                  )}
                </div>
              )}
            </>
          ) : null}
        </div>
        {!narrow && point !== null && !expired && session && <Beaker buffer={buffer} />}
      </section>
      <footer className="feed-cal-foot panel">
        {narrow ? (
          <Button variant="outline" size="icon" aria-label="Back" disabled={backOff} onClick={back}>
            <ChevronLeft aria-hidden />
          </Button>
        ) : (
          <Button variant="outline" disabled={backOff} onClick={back}>
            Back
          </Button>
        )}
        {!narrow && (
          <span className="feed-cal-count">{`Step ${shownStep} of 5${paused ? ` · dosing for ${room} paused` : ""}`}</span>
        )}
        {(narrow ? phonePrimary : next) && (
          <Button
            className="feed-cal-next"
            disabled={!(narrow ? phonePrimary! : next!).enabled}
            onClick={(narrow ? phonePrimary! : next!).go}
          >
            {(narrow ? phonePrimary! : next!).label}
          </Button>
        )}
      </footer>
    </div>
  );
}

/** "Now reads 4.00 in pH 4.00 buffer ✓": the room's corrected sensor, once it uses this calibration. */
function Proof({
  done,
  states,
  prefix,
  kind,
}: {
  done: { session: StoredSession; result: CalibrationCommitResult };
  states: PageProps["controller"]["states"];
  prefix: string;
  kind: FeedKind;
}) {
  const rawDigits = digitsOf(states[done.session.raw_entity_id]?.state);
  const line = proofLine(states, prefix, done.session.probe, done.session.solutions[1], done.result, rawDigits || 2);
  return (
    <p className="feed-cal-proof" data-proof role="status">
      {line ? (
        <>
          <span>{line.text}</span>
          {line.ok ? (
            <span className="feed-cal-ok" role="img" aria-label="within 0.1 of the buffer">
              {" "}
              ✓
            </span>
          ) : (
            <span className="feed-cal-bad">{` — more than ${kind === "ph" ? "0.1" : feedValue(0.1, kind, 1)} off: rinse and check it in the buffer again.`}</span>
          )}
        </>
      ) : (
        "Waiting for the corrected reading…"
      )}
    </p>
  );
}

/** The last minute of the reading, scaled to its own range. */
function Trace({ series, kind, now }: { series: Reading[]; kind: FeedKind; now: number }) {
  if (series.length < 2) return <div className="feed-cal-trace" aria-hidden="true" />;
  const values = series.map((r) => r.value);
  const pad = kind === "ph" ? 0.03 : 0.01 * Math.max(...values.map(Math.abs));
  const lo = Math.min(...values) - pad,
    hi = Math.max(...values) + pad;
  const x = (at: number) => (((at - (now - TRACE_MS)) / TRACE_MS) * 260).toFixed(1);
  const y = (v: number) => (84 - ((v - lo) / (hi - lo || 1)) * 78).toFixed(1);
  // A probe holds its value until it reports again: steps, not slopes.
  const points = series.flatMap((r, i) => (i ? [`${x(r.at)},${y(series[i - 1].value)}`, `${x(r.at)},${y(r.value)}`] : [`${x(r.at)},${y(r.value)}`]));
  return (
    <svg
      className="feed-cal-trace"
      viewBox="0 0 260 90"
      role="img"
      aria-label={`Reading over the last minute: ${feedValue(values[0], kind, 2)} to ${feedValue(values[values.length - 1], kind, 2)}`}
    >
      <line x1="0" x2="260" y1={y(values[values.length - 1])} y2={y(values[values.length - 1])} className="feed-cal-trace-now" />
      <polyline points={points.join(" ")} />
    </svg>
  );
}

/** The probe standing in the buffer. */
function Beaker({ buffer }: { buffer: string }) {
  return (
    <aside className="feed-cal-visual" aria-label={`Probe in the ${buffer} buffer`}>
      <svg viewBox="0 0 240 300" aria-hidden="true">
        <rect className="feed-cal-probe" x="104" y="10" width="32" height="150" rx="8" />
        <path className="feed-cal-liquid" d="M34 140 H206 L198 286 H42 Z" />
        <rect className="feed-cal-tip" x="110" y="160" width="20" height="70" rx="6" />
        <path className="feed-cal-glass" d="M26 110 L42 290 H198 L214 110" />
        <text x="120" y="262" textAnchor="middle">
          {buffer}
        </text>
      </svg>
      <p>Probe tip fully in, not touching the beaker</p>
    </aside>
  );
}
