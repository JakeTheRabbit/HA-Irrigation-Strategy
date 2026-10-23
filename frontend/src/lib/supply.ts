import type { ApplyReceipt, ReviewRow } from "@/components/review-apply";
import { getDisplayUnits } from "./display-units";
import type { SetupRoom } from "./operator-types";
import type { V2Outcome } from "./parity-api";
import type { CapacityPair, SupplyDoc, SupplyPreview } from "./parity-types";
import { UndoError } from "./undo";
import { LITRES_PER_US_GALLON } from "./units";
import { errorText } from "./utils";

/** Pump capacity and exclusive groups (Setup: pumps & valves). The verdicts come from the
 * integration's own `capacity_check`; the "what can run together" rows are display layout only. */

type Check = { ok: boolean | "warn"; text: string };
type Refusal = Extract<V2Outcome<unknown>, { kind: "error" | "missing" }>;

/** A flow in the display volume unit per hour. Gallons get one more digit: a gallon is bigger. */
export function flowText(lph: number, litreDigits: number): string {
  return getDisplayUnits().volume === "gal"
    ? `${(lph / LITRES_PER_US_GALLON).toFixed(litreDigits + 1)} gal/h`
    : `${lph.toFixed(litreDigits)} L/h`;
}
/** The number alone, in the display unit, for an input. */
export function flowValue(lph: number, litreDigits: number): string {
  return getDisplayUnits().volume === "gal" ? (lph / LITRES_PER_US_GALLON).toFixed(litreDigits + 1) : lph.toFixed(litreDigits);
}
export const flowUnit = () => (getDisplayUnits().volume === "gal" ? "gal/h" : "L/h");
/** How many decimals a stored number carries (never round past it); float noise from a sum or a
 * product (57.599999999999994) is not a digit. */
export const digitsOf = (n: number) => (String(Number(n.toPrecision(12))).split(".")[1] ?? "").length;
/** A flow at its own digits. */
export const lphText = (n: number) => flowText(n, digitsOf(n));
/** The same flow, give or take float noise (a gal/h value converted back to L/h). */
const sameFlow = (a: number | null | undefined, b: number) => a != null && Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(b));
/** A typed flow in the display unit, back to L/h; null when it is not a flow above 0. */
export function parseFlow(text: string): number | null {
  const t = text.trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(t)) return null;
  const value = Number(t);
  if (!(value > 0)) return null;
  return getDisplayUnits().volume === "gal" ? Number((value * LITRES_PER_US_GALLON).toPrecision(12)) : value;
}

/** A typed flow that differs from `base` as the field shows it (`digits`: base's L/h decimals), in
 * L/h; null when it is not a flow, or is the same at display precision (retyping the shown gal/h). */
export function flowEdit(typed: string, base: number | null, digits: number): number | null {
  const value = parseFlow(typed);
  if (value === null || base === null) return value;
  return Number(typed.trim().replace(",", ".")) === Number(flowValue(base, digits)) ? null : value;
}

const refText = (ref: CapacityPair["zones"][number]) =>
  typeof ref === "number" ? String(ref) : `${ref.zone} (${ref.room_id.replace(/^room:/, "") || "default"})`;
export const zonesText = (zones: CapacityPair["zones"]) => `Zones ${zones.map(refText).join(" + ")}`;
const pctText = (pct: number) => `${Math.round(pct)}%`;

/** The review panel's checks, from `capacity_check` only. `demand` (each zone's L/h, as the
 * integration has it) only names a zone the check found bigger than the pump. */
