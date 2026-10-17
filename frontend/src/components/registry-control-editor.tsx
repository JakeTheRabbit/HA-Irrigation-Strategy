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
  return (
    <fieldset className="features-control" disabled={readOnly}>
      <legend>
        {label}
        <span className="features-default">
          Default: {shown(row.control.default)}
          {readOnly && " · read-only"}
        </span>
      </legend>
      <table>
        <tbody>
          {cells.map((cell) => {
            const value = staged[cell.entityId] ?? cell.value;
            const unit = String(cell.entity.attributes.unit_of_measurement || "");
            const off = !isDefault(row.control, value);
            return (
              <tr key={cell.entityId} data-changed={off || undefined}>
                <th scope="row">{zoneName(cell.zone)}</th>
                <td>
                  {row.control.domain === "switch" ? (
                    <input
                      type="checkbox"
                      role="switch"
                      aria-label={`${label} ${zoneName(cell.zone)}`}
                      checked={value === true}
                      onChange={(e) => onChange(cell, e.target.checked)}
                    />
                  ) : row.control.domain === "select" ? (
                    <select
                      aria-label={`${label} ${zoneName(cell.zone)}`}
                      value={String(value ?? "")}
                      onChange={(e) => onChange(cell, e.target.value)}
                    >
                      {(Array.isArray(cell.entity.attributes.options)
                        ? (cell.entity.attributes.options as string[])
                        : []
                      ).map((o) => (
                        <option key={o}>{o}</option>
                      ))}
                    </select>
                  ) : (
                    <span className="features-number">
                      <Input
                        type="number"
                        inputMode="decimal"
                        aria-label={`${label} ${zoneName(cell.zone)}`}
                        value={value === null ? "" : String(value)}
                        step={Number(cell.entity.attributes.step) || "any"}
                        min={Number(cell.entity.attributes.min)}
                        max={Number(cell.entity.attributes.max)}
                        onChange={(e) => {
                          const n = Number(e.target.value);
                          if (e.target.value !== "" && Number.isFinite(n)) onChange(cell, n);
                        }}
                      />
                      {unit && <span className="unit">{unit}</span>}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </fieldset>
  );
}
