import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { findSession } from "@/lib/client";
import { catchTest } from "@/lib/catch-test";
import {
  SUBSTRATE_PRESETS,
  SUBSTRATE_PRESET_GROUPS,
  matchPreset,
  presetLabel,
} from "@/lib/substrate-presets";
import {
  SIZING_BOUNDS,
  SIZING_UNITS,
  displayNumber,
  fromMetric,
  initialUnitSystem,
  metricNote,
  sizingError,
  sizingLabel,
  toMetric,
  unitSystemFromHass,
  type SizingKey,
  type SizingUnit,
  type UnitSystem,
} from "@/lib/units";

/** Helpers beside the zone sizing fields. Each one only fills the local setup draft, in
 * litres and L/h; saving still goes through "Review configuration". */
type Quantity = keyof typeof SIZING_UNITS;
const STORAGE: Record<Quantity, string> = {
  volume: "crop-steering-unit-volume",
  flow: "crop-steering-unit-flow",
};
function remembered(quantity: Quantity): string | null {
  try {
    return localStorage.getItem(STORAGE[quantity]);
  } catch {
    return null;
  }
}
export interface SizingUnits {
  systems: Record<Quantity, UnitSystem>;
  choose: (quantity: Quantity, system: UnitSystem) => void;
  volume: SizingUnit;
  flow: SizingUnit;
}
export function useSizingUnits(): SizingUnits {
  const [systems, setSystems] = useState<Record<Quantity, UnitSystem>>(() => {
    const homeAssistant = unitSystemFromHass(findSession());
    return {
      volume: initialUnitSystem(homeAssistant, remembered("volume")),
      flow: initialUnitSystem(homeAssistant, remembered("flow")),
    };
  });
  return {
    systems,
    choose: (quantity, system) => {
      setSystems((current) => ({ ...current, [quantity]: system }));
      try {
        localStorage.setItem(STORAGE[quantity], system);
      } catch {
        /* The choice still applies on this page. */
      }
    },
    volume: SIZING_UNITS.volume[systems.volume],
    flow: SIZING_UNITS.flow[systems.flow],
  };
}

export function SizingUnitPickers({ units, disabled }: { units: SizingUnits; disabled: boolean }) {
  return (
    <div className="workspace-form-grid sizing-units" role="group" aria-label="Sizing units">
      {(
        [
          ["volume", "Pot volume unit"],
          ["flow", "Dripper flow unit"],
        ] as const
      ).map(([quantity, label]) => (
        <div key={quantity}>
          <Label htmlFor={"sizing-unit-" + quantity}>{label}</Label>
          <select
            id={"sizing-unit-" + quantity}
            disabled={disabled}
            value={units.systems[quantity]}
            onChange={(event) => units.choose(quantity, event.target.value as UnitSystem)}
          >
            {(["metric", "us"] as const).map((system) => (
              <option key={system} value={system}>
                {SIZING_UNITS[quantity][system].name}
              </option>
            ))}
          </select>
        </div>
      ))}
      <p className="small muted">
        A unit only changes what you type and read on this page. Pot volume is always saved in
        litres and dripper flow in L/h.
      </p>
    </div>
  );
}

/** Number field that shows and accepts `unit` while the draft (`value`) stays metric. */
export function SizingField({
  id,
  sizingKey,
  unit,
  value,
  disabled,
  onChange,
}: {
  id: string;
  sizingKey: SizingKey;
  unit: SizingUnit;
  value: number;
  disabled: boolean;
  onChange: (metric: number) => void;
}) {
  const shown = () => displayNumber(fromMetric(value, unit));
  const [entry, setEntry] = useState({ value, unit, text: shown() });
  let text = entry.text;
  // The draft moved without this field being typed in (preset, catch test, discard, reload),
  // or the unit changed: show the draft again instead of the stale keystrokes.
  if (!Object.is(entry.value, value) || entry.unit !== unit) {
    text = shown();
    setEntry({ value, unit, text });
  }
  const error = sizingError(value, sizingKey, unit),
    note = metricNote(value, sizingKey, unit),
    { min, max } = SIZING_BOUNDS[sizingKey],
    metric = unit.factor === 1;
  return (
    <div>
      <Label htmlFor={id}>{sizingLabel(sizingKey, unit)}</Label>
      <Input
        id={id}
        type="number"
        min={metric ? min : Math.ceil((min / unit.factor) * 1000) / 1000}
        max={metric ? max : Math.floor((max / unit.factor) * 1000) / 1000}
        step={metric ? 0.1 : "any"}
        disabled={disabled}
        value={text}
        aria-invalid={Boolean(error)}
        aria-describedby={id + "-note"}
        onChange={(event) => {
          const typed = event.target.value;
          const next = toMetric(typed === "" ? NaN : Number(typed), unit);
          setEntry({ value: next, unit, text: typed });
          onChange(next);
        }}
      />
      <p id={id + "-note"} className={error ? "field-error" : "small muted"}>
        {error || note}
      </p>
    </div>
  );
}

