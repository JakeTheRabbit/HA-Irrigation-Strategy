import { errorCodes } from "./error-codes";
import {
  IDLE_HOURS,
  NOTIFY_CONFIG_ID,
  isService,
  parseNotifyConfig,
  type NotifyConfig,
  type NotifyDocument,
  type NotifyKind,
  type NotifyPhone,
  type NotifyRecipient,
  type NotifyTestResult,
} from "./notify";
import type { OperatorAction } from "./operator-types";
import type { States } from "./types";

const codes = (from: number, to: number, skip: number[] = []) =>
  Array.from({ length: to - from + 1 }, (_, index) => from + index)
    .filter((code) => !skip.includes(code))
    .map((code) => `CS-${code}`);

/** The kinds of alert, as the integration's catalog lists them (docs/NOTIFICATIONS.md). */
export const DEMO_KINDS: NotifyKind[] = [
  {
    id: "emergency",
    name: "Emergencies",
    detail: "Every alert whose severity is critical.",
    codes: errorCodes.filter((entry) => entry.severity === "critical").map((entry) => entry.code),
    events: [],
  },
  {
    id: "hardware",
    name: "Hardware lockouts",
    detail:
      "A pump or valve that did not do what it was told, a hardware hold, a shot cut, water that isn't reaching a zone, a table that isn't draining and a sump pump that stopped.",
    codes: [...codes(301, 311), "CS-701"],
    events: [],
  },
  {
    id: "sensors",
    name: "Sensors and drift",
    detail: "A probe the controller cannot use, a zone without one, and a probe Jev set aside.",
    codes: [...codes(101, 104), "CS-603", "CS-604", "CS-703", "CS-704"],
    events: [],
  },
  {
    id: "watering",
    name: "Watering stopped",
    detail:
      "Something stopping the shots in a room or a zone, and a room that has watered nothing for a while with the lights on.",
    codes: [...codes(202, 208), "CS-602", "CS-209"],
    events: [],
  },
  {
    id: "phases",
    name: "Phase changes",
    detail: "A push only, with no notification card.",
    codes: [],
    events: ["phase"],
  },
  {
    id: "stock",
    name: "Stock tanks",
    detail: "A stock tank running low, and a dose not taken off its tank.",
    codes: ["CS-608", "CS-807"],
    events: [],
  },
  {
    id: "dosing",
    name: "Dosing",
    detail: "A dose or a batch that did not end as it should.",
    codes: codes(801, 806),
    events: [],
  },
  {
    id: "jev",
    name: "Jev",
    detail: "Jev's advice, and Jev moving a zone's P2 shot size or re-water point (a push only).",
    codes: ["CS-501", "CS-702", "CS-705", "CS-706", "CS-707", "CS-404"],
    events: ["jev_setpoint"],
  },
  {
    id: "setup",
    name: "Setup and settings",
    detail: "A setup change waiting, settings missing or out of range, and a grow plan holding.",
    codes: ["CS-201", ...codes(401, 405, [404]), "CS-601", "CS-605", "CS-606", "CS-607"],
    events: [],
  },
];
/** The demo site's phones: made-up mobile apps, each registered by a made-up user. */
export const DEMO_PHONES: NotifyPhone[] = [
  ["s23ultra", "S23Ultra", "ben", "Ben"],
  ["callum_phone", "Callum Phone", "callum", "Callum"],
  ["stews_iphone", "Stews iPhone", "stewart", "Stewart"],
  ["sean_iphone", "Sean iPhone", "sean", "Sean"],
  ["pete", "Pete", "pete", "Pete"],
].map(([device, name, user, userName]) => ({
  service: `notify.mobile_app_${device}`,
  name,
  user_id: `demo-user-${user}`,
  user_name: userName,
}));
const row = (index: number, kinds: string[], urgent: boolean): NotifyRecipient => ({
  service: DEMO_PHONES[index].service,
  name: DEMO_PHONES[index].name,
  user_id: DEMO_PHONES[index].user_id,
  kinds,
  rooms: [],
  urgent_high_priority: urgent,
});
/** Saved before the demo starts: Ben gets everything, Callum stock tanks, dosing and hardware
 * lockouts, Stewart emergencies only. Sean and Pete are not listed yet. */
export const DEMO_NOTIFY: NotifyConfig = {
  revision: 3,
  idle_hours: 3,
  recipients: [
    row(
      0,
      DEMO_KINDS.map((kind) => kind.id),
      true,
    ),
    row(1, ["hardware", "stock", "dosing"], false),
    row(2, ["emergency"], true),
  ],
};
const ADMIN = "demo-user-ben";
const rowKey = (item: NotifyRecipient) =>
  JSON.stringify([
    item.name,
    item.user_id,
    [...item.kinds].sort(),
    [...item.rooms].sort(),
    item.urgent_high_priority,
  ]);

