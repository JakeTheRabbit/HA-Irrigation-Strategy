import { CanonicalControls } from "@/components/canonical-controls";
import { useEffect, useId, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CircleDashed,
  CircleDot,
  CircleStop,
  LoaderCircle,
  Settings2,
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
import { UiTip } from "@/components/info-tip";
import { Pill } from "@/components/mini-visuals";
import { PeristalticPump } from "@/components/peristaltic-pump";
import { HoldButton } from "@/components/primitives/hold-button";
import { StockBottle } from "@/components/stock-bottle";
import { DosingSetup } from "@/components/dosing-setup";
import { TankLevel } from "@/components/tank-level";
import { TankStatus } from "@/components/tank-status";
import {
  PUMP_STATES,
  STOCK_STATES,
  batchLevel,
  batchSteps,
  batchTime,
  blankPump,
  canEdit,
  controllerReach,
  doseDeadline,
  exceedsDoseLimit,
  dosingConfigId,
  dosingError,
  dosingStatusId,
  hardwareLabel,
  leftWords,
  levelFall,
  levelFallUnknown,
  mixChecked,
  nextBatch,
  protections,
  pumpStock,
  pumpView,
  parseConfig,
  readConfig,
  readStatus,
  recipeInUse,
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
  type DosingRequest,
  type DosingRequestResult,
  type MixCheck,
  type NextBatch,
  type RecipeRow,
  type PumpStock,
  type PumpView,
  type SetupDraft,
  type StepView,
} from "@/lib/dosing";
import { formatEc, formatVolume, useDisplayUnits } from "@/lib/display-units";
import { descriptor, numeric } from "@/lib/model";
import { reservoirView, type ReservoirView } from "@/lib/reservoir";
import type { StockDocument } from "@/lib/stock";
import { clock, dayKey, dayLabel } from "@/lib/time";
import type { Controller, States } from "@/lib/types";
import { errorText } from "@/lib/utils";
import "./dosing.css";

const mL = (value: number) =>
  value.toLocaleString(undefined, { maximumFractionDigits: value < 100 ? 1 : 0 });
const seconds = (value: number) =>
  value < 100 ? `${number(value, 1)} s` : `${number(value / 60, value < 600 ? 1 : 0)} min`;
/** A time on Home Assistant's clock: "14:06" today, "Sat 25 Oct 09:00" on another day. */
const at = (ms: number, now: number, tz: string) =>
  dayKey(ms, tz) === dayKey(now, tz) ? clock(ms, tz) : `${dayLabel(ms, tz)} ${clock(ms, tz)}`;
const when = (iso: string | null, now: number, tz: string) => {
  const ms = Date.parse(iso ?? "");
  return Number.isFinite(ms) ? at(ms, now, tz) : "time not reported";

};
const PH = (value: number) => value.toFixed(2);
/** A litre figure with the display unit, never finer than the source's one decimal. */
const litres = (value: number) => formatVolume(value, 1);

/** Re-renders every `ms` while `active`: a running dose's progress moves between reports. */
function useTicker(active: boolean, ms = 500) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setTick((tick) => tick + 1), ms);
    return () => clearInterval(timer);
  }, [active, ms]);
}

type RecordedLevel = {
  state: "loading" | "failed" | "loaded";
  points: { time: number; value: number }[];
};
/** The tank level's last day as the recorder holds it (the level chart's own source), read once per
 * room: how fast the tank falls comes from it. "loading" until it loads, "failed" when it cannot. */
