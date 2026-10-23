import { NotificationPredictions } from "@/components/notification-predictions";
import { CanonicalControls } from "@/components/canonical-controls";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, LoaderCircle, Plus, Send, Trash2 } from "lucide-react";
import { Popover } from "radix-ui";
import { toast } from "sonner";
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
import { Empty, Heading } from "@/components/dashboard";
import { UiTip } from "@/components/info-tip";
import { NeedsIntegration } from "@/components/needs-integration";
import { ReviewApply, type ApplyReceipt } from "@/components/review-apply";
import { useDraft } from "@/lib/drafts";
import {
  IDLE_HOURS,
  IDLE_NOTE,
  NotifyRefusal,
  QUIET_NOTE,
  applyChecks,
  canEditRow,
  draftChanges,
  draftSummary,
  fieldErrors,
  hasNotifyConfig,
  isClock,
  kindCoverage,
  lightSpans,
  liveRevision,
  muteEndWords,
  muteUndoTarget,
  mutePayload,
  newRecipient,
  notifyError,
  parseNotifyDocument,
  parseTestResult,
  phoneLabel,
  pressRoom,
  quietSpans,
  quietWords,
  rebaseDraft,
  reviewRows,
  roomChipWords,
  roomsWithoutEmergencies,
  rowLabel,
  sameDraft,
  sameMuteEnd,
  savePayload,
  saveReceipt,
  saveRefusal,
  serviceFromText,
  spanMinutes,
  testLine,
  testPhones,
  toDraft,
  toggleKind,
  unlistedPhones,
  updateRow,
  type NotifyConfig,
  type NotifyDocument,
  type NotifyDraft,
  type NotifyKind,
  type NotifyPhone,
  type NotifyRecipient,
  type NotifyTestResult,
  type QuietHours,
  type Span,
} from "@/lib/notify";
import { clock, dayEndText, hourClock, wallText } from "@/lib/time";
import type { Controller, Room } from "@/lib/types";
import { UndoError, offerUndo } from "@/lib/undo";
import { errorText } from "@/lib/utils";
import "./notifications.css";

/** A row as the grid and the cards draw it. */
interface RowView {
  recipient: NotifyRecipient;
  /** The row as saved; undefined for one this draft adds. */
  saved: NotifyRecipient | undefined;
  label: { title: string; subtitle: string | null; name: string };
  editable: boolean;
}
interface TestState {
  busy: boolean;
  result?: NotifyTestResult;
  at?: number;
}
const MUTE_MS = 2 * 3_600_000;
const EMPTY: NotifyDraft = { idle_hours: IDLE_HOURS.fallback, recipients: [] };
/** The window the quiet-hours editor shows for a phone without quiet hours: nothing is applied
 * until they are turned on or changed. */
const FIRST_WINDOW: QuietHours = { from: "22:00", to: "06:00" };
const hoursText = (minutes: number) => `${Number((minutes / 60).toFixed(2))} h`;

/** `notify_get`. An answer with an error and no setup is that error, never an empty setup. */
async function readNotify(controller: Controller): Promise<NotifyDocument> {
  const raw = await controller.operator<unknown>("notify_get");
  const doc = parseNotifyDocument(raw);
  if (doc.error && !hasNotifyConfig(raw)) throw new Error(doc.error);
  return doc;
}
/** `notify_save`, and the setup it answers with (read again when the answer lacks it). A refusal
 * throws in the integration's words, as given. */
async function saveNotify(controller: Controller, payload: Record<string, unknown>) {
  const raw = await controller.operator<unknown>("notify_save", payload);
  const result = parseNotifyDocument(raw);
  if (result.error) throw new NotifyRefusal(result.error);
  return hasNotifyConfig(raw) ? result : readNotify(controller);
}

/** What a kind of alert covers: its codes with their titles from Help's list, and its events. */
function KindCoverage({ kind }: { kind: NotifyKind }) {
  const { codes, events } = kindCoverage(kind);
  return (
    <>
      {kind.detail && <p className="notify-kind-detail">{kind.detail}</p>}
      {!!codes.length && (
        <ul className="notify-kind-codes">
          {codes.map(({ code, title }) => (
            <li key={code}>
              {title ? <a href={`#/help?code=${code}`}>{code}</a> : <code>{code}</code>}
              <span>{title ?? "Not in Help's list yet"}</span>
            </li>
          ))}
        </ul>
      )}
      {!!events.length && (
        <ul className="notify-kind-events">
          {events.map((event) => (
            <li key={event}>{event.charAt(0).toUpperCase() + event.slice(1)}, as a push</li>
          ))}
        </ul>
      )}
    </>
  );
}

