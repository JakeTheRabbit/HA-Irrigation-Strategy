import { asCode, errorCodes } from "./error-codes";
import { clock, dayKey, dayLabel, startOfDay, wallText } from "./time";
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
  /** Emergencies go out as high-priority, time-sensitive pushes: "Emergencies loud". */
  urgent_high_priority: boolean;
  /** "HH:MM" on Home Assistant's clock, maybe across midnight: inside them only what is critical
   * reaches the phone, the rest waits for one push when they end. Null: none (and on 3.17). */
  quiet_hours: QuietHours | null;
}
export interface QuietHours {
  from: string;
  to: string;
}
export interface NotifyConfig {
  revision: number;
  idle_hours: number;
  recipients: NotifyRecipient[];
  /** Room prefix -> when its mute ends (ms): until then only emergencies are pushed for it. */
  mutes: Record<string, number>;
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
  /** The integration keeps quiet hours and room mutes (3.18): its answer carries `mutes`. */
  quietAndMutes: boolean;
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
const CLOCK = /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/;
const PREFIX = /^(?:[a-z0-9_]+_)?$/;
/** A complete wall time, "HH:MM". */
export const isClock = (value: string) => CLOCK.test(value);
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
    quiet_hours: parseQuiet(raw.quiet_hours),
  };
}
/** Quiet hours as the integration keeps them: two different "HH:MM"; anything else is none. */
function parseQuiet(value: unknown): QuietHours | null {
  const raw = record(value);
  const from = typeof raw.from === "string" && CLOCK.test(raw.from) ? raw.from : null;
  const to = typeof raw.to === "string" && CLOCK.test(raw.to) ? raw.to : null;
  return from && to && from !== to ? { from, to } : null;
}
function parseMutes(value: unknown): Record<string, number> {
  return Object.fromEntries(
    Object.entries(record(value)).flatMap(([room, until]) => {
      const at = typeof until === "string" ? Date.parse(until) : Number.NaN;
      return PREFIX.test(room) && Number.isFinite(at) ? [[room, at]] : [];
    }),
  );
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
    mutes: parseMutes(raw.mutes),
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
    quietAndMutes: "mutes" in record(raw.config),
  };
}
/** Whether an answer carries the setup at all: an error alone does not. */
export const hasNotifyConfig = (value: unknown) =>
  Object.keys(record(record(value).config)).length > 0;
export function parseTestResult(value: unknown): NotifyTestResult {
  const raw = record(value);
  return { sent: raw.sent === true, error: text(raw.error) };
}
/** What `notify_test {services}` answers, phone by phone; null for an answer without `results`
 * (an integration that tests one phone a call). */
export function parseTestResults(value: unknown): Record<string, NotifyTestResult> | null {
  const results = record(value).results;
  if (!Array.isArray(results)) return null;
  return Object.fromEntries(
    results.flatMap((item) => {
      const raw = record(item);
      return isService(raw.service) ? [[raw.service, parseTestResult(raw)]] : [];
    }),
  );
}
/** Test pushes to `services`: one `notify_test {services}` call when the integration takes it
 * (`many`, 3.18), else one call a phone (3.17, or an integration that refuses `services`). A failed
 * call is that error on each phone: the pushes may have gone, so none is sent twice. */
export async function testPhones(
  services: readonly string[],
  many: boolean,
  call: (data: Record<string, unknown>) => Promise<unknown>,
): Promise<Record<string, NotifyTestResult>> {
  const failed = (err: unknown): NotifyTestResult => ({
    sent: false,
    error: err instanceof Error ? err.message : String(err),
  });
  if (many) {
    try {
      const results = parseTestResults(await call({ services: [...services] })) ?? {};
      return Object.fromEntries(
        services.map((service) => [service, results[service] ?? { sent: false, error: "No answer for this phone." }]),
      );
    } catch (err) {
      if (!/extra keys not allowed/i.test(failed(err).error ?? ""))
        return Object.fromEntries(services.map((service) => [service, failed(err)]));
    }
  }
  const results: Record<string, NotifyTestResult> = {};
  for (const service of services) {
    try {
      results[service] = parseTestResult(await call({ service }));
    } catch (err) {
      results[service] = failed(err);
    }
  }
  return results;
}
/** A test push's answer beside its button: "Accepted 13:58" (Home Assistant took the push, which
 * is not proof the phone showed it), or "Failed 13:40 · " and the integration's words. */
