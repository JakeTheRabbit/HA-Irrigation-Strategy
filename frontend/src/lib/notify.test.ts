import { afterEach, describe, expect, it, vi } from "vitest";
import { HaClient } from "./client";
import { createDemo } from "./demo";
import { setDisplayUnits } from "./display-units";
import { errorCodes } from "./error-codes";
import {
  NOTIFY_CONFIG_ID,
  canEditRow,
  draftChanges,
  draftErrors,
  draftSummary,
  hasNotifyConfig,
  kindCoverage,
  lightSpans,
  liveRevision,
  muteEndWords,
  mutePayload,
  newRecipient,
  notifyError,
  parseNotifyDocument,
  parseTestResult,
  parseTestResults,
  phoneLabel,
  pressRoom,
  quietSpans,
  rebaseDraft,
  reviewRows,
  roomChipWords,
  roomWords,
  roomsWithoutEmergencies,
  rowLabel,
  sameDraft,
  sameMuteEnd,
  saveReceipt,
  savePayload,
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
  type NotifyRecipient,
  type NotifyTestResult,
} from "./notify";
import { DEMO_KINDS, DEMO_NOTIFY, DEMO_PHONES, NotifyDemo } from "./notify-demo";
import { OperatorDemo } from "./operator-demo";
import type { Room, States } from "./types";
import { ControllerStore } from "./use-controller";

const ROOMS: Room[] = [
  { id: "room:", prefix: "", name: "Room A" },
  { id: "room:room_b_", prefix: "room_b_", name: "Room B" },
];
const recipient = (
  service: string,
  kinds: string[],
  change: Partial<NotifyRecipient> = {},
): NotifyRecipient => ({
  service,
  name: service.replace("notify.mobile_app_", ""),
  user_id: null,
  kinds,
  rooms: [],
  urgent_high_priority: true,
  quiet_hours: null,
  ...change,
});
const config = (recipients: NotifyRecipient[], revision = 3, idle_hours = 3): NotifyConfig => ({
  revision,
  idle_hours,
  recipients,
  mutes: {},
});
const doc = (change: Partial<NotifyDocument> = {}): NotifyDocument => ({
  schema_version: 1,
  config: structuredClone(DEMO_NOTIFY),
  kinds: DEMO_KINDS,
  phones: DEMO_PHONES,
  can_edit_all: true,
  user_id: "demo-user-owner",
  error: null,
  quietAndMutes: false,
  ...change,
});
const OWNER = "notify.mobile_app_phone_1";
const GROWER = "notify.mobile_app_phone_2";
const MANAGER = "notify.mobile_app_phone_3";
const ASSISTANT = "notify.mobile_app_phone_4";

