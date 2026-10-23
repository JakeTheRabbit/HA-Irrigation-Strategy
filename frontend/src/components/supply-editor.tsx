import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { CapacityBar } from "@/components/primitives/capacity-bar";
import { NeedsIntegration } from "@/components/needs-integration";
import { ReviewApply, type ApplyReceipt, type ReviewRow } from "@/components/review-apply";
import { Button } from "@/components/ui/button";
import { descriptor } from "@/lib/model";
import type { SetupDocument, SetupRoom } from "@/lib/operator-types";
import { callV2, useParity } from "@/lib/parity-api";
import type { SupplyDoc, SupplyPreview } from "@/lib/parity-types";
import {
  applySupply,
  capacityRefusal,
  digitsOf,
  flowEdit,
  flowText,
  flowUnit,
  flowValue,
  forPump,
  overCapacityText,
  parseFlow,
  reviewChecks,
  togetherRows,
  togetherVerdict,
  undoSupply,
  zonesText,
  type DripperEdit,
  type DripperResult,
  type SupplyApplyIo,
} from "@/lib/supply";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";
import "./supply-editor.css";

const FEATURE = "Pump capacity and exclusive groups";
const GROUPS = ["", "A", "B"];
/** A write that may still have landed: nothing says what the controller holds. */
const UNSURE = /timed out|did not confirm|unconfirmed|connection|closed/i;

interface Draft {
  maxFlow: string | null;
  concurrency: number | null;
  groups: Record<string, string>;
  drippers: Record<string, string>;
}
const EMPTY: Draft = { maxFlow: null, concurrency: null, groups: {}, drippers: {} };
type Load = { state: "loading" | "missing" | "error" | "ready"; doc: SupplyDoc | null; error: string | null };

const pct = (n: number) => `${Math.round(n)}%`;
const lph = (n: number) => flowText(n, digitsOf(n) > 1 ? 1 : 0);

/** Setup: pumps & valves. The room's pump (max flow, zones at once), its zones' drippers and
 * exclusive groups, and what can run together; supply_save first, then setup_save for the dripper
 * flows, through Review & apply. */
