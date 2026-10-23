import { stockConfigurationPayload } from "@/lib/stock";
import { useEffect, useId, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";
import { FlaskConical, Pencil, Plus, Trash2, TriangleAlert } from "lucide-react";
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
import {
  MIN_BOTTLE,
  StockBottle,
  bottleSize,
  bottleTop,
  percentTop,
} from "@/components/stock-bottle";
import {
  dosingConfigId,
  dosingStatusId,
  leftWords,
  pumpDraw,
  readConfig,
  readStatus,
  recipeRows,
  stockLeft,
  stockState,
  STOCK_STATES,
  type StockDraw,
} from "@/lib/dosing";
import { formatVolume, getDisplayUnits } from "@/lib/display-units";
import { useParity } from "@/lib/parity-api";
import type { CsEvent } from "@/lib/parity-types";
import {
  batchEveryDays,
  draftErrors,
  nextToRunOut,
  refillRows,
  stockOutlook,
  stockShare,
  undoRefill,
  weeklyUse,
  weeksShown,
  type StockBatch,
  type StockDocument,
  type StockTank,
  type StockTankDraft,
} from "@/lib/stock";
import { clock, dayLabel, shortDate } from "@/lib/time";
import type { Controller } from "@/lib/types";
import { LITRES_PER_US_GALLON } from "@/lib/units";
import { offerUndo } from "@/lib/undo";
import { errorText, sameValue } from "@/lib/utils";
import "./stock.css";

const SOURCES: Record<StockBatch["source"], string> = {
  fill: "Tank fill",
  manual: "By hand",
  pump: "Pump ran",
  dose: "Dose",
  batch: "Batch",
};
/** The integration keeps this many draws (stock.py HISTORY): a full history may start mid-week. */
const HISTORY_KEPT = 30;
const WEEKS_SHOWN = 8;
/** Refills listed from the Journal (3.18) go back this far. */
const REFILL_DAYS = 90;
/** A tank's dosing pump, and what it draws each batch or dose. */
interface Link {
  pump: string;
  draw: StockDraw | null;
}
const blank = (): StockTankDraft => ({
  name: "",
  capacity_l: 20,
  level_l: 20,
  dose_ml: 0,
  dose_entity: null,
  low_l: 4,
});
/** Litres in the display unit, never past the two places the page has always shown. */
const volume = (litres: number) => {
  const places = (String(litres).split(".")[1] ?? "").length;
  return formatVolume(litres, Math.min(2, places));
};
/** A time on the zone's calendar and clock: "2 Oct 14:02". */
const at = (iso: string | null, tz: string) => {
  const ms = iso ? Date.parse(iso) : Number.NaN;
  return Number.isFinite(ms) ? `${shortDate(ms, tz)} ${clock(ms, tz)}` : "Never";
};

/** What a tank still covers: whole batches (and days, while the batch rhythm is known), or doses
 * for a tank whose pump the recipe passes by. */
function outlookWords(
  tank: StockTank,
  perBatchMl: number,
  link: Link | null,
  every: number | null,
): string | null {
  if (perBatchMl > 0) {
    const { batches, daysLeft } = stockOutlook(tank, perBatchMl / 1000, every ?? Number.NaN);
    const count = `${batches} ${batches === 1 ? "batch" : "batches"}`;
    return Number.isFinite(daysLeft)
      ? `${count} · ${daysLeft} ${daysLeft === 1 ? "day" : "days"} left`
      : `${count} left`;
  }
  return link ? leftWords(stockLeft(tank.level_l, link.draw)) : null;
}

function TankCard({
  tank,
  hue,
  scale,
  perBatchMl,
  every,
  link,
  next,
  busy,
  onRefill,
  onLevel,
}: {
  tank: StockTank;
  hue: number;
  /** Its capacity over the room's largest. */
  scale: number;
  /** What one batch takes from it, in mL; 0 when a batch takes nothing. */
  perBatchMl: number;
  /** One batch every so many days, when known. */
  every: number | null;
  /** The dosing pump that draws it, or null: then each batch takes its dose. */
  link: Link | null;
  /** It runs out first. */
  next: boolean;
  busy: boolean;
  onRefill: () => void;
  onLevel: (level: number) => Promise<boolean>;
}) {
  const [setting, setSetting] = useState(false);
  const [level, setLevel] = useState(String(tank.level_l));
  const state = stockState(tank);
  const below = tank.level_l <= tank.low_l;
  const inputId = useId();
  const value = Number(level);
  const valid = level.trim() !== "" && value >= 0 && value <= tank.capacity_l;
  const outlook = outlookWords(tank, perBatchMl, link, every);
  const share = Math.round(stockShare(tank));
  return (
    <article
      className="stock-card"
      data-stock-tank={tank.id}
      data-stock-hue={hue % 8}
      data-state={state}
      {...(next ? { "data-stock-next": "" } : {})}
    >
      <div className="stock-bottle-box">
        <StockBottle
          tank={tank}
          state={state}
          capacityScale={scale}
          label={`${tank.name}: ${share}% full, ${volume(tank.level_l)} of ${volume(tank.capacity_l)}, low mark ${volume(tank.low_l)}${
            STOCK_STATES[state] ? `, ${STOCK_STATES[state].toLowerCase()}` : ""
          }`}
        />
        <span
          className="stock-bottle-percent"
          aria-hidden="true"
          style={{
            // In the liquid; just above it while too little shows to hold the number.
            top: `${percentTop(tank.level_l, tank.capacity_l, tank.low_l, scale)}%`,
          }}
        >
          {share}%
        </span>
        <span
          className="stock-bottle-low"
          aria-hidden="true"
          style={{
            top: `${bottleTop(tank.low_l, tank.capacity_l, scale)}%`,
            left: `calc(50% + ${35 * bottleSize(1, scale) + 4}%)`,
          }}
        >
          low {volume(tank.low_l)}
        </span>
      </div>
      <h2>
        {tank.name}
        {next && <span className="sr-only"> (runs out first)</span>}
      </h2>
      <p className="stock-level" data-stock-level>
        <strong>{volume(tank.level_l)}</strong> of {volume(tank.capacity_l)}
      </p>
      <p className="stock-outlook" data-stock-outlook>
        {outlook ?? "No dose per batch set"}
      </p>
      {link && (
        <p className="stock-drawn" data-stock-drawn>
          Drawn by {link.pump} as it doses
        </p>
      )}
      {below && (
        <p className="stock-warning" data-stock-low>
          <TriangleAlert size={14} aria-hidden="true" />
          <span>Below the low line. Order now.</span>
        </p>
      )}
      {setting ? (
        <form
          className="stock-level-form"
          onSubmit={async (event) => {
            event.preventDefault();
            if (valid && (await onLevel(value))) setSetting(false);
          }}
        >
          <span className="label-with-tip">
            <Label htmlFor={inputId}>Tank level (L)</Label>
            <UiTip copyKey="level read off the tank (l)" />
          </span>
          <div>
            <Input
              id={inputId}
              type="number"
              min={0}
              max={tank.capacity_l}
              step={0.1}
              value={level}
              onChange={(event) => setLevel(event.target.value)}
              aria-invalid={!valid}
              autoFocus
            />
            <Button type="submit" size="sm" disabled={!valid || busy}>
              Save level
            </Button>
            <UiTip copyKey="save level" />
            <Button type="button" size="sm" variant="ghost" onClick={() => setSetting(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="stock-actions">
          <Button variant={next ? "default" : "outline"} disabled={busy} onClick={onRefill}>
            Log refill to {volume(tank.capacity_l)}
          </Button>
          <Button
            size="sm"
            variant="link"
            disabled={busy}
            onClick={() => {
              setLevel(String(tank.level_l));
              setSetting(true);
            }}
          >
            Set level
          </Button>
        </div>
      )}
    </article>
  );
}

/** Litres drawn per week, a bar per tank; this week's so far faded. */
function UsedPerWeek({ doc, tz }: { doc: StockDocument; tz: string }) {
  const weeks = weeksShown(doc.history, tz, HISTORY_KEPT, WEEKS_SHOWN);
  const gal = getDisplayUnits().volume === "gal";
  const unit = gal ? "gal" : "L";
  const shown = (litres: number) => (gal ? litres / LITRES_PER_US_GALLON : litres);
  const rows = weeks.map((week) => ({
    label: week.partial ? "This week" : shortDate(Date.parse(`${week.week}T00:00:00Z`), "UTC"),
    partial: week.partial,
    ...Object.fromEntries(doc.tanks.map((tank) => [tank.id, shown(week.byTank[tank.id] ?? 0)])),
  }));
  const today = dayLabel(Date.now(), tz).split(" ")[0];
  return (
    <section className="panel stock-weekly" data-stock-weekly aria-labelledby="stock-weekly-title">
      <div className="stock-panel-head">
        <h2 id="stock-weekly-title">Used per week</h2>
        <ul className="stock-legend" aria-label="Tanks">
          {doc.tanks.map((tank, index) => (
            <li key={tank.id} data-stock-hue={index % 8}>
              <span className="stock-swatch" aria-hidden="true" />
              {tank.name}
            </li>
          ))}
        </ul>
      </div>
      {rows.length ? (
        <>
          <div className="stock-weekly-chart" role="img" aria-label={weeklyWords(weeks, doc.tanks)}>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={rows} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="label"
                  tickLine={false}
                  stroke="var(--muted-foreground)"
                  fontSize={12}
                />
                <YAxis
                  width={44}
                  tickLine={false}
                  axisLine={false}
                  stroke="var(--muted-foreground)"
                  fontSize={12}
                  tickFormatter={(value: number) => `${number(value, 1)} ${unit}`}
                />
                <Tooltip
                  cursor={{ fill: "color-mix(in srgb, var(--foreground) 6%, transparent)" }}
                  contentStyle={{
                    background: "var(--surface)",
                    color: "var(--foreground)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                  }}
                  formatter={(value) =>
                    formatVolume(gal ? Number(value) * LITRES_PER_US_GALLON : Number(value), 2)
                  }
                />
                {doc.tanks.map((tank, index) => (
                  <Bar
                    key={tank.id}
                    dataKey={tank.id}
                    name={tank.name}
                    fill={`var(--stock-hue-${index % 8})`}
                  >
                    {rows.map((row) => (
                      <Cell key={row.label} fillOpacity={row.partial ? 0.45 : 1} />
                    ))}
                  </Bar>
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
          {weeks.at(-1)?.partial && (
            <p className="muted small">
              Faded bars: this week so far (Mon{today === "Mon" ? "" : `–${today}`}).
            </p>
          )}
        </>
      ) : (
        <p className="muted small">Nothing drawn yet.</p>
      )}
    </section>
  );
}
const weeklyWords = (weeks: ReturnType<typeof weeklyUse>, tanks: StockTank[]) =>
  `Litres used per week: ${weeks
    .map(
      (week) =>
        `${week.partial ? "this week so far" : `week of ${shortDate(Date.parse(`${week.week}T00:00:00Z`), "UTC")}`} ${tanks
          .map((tank) => `${tank.name} ${volume(week.byTank[tank.id] ?? 0)}`)
          .join(", ")}`,
    )
    .join("; ")}`;

/** Refills to capacity: from the Journal on 3.18; on an older integration, each tank's last one (the
 * only one it keeps), less those Undo took back this visit (`undone`, see refillRows). */
function Refills({
  controller,
  doc,
  undone,
}: {
  controller: Controller;
  doc: StockDocument;
  undone: ReadonlySet<string>;
}) {
  const tz = controller.timeZone;
  const journal = useParity<{ events: CsEvent[] }>(
    controller,
    "journal_query",
    {
      room_id: controller.roomId,
      since: new Date(Date.now() - REFILL_DAYS * 86_400_000).toISOString(),
      kinds: ["stock.refilled"],
      limit: 500,
    },
    [controller.roomId, doc.revision],
  );
  const rows =
    journal.state === "ready"
      ? refillRows(doc.tanks, journal.data?.events ?? [])
      : journal.state === "missing"
        ? refillRows(doc.tanks, null, undone)
        : [];
  return (
    <section
      className="panel stock-refills"
      data-stock-refills
      aria-labelledby="stock-refills-title"
    >
      <h2 id="stock-refills-title">Refills</h2>
      {journal.state === "error" && <p className="workspace-message error">{journal.error}</p>}
      {journal.state === "loading" && <p className="muted small">Loading refills…</p>}
      {(journal.state === "ready" || journal.state === "missing") &&
        (rows.length ? (
          <ul className="stock-refill-list">
            {rows.map((row) => (
              <li key={row.key} data-stock-hue={row.hue % 8} data-stock-refill>
                <span className="stock-refill-tank">
                  <span className="stock-swatch" aria-hidden="true" />
                  {row.tank}
                </span>
                <span className="stock-refill-date">{shortDate(row.at, tz)}</span>
                <span className="stock-refill-amount">
                  {row.added !== null && row.added >= 0 ? `+${volume(row.added)}, ` : ""}
                  to {volume(row.to)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted small">No refills logged in the last {REFILL_DAYS} days.</p>
        ))}
      {journal.state === "missing" && (
        <p className="muted small" data-stock-refills-older>
          This integration keeps only each tank's last refill to full.
        </p>
      )}
    </section>
  );
}

function Editor({
  controller,
  initial,
  busy,
  max,
  onSave,
  onClose,
}: {
  controller: Controller;
  initial: StockTankDraft[];
  busy: boolean;
  max: number;
  onSave: (drafts: StockTankDraft[]) => void;
  onClose: () => void;
}) {
  const [drafts, setDrafts] = useState(initial);
  const errors = draftErrors(drafts, max);
  const listId = useId();
  // A doser's dose-volume number is the usual source: offer the mL numbers Home Assistant has.
  const doseEntities = Object.values(controller.states)
    .filter(
      (e) =>
        /^(number|input_number|sensor)\./.test(e.entity_id) &&
        /^ml$/i.test(String(e.attributes.unit_of_measurement ?? "")),
    )
    .map((e) => e.entity_id)
    .sort();
  const update = (index: number, change: Partial<StockTankDraft>) =>
    setDrafts(drafts.map((draft, i) => (i === index ? { ...draft, ...change } : draft)));
  const numeric = (index: number, key: keyof StockTankDraft, label: string, unit: string) => (
    <div>
      <Label htmlFor={`${listId}-${index}-${key}`}>
        {label} ({unit})
      </Label>
      <Input
        id={`${listId}-${index}-${key}`}
        type="number"
        min={0}
        step={unit === "mL" ? 1 : 0.1}
        value={String(drafts[index][key] ?? "")}
        onChange={(event) =>
          update(index, { [key]: event.target.value === "" ? NaN : Number(event.target.value) })
        }
      />
    </div>
  );
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="stock-editor">
        <DialogHeader>
          <DialogTitle>Stock tanks</DialogTitle>
          <DialogDescription>
            Each batch tank takes its dose from every stock tank. A dose entity, such as a doser's
            dose-volume number, is read at each batch; the fixed dose stands in when it reads
            nothing. A tank linked to a dosing pump (in Dosing setup) is drawn by what the pump
            doses, not by the tank's fills.
          </DialogDescription>
        </DialogHeader>
        <datalist id={`${listId}-entities`}>
          {doseEntities.map((id) => (
            <option key={id} value={id} />
          ))}
        </datalist>
        <div className="stock-editor-rows">
          {drafts.map((draft, index) => (
            <fieldset key={draft.id ?? `new-${index}`} className="stock-editor-row">
              <legend className="sr-only">{draft.name || `Tank ${index + 1}`}</legend>
              <div className="stock-editor-name">
                <span className="label-with-tip">
                  <Label htmlFor={`${listId}-${index}-name`}>Name</Label>
                  <UiTip copyKey="name" />
                </span>
                <Input
                  id={`${listId}-${index}-name`}
                  value={draft.name}
                  maxLength={40}
                  onChange={(event) => update(index, { name: event.target.value })}
                />
              </div>
              {numeric(index, "capacity_l", "Capacity", "L")}
              {draft.id ? (
                <div>
                  <span className="small muted">Current level</span>
                  <p>{number(draft.level_l, 2)} L</p>
                  <p className="small muted">
                    Snapshot when opened. Set a measured level or record a refill on the tank card.
                  </p>
                </div>
              ) : (
                numeric(index, "level_l", "Initial level", "L")
              )}
              {numeric(index, "dose_ml", "Per batch", "mL")}
              {numeric(index, "low_l", "Low mark", "L")}
              <div className="stock-editor-entity">
                <span className="label-with-tip">
                  <Label htmlFor={`${listId}-${index}-entity`}>Dose entity (optional)</Label>
                  <UiTip copyKey="dose entity (optional)" />
                </span>
                <Input
                  id={`${listId}-${index}-entity`}
                  list={`${listId}-entities`}
                  placeholder="None"
                  value={draft.dose_entity ?? ""}
                  onChange={(event) => update(index, { dose_entity: event.target.value || null })}
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove ${draft.name || `tank ${index + 1}`}`}
                onClick={() => setDrafts(drafts.filter((_, i) => i !== index))}
              >
                <Trash2 size={16} />
              </Button>
            </fieldset>
          ))}
        </div>
        <Button
          type="button"
          variant="outline"
          disabled={drafts.length >= max}
          onClick={() => setDrafts([...drafts, blank()])}
        >
          <Plus size={16} /> Add a stock tank
        </Button>
        {!!errors.length && (
          <ul className="workspace-message error" role="alert">
            {errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={busy || !!errors.length} onClick={() => onSave(drafts)}>
            Save stock tanks
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function StockTanks({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: (page: Page) => void;
}) {
  const [doc, setDoc] = useState<StockDocument | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<StockTankDraft[] | null>(null);
  const [confirmBatch, setConfirmBatch] = useState(false);
  // Refills Undo took back this visit, as "<tank id>@<refilled_at>": an older integration keeps the
  // refill time through the put-back, so Refills leaves these out itself.
  const [undone, setUndone] = useState<ReadonlySet<string>>(new Set());
  // The newest document, for an Undo pressed after later changes.
  const latest = useRef<StockDocument | null>(null);
  latest.current = doc;
  const tz = controller.timeZone;
  useEffect(() => {
    let current = true;
    setDoc(null);
    setError("");
    controller
      .operator<StockDocument>("stock_get")
      .then((result) => current && setDoc(result))
      .catch((err) => current && setError(errorText(err)));
    return () => {
      current = false;
    };
  }, [controller.roomId, controller.connection]);
  const act = async (
    action: "stock_save" | "stock_refill" | "stock_record_batch",
    data = {},
  ): Promise<StockDocument | null> => {
    if (!doc) return null;
    setBusy(true);
    setError("");
    try {
      const next = await controller.operator<StockDocument>(action, {
        ...data,
        expected_revision: doc.revision,
      });
      setDoc(next);
      return next;
    } catch (err) {
      setError(errorText(err));
      return null;
    } finally {
      setBusy(false);
    }
  };
  /** Refilled to capacity at once, with Undo: back to the level it read before. */
  const refill = async (tank: StockTank) => {
    const before = tank.level_l;
    const after = await act("stock_refill", { id: tank.id });
    if (!after) return;
    const read = after.tanks.find((t) => t.id === tank.id);
    if (!read || !sameValue(String(read.level_l), tank.capacity_l)) {
      toast.error(
        `The controller did not confirm ${tank.name} at ${volume(tank.capacity_l)}. Reload and check it.`,
      );
      return;
    }
    offerUndo({
      message: `${tank.name} refilled to ${volume(read.level_l)}. Written and read back ${clock(Date.now(), tz)}.`,
      undo: async () => {
        if (!latest.current) return;
        setBusy(true);
        try {
          setDoc(await undoRefill(controller, latest.current, tank.id, read.level_l, before));
          setUndone((done) => new Set(done).add(`${tank.id}@${read.refilled_at}`));
          toast.success(`${tank.name} put back to ${volume(before)}.`);
        } finally {
          setBusy(false);
        }
      },
    });
  };
  const edit = () =>
    setEditing(
      doc?.tanks.length
        ? doc.tanks.map(({ refilled_at: _r, updated_at: _u, ...tank }) => tank)
        : [blank()],
    );
  const recordBatch = () => (doc?.fill_entity ? setConfirmBatch(true) : act("stock_record_batch"));
  // The tanks the room's dosing pumps are linked to, from its dosing setup: each is drawn by what
  // its pump doses, and lasts as many batches as the pump's recipe amount allows.
  const { states } = controller;
  const prefix = controller.room.room.prefix;
  const dosing = readConfig(states[dosingConfigId(prefix)]);
  const status = readStatus(states[dosingStatusId(prefix)]);
  const rows = dosing ? recipeRows(dosing, states) : [];
  const links = new Map<string, Link>();
  for (const pump of dosing?.pumps ?? [])
    if (pump.stock_tank)
      links.set(pump.stock_tank, {
        pump: pump.name,
        draw: pumpDraw(pump.id, rows, status?.pumps[pump.id]?.last ?? null),
      });
  // A linked tank runs out by batches only while its pump is in the recipe.
  const doses: Record<string, number> = {
    ...doc?.doses,
    ...Object.fromEntries(
      [...links].map(([id, link]) => [id, link.draw?.per === "batch" ? link.draw.ml : 0]),
    ),
  };
  const next = doc ? nextToRunOut(doc.tanks, doses) : null;
  const every = doc ? batchEveryDays(doc.history) : null;
  const largest = doc ? Math.max(...doc.tanks.map((tank) => tank.capacity_l)) : 0;
  return (
    <div className="stock-page">
      <Heading
        title={`Stock tanks · ${controller.room.room.name}`}
        action={
          doc && (
            <div className="heading-actions">
              <Button variant="outline" disabled={busy || !doc.tanks.length} onClick={recordBatch}>
                Record a batch
              </Button>
              <UiTip copyKey="record a batch" />
              <Button onClick={edit} disabled={busy || !!doc.error}>
                <Pencil size={16} /> Edit stock tanks
              </Button>
            </div>
          )
        }
      />
      {error && (
        <p className="workspace-message error" role="alert">
          {error}
        </p>
      )}
      {doc?.error && (
        <p className="workspace-message error" role="alert">
          {doc.error}
        </p>
      )}
      {!doc && !error && <p className="muted">Loading stock tanks…</p>}
      {doc && !doc.tanks.length && !doc.error && (
        <Empty
          title="No stock tanks"
          detail="Add each concentrate you dose into the batch tank: its capacity, how much one batch takes, and when to warn you."
          action={
            <Button onClick={edit}>
              <FlaskConical size={16} /> Add stock tanks
            </Button>
          }
        />
      )}
      {doc && !!doc.tanks.length && (
        <>
          <p className="stock-rhythm" data-stock-rhythm>
            {doc.tanks.some((tank) => Math.cbrt(tank.capacity_l / largest) < MIN_BOTTLE)
              ? "Drawn to scale, the smallest tanks a little larger"
              : "Drawn to scale"}
            {every
              ? ` · one batch every ${number(every, 1)} ${number(every, 1) === "1" ? "day" : "days"} at current use`
              : ""}
          </p>
          <section className="panel stock-shelf" aria-label="Stock tanks">
            {doc.tanks.map((tank, index) => (
              <TankCard
                key={tank.id}
                tank={tank}
                hue={index}
                scale={largest > 0 ? tank.capacity_l / largest : 1}
                perBatchMl={doses[tank.id] ?? tank.dose_ml}
                every={every}
                link={links.get(tank.id) ?? null}
                next={next?.tank.id === tank.id}
                busy={busy}
                onRefill={() => void refill(tank)}
                onLevel={async (level) =>
                  !!(await act("stock_refill", { id: tank.id, level_l: level }))
                }
              />
            ))}
          </section>
          <div className="stock-lower">
            <UsedPerWeek doc={doc} tz={tz} />
            <div className="stock-side">
              <Refills controller={controller} doc={doc} undone={undone} />
              <p className="stock-source" data-stock-source>
                {doc.fill_entity ? (
                  <>
                    Batches are counted from <code>{doc.fill_entity}</code>: each newer fill time
                    takes one batch's dose from every tank
                    {links.size ? " not linked to a dosing pump" : ""}. Last batch{" "}
                    {at(doc.last_batch, tz)}.
                  </>
                ) : (
                  <>
                    No tank last-fill entity is mapped, so record each batch by hand, or{" "}
                    <Button
                      variant="link"
                      className="inline-link"
                      onClick={() => navigate("equipment/setup")}
                    >
                      map one in Rooms and setup
                    </Button>
                    .
                  </>
                )}
                {links.size
                  ? " A tank linked to a dosing pump is drawn by what the pump runs, whoever starts the dose."
                  : ""}{" "}
                Set a tank's level any time you weigh or dip it.
              </p>
            </div>
          </div>
        </>
      )}
      {doc && !!doc.history.length && (
        <details className="stock-history-more">
          <summary>Recent draws ({doc.history.length})</summary>
          <section className="panel stock-history">
            <div className="panel-heading">
              <h2>Recent draws</h2>
            </div>
            <div className="table-scroll" tabIndex={0} aria-label="Recent draws">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>From</th>
                    {doc.tanks.map((tank) => (
                      <th key={tank.id}>{tank.name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {doc.history.slice(0, 10).map((batch, index) => (
                    <tr key={`${batch.at}-${index}`}>
                      <td>{at(batch.at, tz)}</td>
                      <td>
                        <span className="pill" data-tone="unknown">
                          {SOURCES[batch.source] ?? batch.source}
                        </span>
                      </td>
                      {doc.tanks.map((tank) => (
                        <td key={tank.id} className="numeric">
                          {batch.draw_ml[tank.id] === undefined
                            ? "—"
                            : number(batch.draw_ml[tank.id], 0)}
                          {batch.draw_ml[tank.id] !== undefined && (
                            <span className="unit"> mL</span>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </details>
      )}
      {editing && doc && (
        <Editor
          controller={controller}
          initial={editing}
          busy={busy}
          max={doc.max_tanks}
          onClose={() => setEditing(null)}
          onSave={async (drafts) => {
            if (await act("stock_save", { tanks: stockConfigurationPayload(drafts) }))
              setEditing(null);
          }}
        />
      )}
      {confirmBatch && doc && (
        <Dialog open onOpenChange={(open) => !open && setConfirmBatch(false)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Record a batch by hand?</DialogTitle>
              <DialogDescription>
                Batches are already counted from {doc.fill_entity}. Record one here only for a batch
                that entity missed, or it is counted twice.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="ghost" onClick={() => setConfirmBatch(false)}>
                Cancel
              </Button>
              <Button
                disabled={busy}
                onClick={async () => {
                  if (await act("stock_record_batch")) setConfirmBatch(false);
                }}
              >
                Record the batch
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