describe("reading what notify_get returns", () => {
  it("reads the setup, the kinds, the phones and who is asking", () => {
    const read = parseNotifyDocument({
      schema_version: 1,
      config: {
        revision: 7,
        idle_hours: 4,
        recipients: [
          {
            service: "notify.mobile_app_pixel_7",
            name: "Grower's phone",
            user_id: "7f21",
            kinds: ["stock", "dosing"],
            rooms: ["room_b_"],
            urgent_high_priority: true,
          },
        ],
      },
      kinds: [
        {
          id: "jev",
          name: "AI assistant",
          detail: "The AI assistant's advice",
          codes: ["CS-501"],
          events: ["jev_setpoint"],
        },
      ],
      phones: [
        { service: "notify.mobile_app_pixel_7", name: "Pixel 7", user_id: "7f21", user_name: "C" },
      ],
      can_edit_all: false,
      user_id: "7f21",
    });
    expect(read).toEqual({
      schema_version: 1,
      config: {
        revision: 7,
        idle_hours: 4,
        recipients: [
          {
            service: "notify.mobile_app_pixel_7",
            name: "Grower's phone",
            user_id: "7f21",
            kinds: ["stock", "dosing"],
            rooms: ["room_b_"],
            urgent_high_priority: true,
            quiet_hours: null,
          },
        ],
        mutes: {},
      },
      kinds: [
        {
          id: "jev",
          name: "AI assistant",
          detail: "The AI assistant's advice",
          codes: ["CS-501"],
          events: ["jev_setpoint"],
        },
      ],
      phones: [
        { service: "notify.mobile_app_pixel_7", name: "Pixel 7", user_id: "7f21", user_name: "C" },
      ],
      can_edit_all: false,
      user_id: "7f21",
      error: null,
      quietAndMutes: false,
    });
  });
  it("falls back on anything missing or garbled, and never grants editing it cannot read", () => {
    const read = parseNotifyDocument({
      config: {
        revision: "5",
        idle_hours: "40",
        recipients: [
          { service: "notify.a", kinds: ["emergency", "emergency", 3], rooms: ["", "room_b_", "F 2"] },
          { service: "notify.a", kinds: ["stock"] },
          { service: "light.kitchen", kinds: ["stock"] },
          { service: "notify.b c" },
          "nonsense",
        ],
      },
      kinds: [
        { id: "x", codes: ["cs101", { code: "CS-102" }, "CS-102", 103, "no code"] },
        { id: "x", name: "Twice" },
        { name: "No id" },
        { id: "y", events: [{ id: "Phase" }, "phase", ""] },
      ],
      phones: [{ service: "notify.a" }, { service: "notify.a", name: "Again" }, { name: "none" }],
      can_edit_all: "yes",
    });
    expect(read.config).toEqual({
      revision: 5,
      idle_hours: 12,
      recipients: [
        {
          service: "notify.a",
          name: "notify.a",
          user_id: null,
          kinds: ["emergency"],
          rooms: ["", "room_b_"],
          urgent_high_priority: false,
          quiet_hours: null,
        },
      ],
      mutes: {},
    });
    expect(read.kinds).toEqual([
      { id: "x", name: "x", detail: "", codes: ["CS-101", "CS-102", "CS-103"], events: [] },
      { id: "y", name: "y", detail: "", codes: [], events: ["phase"] },
    ]);
    expect(read.phones).toEqual([
      { service: "notify.a", name: "notify.a", user_id: null, user_name: null },
    ]);
    expect(read).toMatchObject({ schema_version: 0, can_edit_all: false, user_id: null });
    // Nothing at all: an empty setup, three hours, and nothing editable.
    expect(parseNotifyDocument(null)).toEqual({
      schema_version: 0,
      config: { revision: 0, idle_hours: 3, recipients: [], mutes: {} },
      kinds: [],
      phones: [],
      can_edit_all: false,
      user_id: null,
      error: null,
      quietAndMutes: false,
    });
    expect(parseNotifyDocument({ config: { idle_hours: 0.2 } }).config.idle_hours).toBe(1);
  });
  it("tells an answer carrying the setup from an error alone, and reads a test's answer", () => {
    expect(hasNotifyConfig({ config: { revision: 1, recipients: [] } })).toBe(true);
    expect(hasNotifyConfig({ error: "revision" })).toBe(false);
    expect(hasNotifyConfig("revision")).toBe(false);
    expect(parseTestResult({ sent: true })).toEqual<NotifyTestResult>({ sent: true, error: null });
    expect(parseTestResult({ error: "No such service" })).toEqual({
      sent: false,
      error: "No such service",
    });
    expect(parseTestResult(undefined)).toEqual({ sent: false, error: null });
  });
  it("reads the revision off the integration's sensor", () => {
    const sensor = (state: string): States => ({
      [NOTIFY_CONFIG_ID]: { entity_id: NOTIFY_CONFIG_ID, state, attributes: { recipients: 2 } },
    });
    expect(liveRevision(sensor("4"))).toBe(4);
    expect(liveRevision(sensor("unavailable"))).toBeNull();
    expect(liveRevision({})).toBeNull();
  });
  it("says the integration's refusals in words", () => {
    expect(notifyError("revision")).toMatch(/^Someone else saved .* your changes kept on top/);
    expect(notifyError("not allowed: that phone is the owner's")).toBe(
      "Home Assistant did not allow this: that phone is the owner's. An administrator can change every phone; anyone else, only their own phone's ticks.",
    );
    expect(notifyError("not allowed")).toMatch(/^Home Assistant did not allow this\. /);
    expect(notifyError("notify.x is not a notify service")).toBe(
      "notify.x is not a notify service",
    );
  });
});

describe("who may change a row, and what it is called", () => {
  it("lets an administrator change every row, anyone else only their own phone's", () => {
    const own = { user_id: "u1" },
      other = { user_id: "u2" },
      nobody = { user_id: null };
    expect(canEditRow({ can_edit_all: true, user_id: "u1" }, other)).toBe(true);
    expect(canEditRow({ can_edit_all: true, user_id: null }, nobody)).toBe(true);
    expect(canEditRow({ can_edit_all: false, user_id: "u1" }, own)).toBe(true);
    expect(canEditRow({ can_edit_all: false, user_id: "u1" }, other)).toBe(false);
    // A row without an owner is no one's but an administrator's, whoever asks.
    expect(canEditRow({ can_edit_all: false, user_id: "u1" }, nobody)).toBe(false);
    expect(canEditRow({ can_edit_all: false, user_id: null }, nobody)).toBe(false);
  });
  it("names a row by its owner and device, or by its service when the site has no such phone", () => {
    expect(rowLabel(recipient(OWNER, []), DEMO_PHONES)).toEqual({
      title: "Owner",
      subtitle: "Phone 1",
      name: "Owner (Phone 1)",
    });
    const noOwner = [
      { service: "notify.mobile_app_tab", name: "Tab", user_id: null, user_name: null },
    ];
    expect(rowLabel(recipient("notify.mobile_app_tab", []), noOwner)).toEqual({
      title: "Tab",
      subtitle: "notify.mobile_app_tab",
      name: "Tab",
    });
    expect(rowLabel(recipient("notify.everyone", [], { name: "Everyone" }), DEMO_PHONES)).toEqual({
      title: "notify.everyone",
      subtitle: "Everyone",
      name: "notify.everyone",
    });
    expect(
      rowLabel(recipient("notify.everyone", [], { name: "notify.everyone" }), []).subtitle,
    ).toBeNull();
  });
  it("lists what a kind covers: its codes with Help's titles, its events in words", () => {
    const watering = kindCoverage(DEMO_KINDS.find((kind) => kind.id === "watering")!);
    expect(watering.codes[0]).toEqual({
      code: "CS-202",
      title: "Pump or main-line mismatch",
    });
    expect(watering.codes.find((item) => item.code === "CS-209")).toEqual({
      code: "CS-209",
      title: "No shots for some hours",
    });
    expect(kindCoverage(DEMO_KINDS.find((kind) => kind.id === "phases")!).events).toEqual([
      "a zone changing phase",
    ]);
    expect(kindCoverage(DEMO_KINDS.find((kind) => kind.id === "jev")!).events).toEqual([
      "AI assistant setting change",
    ]);
    expect(kindCoverage(DEMO_KINDS.find((kind) => kind.id === "vitals")!).events).toEqual([
      "the controller's regular report on every zone",
    ]);
    expect(
      kindCoverage({ id: "z", name: "Z", detail: "", codes: [], events: ["tank_refill"] }).events,
    ).toEqual(["tank refill"]);
  });
});

