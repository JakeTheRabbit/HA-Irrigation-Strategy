import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Download, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Pill } from "@/components/mini-visuals";
import { dateInZone } from "@/lib/comparison";
import type { RunRecord, RunsDocument } from "@/lib/comparison-types";
import type { Controller } from "@/lib/types";
import "./run-records.css";

type Form = { id?: string; name: string; start_date: string; end_date: string };
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Run records request failed.";

/** The room's run records, which Compare runs lines up by grow week: add a run, change its name or
 * dates, archive or restore it, and export or import them all. Settings › Run records. */
export function RunRecords({
  controller,
  onDirtyChange,
}: {
  controller: Controller;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [document, setDocument] = useState<RunsDocument | null>(null),
    [loadError, setLoadError] = useState<string | null>(null),
    [reload, setReload] = useState(0),
    [archived, setArchived] = useState(false);
  const [form, setForm] = useState<Form | null>(null),
    [saving, setSaving] = useState(false),
    [formError, setFormError] = useState<string | null>(null);
  const roomRef = useRef(controller.roomId);
  roomRef.current = controller.roomId;
  const fileRef = useRef<HTMLInputElement>(null);
  const doc = document?.room_id === controller.roomId ? document : null;
  const timeZone = doc?.time_zone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const runs = doc?.runs.filter((run) => archived || !run.archived) || [];
  useLayoutEffect(() => {
    onDirtyChange?.(Boolean(form));
    return () => onDirtyChange?.(false);
  }, [form, onDirtyChange]);
  useEffect(() => {
    setDocument(null);
    setForm(null);
    setFormError(null);
    setSaving(false);
  }, [controller.roomId]);
  useEffect(() => {
    let cancelled = false;
    if (!controller.roomId) return;
    setLoadError(null);
    controller
      .operator<RunsDocument>("runs_get")
      .then((value) => {
        if (cancelled) return;
        setDocument(value);
        setLoadError(value.error);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(errorText(error));
      });
    return () => {
      cancelled = true;
    };
  }, [controller.roomId, controller.operator, reload]);
  async function save() {
    if (!form || !doc) return;
    const room = controller.roomId;
    setSaving(true);
    setFormError(null);
    try {
      const next = await controller.operator<RunsDocument>("runs_save", {
        record: form,
        expected_revision: doc.revision,
      });
      if (roomRef.current === room) {
        setDocument(next);
        setForm(null);
      }
    } catch (error) {
      if (roomRef.current === room) setFormError(errorText(error));
    } finally {
      if (roomRef.current === room) setSaving(false);
    }
  }
  async function archive(run: RunRecord) {
    if (!doc) return;
    const room = controller.roomId;
    setSaving(true);
    setFormError(null);
    try {
      const next = await controller.operator<RunsDocument>("runs_archive", {
        id: run.id,
        archived: !run.archived,
        expected_revision: doc.revision,
      });
      if (roomRef.current === room) setDocument(next);
    } catch (error) {
      if (roomRef.current === room) setFormError(errorText(error));
    } finally {
      if (roomRef.current === room) setSaving(false);
    }
  }
  function exportRuns() {
    if (!doc) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }),
    );
    const link = window.document.createElement("a");
    link.href = url;
    link.download = "crop-steering-run-metadata.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function importRuns(file?: File) {
    if (!file || !doc) return;
    const room = controller.roomId;
    setFormError(null);
    setSaving(true);
    try {
      if (file.size > 2_000_000) throw new Error("Metadata import is limited to 2 MB.");
      const value = JSON.parse(await file.text());
      if (roomRef.current !== room) throw new Error("Room changed; import cancelled.");
      if (value.schema_version !== 1 || value.room_id !== room || !Array.isArray(value.runs))
        throw new Error("Import a version 1 export for this exact room.");
      const next = await controller.operator<RunsDocument>("runs_import", {
        runs: value.runs,
        expected_revision: doc.revision,
      });
      if (roomRef.current === room) setDocument(next);
    } catch (error) {
      if (roomRef.current === room) setFormError(errorText(error));
    } finally {
      if (roomRef.current === room) setSaving(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }
  return (
    <div className="run-records" id="run-records">
      <div className="comparison-record-heading">
        <p className="small">
          Up to 100 runs per room, each 1–366 calendar days once it ends. Registering a run captures
          the room’s sensors, plant counts, targets and lights schedule as they are now; it never
          enables or arms irrigation.
        </p>
        <Button
          onClick={() => {
            setForm({ name: "", start_date: dateInZone(Date.now(), timeZone), end_date: "" });
            setFormError(null);
          }}
          disabled={!doc || !!doc.error || saving || !!form}
        >
          <Plus size={15} /> Add run
        </Button>
      </div>
      {loadError && (
        <div className="run-records-notice" role="alert">
          {loadError}
          <Button variant="outline" onClick={() => setReload((value) => value + 1)}>
            Reload run records
          </Button>
        </div>
      )}
      <div className="run-records-actions">
        <Button variant="outline" onClick={exportRuns} disabled={!doc}>
          <Download size={15} /> Export metadata
        </Button>
        <Button
          variant="outline"
          onClick={() => fileRef.current?.click()}
          disabled={!doc || !!doc.error || saving || !!form}
        >
          Import metadata
        </Button>
        <input
          ref={fileRef}
          hidden
          type="file"
          accept="application/json,.json"
          aria-label="Import run metadata"
          onChange={(event) => void importRuns(event.target.files?.[0])}
        />
        <label className="run-records-check">
          <input
            type="checkbox"
            checked={archived}
            onChange={(event) => setArchived(event.target.checked)}
          />{" "}
          Include archived run records
        </label>
      </div>
      {form && (
        <form
          className="comparison-form"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label>
            Run name
            <Input
              aria-label="Run name"
              required
              maxLength={80}
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </label>
          <label>
            Start date
            <Input
              aria-label="Run start date"
              type="date"
              required
              value={form.start_date}
              onChange={(event) => setForm({ ...form, start_date: event.target.value })}
            />
          </label>
          <label>
            End date · blank while ongoing
            <Input
              aria-label="Run end date"
              type="date"
              value={form.end_date}
              onChange={(event) => setForm({ ...form, end_date: event.target.value })}
            />
          </label>
          <p className="small run-records-wide">
            {form.id
              ? "Changing the name or dates preserves the original reference, sensors, plants and lights schedule."
              : "Registration captures this room's configured sensors, plant counts, targets and lights schedule now. Past dates do not imply a historical configuration snapshot."}
          </p>
          <div className="run-records-actions run-records-wide">
            <Button type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save run record"}
            </Button>
            <Button type="button" variant="outline" disabled={saving} onClick={() => setForm(null)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
      {formError && (
        <p role="alert" className="run-records-notice">
          {formError}
        </p>
      )}
      {doc && !runs.length && (
        <p className="small muted">
          {doc.runs.length
            ? "Every run of this room is archived."
            : "No runs recorded for this room yet."}
        </p>
      )}
      <div className="comparison-run-list">
        {runs.map((run) => (
          <article key={run.id}>
            <div>
              <h3>
                {run.name}
                {run.archived ? (
                  <Pill tone="neutral">Archived</Pill>
                ) : run.end_date ? (
                  <Pill tone="neutral">Ended</Pill>
                ) : (
                  <Pill dot tone="on">
                    Ongoing
                  </Pill>
                )}
              </h3>
              <p>
                {run.start_date} → {run.end_date || "ongoing"} · {run.time_zone}
              </p>
              <p className="small">
                Reference captured{" "}
                {new Date(run.captured_at).toLocaleString(undefined, { timeZone: run.time_zone })}.{" "}
                {run.reference_source}.
              </p>
              <details>
                <summary>Registered zones and sensors</summary>
                {run.zones.map((zone) => (
                  <p className="small" key={zone.zone_id}>
                    {zone.name} · plants at registration: {zone.plant_count ?? "unknown"} · VWC{" "}
                    {zone.vwc_sensor || "unavailable"} · EC {zone.ec_sensor || "unavailable"}
                  </p>
                ))}
              </details>
            </div>
            <div className="run-records-actions">
              <Button
                variant="outline"
                disabled={saving || !!form || !!doc?.error}
                onClick={() => {
                  setForm({
                    id: run.id,
                    name: run.name,
                    start_date: run.start_date,
                    end_date: run.end_date || "",
                  });
                  setFormError(null);
                }}
              >
                Edit dates/name
              </Button>
              <Button
                variant="outline"
                disabled={saving || !!form || !!doc?.error}
                onClick={() => void archive(run)}
              >
                {run.archived ? "Restore" : "Archive"}
              </Button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
