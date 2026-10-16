import { useMemo, useState } from "react";
import { ExternalLink, RotateCcw, Search, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Heading, ReviewDialog, type ReviewItem } from "@/components/dashboard";
import { InfoTip } from "@/components/info-tip";
import { SETTING_COPY } from "@/lib/ste-copy";
import { settingWords } from "@/lib/setting-words";
import {
  APP_OPTIONS,
  GROUPS,
  featureRows,
  isDefault,
  matches,
  resetChanges,
  type Cell,
  type ControlRow,
  type FeatureRow,
  type Value,
} from "@/lib/features";
import type { Controller } from "@/lib/types";
import type { Page } from "@/lib/routes";
import { pageLabel } from "@/components/page-tabs";
import "./features.css";

type Staged = Record<string, Value>;

/** A control's name: the setting words where they exist, else the key in words. */
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

/** Settings > Features: every switch and setting of the room, from the feature registry. */
export function Features({ controller }: { controller: Controller }) {
  const { room } = controller;
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState<string>("all");
  const [changedOnly, setChangedOnly] = useState(false);
  const [staged, setStaged] = useState<Staged>({});
  const [open, setOpen] = useState<string | null>(null);
  const [review, setReview] = useState(false);
  const locked = controller.admin === false;
  const planOwns = room.strategy.engaged;
  const rows = useMemo(
    () =>
      featureRows(
        controller.states,
        room.room.prefix,
        room.zones.map((z) => z.id),
        room.engine.entityId,
      ),
    [controller.states, room],
  );
  const visible = rows.filter(
    (r) =>
      (group === "all" || r.feature.group === group) &&
      (!changedOnly || r.changed) &&
      matches(r, query),
  );
  const zoneName = (id: number | null) =>
    id === null ? "Room" : (room.zones.find((z) => z.id === id)?.name ?? `Zone ${id}`);
  const stage = (entityId: string, value: Value, current: Value | null) =>
    setStaged((s) => {
      const next = { ...s };
      if (value === current) delete next[entityId];
      else next[entityId] = value;
      return next;
    });
  const cellOf = (entityId: string): { row: ControlRow; cell: Cell } | null => {
    for (const f of rows)
      for (const r of [f.master, ...f.settings])
        for (const c of r ? [r.room, ...r.zones] : [])
          if (c && c.entityId === entityId) return { row: r!, cell: c };
    return null;
  };
  const items: ReviewItem[] = Object.entries(staged).flatMap(([entityId, value]) => {
    const found = cellOf(entityId);
    if (!found) return [];
    const unit = String(found.cell.entity.attributes.unit_of_measurement || "");
    return [
      {
        change: { entityId, value },
        label: `${controlLabel(found.row)} · ${zoneName(found.cell.zone)}`,
        before: shown(found.cell.value, unit),
        after: shown(value, unit),
      },
    ];
  });
  const readOnly = (domain: string) =>
    locked || (planOwns && (domain === "number" || domain === "select"));
  const current = rows.find((r) => r.feature.id === open) ?? null;

  return (
    <>
      <Heading
        title="Features"
        description="Each feature of the room in one list. Changes apply only after you review them."
      />
      <div className="features-toolbar">
        <label className="features-search">
          <Search size={16} aria-hidden="true" />
          <Input
            type="search"
            placeholder="Search features"
            aria-label="Search features"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          aria-label="Group"
          value={group}
          onChange={(e) => setGroup(e.target.value)}
          className="features-group-select"
        >
          <option value="all">All groups</option>
          {GROUPS.map((g) => (
            <option key={g.id} value={g.id}>
              {g.label}
            </option>
          ))}
        </select>
        <label className="features-changed">
          <input
            type="checkbox"
            checked={changedOnly}
            onChange={(e) => setChangedOnly(e.target.checked)}
          />
          Changed from default
        </label>
      </div>
      {locked && (
        <p className="notice-inline">Only a Home Assistant administrator can change features.</p>
      )}
      {planOwns && (
        <p className="notice-inline">
          An active grow plan owns the numbers and selects. Disarm the plan to change them here.
        </p>
      )}
      {GROUPS.filter((g) => g.id !== "app").map((g) => {
        const list = visible.filter((r) => r.feature.group === g.id);
        if (!list.length) return null;
        return (
          <section key={g.id} className="panel features-group" aria-labelledby={`fg-${g.id}`}>
            <div className="panel-heading">
              <h2 id={`fg-${g.id}`}>{g.label}</h2>
              <p>{g.help}</p>
            </div>
            <ul className="features-list">
              {list.map((r) => (
                <FeatureItem
                  key={r.feature.id}
                  row={r}
                  staged={staged}
                  disabled={locked}
                  zoneCount={room.zones.length}
                  onToggle={(cell, on) => stage(cell.entityId, on, cell.value)}
                  onConfigure={() => setOpen(r.feature.id)}
                  onReset={() => {
                    for (const c of resetChanges(r)) {
                      const found = cellOf(c.entityId);
                      if (found && !readOnly(found.row.control.domain))
                        stage(c.entityId, c.value, found.cell.value);
                    }
                  }}
                />
              ))}
            </ul>
          </section>
        );
      })}
      {(group === "all" || group === "app") && !changedOnly && (
        <AppOptions query={query} />
      )}
      {!visible.length && group !== "app" && (
        <p className="features-empty">No feature matches.</p>
      )}
      {items.length > 0 && (
        <div className="features-apply" role="region" aria-label="Changes to review">
          <span>
            {items.length} change{items.length === 1 ? "" : "s"} not applied
          </span>
          <Button variant="outline" onClick={() => setStaged({})}>
            Discard
          </Button>
          <Button onClick={() => setReview(true)} disabled={locked}>
            Review {items.length} change{items.length === 1 ? "" : "s"}
          </Button>
        </div>
      )}
      <Sheet open={current !== null} onOpenChange={(v) => !v && setOpen(null)}>
        <SheetContent className="features-sheet">
          {current && (
            <>
              <SheetHeader>
                <SheetTitle>{current.feature.label}</SheetTitle>
                <SheetDescription>{current.feature.help}</SheetDescription>
              </SheetHeader>
              <div className="features-sheet-body">
                {[current.master, ...current.settings]
                  .filter((r): r is ControlRow => r !== null)
                  .map((r) => (
                    <ControlEditor
                      key={r.control.key}
                      row={r}
                      staged={staged}
                      readOnly={readOnly(r.control.domain)}
                      zoneName={zoneName}
                      onChange={(cell, value) => stage(cell.entityId, value, cell.value)}
                    />
                  ))}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
      <ReviewDialog
        open={review}
        onOpenChange={setReview}
        controller={controller}
        items={items}
        title="Review feature changes"
        onApplied={(applied) =>
          setStaged((s) => {
            const next = { ...s };
            for (const id of applied) delete next[id];
            return next;
          })
        }
      />
    </>
  );
}

function FeatureItem({
  row,
  staged,
  disabled,
  zoneCount,
  onToggle,
  onConfigure,
  onReset,
}: {
  row: FeatureRow;
  staged: Staged;
  disabled: boolean;
  zoneCount: number;
  onToggle: (cell: Cell, on: boolean) => void;
  onConfigure: () => void;
  onReset: () => void;
}) {
  const { feature, master } = row;
  const roomCell = master?.room ?? null;
  const zonesOn = master?.zones.filter((c) => (staged[c.entityId] ?? c.value) === true).length;
  const copy = SETTING_COPY[feature.master?.key ?? feature.settings[0]?.key ?? ""] ?? {
    tooltip: feature.help,
  };
  const configurable = row.settings.length > 0 || (master !== null && master.zones.length > 0);
  const scope = feature.master?.scope ?? feature.settings[0]?.scope;
  return (
    <li className="features-row" data-feature={feature.id} data-changed={row.changed || undefined}>
      <div className="features-name">
        <strong>
          {feature.label} <InfoTip label={feature.label} copy={copy} />
        </strong>
        <p>{feature.help}</p>
        <span className="features-scope">
          {scope === "room" ? "Room" : scope === "zone" ? "Each zone" : "Room, with zone values"}
          {row.changed && <em> · Changed from default</em>}
        </span>
      </div>
      <div className="features-actions">
        {roomCell && typeof roomCell.value === "boolean" && (
          <label className="features-switch">
            <input
              type="checkbox"
              role="switch"
              aria-label={`${feature.label} on`}
              checked={(staged[roomCell.entityId] ?? roomCell.value) === true}
              disabled={disabled}
              onChange={(e) => onToggle(roomCell, e.target.checked)}
            />
            <span>{(staged[roomCell.entityId] ?? roomCell.value) ? "On" : "Off"}</span>
          </label>
        )}
        {master && !roomCell && master.zones.length > 0 && (
          <span className="features-zones-on">
            {zonesOn} of {zoneCount} zones on
          </span>
        )}
        {configurable && (
          <Button variant="outline" size="sm" onClick={onConfigure}>
            <SlidersHorizontal size={14} aria-hidden="true" /> Configure
          </Button>
        )}
        {row.changed && !disabled && (
          <Button variant="ghost" size="sm" onClick={onReset} title="Reset to default">
            <RotateCcw size={14} aria-hidden="true" /> Reset
          </Button>
        )}
        {feature.alsoOn && (
          <a className="features-also" href={`#/${feature.alsoOn}`}>
            Also on {pageLabel(feature.alsoOn as Page)}
          </a>
        )}
      </div>
    </li>
  );
}

function ControlEditor({
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

function AppOptions({ query }: { query: string }) {
  const app = GROUPS.find((g) => g.id === "app")!;
  const q = query.trim().toLowerCase();
  const list = APP_OPTIONS.filter(
    (o) => !q || o.label.toLowerCase().includes(q) || o.key.includes(q),
  );
  if (!list.length) return null;
  return (
    <section className="panel features-group" aria-labelledby="fg-app">
      <div className="panel-heading">
        <h2 id="fg-app">{app.label}</h2>
        <p>{app.help}</p>
      </div>
      <ul className="features-list">
        {list.map((o) => (
          <li key={o.key} className="features-row is-readonly" data-option={o.key}>
            <div className="features-name">
              <strong>{o.label}</strong>
              <span className="features-scope">
                <code>{o.key}</code> · Default: {o.secret ? "not shown" : o.default}
              </span>
            </div>
          </li>
        ))}
      </ul>
      <p className="features-app-link">
        <a href="/hassio/dashboard" target="_top" rel="noreferrer">
          Open the apps in Home Assistant <ExternalLink size={14} aria-hidden="true" />
        </a>{" "}
        Then open the controller app and its Configuration tab.
      </p>
    </section>
  );
}