export function testLine(r: { sent: boolean; error: string | null }, at: number, tz: string): string {
  return r.sent
    ? `Accepted ${clock(at, tz)}`
    : `Failed ${clock(at, tz)} · ${r.error ?? "no reason given"}`;
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
  jev_setpoint: "AI assistant setting change",
  vitals: "the controller's regular report on every zone",
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
    row.quiet_hours,
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
/** A room chip pressed where every room shows each chip on (`all`, the site's prefixes): the room
 * goes out or in; every room, or none left, is every room again, since a row covers at least one. */
export function pressRoom(rooms: readonly string[], prefix: string, all: readonly string[]): string[] {
  const current = rooms.length ? rooms : all;
  const next = current.includes(prefix)
    ? current.filter((room) => room !== prefix)
    : [...current, prefix];
  return !next.length || all.every((room) => next.includes(room)) ? [] : next;
}
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
    quiet_hours: null,
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
  return [
    ...(Number.isInteger(hours) && hours >= IDLE_HOURS.min && hours <= IDLE_HOURS.max
      ? []
      : [`Shots stopped needs ${IDLE_HOURS.min} to ${IDLE_HOURS.max} whole hours.`]),
    ...(draft.recipients.some(
      (row) => row.quiet_hours && !(isClock(row.quiet_hours.from) && isClock(row.quiet_hours.to)),
    )
      ? ["Quiet hours need a start and an end as HH:MM."]
      : draft.recipients.some((row) => row.quiet_hours && row.quiet_hours.from === row.quiet_hours.to)
        ? ["Quiet hours need a start and an end that differ."]
        : []),
  ];
}

/** What `notify_save` is sent. The threshold is the site's, an administrator's to change: anyone
 * else sends the rows alone. Each row's kinds in the order the page shows them. */