export function supplyChecks(doc: SupplyDoc, demand?: Record<string, number>): Check[] {
  const c = doc.capacity_check;
  if (c.max_flow_lph == null) return [];
  const max = c.max_flow_lph;
  const checks: Check[] = [{ ok: true, text: `Pump max flow ${lphText(max)} is in range` }];
  // A pump that passes feeds its worst mix, so each zone alone; else each zone must share a pair
  // that fits.
  const key = (ref: CapacityPair["zones"][number]) => (typeof ref === "number" ? String(ref) : `${ref.room_id}/${ref.zone}`);
  const all = new Set(c.pairs.flatMap((p) => p.zones.map(key)));
  const fits = new Set(c.pairs.filter((p) => p.lph <= max).flatMap((p) => p.zones.map(key)));
  if (c.ok || (all.size > 0 && [...all].every((z) => fits.has(z))))
    checks.push({ ok: true, text: "Every zone fits the pump on its own" });
  if ((c.pumps ?? []).some((p) => !p.ok && p.max_concurrent_zones >= 2))
    checks.push({ ok: false, text: "Zones at once: more than the pump can feed" });
  // One zone at a time is never refused: a zone bigger than its pump still waters (CS-214 warns).
  if ((c.pumps ?? []).some((p) => !p.ok && p.max_concurrent_zones < 2))
    for (const [zone, need] of Object.entries(demand ?? {}))
      if (need > max) checks.push({ ok: "warn", text: `Zone ${zone} alone needs ${lphText(need)}, more than the pump's ${lphText(max)}` });
  for (const p of c.pairs)
    if (p.pct_of_pump != null && p.pct_of_pump > 100)
      checks.push({ ok: "warn", text: `${zonesText(p.zones)} need ${pctText(p.pct_of_pump)}: shots queue, one after another` });
  return checks;
}

/** The checks of Review & apply: only the integration's preview of the current draft (nothing
 * while it is asked, the error when it fails). The preview sizes zones from their saved dripper
 * flows, so with dripper rows drafted the demand checks say so. Dripper rows alone: no checks. */
export function reviewChecks(input: {
  doc: SupplyDoc;
  pumpEntity: string;
  pumpDraft: boolean;
  dripperDraft: boolean;
  preview: { state: string; data: SupplyPreview | null; error: string | null };
  demand?: Record<string, number>;
}): Check[] {
  const { preview } = input;
  if (!input.pumpDraft) return [];
  if (preview.state === "error") return [{ ok: "warn", text: `The draft could not be checked: ${preview.error}` }];
  if (preview.state !== "ready" || !preview.data) return [];
  const checks = supplyChecks(
    { ...input.doc, capacity_check: forPump(preview.data.capacity_check, input.pumpEntity) },
    input.dripperDraft ? undefined : input.demand,
  );
  if (!input.dripperDraft) return checks;
  return checks.map((c, i) => (i === 0 ? c : { ...c, text: `${c.text} (with the saved dripper flows)` }));
}

export interface TogetherRow {
  zones: number[];
  pct: number;
  sameGroup: boolean;
}
/** Every pair of zones (and, up to four zones, every larger set): their summed demand as a share of
 * the pump's max flow, and whether two of them share an exclusive group. */
export function togetherRows(demand: Record<string, number>, maxLph: number, groups: Record<string, string>): TogetherRow[] {
  const zones = Object.keys(demand)
    .map(Number)
    .sort((a, b) => a - b);
  const largest = zones.length <= 4 ? zones.length : 2;
  const rows: TogetherRow[] = [];
  const pick = (start: number, set: number[], size: number) => {
    if (set.length === size) {
      const named = set.map((z) => groups[String(z)]).filter(Boolean);
      rows.push({
        zones: set,
        pct: (set.reduce((sum, z) => sum + demand[String(z)], 0) / maxLph) * 100,
        sameGroup: new Set(named).size < named.length,
      });
      return;
    }
    for (let i = start; i < zones.length; i++) pick(i + 1, [...set, zones[i]], size);
  };
  for (let size = 2; size <= largest; size++) pick(0, [], size);
  return rows;
}
/** The words beside a row. */
export function togetherVerdict(row: TogetherRow, groups: Record<string, string>, maxConcurrent: number): string {
  if (row.sameGroup) {
    const named = row.zones.map((z) => groups[String(z)]).filter(Boolean);
    const shared = named.find((g, i) => named.indexOf(g) !== i);
    return `never together: exclusive group ${shared}`;
  }
  if (row.pct > 100) return "over the pump: will run one after another";
  if (row.zones.length > maxConcurrent) return `one at a time: Zones at once is ${maxConcurrent}`;
  return "fits: can run together";
}

/** One pump's part of a site-wide check: its own row and the pairs of its zones (a pair's share is
 * of this pump's max flow). The whole check when the site has this pump alone. */
export function forPump(check: SupplyDoc["capacity_check"], entityId: string): SupplyDoc["capacity_check"] {
  const rows = check.pumps ?? [];
  const row = rows.find((r) => r.entity_id === entityId);
  if (!row || rows.length === 1) return check;
  const max = row.max_flow_lph;
  return {
    worst_case_lph: row.worst_case_lph,
    max_flow_lph: max,
    ok: row.ok,
    suggest_max_concurrent: row.suggest_max_concurrent,
    pumps: [row],
    pairs: max == null ? [] : check.pairs.filter((p) => p.pct_of_pump != null && Math.abs(p.pct_of_pump - (p.lph / max) * 100) < 1e-9),
  };
}

