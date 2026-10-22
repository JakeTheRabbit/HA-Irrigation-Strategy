import { Check } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Heading } from "@/components/dashboard";
import { NeedsIntegration } from "@/components/needs-integration";
import { CapacityBar } from "@/components/primitives/capacity-bar";
import { Sentence } from "@/components/primitives/sentence";
import { ReviewApply, type ApplyReceipt } from "@/components/review-apply";
import { ShotTimeline } from "@/components/shot-timeline";
import { Button } from "@/components/ui/button";
import { formatVolume } from "@/lib/display-units";
import { irrigationMode } from "@/lib/facility";
import { descriptor, zoneHasProbe } from "@/lib/model";
import { callV2, useParity, type V2Outcome } from "@/lib/parity-api";
import type { SupplyDoc, TimerPreview, TimerProgram, TimerProgramListItem } from "@/lib/parity-types";
import { clock, lightsWindow, startOfDay } from "@/lib/time";
import {
  TIMER_TYPE_HELP,
  TIMER_TYPE_LABEL,
  WINDOW_HELP,
  WINDOW_LABEL,
  consequence,
  dailyUse,
  durText,
  fieldErrors,
  modeNote,
  motherRoomProgram,
  newProgram,
  nextShotWords,
  previewRows,
  programBody,
  programRows,
  programStatus,
  readBackReceipt,
  readPrograms,
  restoreDeleted,
  restoredWords,
  sameProgram,
  sharedZoneError,
  timerTitle,
  timerTokens,
  type GrowDays,
  type IrrigationMode,
} from "@/lib/timers";
import { UndoError, offerUndo } from "@/lib/undo";
import { useNarrow } from "@/lib/use-narrow";
import { coreWaterValue, dailyWater, positiveCount, waterParameters } from "@/lib/water-delivery";
import type { PageProps } from "./placeholder";
import "./timers.css";

const HOUR = 3_600_000;
const MODES: { value: IrrigationMode; label: string }[] = [
  { value: "steering", label: "Steering" },
  { value: "timer", label: "Timer" },
  { value: "off", label: "Off" },
];
const modeLabel = (mode: string) => MODES.find((m) => m.value === mode)?.label ?? mode;
const UNCONFIRMED = /did not confirm|unconfirmed/i;
const hh = (hour: number) => `${String(Math.floor(hour)).padStart(2, "0")}:${String(Math.round((hour % 1) * 60)).padStart(2, "0")}`;
const minutes = (m: number) => `${Number(m.toFixed(1))} min`;
type Listed = { state: "loading" | "ready" | "missing" | "error"; programs: TimerProgramListItem[]; revision: number | null; error: string | null };
/** Two lists hold the same programs, ids included. */
const sameList = (a: TimerProgram[], b: TimerProgram[]) =>
  a.length === b.length && a.every((p) => b.some((q) => q.id === p.id && sameProgram(p, q)));
const copy = (p: TimerProgram): TimerProgram => ({ ...structuredClone(p) });

/** Timer programs (I3, mockup 07): the room's programs, an editor whose amount reads as a sentence,
 * the next 24 hours it waters, its daily limit and pump, and who waters each zone. Saves go through
 * Review & apply and are read back from the program list; a delete is undone from the Journal. */
