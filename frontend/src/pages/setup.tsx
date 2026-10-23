import { sizingChangedSince } from "@/lib/setup-sizing";
import { CanonicalControls } from "@/components/canonical-controls";
import { AllZonesSwitch, RoomPower } from "@/components/room-controls";
import { useLayoutEffect, useEffect, useState } from "react";
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
import { UiTip } from "@/components/info-tip";
import { ControllerSettings } from "@/components/controller-settings";
import { HistoryConnection } from "@/components/history-connection";
import { SetupWizard } from "@/components/setup-wizard";
import { SupplyEditor } from "@/components/supply-editor";
import { RunoffPanel } from "@/components/runoff";
import { Pill } from "@/components/mini-visuals";
import {
  CatchTestCalculator,
  SizingField,
  SizingUnitPickers,
  SubstratePresetPicker,
  useSizingUnits,
} from "@/components/zone-sizing";
import type { Controller } from "@/lib/types";
import { roomSlug } from "@/lib/model";
import { SIZING_UNITS, reviewValue, sizingError } from "@/lib/units";
import {
  PLUMBING_HINTS,
  PLUMBING_LABELS,
  PLUMBING_LAYOUTS,
  hardwareForLayout,
  isPlumbingLayout,
  plumbingErrors,
  plumbingUses,
  type PlumbingLayout,
} from "@/lib/plumbing";
import { errorText } from "@/lib/utils";
import { needsWizard } from "@/lib/commissioning";
import type {
  Commissioning,
  SetupCandidate,
  SetupDocument,
  SetupRoom,
  SetupZone,
} from "@/lib/operator-types";