describe("the draft", () => {
  it("is the same setup whatever order the ticks were made and the rows listed in", () => {
    const a = toDraft(config([recipient(OWNER, ["stock", "dosing"], { rooms: ["room_b_", ""] })]));
    const b = toDraft(config([recipient(OWNER, ["dosing", "stock"], { rooms: ["", "room_b_"] })]));
    expect(sameDraft(a, b)).toBe(true);
    expect(sameDraft(a, { ...a, idle_hours: 4 })).toBe(false);
    expect(sameDraft(a, updateRow(a, OWNER, { urgent_high_priority: false }))).toBe(false);
    // A row removed and added again as it was is no change.
    const two = toDraft(
      config([recipient(OWNER, ["emergency"]), recipient(MANAGER, ["emergency"])]),
    );
    expect(sameDraft(two, { ...two, recipients: [...two.recipients].reverse() })).toBe(true);
    expect(sameDraft(two, { ...two, recipients: [two.recipients[0]] })).toBe(false);
    // A copy: editing the draft leaves the saved setup as it was.
    const saved = config([recipient(OWNER, ["stock"])]);
    toDraft(saved).recipients[0].kinds.push("dosing");
    expect(saved.recipients[0].kinds).toEqual(["stock"]);
  });
  it("ticks and unticks a kind", () => {
    expect(toggleKind(["stock"], "dosing", true)).toEqual(["stock", "dosing"]);
    expect(toggleKind(["stock", "dosing"], "dosing", true)).toEqual(["stock", "dosing"]);
    expect(toggleKind(["stock", "dosing"], "stock", false)).toEqual(["dosing"]);
  });
  it("adds a phone with Emergencies ticked for every room, from the site's phones or by name", () => {
    expect(newRecipient(ASSISTANT, DEMO_PHONES)).toEqual({
      service: ASSISTANT,
      name: "Phone 4",
      user_id: "demo-user-assistant",
      kinds: ["emergency"],
      rooms: [],
      urgent_high_priority: true,
      quiet_hours: null,
    });
    expect(newRecipient("notify.family", DEMO_PHONES)).toMatchObject({
      service: "notify.family",
      name: "notify.family",
      user_id: null,
      kinds: ["emergency"],
    });
    expect(serviceFromText(" family_group ")).toBe("notify.family_group");
    expect(serviceFromText("Notify.Mobile_App_Pixel_7")).toBe("notify.mobile_app_pixel_7");
    for (const bad of ["", "notify.", "notify.a.b", "two words", "light.kitchen"])
      expect(serviceFromText(bad)).toBeNull();
    const draft = toDraft(DEMO_NOTIFY);
    expect(unlistedPhones(draft, DEMO_PHONES).map((phone) => phone.user_name)).toEqual([
      "Assistant",
      "Visitor",
    ]);
  });
  it("finds each room nobody gets emergencies for", () => {
    const draft = (recipients: NotifyRecipient[]) => toDraft(config(recipients));
    expect(roomsWithoutEmergencies(toDraft(DEMO_NOTIFY), ROOMS)).toEqual([]);
    expect(
      roomsWithoutEmergencies(draft([recipient(OWNER, ["emergency"], { rooms: [""] })]), ROOMS),
    ).toEqual([ROOMS[1]]);
    expect(
      roomsWithoutEmergencies(
        draft([
          recipient(OWNER, ["stock"]),
          recipient(GROWER, ["emergency"], { rooms: ["room_b_"] }),
          recipient(MANAGER, ["emergency"], { rooms: [""] }),
        ]),
        ROOMS,
      ),
    ).toEqual([]);
    expect(roomsWithoutEmergencies(draft([recipient(OWNER, ["stock"])]), ROOMS)).toEqual(ROOMS);
  });
  it("checks the threshold as the integration does", () => {
    const draft = toDraft(DEMO_NOTIFY);
    expect(draftErrors(draft)).toEqual([]);
    for (const hours of [0, 13, 2.5, Number.NaN])
      expect(draftErrors({ ...draft, idle_hours: hours })).toEqual([
        "Shots stopped needs 1 to 12 whole hours.",
      ]);
  });
});