export function SupplyEditor({ controller, onDirtyChange }: { controller: Controller; onDirtyChange(dirty: boolean): void }) {
  const room = controller.room.room;
  const roomId = room.id;
  const [load, setLoad] = useState<Load>({ state: "loading", doc: null, error: null });
  const [setup, setSetup] = useState<SetupRoom | null>(null);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [refusal, setRefusal] = useState<{ text: string; suggest: number | null } | null>(null);
  // Why a dripper flow was not written, by zone; editing that zone's field clears it.
  const [dripperReason, setDripperReason] = useState<Record<string, string>>({});
  const [last, setLast] = useState<{ pumps: SupplyDoc["irrigation_pumps"]; groups: SupplyDoc["zone_groups"]; revision: number | null; edits: DripperEdit[] } | null>(null);

  const readSetup = useCallback(async () => {
    try {
      const doc = await controller.operator<SetupDocument>("setup_read");
      const found = doc.rooms?.find((r) => r.prefix === room.prefix) ?? null;
      setSetup(found);
      setSetupError(found ? null : "This room is not in the setup.");
      return found;
    } catch (error) {
      setSetupError(errorText(error));
      return null;
    }
  }, [controller, room.prefix]);
  const readSupply = useCallback(async () => {
    const out = await callV2<SupplyDoc>(controller, "supply_get", {});
    if (out.kind === "ok") setLoad({ state: "ready", doc: out.data, error: null });
    else if (out.kind === "missing") setLoad({ state: "missing", doc: null, error: null });
    else setLoad({ state: "error", doc: null, error: out.message });
  }, [controller]);
  useEffect(() => {
    void readSupply();
  }, [readSupply]);
  useEffect(() => {
    if (load.state === "ready") void readSetup();
  }, [load.state, readSetup]);

  const doc = load.doc;
  const pumpEntity = String(descriptor(controller.states, room)?.attributes.pump || setup?.hardware.pump_switch || "");
  const saved = doc?.irrigation_pumps.find((p) => p.entity_id === pumpEntity) ?? null;
  const baseMax = saved?.max_flow_lph ?? null;
  const baseConc = saved?.max_concurrent_zones ?? 1;
  const baseGroups = doc?.zone_groups[roomId] ?? {};
  const zones = (setup?.zones ?? []).filter((z) => z.active);
  // A typed value the same as the shown one (at display precision) is no change: the saved L/h stays.
  const maxEdit = draft.maxFlow === null ? null : flowEdit(draft.maxFlow, baseMax, baseMax === null ? 0 : digitsOf(baseMax));
  const typedMax = draft.maxFlow === null ? baseMax : parseFlow(draft.maxFlow);
  const maxLph = typedMax === null ? null : (maxEdit ?? baseMax ?? typedMax);
  const maxInvalid = draft.maxFlow !== null && draft.maxFlow.trim() !== "" && maxLph === null;
  const conc = draft.concurrency ?? baseConc;
  const groupOf = (zone: number) => draft.groups[zone] ?? baseGroups[String(zone)] ?? "";
  const dripperEdit = (zone: number, base: number) =>
    draft.drippers[zone] === undefined ? null : flowEdit(draft.drippers[zone], base, Math.max(1, digitsOf(base)));

  // Each zone's demand: the integration's own (sensor.crop_steering_supply_config), else the
  // setup's plants × drippers × flow; an edited dripper flow works its own out.
  const published = controller.states["sensor.crop_steering_supply_config"]?.attributes.zone_demand_lph as
    | Record<string, Record<string, number>>
    | undefined;
  const demand: Record<string, number> = {};
  for (const z of zones) {
    const base = z.dripper_flow_rate ?? 0;
    const flow = dripperEdit(z.id, base) ?? base;
    const own = published?.[roomId]?.[String(z.id)];
    demand[String(z.id)] = dripperEdit(z.id, base) === null && typeof own === "number" ? own : z.plant_count * (z.drippers_per_plant ?? 1) * flow;
  }
  const groups = Object.fromEntries(zones.map((z) => [String(z.id), groupOf(z.id)]).filter(([, g]) => g));

  // The rows of Review & apply.
  const rows: ReviewRow[] = [];
  const edits: DripperEdit[] = [];
  if (maxEdit !== null && maxLph !== null)
    rows.push({
      id: "max_flow",
      label: "Pump max flow",
      before: baseMax === null ? "not set" : lph(baseMax),
      after: lph(maxLph),
      undo: () => setDraft((d) => ({ ...d, maxFlow: null })),
    });
  if (draft.concurrency !== null && draft.concurrency !== baseConc)
    rows.push({
      id: "max_concurrent",
      label: "Zones at once",
      before: String(baseConc),
      after: String(draft.concurrency),
      undo: () => setDraft((d) => ({ ...d, concurrency: null })),
    });
  for (const z of zones) {
    const before = baseGroups[String(z.id)] ?? "";
    const after = groupOf(z.id);
    if (after !== before)
      rows.push({
        id: `group:${z.id}`,
        label: `${z.name} exclusive group`,
        before: before || "None",
        after: after || "None",
        undo: () => setDraft((d) => ({ ...d, groups: Object.fromEntries(Object.entries(d.groups).filter(([k]) => k !== String(z.id))) })),
      });
  }
  for (const z of zones) {
    const base = z.dripper_flow_rate;
    if (base === undefined) continue;
    const after = dripperEdit(z.id, base);
    if (after === null) continue;
    const id = `dripper:${z.id}`;
    const digits = Math.max(1, digitsOf(base), digitsOf(after));
    edits.push({ zone: z.id, before: base, after, rowId: id });
    rows.push({
      id,
      label: `${z.name} dripper flow`,
      before: flowText(base, digits),
      after: flowText(after, digits),
      undo: () => setDraft((d) => ({ ...d, drippers: Object.fromEntries(Object.entries(d.drippers).filter(([k]) => k !== String(z.id))) })),
    });
  }
  const pumpRows = rows.filter((r) => !r.id.startsWith("dripper:"));
  const dirty = rows.length > 0 || maxInvalid;
  useLayoutEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useLayoutEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  const sectionOf = (pump: { max_flow_lph: number | null; max_concurrent_zones: number }, zoneGroups: Record<string, string>) => {
    const mine = { entity_id: pumpEntity, max_flow_lph: pump.max_flow_lph, max_concurrent_zones: pump.max_concurrent_zones, flow_meter: saved?.flow_meter ?? null };
    const pumps = doc!.irrigation_pumps.some((p) => p.entity_id === pumpEntity)
      ? doc!.irrigation_pumps.map((p) => (p.entity_id === pumpEntity ? mine : p))
      : [...doc!.irrigation_pumps, mine];
    const others = Object.fromEntries(Object.entries(doc!.zone_groups).filter(([id]) => id !== roomId));
    return { irrigation_pumps: pumps, zone_groups: Object.keys(zoneGroups).length ? { ...others, [roomId]: zoneGroups } : others };
  };
  const payload = doc && pumpEntity && pumpRows.length ? sectionOf({ max_flow_lph: maxLph, max_concurrent_zones: conc }, groups) : null;
  const preview = useParity<SupplyPreview>(
    controller,
    "supply_save",
    payload && doc ? { ...payload, expected_revision: doc.revision, preview: true } : null,
    [payload, doc?.revision],
  );
  // The pump card reads the preview of the draft, else (nothing drafted) the saved check.
  const check = forPump(
    payload ? (preview.state === "ready" && preview.data ? preview.data.capacity_check : EMPTY_CHECK) : (doc?.capacity_check ?? EMPTY_CHECK),
    pumpEntity,
  );
  const ownDemand = published?.[roomId];
  const checks = doc
    ? reviewChecks({ doc, pumpEntity, pumpDraft: !!payload, dripperDraft: edits.length > 0, preview, ...(ownDemand ? { demand: ownDemand } : {}) })
    : [];
  const ownRow = check.pumps?.find((p) => p.entity_id === pumpEntity);
  const over =
    refusal ??
    (ownRow && !ownRow.ok && ownRow.max_concurrent_zones >= 2
      ? { text: overCapacityText(ownRow.max_concurrent_zones, ownRow.suggest_max_concurrent), suggest: ownRow.suggest_max_concurrent }
      : null);

  // Dripper flows go through the room's setup: read fresh, refuse a value changed since, write,
  // and read back what the controller holds.
  const saveDrippers = async (list: DripperEdit[]): Promise<DripperResult> => {
    const fresh = await readSetup();
    const holds = (r: SetupRoom | null) =>
      Object.fromEntries(list.map((e) => [e.zone, r?.zones.find((z) => z.id === e.zone)?.dripper_flow_rate ?? null]));
    if (!fresh) return { holds: holds(null) };
    const now = holds(fresh);
    if (list.some((e) => now[e.zone] !== e.before)) return { holds: now, reason: "The dripper flow changed since you started editing." };
    try {
      const room = await controller.operator<SetupRoom>("setup_save", {
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
      setSetup(room);
      return { holds: holds(room) };
    } catch (error) {
      const reason = errorText(error);
      return UNSURE.test(reason) ? { holds: holds(null), reason } : { holds: now, reason };
    }
  };
  const saveSupplyWith = (section: ReturnType<typeof sectionOf>, revision: number) => async () => {
    const out = await callV2<SupplyDoc>(controller, "supply_save", { ...section, expected_revision: revision });
    if (out.kind === "ok") setLoad({ state: "ready", doc: out.data, error: null });
    if (out.kind === "error") setRefusal(capacityRefusal(out.message));
    return out;
  };
  const apply = async () => {
    setRefusal(null);
    setDripperReason({});
    const before = doc!;
    let revision: number | null = null;
    const save = payload && saveSupplyWith(payload, before.revision);
    const io: SupplyApplyIo = {
      saveSupply:
        save &&
        (async () => {
          const out = await save();
          if (out.kind === "ok") revision = out.data.revision;
          return out;
        }),
      saveDrippers: async (list) => {
        const result = await saveDrippers(list);
        const why = result.reason;
        if (why) setDripperReason(Object.fromEntries(list.filter((e) => result.holds[e.zone] !== e.after).map((e) => [String(e.zone), why])));
        return result;
      },
    };
    const receipt = await applySupply(io, rows, edits, Date.now());
    if ("ok" in receipt) {
      // What took leaves the draft; a row that did not stays, for Try again.
      const kept = new Set([...receipt.failed.map((f) => f.id), ...(receipt.notConfirmed ?? [])]);
      if (receipt.unconfirmed || (receipt.message && !receipt.summary)) return receipt;
      setDraft((d) => ({
        maxFlow: null,
        concurrency: null,
        groups: {},
        drippers: Object.fromEntries(Object.entries(d.drippers).filter(([zone]) => kept.has(`dripper:${zone}`))),
      }));
      setLast({
        pumps: before.irrigation_pumps,
        groups: before.zone_groups,
        revision: payload ? revision : null,
        edits: edits.filter((e) => !kept.has(e.rowId)).map((e) => ({ ...e, before: e.after, after: e.before })),
      });
    }
    return receipt;
  };
  const undo = async (_receipt: ApplyReceipt) => {
    if (!last) return;
    await undoSupply(
      {
        saveSupply:
          last.revision === null
            ? null
            : saveSupplyWith({ irrigation_pumps: last.pumps, zone_groups: last.groups }, last.revision),
        saveDrippers,
      },
      last.edits,
    );
    setLast(null);
  };
  const discard = () => {
    setDraft(EMPTY);
    setRefusal(null);
    setDripperReason({});
  };

  const title = (
    <h2>
      Setup: pumps &amp; valves · {room.name}
    </h2>
  );
  // Under the page's h1: the part's own h2 keeps the note's h3 in order.
  if (load.state === "missing")
    return (
      <div className="supply-editor" data-supply-editor>
        <header className="supply-head">{title}</header>
        <NeedsIntegration feature={FEATURE} />
      </div>
    );
  if (load.state === "error")
    return (
      <section className="panel supply-editor-error" role="alert">
        <p>The pump settings could not be read: {load.error}</p>
        <Button variant="outline" size="sm" onClick={() => void readSupply()}>
          Try again
        </Button>
      </section>
    );
  if (!doc) return <section className="panel supply-editor-loading">Reading the pump settings…</section>;

  const valves = zones.length;
  const counts = Array.from({ length: Math.max(valves, conc, 1) }, (_, i) => i + 1);
  const together = maxLph ? togetherRows(demand, maxLph, groups) : [];
  const worst = together.filter((r) => r.zones.length === 2 && !r.sameGroup).sort((a, b) => b.pct - a.pct)[0];
  const tone = (zone: number) => `z${((zones.findIndex((z) => z.id === zone) % 6) + 6) % 6}`;
  const segments = (ids: number[]) => ids.map((id) => ({ id: String(id), label: `Zone ${id}`, lph: demand[String(id)] ?? 0, tone: tone(id) }));
  const unit = flowUnit();

  return (
    <div className="supply-editor" data-supply-editor>
      <header className="supply-head">
        {title}
        <span className="muted">
          {pumpEntity ? "1 feed pump" : "No pump"}, {valves} zone valve{valves === 1 ? "" : "s"}
        </span>
      </header>
      <div className="supply-grid">
        <div className="supply-main">
          <section className="panel supply-card" aria-labelledby="supply-pump">
            <h3 id="supply-pump">
              {room.name} feed pump {pumpEntity && <span className="muted supply-entity">{pumpEntity}</span>}
            </h3>
            {!pumpEntity ? (
              <p>This room has no pump mapped. Map Room pump under Rooms &amp; mappings below.</p>
            ) : (
              <>
                {baseMax === null && <p className="supply-empty">Add your pump's output to stop zones starving each other.</p>}
                <div className="supply-pump-fields">
                  <label className="supply-field">
                    <span>Max flow</span>
                    <span className="supply-input">
                      <input
                        inputMode="decimal"
                        aria-label="Max flow"
                        aria-invalid={maxInvalid || undefined}
                        aria-describedby={maxInvalid ? "supply-max-error" : undefined}
                        value={draft.maxFlow ?? (baseMax === null ? "" : flowValue(baseMax, digitsOf(baseMax)))}
                        onChange={(e) => setDraft((d) => ({ ...d, maxFlow: e.target.value }))}
                      />
                      <span>{unit}</span>
                      {rows.some((r) => r.id === "max_flow") && baseMax !== null && (
                        <small className="supply-was">was {flowValue(baseMax, digitsOf(baseMax))}</small>
                      )}
                    </span>
                    {maxInvalid && (
                      <small className="supply-error" id="supply-max-error">
                        Enter a flow above 0.
                      </small>
                    )}
                  </label>
                  <div className="supply-field">
                    <span id="supply-conc">Max zones at once</span>
                    <div className="supply-seg" role="group" aria-labelledby="supply-conc">
                      {counts.map((n) => (
                        <button
                          key={n}
                          type="button"
                          aria-pressed={conc === n}
                          onClick={() => {
                            setRefusal(null);
                            setDraft((d) => ({ ...d, concurrency: n }));
                          }}
                        >
                          {n}
                        </button>
                      ))}
                    </div>
                  </div>
                  {worst && maxLph && conc >= 2 ? (
                    <div className="supply-field supply-worst">
                      <span>Worst pair allowed to start together</span>
                      <CapacityBar
                        segments={segments(worst.zones)}
                        capacityLph={maxLph}
                        caption={`${zonesText(worst.zones)} against the pump line`}
                      />
                      <small className={worst.pct > 100 ? "is-warn" : undefined}>
                        {zonesText(worst.zones)} together = {pct(worst.pct)} of pump: {togetherVerdict(worst, groups, conc)}
                      </small>
                    </div>
                  ) : null}
                </div>
                {over && (
                  <div className="supply-refusal" role="alert">
                    <span>{over.text}</span>
                    {over.suggest !== null && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setRefusal(null);
                          setDraft((d) => ({ ...d, concurrency: over.suggest }));
                        }}
                      >
                        Use {over.suggest}
                      </Button>
                    )}
                  </div>
                )}
              </>
            )}
          </section>

          <section className="panel supply-card" aria-labelledby="supply-zones">
            <h3 id="supply-zones">Zone valves and drippers</h3>
            {!setup ? (
              <p className={setupError ? "supply-error" : "muted"} role={setupError ? "alert" : undefined}>
                {setupError ? `The zones could not be read: ${setupError}` : "Reading the zones…"}
              </p>
            ) : (
              <div className="supply-table-wrap" role="region" aria-label="Zones table, scrolls sideways" tabIndex={0}>
                <table className="supply-table">
                  <thead>
                    <tr>
                      <th scope="col">Zone</th>
                      <th scope="col">Drippers</th>
                      <th scope="col">Dripper flow</th>
                      <th scope="col">Zone flow</th>
                      <th scope="col">Share of pump</th>
                      <th scope="col">Exclusive group</th>
                    </tr>
                  </thead>
                  <tbody>
                    {zones.map((z) => {
                      const base = z.dripper_flow_rate ?? 0;
                      const typed = draft.drippers[z.id];
                      const invalid = typed !== undefined && parseFlow(typed) === null;
                      const changed = dripperEdit(z.id, base) !== null;
                      const share = maxLph ? (demand[String(z.id)] / maxLph) * 100 : null;
                      const reason = dripperReason[String(z.id)];
                      const errorId = `supply-dripper-error-${z.id}`;
                      return (
                        <tr key={z.id} data-zone={z.id}>
                          <th scope="row">
                            <span className="supply-dot" data-tone={tone(z.id)} aria-hidden />
                            {z.name}
                          </th>
                          <td>
                            {z.plant_count * (z.drippers_per_plant ?? 1)}
                            <small className="muted">
                              {z.plant_count} plants × {z.drippers_per_plant ?? 1}
                            </small>
                          </td>
                          <td>
                            <span className="supply-input is-small">
                              <input
                                inputMode="decimal"
                                aria-label={`${z.name} dripper flow`}
                                aria-invalid={invalid || undefined}
                                aria-describedby={invalid || reason ? errorId : undefined}
                                value={typed ?? flowValue(base, Math.max(1, digitsOf(base)))}
                                onChange={(e) => {
                                  const value = e.target.value;
                                  setDripperReason((r) => Object.fromEntries(Object.entries(r).filter(([k]) => k !== String(z.id))));
                                  setDraft((d) => ({ ...d, drippers: { ...d.drippers, [z.id]: value } }));
                                }}
                              />
                              <span>{unit}</span>
                            </span>
                            {changed && <small className="supply-was">was {flowValue(base, Math.max(1, digitsOf(base)))}</small>}
                            {(invalid || reason) && (
                              <small className="supply-error" id={errorId}>
                                {invalid ? "Enter a flow above 0." : reason}
                              </small>
                            )}
                          </td>
                          <td className="supply-num">{lph(demand[String(z.id)])}</td>
                          <td>
                            {share === null ? (
                              <span className="muted">Set max flow</span>
                            ) : (
                              <span className="supply-share">
                                <span className="supply-share-bar" aria-hidden>
                                  <span data-tone={tone(z.id)} style={{ width: `${Math.min(100, (share * 2) / 3)}%` }} />
                                  <i />
                                </span>
                                <span>{pct(share)}</span>
                              </span>
                            )}
                          </td>
                          <td>
                            <div className="supply-seg" role="group" aria-label={`${z.name} exclusive group`}>
                              {[...new Set([...GROUPS, groupOf(z.id)])].map((g) => (
                                <button
                                  key={g || "none"}
                                  type="button"
                                  aria-pressed={groupOf(z.id) === g}
                                  onClick={() => setDraft((d) => ({ ...d, groups: { ...d.groups, [z.id]: g } }))}
                                >
                                  {g || "None"}
                                </button>
                              ))}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <p className="small muted">
              Zones in the same exclusive group never water at the same time, e.g. two zones on one submain. Line at 2/3 of
              each bar = 100% of the pump.
            </p>
          </section>

          {together.length > 0 && maxLph ? (
            <section className="panel supply-card" aria-labelledby="supply-together">
              <h3 id="supply-together">What can run together</h3>
              <ul className="supply-together">
                {together.map((r) => (
                  <li key={r.zones.join("+")} data-muted={r.sameGroup || undefined} data-over={(!r.sameGroup && r.pct > 100) || undefined}>
                    <b>{zonesText(r.zones)}</b>
                    <CapacityBar segments={segments(r.zones)} capacityLph={maxLph} caption={`${zonesText(r.zones)}: ${pct(r.pct)} of the pump`} />
                    <span className="supply-verdict">
                      <b>{pct(r.pct)}</b> {togetherVerdict(r, groups, conc)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>

        <ReviewApply
          layout="panel"
          rows={rows}
          discardLabel="Discard changes"
          checks={checks}
          apply={apply}
          onDiscard={discard}
          onReload={() => {
            discard();
            void readSupply();
            void readSetup();
          }}
          timeZone={controller.timeZone}
          undo={last ? undo : undefined}
          consequence="A shot that has to wait shows as queued on the Timeline. If it waits more than 10 min you get an alert: the zone waited long for its pump."
        />
      </div>
    </div>
  );
}

const EMPTY_CHECK: SupplyDoc["capacity_check"] = { worst_case_lph: 0, max_flow_lph: null, ok: true, suggest_max_concurrent: null, pairs: [] };
