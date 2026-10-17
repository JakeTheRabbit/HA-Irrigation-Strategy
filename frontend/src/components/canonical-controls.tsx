import { useEffect, useLayoutEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ReviewDialog, type ReviewItem } from "@/components/dashboard";
import { ControlEditor } from "@/components/registry-control-editor";
import { featureRows, type ControlRow, type Value } from "@/lib/features";
import { ownerKey, supplementalRow, type ConfigOwner } from "@/lib/config-owners";
import { settingWords } from "@/lib/setting-words";
import type { Controller } from "@/lib/types";
import "@/pages/features.css";

export function CanonicalControls({
  controller,
  owner,
  zoneId,
  onDirtyChange,
}: {
  controller: Controller;
  owner: ConfigOwner;
  zoneId?: number;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [staged, setStaged] = useState<Record<string, Value>>({});
  const [review, setReview] = useState(false);
  const { room } = controller;
  const features = featureRows(
    controller.states,
    room.room.prefix,
    room.zones.map((z) => z.id),
    room.engine.entityId,
  )
    .filter((f) => ownerKey(f.feature) === owner)
    .map((f) => ({
      ...f,
      controls: [f.master, ...f.settings].flatMap((r) => {
        const kept = r && supplementalRow(f.feature, r, controller);
        return kept
          ? [
              {
                ...kept,
                room: zoneId === undefined ? kept.room : null,
                zones: kept.zones.filter((c) => zoneId === undefined || c.zone === zoneId),
              },
            ].filter((r) => r.room || r.zones.length)
          : [];
      }),
    }))
    .filter((f) => f.controls.length);
  const dirty = Object.keys(staged).length > 0;
  useLayoutEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    const id = new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("feature");
    if (id) document.getElementById(`config-${id}`)?.scrollIntoView?.({ block: "center" });
  }, [owner, zoneId]);
  const locked = controller.admin === false || !["live", "demo"].includes(controller.connection);
  const name = (zone: number | null) =>
    zone === null
      ? "Room default"
      : (room.zones.find((z) => z.id === zone)?.name ?? `Zone ${zone}`);
  const label = (r: ControlRow) =>
    r.control.label ?? settingWords(r.control.key)?.label ?? r.control.key.replaceAll("_", " ");
  const items: ReviewItem[] = features.flatMap((f) =>
    f.controls.flatMap((r) =>
      [r.room, ...r.zones].flatMap((c) =>
        c && staged[c.entityId] !== undefined
          ? [
              {
                change: { entityId: c.entityId, value: staged[c.entityId] },
                label: `${label(r)} · ${name(c.zone)}`,
                before: String(c.value ?? "Unavailable"),
                after: String(staged[c.entityId]),
              },
            ]
          : [],
      ),
    ),
  );
  return (
    <>
      {features.map((f) => (
        <section
          key={f.feature.id}
          id={`config-${f.feature.id}`}
          className="panel workspace-card"
          tabIndex={-1}
        >
          <div className="panel-heading">
            <h2>
              {f.feature.label}
              {f.feature.id === "sizing" ? " · room defaults" : ""}
            </h2>
            <p>{f.feature.help}</p>
          </div>
          {f.controls.map((r) => (
            <ControlEditor
              key={r.control.key}
              row={r}
              staged={staged}
              zoneName={name}
              readOnly={
                locked || (room.strategy.engaged && ["number", "select"].includes(r.control.domain))
              }
              onChange={(cell, value) =>
                setStaged((current) => {
                  const next = { ...current };
                  if (cell.value === value) delete next[cell.entityId];
                  else next[cell.entityId] = value;
                  return next;
                })
              }
            />
          ))}
        </section>
      ))}
      {dirty && (
        <div className="features-apply">
          <span>
            {items.length} changes in {room.room.name}
          </span>
          <Button variant="outline" onClick={() => setStaged({})}>
            Discard draft
          </Button>
          <Button disabled={locked || !items.length} onClick={() => setReview(true)}>
            Review changes
          </Button>
        </div>
      )}
      <ReviewDialog
        controller={controller}
        open={review}
        onOpenChange={setReview}
        items={items}
        onApplied={(ids) =>
          setStaged((current) =>
            Object.fromEntries(Object.entries(current).filter(([id]) => !ids.includes(id))),
          )
        }
      />
    </>
  );
}
