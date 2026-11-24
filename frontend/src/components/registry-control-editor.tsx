import { Input } from "@/components/ui/input";
import { isDefault, type ControlRow, type Cell, type Value } from "@/lib/features";
import { settingWords } from "@/lib/setting-words";
type Staged = Record<string, Value>;
function controlLabel(row: ControlRow): string {
  const key = row.control.key;
  return (
    row.control.label ??
    settingWords(key)?.label ??
    key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
  );
}

function shown(value: Value | null | undefined, unit = ""): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "On" : "Off";
  return `${value}${unit ? ` ${unit}` : ""}`;
}

export function ControlEditor({
  row,
  staged,
  readOnly,
  zoneName,
  onChange,
}: {
  row: ControlRow;
  staged: Staged;
  readOnly: boolean;
  zoneName: (id: number | null) => string;
  onChange: (cell: Cell, value: Value) => void;
}) {
  const label = controlLabel(row);
  const cells = [row.room, ...row.zones].filter((c): c is Cell => c !== null);
  const defaultMeta = [
    shown(row.control.default) !== "—" && `Default: ${shown(row.control.default)}`,
    readOnly && "read-only",
  ]
    .filter(Boolean)
    .join(" · ");

  const renderInput = (cell: Cell) => {
    const value = staged[cell.entityId] ?? cell.value;
    const unit = String(cell.entity.attributes.unit_of_measurement || "");
    if (row.control.domain === "switch") {
      return (
        <input
          type="checkbox"
          role="switch"
          aria-label={`${label} ${zoneName(cell.zone)}`}
          checked={value === true}
          disabled={readOnly}
          onChange={(e) => onChange(cell, e.target.checked)}
        />
      );
    }
    if (row.control.domain === "select") {
      return (
        <select
          aria-label={`${label} ${zoneName(cell.zone)}`}
          value={String(value ?? "")}
          disabled={readOnly}
          onChange={(e) => onChange(cell, e.target.value)}
        >
          {(Array.isArray(cell.entity.attributes.options)
            ? (cell.entity.attributes.options as string[])
            : []
          ).map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      );
    }
    return (
      <span className="features-number">
        <Input
          type="number"
          inputMode="decimal"
          aria-label={`${label} ${zoneName(cell.zone)}`}
          value={value === null ? "" : String(value)}
          step={Number(cell.entity.attributes.step) || "any"}
          min={Number(cell.entity.attributes.min)}
          max={Number(cell.entity.attributes.max)}
          disabled={readOnly}
          onChange={(e) => {
            const n = Number(e.target.value);
            if (e.target.value !== "" && Number.isFinite(n)) onChange(cell, n);
          }}
        />
        {unit && <span className="unit">{unit}</span>}
      </span>
    );
  };

  if (cells.length === 1) {
    const cell = cells[0];
    const value = staged[cell.entityId] ?? cell.value;
    const off = !isDefault(row.control, value);
    return (
      <div
        className="features-control features-single-row"
        data-changed={off || undefined}
        data-disabled={readOnly || undefined}
      >
        <div className="features-single-label">
          <span className="features-single-title">{label}</span>
          {defaultMeta && <span className="features-default">{defaultMeta}</span>}
        </div>
        <div className="features-single-input">{renderInput(cell)}</div>
      </div>
    );
  }

  return (
    <fieldset className="features-control" disabled={readOnly}>
      <legend>
        {label}
        {/* A default is said only when there is one. */}
        {defaultMeta && <span className="features-default">{defaultMeta}</span>}
      </legend>
      <table>
        <tbody>
          {cells.map((cell) => {
            const value = staged[cell.entityId] ?? cell.value;
            const off = !isDefault(row.control, value);
            return (
              <tr key={cell.entityId} data-changed={off || undefined}>
                <th scope="row">{zoneName(cell.zone)}</th>
                <td>{renderInput(cell)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </fieldset>
  );
}
