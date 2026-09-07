import { useEffect, useState } from "react";
import {
  Check,
  Plus,
  Search,
  Settings2,
  Trash2,
  RotateCcw,
  ExternalLink,
  RefreshCw,
} from "lucide-react";
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
import { Heading, Empty } from "@/components/dashboard";
import type { Controller } from "@/lib/types";
import type { SetupCandidate, SetupDocument, SetupRoom, SetupZone } from "@/lib/operator-types";

function MappingPicker({
  label,
  values,
  candidates,
  multiple = false,
  onChange,
  disabled = false,
}: {
  label: string;
  values: string[];
  candidates: SetupCandidate[];
  multiple?: boolean;
  onChange: (values: string[]) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false),
    [search, setSearch] = useState("");
  const filtered = candidates.filter((c) =>
    (c.name + " " + c.entity_id + " " + c.unit).toLowerCase().includes(search.toLowerCase()),
  );
  const selected = values.filter(Boolean);
  return (
    <div className="mapping-picker">
      <span className="mapping-label">{label}</span>
      <Button
        type="button"
        variant="outline"
        className="mapping-button"
        aria-label={"Map " + label}
        disabled={disabled}
        onClick={() => {
          setSearch("");
          setOpen(true);
        }}
      >
        <span>
          {selected.length
            ? selected
                .map((id) => candidates.find((c) => c.entity_id === id)?.name || id)
                .join(", ")
            : "Choose " + (multiple ? "sensors" : "entity")}
        </span>
        <Search size={16} />
      </Button>
      {!!selected.length && <small className="muted mapping-id">{selected.join(", ")}</small>}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="mapping-dialog">
          <DialogHeader>
            <DialogTitle>Map {label}</DialogTitle>
            <DialogDescription>
              {multiple
                ? "Choose one or more probes. The integration combines their readings."
                : "Choose the entity already configured in Home Assistant."}{" "}
              Availability and units are shown before selection.
            </DialogDescription>
          </DialogHeader>
          <Input
            autoFocus
            placeholder="Search name or entity ID…"
            aria-label={"Search " + label + " entities"}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="mapping-results" role="group" aria-label={label + " candidates"}>
            {filtered.slice(0, 200).map((c) => (
              <button
                type="button"
                key={c.entity_id}
                className={"mapping-result" + (selected.includes(c.entity_id) ? " selected" : "")}
                aria-pressed={selected.includes(c.entity_id)}
                onClick={() => {
                  const next = multiple
                    ? selected.includes(c.entity_id)
                      ? selected.filter((id) => id !== c.entity_id)
                      : [...selected, c.entity_id]
                    : [c.entity_id];
                  onChange(next);
                  if (!multiple) setOpen(false);
                }}
              >
                <span className="mapping-check">
                  {selected.includes(c.entity_id) && <Check size={16} />}
                </span>
                <span>
                  <strong>{c.name}</strong>
                  <small>{c.entity_id}</small>
                </span>
                <span className="mapping-reading">
                  {c.state}
                  <small>{c.unit || c.domain}</small>
                </span>
              </button>
            ))}
            {!filtered.length && (
              <p className="muted">
                No matching entities. Check the device integration or broaden your search.
              </p>
            )}
          </div>
          {filtered.length > 200 && (
            <p className="muted small">Showing the first 200 matches. Search to narrow the list.</p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => onChange([])}>
              Clear mapping
            </Button>
            <Button onClick={() => setOpen(false)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
function newZone(id: number): SetupZone {
  return {
    id,
    name: "Zone " + id,
    active: true,
    valve: "",
    vwc_sensors: [],
    ec_sensors: [],
    plant_count: 1,
    substrate_volume: 5,
    drippers_per_plant: 1,
    dripper_flow_rate: 2,
  };
}
const hardwareFields = [
  ["pump_switch", "Room pump", "switch"],
  ["main_line_switch", "Mainline valve", "switch"],
  ["feed_ec_sensor", "Feed-water EC", "ec"],
  ["feed_ph_sensor", "Feed-water pH", "ph"],
  ["light_entity", "Room lights", "light"],
] as const;
export function Setup({
  controller,
  onDirtyChange,
}: {
  controller: Controller;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [data, setData] = useState<SetupDocument | null>(null),
    [draft, setDraft] = useState<SetupRoom | null>(null);
  const [original, setOriginal] = useState<SetupRoom | null>(null),
    [isNew, setIsNew] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [review, setReview] = useState<"save" | "remove" | null>(null),
    [confirmName, setConfirmName] = useState("");
  const [tab, setTab] = useState<"rooms" | "install">("rooms");
  const dirty = !!draft && (isNew || JSON.stringify(draft) !== JSON.stringify(original));
  const connected = ["live", "demo"].includes(controller.connection);
  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  function selectRoom(room: SetupRoom | undefined) {
    setIsNew(false);
    setOriginal(room ? structuredClone(room) : null);
    setDraft(room ? structuredClone(room) : null);
    setError("");
    setNotice("");
  }
  async function load(selectId?: string) {
    setBusy(true);
    setError("");
    try {
      const result = await controller.operator<SetupDocument>("setup_read");
      if (result.api_version !== 1 || !Array.isArray(result.rooms))
        throw new Error("Update Crop Steering to use room management.");
      setData(result);
      const room =
        result.rooms.find((r) => r.entry_id === (selectId || draft?.entry_id)) ||
        result.rooms.find((r) => r.prefix === controller.room.room.prefix && r.active) ||
        result.rooms.find((r) => r.active) ||
        result.rooms[0];
      selectRoom(room);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!data && connected) void load();
  }, [controller.connection]);
  function addRoom() {
    const room: SetupRoom = {
      entry_id: "",
      revision: 0,
      room_name: "",
      prefix: "",
      slug: "",
      active: true,
      num_zones: 1,
      active_zone_ids: [1],
      zones: [newZone(1)],
      hardware: {},
      safety: { ready: true, blockers: [] },
    };
    setIsNew(true);
    setOriginal(null);
    setDraft(room);
    setNotice("");
    setError("");
  }
  function editZone(id: number, patch: Partial<SetupZone>) {
    if (draft)
      setDraft({ ...draft, zones: draft.zones.map((z) => (z.id === id ? { ...z, ...patch } : z)) });
  }
  function candidates(kind: string) {
    return (data?.candidates || [])
      .filter((c) =>
        kind === "switch"
          ? c.domain === "switch"
          : kind === "light"
            ? ["light", "switch"].includes(c.domain)
            : c.domain === "sensor",
      )
      .sort((a, b) => {
        const preferred = (c: SetupCandidate) =>
          kind === "vwc"
            ? (c.unit === "%" ? 2 : 0) + (/vwc|moisture|water.content/i.test(c.name) ? 1 : 0)
            : kind === "ec"
              ? (/mS\/cm|dS\/m|µS\/cm|uS\/cm/i.test(c.unit) ? 2 : 0) +
                (/conductivity|\bec\b/i.test(c.name) ? 1 : 0)
              : kind === "ph"
                ? /\bph\b/i.test(c.name)
                  ? 2
                  : 0
                : 0;
        return preferred(b) - preferred(a) || a.name.localeCompare(b.name);
      });
  }
  const activeZones = draft?.zones.filter((z) => z.active) || [],
    archivedZones = draft?.zones.filter((z) => !z.active) || [];
  const errors: string[] = [];
  if (draft) {
    if (!draft.room_name.trim()) errors.push("Name the room.");
    if (!draft.zones.length) errors.push("Add a zone.");
    if (activeZones.some((z) => !z.name.trim() || !z.valve))
      errors.push("Every active zone needs a name and valve.");
    const valves = activeZones.map((z) => z.valve).filter(Boolean);
    if (new Set(valves).size !== valves.length)
      errors.push("Each active zone must use a distinct valve.");
    if (
      activeZones.some(
        (z) =>
          !Number.isInteger(z.plant_count) ||
          z.plant_count < 1 ||
          !Number.isFinite(z.substrate_volume) ||
          Number(z.substrate_volume) <= 0 ||
          !Number.isFinite(z.drippers_per_plant) ||
          Number(z.drippers_per_plant) < 1 ||
          !Number.isFinite(z.dripper_flow_rate) ||
          Number(z.dripper_flow_rate) <= 0,
      )
    )
      errors.push("Enter valid plant counts, pot volumes and dripper sizing.");
  }
  async function save() {
    if (!draft || !review) return;
    setBusy(true);
    setError("");
    try {
      const result = await controller.operator<{ entry_id: string }>(
        review === "remove" ? "setup_remove" : isNew ? "setup_create" : "setup_save",
        review === "remove"
          ? {
              entry_id: draft.entry_id,
              expected_revision: draft.revision,
              confirm_name: confirmName,
            }
          : {
              entry_id: draft.entry_id,
              expected_revision: draft.revision,
              room_name: draft.room_name,
              active: draft.active,
              zones: draft.zones,
              hardware: draft.hardware,
            },
      );
      setReview(null);
      await load(result.entry_id);
      await controller.refresh();
      setNotice(
        review === "remove"
          ? "Room archived. Its identifiers and stored configuration are retained."
          : "Configuration saved in Home Assistant. Controller discovery and acknowledgement may follow on its next refresh; keep the engine off until verified.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const engineConfig = Object.values(controller.states).find(
    (e) => e.entity_id.endsWith("engine_config") && e.attributes.prefix === draft?.prefix,
  );
  const heartbeat = Object.values(controller.states).find(
    (e) => e.entity_id === "sensor.crop_steering_" + draft?.prefix + "ai_heartbeat",
  );
  const confirmedRevision = Number(heartbeat?.attributes.setup_revision);
  const mappingConfirmed =
    !isNew && draft && Number.isFinite(confirmedRevision) && confirmedRevision >= draft.revision;
  const Installation = () => (
    <section className="panel workspace-card">
      <h2>Install once, then map your devices</h2>
      <p className="muted">
        Home Assistant requires confirmation for custom integrations and controller apps. These
        shortcuts take you directly to the correct steps.
      </p>
      <ol className="install-steps">
        <li>
          <span className="step-number">1</span>
          <div>
            <h3>Install the integration with HACS</h3>
            <p>Add this repository as an Integration, download it, then restart Home Assistant.</p>
            <Button asChild variant="outline">
              <a
                href="https://my.home-assistant.io/redirect/hacs_repository/?owner=JakeTheRabbit&repository=HA-Irrigation-Strategy&category=integration"
                target="_blank"
                rel="noreferrer"
              >
                Open in HACS <ExternalLink size={15} />
              </a>
            </Button>
          </div>
        </li>
        <li>
          <span className="step-number">2</span>
          <div>
            <h3>Add Crop Steering</h3>
            <p>
              The native setup flow creates your first room. The new dashboard registers in the
              sidebar automatically.
            </p>
            <Button asChild variant="outline">
              <a
                href="https://my.home-assistant.io/redirect/config_flow_start/?domain=crop_steering"
                target="_blank"
                rel="noreferrer"
              >
                Add integration <ExternalLink size={15} />
              </a>
            </Button>
          </div>
        </li>
        <li>
          <span className="step-number">3</span>
          <div>
            <h3>Install the controller app</h3>
            <p>
              For Home Assistant OS/Supervised, add the repository and install Crop Steering. Keep
              every engine disabled while mapping hardware.
            </p>
            <Button asChild variant="outline">
              <a
                href="https://my.home-assistant.io/redirect/supervisor_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJakeTheRabbit%2FHA-Irrigation-Strategy"
                target="_blank"
                rel="noreferrer"
              >
                Add controller repository <ExternalLink size={15} />
              </a>
            </Button>
          </div>
        </li>
        <li>
          <span className="step-number">4</span>
          <div>
            <h3>Map, verify and start</h3>
            <p>
              Use Rooms & setup to select valves and probes, enter pot/dripper measurements, confirm
              the controller acknowledges the mapping, then review your grow plan. Enable the engine
              deliberately in Settings.
            </p>
            <Button
              variant="outline"
              onClick={() => {
                setTab("rooms");
                void load();
              }}
              disabled={!connected || busy}
            >
              Check installed capabilities <RefreshCw size={15} />
            </Button>
          </div>
        </li>
      </ol>
      <div className="workspace-message">
        Core/Container installations can use the integration and dashboard; running the irrigation
        controller requires a separate supported controller process. HACS is required only for
        automatic custom-integration updates.
      </div>
    </section>
  );
  return (
    <>
      <Heading
        title="Rooms & setup"
        description="Manage rooms, zones, sensor mapping and delivery sizing in one place."
        action={
          <Button
            disabled={!data?.capabilities.create || dirty || busy || !connected}
            onClick={addRoom}
          >
            <Plus size={16} />
            Add room
          </Button>
        }
      />
      <div className="workspace-tabs" role="tablist" aria-label="Setup view">
        <button role="tab" aria-selected={tab === "rooms"} onClick={() => setTab("rooms")}>
          Rooms & mappings
        </button>
        <button role="tab" aria-selected={tab === "install"} onClick={() => setTab("install")}>
          Installation
        </button>
      </div>
      {error && (
        <div className="workspace-message error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="workspace-message" role="status">
          {notice}
        </div>
      )}
      {tab === "install" ? (
        <Installation />
      ) : !data ? (
        <>
          <section className="panel workspace-card">
            <Empty
              title={busy ? "Reading setup" : "Setup service unavailable"}
              detail="Connect as a Home Assistant administrator and install the current integration. Older installations need an update before room management is available."
              action={
                <Button disabled={busy || !connected} onClick={() => void load()}>
                  <RefreshCw size={16} />
                  Retry setup
                </Button>
              }
            />
          </section>
          <Installation />
        </>
      ) : (
        <>
          <section className="panel workspace-card workspace-section-heading">
            <div className="setup-room-select">
              <Label htmlFor="setup-room">Room configuration</Label>
              <select
                id="setup-room"
                disabled={busy || dirty}
                value={isNew ? "new" : draft?.entry_id || ""}
                onChange={(e) => selectRoom(data.rooms.find((r) => r.entry_id === e.target.value))}
              >
                {isNew && <option value="new">New room</option>}
                {!data.rooms.length && !isNew && <option value="">No rooms configured</option>}
                {data.rooms.map((r) => (
                  <option key={r.entry_id} value={r.entry_id}>
                    {r.room_name}
                    {!r.active ? " (archived)" : ""}
                  </option>
                ))}
              </select>
              {dirty && <small className="muted">Save or discard before switching rooms.</small>}
            </div>
            <div className="workspace-actions">
              <Button
                variant="outline"
                disabled={!dirty || busy}
                onClick={() => {
                  if (isNew) selectRoom(data.rooms[0]);
                  else selectRoom(original || undefined);
                }}
              >
                Discard draft
              </Button>
              <Button variant="outline" disabled={dirty || busy} onClick={() => void load()}>
                <RefreshCw size={16} />
                Reload
              </Button>
              <Button
                disabled={!draft || !dirty || !!errors.length || busy || !connected}
                onClick={() => setReview("save")}
              >
                Review configuration
              </Button>
            </div>
          </section>
          {!draft ? (
            <Empty
              title="Create your first room"
              detail="Add a room and map devices that already exist in Home Assistant."
              action={<Button onClick={addRoom}>Add room</Button>}
            />
          ) : (
            <>
              {!draft.active && (
                <div className="workspace-message">
                  This room is archived. Existing entities and history are retained.{" "}
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => setDraft({ ...draft, active: true })}
                  >
                    <RotateCcw size={15} />
                    Restore room
                  </Button>
                </div>
              )}
              <section className="panel workspace-card">
                <div className="workspace-section-heading">
                  <div>
                    <h2>Room identity & readiness</h2>
                    <p className="muted">
                      Room labels can change. Existing controller identifiers stay stable.
                    </p>
                  </div>
                  {!isNew && (
                    <span className={"status-pill " + (mappingConfirmed ? "enabled" : "unknown")}>
                      {mappingConfirmed
                        ? "Mapping acknowledged"
                        : "Controller acknowledgement pending"}
                    </span>
                  )}
                </div>
                <div className="workspace-form-grid">
                  <div>
                    <Label htmlFor="room-name">Room name</Label>
                    <Input
                      id="room-name"
                      value={draft.room_name}
                      disabled={busy}
                      onChange={(e) => setDraft({ ...draft, room_name: e.target.value })}
                      placeholder="Flower room"
                    />
                  </div>
                  <div>
                    <span className="mapping-label">Configuration</span>
                    <p>
                      {isNew
                        ? "New namespace generated on creation"
                        : "Revision " + draft.revision + " · " + (draft.prefix || "Default room")}
                    </p>
                    <small className="muted">
                      {engineConfig ? "Room descriptor discovered" : "Awaiting room descriptor"}
                    </small>
                  </div>
                </div>
                {!isNew && !draft.safety.ready && (
                  <div className="workspace-message">
                    {draft.safety.blockers.map((b) => (
                      <p key={b}>{b}</p>
                    ))}
                    <p>
                      Mapping writes are checked again on the server. Turn the engine off and verify
                      the mapped hardware is off before saving.
                    </p>
                    <Button asChild variant="outline">
                      <a href="#/settings">Engine settings</a>
                    </Button>
                  </div>
                )}
              </section>
              <section className="panel workspace-card">
                <div className="workspace-section-heading">
                  <div>
                    <h2>Shared room hardware</h2>
                    <p className="muted">
                      Pump, mainline and source-water probes. Empty feed mappings leave that
                      source-water gate disabled.
                    </p>
                  </div>
                </div>
                <div className="workspace-form-grid">
                  {hardwareFields.map(([key, label, kind]) => (
                    <MappingPicker
                      key={key}
                      label={label}
                      values={
                        typeof draft.hardware[key] === "string" ? [String(draft.hardware[key])] : []
                      }
                      candidates={candidates(kind)}
                      disabled={busy}
                      onChange={(values) =>
                        setDraft({
                          ...draft,
                          hardware: { ...draft.hardware, [key]: values[0] || "" },
                        })
                      }
                    />
                  ))}
                </div>
              </section>
              <section className="panel workspace-card">
                <div className="workspace-section-heading">
                  <div>
                    <h2>Zones & sensor mapping</h2>
                    <p className="muted">
                      Each zone has its own valve, probes and delivery sizing. Archived IDs are
                      never renumbered.
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    disabled={
                      busy ||
                      Math.max(0, ...draft.zones.map((z) => z.id)) >= (data.limits.max_zones || 24)
                    }
                    onClick={() => {
                      const id = Math.max(0, ...draft.zones.map((z) => z.id)) + 1;
                      setDraft({ ...draft, zones: [...draft.zones, newZone(id)] });
                    }}
                  >
                    <Plus size={16} />
                    Add zone
                  </Button>
                </div>
                <div className="setup-zones">
                  {activeZones.map((zone) => (
                    <section className="setup-zone" key={zone.id}>
                      <div className="workspace-section-heading">
                        <div>
                          <span className="eyebrow">Zone ID {zone.id}</span>
                          <Input
                            aria-label={"Zone " + zone.id + " name"}
                            value={zone.name}
                            disabled={busy}
                            onChange={(e) => editZone(zone.id, { name: e.target.value })}
                          />
                        </div>
                        <Button
                          variant="ghost"
                          disabled={busy}
                          onClick={() => editZone(zone.id, { active: false })}
                        >
                          <Trash2 size={15} />
                          Remove zone
                        </Button>
                      </div>
                      <div className="workspace-form-grid">
                        <MappingPicker
                          label={zone.name + " valve"}
                          values={[zone.valve]}
                          candidates={candidates("switch")}
                          disabled={busy}
                          onChange={(v) => editZone(zone.id, { valve: v[0] || "" })}
                        />
                        <MappingPicker
                          label={zone.name + " VWC probes"}
                          values={zone.vwc_sensors}
                          multiple
                          candidates={candidates("vwc")}
                          disabled={busy}
                          onChange={(v) => editZone(zone.id, { vwc_sensors: v })}
                        />
                        <MappingPicker
                          label={zone.name + " EC probes"}
                          values={zone.ec_sensors}
                          multiple
                          candidates={candidates("ec")}
                          disabled={busy}
                          onChange={(v) => editZone(zone.id, { ec_sensors: v })}
                        />
                      </div>
                      <div className="workspace-form-grid sizing-grid">
                        {(
                          [
                            ["plant_count", "Plants", 1, 1000, 1],
                            ["substrate_volume", "Pot volume · L per plant", 0.1, 200, 0.1],
                            ["drippers_per_plant", "Drippers per plant", 1, 20, 1],
                            ["dripper_flow_rate", "Dripper flow · L/h each", 0.1, 50, 0.1],
                          ] as const
                        ).map(([key, label, min, max, step]) => (
                          <div key={key}>
                            <Label htmlFor={"zone-" + zone.id + "-" + key}>{label}</Label>
                            <Input
                              id={"zone-" + zone.id + "-" + key}
                              type="number"
                              min={min}
                              max={max}
                              step={step}
                              disabled={busy}
                              value={Number.isFinite(zone[key]) ? zone[key] : ""}
                              onChange={(e) =>
                                editZone(zone.id, {
                                  [key]: e.target.value === "" ? NaN : Number(e.target.value),
                                })
                              }
                            />
                          </div>
                        ))}
                      </div>
                      {(!zone.vwc_sensors.length || !zone.ec_sensors.length) && (
                        <p className="small muted">
                          Missing probes: automatic feedback steering needs valid readings. No
                          sensor is selected automatically.
                        </p>
                      )}
                    </section>
                  ))}
                </div>
                {!!archivedZones.length && (
                  <details className="archived-zones">
                    <summary>
                      {archivedZones.length} archived zone{archivedZones.length === 1 ? "" : "s"}
                    </summary>
                    {archivedZones.map((z) => (
                      <div className="workspace-section-heading" key={z.id}>
                        <span>
                          {z.name} · ID {z.id}
                        </span>
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() => editZone(z.id, { active: true })}
                        >
                          <RotateCcw size={15} />
                          Restore zone
                        </Button>
                      </div>
                    ))}
                  </details>
                )}
              </section>
              {!!errors.length && (
                <div className="workspace-message error">
                  <strong>Before saving</strong>
                  <ul>
                    {errors.map((e) => (
                      <li key={e}>{e}</li>
                    ))}
                  </ul>
                </div>
              )}
              {!isNew && draft.active && (
                <section className="panel workspace-card workspace-section-heading">
                  <div>
                    <h2>Remove this room</h2>
                    <p className="muted">
                      Archive the room while retaining its identifiers and configuration. The engine
                      and hardware must be off.
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    disabled={busy || dirty}
                    onClick={() => {
                      setConfirmName("");
                      setReview("remove");
                    }}
                  >
                    <Trash2 size={15} />
                    Archive room
                  </Button>
                </section>
              )}
            </>
          )}
        </>
      )}
      <Dialog
        open={!!review}
        onOpenChange={(open) => {
          if (!open && !busy) setReview(null);
        }}
      >
        <DialogContent className="plan-review-dialog">
          <DialogHeader>
            <DialogTitle>
              {review === "remove"
                ? "Archive " + draft?.room_name + "?"
                : "Review room configuration"}
            </DialogTitle>
            <DialogDescription>
              {review === "remove"
                ? "This removes the room from active control while preserving its identifiers and stored configuration."
                : "Only the selected room configuration is changed. No engine is enabled and no valve is actuated."}
            </DialogDescription>
          </DialogHeader>
          {review === "remove" ? (
            <div>
              <Label htmlFor="confirm-room-name">Type the room name to confirm</Label>
              <Input
                id="confirm-room-name"
                value={confirmName}
                onChange={(e) => setConfirmName(e.target.value)}
              />
            </div>
          ) : (
            <div className="plan-review-zones">
              <h3>{draft?.room_name}</h3>
              <p>
                {activeZones.length} active zones · {archivedZones.length} archived zones
              </p>
              {activeZones.map((z) => (
                <div className="workspace-message" key={z.id}>
                  <strong>
                    {z.name} · ID {z.id}
                  </strong>
                  <p className="mapping-id">{z.valve}</p>
                  <p>
                    {z.vwc_sensors.length} VWC probes · {z.ec_sensors.length} EC probes
                  </p>
                  <p>
                    {z.plant_count} plants × {z.substrate_volume} L · {z.drippers_per_plant}{" "}
                    drippers per plant × {z.dripper_flow_rate} L/h
                  </p>
                </div>
              ))}
            </div>
          )}
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setReview(null)}>
              Back to editing
            </Button>
            <Button
              variant={review === "remove" ? "destructive" : "default"}
              disabled={
                busy || !connected || (review === "remove" && confirmName !== draft?.room_name)
              }
              onClick={() => void save()}
            >
              {busy ? "Saving…" : review === "remove" ? "Archive room" : "Save configuration"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
