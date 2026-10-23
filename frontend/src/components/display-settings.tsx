import { useRef, useState } from "react";
import { Check, Eye, EyeOff, LoaderCircle } from "lucide-react";
import { ReviewDialog } from "@/components/dashboard";
import { InfoTip } from "@/components/info-tip";
import {
  DISPLAY_ROWS,
  displayEntityId,
  unitExamples,
  type DisplayOptions,
  type DisplayRow,
  type UnitKey,
} from "@/lib/display";
import {
  getDisplayUnits,
  readDisplayUnits,
  setDisplayUnits,
  UNITS_STORAGE_KEY,
  type DisplayUnits,
} from "@/lib/display-units";
import { callV2 } from "@/lib/parity-api";
import { clock } from "@/lib/time";
import type { Controller } from "@/lib/types";
import "./display-settings.css";

const ON_OFF = [
  { value: false, label: "Off", icon: EyeOff },
  { value: true, label: "On", icon: Eye },
] as const;

/** Settings › Display: which extra panels the dashboard shows in this room. Each row is off until
 * someone turns it on; a change is reviewed, then saved for everyone who opens the room. A row kept
 * in a switch of its own (the Hardware panel) writes that switch, and only an administrator may. */
export function DisplaySettings({ controller }: { controller: Controller }) {
  const display = controller.room.display;
  const prefix = controller.room.room.prefix;
  const [pending, setPending] = useState<{ row: DisplayRow; value: boolean | string } | null>(null);
  const connected = ["live", "demo"].includes(controller.connection);
  const words = (row: DisplayRow, value: boolean | string) =>
    row.choice?.find((c) => c.value === value)?.label ?? (value ? "On" : "Off");
  const valueOf = (row: DisplayRow): boolean | string | null => {
    if (!row.entity) return display.options[row.key as keyof DisplayOptions] as boolean | string;
    const state = controller.states[row.entity(prefix)]?.state;
    return state === "on" ? true : state === "off" ? false : null;
  };
  const writable = (row: DisplayRow) =>
    connected &&
    (row.entity
      ? valueOf(row) !== null && controller.admin !== false
      : display.available);
  const groups = [...new Set(DISPLAY_ROWS.map((row) => row.group))];
  const entityId = pending?.row.entity
    ? pending.row.entity(prefix)
    : `${displayEntityId(prefix)}.${pending?.row.key}`;
  return (
    <div className="display-settings" data-display-settings>
      {!display.available && (
        <p className="small muted">This needs the updated Crop Steering integration.</p>
      )}
      {groups.map((group) => (
        <div key={group} className="display-group">
          <h3>{group}</h3>
          {DISPLAY_ROWS.filter((row) => row.group === group).map((row) => {
            const current = valueOf(row);
            const options = row.choice
              ? row.choice.map((c) => ({ value: c.value, label: c.label, icon: undefined }))
              : ON_OFF;
            return (
              <div key={row.key} className="display-row" data-display-option={row.key}>
                <span className="label-with-tip">
                  <span id={`display-${row.key}`}>{row.label}</span>
                  <InfoTip label={row.label} copy={row.copy} />
                </span>
                <div
                  className="theme-options display-options"
                  role="group"
                  aria-labelledby={`display-${row.key}`}
                >
                  {options.map((option) => (
                    <button
                      key={String(option.value)}
                      className={current === option.value ? "chosen" : ""}
                      aria-pressed={current === option.value}
                      disabled={!writable(row)}
                      onClick={() =>
                        current !== option.value && setPending({ row, value: option.value })
                      }
                    >
                      {option.icon && <option.icon size={18} />}
                      <span>{option.label}</span>
                      {current === option.value && <Check size={16} />}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ))}
      <ReviewDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        controller={controller}
        title="Review the display option"
        items={
          pending
            ? [
                {
                  change: { entityId, value: pending.value },
                  label: pending.row.label,
                  before: words(pending.row, valueOf(pending.row) ?? false),
                  after: words(pending.row, pending.value),
                },
              ]
            : []
        }
        note="Changes what the dashboard shows for everyone who opens this room. It does not change watering, a setpoint or hardware."
        run={
          pending?.row.entity
            ? undefined
            : async () => {
                if (!pending) return;
                await controller.operator("display_save", {
                  expected_revision: display.revision,
                  options: { [pending.row.key]: pending.value } as Partial<DisplayOptions>,
                });
              }
        }
      />
    </div>
  );
}

type UnitValue = string | number;
/** The four unit rows: each option's value as display_save takes it, and as the display store
 * (lib/display-units) holds it. */
const UNIT_ROWS: {
  key: UnitKey;
  store: keyof DisplayUnits;
  label: string;
  example: "ec" | "temp" | "volume" | "clock";
  options: { value: UnitValue; label: string; shown: string }[];
}[] = [
  {
    key: "ec_unit",
    store: "ec",
    label: "EC",
    example: "ec",
    options: [
      { value: "mS/cm", label: "mS/cm", shown: "mS/cm" },
      { value: "ppm500", label: "PPM 500", shown: "ppm500" },
      { value: "ppm700", label: "PPM 700", shown: "ppm700" },
    ],
  },
  {
    key: "temp_unit",
    store: "temp",
    label: "Temperature",
    example: "temp",
    options: [
      { value: "C", label: "°C", shown: "C" },
      { value: "F", label: "°F", shown: "F" },
    ],
  },
  {
    key: "volume_unit",
    store: "volume",
    label: "Volume",
    example: "volume",
    options: [
      { value: "L", label: "Litres", shown: "L" },
      { value: "gal", label: "US gallons", shown: "gal" },
    ],
  },
  {
    key: "clock",
    store: "clock",
    label: "Clock",
    example: "clock",
    options: [
      { value: 24, label: "24 h", shown: "24" },
      { value: 12, label: "12 h", shown: "12" },
    ],
  },
];

/** What a row last did: busy, a receipt (with Undo while it can still be put back), or a refusal. */
type RowResult =
  | { kind: "busy" }
  | { kind: "saved"; text: string; undo: { before: UnitValue; after: UnitValue } | null }
  | { kind: "error"; text: string };

const UNCONFIRMED = "The controller did not confirm the values. Reload and check before trying again.";
const BLOCKED = "This browser blocked storage. The units stay as they are.";
/** The field of this browser's stored choice (3.17) for each unit, as display-units reads it. */
const LOCAL_FIELD: Record<UnitKey, keyof DisplayUnits> = {
  ec_unit: "ec",
  temp_unit: "temp",
  volume_unit: "volume",
  clock: "clock",
};

/** This browser's stored unit choice; null when storage is blocked. */
function readLocal(): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(UNITS_STORAGE_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : {};
  } catch {
    return null;
  }
}

/** Settings › Units: EC, temperature, volume and the clock for this room, each with a live example
 * through the display store. Saved in the room's display store (integration 3.18) and read back,
 * else in this browser only. A saved choice is undone, not confirmed first. */
export function UnitSettings({ controller }: { controller: Controller }) {
  const display = controller.room.display;
  const roomId = controller.room.room.id;
  const local = !display.units;
  const [results, setResults] = useState<Partial<Record<UnitKey, RowResult>>>({});
  const [, rerender] = useState(0);
  /** The newest revision this page read back: the sensor may not have caught up with a save yet. */
  const revision = useRef(0);
  const connected = ["live", "demo"].includes(controller.connection);
  const blocked = !local && (!connected || controller.admin === false);
  const units = getDisplayUnits();
  const examples = unitExamples(controller.states, controller.room);
  const now = () => clock(Date.now(), controller.timeZone);
  const set = (key: UnitKey, result: RowResult) => setResults((r) => ({ ...r, [key]: result }));

  /** The room's stored value of `key`, read from the integration; undefined when it did not answer. */
  async function readBack(key: UnitKey): Promise<unknown> {
    const got = await callV2<{ revision: number; options: Record<string, unknown> }>(
      controller,
      "display_get",
      { room_id: roomId },
    );
    if (got.kind !== "ok") return undefined;
    revision.current = Math.max(revision.current, got.data.revision);
    return got.data.options[key];
  }
  /** The value stored now: the room's (read from the integration) or this browser's. */
  async function storedNow(key: UnitKey): Promise<string | undefined> {
    const value = local ? readLocal()?.[LOCAL_FIELD[key]] : await readBack(key);
    return value === undefined || value === null ? undefined : String(value);
  }
  /** Writes one unit, then reads it back. */
  async function write(key: UnitKey, value: UnitValue): Promise<{ verified: boolean; error?: string }> {
    if (local) {
      const stored = readLocal();
      if (stored === null) return { verified: false, error: BLOCKED };
      const field = LOCAL_FIELD[key];
      try {
        localStorage.setItem(
          UNITS_STORAGE_KEY,
          JSON.stringify({ ...stored, [field]: field === "clock" ? String(value) : value }),
        );
      } catch {
        return { verified: false, error: BLOCKED };
      }
      setDisplayUnits(readDisplayUnits(undefined, localStorage.getItem(UNITS_STORAGE_KEY)));
      rerender((n) => n + 1);
      return { verified: (await storedNow(key)) === String(value) };
    }
    const saved = await callV2(controller, "display_save", {
      room_id: roomId,
      expected_revision: Math.max(display.revision, revision.current),
      options: { [key]: value },
    });
    if (saved.kind === "missing") return { verified: false, error: "Needs integration 3.18." };
    if (saved.kind === "error") return { verified: false, error: saved.message };
    return { verified: (await readBack(key)) === value };
  }
  async function choose(key: UnitKey, before: UnitValue, value: UnitValue) {
    set(key, { kind: "busy" });
    const done = await write(key, value);
    if (done.error) set(key, { kind: "error", text: done.error });
    else if (!done.verified) set(key, { kind: "error", text: UNCONFIRMED });
    else set(key, { kind: "saved", text: `Saved and read back ${now()}`, undo: { before, after: value } });
  }
  async function undo(key: UnitKey, change: { before: UnitValue; after: UnitValue }) {
    set(key, { kind: "busy" });
    // Put back only what this page saved: a value changed since stays as it is.
    if ((await storedNow(key)) !== String(change.after))
      return set(key, {
        kind: "error",
        text: "Changed since you saved it, so it was not put back. Check the value above.",
      });
    const done = await write(key, change.before);
    if (done.error) set(key, { kind: "error", text: done.error });
    else if (!done.verified) set(key, { kind: "error", text: UNCONFIRMED });
    else set(key, { kind: "saved", text: `Put back and read back ${now()}`, undo: null });
  }

  return (
    <div className="unit-settings" data-unit-settings>
      <div className="unit-head">
        <h2 id="units-title">Units</h2>
        <p>
          {local
            ? "Saved on this browser only until integration 3.18"
            : "Shown on every page and phone for this room"}
        </p>
      </div>
      {blocked && (
        <p className="small muted">
          {connected
            ? "Only an administrator can change the units of this room."
            : "Connect to Home Assistant to change the units."}
        </p>
      )}
      {UNIT_ROWS.map((row) => {
        const shown = String(units[row.store]);
        const current = row.options.find((o) => o.shown === shown) ?? row.options[0];
        const result = results[row.key];
        return (
          <div key={row.key} className="unit-row" data-unit={row.key}>
            <span className="unit-label" id={`unit-${row.key}`}>
              {row.label}
            </span>
            <div className="unit-choice" role="group" aria-labelledby={`unit-${row.key}`}>
              {row.options.map((option) => (
                <button
                  key={String(option.value)}
                  type="button"
                  className={option === current ? "chosen" : ""}
                  aria-pressed={option === current}
                  disabled={blocked || result?.kind === "busy"}
                  onClick={() =>
                    option !== current && void choose(row.key, current.value, option.value)
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>
            <span className="unit-example" data-unit-example={row.example}>
              {examples[row.example]}
            </span>
            {result && (
              <p
                className={`unit-result ${result.kind === "error" ? "error-text" : "success-text"}`}
                role={result.kind === "error" ? "alert" : "status"}
              >
                {result.kind === "busy" ? (
                  <>
                    <LoaderCircle size={14} className="spin" /> Saving…
                  </>
                ) : (
                  result.text
                )}
                {result.kind === "saved" && result.undo && (
                  <button
                    type="button"
                    className="unit-undo"
                    onClick={() => result.undo && void undo(row.key, result.undo)}
                  >
                    Undo
                  </button>
                )}
              </p>
            )}
          </div>
        );
      })}
      <p className="small muted unit-foot">
        Display only. Readings stay stored in mS/cm, °C and litres, so switching back shows exactly
        the same numbers.
      </p>
    </div>
  );
}
