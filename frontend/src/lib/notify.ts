import { asCode, errorCodes } from "./error-codes";
import type { Room, States } from "./types";

/** Who gets a phone push for which alerts (docs/NOTIFICATIONS.md): the site's notification setup as
 * `notify_get` returns it, and what Settings & help › Notifications works out from it. Nothing here
 * sends anything: a test push is `notify_test`, a save is `notify_save`, and the integration decides
 * who each push goes to. */

/** The integration's sensor: its state is the setup's revision. */
export const NOTIFY_CONFIG_ID = "sensor.crop_steering_notify_config";
export const EMERGENCY = "emergency";
export const IDLE_HOURS = { min: 1, max: 12, fallback: 3 } as const;

export interface NotifyRecipient {
  /** Any notify service: notify.mobile_app_pixel_7, a group, Supernotify. */
  service: string;
  /** Shown on the page; the device name to start with. */
  name: string;
  /** The Home Assistant user the phone belongs to, when known. */
  user_id: string | null;
  /** The ids of the kinds of alert it ticks. */
  kinds: string[];
  /** Room prefixes ("" is the default room); empty is every room. */
  rooms: string[];
  /** Emergencies go out as high-priority, time-sensitive pushes. */
  urgent_high_priority: boolean;
}
export interface NotifyConfig {
  revision: number;
  idle_hours: number;
  recipients: NotifyRecipient[];
}
/** A checkbox column: the codes and events a kind of alert covers. */
export interface NotifyKind {
  id: string;
  name: string;
  detail: string;
  codes: string[];
  events: string[];
}
/** One of the site's phones: a mobile app's notify service, its device and whose it is. */
export interface NotifyPhone {
  service: string;
  name: string;
  user_id: string | null;
  user_name: string | null;
}
/** What `notify_get` and `notify_save` answer. */
export interface NotifyDocument {
  schema_version: number;
  config: NotifyConfig;
  kinds: NotifyKind[];
  phones: NotifyPhone[];
  /** An administrator: every row, adding and removing rows, and the threshold. */
  can_edit_all: boolean;
  /** The signed-in user; anyone else changes only the rows that are theirs. */
  user_id: string | null;
  error: string | null;
}
/** What `notify_test` answers. */
export interface NotifyTestResult {
  sent: boolean;
  error: string | null;
}

// Reading what the integration returns: anything missing or garbled falls back, never throws.
type Raw = Record<string, unknown>;
const record = (value: unknown): Raw =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Raw) : {};
const text = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value.trim() : null;
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const unique = <T>(values: T[]): T[] => [...new Set(values)];
/** A number, or one written out ("3"); NaN for anything else. */
const numeric = (value: unknown): number =>
  typeof value === "number" ? value : text(value) ? Number(value) : Number.NaN;