export function Timers({ controller, onDirtyChange }: PageProps) {
  const { timeZone: tz, room, roomId, states } = controller;
  const prefix = room.room.prefix;
  const phone = useNarrow(720);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  const latest = useRef(states);
  latest.current = states;

  // The room's programs, and which one the editor holds ("" a new one).
  const [list, setList] = useState<Listed>({ state: "loading", programs: [], revision: null, error: null });
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<TimerProgram | null>(null);
  const load = useCallback(async () => {
    const out = await readPrograms(controller, roomId);
    if (out.kind === "ok") setList({ state: "ready", programs: out.data.programs, revision: out.data.revision, error: out.data.error ?? null });
    else if (out.kind === "missing") setList({ state: "missing", programs: [], revision: null, error: null });
    else setList((previous) => ({ ...previous, state: previous.state === "ready" ? "ready" : "error", error: out.message }));
    return out;
  }, [controller.operator, roomId]);
  useEffect(() => {
    void load();
  }, [load]);
  const open = (program: TimerProgram | null) => {
    setSelected(program ? program.id : null);
    setDraft(program ? copy(program) : null);
    setNote(null);
  };
  useEffect(() => {
    if (list.state === "ready" && selected === null && list.programs.length) open(list.programs[0]);
  }, [list]);
  const saved = selected ? (list.programs.find((p) => p.id === selected) ?? null) : null;
  const dirty = !!draft && (!saved || !sameProgram(saved, draft));
  useEffect(() => onDirtyChange(dirty), [dirty]);
  const [note, setNote] = useState<string | null>(null);
  const [lastSave, setLastSave] = useState<{ id: string; receipt: ApplyReceipt; program: TimerProgram } | null>(null);

  // The zones: their names, modes, probes, water per plant and daily limit.
  const names: Record<string, string> = { room: room.room.name };
  for (const z of room.zones) if (z.cultivar) names[z.id] = z.cultivar;
  const modeEntity = (zone: number) => `select.crop_steering_${prefix}zone_${zone}_irrigation_mode`;
  const rates: Record<number, number> = {};
  const perPlantMax: Record<number, number | null> = {};
  const zoneLph: Record<number, number | null> = {};
  // Today's water so far, in litres a plant (the zone's Water today reading); null without it.
  const usedToday: Record<number, number | null> = {};
  for (const z of room.zones) {
    const p = waterParameters(controller, z.id);
    const plants = positiveCount(p.plant_count) ? p.plant_count : null;
    const perPlantLph = p.dripper_flow_rate && p.drippers_per_plant ? p.dripper_flow_rate * p.drippers_per_plant : null;
    if (perPlantLph && perPlantLph > 0) rates[z.id] = perPlantLph / 3600;
    const limit = coreWaterValue("max_daily_volume", p.max_daily_volume).value;
    perPlantMax[z.id] = limit !== null && plants ? limit / plants : null;
    zoneLph[z.id] = perPlantLph && plants ? perPlantLph * plants : null;
    const water = dailyWater(z, plants);
    usedToday[z.id] = water.zoneL !== null && plants ? water.zoneL / plants : null;
  }
  const covered = (zone: number) => list.programs.some((p) => p.active && p.zones.includes(zone));

  // The next 24 hours, 250 ms after the last edit. The draft is only previewed, never saved.
  const [preview, setPreview] = useState<{ data: TimerPreview | null; error: string | null; missing?: boolean } | null>(null);
  const body = draft ? JSON.stringify(programBody(draft)) : null;
  useEffect(() => {
    if (!draft) return setPreview(null);
    const local = sharedZoneError(draft, list.programs);
    if (local) return setPreview({ data: null, error: local });
    let current = true;
    const timer = setTimeout(() => {
      void callV2<TimerPreview>(controller, "timer_program_preview", { room_id: roomId, program: programBody(draft), hours: 24 }).then((out) => {
        if (!current) return;
        setPreview(
          out.kind === "ok"
            ? { data: out.data, error: null }
            : out.kind === "missing"
              ? { data: null, error: null, missing: true }
              : { data: null, error: out.message },
        );
      });
    }, 250);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [body, roomId, list.programs]);
  const errors = fieldErrors(preview?.error ?? null);
  const errorOf = (...fields: string[]) =>
    errors
      .filter((e) => fields.includes(e.field))
      .map((e) => (
        <p key={e.field} className="tm-error" role="alert" data-field-error={e.field}>
          {e.message}
        </p>
      ));

  // Supply: the room's pump.
  const supply = useParity<SupplyDoc>(controller, "supply_get", {}, []);
  const roomPump = descriptor(states, room.room)?.attributes.pump;
  const pumps = supply.data?.irrigation_pumps ?? [];
  const pump = pumps.find((p) => p.entity_id === roomPump) ?? (pumps.length === 1 ? pumps[0] : null);
  const oneAtATime = pump?.max_concurrent_zones === 1;

  // Irrigation mode: a switch says what it does first, then is written and read back.
  const [pending, setPending] = useState<{ zone: number; mode: IrrigationMode } | null>(null);
  const [modeError, setModeError] = useState<{ zone: number; text: string } | null>(null);
  const [writing, setWriting] = useState(false);
  const switchMode = async (zone: number, mode: IrrigationMode, from: string) => {
    const entityId = modeEntity(zone);
    setWriting(true);
    try {
      const result = await controller.write([{ entityId, value: mode }]);
      setPending(null);
      if (!result.applied.includes(entityId)) {
        const reason = result.failed[0]?.reason ?? "";
        return setModeError({
          zone,
          text: UNCONFIRMED.test(reason) ? "The controller did not confirm the change. Reload and check it before trying again." : reason,
        });
      }
      setModeError(null);
      offerUndo({
        message: `Zone ${zone} set to ${modeLabel(mode)}. Written and read back ${clock(Date.now(), tz)}.`,
        undo: async () => {
          if (latest.current[entityId]?.state !== mode)
            throw new UndoError(`Zone ${zone}'s mode has changed since. Nothing was undone.`, 0, 1);
          const back = await controller.write([{ entityId, value: from }]);
          if (!back.applied.includes(entityId)) throw new UndoError(back.failed[0]?.reason ?? "Undo failed. Nothing was changed.", 0, 1);
          toast(`Zone ${zone} is back on ${modeLabel(from)}.`);
        },
      });
    } finally {
      setWriting(false);
    }
  };

  // Save, read back from the list; Undo puts the Journal's change back.
  const rows = draft
    ? programRows(saved, draft, names, tz, (field) => {
        if (!saved || field === "program") return open(list.programs[0] ?? null);
        setDraft((d) => (d ? ({ ...d, [field]: saved[field as keyof TimerProgram] } as TimerProgram) : d));
      })
    : [];
  const apply = async (): Promise<ApplyReceipt | Extract<V2Outcome<unknown>, { kind: "error" | "missing" }>> => {
    const sent = draft!;
    const asked = rows;
    const out = await callV2<{ program: TimerProgram; revision: number }>(controller, "timer_program_set", {
      room_id: roomId,
      expected_revision: list.revision,
      program: programBody(sent),
    });
    if (out.kind !== "ok") {
      if (out.kind === "error" && out.code === "stale_revision") void load();
      else if (out.kind === "error") setPreview({ data: null, error: out.message });
      return out;
    }
    const kept = { ...sent, id: out.data.program.id };
    const read = await load();
    const receipt = readBackReceipt(
      asked,
      kept,
      read.kind === "ok" ? { kind: "ok", programs: read.data.programs } : { kind: "error" },
      { names, tz },
      Date.now(),
      out.eventIds,
    );
    const listed = read.kind === "ok" ? read.data.programs.find((p) => p.id === kept.id) : undefined;
    if (receipt.ok && listed) {
      setLastSave({ id: kept.id, receipt, program: listed });
      open(listed);
    }
    return receipt;
  };
  const undoSave = async (receipt: ApplyReceipt) => {
    const last = lastSave;
    if (!last || !receipt.eventIds.length)
      throw new UndoError("The controller has no record of this change to put back. Nothing was undone.", 0, 1);
    const check = await readPrograms(controller, roomId);
    const now = check.kind === "ok" ? check.data.programs.find((p) => p.id === last.id) : undefined;
    if (!now || !sameProgram(now, last.program))
      throw new UndoError("This program has changed since you saved it. Nothing was undone.", 0, 1);
    const id = await restoreDeleted(controller, receipt.eventIds, last.id);
    const after = await load();
    const back = after.kind === "ok" ? after.data.programs.find((p) => p.id === id) : undefined;
    if (back) setDraft(copy(back));
    else open(after.kind === "ok" ? (after.data.programs[0] ?? null) : null);
  };

  const [deleting, setDeleting] = useState(false);
  const remove = async () => {
    if (!saved) return open(list.programs[0] ?? null);
    const gone = saved;
    const title = timerTitle(gone, names, tz);
    setDeleting(true);
    try {
      const out = await callV2(controller, "timer_program_delete", { room_id: roomId, expected_revision: list.revision, id: gone.id });
      if (out.kind === "missing") return setNote("Deleting a program needs Crop Steering 3.18 or newer.");
      if (out.kind === "error") {
        if (out.code === "stale_revision") await load();
        return setNote(out.message);
      }
      const read = await load();
      const rest = read.kind === "ok" ? read.data.programs : [];
      open(rest[0] ?? null);
      if (read.kind !== "ok" || rest.some((p) => p.id === gone.id))
        return void toast("Delete sent, not confirmed. Check the programs.");
      if (!out.eventIds.length) return void toast(`Deleted: ${title}.`);
      offerUndo({
        message: `Deleted: ${title}.`,
        undo: async () => {
          const check = await readPrograms(controller, roomId);
          if (check.kind !== "ok" || !sameList(check.data.programs, rest))
            throw new UndoError("The timer programs changed since the delete. Nothing was undone.", 0, 1);
          const id = await restoreDeleted(controller, out.eventIds, gone.id);
          const after = await load();
          const back = after.kind === "ok" ? after.data.programs.find((p) => p.id === id) : undefined;
          if (back) open(back);
          toast(restoredWords(title, id, after.kind === "ok" ? after.data.programs : []));
        },
      });
    } finally {
      setDeleting(false);
    }
  };

  const lightsOn = Number(states[`number.crop_steering_${prefix}lights_on_hour`]?.state);
  const lightsOff = Number(states[`number.crop_steering_${prefix}lights_off_hour`]?.state);
  const lights = useMemo(() => {
    if (!Number.isFinite(lightsOn) || !Number.isFinite(lightsOff)) return [];
    const today = startOfDay(now, tz);
    return [-1, 0, 1].map((d) => lightsWindow(startOfDay(today + d * 24 * HOUR + 12 * HOUR, tz), hh(lightsOn), hh(lightsOff), tz));
  }, [lightsOn, lightsOff, now, tz]);
  // The grow-days the next 24 hours span: a new one at each lights-on; without the lights hours
  // they can't be told apart.
  const days: GrowDays | null = lights.length
    ? { resets: lights.map((l) => l.on).filter((t) => t > now && t <= now + 24 * HOUR), usedToday }
    : null;

  if (list.state === "missing")
    return (
      <>
        <Heading title="Timer programs" />
        <section className="panel timers-missing" aria-labelledby="timers-missing-title">
          <h2 id="timers-missing-title" className="sr-only">
            Timer programs
          </h2>
          <NeedsIntegration feature="Timer programs" />
        </section>
      </>
    );

  const timerZones = room.zones.filter((z) => irrigationMode(states, room.room, z.id) === "timer");
  const freeZones = timerZones.map((z) => z.id).filter((z) => !covered(z));
  const index = saved ? list.programs.findIndex((p) => p.id === saved.id) : -1;

  const programs = (
    <section className="panel tm-programs" aria-labelledby="tm-programs-title">
      <div className="tm-head">
        <h2 id="tm-programs-title">
          Programs <small>for zones without probes</small>
        </h2>
        <Button variant="outline" size="sm" onClick={() => open(newProgram(roomId, freeZones, list.programs.length + 1))}>
          New program
        </Button>
      </div>
      {list.state === "error" && !list.programs.length ? (
        <div className="tm-empty" role="alert">
          <p>Couldn't read the timer programs: {list.error}</p>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      ) : list.state === "ready" && !list.programs.length && selected !== "" ? (
        <div className="tm-empty" data-timers-empty>
          <p>No timer yet. Most mother rooms use 2 min every 2 h during lights-on.</p>
          <Button size="sm" onClick={() => open(motherRoomProgram(roomId, freeZones))}>
            Use that
          </Button>
        </div>
      ) : (
        <ul className="tm-list">
          {list.programs.map((p) => (
            <li key={p.id}>
              <button type="button" className="tm-card" aria-pressed={p.id === selected} onClick={() => open(p)} data-program={p.id}>
                <b>{timerTitle(p, names, tz)}</b>
                <span className="tm-status" data-on={p.active || undefined}>
                  {programStatus(p, now, tz)}
                </span>
                {p.error && <span className="tm-error">{p.error}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );

  const modes = (
    <section className="panel tm-modes" aria-labelledby="tm-modes-title">
      <div className="tm-head">
        <h2 id="tm-modes-title">
          Irrigation mode <small>who waters each zone</small>
        </h2>
      </div>
      <ul className="tm-mode-list">
        {room.zones.map((z) => {
          const mode = irrigationMode(states, room.room, z.id);
          const options = states[modeEntity(z.id)]?.attributes.options;
          const probe = zoneHasProbe(z, states);
          const asked = pending?.zone === z.id ? pending : null;
          const line = modeNote({ zone: z.id, mode: asked?.mode ?? mode ?? "", hasProbe: probe, covered: covered(z.id), pending: !!asked });
          return (
            <li key={z.id} data-zone={z.id}>
              <span className="tm-mode-name">{z.name}</span>
              {mode === null ? (
                <span className="tm-muted">This zone has no irrigation mode setting.</span>
              ) : (
                <div className="tm-seg" role="group" aria-label={`Irrigation mode for ${z.name}`}>
                  {MODES.filter((m) => !Array.isArray(options) || options.includes(m.value)).map((m) => {
                    const blocked = m.value === "steering" && !probe;
                    return (
                      <button
                        key={m.value}
                        type="button"
                        aria-pressed={(asked?.mode ?? mode) === m.value}
                        data-mode={m.value}
                        disabled={blocked || writing}
                        title={blocked ? "Needs a probe in this zone" : undefined}
                        onClick={() => {
                          setModeError(null);
                          setPending(m.value === mode ? null : { zone: z.id, mode: m.value });
                        }}
                      >
                        {m.label}
                      </button>
                    );
                  })}
                </div>
              )}
              {line && (
                <p className="tm-mode-note" data-tone={asked ? "pending" : mode === "off" ? "bad" : mode === "timer" && !covered(z.id) ? "warn" : undefined}>
                  {line}
                </p>
              )}
              {asked && mode !== null && (
                <div className="tm-mode-confirm">
                  <Button size="sm" disabled={writing} onClick={() => void switchMode(z.id, asked.mode, mode)}>
                    {writing ? "Sending…" : `Switch ${z.name} to ${modeLabel(asked.mode)}`}
                  </Button>
                  <Button size="sm" variant="outline" disabled={writing} onClick={() => setPending(null)}>
                    Keep {modeLabel(mode)}
                  </Button>
                </div>
              )}
              {modeError?.zone === z.id && (
                <p className="tm-error" role="alert">
                  {modeError.text}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );

  let editor: ReactNode = null;
  if (draft) {
    const set = (p: TimerProgram) => setDraft(p);
    const listedZones = room.zones.filter((z) => irrigationMode(states, room.room, z.id) === "timer" || draft.zones.includes(z.id));
    const shots = preview?.data?.preview ?? [];
    const firstShot = shots[0];
    const use = dailyUse(shots, draft.zones, rates, perPlantMax, days);
    const lph = draft.zones.map((z) => ({ zone: z, lph: zoneLph[z] ?? null }));
    const segments = (oneAtATime ? [...lph].sort((a, b) => (b.lph ?? 0) - (a.lph ?? 0)).slice(0, 1) : lph)
      .filter((s): s is { zone: number; lph: number } => s.lph !== null)
      .map((s) => ({ id: String(s.zone), label: `Zone ${s.zone}`, lph: s.lph, tone: "primary" }));
    const needs = segments.reduce((sum, s) => sum + s.lph, 0);
    const pumpName = pump ? String(states[pump.entity_id]?.attributes.friendly_name ?? "The room's pump") : "";
    const zonesSorted = [...draft.zones].sort((a, b) => a - b);
    editor = (
      <section className="panel tm-editor" aria-labelledby="tm-editor-title" data-timer-editor>
        <p className="tm-kicker">
          {saved ? `Program ${index + 1} · ${saved.active ? "Running" : "Draft"}` : "New program"}
          {dirty && <span className="tm-chip">Unsaved edits</span>}
        </p>
        <h2 id="tm-editor-title">{timerTitle(draft, names, tz)}</h2>
        <div className="tm-fields">
          <span className="tm-label" id="tm-type">
            Type
          </span>
          <div className="tm-field">
            <div className="tm-seg" role="group" aria-labelledby="tm-type">
              {(Object.keys(TIMER_TYPE_LABEL) as TimerProgram["type"][]).map((type) => (
                <button
                  key={type}
                  type="button"
                  aria-pressed={draft.type === type}
                  onClick={() =>
                    set({
                      ...draft,
                      type,
                      interval_min: draft.interval_min ?? 30,
                      frequency_per_day: draft.frequency_per_day ?? 6,
                      start_at: draft.start_at ?? new Date(Math.ceil(now / HOUR) * HOUR).toISOString(),
                    })
                  }
                >
                  {TIMER_TYPE_LABEL[type]}
                </button>
              ))}
            </div>
            <span className="tm-help">{TIMER_TYPE_HELP[draft.type]}</span>
            {errorOf("type")}
          </div>

          <span className="tm-label" id="tm-zones">
            Zones
          </span>
          <div className="tm-field">
            {listedZones.length ? (
              <div className="tm-zones" role="group" aria-labelledby="tm-zones">
                {listedZones.map((z) => (
                  <label key={z.id}>
                    <input
                      type="checkbox"
                      checked={draft.zones.includes(z.id)}
                      onChange={(e) =>
                        set({ ...draft, zones: e.target.checked ? [...draft.zones, z.id].sort((a, b) => a - b) : draft.zones.filter((n) => n !== z.id) })
                      }
                    />
                    {z.name}
                    {z.cultivar ? ` · ${z.cultivar}` : ""}
                  </label>
                ))}
              </div>
            ) : (
              <span className="tm-muted">No zone is set to Timer yet. Set one under Irrigation mode.</span>
            )}
            <span className="tm-help">Only zones set to Timer are listed</span>
            {errorOf("zones")}
          </div>

          <span className="tm-label">Amount</span>
          <div className="tm-field">
            <Sentence parts={timerTokens(draft, set, { now, timeZone: tz })} phone={phone} ariaLabel="Amount" />
            {errorOf("duration_s", "interval_min", "frequency_per_day", "start_at", "end", "times")}
          </div>

          {draft.type !== "one_off" && (
            <>
              <span className="tm-label" id="tm-when">
                When
              </span>
              <div className="tm-field">
                <div className="tm-seg" role="group" aria-labelledby="tm-when">
                  {(Object.keys(WINDOW_LABEL) as TimerProgram["window"]["kind"][]).map((kind) => (
                    <button
                      key={kind}
                      type="button"
                      aria-pressed={draft.window.kind === kind}
                      onClick={() =>
                        set({ ...draft, window: kind === "custom" ? { kind, from: draft.window.from ?? "08:00", to: draft.window.to ?? "12:00" } : { kind } })
                      }
                    >
                      {WINDOW_LABEL[kind]}
                    </button>
                  ))}
                </div>
                <span className="tm-help">{WINDOW_HELP[draft.window.kind]}</span>
                {errorOf("window")}
              </div>
            </>
          )}
        </div>

        <section className="tm-preview" aria-labelledby="tm-preview-title" data-timer-preview>
          <div className="tm-preview-head">
            <h3 id="tm-preview-title">Next 24 hours</h3>
            <span data-timer-summary>
              {preview?.data
                ? `${consequence(preview.data, rates, perPlantMax, days)}${firstShot ? ` First ${nextShotWords(firstShot.at, now, tz)}.` : ""}`
                : preview?.missing
                  ? "The next 24 hours need Crop Steering 3.18 or newer."
                  : preview?.error
                    ? "Fix the program to see its shots."
                    : "Working out the shots…"}
            </span>
          </div>
          {errorOf("program")}
          {preview?.data && zonesSorted.length > 0 && (
            <>
              <ShotTimeline
                mode="preview"
                rows={previewRowsFor(zonesSorted)}
                span={{ start: now, end: now + 24 * HOUR }}
                now={now}
                timeZone={tz}
              />
              <div className="st-legend tm-legend" aria-label="Legend">
                <span data-glyph="planned">This program</span>
                {oneAtATime && zonesSorted.length > 1 && <span data-glyph="queued">Waiting for pump</span>}
                {previewRowsFor(zonesSorted).some((r) => r.blocks.some((b) => b.glyph === "failed")) && (
                  <span data-glyph="failed">Blocked by daily max</span>
                )}
                {lights.length > 0 && (
                  <span data-glyph="lights">
                    Lights on {hh(lightsOn)}–{hh(lightsOff)}
                  </span>
                )}
              </div>
            </>
          )}
        </section>

        <div className="tm-cards">
          <section className="tm-cardbox" aria-labelledby="tm-daily">
            <h3 id="tm-daily">Daily max per zone</h3>
            {use && use.allowedMin !== null ? (
              <>
                <span className="tm-meter" aria-hidden="true">
                  <span style={{ width: `${Math.min(100, (use.usedMin / use.allowedMin) * 100)}%` }} data-over={use.usedMin > use.allowedMin || undefined} />
                </span>
                <p>
                  <b>{minutes(use.usedMin)}</b> of {minutes(use.allowedMin)} a day{use.today ? " today" : " in the next grow-day"}{draft.zones.length > 1 ? ` · Zone ${use.zone}` : ""}
                </p>
              </>
            ) : (
              <p>
                {draft.zones.length && perPlantMax[draft.zones[0]] !== null
                  ? `Daily limit ${formatVolume(perPlantMax[draft.zones[0]]!, 2)} per plant. The minutes it allows need the zone's dripper flow.`
                  : "The daily limit needs the zone's plant count and dripper flow."}
              </p>
            )}
            <small>Per zone, all programs together. Shots past it are skipped and logged.</small>
          </section>
          <section className="tm-cardbox" aria-labelledby="tm-pump">
            <h3 id="tm-pump">Pump capacity</h3>
            {supply.state === "missing" ? (
              <NeedsIntegration feature="Pump capacity" compact />
            ) : pump ? (
              <>
                {pump.max_flow_lph && segments.length ? (
                  <CapacityBar
                    segments={segments}
                    capacityLph={pump.max_flow_lph}
                    caption={`${Math.round(needs)} L/h of the pump's ${pump.max_flow_lph} L/h`}
                  />
                ) : null}
                <p>
                  <b>
                    {pumpName} runs {oneAtATime ? "one zone at a time" : `up to ${pump.max_concurrent_zones} zones at once`}
                  </b>
                </p>
                <small>
                  {oneAtATime && zonesSorted.length > 1
                    ? `Zone ${zonesSorted[1]} starts when zone ${zonesSorted[0]} finishes, ${durText(draft.duration_s)} later each time.`
                    : supply.data && !supply.data.capacity_check.ok
                      ? "The pump cannot feed every zone it may run at once."
                      : pump.max_flow_lph && segments.length
                        ? `${Math.round(needs)} L/h of ${pump.max_flow_lph} L/h.`
                        : ""}
                </small>
              </>
            ) : (
              <p>No pump is set up for this room yet.</p>
            )}
          </section>
          <section className="tm-cardbox" aria-labelledby="tm-safety">
            <h3 id="tm-safety">Same safety as steering</h3>
            <ul className="tm-checks">
              {["Stop all / room stop", "Source-water pH/EC check", "Feed tank level guard"].map((t) => (
                <li key={t}>
                  <Check aria-hidden size={16} />
                  {t}
                </li>
              ))}
            </ul>
          </section>
        </div>

        <div className="tm-foot">
          <Button variant="outline" className="tm-delete" disabled={deleting} onClick={() => void remove()}>
            {saved ? "Delete program" : "Discard new program"}
          </Button>
          <div className="tm-save">
            {(rows.length > 0 || lastSave?.id === selected) && (
            <ReviewApply
              key={selected ?? ""}
              rows={rows}
              layout="bar"
              apply={apply}
              onDiscard={() => open(saved ?? list.programs[0] ?? null)}
              onReload={() => void load().then((out) => out.kind === "ok" && open(out.data.programs.find((p) => p.id === selected) ?? out.data.programs[0] ?? null))}
              last={lastSave?.id === selected ? lastSave.receipt : null}
              timeZone={tz}
              undo={undoSave}
            />
            )}
            {!dirty && saved && (
              <Button variant="secondary" disabled>
                Saved
              </Button>
            )}
          </div>
          {note && (
            <p className="tm-error" role="alert">
              {note}
            </p>
          )}
        </div>
      </section>
    );
  }

  function previewRowsFor(zones: number[]) {
    return previewRows(preview?.data?.preview ?? [], {
      roomName: room.room.name,
      zones: zones.map((zone) => {
        const z = room.zones.find((q) => q.id === zone);
        return { zone, label: z?.name ?? `Zone ${zone}`, sublabel: z?.cultivar ?? "timer" };
      }),
      rates,
      dailyMax: perPlantMax,
      oneAtATime,
      lights,
      days,
    });
  }

  return (
    <>
      <Heading title="Timer programs" />
      <div className="timers" data-timers>
        <div className="tm-side">
          {programs}
          {!phone && modes}
        </div>
        {editor ?? (
          <section className="panel tm-editor tm-editor-empty" aria-label="Program">
            <p className="tm-muted">{list.state === "loading" ? "Reading the timer programs…" : "Pick a program, or start a new one."}</p>
          </section>
        )}
        {phone && modes}
      </div>
    </>
  );
}
