import { useEffect, useId, useLayoutEffect, useState } from "react";
import { ArrowDown, ArrowUp, LoaderCircle, Pencil, Plus, Trash2 } from "lucide-react";
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
import { MappingPicker } from "@/pages/setup";
import {
  DOMAINS,
  FIELD_LABELS,
  MAX_PUMPS,
  PUMP_FIELDS,
  blankPump,
  canEdit,
  dosingError,
  newPumpId,
  setupChanges,
  setupDraft,
  setupErrors,
  setupPayload,
  stockTanks,
  type DosingBatch,
  type DosingConfig,
  type DosingDocument,
  type PumpDraft,
  type SetupDraft,
} from "@/lib/dosing";
import type { StockDocument } from "@/lib/stock";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";

const HINTS: Record<string, string> = {
  volume_entity: "Choose the number the pump's firmware doses, in mL.",
  start_entity: "Choose the button or script that starts a dose on the pump itself.",
  dosing_entity:
    "Choose what reports the pump dosing: a binary sensor, or a sensor whose state says so.",
  power_entity: "Choose the switch that cuts the pump's motor.",
  flow_entity: "Choose the pump's calibrated flow, in mL per second.",
  fill_valve: "Choose the switch that fills the batch tank; none if it is filled by hand.",
  full_entity: "Choose the float that says the tank is full.",
  mix_pump: "Choose the switch that runs the mixing pump.",
  mix_valves: "Choose the valves opened before the mixing pump starts.",
  mix_power_sensor: "Choose the mixing pump's power sensor, in W.",
  close_entities: "Choose the switches turned off before filling, such as another room's feed.",
  hold_entity: "Choose a helper that is on for the whole batch, for other automations to read.",
  filled_at_entity:
    "Choose a date and time helper stamped when a batch finishes; stock tanks count batches by it.",
  ml_entity:
    "Choose a number or sensor read at the start of each batch; it wins over the fixed amount.",
};
const OPTIONAL_BATCH = [
  "fill_valve",
  "full_entity",
  "mix_pump",
  "mix_power_sensor",
  "hold_entity",
  "filled_at_entity",
] as const;

/** Equipment › Dosing's setup: each pump's hardware and the batch's, from the entities Home
 * Assistant has (dosing_get), saved with dosing_save against the revision it was read at. An
 * administrator edits it; anyone else reads it. */