function useRecordedLevel(controller: Controller, levelId: string | null): RecordedLevel {
  const [recorded, setRecorded] = useState<RecordedLevel>({ state: "loading", points: [] });
  const ready = ["live", "demo"].includes(controller.connection);
  const load = controller.timeline;
  useEffect(() => {
    setRecorded({ state: "loading", points: [] });
    if (!levelId || !ready) return;
    let current = true;
    const end = Date.now();
    load({ entityIds: [levelId], attributeIds: [], start: end - 24 * 3_600_000, end })
      .then((rows) => {
        if (!current) return;
        setRecorded({
          state: "loaded",
          points: (rows[levelId] ?? []).flatMap((row) => {
            const value = Number(row.state);
            return row.state.trim() && Number.isFinite(value) ? [{ time: row.time, value }] : [];
          }),
        });
      })
      .catch(() => current && setRecorded({ state: "failed", points: [] }));
    return () => {
      current = false;
    };
  }, [levelId, ready, load, controller.roomId]);
  return recorded;
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
          <UiTip copyKey="back" />
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

/** A dosing pump in the plumbing: its stock bottle to scale (`largest`: the room's largest linked
 * tank), the litres left, its flow and state, and its head, which chooses it for a dose by hand. */
function PlumbPump({
  view,
  index,
  selected,
  onSelect,
  stock,
  largest,
}: {
  view: PumpView;
  index: number;
  selected: boolean;
  onSelect: () => void;
  stock: PumpStock | null;
  largest: number;
}) {
  const { pump, progress } = view;
  const pill = PUMP_STATES[view.state];
  const tank = stock?.tank ?? null;
  return (
    <li
      className="plumb-pump"
      data-dosing-pump={pump.id}
      data-state={view.state}
      data-selected={selected || undefined}
      data-hue={index % 8}
    >
      {tank && stock ? (
        <div className="plumb-stock" data-pump-stock={tank.id} data-level={stock.state}>
          <StockBottle
            tank={tank}
            state={stock.state}
            scale={largest > 0 ? Math.cbrt(tank.capacity_l / largest) : 1}
            label={`${tank.name} stock tank: ${litres(tank.level_l)} of ${litres(tank.capacity_l)}, low mark ${litres(tank.low_l)}`}
          />
          <p className="dosing-stock-lines">
            {tank.name.toLowerCase() !== pump.name.toLowerCase() && (
              <span className="dosing-stock-name">{tank.name}</span>
            )}
            <span className="dosing-stock-litres">
              {formatVolume(tank.level_l, 1).replace(/ (L|gal)$/, "")} /{" "}
              {formatVolume(tank.capacity_l, 1)}
            </span>
            {stock.state !== "ok" && (
              <span className="dosing-stock-state">{STOCK_STATES[stock.state].toLowerCase()}</span>
            )}
            {stock.left && <span className="dosing-stock-left">{leftWords(stock.left)}</span>}
          </p>
        </div>
      ) : (
        <p className="plumb-stock dosing-stock-none" data-pump-stock="">
          {stock ? `Stock tank ${stock.id} not found` : "No stock tank linked"}
        </p>
      )}
      <div className="plumb-pump-head">
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
        <span className="plumb-flow">
          {view.flow === null ? "flow not read" : `${number(view.flow * 60, 1)} mL/min`}
        </span>
        <Pill tone={pill.tone} dot={view.state === "dosing"}>
          {pill.label}
        </Pill>
      </div>
      <div className="plumb-pump-art">
        <PeristalticPump state={view.state} label={`${pump.name}: ${pill.label.toLowerCase()}`} />
      </div>
      {progress && (
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
      )}
      {view.reason && view.state !== "idle" && <p className="dosing-reason">{view.reason}</p>}
    </li>
  );
}

/** A guard on the plumbing, armed (a check) or not (a cross). */
function Mark({
  item,
  children,
}: {
  item: { label: string; ok: boolean };
  children?: React.ReactNode;
}) {
  return (
    <p className="plumb-mark" data-protection={item.ok ? "armed" : "off"}>
      {item.ok ? (
        <Check size={15} role="img" aria-label="Armed" />
      ) : (
        <X size={15} role="img" aria-label="Not armed" />
      )}
      <span>{item.label}</span>
      {children}
    </p>
  );
}

/** A reading against its band: the band drawn, the reading a tick across it. */
function BandGauge({
  name,
  value,
  low,
  high,
  text,
}: {
  name: string;
  value: number | null;
  low: number | null;
  high: number | null;
  text: (value: number) => string;
}) {
  const ends = [value, low, high].filter((v): v is number => v !== null && v > 0);
  const min = Math.min(...ends) * 0.85,
    max = Math.max(...ends) * 1.1;
  const x = (v: number) => `${((v - min) / (max - min || 1)) * 100}%`;
  const off =
    value !== null &&
    ((low !== null && low > 0 && value < low) || (high !== null && high > 0 && value > high));
  return (
    <div className="mix-gauge" data-mix-gauge={name} data-off={off || undefined}>
      <span className="mix-gauge-name">
        {name} <b>{value === null ? "not read" : text(value)}</b>
      </span>
      <span
        className="mix-gauge-track"
        role="img"
        aria-label={`${name} ${value === null ? "not read" : text(value)}, band ${low ? text(low) : "no minimum"} to ${high ? text(high) : "no maximum"}`}
      >
        {ends.length > 0 && (
          <>
            <i
              className="mix-gauge-band"
              style={{
                left: x(low && low > 0 ? low : min),
                right: `calc(100% - ${x(high && high > 0 ? high : max)})`,
              }}
            />
            {value !== null && <i className="mix-gauge-tick" style={{ left: x(value) }} />}
          </>
        )}
      </span>
    </div>
  );
}

const MIX_TITLE = {
  "off target": "Mix check failed",
  "not read": "Mix check could not read the tank",
};
const PROBE_NAMES = { ec: "EC", ph: "pH" } as const;

/** The last batch's mix check, in place beside the tank, when it did not pass: both readings on
 * their bands, why, and a hold to make a batch that fills, mixes and checks again. Making a batch is
 * the only way on: no service releases a failed check. */
export function MixCheckCard({
  mix,
  states,
  prefix,
  calibration,
  now,
  tz,
  block,
  room,
  warning,
  onTopUp,
  error,
}: {
  mix: MixCheck;
  states: States;
  prefix: string;
  /** When each feed probe was last calibrated (engine_config `feed_calibration`), null when never. */
  calibration: { ec: number | null; ph: number | null };
  now: number;
  tz: string;
  block: string | null;
  /** The room's name: watering in it is held while the batch runs. */
  room: string;
  /** A dosed pump that is not ready: the controller would refuse the batch. */
  warning: string | null;
  onTopUp: () => void;
  error: string;
}) {
  const id = useId();
  const band = (quantity: "ec" | "ph", end: "min" | "max") =>
    numeric(states[`number.crop_steering_${prefix}irrigation_${quantity}_${end}`]);
  const ec = { low: band("ec", "min"), high: band("ec", "max") };
  const ph = { low: band("ph", "min"), high: band("ph", "max") };
  const ecText = (v: number) => formatEc(v, 2);
  const outside = (v: number | null, b: { low: number | null; high: number | null }) =>
    v !== null &&
    ((b.low !== null && b.low > 0 && v < b.low) || (b.high !== null && b.high > 0 && v > b.high));
  const range = (b: { low: number | null; high: number | null }, text: (v: number) => string) =>
    b.low && b.low > 0 && b.high && b.high > 0
      ? `${text(b.low).replace(/ \S+$/, "")}–${text(b.high)}`
      : b.low && b.low > 0
        ? `at least ${text(b.low)}`
        : `at most ${text(b.high ?? 0)}`;
  const wanted = [
    outside(mix.ec, ec) && `Want EC ${range(ec, ecText)}; it read ${ecText(mix.ec!)}.`,
    outside(mix.ph, ph) && `Want pH ${range(ph, PH)}; it read ${PH(mix.ph!)}.`,
  ].filter(Boolean);
  // What the controller could not read, in its own words; an off-band reading is said above, in
  // display units.
  const unread =
    mix.verdict === "off target"
      ? null
      : (mix.why ?? "")
          .split("; ")
          .filter((part) => part && !/ outside the feed /.test(part))
          .join("; ") || null;
  // The probe behind each failure: one off its band, or one that read nothing. A probe the check
  // did not cover is not drawn.
  const probes = mix.probes.filter((quantity) => {
    const value = mix[quantity];
    return value === null
      ? mix.verdict !== "off target"
      : outside(value, quantity === "ec" ? ec : ph);
  });
  const checked = Date.parse(mix.checked_at ?? mix.gave_up_at ?? "");
  const title = mix.gave_up_at
    ? "Mix check not done"
    : MIX_TITLE[mix.verdict as keyof typeof MIX_TITLE];
  const ago = (ms: number) => {
    const days = Math.floor((now - ms) / 86_400_000);
    return days === 0 ? "today" : `${days} ${days === 1 ? "day" : "days"} ago`;
  };
  return (
    <section
      className="plumb-mix"
      aria-labelledby={id}
      data-mix-check={mix.gave_up_at ? "not done" : mix.verdict}
    >
      <h3 id={id}>
        {title}
        {Number.isFinite(checked) && ` ${at(checked, now, tz)}`}
      </h3>
      {mix.probes.includes("ec") && (
        <BandGauge name="EC" value={mix.ec} low={ec.low} high={ec.high} text={ecText} />
      )}
      {mix.probes.includes("ph") && (
        <BandGauge name="pH" value={mix.ph} low={ph.low} high={ph.high} text={PH} />
      )}
      <p className="plumb-mix-why">
        {[
          ...wanted,
          unread
            ? `The controller could not judge the tank: ${unread}.`
            : wanted.length
              ? null
              : "The controller could not judge the tank.",
        ]
          .filter(Boolean)
          .join(" ")}{" "}
        The shots continue. The controller refuses a batch an automation asks for until a batch made
        by hand passes this check.
      </p>
      <HoldButton
        mode="hold-to-confirm"
        label="Top up and re-check"
        srLabel="Hold for 1.5 seconds: the controller makes a batch, which fills, mixes and checks the tank again."
        maxSeconds={5}
        disabledReason={block ?? undefined}
        onStart={onTopUp}
      />
      <p className="muted small">
        {warning ? `${warning} ` : ""}
        While the batch runs, watering in {room}, and in any room whose pump or valves the batch uses,
        is held.
      </p>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {probes.map((quantity) => {
        const ms = calibration[quantity];
        return (
          <p className="plumb-mix-cal" key={quantity} data-mix-probe={quantity}>
            {ms === null ? (
              <a href="#/equipment/feed-calibration">
                Calibrate the feed {PROBE_NAMES[quantity]} probe
              </a>
            ) : (
              <>
                Feed {PROBE_NAMES[quantity]} probe calibrated {ago(ms)} ·{" "}
                <a href="#/equipment/feed-calibration">calibrate</a>
              </>
            )}
          </p>
        );
      })}
    </section>
  );
}

/** The tank minimum on the drawing: its mark, and what it is doing when it holds watering. */
export function GuardMark({
  guard,
  item,
  onConfigure,
}: {
  guard: ReservoirView;
  item: { label: string; ok: boolean };
  onConfigure: () => void;
}) {
  return (
    <div className="plumb-guard" data-reservoir-guard={guard.state}>
      <Mark item={item} />
      {guard.state === "ok" ? (
        <p className="plumb-guard-line">
          {guard.label}
          {guard.marks.release !== null && ` · starts again at ${guard.marks.release}%`}
          {guard.aboveMinimumL !== null && ` · about ${litres(guard.aboveMinimumL)} above it`}
          {guard.litresPerPct !== null
            ? ` · ${litres(guard.litresPerPct)} per 1%`
            : " · litres per 1% not learned yet, so no shot waits ahead of the minimum"}
        </p>
      ) : (
        <div className="plumb-guard-problem" role="status">
          <Pill dot tone={guard.tone}>
            {guard.label}
          </Pill>
          {guard.code && <a href={`#/help?code=${guard.code}`}>{guard.code}</a>}
          <p>{guard.detail}</p>
          {guard.state === "unmapped" && (
            <Button variant="ghost" size="sm" onClick={onConfigure}>
              <Settings2 size={16} /> Map the tank level
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** Feed recipes by flower week: the weeks coloured by recipe, this week marked, then each recipe. */
function FeedRecipes({
  doc,
  room,
  ec,
}: {
  doc: DosingDocument | null;
  room: string;
  ec: (v: number) => string;
}) {
  const feed = doc?.config?.feed;
  const now = doc?.feed_now ?? null;
  const pumps = doc?.config?.pumps ?? [];
  const recipes = feed?.recipes ?? [];
  const weeks = feed?.schedule.weeks ?? [];
  const order = (id: string) => recipes.findIndex((recipe) => recipe.id === id);
  const ranges = (id: string) => {
    const out: string[] = [];
    weeks.forEach((week, i) => {
      if (week !== id || weeks[i - 1] === id) return;
      let end = i;
      while (weeks[end + 1] === id) end++;
      out.push(end > i ? `Wk ${i + 1}–${end + 1}` : `Wk ${i + 1}`);
    });
    return out.join(", ");
  };
  const name = (pump: string) => pumps.find((item) => item.id === pump)?.name ?? pump;
  return (
    <section className="panel feed-recipes" aria-labelledby="feed-recipes-title" data-feed-recipes>
      <div className="panel-heading">
        <div>
          <h2 id="feed-recipes-title">Feed recipes</h2>
          {now?.week && (
            <p>
              by flower week · {room} is in week {now.week}
            </p>
          )}
        </div>
      </div>
      {recipes.length ? (
        <>
          {weeks.length > 0 && (
            <ol className="feed-weeks" aria-label="Weeks of the feed schedule">
              {weeks.map((id, i) => (
                <li
                  key={i}
                  data-week={i + 1}
                  data-recipe-hue={order(id) % 8}
                  data-past={now?.week && i + 1 < now.week ? true : undefined}
                  aria-current={now?.week === i + 1 ? "step" : undefined}
                >
                  Wk {i + 1}
                </li>
              ))}
            </ol>
          )}
          <ul className="feed-recipe-list">
            {recipes.map((recipe, i) => (
              <li
                key={recipe.id}
                data-feed-recipe={recipe.id}
                data-recipe-hue={i % 8}
                data-now={now?.recipe_id === recipe.id || undefined}
              >
                <strong>{recipe.name}</strong>
                <span className="feed-recipe-weeks">{ranges(recipe.id) || "not scheduled"}</span>
                <span className="feed-recipe-mix">
                  {[
                    recipe.ec !== null ? `EC ${ec(recipe.ec)}` : null,
                    ...recipe.doses.map((dose) => `${name(dose.pump)} ${mL(dose.ml)} mL`),
                  ]
                    .filter(Boolean)
                    .join(" · ") || "water only"}
                  {!recipe.doses.length && recipe.ec !== null && " · water only"}
                </span>
                {now?.recipe_id === recipe.id && (
                  <span className="feed-recipe-now">
                    {now.source === "held"
                      ? "Picked by hand"
                      : now.source === "hand"
                        ? "In use"
                        : "This week"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="muted feed-recipes-none">
          No feed recipes in {room}: each batch doses the batch recipe in the dosing setup.
        </p>
      )}
    </section>
  );
}

/** The batch's doses on the drawing: each pump's amount and time, a pump the batch passes by, a
 * line that names no pump of this room, and an amount read from an entity (or not read). */
export function BatchDoses({ rows }: { rows: RecipeRow[] }) {
  return (
    <ul className="plumb-doses">
      {rows.map((row) => (
        <li key={row.pump} data-recipe-pump={row.pump} data-skipped={row.skipped || undefined}>
          <span>
            {row.name}
            {(row.fromEntity || row.unreadable) && (
              <small>
                from {row.entity}
                {row.unreadable ? ", which reads nothing" : ""}
              </small>
            )}
            {row.unknown && <small>not a pump of this room</small>}
          </span>
          <b>
            {row.unreadable ? "?" : row.skipped ? "passed by" : `${mL(row.ml)} mL`}
            {!row.skipped && ` · ${row.seconds === null ? "? s" : seconds(row.seconds)}`}
          </b>
        </li>
      ))}
    </ul>
  );
}

const STEP_NAMES: Record<NextBatch["steps"][number]["name"], string> = {
  premix: "premix",
  dose: "dose",
  postmix: "postmix",
  check: "check",
};

export function NextBatchCard({
  next,
  atPct,
  why,
  now,
  tz,
  navigate,
}: {
  next: NextBatch;
  atPct: number | null;
  /** Why no time is known (levelFallUnknown). */
  why: string;
  now: number;
  tz: string;
  navigate: (page: Page) => void;
}) {
  const total = next.steps.reduce((sum, step) => sum + step.min, 0);
  return (
    <section className="panel next-batch" aria-labelledby="next-batch-title" data-next-batch>
      <div className="panel-heading">
        <div>
          <h2 id="next-batch-title">Next batch</h2>
          <p>
            {atPct === null
              ? "when the tank reaches its minimum (the controller does not report it)"
              : `when the tank reaches ${atPct}%`}
          </p>
        </div>
      </div>
      <div className="next-batch-body">
        <p className="next-batch-when" data-next-batch-at={next.at ?? ""}>
          {next.at === null
            ? why
            : next.at <= now
              ? "Now: the tank is at that level"
              : `${dayLabel(next.at, tz)}, about ${clock(next.at, tz)}`}
        </p>
        <p className="next-batch-what">
          {[
            next.litres !== null ? `about ${litres(next.litres)}` : null,
            ...next.doses.map((dose) => `${dose.name} ${mL(dose.ml)} mL`),
          ]
            .filter(Boolean)
            .join(" · ") || "Nothing to dose"}
        </p>
        {total > 0 && (
          <>
            <div className="next-batch-bar" aria-hidden="true">
              {next.steps.map((step) => (
                <i key={step.name} data-step={step.name} style={{ flexGrow: step.min }} />
              ))}
            </div>
            <p className="next-batch-steps">
              After the fill:{" "}
              {next.steps.map((step) => `${STEP_NAMES[step.name]} ${step.min} min`).join(" · ")}
            </p>
          </>
        )}
        {next.stockWarning && (
          <p className="next-batch-warning" data-stock-warning>
            <AlertTriangle size={16} aria-hidden="true" /> {next.stockWarning}{" "}
            <a href="#/equipment/stock">Stock tanks</a>
          </p>
        )}
        <div className="next-batch-actions">
          <Button variant="outline" onClick={() => navigate("equipment/pump-calibration")}>
            Calibrate a pump
          </Button>
          <Button variant="outline" onClick={() => navigate("equipment/feed-calibration")}>
            Calibrate feed pH/EC
          </Button>
        </div>
      </div>
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
  useDisplayUnits(controller);
  const [setupDirty, setSetupDirty] = useState(false);
  const [permissionsDirty, setPermissionsDirty] = useState(false);
  useEffect(() => {
    onDirtyChange(setupDirty || permissionsDirty);
    return () => onDirtyChange(false);
  }, [setupDirty, permissionsDirty, onDirtyChange]);
  const { room, states } = controller;
  const tz = controller.timeZone;
  const prefix = room.room.prefix;
  const formId = useId();
  const [doc, setDoc] = useState<DosingDocument | null>(null);
  const [stock, setStock] = useState<StockDocument | null>(null);
  const [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [amount, setAmount] = useState("25");
  const [review, setReview] = useState<RequestReview | null>(null);
  const [draft, setDraft] = useState<SetupDraft | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const [reads, setReads] = useState(0);
  const [topUpError, setTopUpError] = useState("");
  // A Top up hold sent and not yet on the controller's request line: true while sending, then the
  // request's id until the line shows it.
  const [topUpSent, setTopUpSent] = useState<string | true | null>(null);
  const connected = ["live", "demo"].includes(controller.connection);
  useEffect(() => {
    setDoc(null);
    setStock(null);
    setLoadError("");
    setTopUpError("");
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
    // What one batch takes from each stock tank: the next batch's warning. Without it, none.
    controller
      .operator<StockDocument>("stock_get")
      .then((result) => current && setStock(result.error ? null : result))
      .catch(() => current && setStock(null));
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
  const views = (config?.pumps ?? []).map((pump) => pumpView(pump, status, reach, states, now, config!.profile));
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
  // Each pump's stock tank, by its stock_tank: the drawing shows theirs to scale against the largest.
  const tanks = stockTanks(states, prefix);
  const stocks = views.map((item) => pumpStock(item.pump, tanks, rows, item.last));
  const largest = Math.max(
    0,
    ...stocks.flatMap((item) => (item?.tank ? [item.tank.capacity_l] : [])),
  );

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
  const configure = () => navigate("equipment/setup");

  // The dose form.
  const ml = amount.trim() === "" ? Number.NaN : Number(amount);
  const max = view?.pump.max_ml ?? 0;
  const profile = (config ?? parseConfig({})!).profile;
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
                    : expected !== null && exceedsDoseLimit(expected, profile)
                      ? `That dose would take ${seconds(expected)}: the controller refuses a dose longer than ${seconds(profile.max_dose_s)} in this room.`
                      : null;
  const reviewDose = () => {
    if (!view || !validMl) return;
    setReview({
      title: `Dose ${view.pump.name}?`,
      rows: [
        { label: "Pump", value: `${view.pump.name} (${hardwareLabel(view.pump)})` },
        { label: "Quantity", value: `${mL(ml)} mL, into the tank as it is` },
        {
          label: "Expected time",
          value: expected
            ? `about ${seconds(expected)} at ${number(view.flow, 2)} mL/s`
            : "unknown: the flow reads nothing",
        },
        {
          label: "How it stops",
          value: expected
            ? `by itself: the pump times the dose. Still running after ${seconds(doseDeadline(expected, profile.max_dose_s))}, its power is switched off.`
            : "by itself: the pump times the dose.",
        },
      ],
      note: "The shots continue while a single dose runs.",
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
  // Top up and re-check: held for 1.5 s, the controller makes a batch at once (no review: the hold
  // is the confirmation). The request line then follows it.
  const topUp = () => {
    setTopUpError("");
    setTopUpSent(true);
    controller
      .operator<DosingRequestResult>("dosing_request", { action: "batch" })
      .then((result) => {
        if (result.error) setTopUpError(dosingError(result.error));
        setTopUpSent(result.error ? null : (result.request?.id ?? null));
      })
      .catch((err) => {
        setTopUpError(errorText(err));
        setTopUpSent(null);
      });
  };
  const sentId = stage?.request.id ?? null;
  useEffect(() => {
    if (typeof topUpSent === "string" && (sentId === topUpSent || batchRunning)) setTopUpSent(null);
  }, [topUpSent, sentId, batchRunning]);

  const current = steps.find((step) => step.state === "running");
  const dosingNow = views.find((item) => item.state === "dosing");
  const lastBatch = status?.history.find((entry) => entry.kind === "batch");
  // "finished 14:00", "stopped 16:10 (stop requested during fill the tank)".
  const lastBatchWords = lastBatch
    ? (() => {
        const [head, ...reason] = lastBatch.result.split(":");
        return `${head.trim().toLowerCase() || "ended"} ${when(lastBatch.ended_at ?? lastBatch.at, now, tz)}${reason.length ? ` (${reason.join(":").trim()})` : ""}`;
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

  // The plumbing's facts.
  const guard = reservoirView(states, prefix);
  const armed = config
    ? protections(
        { schema_version: 1, room_id: controller.roomId, config, candidates: [], error: null },
        states,
      )
    : [];
  const armedCount = armed.filter((item) => item.ok).length;
  const fillValve = config?.batch.fill_valve ? states[config.batch.fill_valve] : undefined;
  const engine = descriptor(states, room.room)?.attributes ?? {};
  const calibratedAt = (quantity: "ec" | "ph") => {
    const record = (
      engine.feed_calibration as Record<string, { calibrated_at?: string }> | undefined
    )?.[quantity];
    const ms = Date.parse(record?.calibrated_at ?? "");
    return Number.isFinite(ms) ? ms : null;
  };
  const mix = status?.mix ?? null;
  const failed =
    !!mix &&
    !batchRunning &&
    (mix.verdict === "off target" || mix.verdict === "not read" || !!mix.gave_up_at);
  const feedNow = doc?.feed_now ?? null;
  const inUse = doc ? recipeInUse(doc) : { name: null, lines: [] };
  const started = Date.parse(status?.batch.started_at ?? "");
  // The next batch: made when the tank reaches its refill reminder, else its minimum, timed from the
  // level that mark is on.
  const level = batchLevel(states, prefix);
  const atPct = level.atPct;
  const recorded = useRecordedLevel(controller, config ? level.entityId : null);
  // The recorded level, then the level it reads now: a level that has held since its last change
  // still counts the time it held.
  const points = [
    ...recorded.points,
    ...(level.pct !== null ? [{ time: now, value: level.pct }] : []),
  ];
  const fall = levelFall(points);
  const next =
    doc && config
      ? nextBatch({ ...doc, config: { ...doc.config, ...config } }, stock, now, {
          states,
          levelPct: level.pct,
          litresPerPct: guard.litresPerPct,
          pctPerHour: fall,
          atPct,
          checks: mixChecked(states, prefix, engine),
        })
      : null;
  const ec = (value: number) => formatEc(value, 2);

  return (
    <div className="dosing-page">
      <Heading
        title={`Feed & dosing · ${room.room.name}`}
        description={
          config
            ? `Batch tank, ${views.length} dosing ${views.length === 1 ? "pump" : "pumps"}, ${room.zones.length} ${room.zones.length === 1 ? "zone" : "zones"}${armed.length ? ` · protections armed ${armedCount} of ${armed.length}` : ""}`
            : undefined
        }
        action={
          config && (
            <Button variant="outline" onClick={() => openSetup(false)}>
              Dosing setup
            </Button>
          )
        }
      />
      <CanonicalControls
        controller={controller}
        owner="dosing"
        onDirtyChange={setPermissionsDirty}
      />
      {loadError && !config && (
        <Empty
          title="Dosing not available"
          detail={`${loadError} Dosing needs the Crop Steering integration and controller app with batch-tank dosing.`}
        />
      )}
      {loadError && config && (
        <p className="workspace-message error" role="alert">
          {loadError}
        </p>
      )}
      {loading && <p className="muted">Loading dosing…</p>}
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
            ? `Sent at ${when(stage.request.at, now, tz)}: ${describe(stage.request)}. Waiting for the controller to take it…`
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
      {/* The plumbing: stock and pumps into the tank, the fill, the guards and the mix check, in
          place. The tank and its minimum show also while dosing itself is unavailable. */}
      <section
        className="panel plumbing"
        aria-label={`${room.room.name} feed plumbing`}
        data-plumbing
      >
        {config && !!views.length && (
          <div className="plumb-top">
            <div className="plumb-pumps-wrap">
              <h2 id={`${formId}-pumps`} className="sr-only">
                Dosing pumps
              </h2>
              <ul className="plumb-pumps" aria-labelledby={`${formId}-pumps`}>
                {views.map((item, index) => (
                  <PlumbPump
                    key={item.pump.id}
                    view={item}
                    index={index}
                    selected={item.pump.id === view?.pump.id}
                    onSelect={() => setSelected(item.pump.id)}
                    stock={stocks[index]}
                    largest={largest}
                  />
                ))}
              </ul>
              {armed[0] && <Mark item={armed[0]} />}
            </div>
            <section
              className="plumb-batch"
              aria-labelledby={`${formId}-batch-card`}
              data-batch-card
            >
              <h2 id={`${formId}-batch-card`}>
                Batch{" "}
                <span>
                  {[
                    inUse.name ?? feedNow?.recipe,
                    feedNow?.week ? `week ${feedNow.week}` : null,
                    batchRunning && Number.isFinite(started)
                      ? `started ${at(started, now, tz)}`
                      : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </h2>
              <BatchDoses rows={rows} />
              {feedNow?.ec ? <p className="plumb-target">Target EC {ec(feedNow.ec)}</p> : null}
              <p className="plumb-batch-line" data-batch-line>
                {batchLine}
              </p>
            </section>
          </div>
        )}
        {/* No pumps to draw: the last batch is still said. */}
        {config && !views.length && status && (
          <p className="plumb-batch-line" data-batch-line>
            {batchLine}
          </p>
        )}
        <div className="plumb-main">
          {config && (
            <div className="plumb-fill" data-fill-valve>
              <h3>Fill valve</h3>
              <p>
                {!config.batch.fill_valve
                  ? "None: the tank is filled by hand"
                  : !fillValve || ["unknown", "unavailable"].includes(fillValve.state)
                    ? "Not read"
                    : `${fillValve.state === "on" ? "Open" : "Closed"} · ${when(fillValve.last_changed ?? null, now, tz)}`}
              </p>
              {armed[4] && <Mark item={armed[4]} />}
            </div>
          )}
          <div className="plumb-tank">
            {armed[1] && <Mark item={armed[1]} />}
            <TankStatus controller={controller} onConfigure={configure} />
            <GuardMark
              guard={guard}
              item={armed[2] ?? { label: guard.minimum === null ? "Minimum" : `Minimum ${guard.minimum}%`, ok: guard.level !== null }}
              onConfigure={configure}
            />
            {armed[3] && <Mark item={armed[3]} />}
          </div>
          {config && failed && mix && (
            <MixCheckCard
              mix={mix}
              states={states}
              prefix={prefix}
              calibration={{ ec: calibratedAt("ec"), ph: calibratedAt("ph") }}
              now={now}
              tz={tz}
              block={
                topUpSent
                  ? "Sending the batch request."
                  : (batchBlock ?? (canAct ? null : "The controller cannot take a request now."))
              }
              room={room.room.name}
              warning={batchWarning}
              onTopUp={topUp}
              error={topUpError}
            />
          )}
        </div>
      </section>
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
        <div className="dosing-lower">
          <FeedRecipes doc={doc} room={room.room.name} ec={ec} />
          {next && (
            <NextBatchCard
              next={next}
              atPct={atPct}
              why={levelFallUnknown(level.pct !== null, recorded.state, points)}
              now={now}
              tz={tz}
              navigate={navigate}
            />
          )}
        </div>
      )}
      {config && !!views.length && (
        <div className="dosing-work">
          {view && (
            <section
              className="panel dosing-panel dosing-dose"
              aria-labelledby={`${formId}-dose`}
              data-hue={views.indexOf(view) % 8}
            >
              <div className="dosing-panel-head">
                <span className="eyebrow">
                  Dose by hand · <span className="dosing-mono">{hardwareLabel(view.pump)}</span>
                </span>
                <h2 id={`${formId}-dose`}>Dose {view.pump.name}</h2>
              </div>
              <form
                className="dosing-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!doseBlock) reviewDose();
                }}
              >
                <div className="dosing-field">
                  <span className="label-with-tip">
                    <Label htmlFor={`${formId}-ml`}>Quantity (mL)</Label>
                    <UiTip copyKey="amount (ml)" />
                  </span>
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
                  {doseBlock ??
                    "Choose the pump on the drawing. The pump must be idle. You review the dose before it is sent."}
                </p>
              </form>
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
          )}
          <section className="panel dosing-batch" aria-labelledby={`${formId}-batch`}>
            <div className="panel-heading">
              <div>
                <h2 id={`${formId}-batch`}>Make a batch</h2>
                <p data-batch-time>
                  Expected time: {expectedBatch}, with {config.batch.premix_min} min of mixing
                  before dosing and {config.batch.postmix_min} min after.
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
                  <>
                    <Button disabled={!!batchBlock || !canAct} onClick={reviewBatch}>
                      Make a batch
                    </Button>
                    <UiTip copyKey="make a batch" />
                  </>
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
          </section>
        </div>
      )}
      {config && !!views.length && (
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
                      <td>{when(entry.at, now, tz)}</td>
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
      )}
      {/* The tank's level over time, with the shots, pump runs and fills that moved it. */}
      <TankLevel controller={controller} onConfigure={configure} />
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
            onDirtyChange={setSetupDirty}
          />
        </details>
      )}
      <RequestDialog controller={controller} review={review} onClose={() => setReview(null)} />
    </div>
  );
}
