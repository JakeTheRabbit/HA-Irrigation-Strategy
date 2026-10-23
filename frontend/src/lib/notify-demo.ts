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

const HOUR = 3_600_000;
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
      "A pump or valve that did not do what it was told, a hardware hold, a shot cut, a zone that keeps hitting its longest allowed shot, water that does not get to a zone or that possibly goes around its substrate, a table that isn't draining, a sump pump that stopped a pump or valve the controller can't switch, a zone that needs more than its pump, and a flow meter that disagrees with the shots.",
    codes: ["CS-214", ...codes(301, 319), "CS-701", "CS-710"],
    events: [],
  },
  {
    id: "sensors",
    name: "Sensors and drift",
    detail:
      "A probe the controller cannot use, a probe set aside for its unit, a zone without one, a zone whose probes disagree or whose primary probe is offline, a zone steering on bulk EC, a probe that the AI assistant set aside, a room with no feed EC, so no EC flush, a feed probe due its calibration and probe offsets that cannot be read.",
    codes: [...codes(101, 104), "CS-502", "CS-503", "CS-504", "CS-505", "CS-603", "CS-604", "CS-612", "CS-615", "CS-703", "CS-704", "CS-907"],
    events: [],
  },
  {
    id: "watering",
    name: "Shots stopped",
    detail:
      "Something stopping the shots in a room or a zone, a room that has watered nothing for a while with the lights on, the tank it waters from at its minimum, due a refill or over its full mark, and a batch tank to refill.",
    codes: [...codes(202, 208), "CS-602", "CS-609", "CS-209", "CS-210", "CS-211", "CS-212", "CS-316", ...codes(901, 906)],
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
    id: "vitals",
    name: "Vitals",
    detail:
      "The controller's regular report on every zone: moisture, EC, water today and, while the room's predictions switch is on, what each zone does next.",
    codes: [],
    events: ["vitals"],
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
    detail: "A dose or a batch that did not end correctly, or a mix outside its EC or pH band.",
    codes: [...codes(801, 806), ...codes(808, 811)],
    events: [],
  },
  {
    id: "jev",
    name: "AI assistant",
    detail:
      "The advice of the AI assistant, and its changes to the P2 shot size or the re-water point of a zone (a push only). Also its AI budget, key, the removed first AI route and feed proposals, and the grow plan state of the room.",
    codes: [
      "CS-501",
      "CS-702",
      "CS-705",
      "CS-706",
      "CS-707",
      "CS-708",
      "CS-709",
      "CS-711",
      "CS-712",
      "CS-713",
      "CS-404",
    ],
    events: ["jev_setpoint"],
  },
  {
    id: "setup",
    name: "Setup and settings",
    detail:
      "A setup change waiting, settings missing or out of range, a grow plan holding, an Engine Enabled switch that does not stop water, a retired entity an automation still uses, and the upgrade report of an update.",
    codes: [
      "CS-201",
      ...codes(401, 405, [404]),
      "CS-601",
      "CS-605",
      "CS-606",
      "CS-607",
      "CS-610",
      "CS-611",
      "CS-613",
      "CS-614",
      "CS-616",
      "CS-713",
    ],
    events: [],
  },
];
/** The demo site's phones: made-up mobile apps, each registered by a made-up user. */
export const DEMO_PHONES: NotifyPhone[] = [
  ["phone_1", "Phone 1", "owner", "Owner"],
  ["phone_2", "Phone 2", "grower", "Grower"],
  ["phone_3", "Phone 3", "manager", "Manager"],
  ["phone_4", "Phone 4", "assistant", "Assistant"],
  ["phone_5", "Phone 5", "visitor", "Visitor"],
].map(([device, name, user, userName]) => ({
  service: `notify.mobile_app_${device}`,
  name,
  user_id: `demo-user-${user}`,
  user_name: userName,
}));
const row = (
  index: number,
  kinds: string[],
  urgent: boolean,
  quiet: NotifyRecipient["quiet_hours"] = null,
): NotifyRecipient => ({
  service: DEMO_PHONES[index].service,
  name: DEMO_PHONES[index].name,
  user_id: DEMO_PHONES[index].user_id,
  kinds,
  rooms: [],
  urgent_high_priority: urgent,
  quiet_hours: quiet,
});
/** Saved before the demo starts: the owner gets everything, quiet from 23:00 to 05:00, the grower
 * stock tanks, dosing and hardware lockouts, the manager emergencies only. The assistant and the
 * visitor are not listed yet. Nothing is muted; the demo mutes Room B as it starts. */
export const DEMO_NOTIFY: NotifyConfig = {
  revision: 3,
  idle_hours: 3,
  recipients: [
    row(
      0,
      DEMO_KINDS.map((kind) => kind.id),
      true,
      { from: "23:00", to: "05:00" },
    ),
    row(1, ["hardware", "stock", "dosing"], false),
    row(2, ["emergency"], true),
  ],
  mutes: {},
};
const ADMIN = "demo-user-owner";
const rowKey = (item: NotifyRecipient) =>
  JSON.stringify([
    item.name,
    item.user_id,
    [...item.kinds].sort(),
    [...item.rooms].sort(),
    item.urgent_high_priority,
    item.quiet_hours,
  ]);