describe("saving", () => {
  it("sends every row against the revision it was read at, the threshold only as an administrator", () => {
    const draft = toDraft(
      config([
        recipient(GROWER, ["dosing", "phases", "stock", "unknown"], {
          user_id: "demo-user-grower",
          rooms: ["room_b_"],
        }),
        recipient("notify.family", ["emergency"]),
      ]),
    );
    const payload = savePayload(doc(), { ...draft, idle_hours: 5 });
    expect(payload).toEqual({
      expected_revision: 3,
      recipients: [
        {
          service: GROWER,
          name: "phone_2",
          user_id: "demo-user-grower",
          kinds: ["phases", "stock", "dosing", "unknown"],
          rooms: ["room_b_"],
          urgent_high_priority: true,
        },
        // No owner: sent without one.
        {
          service: "notify.family",
          name: "notify.family",
          kinds: ["emergency"],
          rooms: [],
          urgent_high_priority: true,
        },
      ],
      idle_hours: 5,
    });
    expect(savePayload(doc({ can_edit_all: false }), draft)).not.toHaveProperty("idle_hours");
  });
  it("carries a draft onto a setup saved elsewhere meanwhile, field by field", () => {
    const before = config([
      recipient(OWNER, ["emergency", "stock"]),
      recipient(GROWER, ["hardware"]),
      recipient(MANAGER, ["emergency"]),
      recipient("notify.gone", ["stock"]),
    ]);
    // This draft: the grower ticks phases, the manager is removed, the assistant is added, the threshold is 5.
    const draft: ReturnType<typeof toDraft> = {
      idle_hours: 5,
      recipients: [
        recipient(OWNER, ["emergency", "stock"]),
        recipient(GROWER, ["hardware", "phases"]),
        recipient("notify.gone", ["stock", "dosing"]),
        recipient(ASSISTANT, ["emergency"]),
      ],
    };
    // Elsewhere: the owner's rooms and high priority, the grower's rooms, a new family group; "gone" removed.
    const after = config(
      [
        recipient(OWNER, ["emergency", "stock"], { rooms: ["room_b_"], urgent_high_priority: false }),
        recipient(GROWER, ["hardware"], { rooms: [""] }),
        recipient(MANAGER, ["emergency"]),
        recipient("notify.family", ["emergency"]),
      ],
      4,
      3,
    );
    const rebased = rebaseDraft(before, draft, after);
    expect(rebased.idle_hours).toBe(5);
    expect(rebased.recipients).toEqual([
      recipient(OWNER, ["emergency", "stock"], { rooms: ["room_b_"], urgent_high_priority: false }),
      recipient(GROWER, ["hardware", "phases"], { rooms: [""] }),
      recipient("notify.family", ["emergency"]),
      // Changed here, removed elsewhere: kept, so the review shows it as added.
      recipient("notify.gone", ["stock", "dosing"]),
      recipient(ASSISTANT, ["emergency"]),
    ]);
    // A row removed elsewhere that this draft did not touch goes with it.
    const untouched = rebaseDraft(before, toDraft(before), after);
    expect(untouched.recipients.map((row) => row.service)).toEqual([
      OWNER,
      GROWER,
      MANAGER,
      "notify.family",
    ]);
    expect(untouched.idle_hours).toBe(3);
  });
  it("lists what a save changes, phone by phone", () => {
    const base = DEMO_NOTIFY;
    let draft = toDraft(base);
    draft = updateRow(draft, GROWER, {
      kinds: ["hardware", "stock", "phases"],
      rooms: ["room_b_"],
      urgent_high_priority: true,
    });
    draft = { ...draft, recipients: draft.recipients.filter((row) => row.service !== MANAGER) };
    draft = { ...draft, recipients: [...draft.recipients, newRecipient(ASSISTANT, DEMO_PHONES)] };
    draft = { ...draft, idle_hours: 6 };
    const changes = draftChanges(base, draft, {
      kinds: DEMO_KINDS,
      phones: DEMO_PHONES,
      rooms: ROOMS,
    });
    expect(changes.count).toBe(4);
    expect(changes.idle).toEqual({ before: 3, after: 6 });
    expect(changes.phones).toEqual([
      {
        service: GROWER,
        title: "Grower (Phone 2)",
        change: "changed",
        lines: [
          { label: "New alert kinds", before: null, after: "Phase changes" },
          { label: "Removed alert kinds", before: null, after: "Dosing" },
          { label: "Rooms", before: "All rooms", after: "Room B" },
          { label: "Emergencies loud", before: "Off", after: "On" },
        ],
      },
      {
        service: ASSISTANT,
        title: "Assistant (Phone 4)",
        change: "added",
        lines: [
          { label: "Gets", before: null, after: "Emergencies" },
          { label: "Rooms", before: null, after: "All rooms" },
          { label: "Emergencies loud", before: null, after: "On" },
        ],
      },
      {
        service: MANAGER,
        title: "Manager (Phone 3)",
        change: "removed",
        lines: [{ label: "Removed", before: null, after: "no more pushes from Crop Steering" }],
      },
    ]);
    expect(
      draftChanges(base, toDraft(base), { kinds: DEMO_KINDS, phones: DEMO_PHONES, rooms: ROOMS }),
    ).toEqual({
      phones: [],
      idle: null,
      count: 0,
    });
    // The default room's prefix is "": all rooms to that room alone is a change too.
    const defaultRoom = draftChanges(base, updateRow(toDraft(base), MANAGER, { rooms: [""] }), {
      kinds: DEMO_KINDS,
      phones: DEMO_PHONES,
      rooms: ROOMS,
    });
    expect(defaultRoom.phones[0].lines).toEqual([
      { label: "Rooms", before: "All rooms", after: "Room A" },
    ]);
    expect(roomWords(["room_b_", "", "f9_"], ROOMS)).toBe("Room B, Room A, f9_");
  });
});