/** The integration's notification services, in memory, for the demo. It answers as Ben, an
 * administrator, or with `user` (?demo&notify-user=callum) as that phone's owner, who is not: they
 * may change only their own phone's row, as the integration allows. A test push is never sent. */
export class NotifyDemo {
  private config: NotifyConfig = structuredClone(DEMO_NOTIFY);
  private user: { id: string; admin: boolean };
  constructor(
    private getStates: () => States,
    private updateStates: (states: States) => void,
    user: string | null = null,
  ) {
    const owner = DEMO_PHONES.find(
      (phone) => !!user && phone.user_name?.toLowerCase() === user.trim().toLowerCase(),
    );
    this.user =
      owner?.user_id && owner.user_id !== ADMIN
        ? { id: owner.user_id, admin: false }
        : { id: ADMIN, admin: true };
  }

  call(action: OperatorAction, data: Record<string, unknown>): NotifyDocument | NotifyTestResult {
    this.publish();
    if (action === "notify_get") return this.document(null);
    if (action === "notify_save") return this.save(data);
    if (action === "notify_test") return this.test(data);
    throw new Error("Unsupported demo action.");
  }

  private document(error: string | null): NotifyDocument {
    return structuredClone({
      schema_version: 1,
      config: this.config,
      kinds: DEMO_KINDS,
      phones: DEMO_PHONES,
      can_edit_all: this.user.admin,
      user_id: this.user.id,
      error,
    });
  }
  /** The integration's sensor: the revision, and how many phones are listed. */
  private publish() {
    const states = this.getStates();
    const { revision, recipients } = this.config;
    const current = states[NOTIFY_CONFIG_ID];
    if (current?.state === String(revision) && current.attributes.recipients === recipients.length)
      return;
    const stamp = new Date().toISOString();
    this.updateStates({
      ...states,
      [NOTIFY_CONFIG_ID]: {
        entity_id: NOTIFY_CONFIG_ID,
        state: String(revision),
        attributes: {
          recipients: recipients.length,
          friendly_name: "Crop Steering notifications",
          synthetic: true,
        },
        last_changed: stamp,
        last_updated: stamp,
      },
    });
  }
  private save(data: Record<string, unknown>): NotifyDocument {
    if (data.expected_revision !== this.config.revision) return this.document("revision");
    const sent = Array.isArray(data.recipients) ? data.recipients : null;
    const recipients = parseNotifyConfig({ recipients: sent }).recipients;
    if (!sent || recipients.length !== sent.length)
      return this.document(
        "Each phone needs a notify service such as notify.mobile_app_pixel_7, listed once.",
      );
    const known = new Set(DEMO_KINDS.map((kind) => kind.id));
    const unknown = recipients.flatMap((item) => item.kinds).find((kind) => !known.has(kind));
    if (unknown) return this.document(`${unknown} is not a kind of alert.`);
    const hours = data.idle_hours ?? this.config.idle_hours;
    if (
      typeof hours !== "number" ||
      !Number.isInteger(hours) ||
      hours < IDLE_HOURS.min ||
      hours > IDLE_HOURS.max
    )
      return this.document(
        `Watering stopped needs ${IDLE_HOURS.min} to ${IDLE_HOURS.max} whole hours.`,
      );
    if (!this.user.admin) {
      const before = new Map(this.config.recipients.map((item) => [item.service, item]));
      if (recipients.length !== before.size || recipients.some((item) => !before.has(item.service)))
        return this.document("not allowed: only an administrator adds or removes phones");
      const other = recipients.find((item) => {
        const was = before.get(item.service)!;
        return rowKey(was) !== rowKey(item) && was.user_id !== this.user.id;
      });
      if (other || recipients.some((item) => item.user_id !== before.get(item.service)!.user_id))
        return this.document("not allowed: only an administrator changes other people's phones");
      if (hours !== this.config.idle_hours)
        return this.document("not allowed: only an administrator changes the threshold");
    }
    this.config = { revision: this.config.revision + 1, idle_hours: hours, recipients };
    this.publish();
    return this.document(null);
  }
  private test(data: Record<string, unknown>): NotifyTestResult {
    if (!isService(data.service)) return { sent: false, error: "Choose a notify service." };
    const owner =
      this.config.recipients.find((item) => item.service === data.service)?.user_id ??
      DEMO_PHONES.find((phone) => phone.service === data.service)?.user_id;
    if (!this.user.admin && owner !== this.user.id)
      return {
        sent: false,
        error: "not allowed: only an administrator tests other people's phones",
      };
    // Nothing leaves the demo: the push is only said to be sent.
    return { sent: true, error: null };
  }
}
