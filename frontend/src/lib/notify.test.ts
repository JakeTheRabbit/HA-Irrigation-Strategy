import { afterEach, describe, expect, it, vi } from "vitest";
import { HaClient } from "./client";
import { createDemo } from "./demo";
import { errorCodes } from "./error-codes";
import {
  NOTIFY_CONFIG_ID,
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
  rebaseDraft,
  roomWords,
  roomsWithoutEmergencies,
  rowLabel,
  sameDraft,
  savePayload,
  serviceFromText,
  toDraft,
  toggleKind,
  toggleRoom,
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
  { id: "room:", prefix: "", name: "Flower 2" },
  { id: "room:f1_", prefix: "f1_", name: "Flower 1" },
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
  ...change,
});
const config = (recipients: NotifyRecipient[], revision = 3, idle_hours = 3): NotifyConfig => ({
  revision,
  idle_hours,
  recipients,
});
const doc = (change: Partial<NotifyDocument> = {}): NotifyDocument => ({
  schema_version: 1,
  config: structuredClone(DEMO_NOTIFY),
  kinds: DEMO_KINDS,
  phones: DEMO_PHONES,
  can_edit_all: true,
  user_id: "demo-user-ben",
  error: null,
  ...change,
});
const BEN = "notify.mobile_app_s23ultra";
const CALLUM = "notify.mobile_app_callum_phone";
const STEWART = "notify.mobile_app_stews_iphone";
const SEAN = "notify.mobile_app_sean_iphone";

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
            name: "Callum's phone",
            user_id: "7f21",
            kinds: ["stock", "dosing"],
            rooms: ["f1_"],
            urgent_high_priority: true,
          },
        ],
      },
      kinds: [
        {
          id: "jev",
          name: "Jev",
          detail: "Jev's advice",
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
            name: "Callum's phone",
            user_id: "7f21",
            kinds: ["stock", "dosing"],
            rooms: ["f1_"],
            urgent_high_priority: true,
          },
        ],
      },
      kinds: [
        {
          id: "jev",
          name: "Jev",
          detail: "Jev's advice",
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
    });
  });
  it("falls back on anything missing or garbled, and never grants editing it cannot read", () => {
    const read = parseNotifyDocument({
      config: {
        revision: "5",
        idle_hours: "40",
        recipients: [
          { service: "notify.a", kinds: ["emergency", "emergency", 3], rooms: ["", "f1_", "F 2"] },
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
          rooms: ["", "f1_"],
          urgent_high_priority: false,
        },
      ],
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
      config: { revision: 0, idle_hours: 3, recipients: [] },
      kinds: [],
      phones: [],
      can_edit_all: false,
      user_id: null,
      error: null,
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
    expect(notifyError("not allowed: that phone is Ben's")).toBe(
      "Home Assistant did not allow this: that phone is Ben's. An administrator can change every phone; anyone else, only their own phone's ticks.",
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
    expect(rowLabel(recipient(BEN, []), DEMO_PHONES)).toEqual({
      title: "Ben",
      subtitle: "S23Ultra",
      name: "Ben (S23Ultra)",
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
      title: "Plumbing and switches disagree, not watering",
    });
    expect(watering.codes.find((item) => item.code === "CS-209")).toEqual({
      code: "CS-209",
      title: "No watering for a while",
    });
    expect(kindCoverage(DEMO_KINDS.find((kind) => kind.id === "phases")!).events).toEqual([
      "a zone changing phase",
    ]);
    expect(kindCoverage(DEMO_KINDS.find((kind) => kind.id === "jev")!).events).toEqual([
      "Jev moving a setting",
    ]);
    expect(
      kindCoverage({ id: "z", name: "Z", detail: "", codes: [], events: ["tank_refill"] }).events,
    ).toEqual(["tank refill"]);
  });
});

describe("the draft", () => {
  it("is the same setup whatever order the ticks were made and the rows listed in", () => {
    const a = toDraft(config([recipient(BEN, ["stock", "dosing"], { rooms: ["f1_", ""] })]));
    const b = toDraft(config([recipient(BEN, ["dosing", "stock"], { rooms: ["", "f1_"] })]));
    expect(sameDraft(a, b)).toBe(true);
    expect(sameDraft(a, { ...a, idle_hours: 4 })).toBe(false);
    expect(sameDraft(a, updateRow(a, BEN, { urgent_high_priority: false }))).toBe(false);
    // A row removed and added again as it was is no change.
    const two = toDraft(config([recipient(BEN, ["emergency"]), recipient(STEWART, ["emergency"])]));
    expect(sameDraft(two, { ...two, recipients: [...two.recipients].reverse() })).toBe(true);
    expect(sameDraft(two, { ...two, recipients: [two.recipients[0]] })).toBe(false);
    // A copy: editing the draft leaves the saved setup as it was.
    const saved = config([recipient(BEN, ["stock"])]);
    toDraft(saved).recipients[0].kinds.push("dosing");
    expect(saved.recipients[0].kinds).toEqual(["stock"]);
  });
  it("ticks and unticks a kind, and presses a room chip", () => {
    expect(toggleKind(["stock"], "dosing", true)).toEqual(["stock", "dosing"]);
    expect(toggleKind(["stock", "dosing"], "dosing", true)).toEqual(["stock", "dosing"]);
    expect(toggleKind(["stock", "dosing"], "stock", false)).toEqual(["dosing"]);
    // All covers every room; a room chip from All covers that room only.
    expect(toggleRoom(["f1_"], null)).toEqual([]);
    expect(toggleRoom([], "f1_")).toEqual(["f1_"]);
    expect(toggleRoom(["f1_"], "")).toEqual(["f1_", ""]);
    expect(toggleRoom(["f1_", ""], "f1_")).toEqual([""]);
    // The last room taken out covers every room again: a row covers at least one.
    expect(toggleRoom([""], "")).toEqual([]);
  });
  it("adds a phone with Emergencies ticked for every room, from the site's phones or by name", () => {
    expect(newRecipient(SEAN, DEMO_PHONES)).toEqual({
      service: SEAN,
      name: "Sean iPhone",
      user_id: "demo-user-sean",
      kinds: ["emergency"],
      rooms: [],
      urgent_high_priority: true,
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
      "Sean",
      "Pete",
    ]);
  });
  it("finds each room nobody gets emergencies for", () => {
    const draft = (recipients: NotifyRecipient[]) => toDraft(config(recipients));
    expect(roomsWithoutEmergencies(toDraft(DEMO_NOTIFY), ROOMS)).toEqual([]);
    expect(
      roomsWithoutEmergencies(draft([recipient(BEN, ["emergency"], { rooms: [""] })]), ROOMS),
    ).toEqual([ROOMS[1]]);
    expect(
      roomsWithoutEmergencies(
        draft([
          recipient(BEN, ["stock"]),
          recipient(CALLUM, ["emergency"], { rooms: ["f1_"] }),
          recipient(STEWART, ["emergency"], { rooms: [""] }),
        ]),
        ROOMS,
      ),
    ).toEqual([]);
    expect(roomsWithoutEmergencies(draft([recipient(BEN, ["stock"])]), ROOMS)).toEqual(ROOMS);
  });
  it("checks the threshold as the integration does", () => {
    const draft = toDraft(DEMO_NOTIFY);
    expect(draftErrors(draft)).toEqual([]);
    for (const hours of [0, 13, 2.5, Number.NaN])
      expect(draftErrors({ ...draft, idle_hours: hours })).toEqual([
        "Watering stopped needs 1 to 12 whole hours.",
      ]);
  });
});

describe("saving", () => {
  it("sends every row against the revision it was read at, the threshold only as an administrator", () => {
    const draft = toDraft(
      config([
        recipient(CALLUM, ["dosing", "phases", "stock", "unknown"], {
          user_id: "demo-user-callum",
          rooms: ["f1_"],
        }),
        recipient("notify.family", ["emergency"]),
      ]),
    );
    const payload = savePayload(doc(), { ...draft, idle_hours: 5 });
    expect(payload).toEqual({
      expected_revision: 3,
      recipients: [
        {
          service: CALLUM,
          name: "callum_phone",
          user_id: "demo-user-callum",
          kinds: ["phases", "stock", "dosing", "unknown"],
          rooms: ["f1_"],
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
      recipient(BEN, ["emergency", "stock"]),
      recipient(CALLUM, ["hardware"]),
      recipient(STEWART, ["emergency"]),
      recipient("notify.gone", ["stock"]),
    ]);
    // This draft: Callum ticks phases, Stewart is removed, Sean is added, the threshold is 5.
    const draft: ReturnType<typeof toDraft> = {
      idle_hours: 5,
      recipients: [
        recipient(BEN, ["emergency", "stock"]),
        recipient(CALLUM, ["hardware", "phases"]),
        recipient("notify.gone", ["stock", "dosing"]),
        recipient(SEAN, ["emergency"]),
      ],
    };
    // Elsewhere: Ben's rooms and high priority, Callum's rooms, a new family group; "gone" removed.
    const after = config(
      [
        recipient(BEN, ["emergency", "stock"], { rooms: ["f1_"], urgent_high_priority: false }),
        recipient(CALLUM, ["hardware"], { rooms: [""] }),
        recipient(STEWART, ["emergency"]),
        recipient("notify.family", ["emergency"]),
      ],
      4,
      3,
    );
    const rebased = rebaseDraft(before, draft, after);
    expect(rebased.idle_hours).toBe(5);
    expect(rebased.recipients).toEqual([
      recipient(BEN, ["emergency", "stock"], { rooms: ["f1_"], urgent_high_priority: false }),
      recipient(CALLUM, ["hardware", "phases"], { rooms: [""] }),
      recipient("notify.family", ["emergency"]),
      // Changed here, removed elsewhere: kept, so the review shows it as added.
      recipient("notify.gone", ["stock", "dosing"]),
      recipient(SEAN, ["emergency"]),
    ]);
    // A row removed elsewhere that this draft did not touch goes with it.
    const untouched = rebaseDraft(before, toDraft(before), after);
    expect(untouched.recipients.map((row) => row.service)).toEqual([
      BEN,
      CALLUM,
      STEWART,
      "notify.family",
    ]);
    expect(untouched.idle_hours).toBe(3);
  });
  it("keeps the page's state: a draft back to what is saved is none, and a re-read rebases it", () => {
    const first = doc();
    let state = notifyReducer({ doc: null, draft: null }, { type: "loaded", doc: first });
    expect(state).toEqual({ doc: first, draft: null });
    const tick = (on: boolean) => ({
      type: "edit" as const,
      edit: (draft: ReturnType<typeof toDraft>) =>
        updateRow(draft, CALLUM, {
          kinds: toggleKind(draft.recipients[1].kinds, "phases", on),
        }),
    });
    state = notifyReducer(state, tick(true));
    expect(state.draft!.recipients[1].kinds).toEqual(["hardware", "stock", "dosing", "phases"]);
    expect(notifyReducer(state, tick(false)).draft).toBeNull();
    expect(notifyReducer(state, { type: "discard" }).draft).toBeNull();
    // Saved elsewhere: Stewart gets stock tanks too. The draft stays on top of it.
    const elsewhere = doc({
      config: {
        ...first.config,
        revision: 4,
        recipients: first.config.recipients.map((row) =>
          row.service === STEWART ? { ...row, kinds: ["emergency", "stock"] } : row,
        ),
      },
    });
    const reread = notifyReducer(state, { type: "loaded", doc: elsewhere });
    expect(reread.doc).toBe(elsewhere);
    expect(reread.draft!.recipients[1].kinds).toContain("phases");
    expect(reread.draft!.recipients[2].kinds).toEqual(["emergency", "stock"]);
    // The same change saved elsewhere leaves nothing to save.
    const same = doc({ config: { ...toDraft(first.config), ...state.draft!, revision: 4 } });
    expect(notifyReducer(state, { type: "loaded", doc: same }).draft).toBeNull();
    expect(notifyReducer(state, { type: "saved", doc: same })).toEqual({ doc: same, draft: null });
    // Nothing read yet: nothing to edit.
    expect(notifyReducer({ doc: null, draft: null }, tick(true))).toEqual({
      doc: null,
      draft: null,
    });
  });
  it("lists what a save changes, phone by phone", () => {
    const base = DEMO_NOTIFY;
    let draft = toDraft(base);
    draft = updateRow(draft, CALLUM, {
      kinds: ["hardware", "stock", "phases"],
      rooms: ["f1_"],
      urgent_high_priority: true,
    });
    draft = { ...draft, recipients: draft.recipients.filter((row) => row.service !== STEWART) };
    draft = { ...draft, recipients: [...draft.recipients, newRecipient(SEAN, DEMO_PHONES)] };
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
        service: CALLUM,
        title: "Callum (Callum Phone)",
        change: "changed",
        lines: [
          { label: "Starts getting", before: null, after: "Phase changes" },
          { label: "Stops getting", before: null, after: "Dosing" },
          { label: "Rooms", before: "All rooms", after: "Flower 1" },
          { label: "High priority for emergencies", before: "Off", after: "On" },
        ],
      },
      {
        service: SEAN,
        title: "Sean (Sean iPhone)",
        change: "added",
        lines: [
          { label: "Gets", before: null, after: "Emergencies" },
          { label: "Rooms", before: null, after: "All rooms" },
          { label: "High priority for emergencies", before: null, after: "On" },
        ],
      },
      {
        service: STEWART,
        title: "Stewart (Stews iPhone)",
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
    const defaultRoom = draftChanges(base, updateRow(toDraft(base), STEWART, { rooms: [""] }), {
      kinds: DEMO_KINDS,
      phones: DEMO_PHONES,
      rooms: ROOMS,
    });
    expect(defaultRoom.phones[0].lines).toEqual([
      { label: "Rooms", before: "All rooms", after: "Flower 2" },
    ]);
    expect(roomWords(["f1_", "", "f9_"], ROOMS)).toBe("Flower 1, Flower 2, f9_");
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
  it("answers as Ben, an administrator, with five phones and three of them listed", () => {
    const { get, sensor } = start();
    const read = parseNotifyDocument(get());
    expect(read).toMatchObject({ schema_version: 1, can_edit_all: true, user_id: "demo-user-ben" });
    expect(read.kinds.map((kind) => kind.id)).toEqual([
      "emergency",
      "hardware",
      "sensors",
      "watering",
      "phases",
      "stock",
      "dosing",
      "jev",
      "setup",
    ]);
    expect(read.phones.map(phoneLabel)).toEqual([
      "Ben (S23Ultra)",
      "Callum (Callum Phone)",
      "Stewart (Stews iPhone)",
      "Sean (Sean iPhone)",
      "Pete (Pete)",
    ]);
    expect(read.config.idle_hours).toBe(3);
    expect(read.config.recipients.map((row) => [row.service, row.kinds])).toEqual([
      [BEN, DEMO_KINDS.map((kind) => kind.id)],
      [CALLUM, ["hardware", "stock", "dosing"]],
      [STEWART, ["emergency"]],
    ]);
    // Emergencies are every critical code (docs/NOTIFICATIONS.md).
    expect(read.kinds[0].codes).toEqual([
      "CS-201",
      "CS-202",
      "CS-203",
      "CS-204",
      "CS-207",
      "CS-301",
      "CS-308",
      "CS-310",
      "CS-311",
      "CS-402",
      "CS-601",
      "CS-606",
      "CS-801",
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
    const draft = updateRow(toDraft(get().config), CALLUM, {
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
      save({ expected_revision: 4, recipients: [{ service: BEN, kinds: ["weather"] }] }).error,
    ).toBe("weather is not a kind of alert.");
    expect(save({ expected_revision: 4, recipients: [], idle_hours: 13 }).error).toMatch(/1 to 12/);
    // Every phone removed: saved, and the controller falls back to its own notify service.
    expect(save({ expected_revision: 4, recipients: [] }).config.recipients).toEqual([]);
    expect(sensor()).toMatchObject({ state: "5", attributes: { recipients: 0 } });
  });
  it("as Callum, lets him change his own row only, and test only his own phone", () => {
    const { get, save, test } = start("callum");
    const read = get();
    expect(read).toMatchObject({ can_edit_all: false, user_id: "demo-user-callum" });
    const draft = toDraft(read.config);
    const own = updateRow(draft, CALLUM, { kinds: ["hardware", "stock", "dosing", "phases"] });
    const other = updateRow(draft, BEN, { kinds: ["emergency"] });
    expect(save(savePayload(read, other)).error).toMatch(/^not allowed: /);
    expect(
      save(savePayload(read, { ...draft, recipients: draft.recipients.slice(0, 2) })).error,
    ).toMatch(/^not allowed: /);
    expect(save({ ...savePayload(read, draft), idle_hours: 6 }).error).toMatch(/^not allowed: /);
    const saved = save(savePayload(read, own));
    expect(saved.error).toBeNull();
    expect(saved.config.recipients[1].kinds).toContain("phases");
    expect(test(CALLUM)).toEqual({ sent: true, error: null });
    expect(test(BEN)).toMatchObject({ sent: false, error: expect.stringMatching(/^not allowed/) });
    expect(test("nonsense")).toMatchObject({ sent: false });
  });
  it("answers as Ben for a name that is no phone's owner", () => {
    expect(start("nobody").get()).toMatchObject({ can_edit_all: true, user_id: "demo-user-ben" });
    expect(start("Ben").get()).toMatchObject({ can_edit_all: true });
  });
  it("is reached through the demo's router, as whoever ?notify-user names", async () => {
    let states = createDemo();
    const router = new OperatorDemo(
      () => states,
      (next) => (states = next),
      null,
      "stewart",
    );
    const read = await router.call<NotifyDocument>("notify_get", {});
    expect(read).toMatchObject({ can_edit_all: false, user_id: "demo-user-stewart" });
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
    await store.operator("notify_test", { service: BEN });
    expect(operator).toHaveBeenNthCalledWith(1, "notify_get", {});
    expect(operator).toHaveBeenNthCalledWith(2, "notify_test", { service: BEN });
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