describe("the demo's notification services", () => {
  const start = (user: string | null = null) => {
    let states: States = {};
    const demo = new NotifyDemo(
      () => states,
      (next) => (states = next),
      user,
    );
    return {
      demo,
      get: () => demo.call("notify_get", {}) as NotifyDocument,
      save: (data: Record<string, unknown>) => demo.call("notify_save", data) as NotifyDocument,
      test: (service: string) => demo.call("notify_test", { service }) as NotifyTestResult,
      sensor: () => states[NOTIFY_CONFIG_ID],
    };
  };
  it("answers as the owner, an administrator, with five phones and three of them listed", () => {
    const { get, sensor } = start();
    const read = parseNotifyDocument(get());
    expect(read).toMatchObject({
      schema_version: 1,
      can_edit_all: true,
      user_id: "demo-user-owner",
    });
    expect(read.kinds.map((kind) => kind.id)).toEqual([
      "emergency",
      "hardware",
      "sensors",
      "watering",
      "phases",
      "vitals",
      "stock",
      "dosing",
      "jev",
      "setup",
    ]);
    expect(read.phones.map(phoneLabel)).toEqual([
      "Owner (Phone 1)",
      "Grower (Phone 2)",
      "Manager (Phone 3)",
      "Assistant (Phone 4)",
      "Visitor (Phone 5)",
    ]);
    expect(read.config.idle_hours).toBe(3);
    expect(read.config.recipients.map((row) => [row.service, row.kinds])).toEqual([
      [OWNER, DEMO_KINDS.map((kind) => kind.id)],
      [GROWER, ["hardware", "stock", "dosing"]],
      [MANAGER, ["emergency"]],
    ]);
    // Emergencies are every critical code (docs/NOTIFICATIONS.md).
    expect(read.kinds[0].codes).toEqual([
      "CS-201",
      "CS-202",
      "CS-203",
      "CS-204",
      "CS-207",
      "CS-211",
      "CS-301",
      "CS-308",
      "CS-310",
      "CS-311",
      "CS-315",
      "CS-402",
      "CS-601",
      "CS-606",
      "CS-801",
      "CS-809",
      "CS-811",
      "CS-901",
      "CS-902",
    ]);
    // The integration's sensor, as the controller reads it.
    expect(sensor()).toMatchObject({ state: "3", attributes: { recipients: 3 } });
  });
  it("covers every code Help lists with at least one kind, as the integration's catalog must", () => {
    const covered = new Set(DEMO_KINDS.flatMap((kind) => kind.codes));
    expect(
      errorCodes.filter((entry) => !covered.has(entry.code)).map((entry) => entry.code),
    ).toEqual([]);
  });
  it("saves against the revision, and refuses one saved meanwhile", () => {
    const { get, save, sensor } = start();
    const draft = updateRow(toDraft(get().config), GROWER, {
      kinds: ["hardware", "stock", "dosing", "phases"],
    });
    const saved = save(savePayload(get(), { ...draft, idle_hours: 4 }));
    expect(saved.error).toBeNull();
    expect(saved.config.revision).toBe(4);
    expect(saved.config.idle_hours).toBe(4);
    expect(saved.config.recipients[1].kinds).toContain("phases");
    expect(sensor()).toMatchObject({ state: "4", attributes: { recipients: 3 } });
    // The same draft again, against revision 3: refused, nothing changed.
    expect(save(savePayload(doc(), draft)).error).toBe("revision");
    expect(get().config.revision).toBe(4);
    expect(save({ expected_revision: 4, recipients: [{ service: "light.x" }] }).error).toMatch(
      /notify service/,
    );
    expect(
      save({ expected_revision: 4, recipients: [{ service: OWNER, kinds: ["weather"] }] }).error,
    ).toBe("weather is not a kind of alert.");
    expect(save({ expected_revision: 4, recipients: [], idle_hours: 13 }).error).toMatch(/1 to 12/);
    // Every phone removed: saved, and the controller falls back to its own notify service.
    expect(save({ expected_revision: 4, recipients: [] }).config.recipients).toEqual([]);
    expect(sensor()).toMatchObject({ state: "5", attributes: { recipients: 0 } });
  });
  it("as the grower, lets them change their own row only, and test only their own phone", () => {
    const { get, save, test } = start("grower");
    const read = get();
    expect(read).toMatchObject({ can_edit_all: false, user_id: "demo-user-grower" });
    const draft = toDraft(read.config);
    const own = updateRow(draft, GROWER, { kinds: ["hardware", "stock", "dosing", "phases"] });
    const other = updateRow(draft, OWNER, { kinds: ["emergency"] });
    expect(save(savePayload(read, other)).error).toMatch(/^not allowed: /);
    expect(
      save(savePayload(read, { ...draft, recipients: draft.recipients.slice(0, 2) })).error,
    ).toMatch(/^not allowed: /);
    expect(save({ ...savePayload(read, draft), idle_hours: 6 }).error).toMatch(/^not allowed: /);
    const saved = save(savePayload(read, own));
    expect(saved.error).toBeNull();
    expect(saved.config.recipients[1].kinds).toContain("phases");
    expect(test(GROWER)).toEqual({ sent: true, error: null });
    expect(test(OWNER)).toMatchObject({
      sent: false,
      error: expect.stringMatching(/^not allowed/),
    });
    expect(test("nonsense")).toMatchObject({ sent: false });
  });
  it("answers as the owner for a name that is no phone's owner", () => {
    expect(start("nobody").get()).toMatchObject({ can_edit_all: true, user_id: "demo-user-owner" });
    expect(start("Owner").get()).toMatchObject({ can_edit_all: true });
  });
  it("is reached through the demo's router, as whoever ?notify-user names", async () => {
    let states = createDemo();
    const router = new OperatorDemo(
      () => states,
      (next) => (states = next),
      null,
      "manager",
    );
    const read = await router.call<NotifyDocument>("notify_get", {});
    expect(read).toMatchObject({ can_edit_all: false, user_id: "demo-user-manager" });
    expect(states[NOTIFY_CONFIG_ID].state).toBe("3");
  });
});