export function SubstratePresetPicker({
  id,
  volumeFieldId,
  litres,
  disabled,
  onPick,
}: {
  id: string;
  volumeFieldId: string;
  litres: number;
  disabled: boolean;
  onPick: (litres: number) => void;
}) {
  return (
    <div>
      <Label htmlFor={id}>Substrate preset</Label>
      <select
        id={id}
        disabled={disabled}
        value={matchPreset(litres)?.id ?? "custom"}
        aria-describedby={id + "-note"}
        onChange={(event) => {
          const preset = SUBSTRATE_PRESETS.find((item) => item.id === event.target.value);
          if (preset) onPick(preset.litres);
          else document.getElementById(volumeFieldId)?.focus();
        }}
      >
        <option value="custom">Custom · type the pot volume</option>
        {SUBSTRATE_PRESET_GROUPS.map((group) => (
          <optgroup key={group.id} label={group.label}>
            {SUBSTRATE_PRESETS.filter((item) => item.group === group.id).map((item) => (
              <option key={item.id} value={item.id}>
                {presetLabel(item)}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <p id={id + "-note"} className="small muted">
        Nursery “trade” pots often hold less than their nominal gallons, and shot sizes are a
        percentage of this volume, so measure it if unsure.
      </p>
    </div>
  );
}

export function CatchTestCalculator({
  id,
  zoneName,
  flowUnit,
  disabled,
  onUse,
}: {
  id: string;
  zoneName: string;
  flowUnit: SizingUnit;
  disabled: boolean;
  onUse: (litresPerHour: number) => void;
}) {
  const [seconds, setSeconds] = useState(""),
    [ml, setMl] = useState("");
  const result = seconds.trim() && ml.trim() ? catchTest(Number(ml), Number(seconds)) : null;
  const wrong = (field: "seconds" | "ml") =>
    !!result && result.flow === null && (result.field === field || result.field === "both");
  return (
    <details id={id} className="catch-test">
      <summary>Work out dripper flow from a catch test</summary>
      <p className="small muted">
        Run one dripper into a measuring cup, time it, then enter what that one dripper delivered.
        This calculator only does the arithmetic: it never opens a valve or runs a pump, so start
        and stop the water yourself.
      </p>
      <div className="workspace-form-grid">
        <div>
          <Label htmlFor={id + "-seconds"}>Run time · seconds</Label>
          <Input
            id={id + "-seconds"}
            type="number"
            min="0"
            step="1"
            placeholder="e.g. 60"
            disabled={disabled}
            value={seconds}
            aria-invalid={wrong("seconds")}
            aria-describedby={id + "-result"}
            onChange={(event) => setSeconds(event.target.value)}
          />
        </div>
        <div>
          <Label htmlFor={id + "-ml"}>Water caught from one dripper · mL</Label>
          <Input
            id={id + "-ml"}
            type="number"
            min="0"
            step="1"
            placeholder="e.g. 65"
            disabled={disabled}
            value={ml}
            aria-invalid={wrong("ml")}
            aria-describedby={id + "-result"}
            onChange={(event) => setMl(event.target.value)}
          />
        </div>
      </div>
      <p
        id={id + "-result"}
        className={result?.error ? "field-error" : "catch-test-result"}
        role="status"
      >
        {!result ? (
          "Enter both values to see the flow."
        ) : result.flow === null ? (
          result.error
        ) : (
          <>
            Flow per dripper: <strong>{result.flow} L/h</strong>
            {flowUnit.factor !== 1 &&
              ` (${displayNumber(fromMetric(result.flow, flowUnit))} ${flowUnit.symbol})`}
          </>
        )}
      </p>
      <Button
        type="button"
        variant="outline"
        className="sizing-action"
        disabled={disabled || !result || result.flow === null}
        onClick={() => {
          if (result && result.flow !== null) onUse(result.flow);
        }}
      >
        {result && result.flow !== null
          ? `Use ${result.flow} L/h as ${zoneName} dripper flow`
          : "Use the result as dripper flow"}
      </Button>
      <p className="small muted">
        Using the result fills the dripper flow field in this draft only. Nothing is saved until you
        review and save the configuration.
      </p>
    </details>
  );
}