/** The integration's notification services, in memory, for the demo. It answers as the owner, an
 * administrator, or with `user` (?demo&notify-user=grower) as that phone's owner, who is not: they
 * may change only their own phone's row, as the integration allows. A test push is never sent.
 * `backend` "3.17" answers as that integration: no quiet hours, no mutes, one phone a test. */
export class NotifyDemo {
  private config: NotifyConfig = structuredClone(DEMO_NOTIFY);
  private user: { id: string; admin: boolean };
  constructor(
    private getStates: () => States,
    private updateStates: (states: States) => void,
    user: string | null = null,
    private backend: "3.17" | "3.18" = "3.18",
  ) {
    // Room B muted until five hours after the next whole hour (5 to 6 h from the start).
    if (backend === "3.18") this.config.mutes = { room_b_: Math.ceil(Date.now() / HOUR) * HOUR + 5 * HOUR };
    const owner = DEMO_PHONES.find(
      (phone) => !!user && phone.user_name?.toLowerCase() === user.trim().toLowerCase(),
    );
    this.user =
      owner?.user_id && owner.user_id !== ADMIN
        ? { id: owner.user_id, admin: false }
        : { id: ADMIN, admin: true };
  }

  call(
    action: OperatorAction,
    data: Record<string, unknown>,
  ): NotifyDocument | NotifyTestResult | { results: unknown[] } {
    this.publish();
    if (action === "notify_get") return this.document(null);
    if (action === "notify_save") return this.save(data);
    if (action === "notify_test") return this.test(data);
    throw new Error("Unsupported demo action.");
  }

  /** As `notify_get` answers: mutes as ISO times; 3.17 has no mutes and no quiet hours. */
  private document(error: string | null): NotifyDocument {
    const { mutes, ...config } = this.config;
    const answer =
      this.backend === "3.17"
        ? { ...config, recipients: config.recipients.map(({ quiet_hours: _q, ...item }) => item) }
        : {
            ...config,
            mutes: Object.fromEntries(
              Object.entries(mutes).map(([room, at]) => [room, new Date(at).toISOString()]),
            ),
          };
    return structuredClone({
      schema_version: 1,
      config: answer as unknown as NotifyConfig,
      kinds: DEMO_KINDS,
      phones: DEMO_PHONES,
      can_edit_all: this.user.admin,
      user_id: this.user.id,
      error,
      quietAndMutes: this.backend === "3.18",
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
    const stored = new Map(this.config.recipients.map((item) => [item.service, item]));
    // A row sent without quiet hours keeps its own, as the integration does.
    const recipients = parseNotifyConfig({ recipients: sent }).recipients.map((item, index) => {
      const raw = (sent?.[index] ?? {}) as Record<string, unknown>;
      return "quiet_hours" in raw ? item : { ...item, quiet_hours: stored.get(item.service)?.quiet_hours ?? null };
    });
    if (!sent || recipients.length !== sent.length)
      return this.document(
        "Each phone needs a notify service such as notify.mobile_app_pixel_7, listed once.",
      );
    if (this.backend === "3.18") {
      // Refused in the integration's words: a window it cannot read, or one that starts as it ends.
      for (const [index, raw] of (sent ?? []).entries()) {
        const quiet = (raw as Record<string, unknown> | null)?.quiet_hours as Record<string, unknown> | null | undefined;
        if (quiet == null || recipients[index]?.quiet_hours) continue;
        return this.document(
          quiet.from !== undefined && quiet.from === quiet.to
            ? `phone ${index + 1}: Quiet hours need a start and an end that differ`
            : `phone ${index + 1}: quiet_hours must be {from, to} as HH:MM, 00:00 to 23:59`,
        );
      }
    }
    let mutes = this.config.mutes;
    if (this.backend === "3.18" && data.mutes !== undefined) {
      if (!this.user.admin) return this.document("not allowed: only an administrator can mute a room");
      mutes = parseNotifyConfig({ mutes: data.mutes }).mutes;
      mutes = Object.fromEntries(Object.entries(mutes).filter(([, at]) => at > Date.now()));
    }
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
        `Shots stopped needs ${IDLE_HOURS.min} to ${IDLE_HOURS.max} whole hours.`,
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
    this.config = { revision: this.config.revision + 1, idle_hours: hours, recipients, mutes };
    this.publish();
    return this.document(null);
  }
  private test(data: Record<string, unknown>): NotifyTestResult | { results: unknown[] } {
    if (data.services !== undefined) {
      if (this.backend === "3.17") throw new Error("extra keys not allowed @ data['services']");
      const services = Array.isArray(data.services) ? data.services : [];
      return { results: services.map((service) => ({ service, ...this.test({ service }) })) };
    }
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