/** The sentence for a pump set to feed more zones at once than it can. */
export function overCapacityText(zones: number, suggest: number | null): string {
  return `The pump can't feed ${zones} zones at once.${suggest === null ? "" : ` Set Zones at once to ${suggest} or less.`}`;
}

const OVER = /pump_over_capacity: \S+ cannot feed (\d+) zones at once:.*Set Zones at once to (\d+|None) or less\./;
/** supply_save's refusal of a pump set to feed more zones at once than it can, in grower words,
 * with the count it suggests (`capacity_check.suggest_max_concurrent`). */
export function capacityRefusal(message: string): { text: string; suggest: number | null } | null {
  const match = OVER.exec(message);
  if (!match) return null;
  const suggest = match[2] === "None" ? null : Number(match[2]);
  return { text: overCapacityText(Number(match[1]), suggest), suggest };
}

/** One zone's dripper flow edit, in L/h. */
export interface DripperEdit {
  zone: number;
  before: number;
  after: number;
  rowId: string;
}
/** `holds`: each zone's dripper flow the controller read back after the write (null: not read).
 * `reason`: why it was not written, when it was refused. */
export interface DripperResult {
  holds: Record<number, number | null>;
  reason?: string;
}
export interface SupplyApplyIo {
  saveSupply: (() => Promise<V2Outcome<SupplyDoc>>) | null;
  saveDrippers: ((edits: DripperEdit[]) => Promise<DripperResult>) | null;
}

const line = (r: ReviewRow) => `${r.label} ${r.before} → ${r.after}`;
const isDripper = (r: ReviewRow) => r.id.startsWith("dripper:");

/** Apply: supply_save first (pump and groups), then setup_save for the dripper flows. A refused or
 * unconfirmed supply save stops there; a dripper flow not written is named with what the controller
 * still holds. Pump and group rows with no supply save (no pump mapped) are not written. */
export async function applySupply(
  io: SupplyApplyIo,
  rows: ReviewRow[],
  edits: DripperEdit[],
  now: number,
): Promise<ApplyReceipt | Refusal> {
  const pumpRows = rows.filter((r) => !isDripper(r));
  let eventIds: string[] = [];
  if (pumpRows.length && io.saveSupply) {
    const out = await io.saveSupply();
    if (out.kind === "missing") return out;
    if (out.kind === "error") {
      const over = out.code === "invalid" ? capacityRefusal(out.message) : null;
      if (!over) return out;
      return {
        at: now,
        ok: false,
        failed: rows.map((r) => ({ id: r.id, holds: r.before })),
        // The pump card says why (with Use N); the panel only says nothing changed.
        message: "Nothing was changed. The pump card says why.",
        summary: "",
        eventIds: [],
      };
    }
    if (out.readback.status !== "verified")
      return { at: now, ok: false, unconfirmed: true, failed: rows.map((r) => ({ id: r.id, holds: r.before })), summary: "", eventIds: out.eventIds };
    eventIds = out.eventIds;
  }
  const unsaved = io.saveSupply ? [] : pumpRows.map((r) => ({ id: r.id, holds: r.before, label: r.label }));
  const result: DripperResult = edits.length && io.saveDrippers ? await io.saveDrippers(edits) : { holds: {} };
  const failed: ApplyReceipt["failed"] = [];
  const notConfirmed: string[] = [];
  for (const edit of edits) {
    const holds = result.holds[edit.zone];
    const label = rows.find((r) => r.id === edit.rowId)?.label ?? `Zone ${edit.zone} dripper flow`;
    if (holds == null) notConfirmed.push(edit.rowId);
    else if (!sameFlow(holds, edit.after)) failed.push({ id: edit.rowId, holds: flowText(holds, Math.max(1, digitsOf(holds))), label });
  }
  const left = new Set([...unsaved.map((f) => f.id), ...failed.map((f) => f.id), ...notConfirmed]);
  const receipt: ApplyReceipt = {
    at: now,
    ok: !left.size,
    failed: [...unsaved, ...failed],
    ...(notConfirmed.length ? { notConfirmed } : {}),
    summary: rows
      .filter((r) => !left.has(r.id))
      .map(line)
      .join(" · "),
    eventIds,
  };
  if ((unsaved.length || failed.length) && !notConfirmed.length)
    receipt.message = [
      pumpRows.length && !unsaved.length ? "Pump settings were saved." : "",
      ...unsaved.map((f) => `${f.label} was not saved: this room has no pump mapped.`),
      ...failed.map((f) => `${f.label} was not: controller still holds ${f.holds}.`),
    ]
      .filter(Boolean)
      .join(" ");
  return receipt;
}