/** A column heading: opened by a click or tap, it says what the kind covers. */
function KindHeading({ kind }: { kind: NotifyKind }) {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className="notify-kind-trigger">
          {kind.name}
          <ChevronDown size={10} aria-hidden="true" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        {/* Long enough to scroll on a short screen: keyboard-focusable so arrow keys can scroll it. */}
        <Popover.Content
          className="notify-kind-popover"
          aria-label={kind.name}
          tabIndex={0}
          side="bottom"
          align="center"
          sideOffset={6}
          collisionPadding={12}
        >
          <strong className="notify-kind-name">{kind.name}</strong>
          <KindCoverage kind={kind} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** The rooms a row covers: a chip per room of the site, every chip on for every room, and a room
 * it names that the site no longer has; under them, "every room" or "F2 only". */
function RoomChips({
  rooms,
  value,
  name,
  disabled,
  onChange,
}: {
  rooms: readonly Room[];
  value: readonly string[];
  name: string;
  disabled: boolean;
  onChange: (rooms: string[]) => void;
}) {
  const all = rooms.map((room) => room.prefix);
  const gone = value.filter((prefix) => !all.includes(prefix));
  return (
    <div className="notify-rooms-cell">
      <div className="notify-rooms" role="group" aria-label={`${name}: rooms`}>
        {rooms.map((room) => (
          <button
            type="button"
            key={room.id}
            aria-pressed={!value.length || value.includes(room.prefix)}
            disabled={disabled}
            onClick={() => onChange(pressRoom(value, room.prefix, all))}
          >
            {room.name}
          </button>
        ))}
        {gone.map((prefix) => (
          <button
            type="button"
            key={`gone-${prefix}`}
            aria-pressed="true"
            disabled={disabled}
            title="This room is not on this site now. Select it to remove it from the phone."
            onClick={() => onChange(value.filter((room) => room !== prefix))}
          >
            {prefix || "Default room"} (gone)
          </button>
        ))}
      </div>
      <small className="notify-rooms-words">{roomChipWords(value, rooms)}</small>
    </div>
  );
}

/** Add a phone: one of the site's phones not listed yet, or any notify service by its name. */
function AddPhone({
  phones,
  listed,
  onAdd,
  onClose,
}: {
  phones: readonly NotifyPhone[];
  listed: ReadonlySet<string>;
  onAdd: (service: string) => void;
  onClose: () => void;
}) {
  const id = useId();
  const [choice, setChoice] = useState(phones[0]?.service ?? "");
  const [typed, setTyped] = useState("");
  const typedService = serviceFromText(typed);
  const typedError = !typed.trim()
    ? null
    : !typedService
      ? "Type a notify service, such as notify.mobile_app_pixel_7."
      : listed.has(typedService)
        ? `${typedService} is already listed.`
        : null;
  const service = choice ? choice : typedService;
  const ready = !!service && !listed.has(service);
  return (
    <form
      className="notify-add"
      onSubmit={(event) => {
        event.preventDefault();
        if (service && ready) onAdd(service);
      }}
    >
      <fieldset className="notify-add-choices">
        <legend className="sr-only">The phone to add</legend>
        {phones.map((phone) => (
          <label className="notify-add-choice" key={phone.service}>
            <input
              type="radio"
              name={`${id}-phone`}
              checked={choice === phone.service}
              onChange={() => setChoice(phone.service)}
            />
            <span>
              <strong>{phoneLabel(phone)}</strong>
              <small>{phone.service}</small>
            </span>
          </label>
        ))}
        <label className="notify-add-choice">
          <input
            type="radio"
            name={`${id}-phone`}
            checked={!choice}
            onChange={() => setChoice("")}
          />
          <span>
            <strong>A notify service by its name</strong>
            <small>A group, Supernotify, or a phone this list does not have</small>
          </span>
        </label>
      </fieldset>
      {!choice && (
        <div className="notify-add-service">
          <span className="label-with-tip">
            <Label htmlFor={`${id}-service`}>Notify service</Label>
            <UiTip copyKey="notify service" />
          </span>
          <Input
            id={`${id}-service`}
            value={typed}
            placeholder="notify.mobile_app_phone"
            autoComplete="off"
            spellCheck={false}
            autoFocus
            aria-invalid={!!typedError}
            aria-describedby={`${id}-service-help`}
            onChange={(event) => setTyped(event.target.value)}
          />
          <small id={`${id}-service-help`} className={typedError ? "field-error" : "muted"}>
            {typedError ?? "The service's name as Home Assistant lists it under Actions."}
          </small>
        </div>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <div className="flex items-center gap-1">
          <Button type="submit" className="flex-1 sm:flex-none" disabled={!ready}>
            Add
          </Button>
          <UiTip copyKey="add" />
        </div>
      </DialogFooter>
    </form>
  );
}

/** One day as a 24-hour strip: the quiet hours of every phone as one band, each room's lights on
 * as a line over it. */
function DayStrip({ quiet, lights }: { quiet: Span[]; lights: Span[] }) {
  const pct = (minute: number) => `${(minute / 1440) * 100}%`;
  return (
    <div className="notify-strip" data-quiet-strip aria-hidden="true">
      <div className="notify-strip-bar">
        {quiet.map(([a, b]) => (
          <span
            key={`q${a}`}
            className="notify-strip-quiet"
            data-quiet-span={`${a}-${b}`}
            style={{ left: pct(a), width: pct(b - a) }}
          />
        ))}
        {lights.map(([a, b]) => (
          <span
            key={`l${a}`}
            className="notify-strip-lights"
            style={{ left: pct(a), width: pct(b - a) }}
          />
        ))}
      </div>
      <div className="notify-strip-ticks">
        {["00:00", "06:00", "12:00", "18:00", "24:00"].map((tick) => (
          <span key={tick}>{tick === "24:00" ? dayEndText() : wallText(tick)}</span>
        ))}
      </div>
    </div>
  );
}

/** Settings & help › Notifications: which phones get a push for which alerts, quiet hours and room
 * mutes, for the whole site (docs/NOTIFICATIONS.md). Edits are a draft (kept in this tab) until
 * applied with `notify_save` against the revision they were read at; a mute applies at once, with
 * Undo. The page itself never sends a push but a test one. */
export function Notifications({
  controller,
  onDirtyChange,
}: {
  controller: Controller;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const id = useId();
  const tz = controller.timeZone;
  const [doc, setDoc] = useState<NotifyDocument | null>(null);
  const [loadError, setLoadError] = useState("");
  const [reads, setReads] = useState(0);
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [testingAll, setTestingAll] = useState(false);
  const [adding, setAdding] = useState(0);
  /** The phone whose quiet hours the editor shows. */
  const [quietFor, setQuietFor] = useState<string | null>(null);
  const [muting, setMuting] = useState<string | null>(null);
  const added = useRef<string | null>(null);
  /** The setup a save replaced, and the revision the save made: what its Undo writes back. */
  const lastSave = useRef<{ before: NotifyConfig; revision: number } | null>(null);
  const saved = doc ? toDraft(doc.config) : EMPTY;
  const stored = useDraft<NotifyDraft>("notify", saved);
  const dirty = !!doc && !sameDraft(stored.draft, saved);
  const shown = dirty ? stored.draft : saved;
  const latest = useRef({ doc, shown, dirty });
  latest.current = { doc, shown, dirty };
  const connected = ["live", "demo"].includes(controller.connection);

  /** A setup read: a draft on the one read before is carried onto it, field by field. */
  const loaded = (next: NotifyDocument) => {
    const { doc: before, shown: draft, dirty: changed } = latest.current;
    if (before && changed) {
      const carried = rebaseDraft(before.config, draft, next.config);
      if (sameDraft(carried, toDraft(next.config))) stored.discard();
      else stored.set(carried);
    }
    setDoc(next);
  };
  useEffect(() => {
    if (controller.connection === "connecting") return;
    let current = true;
    readNotify(controller)
      .then((next) => {
        if (!current) return;
        loaded(next);
        setLoadError(next.error ?? "");
      })
      .catch((err) => current && setLoadError(errorText(err)));
    return () => {
      current = false;
    };
    // `loaded` reads the latest state through a ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller.connection, reads]);
  // Saved elsewhere (the integration's sensor moved on): read it again, the draft kept on top.
  const live = liveRevision(controller.states);
  const revision = doc?.config.revision;
  useEffect(() => {
    if (revision !== undefined && live !== null && live !== revision) setReads((n) => n + 1);
  }, [live, revision]);
  // A mute that ends while the page is open: draw the page again then.
  const [ticks, setTicks] = useState(0);
  const mutes = doc?.config.mutes;
  useEffect(() => {
    const now = Date.now();
    const next = Math.min(...Object.values(mutes ?? {}).filter((at) => at > now));
    if (!Number.isFinite(next)) return;
    const timer = window.setTimeout(
      () => setTicks((n) => n + 1),
      Math.min(next - now + 250, 2 ** 31 - 1),
    );
    return () => window.clearTimeout(timer);
  }, [mutes, ticks]);
  const [policyDirty, setPolicyDirty] = useState(false);
  useLayoutEffect(() => {
    onDirtyChange(dirty || policyDirty);
    return () => onDirtyChange(false);
  }, [dirty, policyDirty, onDirtyChange]);

  if (!doc)
    return (
      <>
        <Heading title="Notifications" />
        {loadError ? (
          <Empty
            title="Notifications not available"
            detail={`${loadError} Choosing who gets which alerts needs the updated Crop Steering integration.`}
          />
        ) : (
          <p className="muted">Loading notifications…</p>
        )}
      </>
    );

  const rooms = controller.rooms;
  const admin = doc.can_edit_all;
  const context = { kinds: doc.kinds, phones: doc.phones, rooms };
  const edit = (change: (current: NotifyDraft) => NotifyDraft) => {
    const next = change(shown);
    if (sameDraft(next, saved)) stored.discard();
    else stored.set(next);
  };
  const change = (service: string, next: (row: NotifyRecipient) => Partial<NotifyRecipient>) =>
    edit((current) => {
      const row = current.recipients.find((item) => item.service === service);
      return row ? updateRow(current, service, next(row)) : current;
    });
  const views: RowView[] = shown.recipients.map((recipient) => ({
    recipient,
    saved: doc.config.recipients.find((row) => row.service === recipient.service),
    label: rowLabel(recipient, doc.phones),
    editable: canEditRow(doc, recipient),
  }));
  const editable = views.filter((view) => view.editable);
  const uncovered = shown.recipients.length ? roomsWithoutEmergencies(shown, rooms) : [];
  const readOnly = views.some((view) => !view.editable);
  const checks = applyChecks(shown);
  const fieldError = fieldErrors(shown);
  const changes = draftChanges(doc.config, shown, context);
  const rows = dirty ? reviewRows(changes) : [];
  const summary = dirty ? draftSummary(shown, doc.config, context) : "";
  const count = Number(/^\d+/.exec(summary)?.[0] ?? 0);
  const unlisted = unlistedPhones(shown, doc.phones);
  const listed = new Set(shown.recipients.map((row) => row.service));
  const hours = shown.idle_hours;
  const now = Date.now();
  // The quiet-hours editor: one phone's window at a time.
  const quietView =
    views.find((view) => view.recipient.service === quietFor) ??
    editable.find((view) => view.recipient.quiet_hours) ??
    editable[0] ??
    views[0];
  const shownWindow = quietView?.recipient.quiet_hours ?? FIRST_WINDOW;
  const quiet = quietSpans(shown.recipients.map((row) => row.quiet_hours));
  const lightsOf = (room: Room) => {
    const hour = (key: string) =>
      Number(controller.states[`number.crop_steering_${room.prefix}lights_${key}_hour`]?.state);
    return { on: hour("on"), off: hour("off") };
  };
  const roomLights = rooms
    .map((room) => ({ room, ...lightsOf(room) }))
    .filter((item) => lightSpans(item.on, item.off).length);
  // Every room's lights as one union, the same way as the quiet hours.
  const lights = quietSpans(roomLights.map(({ on, off }) => ({ from: hourClock(on), to: hourClock(off) })));
  const hhmm = (hour: number) => wallText(hourClock(hour));
  const lightsWords = (() => {
    if (!roomLights.length) return "";
    const same = roomLights.every((item) => item.on === roomLights[0].on && item.off === roomLights[0].off);
    if (same)
      return `lights on in ${roomLights.map((item) => item.room.name).join(" and ")}, ${hhmm(roomLights[0].on)}–${hhmm(roomLights[0].off)}`;
    return `lights on: ${roomLights.map((item) => `${item.room.name} ${hhmm(item.on)}–${hhmm(item.off)}`).join(", ")}`;
  })();

  async function sendTest(service: string) {
    setTests((current) => ({ ...current, [service]: { ...current[service], busy: true } }));
    let result: NotifyTestResult;
    try {
      result = parseTestResult(await controller.operator<unknown>("notify_test", { service }));
    } catch (err) {
      result = { sent: false, error: errorText(err) };
    }
    setTests((current) => ({ ...current, [service]: { busy: false, result, at: Date.now() } }));
  }
  /** Test all (an administrator) or Test my phones: one `notify_test {services}` call on 3.18, one
   * call a phone on 3.17. */
  async function testAll() {
    const services = editable.map((view) => view.recipient.service);
    setTestingAll(true);
    setTests((current) =>
      Object.fromEntries([
        ...Object.entries(current),
        ...services.map((service) => [service, { ...current[service], busy: true }]),
      ]),
    );
    const results = await testPhones(services, doc!.quietAndMutes, (data) =>
      controller.operator<unknown>("notify_test", data),
    );
    const at = Date.now();
    setTests((current) => ({
      ...current,
      ...Object.fromEntries(
        services.map((service) => [
          service,
          {
            busy: false,
            result: results[service] ?? { sent: false, error: "No answer for this phone." },
            at,
          },
        ]),
      ),
    }));
    setTestingAll(false);
  }

  /** Apply: `notify_save` with the draft. A save that met one made elsewhere carries the draft onto
   * it and says so; a refusal is the integration's words. */
  async function apply() {
    const sent = shown;
    const before = doc!.config;
    let fresh: NotifyDocument;
    try {
      fresh = await saveNotify(controller, savePayload(doc!, sent));
    } catch (err) {
      const refusal = saveRefusal(err);
      // Not a refusal (a closed socket, a timeout): it may have landed, so it is not confirmed.
      if (!refusal) throw err;
      if (refusal.code === "stale_revision") loaded(await readNotify(controller));
      return refusal;
    }
    const receipt: ApplyReceipt = saveReceipt(rows, sent, fresh.config, Date.now());
    lastSave.current = { before, revision: fresh.config.revision };
    stored.discard();
    setDoc(fresh);
    return receipt;
  }
  /** Undo a save: the setup it replaced, written back only while nobody has saved since. */
  async function undoSave() {
    const last = lastSave.current;
    if (!last) throw new UndoError("Nothing to undo.", 0, 1);
    const current = await readNotify(controller);
    if (current.config.revision !== last.revision)
      throw new UndoError("The notifications changed since. Nothing was undone.", 0, 1);
    const back = await saveNotify(controller, savePayload(current, toDraft(last.before)));
    setDoc(back);
    if (!sameDraft(toDraft(back.config), toDraft(last.before)))
      throw new UndoError(
        "The integration did not confirm the previous setup. Reload and check before trying again.",
        0,
        1,
      );
    lastSave.current = null;
  }

  /** Mute or unmute a room at once (`until` null: unmute), with Undo. A mute shows as done only
   * once the setup read back holds it. */
  async function setMute(room: Room, until: number | null) {
    const prefix = room.prefix;
    const was = doc!.config.mutes[prefix] ?? null;
    const write = async (base: NotifyDocument, end: number | null) => {
      const mutes = { ...base.config.mutes };
      if (end === null) delete mutes[prefix];
      else mutes[prefix] = end;
      const back = await saveNotify(controller, mutePayload(base, mutes));
      setDoc(back);
      return sameMuteEnd(back.config.mutes[prefix], end);
    };
    setMuting(prefix);
    try {
      if (!(await write(doc!, until)))
        return void toast.error(
          "The integration did not confirm the mute. Reload and check before trying again.",
        );
      const words =
        until === null
          ? `${room.name} unmuted: it sends every alert.`
          : `${room.name} muted until ${muteEndWords(until, Date.now(), tz)}.`;
      offerUndo({
        message: `${words} Written and read back ${clock(Date.now(), tz)}.`,
        undo: async () => {
          const current = await readNotify(controller);
          if (!sameMuteEnd(current.config.mutes[prefix], until))
            throw new UndoError(`${room.name}'s mute changed since. Nothing was undone.`, 0, 1);
          const back = muteUndoTarget(was, Date.now());
          if (!(await write(current, back)))
            throw new UndoError(
              "The integration did not confirm the previous mute. Reload and check before trying again.",
              0,
              1,
            );
          toast(
            `${back === null ? `${room.name} sends every alert again${was === null ? "" : ": its earlier mute had already ended"}` : `${room.name} muted until ${muteEndWords(back, Date.now(), tz)} again`}. Written and read back ${clock(Date.now(), tz)}.`,
          );
        },
      });
    } catch (err) {
      const message = errorText(err);
      toast.error(message === "revision" ? notifyError("revision") : notifyError(message));
      if (message === "revision") setReads((n) => n + 1);
    } finally {
      setMuting(null);
    }
  }

  /** The shown phone's quiet hours, and only that phone's; a time not complete yet is not taken. */
  function setQuiet(next: QuietHours | null) {
    if (!quietView || (next && !(isClock(next.from) && isClock(next.to)))) return;
    change(quietView.recipient.service, () => ({ quiet_hours: next }));
  }

  const removeButton = (view: RowView) =>
    admin && (
      <span className="label-with-tip">
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          className="notify-remove"
          aria-label={`Remove ${view.label.name}`}
          disabled={!connected}
          onClick={() =>
            edit((current) => ({
              ...current,
              recipients: current.recipients.filter(
                (row) => row.service !== view.recipient.service,
              ),
            }))
          }
        >
          <Trash2 size={15} />
        </Button>
        <UiTip copyKey="remove {x}" values={[view.label.name]} />
      </span>
    );
  const kindBox = (view: RowView, kind: NotifyKind) => (
    <input
      type="checkbox"
      data-kind={kind.id}
      checked={view.recipient.kinds.includes(kind.id)}
      disabled={!view.editable || !connected}
      aria-label={`${view.label.name}: ${kind.name}`}
      onChange={(event) => {
        const on = event.target.checked;
        change(view.recipient.service, (row) => ({ kinds: toggleKind(row.kinds, kind.id, on) }));
      }}
    />
  );
  const kindChanged = (view: RowView, kind: NotifyKind) =>
    (view.saved && view.saved.kinds.includes(kind.id) !== view.recipient.kinds.includes(kind.id)) ||
    undefined;
  const loudSwitch = (view: RowView) => (
    <input
      type="checkbox"
      role="switch"
      data-urgent
      className="notify-switch"
      checked={view.recipient.urgent_high_priority}
      disabled={!view.editable || !connected}
      aria-label={`${view.label.name}: Emergencies loud`}
      onChange={(event) => {
        const on = event.target.checked;
        change(view.recipient.service, () => ({ urgent_high_priority: on }));
      }}
    />
  );
  const loudChanged = (view: RowView) =>
    (view.saved && view.saved.urgent_high_priority !== view.recipient.urgent_high_priority) ||
    undefined;
  const roomChips = (view: RowView) => (
    <RoomChips
      rooms={rooms}
      value={view.recipient.rooms}
      name={view.label.name}
      disabled={!view.editable || !connected}
      onChange={(next) => change(view.recipient.service, () => ({ rooms: next }))}
    />
  );
  const testCell = (view: RowView) => {
    const test = tests[view.recipient.service];
    return (
      <div className="notify-test">
        <span className="label-with-tip">
          <Button
            type="button"
            variant="outline"
            size="xs"
            disabled={!view.editable || !connected || test?.busy}
            aria-label={`Send test to ${view.label.name}`}
            onClick={() => void sendTest(view.recipient.service)}
          >
            {test?.busy ? <LoaderCircle className="spin" /> : <Send />}
            Send test
          </Button>
          <UiTip copyKey="send a test to {x}" values={[view.label.name]} />
        </span>
        <span
          className="notify-test-result"
          role="status"
          data-test-result={
            test?.busy || !test?.result ? undefined : test.result.sent ? "sent" : "failed"
          }
        >
          {test?.busy
            ? ""
            : test?.result && test.at !== undefined
              ? testLine(test.result, test.at, tz)
              : "Never tested"}
        </span>
      </div>
    );
  };
  /** Under a phone's name: its device and its service, each once. */
  const phoneFacts = (view: RowView) =>
    [view.label.subtitle, view.recipient.service]
      .filter((part, index, all): part is string => !!part && all.indexOf(part) === index)
      .join(" · ");
  const addButton = admin && (
    <Button onClick={() => setAdding((n) => n + 1)} disabled={!connected}>
      <Plus size={16} /> Add a phone
    </Button>
  );

  return (
    <div className="notify-page">
      <Heading title="Notifications" action={shown.recipients.length > 0 && addButton} />
      <NotificationPredictions controller={controller} />
      <CanonicalControls
        controller={controller}
        owner="notifications"
        onDirtyChange={setPolicyDirty}
      />
      {loadError && (
        <p className="workspace-message error" role="alert">
          {loadError}
        </p>
      )}
      {uncovered.length > 0 && (
        <div className="attention-list" role="status">
          {uncovered.map((room) => (
            <div className="attention" key={room.id} data-uncovered={room.prefix}>
              <AlertTriangle size={18} aria-hidden="true" />
              <div>
                <strong>Nobody gets emergencies for {room.name}</strong>
                <p>
                  Tick Emergencies for at least one phone that covers {room.name}. Until then its
                  emergencies go to every phone that gets emergencies, or to the controller app's
                  notify_service option when none does.
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
      {!shown.recipients.length ? (
        <section className="panel">
          <Empty
            title="No phones"
            detail="Until a phone is added here, every push goes to the controller app's notify_service option, the way it always has. Add a phone to choose who gets which alerts, room by room."
            action={
              addButton || (
                <p className="muted small">A Home Assistant administrator adds phones here.</p>
              )
            }
          />
        </section>
      ) : (
        <section className="panel notify-panel" aria-labelledby={`${id}-title`}>
          <div className="panel-heading">
            <div>
              <h2 id={`${id}-title`}>Who gets which alerts</h2>
              <p>
                A push goes only to the phones whose row ticks that kind. Open a column name to see
                what it covers.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={!connected || testingAll || !editable.length}
              onClick={() => void testAll()}
            >
              {testingAll ? <LoaderCircle className="spin" /> : <Send />}
              {admin ? "Test all" : "Test my phones"}
            </Button>
          </div>
          {readOnly && (
            <p className="notify-readonly" data-readonly-note>
              Only an administrator can change other people's phones.
              {editable.length ? "" : " Ask one to add yours."}
            </p>
          )}
          <div className="table-scroll notify-scroll">
            <table className="notify-table">
              <caption className="sr-only">A row per phone, a column per kind of alert</caption>
              <thead>
                <tr>
                  <th scope="col" className="notify-phone-head">
                    Phone
                  </th>
                  {doc.kinds.map((kind) => (
                    <th scope="col" key={kind.id} data-kind={kind.id}>
                      <KindHeading kind={kind} />
                    </th>
                  ))}
                  <th scope="col">Rooms</th>
                  <th scope="col" className="notify-urgent-head">
                    Emergencies loud
                  </th>
                </tr>
              </thead>
              <tbody>
                {views.map((view) => (
                  <tr
                    key={view.recipient.service}
                    data-notify-row={view.recipient.service}
                    data-readonly={!view.editable || undefined}
                    data-new={!view.saved || undefined}
                  >
                    <th scope="row" className="notify-phone">
                      <div>
                        <span>
                          <span className="notify-phone-name">{view.label.title}</span>
                          <span className="cell-subtext">{phoneFacts(view)}</span>
                        </span>
                        {removeButton(view)}
                      </div>
                      {testCell(view)}
                    </th>
                    {doc.kinds.map((kind) => (
                      <td
                        key={kind.id}
                        className="notify-check"
                        data-changed={kindChanged(view, kind)}
                      >
                        {kindBox(view, kind)}
                      </td>
                    ))}
                    <td>{roomChips(view)}</td>
                    <td className="notify-check" data-changed={loudChanged(view)}>
                      {loudSwitch(view)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details className="notify-legend">
            <summary>Kinds of alert</summary>
            <dl>
              {doc.kinds.map((kind) => (
                <div key={kind.id}>
                  <dt>{kind.name}</dt>
                  <dd>
                    <KindCoverage kind={kind} />
                  </dd>
                </div>
              ))}
            </dl>
          </details>
          <div className="notify-cards">
            {views.map((view) => (
              <article
                className="notify-card"
                key={view.recipient.service}
                data-notify-card={view.recipient.service}
                data-readonly={!view.editable || undefined}
                data-new={!view.saved || undefined}
              >
                <div className="notify-card-head">
                  <div>
                    <h3>{view.label.title}</h3>
                    <p>{phoneFacts(view)}</p>
                  </div>
                  {testCell(view)}
                  {removeButton(view)}
                </div>
                {/* Chips, not a list of ticks: a phone's whole row fits a screen. */}
                <ul className="notify-card-kinds" aria-label={`Alerts for ${view.label.name}`}>
                  {doc.kinds.map((kind) => (
                    <li key={kind.id}>
                      <label className="notify-chip" data-changed={kindChanged(view, kind)}>
                        {kindBox(view, kind)}
                        <span>{kind.name}</span>
                      </label>
                    </li>
                  ))}
                  <li>
                    <label className="notify-chip" data-changed={loudChanged(view)}>
                      {loudSwitch(view)}
                      <span>Emergencies loud</span>
                    </label>
                  </li>
                </ul>
                <div className="notify-card-rooms">
                  <span aria-hidden="true">Rooms</span>
                  {roomChips(view)}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
      <div className="notify-lower">
        <section className="panel notify-quiet" aria-labelledby={`${id}-quiet`}>
          <h2 id={`${id}-quiet`}>Quiet hours</h2>
          {!doc.quietAndMutes ? (
            <NeedsIntegration feature="Quiet hours" />
          ) : (
            <>
              <QuietPhones
                phones={views.map((view) => ({
                  service: view.recipient.service,
                  title: view.label.title,
                  window: view.recipient.quiet_hours ? quietWords(view.recipient.quiet_hours) : null,
                }))}
                value={quietView?.recipient.service ?? null}
                onChange={setQuietFor}
              />
              {quietView && (
                <div className="notify-quiet-window">
                  <label>
                    <input
                      type="checkbox"
                      role="switch"
                      className="notify-switch"
                      checked={!!quietView.recipient.quiet_hours}
                      disabled={!quietView.editable || !connected}
                      aria-label={`Quiet hours on ${quietView.label.name}`}
                      onChange={(event) => setQuiet(event.target.checked ? shownWindow : null)}
                    />
                    <span aria-hidden="true">On</span>
                  </label>
                  <label>
                    From
                    <Input
                      type="time"
                      value={shownWindow.from}
                      disabled={!quietView.editable || !connected}
                      onChange={(event) => setQuiet({ ...shownWindow, from: event.target.value })}
                    />
                  </label>
                  <label>
                    to
                    <Input
                      type="time"
                      value={shownWindow.to}
                      disabled={!quietView.editable || !connected}
                      onChange={(event) => setQuiet({ ...shownWindow, to: event.target.value })}
                    />
                  </label>
                </div>
              )}
              {fieldError.quiet && (
                <p className="field-error" role="alert">
                  {fieldError.quiet}
                </p>
              )}
              <DayStrip quiet={quiet} lights={lights} />
              <p className="notify-strip-legend" data-quiet-legend>
                <span className="notify-key-quiet" aria-hidden="true" />
                {quiet.length ? `quiet ${hoursText(spanMinutes(quiet))}` : "no quiet hours"}
                {lightsWords && (
                  <span>
                    <span className="notify-key-lights" aria-hidden="true" /> {lightsWords}
                  </span>
                )}
              </p>
              <p className="muted small">{QUIET_NOTE}</p>
            </>
          )}
        </section>
        <section className="panel notify-idle" aria-labelledby={`${id}-idle`}>
          <div className="label-with-tip">
            <h2 id={`${id}-idle`}>Watering stopped and room mutes</h2>
            <UiTip copyKey="tell me when a room has watered nothing for" />
          </div>
          <label className="notify-idle-sentence">
            Count watering as stopped after{" "}
            <Input
              type="number"
              inputMode="numeric"
              className="notify-hours"
              min={IDLE_HOURS.min}
              max={IDLE_HOURS.max}
              step={1}
              value={Number.isFinite(hours) ? String(hours) : ""}
              disabled={!admin || !connected}
              aria-invalid={!!fieldError.idle}
              onChange={(event) => {
                const value = event.target.value.trim();
                edit((current) => ({
                  ...current,
                  idle_hours: value === "" ? Number.NaN : Number(value),
                }));
              }}
            />{" "}
            h with no shot, lights on
          </label>
          {fieldError.idle && (
            <p className="field-error" role="alert">
              {fieldError.idle}
            </p>
          )}
          <p className="muted small">{IDLE_NOTE}</p>
          {admin ? null : (
            <p className="muted small">Only an administrator can change it or mute a room.</p>
          )}
          {!doc.quietAndMutes ? (
            <NeedsIntegration feature="Room mutes" compact />
          ) : (
            <ul className="notify-mutes">
              {rooms.map((room) => {
                const until = doc.config.mutes[room.prefix];
                const muted = until !== undefined && until > now;
                return (
                  <li key={room.id} data-mute-room={room.prefix} data-muted={muted || undefined}>
                    <span className="notify-mute-dot" aria-hidden="true" />
                    <span>
                      {muted
                        ? `${room.name} muted until ${muteEndWords(until, now, tz)}. Only emergencies get through.`
                        : `${room.name} sends every alert.`}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!admin || !connected || muting !== null}
                      onClick={() => void setMute(room, muted ? null : Date.now() + MUTE_MS)}
                    >
                      {muting === room.prefix && <LoaderCircle className="spin" />}
                      {muted ? `Unmute ${room.name}` : `Mute ${room.name} for 2 h`}
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
      <div className="notify-bar">
        <ReviewApply
          layout="bar"
          rows={rows}
          summary={summary ? <SummaryText text={summary} /> : undefined}
          discardLabel="Discard"
          applyLabel={`Apply ${count} ${count === 1 ? "change" : "changes"}`}
          checks={dirty ? checks : []}
          apply={apply}
          onDiscard={stored.discard}
          onReload={() => setReads((n) => n + 1)}
          timeZone={tz}
          confirmedBy={controller.demo ? "Demo only. The integration" : "The integration"}
          undo={undoSave}
        />
      </div>
      <Dialog open={adding > 0} onOpenChange={(open) => !open && setAdding(0)}>
        <DialogContent
          className="review-dialog"
          onCloseAutoFocus={(event) => {
            // Added: carry on from the new row's first tick.
            const service = added.current;
            added.current = null;
            const box = [
              ...document.querySelectorAll<HTMLInputElement>(
                `[data-notify-row="${service}"] input, [data-notify-card="${service}"] input`,
              ),
            ].find((input) => input.offsetParent !== null && !input.disabled);
            if (!service || !box) return;
            event.preventDefault();
            box.focus();
          }}
        >
          <DialogHeader>
            <DialogTitle>Add a phone</DialogTitle>
            <DialogDescription>
              It starts with Emergencies ticked for every room. Tick what else it should get, then
              apply.
            </DialogDescription>
          </DialogHeader>
          <AddPhone
            key={adding}
            phones={unlisted}
            listed={listed}
            onClose={() => setAdding(0)}
            onAdd={(service) => {
              added.current = service;
              edit((current) => ({
                ...current,
                recipients: [...current.recipients, newRecipient(service, doc.phones)],
              }));
              setAdding(0);
            }}
          />
        </DialogContent>
      </Dialog>
    </div>
  );

}

/** The quiet-hours editor's phone picker: one phone shown at a time, so a radio group. */
export function QuietPhones({
  phones,
  value,
  onChange,
}: {
  phones: { service: string; title: string; window: string | null }[];
  value: string | null;
  onChange: (service: string) => void;
}) {
  const move = (from: number, step: number) => {
    const next = phones[(from + step + phones.length) % phones.length];
    onChange(next.service);
    document.querySelector<HTMLElement>(`[data-quiet-phone="${next.service}"]`)?.focus();
  };
  return (
    <div className="notify-quiet-phones" role="radiogroup" aria-label="Quiet hours for">
      <span aria-hidden="true">for</span>
      {phones.map((phone, index) => (
        <button
          type="button"
          key={phone.service}
          role="radio"
          aria-checked={phone.service === value}
          tabIndex={phone.service === value ? 0 : -1}
          data-quiet-phone={phone.service}
          onClick={() => onChange(phone.service)}
          onKeyDown={(event) => {
            const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
            if (!step) return;
            event.preventDefault();
            move(index, step);
          }}
        >
          {phone.title} <small>{phone.window ?? "no quiet hours"}</small>
        </button>
      ))}
    </div>
  );
}

/** "2 changes not applied yet: Sam's phone gets Dosing", its count part in bold. */
function SummaryText({ text }: { text: string }) {
  const at = text.indexOf(": ");
  return (
    <span className="notify-summary" data-draft-summary>
      <b>{text.slice(0, at + 1)}</b> {text.slice(at + 2)}
    </span>
  );
}
