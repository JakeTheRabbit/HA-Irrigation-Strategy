import { useEffect, useId, useLayoutEffect, useReducer, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  LoaderCircle,
  Plus,
  Send,
  Trash2,
} from "lucide-react";
import { Popover } from "radix-ui";
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
import {
  IDLE_HOURS,
  canEditRow,
  draftChanges,
  draftErrors,
  hasNotifyConfig,
  kindCoverage,
  liveRevision,
  newRecipient,
  notifyError,
  notifyReducer,
  parseNotifyDocument,
  parseTestResult,
  phoneLabel,
  roomsWithoutEmergencies,
  rowLabel,
  savePayload,
  serviceFromText,
  toDraft,
  toggleKind,
  toggleRoom,
  unlistedPhones,
  updateRow,
  type DraftChanges,
  type NotifyDocument,
  type NotifyDraft,
  type NotifyKind,
  type NotifyPhone,
  type NotifyRecipient,
} from "@/lib/notify";
import type { Controller, Room } from "@/lib/types";
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
  sent?: boolean;
  text?: string;
}

const hoursWords = (hours: number) => `${hours} ${hours === 1 ? "hour" : "hours"}`;
/** "Unsaved changes to 2 phones and the threshold". */
const unsavedWords = ({ phones, idle }: DraftChanges) => {
  const parts = [
    phones.length ? `${phones.length} ${phones.length === 1 ? "phone" : "phones"}` : "",
    idle ? "the threshold" : "",
  ].filter(Boolean);
  return parts.length ? `Unsaved changes to ${parts.join(" and ")}` : "Unsaved changes";
};