describe("the controller store", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  function browser() {
    const storage = new Map<string, string>();
    vi.stubGlobal("sessionStorage", {
      getItem: (key: string) => storage.get(key) || null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    });
    vi.stubGlobal("window", {
      location: {
        origin: "http://example.test",
        hostname: "example.test",
        href: "http://example.test/",
        search: "",
      },
      history: { replaceState: vi.fn() },
    });
  }
  it("sends the notification services for the whole site; a test push holds nothing up", async () => {
    browser();
    const getStates = vi.spyOn(HaClient.prototype, "states").mockResolvedValue(createDemo());
    const operator = vi
      .spyOn(HaClient.prototype, "operator")
      .mockResolvedValue({ sent: true } as never);
    const store = new ControllerStore(false);
    await store.connect("http://example.test", "test");
    expect(store.getSnapshot().roomId).toBe("room:");
    getStates.mockClear();
    await store.operator("notify_get");
    await store.operator("notify_test", { service: OWNER });
    expect(operator).toHaveBeenNthCalledWith(1, "notify_get", {});
    expect(operator).toHaveBeenNthCalledWith(2, "notify_test", { service: OWNER });
    // Reads and a test push refresh nothing; a save refreshes the states once, like any change.
    expect(getStates).not.toHaveBeenCalled();
    await store.operator("notify_save", { expected_revision: 3, recipients: [] });
    expect(operator).toHaveBeenLastCalledWith("notify_save", {
      expected_revision: 3,
      recipients: [],
    });
    expect(getStates).toHaveBeenCalledTimes(1);
    store.disconnect();
  });
});

