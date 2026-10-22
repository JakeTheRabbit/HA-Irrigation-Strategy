import { useContext, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NeedsIntegration } from "@/components/needs-integration";
import { ReviewApply, type ApplyReceipt } from "@/components/review-apply";
import { RoomPickContext } from "@/components/room-tree";
import { callV2, useParity, type V2Outcome } from "@/lib/parity-api";
import type { PresetList, PresetResult, PresetSaved, PresetTarget } from "@/lib/parity-types";
import {
  ALL_SECTIONS,
  SCOPE_WORDS,
  copyReceipt,
  diffRows,
  notCopiedLines,
  parseTarget,
  presetWords,
  skippedLine,
} from "@/lib/presets";
import { dayLabel } from "@/lib/time";
import type { Controller } from "@/lib/types";
import { revertEvents } from "@/lib/undo";

/** The room's own live settings ("room"), or a stored preset's id. */
type Source = "room" | string;
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Presets stored on the controller (every phone and PC sees the same list), saving this room as a
 * new one, and copying the room or a preset to another room: the room tree picks the target, a
 * preview lists each change and each setting not copied, one button writes and reads back every
 * value, and the receipt offers Undo of the journalled writes. On 3.17: Needs integration. */
export function PresetsPanel({
  controller,
  roomId,
  planName,
}: {
  controller: Controller;
  roomId: string;
  planName: string;
}) {
  const list = useParity<PresetList>(controller, "preset_list", {}, [roomId]);
  const setPick = useContext(RoomPickContext);
  const words = presetWords(controller.states, controller.rooms);
  const roomName = words.target({ room_id: roomId });
  const [source, setSource] = useState<Source>("room");
  const [picking, setPicking] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [targets, setTargets] = useState<PresetTarget[]>([]);
  const [preview, setPreview] = useState<V2Outcome<PresetResult> | null>(null);
  const [copied, setCopied] = useState(false);
  const [undoable, setUndoable] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ text: string; skipped: string; error?: boolean } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  const preset =
    source === "room" ? null : (list.data?.presets.find((p) => p.id === source) ?? null);
  const name = preset?.name ?? planName;
  // A room's live settings never go back into the same room.
  const exclude = preset ? undefined : roomId;
  useEffect(() => {
    if (!picking) return;
    setPick({
      title: `Copy “${name}” to`,
      selected,
      exclude,
      onChange: setSelected,
      onDone: () => {
        setPicking(false);
        if (selected.size) void choose([...selected].map(parseTarget));
      },
      onCancel: () => setPicking(false),
    });
  }, [picking, selected, name, exclude]);
  useEffect(() => {
    if (!picking) setPick(null);
  }, [picking]);
  useEffect(() => () => setPick(null), []);

  const request = (to: PresetTarget[], dry: boolean) =>
    preset
      ? callV2<PresetResult>(controller, "preset_apply", { preset_id: preset.id, to, preview: dry })
      : callV2<PresetResult>(controller, "copy_config", {
          from: { room_id: roomId },
          to,
          sections: [...ALL_SECTIONS],
          preview: dry,
        });
  async function choose(to: PresetTarget[]) {
    setTargets(to);
    setCopied(false);
    setUndoable(false);
    setPreview(null);
    setPreview(await request(to, true));
  }
  function startPick(next: Source) {
    setSource(next);
    setSelected(new Set());
    setTargets([]);
    setPreview(null);
    setPicking(true);
  }

  async function save() {
    if (!saving?.trim() || !list.data) return;
    setBusy(true);
    const outcome = await callV2<PresetSaved>(controller, "preset_save", {
      name: saving.trim(),
      scope: "all",
      from: { room_id: roomId },
      expected_revision: list.data.revision,
    });
    setBusy(false);
    if (outcome.kind === "ok") {
      setSaved({
        text: `Saved “${outcome.data.preset.name}” on the controller.`,
        skipped: skippedLine(outcome.data.skipped ?? [], words),
      });
      setSaving(null);
      list.reload();
    } else
      setSaved({
        text:
          outcome.kind === "missing"
            ? "Saving presets needs Crop Steering 3.18 or newer."
            : outcome.code === "stale_revision"
              ? "Someone else changed the presets since this list was read. It has been read again: save once more."
              : outcome.message,
        skipped: "",
        error: true,
      });
    if (outcome.kind === "error" && outcome.code === "stale_revision") list.reload();
  }

  if (list.state === "missing")
    return (
      <section className="panel presets-panel" aria-labelledby="presets-title">
        <h2 id="presets-title">Presets</h2>
        <NeedsIntegration feature="Presets" />
      </section>
    );

  const result = preview?.kind === "ok" ? preview.data : null;
  const rows = result && !copied ? diffRows(result.diff, words) : [];
  const missing = result ? notCopiedLines(result.missing, words) : [];
  const toNames = targets.map(words.target).join(" and ");
  const cards = [
    { id: "room", title: planName, sub: `Running in ${roomName} · its live settings` },
    ...(list.data?.presets ?? []).map((p) => ({
      id: p.id,
      title: p.name,
      sub: `From ${words.target(p.from)} · ${SCOPE_WORDS[p.scope]} · saved ${dayLabel(Date.parse(p.created_at), controller.timeZone)}`,
    })),
  ];

  return (
    <section className="panel presets-panel" aria-labelledby="presets-title">
      <h2 id="presets-title">Presets</h2>
      <p className="muted small">Stored on the controller: the same list on every phone and PC</p>
      {list.state === "error" && (
        <p role="alert" className="error-text">
          {list.error}
        </p>
      )}
      <ul className="preset-cards" aria-label="Presets">
        {cards.map((card) => (
          <li key={card.id}>
            <button
              type="button"
              className="preset-card"
              aria-pressed={source === card.id}
              onClick={() => {
                setSource(card.id);
                setTargets([]);
                setPreview(null);
              }}
            >
              <b>{card.title}</b>
              <span>{card.sub}</span>
            </button>
          </li>
        ))}
      </ul>
      {saving === null ? (
        <Button
          variant="outline"
          className="preset-save"
          onClick={() => {
            setSaving(planName);
            setSaved(null);
          }}
          disabled={!list.data}
        >
          Save {roomName} plan as a new preset
        </Button>
      ) : (
        <form
          className="preset-save-form"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label htmlFor="preset-name">Preset name</label>
          <Input
            id="preset-name"
            value={saving}
            maxLength={60}
            onChange={(e) => setSaving(e.target.value)}
          />
          <p className="muted small">
            Saves {roomName}’s live targets, timing, water limits and timer programs.
          </p>
          <div className="preset-save-actions">
            <Button type="submit" disabled={busy || !saving.trim()}>
              {busy ? "Saving…" : "Save preset"}
            </Button>
            <Button type="button" variant="outline" onClick={() => setSaving(null)} disabled={busy}>
              Cancel
            </Button>
          </div>
        </form>
      )}
      {saved && (
        <p
          role={saved.error ? "alert" : "status"}
          className={saved.error ? "error-text" : "preset-saved"}
        >
          {saved.text}
          {saved.skipped && <span className="preset-skipped">{saved.skipped}</span>}
        </p>
      )}

      <div className="preset-copy">
        <h3>Copy “{name}” to room…</h3>
        <Button
          variant="outline"
          onClick={() => startPick(source)}
          disabled={picking || (!!exclude && controller.rooms.length < 2)}
        >
          {targets.length ? "Pick another room" : "Pick a room"}
        </Button>
        {targets.length > 0 && preview === null && (
          <p className="muted small">Reading {toNames}…</p>
        )}
        {preview && preview.kind !== "ok" && (
          <p role="alert" className="error-text">
            {preview.kind === "missing"
              ? "Copying needs Crop Steering 3.18 or newer."
              : preview.message}
          </p>
        )}
        {result && (
          <>
            {!copied && !rows.length && (
              <p className="preset-same">{toNames} already has these values.</p>
            )}
            {!copied && missing.length > 0 && (
              <ul className="preset-not-copied" aria-label="Not copied">
                {missing.map((line) => (
                  <li key={line}>Not copied: {line}</li>
                ))}
              </ul>
            )}
            {(rows.length > 0 || copied) && (
              <ReviewApply
                key={targets.map((t) => JSON.stringify(t)).join() + source}
                rows={rows}
                layout="panel"
                summary={
                  <span className="review-apply-sub">
                    {rows.length
                      ? `${plural(rows.length, "change")} to ${toNames}, from ${name}`
                      : `Copy to ${toNames}`}
                  </span>
                }
                applyLabel={`Copy ${plural(rows.length, "change")} to ${toNames}`}
                discardLabel="Cancel copy"
                consequence={`Writes ${toNames}’s own settings now and reads each one back. ${preset ? "" : `${roomName} is not changed.`}`}
                apply={async () => {
                  const receipt = copyReceipt(
                    await request(targets, false),
                    rows,
                    words,
                    Date.now(),
                  );
                  if ("ok" in receipt && !receipt.unconfirmed) {
                    setCopied(true);
                    setUndoable(receipt.ok && receipt.eventIds.length > 0);
                  }
                  return receipt as
                    ApplyReceipt | Extract<V2Outcome<unknown>, { kind: "error" | "missing" }>;
                }}
                onDiscard={() => {
                  setTargets([]);
                  setPreview(null);
                }}
                timeZone={controller.timeZone}
                undo={
                  undoable
                    ? async (receipt) => {
                        await revertEvents(controller, receipt.eventIds);
                      }
                    : undefined
                }
              />
            )}
          </>
        )}
      </div>
    </section>
  );
}