/** `notify_get`. An answer with an error and no setup is that error, never an empty setup. */
async function readNotify(controller: Controller): Promise<NotifyDocument> {
  const raw = await controller.operator<unknown>("notify_get");
  const doc = parseNotifyDocument(raw);
  if (doc.error && !hasNotifyConfig(raw)) throw new Error(doc.error);
  return doc;
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

/** The rooms a row covers: All, or chips for each room of the site (and a room it names that the
 * site no longer has). */
function RoomChips({
  rooms,
  value,
  name,
  disabled,
  onPress,
}: {
  rooms: readonly Room[];
  value: readonly string[];
  name: string;
  disabled: boolean;
  onPress: (prefix: string | null) => void;
}) {
  const gone = value.filter((prefix) => !rooms.some((room) => room.prefix === prefix));
  return (
    <div className="notify-rooms" role="group" aria-label={`${name}: rooms`}>
      <button
        type="button"
        aria-pressed={!value.length}
        disabled={disabled}
        onClick={() => onPress(null)}
      >
        All
      </button>
      {rooms.map((room) => (
        <button
          type="button"
          key={room.id}
          aria-pressed={value.includes(room.prefix)}
          disabled={disabled}
          onClick={() => onPress(room.prefix)}
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
          title="Not a room of this site now"
          onClick={() => onPress(prefix)}
        >
          {prefix || "Default room"} (gone)
        </button>
      ))}
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
          <Label htmlFor={`${id}-service`}>Notify service</Label>
          <Input
            id={`${id}-service`}
            value={typed}
            placeholder="notify.mobile_app_pixel_7"
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
        <Button type="submit" disabled={!ready}>
          Add
        </Button>
      </DialogFooter>
    </form>
  );
}

/** Settings & help › Notifications: which phones get a push for which kinds of alert, for the whole
 * site (docs/NOTIFICATIONS.md). Edits are a draft until reviewed and saved with `notify_save`
 * against the revision they were read at; the page itself never sends a push but a test one. */
export function Notifications({
  controller,
  onDirtyChange,
}: {
  controller: Controller;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const id = useId();
  const [{ doc, draft }, dispatch] = useReducer(notifyReducer, { doc: null, draft: null });
  const [loadError, setLoadError] = useState("");
  const [reads, setReads] = useState(0);
  const [notice, setNotice] = useState("");
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [adding, setAdding] = useState(0);
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState("");
  const added = useRef<string | null>(null);
  const saved = useRef(false);
  const noticeRef = useRef<HTMLParagraphElement>(null);
  const connected = ["live", "demo"].includes(controller.connection);

  useEffect(() => {
    if (controller.connection === "connecting") return;
    let current = true;
    readNotify(controller)
      .then((next) => {
        if (!current) return;
        dispatch({ type: "loaded", doc: next });
        setLoadError(next.error ?? "");
      })
      .catch((err) => current && setLoadError(errorText(err)));
    return () => {
      current = false;
    };
  }, [controller.connection, reads]);
  // Saved elsewhere (the integration's sensor moved on): read it again, the draft kept on top.
  const live = liveRevision(controller.states);
  const revision = doc?.config.revision;
  useEffect(() => {
    if (revision !== undefined && live !== null && live !== revision) setReads((n) => n + 1);
  }, [live, revision]);
  const dirty = !!draft;
  useLayoutEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);

  if (!doc)
    return (
      <>
        <Heading title="Notifications" />
        {loadError ? (
          <Empty
            title="Notifications are not available"
            detail={`${loadError} Choosing who gets which alerts needs the updated Crop Steering integration.`}
          />
        ) : (
          <p className="muted">Loading notifications…</p>
        )}
      </>
    );

  const shown = draft ?? toDraft(doc.config);
  const rooms = controller.rooms;
  const admin = doc.can_edit_all;
  const edit = (change: (current: NotifyDraft) => NotifyDraft) => {
    setNotice("");
    dispatch({ type: "edit", edit: change });
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
  const uncovered = shown.recipients.length ? roomsWithoutEmergencies(shown, rooms) : [];
  const readOnly = views.some((view) => !view.editable);
  const own = views.some((view) => view.editable);
  const errors = draftErrors(shown);
  const changes = draftChanges(doc.config, shown, { kinds: doc.kinds, phones: doc.phones, rooms });
  const unlisted = unlistedPhones(shown, doc.phones);
  const listed = new Set(shown.recipients.map((row) => row.service));
  const hours = shown.idle_hours;

  async function sendTest(service: string) {
    setTests((current) => ({ ...current, [service]: { busy: true } }));
    let next: TestState;
    try {
      const result = parseTestResult(
        await controller.operator<unknown>("notify_test", { service }),
      );
      next = result.sent
        ? { busy: false, sent: true, text: "Sent. Check the phone." }
        : {
            busy: false,
            sent: false,
            text: `Not sent: ${notifyError(result.error ?? "no reason given.")}`,
          };
    } catch (err) {
      next = { busy: false, sent: false, text: `Not sent: ${errorText(err)}` };
    }
    setTests((current) => ({ ...current, [service]: next }));
  }
  async function save() {
    if (!draft) return;
    setBusy(true);
    setSaveError("");
    try {
      const raw = await controller.operator<unknown>("notify_save", savePayload(doc!, draft));
      const result = parseNotifyDocument(raw);
      if (result.error === "revision") {
        // Read what was saved meanwhile; the reducer keeps this draft's changes on top of it.
        dispatch({ type: "loaded", doc: await readNotify(controller) });
        setSaveError(notifyError("revision"));
      } else if (result.error) setSaveError(notifyError(result.error));
      else {
        const fresh = hasNotifyConfig(raw) ? result : await readNotify(controller);
        dispatch({ type: "saved", doc: fresh });
        setNotice(`Saved as revision ${fresh.config.revision}. The next push follows it.`);
        saved.current = true;
        setReview(false);
      }
    } catch (err) {
      setSaveError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const removeButton = (view: RowView) =>
    admin && (
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
            recipients: current.recipients.filter((row) => row.service !== view.recipient.service),
          }))
        }
      >
        <Trash2 size={15} />
      </Button>
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
  const urgentBox = (view: RowView) => (
    <input
      type="checkbox"
      data-urgent
      checked={view.recipient.urgent_high_priority}
      disabled={!view.editable || !connected}
      aria-label={`${view.label.name}: High priority for emergencies`}
      onChange={(event) => {
        const on = event.target.checked;
        change(view.recipient.service, () => ({ urgent_high_priority: on }));
      }}
    />
  );
  const urgentChanged = (view: RowView) =>
    (view.saved && view.saved.urgent_high_priority !== view.recipient.urgent_high_priority) ||
    undefined;
  const roomChips = (view: RowView) => (
    <RoomChips
      rooms={rooms}
      value={view.recipient.rooms}
      name={view.label.name}
      disabled={!view.editable || !connected}
      onPress={(prefix) =>
        change(view.recipient.service, (row) => ({ rooms: toggleRoom(row.rooms, prefix) }))
      }
    />
  );
  const testCell = (view: RowView) => {
    const test = tests[view.recipient.service];
    return (
      <div className="notify-test">
        <Button
          type="button"
          variant="outline"
          size="xs"
          disabled={!view.editable || !connected || test?.busy}
          aria-label={`Send a test to ${view.label.name}`}
          onClick={() => void sendTest(view.recipient.service)}
        >
          {test?.busy ? <LoaderCircle className="spin" /> : <Send />}
          Send a test
        </Button>
        <span
          className="notify-test-result"
          role="status"
          data-test-result={test?.busy ? undefined : test?.sent ? "sent" : test && "failed"}
        >
          {test?.busy ? "" : test?.text}
        </span>
      </div>
    );
  };
  const addButton = admin && (
    <Button onClick={() => setAdding((count) => count + 1)} disabled={!connected}>
      <Plus size={16} /> Add a phone
    </Button>
  );

  return (
    <div className="notify-page">
      <Heading title="Notifications" action={shown.recipients.length > 0 && addButton} />
      {notice && (
        <p className="success-text notify-notice" role="status" tabIndex={-1} ref={noticeRef}>
          <Check size={16} />
          {notice}
        </p>
      )}
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
            title="No phones yet"
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
                Every alert is still a Home Assistant notification. A phone also gets a push for the
                kinds of alert its row ticks: one push, however many of its ticks an alert falls
                under. Open a heading to see what it covers.
              </p>
            </div>
          </div>
          {readOnly && (
            <p className="notify-readonly" data-readonly-note>
              Only an administrator can change other people's phones.
              {own ? "" : " Ask one to add yours."}
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
                    High priority for emergencies
                  </th>
                  <th scope="col">
                    <span className="sr-only">Test push</span>
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
                          {view.label.subtitle && (
                            <span className="cell-subtext">{view.label.subtitle}</span>
                          )}
                        </span>
                        {removeButton(view)}
                      </div>
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
                    <td className="notify-check" data-changed={urgentChanged(view)}>
                      {urgentBox(view)}
                    </td>
                    <td>{testCell(view)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details className="notify-legend">
            <summary>What each kind of alert covers</summary>
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
                    {view.label.subtitle && <p>{view.label.subtitle}</p>}
                  </div>
                  {removeButton(view)}
                </div>
                <ul className="notify-card-kinds" aria-label={`What ${view.label.name} gets`}>
                  {doc.kinds.map((kind) => (
                    <li key={kind.id} data-changed={kindChanged(view, kind)}>
                      <label>
                        {kindBox(view, kind)}
                        <span>{kind.name}</span>
                      </label>
                    </li>
                  ))}
                </ul>
                <div className="notify-card-rooms">
                  <span aria-hidden="true">Rooms</span>
                  {roomChips(view)}
                </div>
                <label className="notify-card-urgent" data-changed={urgentChanged(view)}>
                  {urgentBox(view)}
                  <span>High priority for emergencies</span>
                </label>
                {testCell(view)}
              </article>
            ))}
          </div>
        </section>
      )}
      <section className="panel notify-idle" aria-labelledby={`${id}-idle`}>
        <h2 id={`${id}-idle`}>Watering stopped</h2>
        <label className="notify-idle-sentence">
          Tell me when a room has watered nothing for{" "}
          <Input
            type="number"
            inputMode="numeric"
            className="notify-hours"
            min={IDLE_HOURS.min}
            max={IDLE_HOURS.max}
            step={1}
            value={Number.isFinite(hours) ? String(hours) : ""}
            disabled={!admin || !connected}
            aria-invalid={!!errors.length}
            onChange={(event) => {
              const value = event.target.value.trim();
              edit((current) => ({
                ...current,
                idle_hours: value === "" ? Number.NaN : Number(value),
              }));
            }}
          />{" "}
          hours with the lights on
        </label>
        {!!errors.length && (
          <p className="field-error" role="alert">
            {errors[0]}
          </p>
        )}
        <p className="muted small">
          Sent as CS-209 to the phones that tick Watering stopped, again every{" "}
          {errors.length ? "so many hours" : hoursWords(hours)} while it lasts, and over at the next
          shot. A room counts only while a zone is in P1 or P2: the morning dryback (P0) and the
          night (P3) do not start the clock.
          {admin ? "" : " Only an administrator can change it."}
        </p>
      </section>
      {draft && (
        <div className="draft-bar" role="status">
          <div>
            <strong>{unsavedWords(changes)}</strong>
            <span>{errors[0] ?? "A draft in this tab until you save it."}</span>
          </div>
          <Button variant="ghost" onClick={() => dispatch({ type: "discard" })}>
            Discard draft
          </Button>
          <Button
            disabled={!!errors.length || !connected}
            onClick={() => {
              setSaveError("");
              setReview(true);
            }}
          >
            Review and save <ArrowRight size={16} />
          </Button>
        </div>
      )}
      <Dialog open={review} onOpenChange={(open) => !busy && setReview(open)}>
        <DialogContent
          className="review-dialog"
          onCloseAutoFocus={(event) => {
            // Saved: the draft bar that opened it is gone. Go on from the line that says so.
            if (!saved.current || !noticeRef.current) return;
            saved.current = false;
            event.preventDefault();
            noticeRef.current.focus({ preventScroll: true });
          }}
        >
          <DialogHeader>
            <DialogTitle>Save notifications?</DialogTitle>
            <DialogDescription>
              {controller.demo ? "Demo only. " : ""}Who gets a phone push for which alerts, across
              the whole site. Nothing is sent now: the next alert follows the new setup.
            </DialogDescription>
          </DialogHeader>
          {changes.count ? (
            <div className="review-list">
              {changes.phones.map((item) => (
                <div className="review-row" key={item.service} data-review-phone={item.service}>
                  <strong>
                    {item.title}
                    {item.change === "changed" ? "" : ` · ${item.change}`}
                  </strong>
                  {item.lines.map((line) => (
                    <span key={line.label}>
                      {line.label}:{" "}
                      {line.before !== null && (
                        <>
                          {line.before} <span aria-hidden="true">→</span>{" "}
                        </>
                      )}
                      <b>{line.after}</b>
                    </span>
                  ))}
                </div>
              ))}
              {changes.idle && (
                <div className="review-row" data-review-idle>
                  <strong>Watering stopped</strong>
                  <span>
                    After {hoursWords(changes.idle.before)} <span aria-hidden="true">→</span>{" "}
                    <b>{hoursWords(changes.idle.after)}</b>
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="muted small">
              Nothing is left to save: the setup already reads this way.
            </p>
          )}
          {!shown.recipients.length && (
            <p className="notice-inline">
              With no phones listed, every push goes back to the controller app's notify_service
              option.
            </p>
          )}
          {uncovered.length > 0 && (
            <p className="notice-inline">
              No phone covers emergencies for {uncovered.map((room) => room.name).join(" or ")}: they
              will go to every phone that gets emergencies, or to the controller app's notify_service
              option when none does.
            </p>
          )}
          {saveError && (
            <p className="form-error" role="alert">
              {saveError}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setReview(false)}>
              Back to editing
            </Button>
            <Button disabled={busy || !changes.count || !connected} onClick={() => void save()}>
              {busy && <LoaderCircle className="spin" size={16} />}
              {busy ? "Saving…" : "Save notifications"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
              save.
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