const whole = (value: unknown): number | null => {
  const parsed = numeric(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
};
const SERVICE = /^notify\.[^\s.]+$/;
const PREFIX = /^(?:[a-z0-9_]+_)?$/;
export const isService = (value: unknown): value is string =>
  typeof value === "string" && SERVICE.test(value);

function parseRecipient(value: unknown): NotifyRecipient | null {
  const raw = record(value);
  const service = text(raw.service);
  if (!service || !SERVICE.test(service)) return null;
  return {
    service,
    name: text(raw.name) ?? service,
    user_id: text(raw.user_id),
    kinds: unique(list(raw.kinds).flatMap((kind) => text(kind) ?? [])),
    rooms: unique(
      list(raw.rooms).flatMap((room) =>
        typeof room === "string" && PREFIX.test(room.trim()) ? [room.trim()] : [],
      ),
    ),
    urgent_high_priority: raw.urgent_high_priority === true,
  };
}
/** The saved setup; every phone listed once. */
export function parseNotifyConfig(value: unknown): NotifyConfig {
  const raw = record(value);
  const seen = new Set<string>();
  const hours = numeric(raw.idle_hours);
  return {
    revision: whole(raw.revision) ?? 0,
    idle_hours: Number.isFinite(hours)
      ? Math.min(IDLE_HOURS.max, Math.max(IDLE_HOURS.min, Math.round(hours)))
      : IDLE_HOURS.fallback,
    recipients: list(raw.recipients).flatMap((item) => {
      const recipient = parseRecipient(item);
      if (!recipient || seen.has(recipient.service)) return [];
      seen.add(recipient.service);
      return [recipient];
    }),
  };
}
function parseKind(value: unknown): NotifyKind | null {
  const raw = record(value);
  const id = text(raw.id);
  if (!id) return null;
  return {
    id,
    name: text(raw.name) ?? id,
    detail: text(raw.detail) ?? "",
    codes: unique(
      list(raw.codes).flatMap(
        (item) => asCode(String(typeof item === "object" ? (record(item).code ?? "") : item)) ?? [],
      ),
    ),
    events: unique(
      list(raw.events).flatMap(
        (item) => text(typeof item === "object" ? record(item).id : item)?.toLowerCase() ?? [],
      ),
    ),
  };
}
function parsePhone(value: unknown): NotifyPhone | null {
  const raw = record(value);
  const service = text(raw.service);
  if (!service || !SERVICE.test(service)) return null;
  return {
    service,
    name: text(raw.name) ?? service,
    user_id: text(raw.user_id),
    user_name: text(raw.user_name),
  };
}
const byKey = <T>(items: (T | null)[], key: (item: T) => string): T[] => {
  const seen = new Set<string>();
  return items.flatMap((item) => {
    if (!item || seen.has(key(item))) return [];
    seen.add(key(item));
    return [item];
  });
};
/** A `notify_get` or `notify_save` answer. Without `can_edit_all` the page edits nothing it cannot
 * show is the user's own. */
export function parseNotifyDocument(value: unknown): NotifyDocument {
  const raw = record(value);
  return {
    schema_version: whole(raw.schema_version) ?? 0,
    config: parseNotifyConfig(raw.config),
    kinds: byKey(list(raw.kinds).map(parseKind), (kind) => kind.id),
    phones: byKey(list(raw.phones).map(parsePhone), (phone) => phone.service),
    can_edit_all: raw.can_edit_all === true,
    user_id: text(raw.user_id),
    error: text(raw.error),
  };
}
/** Whether an answer carries the setup at all: an error alone does not. */
export const hasNotifyConfig = (value: unknown) =>
  Object.keys(record(record(value).config)).length > 0;
export function parseTestResult(value: unknown): NotifyTestResult {
  const raw = record(value);
  return { sent: raw.sent === true, error: text(raw.error) };
}
/** The revision the integration's sensor reports; null when there is none. */
export function liveRevision(states: States): number | null {
  const entity = states[NOTIFY_CONFIG_ID];
  return entity ? whole(entity.state) : null;
}

/** The integration's refusals in words. */
export function notifyError(error: string): string {
  if (error === "revision")
    return "Someone else saved the notifications meanwhile. They have been read again with your changes kept on top: check them, then save again.";
  const refused = /^not allowed\b:?\s*(.*)$/is.exec(error);
  if (refused)
    return `Home Assistant did not allow this${refused[1] ? `: ${refused[1]}` : ""}. An administrator can change every phone; anyone else, only their own phone's ticks.`;
  return error;
}

/** Whether this user may change a row: an administrator any, anyone else only their own phone's. */
export const canEditRow = (
  doc: Pick<NotifyDocument, "can_edit_all" | "user_id">,
  recipient: Pick<NotifyRecipient, "user_id">,
) => doc.can_edit_all || (doc.user_id !== null && recipient.user_id === doc.user_id);

/** How a row is named: the owner and the device from the site's phones, else the service itself.
 * `name` names the row to a screen reader, on each of its controls. */
export function rowLabel(
  recipient: NotifyRecipient,
  phones: readonly NotifyPhone[],
): { title: string; subtitle: string | null; name: string } {
  const phone = phones.find((item) => item.service === recipient.service);
  if (!phone)
    return {
      title: recipient.service,
      subtitle: recipient.name !== recipient.service ? recipient.name : null,
      name: recipient.service,
    };
  if (phone.user_name)
    return {
      title: phone.user_name,
      subtitle: phone.name,
      name: `${phone.user_name} (${phone.name})`,
    };
  return { title: phone.name, subtitle: phone.service, name: phone.name };
}
export const phoneLabel = (phone: NotifyPhone) =>
  phone.user_name ? `${phone.user_name} (${phone.name})` : phone.name;

/** Each code a kind covers with its title from Help's list (null for one it does not have yet), and
 * each event in words. */
export const EVENT_WORDS: Readonly<Record<string, string>> = {
  phase: "a zone changing phase",
  jev_setpoint: "Jev moving a setting",
};
export const eventWords = (id: string) => EVENT_WORDS[id] ?? id.replaceAll("_", " ");
export function kindCoverage(kind: NotifyKind): {
  codes: { code: string; title: string | null }[];
  events: string[];
} {
  return {
    codes: kind.codes.map((code) => ({
      code,
      title: errorCodes.find((entry) => entry.code === code)?.title ?? null,
    })),
    events: kind.events.map(eventWords),
  };
}

/** The page's draft: what the save sends, less the revision it is saved against. */
export interface NotifyDraft {
  idle_hours: number;
  recipients: NotifyRecipient[];
}
export const toDraft = (config: NotifyConfig): NotifyDraft =>
  structuredClone({ idle_hours: config.idle_hours, recipients: config.recipients });
const sorted = (values: readonly string[]) => [...values].sort();
const rowKey = (row: NotifyRecipient) =>
  JSON.stringify([
    row.service,
    row.name,
    row.user_id,
    sorted(row.kinds),
    sorted(row.rooms),
    row.urgent_high_priority,
  ]);
/** The same setup, whatever order the ticks were made and the rows listed in. */
export const sameDraft = (a: NotifyDraft, b: NotifyDraft) =>
  JSON.stringify([a.idle_hours, sorted(a.recipients.map(rowKey))]) ===
  JSON.stringify([b.idle_hours, sorted(b.recipients.map(rowKey))]);

/** One row changed: `change` merged into the row whose service it is. */
export const updateRow = (
  draft: NotifyDraft,
  service: string,
  change: Partial<Omit<NotifyRecipient, "service">>,
): NotifyDraft => ({
  ...draft,
  recipients: draft.recipients.map((row) =>
    row.service === service ? { ...row, ...change } : row,
  ),
});
export const toggleKind = (kinds: readonly string[], id: string, on: boolean): string[] =>
  on ? unique([...kinds, id]) : kinds.filter((kind) => kind !== id);
/** A room chip pressed: All (null) is every room; a room is added or taken out, and taking out the
 * last one is every room again, since a row covers at least one. */
export const toggleRoom = (rooms: readonly string[], prefix: string | null): string[] =>
  prefix === null
    ? []
    : rooms.includes(prefix)
      ? rooms.filter((room) => room !== prefix)
      : [...rooms, prefix];
/** A new row: Emergencies for every room, sent as high priority. */
export function newRecipient(service: string, phones: readonly NotifyPhone[]): NotifyRecipient {
  const phone = phones.find((item) => item.service === service);
  return {
    service,
    name: phone?.name ?? service,
    user_id: phone?.user_id ?? null,
    kinds: [EMERGENCY],
    rooms: [],
    urgent_high_priority: true,
  };
}
/** A notify service typed by name, "notify.x" or just "x"; null when it cannot be one. */
export function serviceFromText(value: string): string | null {
  const typed = value.trim().toLowerCase();
  const service = typed.startsWith("notify.") ? typed : `notify.${typed}`;
  return /^notify\.[a-z0-9_]+$/.test(service) ? service : null;
}
/** The site's phones the setup does not list yet. */
export const unlistedPhones = (draft: NotifyDraft, phones: readonly NotifyPhone[]) =>
  phones.filter((phone) => !draft.recipients.some((row) => row.service === phone.service));

/** The site's rooms that no row sends emergencies for. */
export const roomsWithoutEmergencies = (draft: NotifyDraft, rooms: readonly Room[]): Room[] =>
  rooms.filter(
    (room) =>
      !draft.recipients.some(
        (row) =>
          row.kinds.includes(EMERGENCY) && (!row.rooms.length || row.rooms.includes(room.prefix)),
      ),
  );
/** The checks the integration makes on a save that the page can make first. */
export function draftErrors(draft: NotifyDraft): string[] {
  const hours = draft.idle_hours;
  return Number.isInteger(hours) && hours >= IDLE_HOURS.min && hours <= IDLE_HOURS.max
    ? []
    : [`Watering stopped needs ${IDLE_HOURS.min} to ${IDLE_HOURS.max} whole hours.`];
}

/** What `notify_save` is sent. The threshold is the site's, an administrator's to change: anyone
 * else sends the rows alone. Each row's kinds in the order the page shows them. */
export function savePayload(
  doc: Pick<NotifyDocument, "config" | "kinds" | "can_edit_all">,
  draft: NotifyDraft,
): Record<string, unknown> {
  const order = new Map(doc.kinds.map((kind, index) => [kind.id, index]));
  const rank = (id: string) => order.get(id) ?? order.size;
  return {
    expected_revision: doc.config.revision,
    recipients: draft.recipients.map((row) => ({
      service: row.service,
      name: row.name,
      ...(row.user_id ? { user_id: row.user_id } : {}),
      kinds: [...row.kinds].sort((a, b) => rank(a) - rank(b)),
      rooms: [...row.rooms],
      urgent_high_priority: row.urgent_high_priority,
    })),
    ...(doc.can_edit_all ? { idle_hours: draft.idle_hours } : {}),
  };
}

/** The draft carried onto a setup saved elsewhere meanwhile (a save refused as "revision"): what
 * this draft changed keeps its change, field by field; everything else takes the new value. A row
 * this draft added stays added and one it removed stays removed; a row removed elsewhere goes,
 * unless this draft changed it. */
export function rebaseDraft(
  before: NotifyConfig,
  draft: NotifyDraft,
  after: NotifyConfig,
): NotifyDraft {
  const old = new Map(before.recipients.map((row) => [row.service, row]));
  const mine = new Map(draft.recipients.map((row) => [row.service, row]));
  const fresh = new Set(after.recipients.map((row) => row.service));
  const same = (a: unknown, b: unknown) =>
    JSON.stringify(Array.isArray(a) ? sorted(a) : a) ===
    JSON.stringify(Array.isArray(b) ? sorted(b) : b);
  const recipients = after.recipients.flatMap((row): NotifyRecipient[] => {
    const was = old.get(row.service),
      now = mine.get(row.service);
    if (!now) return was ? [] : [row];
    if (!was) return [now];
    const merged = { ...row };
    for (const field of ["name", "user_id", "kinds", "rooms", "urgent_high_priority"] as const)
      if (!same(now[field], was[field])) Object.assign(merged, { [field]: now[field] });
    return [merged];
  });
  for (const row of draft.recipients) {
    if (fresh.has(row.service)) continue;
    const was = old.get(row.service);
    if (!was || rowKey(was) !== rowKey(row)) recipients.push(row);
  }
  return {
    idle_hours: draft.idle_hours !== before.idle_hours ? draft.idle_hours : after.idle_hours,
    recipients,
  };
}

/** The page's state: the last setup read, and the draft on it (null: nothing changed). */
export interface NotifyState {
  doc: NotifyDocument | null;
  draft: NotifyDraft | null;
}
export type NotifyAction =
  | { type: "loaded"; doc: NotifyDocument }
  | { type: "edit"; edit: (draft: NotifyDraft) => NotifyDraft }
  | { type: "discard" }
  | { type: "saved"; doc: NotifyDocument };
/** A setup read again keeps the draft on top of it; a draft back to what is saved is no draft. */
export function notifyReducer(state: NotifyState, action: NotifyAction): NotifyState {
  const settle = (doc: NotifyDocument, draft: NotifyDraft | null): NotifyState => ({
    doc,
    draft: draft && !sameDraft(draft, toDraft(doc.config)) ? draft : null,
  });
  if (action.type === "loaded")
    return settle(
      action.doc,
      state.doc && state.draft
        ? rebaseDraft(state.doc.config, state.draft, action.doc.config)
        : null,
    );
  if (action.type === "saved") return { doc: action.doc, draft: null };
  if (!state.doc) return state;
  if (action.type === "discard") return { ...state, draft: null };
  return settle(state.doc, action.edit(state.draft ?? toDraft(state.doc.config)));
}

/** A room's name for a prefix, or the prefix of one that is not a room of the site now. */
const roomName = (prefix: string, rooms: readonly Room[]) =>
  rooms.find((room) => room.prefix === prefix)?.name ?? (prefix || "the default room");
export const roomWords = (prefixes: readonly string[], rooms: readonly Room[]) =>
  prefixes.length ? prefixes.map((prefix) => roomName(prefix, rooms)).join(", ") : "All rooms";

export interface ChangeLine {
  label: string;
  before: string | null;
  after: string;
}
export interface PhoneChange {
  service: string;
  title: string;
  change: "added" | "removed" | "changed";
  lines: ChangeLine[];
}
export interface DraftChanges {
  phones: PhoneChange[];
  idle: { before: number; after: number } | null;
  count: number;
}
/** What a save would change, phone by phone, for the review. */
export function draftChanges(
  base: NotifyConfig,
  draft: NotifyDraft,
  context: { kinds: readonly NotifyKind[]; phones: readonly NotifyPhone[]; rooms: readonly Room[] },
): DraftChanges {
  const { kinds, phones, rooms } = context;
  // In the page's order, then any the page does not show.
  const names = (ids: readonly string[]) =>
    kinds
      .filter((kind) => ids.includes(kind.id))
      .map((kind) => kind.name)
      .concat(ids.filter((id) => !kinds.some((kind) => kind.id === id)))
      .join(", ");
  const onOff = (value: boolean) => (value ? "On" : "Off");
  const old = new Map(base.recipients.map((row) => [row.service, row]));
  const listed = new Set(draft.recipients.map((row) => row.service));
  const result: PhoneChange[] = [];
  for (const row of draft.recipients) {
    const was = old.get(row.service);
    const title = rowLabel(row, phones).name;
    if (!was) {
      result.push({
        service: row.service,
        title,
        change: "added",
        lines: [
          { label: "Gets", before: null, after: names(row.kinds) || "nothing yet" },
          { label: "Rooms", before: null, after: roomWords(row.rooms, rooms) },
          {
            label: "High priority for emergencies",
            before: null,
            after: onOff(row.urgent_high_priority),
          },
        ],
      });
      continue;
    }
    const lines: ChangeLine[] = [];
    const started = row.kinds.filter((id) => !was.kinds.includes(id));
    const stopped = was.kinds.filter((id) => !row.kinds.includes(id));
    if (started.length)
      lines.push({ label: "Starts getting", before: null, after: names(started) });
    if (stopped.length) lines.push({ label: "Stops getting", before: null, after: names(stopped) });
    // As JSON: the default room's prefix is "", which a plain join cannot tell from no room.
    if (JSON.stringify(sorted(row.rooms)) !== JSON.stringify(sorted(was.rooms)))
      lines.push({
        label: "Rooms",
        before: roomWords(was.rooms, rooms),
        after: roomWords(row.rooms, rooms),
      });
    if (row.urgent_high_priority !== was.urgent_high_priority)
      lines.push({
        label: "High priority for emergencies",
        before: onOff(was.urgent_high_priority),
        after: onOff(row.urgent_high_priority),
      });
    if (row.name !== was.name) lines.push({ label: "Name", before: was.name, after: row.name });
    if (lines.length) result.push({ service: row.service, title, change: "changed", lines });
  }
  for (const row of base.recipients)
    if (!listed.has(row.service))
      result.push({
        service: row.service,
        title: rowLabel(row, phones).name,
        change: "removed",
        lines: [{ label: "Removed", before: null, after: "no more pushes from Crop Steering" }],
      });
  const idle =
    draft.idle_hours !== base.idle_hours
      ? { before: base.idle_hours, after: draft.idle_hours }
      : null;
  return { phones: result, idle, count: result.length + (idle ? 1 : 0) };
}