export function savePayload(
  doc: Pick<NotifyDocument, "config" | "kinds" | "can_edit_all" | "quietAndMutes">,
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
      ...(doc.quietAndMutes ? { quiet_hours: row.quiet_hours } : {}),
    })),
    ...(doc.can_edit_all ? { idle_hours: draft.idle_hours } : {}),
  };
}
/** A mute or unmute, applied at once: the saved rows as they are, and the rooms' new mute ends. */
export function mutePayload(
  doc: Pick<NotifyDocument, "config" | "kinds" | "can_edit_all" | "quietAndMutes">,
  mutes: Record<string, number>,
): Record<string, unknown> {
  return {
    expected_revision: doc.config.revision,
    recipients: savePayload(doc, toDraft(doc.config)).recipients,
    mutes: Object.fromEntries(
      Object.entries(mutes).map(([room, until]) => [room, new Date(until).toISOString()]),
    ),
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
    for (const field of [
      "name",
      "user_id",
      "kinds",
      "rooms",
      "urgent_high_priority",
      "quiet_hours",
    ] as const)
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

/** A room's name for a prefix, or the prefix of one that is not a room of the site now. */
const roomName = (prefix: string, rooms: readonly Room[]) =>
  rooms.find((room) => room.prefix === prefix)?.name ?? (prefix || "the default room");
export const roomWords = (prefixes: readonly string[], rooms: readonly Room[]) =>
  prefixes.length ? prefixes.map((prefix) => roomName(prefix, rooms)).join(", ") : "All rooms";
/** Under a row's room chips: "every room", or "F2 only". */
export const roomChipWords = (prefixes: readonly string[], rooms: readonly Room[]) =>
  prefixes.length ? `${roomWords(prefixes, rooms)} only` : "every room";
export const quietWords = (quiet: QuietHours | null) =>
  quiet ? `${wallText(quiet.from)}–${wallText(quiet.to)}` : "None";

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
          { label: "Emergencies loud", before: null, after: onOff(row.urgent_high_priority) },
          ...(row.quiet_hours
            ? [{ label: "Quiet hours", before: null, after: quietWords(row.quiet_hours) }]
            : []),
        ],
      });
      continue;
    }
    const lines: ChangeLine[] = [];
    const started = row.kinds.filter((id) => !was.kinds.includes(id));
    const stopped = was.kinds.filter((id) => !row.kinds.includes(id));
    if (started.length)
      lines.push({ label: "New alert kinds", before: null, after: names(started) });
    if (stopped.length)
      lines.push({ label: "Removed alert kinds", before: null, after: names(stopped) });
    // As JSON: the default room's prefix is "", which a plain join cannot tell from no room.
    if (JSON.stringify(sorted(row.rooms)) !== JSON.stringify(sorted(was.rooms)))
      lines.push({
        label: "Rooms",
        before: roomWords(was.rooms, rooms),
        after: roomWords(row.rooms, rooms),
      });
    if (row.urgent_high_priority !== was.urgent_high_priority)
      lines.push({
        label: "Emergencies loud",
        before: onOff(was.urgent_high_priority),
        after: onOff(row.urgent_high_priority),
      });
    if (JSON.stringify(row.quiet_hours) !== JSON.stringify(was.quiet_hours))
      lines.push({
        label: "Quiet hours",
        before: quietWords(was.quiet_hours),
        after: quietWords(row.quiet_hours),
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

/** The bottom bar's sentence: "2 changes not applied yet: Sam's phone gets Dosing · Office tablet:
 * F2 only", one part a change, in the rows' order, then the rows taken out, then the threshold;
 * "" with nothing changed. */
export function draftSummary(
  draft: NotifyDraft,
  saved: NotifyConfig,
  context: { kinds: readonly NotifyKind[]; phones: readonly NotifyPhone[]; rooms: readonly Room[] },
): string {
  const { kinds, phones, rooms } = context;
  const names = (ids: readonly string[]) =>
    kinds
      .filter((kind) => ids.includes(kind.id))
      .map((kind) => kind.name)
      .concat(ids.filter((id) => !kinds.some((kind) => kind.id === id)))
      .join(", ");
  const old = new Map(saved.recipients.map((row) => [row.service, row]));
  const listed = new Set(draft.recipients.map((row) => row.service));
  const parts: string[] = [];
  for (const row of draft.recipients) {
    const title = rowLabel(row, phones).title;
    const was = old.get(row.service);
    if (!was) {
      parts.push(`${title} added`);
      continue;
    }
    const started = row.kinds.filter((id) => !was.kinds.includes(id));
    const stopped = was.kinds.filter((id) => !row.kinds.includes(id));
    if (started.length) parts.push(`${title} gets ${names(started)}`);
    if (stopped.length) parts.push(`${title} stops getting ${names(stopped)}`);
    if (JSON.stringify(sorted(row.rooms)) !== JSON.stringify(sorted(was.rooms)))
      parts.push(`${title}: ${roomChipWords(row.rooms, rooms)}`);
    if (row.urgent_high_priority !== was.urgent_high_priority)
      parts.push(`${title}: emergencies ${row.urgent_high_priority ? "loud" : "not loud"}`);
    if (JSON.stringify(row.quiet_hours) !== JSON.stringify(was.quiet_hours))
      parts.push(
        `${title}: ${row.quiet_hours ? `quiet ${quietWords(row.quiet_hours)}` : "no quiet hours"}`,
      );
    if (row.name !== was.name) parts.push(`${title} renamed ${row.name}`);
  }
  for (const row of saved.recipients)
    if (!listed.has(row.service)) parts.push(`${rowLabel(row, phones).title} removed`);
  if (draft.idle_hours !== saved.idle_hours)
    parts.push(`Watering stopped after ${draft.idle_hours} h`);
  if (!parts.length) return "";
  const n = parts.length;
  return `${n} ${n === 1 ? "change" : "changes"} not applied yet: ${parts.join(" · ")}`;
}

/** Minutes of the day [start, end) on the 24-hour strip, the day's end as 1440. */
export type Span = [number, number];
const minuteOf = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
/** A window on one day's strip, split at midnight when it crosses it. */
const daySpans = (start: number, end: number): Span[] =>
  start < end
    ? [[start, end]]
    : ([
        [0, end],
        [start, 1440],
      ] as Span[]).filter(([a, b]) => b > a);
function merge(spans: Span[]): Span[] {
  const out: Span[] = [];
  for (const [a, b] of [...spans].sort((x, y) => x[0] - y[0])) {
    const last = out.at(-1);
    if (last && a <= last[1]) last[1] = Math.max(last[1], b);
    else out.push([a, b]);
  }
  return out;
}
/** Every phone's quiet hours on one day's strip, as one union. */
export const quietSpans = (windows: readonly (QuietHours | null)[]): Span[] =>
  merge(windows.flatMap((w) => (w ? daySpans(minuteOf(w.from), minuteOf(w.to)) : [])));
export const spanMinutes = (spans: readonly Span[]) =>
  spans.reduce((sum, [a, b]) => sum + b - a, 0);
/** A room's lights on the strip, from its lights-on and lights-off hours (its number entities). */
export function lightSpans(onHour: number, offHour: number): Span[] {
  if (!Number.isFinite(onHour) || !Number.isFinite(offHour) || onHour === offHour) return [];
  return daySpans(Math.round(onHour * 60), Math.round(offHour * 60));
}

/** When a room's mute ends, from now: "08:00", "08:00 tomorrow", or "08:00 Sat 25 Oct". */
export function muteEndWords(at: number, now: number, tz: string): string {
  const day = dayKey(at, tz);
  if (day === dayKey(now, tz)) return clock(at, tz);
  if (day === dayKey(startOfDay(now, tz) + 36 * 3_600_000, tz)) return `${clock(at, tz)} tomorrow`;
  return `${clock(at, tz)} ${dayLabel(at, tz)}`;
}
/** The mute read back is the one written: the integration keeps whole seconds. */
export const sameMuteEnd = (read: number | undefined, wanted: number | null) =>
  wanted === null ? read === undefined : read !== undefined && Math.abs(read - wanted) < 1000;

/** One line of the review: a phone's change (`key` its service) or the threshold (`key` "idle"). */
export interface NotifyReviewRow {
  id: string;
  key: string;
  label: string;
  before: string;
  after: string;
}
export function reviewRows(changes: DraftChanges): NotifyReviewRow[] {
  return [
    ...changes.phones.flatMap((phone) =>
      phone.lines.map((line) => ({
        id: `${phone.service}|${line.label}`,
        key: phone.service,
        label: `${phone.title}: ${line.label}`,
        before: line.before ?? (phone.change === "added" ? "Not listed" : "—"),
        after: line.after,
      })),
    ),
    ...(changes.idle
      ? [
          {
            id: "idle",
            key: "idle",
            label: "Watering stopped after",
            before: `${changes.idle.before} h`,
            after: `${changes.idle.after} h`,
          },
        ]
      : []),
  ];
}
/** What a save did, row by row, from the setup `notify_save` answered with (the integration's
 * stored setup, read after writing): a row is written and read back only when its phone (or the
 * threshold) reads back exactly as sent; any other is named as not confirmed, never as taken. */
export function saveReceipt(
  rows: readonly NotifyReviewRow[],
  sent: NotifyDraft,
  read: NotifyConfig,
  at: number,
): {
  at: number;
  ok: boolean;
  failed: [];
  notConfirmed?: string[];
  summary: string;
  eventIds: [];
} {
  const back = new Map(read.recipients.map((row) => [row.service, row]));
  // As the integration stores a row: its name trimmed and cut to 40, its user filled in when unsent.
  const stored = (row: NotifyRecipient) => {
    const was = back.get(row.service);
    return rowKey({
      ...row,
      name: row.name.trim().slice(0, 40) || (was?.name ?? row.service),
      user_id: row.user_id ?? was?.user_id ?? null,
    });
  };
  const mine = new Map(sent.recipients.map((row) => [row.service, stored(row)]));
  const confirmed = (key: string) => {
    if (key === "idle") return read.idle_hours === sent.idle_hours;
    const was = back.get(key);
    return mine.get(key) === (was ? rowKey(was) : undefined);
  };
  const unsure = rows.filter((row) => !confirmed(row.key)).map((row) => row.id);
  return {
    at,
    ok: !unsure.length,
    failed: [],
    ...(unsure.length ? { notConfirmed: unsure } : {}),
    summary: rows
      .filter((row) => !unsure.includes(row.id))
      .map((row) => `${row.label} ${row.before} → ${row.after}`)
      .join(" · "),
    eventIds: [],
  };
}
