import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";

interface Settings {
  room_id: string;
  revision: number;
  connection: Record<string, string | boolean>;
  has_password: boolean;
  has_token: boolean;
}
const FIELDS = [
  ["url", "InfluxDB URL"], ["database", "Database (1.x)"], ["bucket", "Bucket (2.x)"],
  ["org", "Organisation (2.x)"], ["username", "Username (1.x)"],
  ["password", "Password (1.x)"], ["token", "Read-only token (2.x)"],
  ["measurement", "Measurement (blank uses each sensor's unit)"],
  ["field", "Value field"], ["tag", "Entity tag"], ["domain_tag", "Domain tag (blank if the archive has none)"],
];

/** Credentials are write-only; the browser never receives saved secrets. */
export function HistoryConnection({ controller }: { controller: Controller }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const currentRoom = useRef({ id: controller.roomId, generation: 0 });
  if (currentRoom.current.id !== controller.roomId) {
    currentRoom.current = { id: controller.roomId, generation: currentRoom.current.generation + 1 };
  }
  const open = expanded === controller.roomId;
  useEffect(() => {
    let active = true;
    setSettings(null); setDraft({}); setMessage(""); setBusy(false);
    if (open && !controller.demo) controller.operator<Settings>("history_connection_get").then(value => {
      if (active) { setSettings(value); setDraft(value.connection); }
    }).catch(error => { if (active) setMessage(errorText(error)); });
    return () => { active = false; };
  }, [controller.roomId, controller.operator, controller.demo, open]);
  if (controller.demo) return null;
  const update = (key: string, value: string | boolean) => setDraft(old => ({ ...old, [key]: value }));
  const save = async () => {
    if (!settings) return;
    const generation = currentRoom.current.generation;
    setBusy(true); setMessage("");
    try {
      const payload = { ...draft };
      // Blank password/token retains the stored secret, rather than asking the browser to hold it.
      for (const key of ["password", "token"]) if (!payload[key]) delete payload[key];
      const result = await controller.operator<Settings>("history_connection_save", {
        expected_revision: settings.revision, connection: payload,
      });
      if (currentRoom.current.generation !== generation) return;
      setSettings(result); setDraft(result.connection);
      setMessage("Saved. InfluxDB is read-only; the connection was tested before enabling it.");
    } catch (error) { if (currentRoom.current.generation === generation) setMessage(errorText(error)); }
    finally { if (currentRoom.current.generation === generation) setBusy(false); }
  };
  return <details className="panel" aria-label="Long history source" open={open}
    onToggle={event => setExpanded(event.currentTarget.open ? controller.roomId : null)}>
    <summary>Long history</summary>
    {open && <>
    <p className="small muted">Recorder stays the default. Optional InfluxDB history uses read-only queries of this room's mapped sensors, capped at 1000 points per sensor. Keep a read-only account or token.</p>
    {!settings && !message && <p role="status">Loading history settings…</p>}
    {settings && <>
    <label>History source <select value={String(draft.source)} disabled={busy} onChange={e => update("source", e.target.value)}>
      <option value="recorder">Home Assistant Recorder</option><option value="influxdb">InfluxDB</option>
    </select></label>
    {draft.source === "influxdb" && <>
      <label>InfluxDB version <select value={String(draft.version)} disabled={busy} onChange={e => update("version", e.target.value)}>
        <option value="1">1.x (InfluxQL)</option><option value="2">2.x (Flux)</option>
      </select></label>
      <div className="grid gap-3 sm:grid-cols-2">{FIELDS.map(([key, label]) => <label key={key}>{label}
        <Input type={key === "password" || key === "token" ? "password" : "text"} autoComplete="off" disabled={busy}
          value={String(draft[key] ?? "")} onChange={e => update(key, e.target.value)}
          placeholder={(key === "password" && settings.has_password) || (key === "token" && settings.has_token) ? "Saved; leave blank to keep" : ""} />
      </label>)}</div>
      <label><input type="checkbox" checked={draft.full_entity_id === true} disabled={busy} onChange={e => update("full_entity_id", e.target.checked)} /> Entity tag includes sensor. prefix</label>
    </>}
    <Button disabled={busy} onClick={save}>{busy ? "Testing connection…" : "Save history source"}</Button>
    </>}
    {message && <p role="status">{message}</p>}
    </>}
  </details>;
}