describe("quiet hours, mutes, the bottom bar and test pushes (Task 26)", () => {
  const NZ = "Pacific/Auckland";
  afterEach(() => setDisplayUnits({ clock: "24" }));
  it("parse tolerates missing quiet_hours and loud", () => {
    const read = parseNotifyDocument({
      config: {
        revision: 2,
        recipients: [
          { service: "notify.a", urgent_high_priority: true, quiet_hours: { from: "22:00", to: "06:00" } },
          { service: "notify.b" },
          { service: "notify.c", quiet_hours: { from: "7:00", to: "06:00" } },
          { service: "notify.d", quiet_hours: { from: "06:00", to: "06:00" } },
        ],
        mutes: { room_b_: "2026-10-23T03:00:00+00:00", "": "not a time", "F 2": "2026-10-23T03:00:00Z" },
      },
    });
    expect(read.config.recipients.map((row) => [row.service, row.quiet_hours, row.urgent_high_priority])).toEqual([
      ["notify.a", { from: "22:00", to: "06:00" }, true],
      ["notify.b", null, false],
      ["notify.c", null, false],
      ["notify.d", null, false],
    ]);
    expect(read.config.mutes).toEqual({ room_b_: Date.parse("2026-10-23T03:00:00Z") });
    // Quiet hours and mutes are the 3.18 integration's: an answer without `mutes` has neither.
    expect(read.quietAndMutes).toBe(true);
    const old = parseNotifyDocument({ config: { revision: 2, recipients: [{ service: "notify.a" }] } });
    expect(old.quietAndMutes).toBe(false);
    expect(old.config.mutes).toEqual({});
    expect(old.config.recipients[0].quiet_hours).toBeNull();
  });
  it("draftSummary words each change", () => {
    const context = { kinds: DEMO_KINDS, phones: DEMO_PHONES, rooms: ROOMS };
    const saved = DEMO_NOTIFY;
    let draft = updateRow(toDraft(saved), MANAGER, { kinds: ["emergency", "dosing"], rooms: ["room_b_"] });
    expect(draftSummary(draft, saved, context)).toBe(
      "2 changes not applied yet: Manager gets Dosing · Manager: Room B only",
    );
    draft = updateRow(toDraft(saved), GROWER, {
      kinds: ["hardware"],
      urgent_high_priority: true,
      quiet_hours: { from: "22:00", to: "06:00" },
    });
    draft = { ...draft, idle_hours: 4 };
    expect(draftSummary(draft, saved, context)).toBe(
      "4 changes not applied yet: Grower stops getting Stock tanks, Dosing · Grower: emergencies loud · Grower: quiet 22:00–06:00 · Watering stopped after 4 h",
    );
    draft = { ...toDraft(saved), recipients: [...toDraft(saved).recipients.slice(1), newRecipient(ASSISTANT, DEMO_PHONES)] };
    expect(draftSummary(draft, saved, context)).toBe(
      "2 changes not applied yet: Assistant added · Owner removed",
    );
    setDisplayUnits({ clock: "12" });
    const quiet = updateRow(toDraft(saved), OWNER, { quiet_hours: { from: "22:00", to: "06:30" } });
    expect(draftSummary(quiet, saved, context)).toBe(
      "1 change not applied yet: Owner: quiet 10:00 pm–6:30 am",
    );
    expect(draftSummary(toDraft(saved), saved, context)).toBe("");
  });
  it("testLine accepted and failed", () => {
    const at = Date.parse("2026-10-23T00:58:00Z"); // 13:58 in Auckland
    expect(testLine({ sent: true, error: null }, at, NZ)).toBe("Accepted 13:58");
    expect(testLine({ sent: false, error: "notify.x is not a notify service in Home Assistant" }, at, NZ)).toBe(
      "Failed 13:58 · notify.x is not a notify service in Home Assistant",
    );
    expect(testLine({ sent: false, error: null }, at, NZ)).toBe("Failed 13:58 · no reason given");
    setDisplayUnits({ clock: "12" });
    expect(testLine({ sent: true, error: null }, at, NZ)).toBe("Accepted 1:58 pm");
  });
  it("reads a Test all answer, phone by phone", () => {
    expect(
      parseTestResults({
        results: [
          { service: "notify.a", sent: true, error: null },
          { service: "notify.b", sent: false, error: "timed out" },
          { service: "light.x", sent: true },
        ],
      }),
    ).toEqual({
      "notify.a": { sent: true, error: null },
      "notify.b": { sent: false, error: "timed out" },
    });
    expect(parseTestResults({ sent: true })).toBeNull();
  });
  it("draws the union of every phone's quiet hours on the day, across midnight", () => {
    expect(quietSpans([{ from: "22:00", to: "06:00" }, null])).toEqual([
      [0, 360],
      [1320, 1440],
    ]);
    expect(quietSpans([{ from: "22:00", to: "06:00" }, { from: "05:00", to: "07:30" }, { from: "12:00", to: "13:00" }])).toEqual([
      [0, 450],
      [720, 780],
      [1320, 1440],
    ]);
    expect(quietSpans([null])).toEqual([]);
    expect(spanMinutes(quietSpans([{ from: "22:00", to: "06:00" }]))).toBe(480);
    // Lights on 18:00 to 06:00 crosses midnight too.
    expect(lightSpans(18, 6)).toEqual([
      [0, 360],
      [1080, 1440],
    ]);
    expect(lightSpans(6, 18)).toEqual([[360, 1080]]);
    expect(lightSpans(Number.NaN, 18)).toEqual([]);
  });
  it("presses a room chip: every room shows each chip on, and the last room off is every room again", () => {
    const all = ["", "room_b_"];
    expect(pressRoom([], "room_b_", all)).toEqual([""]);
    expect(pressRoom([""], "room_b_", all)).toEqual([]);
    expect(pressRoom([""], "", all)).toEqual([]);
    expect(pressRoom(["room_b_"], "", all)).toEqual([]);
    expect(roomChipWords([], ROOMS)).toBe("every room");
    expect(roomChipWords(["room_b_"], ROOMS)).toBe("Room B only");
  });
  it("saves quiet hours on a 3.18 setup only, and mutes are a save of their own", () => {
    const d = doc({ quietAndMutes: true });
    const draft = updateRow(toDraft(d.config), OWNER, { quiet_hours: { from: "22:00", to: "06:00" } });
    const sent = savePayload(d, draft).recipients as Record<string, unknown>[];
    expect(sent[0].quiet_hours).toEqual({ from: "22:00", to: "06:00" });
    expect(sent[1].quiet_hours).toBeNull();
    expect((savePayload(doc(), draft).recipients as Record<string, unknown>[])[0]).not.toHaveProperty("quiet_hours");
    const until = Date.parse("2026-10-23T03:00:00Z");
    expect(mutePayload(d, { room_b_: until })).toEqual({
      expected_revision: 3,
      recipients: savePayload(d, toDraft(d.config)).recipients,
      mutes: { room_b_: "2026-10-23T03:00:00.000Z" },
    });
    expect(draftErrors(updateRow(toDraft(d.config), OWNER, { quiet_hours: { from: "06:00", to: "06:00" } }))).toEqual([
      "Quiet hours need a start and an end that differ.",
    ]);
  });
});