/** Undo: the pump and groups as they were (supply_save at the applied revision, so a later change
 * refuses it), then each dripper flow as it was (`edits` run from the applied value back). Stops at
 * the first that does not take: "k of n put back". */
export async function undoSupply(io: SupplyApplyIo, edits: DripperEdit[]): Promise<void> {
  const total = (io.saveSupply ? 1 : 0) + edits.length;
  let reverted = 0;
  const stop = (reason: string): never => {
    throw new UndoError(reverted ? `${reverted} of ${total} put back: ${reason}` : reason, reverted, total);
  };
  if (io.saveSupply) {
    const out = await io.saveSupply();
    if (out.kind === "missing") stop("Undo needs Crop Steering 3.18 or newer. Nothing was changed.");
    else if (out.kind === "error") stop(out.message);
    else if (out.readback.status !== "verified")
      stop("The controller did not confirm the previous value. Reload and check it before trying again.");
    reverted++;
  }
  if (!edits.length || !io.saveDrippers) return;
  const result = await io.saveDrippers(edits);
  for (const edit of edits) {
    if (!sameFlow(result.holds[edit.zone], edit.after))
      stop(result.reason ?? "The controller did not confirm the previous value. Reload and check it before trying again.");
    reverted++;
  }
}

/** What Undo puts back: the pump and groups as they were before `revision` (null: no supply save),
 * and the dripper edits run back. `partial`: that apply did not all take, so its receipt had no Undo. */
export interface SupplyUndo {
  pumps: SupplyDoc["irrigation_pumps"];
  groups: SupplyDoc["zone_groups"];
  revision: number | null;
  edits: DripperEdit[];
  partial: boolean;
}
/** The Undo after an apply. A Try again after a partial apply (the rows left over, no new pump
 * change) carries the earlier one: its pump save and its dripper edits stay in this Undo. */
export function nextUndo(prev: SupplyUndo | null, applied: SupplyUndo): SupplyUndo {
  if (!prev?.partial || applied.revision !== null) return applied;
  return { ...prev, edits: [...prev.edits, ...applied.edits], partial: applied.partial };
}

/** A write that may still have landed: nothing says what the controller holds. */
const UNSURE = /timed out|did not confirm|unconfirmed|connection|closed/i;
export interface DripperSetupIo {
  read: () => Promise<SetupRoom | null>;
  save: (payload: Record<string, unknown>) => Promise<SetupRoom>;
}
/** Dripper flows go through the room's setup: read fresh, refuse a value changed since, write,
 * and read back what the controller holds. */
export async function saveDripperFlows(io: DripperSetupIo, list: DripperEdit[]): Promise<DripperResult> {
  const fresh = await io.read();
  const holds = (r: SetupRoom | null) =>
    Object.fromEntries(list.map((e) => [e.zone, r?.zones.find((z) => z.id === e.zone)?.dripper_flow_rate ?? null]));
  if (!fresh) return { holds: holds(null) };
  const now = holds(fresh);
  if (list.some((e) => !sameFlow(now[e.zone], e.before))) return { holds: now, reason: "The dripper flow changed since you started editing." };
  try {
    const room = await io.save({
      entry_id: fresh.entry_id,
      expected_revision: fresh.revision,
      room_name: fresh.room_name,
      active: fresh.active,
      zones: fresh.zones.map((z) => {
        const e = list.find((x) => x.zone === z.id);
        return e ? { ...z, dripper_flow_rate: e.after } : z;
      }),
      hardware: fresh.hardware,
      ...(fresh.plumbing ? { plumbing: fresh.plumbing } : {}),
    });
    return { holds: holds(room) };
  } catch (error) {
    const reason = errorText(error);
    return UNSURE.test(reason) ? { holds: holds(null), reason } : { holds: now, reason };
  }
}