export function DosingSetup({
  controller,
  doc,
  config,
  draft,
  setDraft,
  onSaved,
  onDirtyChange,
}: {
  controller: Controller;
  doc: DosingDocument | null;
  /** What the room runs now, for reading. */
  config: DosingConfig | null;
  /** The editor's draft; null when not editing. */
  draft: SetupDraft | null;
  setDraft: (draft: SetupDraft | null) => void;
  onSaved: (doc: DosingDocument) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const id = useId();
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // The room's stock tanks, read when editing starts: each pump may be linked to one.
  const [tanks, setTanks] = useState<{ id: string; name: string }[] | null>(null);
  const [tanksError, setTanksError] = useState("");
  const editing = !!draft;
  useEffect(() => {
    if (!editing) return;
    let current = true;
    setTanksError("");
    controller
      .operator<StockDocument>("stock_get")
      .then((result) => current && setTanks(result.tanks.map(({ id, name }) => ({ id, name }))))
      .catch((err) => current && setTanksError(errorText(err)));
    return () => {
      current = false;
    };
  }, [editing, controller.roomId]);
  const base = doc?.config ?? null;
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(setupDraft(base));
  useLayoutEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  const admin = canEdit(doc, controller.admin);
  const connected = ["live", "demo"].includes(controller.connection);
  const pick = (field: string) =>
    (doc?.candidates ?? []).filter((candidate) => DOMAINS[field]?.includes(candidate.domain));
  // The tanks the stock sensor lists, to name them before stock_get has been read.
  const named = tanks ?? stockTanks(controller.states, controller.room.room.prefix);

  if (!draft)
    return (
      <div className="dosing-setup-body">
        {notice && (
          <p className="success-text" role="status">
            {notice}
          </p>
        )}
        {config ? (
          <SetupSummary config={config} tanks={named} />
        ) : (
          <p className="muted">No dosing setup yet.</p>
        )}
        {admin ? (
          <Button
            variant="outline"
            disabled={!doc || !connected || !!doc.error}
            onClick={() => {
              setNotice("");
              setError("");
              setDraft(setupDraft(base));
            }}
          >
            <Pencil size={15} /> Edit dosing setup
          </Button>
        ) : (
          <p className="muted small">
            Only a Home Assistant administrator can change the dosing setup.
          </p>
        )}
      </div>
    );

  const errors = setupErrors(draft, tanks?.map((tank) => tank.id) ?? null);
  const payload = setupPayload(draft);
  const taken = new Set(draft.pumps.flatMap((pump) => pump.id ?? []));
  const updatePump = (key: string, change: Partial<PumpDraft>) =>
    setDraft({
      ...draft,
      pumps: draft.pumps.map((pump) => (pump.key === key ? { ...pump, ...change } : pump)),
    });
  const updateBatch = (change: Partial<DosingBatch>) =>
    setDraft({ ...draft, batch: { ...draft.batch, ...change } });
  const moveLine = (index: number, by: number) => {
    const recipe = [...draft.batch.recipe];
    const [line] = recipe.splice(index, 1);
    recipe.splice(index + by, 0, line);
    updateBatch({ recipe });
  };
  const count = (value: string) => (value === "" ? Number.NaN : Number(value));
  const pumpName = (key: string) => draft.pumps.find((pump) => pump.key === key)?.name || "A pump";
  const unused = draft.pumps.filter(
    (pump) => !draft.batch.recipe.some((line) => line.pump === pump.key),
  );
  const single = (field: (typeof OPTIONAL_BATCH)[number], optional = true) => (
    <MappingPicker
      label={FIELD_LABELS[field] + (optional ? " (optional)" : "")}
      values={draft.batch[field] ? [draft.batch[field]!] : []}
      candidates={pick(field)}
      hint={HINTS[field]}
      onChange={(values) => updateBatch({ [field]: values[0] ?? null })}
    />
  );
  const minutes = (
    field: "fill_timeout_min" | "mix_min_w" | "premix_min" | "postmix_min",
    max: number,
  ) => (
    <div className="dosing-field">
      <Label htmlFor={`${id}-${field}`}>{FIELD_LABELS[field]}</Label>
      <Input
        id={`${id}-${field}`}
        type="number"
        min={field === "fill_timeout_min" ? 1 : 0}
        max={max}
        step={1}
        value={Number.isFinite(draft.batch[field]) ? String(draft.batch[field]) : ""}
        onChange={(event) => updateBatch({ [field]: count(event.target.value) })}
      />
    </div>
  );
  async function save() {
    setBusy(true);
    setError("");
    try {
      const result = await controller.operator<DosingDocument>("dosing_save", {
        expected_revision: base?.revision ?? 0,
        ...payload,
      });
      if (result.error) setError(dosingError(result.error, true));
      else {
        setReview(false);
        setDraft(null);
        onSaved(result);
        setNotice(
          `Saved as revision ${result.config?.revision ?? "?"}. The controller reads it within a few seconds.`,
        );
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  const changes = setupChanges(base, payload, named);
  /** A pump's stock tank: none, or one of the room's; a tank another pump draws is not offered. */
  const stockPicker = (pump: PumpDraft) => {
    const others = draft.pumps.filter((item) => item.key !== pump.key);
    const known = named.some((tank) => tank.id === pump.stock_tank);
    return (
      <div className="dosing-field">
        <Label htmlFor={`${id}-${pump.key}-stock`}>{FIELD_LABELS.stock_tank}</Label>
        <select
          id={`${id}-${pump.key}-stock`}
          value={pump.stock_tank ?? ""}
          aria-describedby={`${id}-${pump.key}-stock-help`}
          onChange={(event) => updatePump(pump.key, { stock_tank: event.target.value || null })}
        >
          <option value="">None</option>
          {named.map((tank) => {
            const by = others.find((item) => item.stock_tank === tank.id);
            return (
              <option key={tank.id} value={tank.id} disabled={!!by}>
                {tank.name}
                {by ? ` (linked to ${by.name.trim() || "another pump"})` : ""}
              </option>
            );
          })}
          {pump.stock_tank && !known && (
            <option value={pump.stock_tank}>{pump.stock_tank} (not found)</option>
          )}
        </select>
        <small id={`${id}-${pump.key}-stock-help`} className="muted">
          {tanksError
            ? `The stock tanks could not be read: ${tanksError}`
            : "What the pump doses is taken off this tank."}
        </small>
      </div>
    );
  };
  return (
    <div className="dosing-setup-body">
      <fieldset className="dosing-setup-group">
        <legend>Pumps, in the order the page shows them</legend>
        {draft.pumps.map((pump, index) => (
          <div className="dosing-setup-pump" key={pump.key} data-setup-pump={pump.key}>
            <div className="dosing-setup-pump-head">
              <div className="dosing-field">
                <Label htmlFor={`${id}-${pump.key}-name`}>Name</Label>
                <Input
                  id={`${id}-${pump.key}-name`}
                  value={pump.name}
                  maxLength={40}
                  // The button that opened the editor is gone: carry on from the first field.
                  autoFocus={index === 0}
                  onChange={(event) => updatePump(pump.key, { name: event.target.value })}
                />
              </div>
              <code className="dosing-mono" title="The pump's id in this room">
                {pump.id ?? newPumpId(pump.name, taken)}
              </code>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove ${pump.name || `pump ${index + 1}`}`}
                onClick={() =>
                  setDraft({
                    pumps: draft.pumps.filter((item) => item.key !== pump.key),
                    batch: {
                      ...draft.batch,
                      recipe: draft.batch.recipe.filter((line) => line.pump !== pump.key),
                    },
                  })
                }
              >
                <Trash2 size={16} />
              </Button>
            </div>
            <div className="dosing-setup-grid">
              {PUMP_FIELDS.map((field) => (
                <MappingPicker
                  key={field}
                  label={FIELD_LABELS[field]}
                  values={pump[field] ? [pump[field]] : []}
                  candidates={pick(field)}
                  hint={HINTS[field]}
                  onChange={(values) => updatePump(pump.key, { [field]: values[0] ?? "" })}
                />
              ))}
              {stockPicker(pump)}
              {pump.dosing_entity.startsWith("sensor.") && (
                <div className="dosing-field">
                  <Label htmlFor={`${id}-${pump.key}-prefix`}>{FIELD_LABELS.dosing_prefix}</Label>
                  <Input
                    id={`${id}-${pump.key}-prefix`}
                    value={pump.dosing_prefix}
                    onChange={(event) =>
                      updatePump(pump.key, { dosing_prefix: event.target.value })
                    }
                  />
                </div>
              )}
              <div className="dosing-field">
                <Label htmlFor={`${id}-${pump.key}-max`}>{FIELD_LABELS.max_ml}</Label>
                <Input
                  id={`${id}-${pump.key}-max`}
                  type="number"
                  min={1}
                  max={5000}
                  step={1}
                  value={Number.isFinite(pump.max_ml) ? String(pump.max_ml) : ""}
                  onChange={(event) => updatePump(pump.key, { max_ml: count(event.target.value) })}
                />
              </div>
              <label className="dosing-check">
                <input
                  type="checkbox"
                  checked={pump.restore_volume}
                  onChange={(event) =>
                    updatePump(pump.key, { restore_volume: event.target.checked })
                  }
                />
                Put the dose volume back after a single dose (firmware that keeps its batch recipe
                in that number)
              </label>
            </div>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          disabled={draft.pumps.length >= MAX_PUMPS}
          onClick={() =>
            setDraft({
              ...draft,
              pumps: [...draft.pumps, blankPump(`new-${Date.now()}-${draft.pumps.length}`)],
            })
          }
        >
          <Plus size={16} /> Add a pump
        </Button>
      </fieldset>
      <fieldset className="dosing-setup-group">
        <legend>Batch hardware</legend>
        <div className="dosing-setup-grid">
          {single("fill_valve")}
          {single("full_entity", !draft.batch.fill_valve)}
          <div className="dosing-field">
            <Label htmlFor={`${id}-full-state`}>{FIELD_LABELS.full_state}</Label>
            <Input
              id={`${id}-full-state`}
              value={draft.batch.full_state}
              onChange={(event) => updateBatch({ full_state: event.target.value })}
            />
          </div>
          {minutes("fill_timeout_min", 60)}
          {single("mix_pump")}
          <MappingPicker
            label={FIELD_LABELS.mix_valves}
            multiple
            values={draft.batch.mix_valves}
            candidates={pick("mix_valves")}
            hint={HINTS.mix_valves}
            choose="Choose switches"
            onChange={(values) => updateBatch({ mix_valves: values })}
          />
          {single("mix_power_sensor")}
          {minutes("mix_min_w", 100_000)}
          {minutes("premix_min", 30)}
          {minutes("postmix_min", 60)}
          <MappingPicker
            label={FIELD_LABELS.close_entities}
            multiple
            values={draft.batch.close_entities}
            candidates={pick("close_entities")}
            hint={HINTS.close_entities}
            choose="Choose switches"
            onChange={(values) => updateBatch({ close_entities: values })}
          />
          {single("hold_entity")}
          {single("filled_at_entity")}
        </div>
      </fieldset>
      <fieldset className="dosing-setup-group">
        <legend>Recipe, in dose order</legend>
        {!draft.batch.recipe.length && (
          <p className="muted small">No pump is in the recipe yet: a batch would only mix.</p>
        )}
        {draft.batch.recipe.map((line, index) => (
          <div className="dosing-setup-line" key={line.pump} data-setup-line={line.pump}>
            <span className="dosing-setup-order" aria-hidden="true">
              {index + 1}
            </span>
            <strong>{pumpName(line.pump)}</strong>
            <div className="dosing-field">
              <Label htmlFor={`${id}-${line.pump}-ml`}>mL</Label>
              <Input
                id={`${id}-${line.pump}-ml`}
                type="number"
                min={0}
                step={1}
                value={Number.isFinite(line.ml) ? String(line.ml) : ""}
                onChange={(event) =>
                  updateBatch({
                    recipe: draft.batch.recipe.map((item, i) =>
                      i === index ? { ...item, ml: count(event.target.value) } : item,
                    ),
                  })
                }
              />
            </div>
            <MappingPicker
              label={`${FIELD_LABELS.ml_entity} (optional)`}
              values={line.ml_entity ? [line.ml_entity] : []}
              candidates={pick("ml_entity")}
              hint={HINTS.ml_entity}
              onChange={(values) =>
                updateBatch({
                  recipe: draft.batch.recipe.map((item, i) =>
                    i === index ? { ...item, ml_entity: values[0] ?? null } : item,
                  ),
                })
              }
            />
            <div className="dosing-setup-line-actions">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Move ${pumpName(line.pump)} earlier`}
                disabled={index === 0}
                onClick={() => moveLine(index, -1)}
              >
                <ArrowUp size={16} />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Move ${pumpName(line.pump)} later`}
                disabled={index === draft.batch.recipe.length - 1}
                onClick={() => moveLine(index, 1)}
              >
                <ArrowDown size={16} />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Take ${pumpName(line.pump)} out of the recipe`}
                onClick={() =>
                  updateBatch({ recipe: draft.batch.recipe.filter((_, i) => i !== index) })
                }
              >
                <Trash2 size={16} />
              </Button>
            </div>
          </div>
        ))}
        {!!unused.length && (
          <div className="dosing-field dosing-setup-add">
            <Label htmlFor={`${id}-add-line`}>Add a pump to the recipe</Label>
            <select
              id={`${id}-add-line`}
              value=""
              onChange={(event) =>
                event.target.value &&
                updateBatch({
                  recipe: [
                    ...draft.batch.recipe,
                    { pump: event.target.value, ml: 0, ml_entity: null },
                  ],
                })
              }
            >
              <option value="">Choose a pump…</option>
              {unused.map((pump, index) => (
                <option key={pump.key} value={pump.key}>
                  {pump.name || `Pump ${index + 1}`}
                </option>
              ))}
            </select>
          </div>
        )}
      </fieldset>
      {!!errors.length && (
        <ul className="workspace-message error" role="alert">
          {errors.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
      {error && !review && (
        <p className="workspace-message error" role="alert">
          {error}
        </p>
      )}
      <div className="dosing-setup-actions">
        <Button variant="ghost" onClick={() => setDraft(null)}>
          Cancel
        </Button>
        <Button
          disabled={!!errors.length || !dirty || !connected}
          onClick={() => {
            setError("");
            setReview(true);
          }}
        >
          Review dosing setup
        </Button>
      </div>
      <Dialog open={review} onOpenChange={(open) => !busy && setReview(open)}>
        <DialogContent className="review-dialog">
          <DialogHeader>
            <DialogTitle>Save the dosing setup?</DialogTitle>
            <DialogDescription>
              {controller.demo ? "Demo only. " : ""}This changes {controller.room.room.name}'s
              dosing only. Nothing is switched or started: the controller reads the new setup and
              uses it for the next dose or batch.
            </DialogDescription>
          </DialogHeader>
          <div className="review-list">
            {changes.map((change) => (
              <div className="review-row" key={change.label}>
                <strong>{change.label}</strong>
                <span>
                  {change.before} <span aria-hidden="true">→</span> <b>{change.after}</b>
                </span>
              </div>
            ))}
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setReview(false)}>
              Back to editing
            </Button>
            <Button disabled={busy || !changes.length} onClick={() => void save()}>
              {busy && <LoaderCircle className="spin" size={16} />}
              {busy ? "Saving…" : "Save dosing setup"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** The setup as it stands, to read. */
function SetupSummary({
  config,
  tanks,
}: {
  config: DosingConfig;
  tanks: { id: string; name: string }[];
}) {
  const batch = config.batch;
  const entity = (id: string | null) => (id ? <code className="dosing-mono">{id}</code> : "none");
  return (
    <>
      {config.pumps.length ? (
        <div className="table-scroll" tabIndex={0} aria-label="Dosing pumps and their hardware">
          <table className="data-table dosing-setup-table">
            <thead>
              <tr>
                <th>Pump</th>
                {PUMP_FIELDS.map((field) => (
                  <th key={field}>{FIELD_LABELS[field]}</th>
                ))}
                <th>{FIELD_LABELS.stock_tank}</th>
                <th className="numeric">Largest dose</th>
              </tr>
            </thead>
            <tbody>
              {config.pumps.map((pump) => (
                <tr key={pump.id}>
                  <td>
                    {pump.name}
                    <span className="cell-subtext dosing-mono">{pump.id}</span>
                  </td>
                  {PUMP_FIELDS.map((field) => (
                    <td key={field}>{entity(pump[field])}</td>
                  ))}
                  <td>
                    {pump.stock_tank
                      ? (tanks.find((tank) => tank.id === pump.stock_tank)?.name ?? pump.stock_tank)
                      : "none"}
                  </td>
                  <td className="numeric">{pump.max_ml} mL</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">No dosing pumps are mapped in this room.</p>
      )}
      <dl className="dosing-setup-facts">
        {OPTIONAL_BATCH.map((field) => (
          <div key={field}>
            <dt>{FIELD_LABELS[field]}</dt>
            <dd>{entity(batch[field])}</dd>
          </div>
        ))}
        <div>
          <dt>{FIELD_LABELS.mix_valves}</dt>
          <dd>{batch.mix_valves.length ? batch.mix_valves.map((id) => entity(id)) : "none"}</dd>
        </div>
        <div>
          <dt>{FIELD_LABELS.close_entities}</dt>
          <dd>
            {batch.close_entities.length ? batch.close_entities.map((id) => entity(id)) : "none"}
          </dd>
        </div>
        <div>
          <dt>Timing</dt>
          <dd>
            Fill up to {batch.fill_timeout_min} min · mix {batch.premix_min} min before and{" "}
            {batch.postmix_min} min after dosing
            {batch.mix_min_w > 0 ? ` · the mixing pump must draw ${batch.mix_min_w} W` : ""}
          </dd>
        </div>
      </dl>
    </>
  );
}