describe("mutes and the save's receipt (Task 26)", () => {
  const NZ = "Pacific/Auckland";
  it("words when a mute ends and checks the one read back", () => {
    const now = Date.parse("2026-10-23T01:00:00Z"); // 14:00 Friday in Auckland
    expect(muteEndWords(Date.parse("2026-10-23T03:00:00Z"), now, NZ)).toBe("16:00");
    expect(muteEndWords(Date.parse("2026-10-23T19:00:00Z"), now, NZ)).toBe("08:00 tomorrow");
    expect(muteEndWords(Date.parse("2026-10-25T19:00:00Z"), now, NZ)).toBe("08:00 Mon 26 Oct");
    expect(sameMuteEnd(now + 400, now)).toBe(true);
    expect(sameMuteEnd(undefined, now)).toBe(false);
    expect(sameMuteEnd(undefined, null)).toBe(true);
    expect(sameMuteEnd(now, null)).toBe(false);
  });
  it("claims a row written and read back only when its phone reads back as sent", () => {
    const saved = DEMO_NOTIFY;
    const draft = { ...updateRow(toDraft(saved), MANAGER, { kinds: ["emergency", "dosing"] }), idle_hours: 4 };
    const changes = draftChanges(saved, draft, { kinds: DEMO_KINDS, phones: DEMO_PHONES, rooms: ROOMS });
    const rows = reviewRows(changes);
    expect(rows.map((row) => [row.key, row.label, row.before, row.after])).toEqual([
      [MANAGER, "Manager (Phone 3): New alert kinds", "—", "Dosing"],
      ["idle", "Watering stopped after", "3 h", "4 h"],
    ]);
    const at = 1;
    const all = saveReceipt(rows, draft, { ...saved, ...draft, revision: 4 }, at);
    expect(all).toMatchObject({ ok: true, summary: "Manager (Phone 3): New alert kinds — → Dosing · Watering stopped after 3 h → 4 h" });
    expect(all).not.toHaveProperty("notConfirmed");
    // The integration kept the old threshold: that row is not confirmed, the phone's still is.
    const part = saveReceipt(rows, draft, { ...saved, recipients: draft.recipients, revision: 4 }, at);
    expect(part).toMatchObject({ ok: false, notConfirmed: ["idle"] });
    expect(part.summary).toBe("Manager (Phone 3): New alert kinds — → Dosing");
  });
});

describe("Task 26 review round 1", () => {
  it("refuses quiet hours that are not HH:MM", () => {
    const draft = updateRow(toDraft(DEMO_NOTIFY), MANAGER, { quiet_hours: { from: "", to: "06:00" } });
    expect(draftErrors(draft)).toEqual(["Quiet hours need a start and an end as HH:MM."]);
  });
  it("reads a row back as sent after the integration trims and cuts its name and fills its user", () => {
    const long = "  A very long phone name that goes on past forty letters  ";
    const draft = {
      ...toDraft(DEMO_NOTIFY),
      recipients: [...DEMO_NOTIFY.recipients, recipient("notify.mobile_app_new", ["emergency"], { name: long })],
    };
    const rows = reviewRows(draftChanges(DEMO_NOTIFY, draft, { kinds: DEMO_KINDS, phones: DEMO_PHONES, rooms: ROOMS }));
    const back = {
      ...DEMO_NOTIFY,
      revision: 4,
      recipients: [
        ...DEMO_NOTIFY.recipients,
        recipient("notify.mobile_app_new", ["emergency"], { name: long.trim().slice(0, 40), user_id: "u-new" }),
      ],
    };
    expect(saveReceipt(rows, draft, back, 1)).toMatchObject({ ok: true });
    // A different name than the one sent is still not confirmed.
    const other = {
      ...back,
      recipients: [...DEMO_NOTIFY.recipients, recipient("notify.mobile_app_new", ["emergency"], { name: "Else" })],
    };
    expect(saveReceipt(rows, draft, other, 1).ok).toBe(false);
  });
  it("tests every phone in one call on 3.18 and shows its error on each phone, never a second push", async () => {
    const call = vi.fn(async () => {
      throw new Error("timed out");
    });
    expect(await testPhones(["notify.a", "notify.b"], true, call)).toEqual({
      "notify.a": { sent: false, error: "timed out" },
      "notify.b": { sent: false, error: "timed out" },
    });
    expect(call).toHaveBeenCalledTimes(1);
  });
  it("tests phone by phone on 3.17, or when the integration refuses services", async () => {
    const one = vi.fn(async (data: Record<string, unknown>) => {
      if ("services" in data) throw new Error("extra keys not allowed @ data['services']");
      return { sent: true, error: null };
    });
    const ok = { sent: true, error: null };
    expect(await testPhones(["notify.a", "notify.b"], false, one)).toEqual({ "notify.a": ok, "notify.b": ok });
    expect(one).toHaveBeenCalledTimes(2);
    one.mockClear();
    expect(await testPhones(["notify.a", "notify.b"], true, one)).toEqual({ "notify.a": ok, "notify.b": ok });
    expect(one).toHaveBeenCalledTimes(3);
    const many = vi.fn(async () => ({ results: [{ service: "notify.a", sent: true, error: null }] }));
    expect(await testPhones(["notify.a", "notify.b"], true, many)).toEqual({
      "notify.a": ok,
      "notify.b": { sent: false, error: "No answer for this phone." },
    });
  });
});