export function MappingPicker({
  label,
  values,
  candidates,
  multiple = false,
  onChange,
  disabled = false,
  hint,
  choose,
}: {
  label: string;
  values: string[];
  candidates: SetupCandidate[];
  multiple?: boolean;
  onChange: (values: string[]) => void;
  disabled?: boolean;
  /** What to choose, in the picker; the probes' wording by default. */
  hint?: string;
  /** The button's words while nothing is mapped. */
  choose?: string;
}) {
  const [open, setOpen] = useState(false),
    [search, setSearch] = useState("");
  const filtered = candidates.filter((c) =>
    (c.name + " " + c.entity_id + " " + c.unit).toLowerCase().includes(search.toLowerCase()),
  );
  const selected = values.filter(Boolean);
  // A mapped entity Home Assistant reports no state for is mapped, but not usable.
  const silent = selected.filter((id) =>
    ["unavailable", "unknown"].includes(
      candidates.find((c) => c.entity_id === id)?.state.toLowerCase() ?? "",
    ),
  ).length;
  return (
    <div className="mapping-picker">
      <div className="mapping-head">
        <span className="mapping-label">{label}</span>
        {!selected.length ? (
          <Pill tone="neutral">Not mapped</Pill>
        ) : silent ? (
          <Pill tone="warn">
            {selected.length === 1 ? "Unavailable" : `${silent} of ${selected.length} unavailable`}
          </Pill>
        ) : (
          <Pill tone="on">{selected.length === 1 ? "Mapped" : `${selected.length} mapped`}</Pill>
        )}
      </div>
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
            : (choose ?? "Choose " + (multiple ? "sensors" : "entity"))}
        </span>
        <Search size={16} />
      </Button>
      {!!selected.length && <small className="muted mapping-id">{selected.join(", ")}</small>}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="mapping-dialog">
          <DialogHeader>
            <DialogTitle>Map {label}</DialogTitle>
            <DialogDescription>
              {hint ??
                (multiple
                  ? "Choose one or more probes. The integration combines their readings."
                  : "Choose the entity already configured in Home Assistant.")}{" "}
              Availability and units are shown before selection.
            </DialogDescription>
          </DialogHeader>
          <Input
            autoFocus
            placeholder="Name or entity ID"
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
/** A new zone, its sizing from the integration's one defaults table (`defaults`; these values
 * where an older integration does not send it). */
function newZone(id: number, defaults: SetupDocument["sizing_defaults"] = {}): SetupZone {
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
    ...defaults,
  };
}
const hardwareFields = [
  ["pump_switch", "Room pump", "switch"],
  ["main_line_switch", "Mainline valve", "switch"],
  ["feed_ec_sensor", "Feed-water EC", "ec"],
  ["feed_ph_sensor", "Feed-water pH", "ph"],
  ["light_entity", "Room lights", "light"],
  ["water_level_sensor", "Tank fill level (%)", "level"],
  ["tank_ec_sensor", "Tank EC (display)", "ec"],
  ["tank_ph_sensor", "Tank pH (display)", "ph"],
  ["tank_temperature_sensor", "Tank temperature", "temperature"],
  ["tank_last_fill_sensor", "Last recorded tank fill", "timestamp"],
  ["tank_fill_entity", "Tank filling status", "binary"],
  ["leaf_temperature_sensor", "Leaf temperature (plant stress card)", "temperature"],
  // Shown on the dashboard only (Settings › Display); the controller reads none of them.
  ["camera_entity", "Room camera (display)", "camera"],
  ["co2_sensor", "CO2 (display)", "co2"],
  ["ppfd_sensor", "PPFD (display)", "ppfd"],
  ["dli_sensor", "Daily light integral (display)", "dli"],
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
  const units = useSizingUnits();
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [equipmentDirty, setEquipmentDirty] = useState(false);
  const [supplyDirty, setSupplyDirty] = useState(false);
  const dirty = !!draft && (isNew || JSON.stringify(draft) !== JSON.stringify(original));
  const connected = ["live", "demo"].includes(controller.connection);
  useLayoutEffect(() => {
    onDirtyChange(dirty || settingsDirty || equipmentDirty || supplyDirty);
    return () => onDirtyChange(false);
  }, [dirty, settingsDirty, equipmentDirty, supplyDirty, onDirtyChange]);
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
      setError(errorText(e));
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
      zones: [newZone(1, data?.sizing_defaults)],
      hardware: {},
      plumbing: "",
      safety: { ready: true, blockers: [] },
    };
    setIsNew(true);
    setOriginal(null);
    setDraft(room);
    setNotice("");
    setError("");
  }
  // The wizard's checks change nothing in the room's setup: patch both copies, so they never make
  // the room look edited.
  function wizardStatus(commissioning: Commissioning) {
    setOriginal((room) => room && { ...room, commissioning });
    setDraft((room) => room && { ...room, commissioning });
    if (commissioning.commissioned)
      setNotice(
        "The setup of this room is complete. Set the Watering switch to on. The dashboard shows a review first.",
      );
  }
  function editZone(id: number, patch: Partial<SetupZone>) {
    if (draft)
      setDraft({ ...draft, zones: draft.zones.map((z) => (z.id === id ? { ...z, ...patch } : z)) });
  }
  function candidates(kind: string) {
    return (data?.candidates || [])
      .filter((c) =>
        kind === "switch"
          ? // a zone valve, main line or pump: what the controller can open and close
            ["switch", "input_boolean", "valve"].includes(c.domain)
          : kind === "hvac"
            ? // an AC or dehumidifier: a state that reads on while it runs, or its power sensor
              [
                "switch",
                "input_boolean",
                "binary_sensor",
                "climate",
                "humidifier",
                "fan",
                "sensor",
              ].includes(c.domain)
            : kind === "timestamp"
              ? ["sensor", "input_datetime"].includes(c.domain)
              : kind === "binary"
                ? ["switch", "binary_sensor"].includes(c.domain)
                : kind === "light"
                  ? ["light", "switch"].includes(c.domain)
                  : kind === "camera"
                    ? c.domain === "camera"
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
                : kind === "temperature"
                  ? /°[CF]/.test(c.unit)
                    ? 2
                    : 0
                  : kind === "co2"
                    ? /ppm/i.test(c.unit)
                      ? 2
                      : 0
                    : kind === "ppfd" || kind === "dli"
                      ? /mol/i.test(c.unit)
                        ? 2
                        : 0
                      : 0;
        return preferred(b) - preferred(a) || a.name.localeCompare(b.name);
      });
  }
  const activeZones = draft?.zones.filter((z) => z.active) || [],
    archivedZones = draft?.zones.filter((z) => !z.active) || [];
  // An integration from before declared plumbing neither stores nor checks it: ask nothing.
  const asksPlumbing = !!data?.capabilities.plumbing;
  // What the room declared; else, for a room from before the question existed, what its SAVED
  // switches imply. Never the draft's switches: clearing the pump of a pumped room must raise
  // an error, not quietly turn the room into a tent. A new room has no answer until one is given.
  const plumbing = !asksPlumbing
    ? ""
    : draft?.plumbing || (isNew ? "" : original?.plumbing_inferred || "");
  const plumbingConfirmed = !asksPlumbing || isNew || !!draft?.plumbing;
  const errors: string[] = [];
  if (draft) {
    if (asksPlumbing && draft.active) {
      if (!plumbing) errors.push("Choose how this room is plumbed.");
      errors.push(...plumbingErrors(plumbing, draft.hardware));
    }
    if (!draft.room_name.trim()) errors.push("Name the room.");
    else if (isNew && roomSlug(draft.room_name) === "default")
      errors.push("Default is reserved for the original room. Choose another room name.");
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
          !!sizingError(
            z.substrate_volume ?? NaN,
            "substrate_volume",
            SIZING_UNITS.volume.metric,
          ) ||
          !Number.isFinite(z.drippers_per_plant) ||
          Number(z.drippers_per_plant) < 1 ||
          !!sizingError(z.dripper_flow_rate ?? NaN, "dripper_flow_rate", SIZING_UNITS.flow.metric),
      )
    )
      errors.push("Enter valid plant counts, pot volumes and dripper sizing.");
  }
  async function save() {
    if (!draft || !review) return;
    setBusy(true);
    setError("");
    try {
      if (!isNew && review === "save" && original) {
        const fresh = await controller.operator<SetupDocument>("setup_read");
        const current = fresh.rooms.find((r) => r.entry_id === original.entry_id);
        if (!current) throw new Error("This room was removed. Your draft is retained.");
        if (sizingChangedSince(original, current))
          throw new Error(
            "Live zone sizing changed since this draft opened. Your draft is retained; reload the room configuration before reviewing again.",
          );
      }
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
              ...(asksPlumbing && plumbing ? { plumbing } : {}),
            },
      );
      setReview(null);
      await load(result.entry_id);
      await controller.refresh();
      setNotice(
        review === "remove"
          ? "Room archived. Its identifiers and stored configuration are retained."
          : "The configuration is saved in Home Assistant. The controller can find and accept it at its next refresh. Keep the kill switch at off until you verify it.",
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  // A new room has no prefix until it is created (it then gets its own slug), so it never
  // borrows the descriptor or heartbeat of an older install's un-prefixed room.
  const engineConfig = isNew
    ? undefined
    : Object.values(controller.states).find(
        (e) => e.entity_id.endsWith("engine_config") && e.attributes.prefix === draft?.prefix,
      );
  const heartbeat = isNew
    ? undefined
    : Object.values(controller.states).find(
        (e) => e.entity_id === "sensor.crop_steering_" + draft?.prefix + "ai_heartbeat",
      );
  const confirmedRevision = Number(heartbeat?.attributes.setup_revision);
  const mappingConfirmed =
    !isNew && draft && Number.isFinite(confirmedRevision) && confirmedRevision >= draft.revision;
  const Installation = () => (
    <section className="panel workspace-card">
      <h2>Install, then map devices</h2>
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
            <h3>
              Install the controller app <UiTip copyKey="install the controller app" />
            </h3>
            <p>
              For Home Assistant OS/Supervised, add the repository and install Crop Steering. Keep
              watering off in every room while mapping hardware.
            </p>
            <Button asChild variant="outline">
              <a
                href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJakeTheRabbit%2FHA-Irrigation-Strategy"
                target="_blank"
                rel="noreferrer"
              >
                Add controller repository <ExternalLink size={15} />
              </a>
            </Button>
            <p>
              Home Assistant Container or Core: run the controller container instead.{" "}
              <a
                href="https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/INSTALL.md#home-assistant-container-or-core"
                target="_blank"
                rel="noreferrer"
              >
                How to run it <ExternalLink size={13} />
              </a>
            </p>
          </div>
        </li>
        <li>
          <span className="step-number">4</span>
          <div>
            <h3>
              Map, verify and start <UiTip copyKey="map, verify and start" />
            </h3>
            <p>
              Use Rooms and setup to select valves and probes, enter pot/dripper measurements,
              confirm the controller acknowledges the mapping, then review your grow plan. Switch
              watering on deliberately using Watering in the header for that room.
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
      {connected && <SupplyEditor key={controller.roomId} controller={controller} onDirtyChange={setSupplyDirty} />}
      <Heading
        title="Rooms and setup"
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
              <span className="label-with-tip">
                <Label htmlFor="setup-room">Room</Label>
                <UiTip copyKey="room configuration" />
              </span>
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
              title="Make your first room"
              detail="Add a room and map devices that already exist in Home Assistant."
              action={
                <span className="label-with-tip">
                  <Button onClick={addRoom}>Add room</Button>
                  <UiTip copyKey="add room" />
                </span>
              }
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
              {!isNew && original && needsWizard(original) && (
                <SetupWizard controller={controller} room={original} onStatus={wizardStatus} />
              )}
              <section className="panel workspace-card">
                <div className="workspace-section-heading">
                  <div>
                    <h2>Room name and status</h2>
                    <p className="muted">
                      Room labels can change. Existing controller identifiers stay stable.
                    </p>
                  </div>
                  {!isNew && (
                    <Pill dot tone={mappingConfirmed ? "on" : "warn"}>
                      {mappingConfirmed
                        ? "Mapping acknowledged"
                        : "Controller acknowledgement pending"}
                    </Pill>
                  )}
                </div>
                <div className="workspace-form-grid">
                  <div>
                    <span className="label-with-tip">
                      <Label htmlFor="room-name">Room name</Label>
                      <UiTip copyKey="room name" />
                    </span>
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
                        ? "Entity ids will start crop_steering_" + roomSlug(draft.room_name) + "_"
                        : "Revision " + draft.revision + " · " + (draft.prefix || "Default room")}
                    </p>
                    <Pill dot tone={engineConfig ? "on" : "warn"}>
                      {engineConfig ? "Room descriptor discovered" : "Awaiting room descriptor"}
                    </Pill>
                  </div>
                </div>
                {!isNew && !draft.safety.ready && (
                  <div className="workspace-message">
                    {draft.safety.blockers.map((b) => (
                      <p key={b}>{b}</p>
                    ))}
                    <p>
                      Mapping writes are checked again on the server. Switch watering off and verify
                      the mapped hardware is off before saving.
                    </p>
                    {draft.prefix === controller.room.room.prefix ? (
                      <Button
                        variant="outline"
                        onClick={() =>
                          document
                            .querySelector<HTMLButtonElement>('[data-safety="watering"]')
                            ?.focus()
                        }
                      >
                        Find this room’s watering control
                      </Button>
                    ) : (
                      <p>
                        The header controls {controller.room.room.name}, not this setup draft. Pause
                        the affected room in Home Assistant before retrying; your draft stays here.
                      </p>
                    )}
                  </div>
                )}
              </section>
              <section className="panel workspace-card">
                <div className="workspace-section-heading">
                  <div>
                    <h2>Shared room hardware</h2>
                    <p className="muted">
                      How the room is plumbed, then the switches and source-water probes that go
                      with it. Empty feed mappings leave that source-water gate disabled. Tank
                      display mappings show readings in Overview; they do not change feed-water
                      gates or operate the fill valve.
                    </p>
                  </div>
                </div>
                {asksPlumbing && (
                  <div className="setup-plumbing">
                    <span className="label-with-tip">
                      <Label htmlFor="room-plumbing">Room plumbing</Label>
                      <UiTip copyKey="how is this room plumbed?" />
                    </span>
                    <select
                      id="room-plumbing"
                      disabled={busy}
                      value={isPlumbingLayout(plumbing) ? plumbing : ""}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          plumbing: e.target.value,
                          hardware: hardwareForLayout(e.target.value, draft.hardware),
                        })
                      }
                    >
                      {!isPlumbingLayout(plumbing) && <option value="">Choose…</option>}
                      {(Object.keys(PLUMBING_LAYOUTS) as PlumbingLayout[]).map((name) => (
                        <option key={name} value={name}>
                          {PLUMBING_LABELS[name]}
                        </option>
                      ))}
                    </select>
                    <small className="muted">
                      {isPlumbingLayout(plumbing)
                        ? PLUMBING_HINTS[plumbing]
                        : "If water only comes out while a pump is running, the room has a pump."}{" "}
                      The switches below have to match this, and a room whose switches stop matching
                      is held rather than watered with the valve open and no pump.
                    </small>
                    {!plumbingConfirmed && isPlumbingLayout(plumbing) && (
                      <div className="workspace-message">
                        <p>
                          This room was set up before it could say how it is plumbed. Its saved
                          switches imply <strong>{PLUMBING_LABELS[plumbing]}</strong>. Until that is
                          confirmed, the controller goes on working it out from whichever switches
                          are mapped.
                        </p>
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() => setDraft({ ...draft, plumbing })}
                        >
                          <Check size={15} />
                          Confirm this plumbing
                        </Button>
                      </div>
                    )}
                  </div>
                )}
                <div className="workspace-form-grid">
                  {hardwareFields
                    .filter(([key]) => plumbingUses(plumbing, key))
                    // an older integration has no leaf sensor field: it would refuse one
                    .filter(([key]) => key !== "leaf_temperature_sensor" || key in draft.hardware)
                    .map(([key, label, kind]) => (
                      <MappingPicker
                        key={key}
                        label={label}
                        values={
                          typeof draft.hardware[key] === "string"
                            ? [String(draft.hardware[key])]
                            : []
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
                  {(
                    [
                      ["ac_entities", "ACs (runoff estimator)"],
                      ["dehumidifier_entities", "Dehumidifiers (runoff estimator)"],
                    ] as const
                  )
                    // an older integration has no such lists: it would refuse them
                    .filter(([key]) => Array.isArray(draft.hardware[key]))
                    .map(([key, label]) => (
                      <MappingPicker
                        key={key}
                        label={label}
                        values={draft.hardware[key] as string[]}
                        multiple
                        candidates={candidates("hvac")}
                        hint="Choose each unit's switch, state or power sensor"
                        disabled={busy}
                        onChange={(values) =>
                          setDraft({ ...draft, hardware: { ...draft.hardware, [key]: values } })
                        }
                      />
                    ))}
                </div>
              </section>
              <RunoffPanel controller={controller} />
              <section className="panel workspace-card">
                <div className="workspace-section-heading">
                  <div>
                    <h2>Zones and probe mapping</h2>
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
                      setDraft({
                        ...draft,
                        zones: [...draft.zones, newZone(id, data?.sizing_defaults)],
                      });
                    }}
                  >
                    <Plus size={16} />
                    Add zone
                  </Button>
                </div>
                <SizingUnitPickers units={units} disabled={busy} />
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
                          <Input
                            aria-label={"Zone " + zone.id + " cultivar"}
                            placeholder="Cultivar (optional)"
                            maxLength={40}
                            value={zone.cultivar ?? ""}
                            disabled={busy}
                            onChange={(e) => editZone(zone.id, { cultivar: e.target.value })}
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
                        {zone.leaf_temperature_sensor !== undefined && (
                          <MappingPicker
                            label={zone.name + " leaf temperature (optional)"}
                            values={
                              zone.leaf_temperature_sensor ? [zone.leaf_temperature_sensor] : []
                            }
                            candidates={candidates("temperature")}
                            disabled={busy}
                            onChange={(v) =>
                              editZone(zone.id, { leaf_temperature_sensor: v[0] || "" })
                            }
                          />
                        )}
                        <MappingPicker
                          label={zone.name + " root-zone temperature (display)"}
                          values={
                            zone.substrate_temperature_sensor
                              ? [zone.substrate_temperature_sensor]
                              : []
                          }
                          candidates={candidates("temperature")}
                          disabled={busy}
                          onChange={(v) =>
                            editZone(zone.id, { substrate_temperature_sensor: v[0] || "" })
                          }
                        />
                      </div>
                      <div className="workspace-form-grid sizing-grid">
                        {(
                          [
                            "plant_count",
                            "substrate_volume",
                            "drippers_per_plant",
                            "dripper_flow_rate",
                          ] as const
                        ).map((key) =>
                          key === "substrate_volume" || key === "dripper_flow_rate" ? (
                            <SizingField
                              key={key}
                              id={"zone-" + zone.id + "-" + key}
                              sizingKey={key}
                              unit={key === "substrate_volume" ? units.volume : units.flow}
                              value={zone[key] ?? NaN}
                              disabled={busy}
                              onChange={(metric) => editZone(zone.id, { [key]: metric })}
                            />
                          ) : (
                            <div key={key}>
                              <Label htmlFor={"zone-" + zone.id + "-" + key}>
                                {key === "plant_count" ? "Plants" : "Drippers per plant"}
                              </Label>
                              <Input
                                id={"zone-" + zone.id + "-" + key}
                                type="number"
                                min={1}
                                max={key === "plant_count" ? 1000 : 20}
                                step={1}
                                disabled={busy}
                                value={Number.isFinite(zone[key]) ? zone[key] : ""}
                                onChange={(e) =>
                                  editZone(zone.id, {
                                    [key]: e.target.value === "" ? NaN : Number(e.target.value),
                                  })
                                }
                              />
                            </div>
                          ),
                        )}
                      </div>
                      <div className="workspace-form-grid sizing-helpers">
                        <SubstratePresetPicker
                          id={"zone-" + zone.id + "-substrate-preset"}
                          volumeFieldId={"zone-" + zone.id + "-substrate_volume"}
                          litres={zone.substrate_volume ?? NaN}
                          disabled={busy}
                          onPick={(litres) => editZone(zone.id, { substrate_volume: litres })}
                        />
                        <CatchTestCalculator
                          id={"zone-" + zone.id + "-catch-test"}
                          zoneName={zone.name}
                          flowUnit={units.flow}
                          disabled={busy}
                          onUse={(flow) => editZone(zone.id, { dripper_flow_rate: flow })}
                        />
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
                    <h2>
                      Remove this room <UiTip copyKey="remove this room" />
                    </h2>
                    <p className="muted">
                      Archive the room while retaining its identifiers and configuration. Watering
                      and the hardware must be off.
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
      {tab === "rooms" && controller.roomId && (
        <>
          <section className="panel workspace-card" id="config-room_active">
            <h2>Room in use</h2>
            <RoomPower controller={controller} />
            <h3>All zone switches</h3>
            <AllZonesSwitch controller={controller} />
          </section>
          <ControllerSettings controller={controller} onDirtyChange={setSettingsDirty} />
          <CanonicalControls
            controller={controller}
            owner="equipment"
            onDirtyChange={setEquipmentDirty}
          />
          <HistoryConnection controller={controller} />
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
                : "Only the selected room configuration is changed. Watering is not switched on and no valve is actuated."}
            </DialogDescription>
          </DialogHeader>
          {!isNew && draft && !draft.safety.ready && (
            <div className="workspace-message" role="note">
              <strong>Equipment and sizing changes need watering off</strong>
              <p>
                Switch watering off for the affected rooms and wait for their equipment to stop
                before saving these changes.
              </p>
              {draft.safety.blockers.map((blocker) => (
                <p key={blocker}>{blocker}</p>
              ))}
              <p>
                Zone names and probe choices can still be saved while watering. Home Assistant
                checks the actual change again when you save.
              </p>
            </div>
          )}
          {review === "remove" ? (
            <div>
              <span className="label-with-tip">
                <Label htmlFor="confirm-room-name">Type the room name</Label>
                <UiTip copyKey="type the room name to confirm" />
              </span>
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
              {asksPlumbing && isPlumbingLayout(plumbing) && (
                <div className="workspace-message">
                  <strong>Plumbing: {PLUMBING_LABELS[plumbing]}</strong>
                  <p className="mapping-id">
                    {[draft?.hardware.pump_switch, draft?.hardware.main_line_switch]
                      .filter(Boolean)
                      .join(" → ") || "No pump or main-line valve: each zone is its one switch."}
                  </p>
                </div>
              )}
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
                    {z.plant_count} plants ×{" "}
                    {reviewValue(z.substrate_volume ?? NaN, "substrate_volume", units.volume)} ·{" "}
                    {z.drippers_per_plant} drippers per plant ×{" "}
                    {reviewValue(z.dripper_flow_rate ?? NaN, "dripper_flow_rate", units.flow)}
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
