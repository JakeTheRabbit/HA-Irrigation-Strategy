import { liveSensorStatistics } from "./live";
import { demoDisplay } from "./display";
import type { DailyRanges, HistoryRequest, HistoryWindow, RunsDocument } from "./comparison-types";
import { demoHistoryWindow } from "./comparison-demo";
import type { TimelineRequest } from "./day-timeline";
import { explorerSensors } from "./history-explorer";
import type { OperatorAction } from "./operator-types";
import { OperatorDemo } from "./operator-demo";
import { demoJournalVwc } from "./parity-demo/journal";
import { demoParityStatus, demoShotTable } from "./parity-demo/status";
import { JournalMissing, mergeEvents, startEventFeed } from "./events";
import { isParityAction, pagedQuery } from "./parity-api";
import type { CsEvent } from "./parity-types";
import { useEffect, useRef, useSyncExternalStore } from "react";
import type { Change, Controller, EntityState, States, WriteResult } from "./types";
import {
  applyChanges,
  asStates,
  findSession,
  HaClient,
  haSessionToken,
  haTimeZone,
  type HassSession,
} from "./client";
import {
  buildRoom,
  descriptor,
  discoverRooms,
  emptyRoom,
  numeric,
  resolveRequestedRoom,
  validateChange,
} from "./model";
import {
  createDemo,
  demoBackend,
  demoBeat,
  demoClock,
  demoDay,
  demoHistory,
  demoReact,
  demoWaterRecord,
  isDemoLocation,
} from "./demo";
import {
  applyEntityUpdate,
  liveConnection,
  liveDailyStatistics,
  liveHistory,
  liveStatistics,
  watchedEntities,
  whileVisible,
  type EntityUpdate,
  type LiveConnection,
} from "./live";
import { roomProbeIds } from "./probes";
import { TANK_KEYS } from "./tank-level";
import { historySamples, type WaterRecord, type WaterRecordRequest } from "./water-use";

type Listener = () => void;
/** v2 services that take one `room_id` (backend plan); the others are site-wide, all-rooms or
 * keyed by a session or event id. */
const PARITY_ROOM_DEFAULT = new Set<string>([
  "journal_query",
  "pump_precheck",
  "pump_prime",
  "pump_stop",
  "pump_calibrate",
  "pump_calibration_commit",
  "calibration_start",
  "calibration_revert",
  "probe_offset_set",
  "alert_ack",
  "timer_program_set",
  "timer_program_delete",
  "timer_program_preview",
  "timer_skip",
]);
/** v2 services whose `preview: true` dry run writes nothing (backend Tasks 11, 21, 22). No other
 * service's `preview` key skips the write lock. */
const PREVIEWABLE = new Set<string>(["preset_apply", "copy_config", "probe_offset_set", "supply_save"]);
/** v2 services that change nothing: kept out of the one-write-at-a-time lock. `pump_stop` is
 * here too: it ends a while-held prime and must never be refused behind another write. */
const PARITY_READS = new Set<string>([
  "journal_query",
  "timeline_get",
  "timeline_summary",
  "history_changes",
  "supply_get",
  "timer_program_list",
  "timer_program_preview",
  "alert_rule_list",
  "alert_rule_preview",
  "pump_precheck",
  "calibration_status",
  "preset_list",
  "dashboard_list",
  "system_status_get",
  "pump_stop",
]);
const SESSION_KEY = "crop-steering-connection-tab";
/** Whether Home Assistant's signed-in user is an administrator; null when this page cannot tell
 * (a standalone tab with a token). */
const adminOf = (session?: HassSession) =>
  typeof session?.user?.is_admin === "boolean" ? session.user.is_admin : null;
export class ControllerStore {
  private listeners = new Set<Listener>();
  private client: HaClient | null = null;
  private generation = 0;
  private requestId = 0;
  private stopTimer?: () => void;
  /** Home Assistant's own websocket, when this page runs inside Home Assistant. */
  private live: LiveConnection | null = null;
  private liveToken = 0;
  /** Ends the current subscription; set while one is open or opening. */
  private dropLive?: () => void;
  /** Every entity id subscribed so far on this connection. */
  private watched = new Set<string>();
  private offlineTicks = 0;
  private publishTimer?: ReturnType<typeof setTimeout>;
  private states: States;
  private roomId = "";
  private connection: Controller["connection"];
  private error: string | null = null;
  private updated: number | null = null;
  private writing = false;
  private admin: boolean | null = null;
  private timeZone = haTimeZone();
  /** The connection whose Home Assistant time zone has been asked for. */
  private zoneOf?: HaClient;
  readonly demo: boolean;
  private snapshot!: Controller;
  private operatorDemo?: OperatorDemo;
  private runDocuments = new Map<string, { generation: number; document: RunsDocument }>();
  private historyAborters = new Set<AbortController>();
  /** The live event feed (Controller.recentEvents), over the rooms in `feedRooms`; `feedSince`
   * keeps each room's last event time when the room set changes. */
  private stopFeed?: () => void;
  private feedRooms = "";
  private feedSince = new Map<string, string>();
  private recentEvents: readonly CsEvent[] = [];
  constructor(
    demo = typeof window !== "undefined" && isDemoLocation(window.location),
    /** The page's query (tests pass their own). */
    query: string | null = typeof window !== "undefined" ? window.location.search : null,
  ) {
    this.demo = demo;
    this.admin = demo ? true : null;
    this.states = demo ? demoClock(createDemo()) : {};
    this.connection = demo ? "demo" : "connecting";
    const search = query === null ? null : new URLSearchParams(query);
    // ?display=show_climate,today_tank_readout (or all): those display options on in the demo.
    if (demo) this.states = demoDisplay(this.states, search?.get("display") ?? null);
    // The 3.18 room entities (grow day, pump queue, open alerts...); an older integration has none.
    if (demo && demoBackend(query ?? "") === "3.18") this.states = demoParityStatus(this.states, Date.now());
    // An older integration has no Journal: its shot table instead.
    else if (demo) this.states = demoShotTable(this.states, Date.now());
    if (demo)
      this.operatorDemo = new OperatorDemo(
        () => this.states,
        (states) => {
          this.states = states;
          if (this.roomId && !discoverRooms(states).some((room) => room.id === this.roomId)) {
            this.roomId = "";
            this.error = "This room is archived. Select an available room.";
          }
          this.publish();
        },
        // ?whats-new=2.22.0: the demo as an installation updated from 2.22.0, ?whats-new=unknown
        // from one running before What's new existed. Otherwise it has nothing new to show.
        search?.get("whats-new") ?? null,
        // ?notify-user=grower: Settings & help › Notifications as that phone's owner, who is not an
        // administrator.
        search?.get("notify-user") ?? null,
        // ?backend=3.17: an integration without the parity (v2) services.
        demoBackend(query ?? ""),
      );
    const requested = search?.get("room") ?? null;
    const rooms = discoverRooms(this.states);
    this.roomId =
      resolveRequestedRoom(rooms, requested)?.id || (requested === null ? rooms[0]?.id : "") || "";
    if (demo && requested !== null && !this.roomId)
      this.error = `Requested room "${requested}" is unavailable. Select an available room.`;
    if (demo) this.updated = Date.now();
    this.publish();
  }
  subscribe = (listener: Listener) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  getSnapshot = () => this.snapshot;
  private publish() {
    const rooms = discoverRooms(this.states);
    const room = rooms.find((r) => r.id === this.roomId) || emptyRoom;
    this.snapshot = {
      demo: this.demo,
      admin: this.admin,
      connection: this.connection,
      timeZone: this.timeZone,
      error: this.error,
      lastUpdated: this.updated,
      roomId: this.roomId,
      rooms,
      room: buildRoom(this.states, room),
      states: this.states,
      refresh: this.refresh,
      changeRoom: this.changeRoom,
      connect: this.connect,
      disconnect: this.disconnect,
      write: this.write,
      history: this.history,
      historyWindow: this.historyWindow,
      dailyRanges: this.dailyRanges,
      sensorStatistics: this.sensorStatistics,
      timeline: this.timeline,
      waterRecord: this.waterRecord,
      operator: this.operator,
      recentEvents: this.recentEvents,
    };
    this.listeners.forEach((listener) => listener());
  }
  start = () => {
    if (!this.demo && !this.client) {
      let saved: { base?: string; token?: string } = {};
      try {
        saved = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "{}");
      } catch {
        /* no storage */
      }
      const base =
        saved.base || (typeof window !== "undefined" ? window.location.origin : "http://localhost");
      const session = saved.token ? undefined : findSession(base);
      this.admin = adminOf(session);
      this.timeZone = haTimeZone(session?.config);
      const inheritedToken =
        typeof window !== "undefined" && base === window.location.origin ? haSessionToken() : "";
      try {
        this.client = new HaClient(base, saved.token || inheritedToken, session);
        this.live = liveConnection(session);
        void this.refresh();
      } catch (error) {
        this.connection = "offline";
        this.error = message(error);
        this.publish();
      }
    }
    this.stopTimer ??= whileVisible(this.tick, 30_000);
    this.startFeed();
    if (typeof window !== "undefined") window.addEventListener?.("pagehide", this.unsubscribe);
    return this.stop;
  };
  stop = () => {
    this.stopTimer?.();
    this.stopTimer = undefined;
    if (typeof window !== "undefined") window.removeEventListener?.("pagehide", this.unsubscribe);
    this.unsubscribe();
    this.endFeed();
    clearTimeout(this.publishTimer);
    this.publishTimer = undefined;
    this.historyAborters.forEach((abort) => abort.abort());
    this.historyAborters.clear();
    this.generation++;
    this.client?.dispose();
    this.client = null;
  };
  refresh = async () => {
    if (this.demo) {
      this.updated = Date.now();
      this.states = demoClock(demoBeat(this.states, this.updated), this.updated);
      this.publish();
      return;
    }
    const client = this.client;
    if (!client) return;
    const generation = this.generation;
    const request = ++this.requestId;
    try {
      // The full download: discovery, and the standalone poll. Inside Home Assistant it runs once
      // (and after a reconnect); the subscription keeps it current from there.
      const states = await client.states();
      if (generation !== this.generation || request !== this.requestId) return;
      this.states = states;
      this.settle();
      if (this.live) this.subscribeLive(this.live);
      this.startFeed();
      if (this.zoneOf !== client) void this.readTimeZone(client);
    } catch (error) {
      if (generation !== this.generation || request !== this.requestId) return;
      this.connection = "offline";
      this.error = message(error);
    }
    this.publish();
  };
  /** Home Assistant's time zone, once per connection (again at the next refresh if it fails). */
  private async readTimeZone(client: HaClient) {
    this.zoneOf = client;
    try {
      const zone = await client.timeZone();
      if (client !== this.client || zone === this.timeZone) return;
      this.timeZone = zone;
      this.publish();
    } catch {
      if (client === this.client) this.zoneOf = undefined;
    }
  }
  /** New states arrived: keep the selected room (or pick the requested or first one). */
  private settle() {
    const rooms = discoverRooms(this.states);
    const requested = new URLSearchParams(window.location.search).get("room");
    if (!rooms.some((r) => r.id === this.roomId)) {
      this.roomId =
        resolveRequestedRoom(rooms, requested)?.id ||
        (requested === null ? rooms[0]?.id : "") ||
        "";
    }
    this.connection = "live";
    this.error =
      requested !== null && !this.roomId
        ? `Requested room "${requested}" is unavailable. Select an available room.`
        : rooms.length
          ? null
          : "Connected, but no crop-steering room descriptors were discovered.";
    this.updated = Date.now();
  }
  /** Every 30 s while the page is visible. Standalone: poll. Live: nothing to download; re-derive
   * what depends on the clock, and report a websocket that stays down. */
  private tick = () => {
    if (this.demo || !this.dropLive) return void this.refresh();
    if (this.live?.connected === false) {
      // Home Assistant drops its socket while a tab is hidden and reconnects when it is shown,
      // so only a second disconnected tick in a row counts.
      if (++this.offlineTicks > 1 && this.connection === "live") {
        this.connection = "offline";
        this.error =
          "Live updates from Home Assistant stopped. Values shown are the last received.";
      }
    } else {
      this.offlineTicks = 0;
      if (this.connection === "offline") return void this.refresh();
      this.updated = Date.now();
    }
    this.publish();
  };
  /** Subscribes to every entity this console reads. The first event restates all of them, so the
   * snapshot just fetched is brought up to date with anything that changed meanwhile. */
  private subscribeLive(live: LiveConnection) {
    this.unsubscribe();
    // Ids stay watched for the life of the connection: a fetch made while Home Assistant is still
    // starting may lack them, and they come back as additions.
    for (const id of watchedEntities(this.states)) this.watched.add(id);
    // An empty list would subscribe to every entity in Home Assistant; keep polling instead.
    if (!this.watched.size) return;
    const token = ++this.liveToken;
    const current = () => token === this.liveToken;
    const reconnected = () => {
      if (current()) void this.refresh();
    };
    let cancel: (() => unknown) | undefined;
    const end = (stop: (() => unknown) | undefined) =>
      Promise.resolve()
        .then(stop)
        .catch(() => {});
    live.addEventListener?.("ready", reconnected);
    this.dropLive = () => {
      live.removeEventListener?.("ready", reconnected);
      void end(cancel);
    };
    live
      .subscribeMessage<EntityUpdate>(
        (update) => {
          if (!current()) return;
          this.states = applyEntityUpdate(this.states, update);
          this.publishSoon();
        },
        { type: "subscribe_entities", entity_ids: [...this.watched].sort() },
      )
      .then(
        (unsubscribe) => (current() ? (cancel = unsubscribe) : void end(unsubscribe)),
        () => {
          // Refused (an older Home Assistant, or no permission): poll instead.
          if (!current()) return;
          this.unsubscribe();
          this.live = null;
        },
      );
  }
  /** Every room's live Journal events into `recentEvents`: one feed per connection and set of
   * rooms. A feed that stopped itself (an older integration) stays stopped until they change. */
  private startFeed() {
    const rooms = discoverRooms(this.states).map((room) => room.id).sort();
    if (!rooms.length || (this.stopFeed && rooms.join() === this.feedRooms)) return;
    this.endFeed();
    this.feedRooms = rooms.join();
    this.stopFeed = startEventFeed({
      connection: this.demo ? null : this.live,
      rooms,
      poll: async (room_id, since) => {
        const page = await pagedQuery(this, { room_id, since });
        if (page.kind === "missing") throw new JournalMissing();
        if (page.kind === "error") throw new Error(page.message);
        return page.data.events;
      },
      onEvents: (events) => {
        const ring = mergeEvents(this.recentEvents, events);
        if (ring === this.recentEvents) return;
        this.recentEvents = ring;
        this.publish();
      },
      visible: () => typeof document === "undefined" || !document.hidden,
      since: this.feedSince,
      // The demo's Journal is generated up to now: show it from the start.
      ...(this.demo ? { start: new Date(0).toISOString() } : {}),
    });
  }
  private endFeed() {
    this.stopFeed?.();
    this.stopFeed = undefined;
  }
  private unsubscribe = () => {
    this.liveToken++;
    this.dropLive?.();
    this.dropLive = undefined;
  };
  /** Single-entity reads (write preflight and readback) go into the snapshot, never over a state
   * that is newer (the subscription may already have delivered a later one). */
  private merge(entities: EntityState[]) {
    const read = Object.values(asStates(entities)).filter(
      (entity) =>
        !(
          Date.parse(this.states[entity.entity_id]?.last_updated ?? "") >
          Date.parse(entity.last_updated ?? "")
        ),
    );
    if (read.length)
      this.states = { ...this.states, ...Object.fromEntries(read.map((e) => [e.entity_id, e])) };
  }
  /** Entity updates come in bursts (the controller posts its whole room at once): publish once. */
  private publishSoon() {
    this.publishTimer ??= setTimeout(() => {
      this.publishTimer = undefined;
      if (!this.dropLive) return;
      this.settle();
      this.publish();
    }, 250);
  }
  changeRoom = (id: string) => {
    if (id === this.roomId || !discoverRooms(this.states).some((r) => r.id === id)) return;
    this.historyAborters.forEach((abort) => abort.abort());
    this.historyAborters.clear();
    this.generation++;
    this.roomId = id;
    if (this.connection === "live" || this.demo) this.error = null;
    this.publish();
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("room", id);
      window.history.replaceState({}, "", url);
    }
    // A live subscription already covers every room.
    if (!this.dropLive) void this.refresh();
  };
  connect = async (base: string, token: string) => {
    if (this.demo) return;
    const session = token.trim() ? undefined : findSession(base);
    const client = new HaClient(base, token.trim(), session);
    this.admin = adminOf(session);
    this.timeZone = haTimeZone(session?.config);
    this.historyAborters.forEach((abort) => abort.abort());
    this.historyAborters.clear();
    this.generation++;
    this.client?.dispose();
    this.client = client;
    this.unsubscribe();
    this.endFeed();
    this.recentEvents = [];
    this.feedSince.clear();
    this.watched.clear();
    this.live = liveConnection(session);
    this.states = {};
    this.roomId = "";
    this.updated = null;
    this.connection = "connecting";
    this.error = null;
    try {
      sessionStorage.setItem(
        SESSION_KEY,
        JSON.stringify({ base: client.base, token: token.trim() }),
      );
    } catch {
      /* current-memory connection still works */
    }
    this.publish();
    await this.refresh();
  };
  disconnect = () => {
    if (this.demo) return;
    this.historyAborters.forEach((abort) => abort.abort());
    this.historyAborters.clear();
    this.generation++;
    this.client?.dispose();
    this.client = null;
    this.unsubscribe();
    this.endFeed();
    this.live = null;
    this.connection = "offline";
    this.error = "Disconnected. Displayed data is the last successful snapshot.";
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      /* no storage */
    }
    this.publish();
  };
  write = async (changes: Change[]): Promise<WriteResult> => {
    const fail = (reason: string): WriteResult => ({
      applied: [],
      failed: changes.map((c) => ({ entityId: c.entityId, reason })),
    });
    if (this.writing) return fail("Another change batch is still being applied.");
    const generation = this.generation;
    const roomId = this.roomId;
    const client = this.client;
    const isCurrent = () => generation === this.generation && roomId === this.roomId;
    this.writing = true;
    try {
      if (this.demo) {
        const result: WriteResult = { applied: [], failed: [] };
        let next = { ...this.states };
        for (const change of changes) {
          const reason = validateChange(this.snapshot.room, this.states, change);
          if (reason) result.failed.push({ entityId: change.entityId, reason });
          else {
            const state =
              typeof change.value === "boolean" ? (change.value ? "on" : "off") : String(change.value);
            const stamp = new Date().toISOString();
            if (typeof change.value === "number" && change.entityId.startsWith("number."))
              this.operatorDemo?.journalTarget(
                roomId,
                this.snapshot.room.room.prefix,
                change.entityId,
                numeric(next[change.entityId]) ?? null,
                change.value,
              );
            next[change.entityId] = {
              ...next[change.entityId],
              state,
              last_updated: stamp,
              // As Home Assistant does: a new state is a change.
              ...(next[change.entityId]?.state !== state ? { last_changed: stamp } : {}),
            };
            next = demoReact(next, change.entityId, change.value);
            result.applied.push(change.entityId);
          }
        }
        this.states = next;
        this.updated = Date.now();
        this.publish();
        return result;
      }
      if (!client || this.connection !== "live")
        return fail("Connect to Home Assistant before applying changes.");
      // Preflight re-reads only the entities being written (availability and limits); room
      // membership comes from the current snapshot.
      const read: EntityState[] = [];
      for (const { entityId } of changes)
        if (this.states[entityId]) read.push(await client.state(entityId));
      if (!isCurrent()) return fail("Room or connection changed; changes cancelled.");
      this.merge(read);
      const currentRoom = discoverRooms(this.states).find((r) => r.id === roomId);
      if (!currentRoom) return fail("The selected room is no longer available.");
      const result = await applyChanges(
        {
          service: (domain, action, data) => client.service(domain, action, data),
          state: async (entityId) => {
            const entity = await client.state(entityId);
            if (isCurrent()) this.merge([entity]);
            return entity;
          },
        },
        buildRoom(this.states, currentRoom),
        this.states,
        changes,
        isCurrent,
      );
      if (isCurrent()) this.publish();
      return result;
    } catch (error) {
      if (isCurrent()) {
        this.error = message(error);
        this.connection = "offline";
        this.publish();
      }
      return fail(message(error));
    } finally {
      this.writing = false;
    }
  };
  operator = async <T>(action: OperatorAction, data: Record<string, unknown> = {}): Promise<T> => {
    const generation = this.generation;
    const roomId = this.roomId;
    const parity = isParityAction(action);
    // Notifications are the whole site's, never a room's. A v2 service that names one room gets the
    // selected room unless the caller names another (the live feed polls every room); site-wide and
    // all-rooms reads (supply, presets, timeline_get's `rooms`, history_changes without a room) and
    // session-keyed steps get none.
    const scoped =
      !parity && (action.startsWith("strategy_") ||
      action.startsWith("runs_") ||
      action.startsWith("setpoint_log_") ||
      action.startsWith("overlay_") ||
      action.startsWith("stock_") ||
      action.startsWith("calibration_") ||
      action.startsWith("dosing_") ||
      action.startsWith("brain_") ||
      action.startsWith("grow_days_") ||
      action.startsWith("harvests_") ||
      action.startsWith("display_") ||
      action.startsWith("history_"));
    const defaulted = parity && PARITY_ROOM_DEFAULT.has(action) && data.room_id === undefined;
    const payload = scoped || defaulted ? { ...data, room_id: roomId } : data;
    if ((scoped || defaulted) && !roomId) throw new Error("Select an available room.");
    // What's new's record and a test push change nothing a refresh would show, and must neither
    // wait on nor hold up a change being applied. Nor do v2 reads and previews. Stopping a pump
    // must never wait behind anything.
    const mutation =
      !action.startsWith("whats_new_") &&
      !(
        parity &&
        (PARITY_READS.has(action) ||
          (PREVIEWABLE.has(action) && data.preview === true) ||
          (action === "alert_rule_test" && data.send !== true))
      ) &&
      ![
        "strategy_get",
        "strategy_preview",
        "setup_read",
        "runs_get",
        "setpoint_log_get",
        "overlay_get",
        "stock_get",
        "calibration_get",
        "dosing_get",
        "notify_get",
        "notify_test",
        "history_connection_get",
        "history_long",
        "grow_days_get",
        "harvests_get",
        "display_get",
      ].includes(action);
    if (mutation && this.writing) throw new Error("Another change is still being applied.");
    if (mutation) this.writing = true;
    try {
      if (!this.demo && (!this.client || this.connection !== "live"))
        throw new Error("Connect to Home Assistant before using this action.");
      const result = this.demo
        ? await this.operatorDemo!.call<T>(action, payload)
        : await this.client!.operator<T>(action, payload);
      if (generation !== this.generation || roomId !== this.roomId)
        throw new Error(
          "Room or connection changed; response is unconfirmed. Reload before retrying.",
        );
      // A harvest is kept beside the run records, not in them (runs_set_harvest answers the harvests).
      if (action.startsWith("runs_") && action !== "runs_set_harvest") {
        const document = result as RunsDocument;
        if (
          document.room_id !== roomId ||
          !Array.isArray(document.runs) ||
          document.runs.some((run) => run.room_id !== roomId)
        )
          throw new Error("Invalid room-scoped run metadata response.");
        this.runDocuments.set(roomId, { generation, document });
      }
      if (mutation && !action.startsWith("runs_")) await this.refresh();
      return result;
    } finally {
      if (mutation) this.writing = false;
    }
  };
  /** Throws unless every id is a sensor of the selected room or one of its registered runs. A
   * promise only when it has to read the room's run records first. */
  private checkRunSensors(entityIds: string[]): Promise<void> | void {
    const generation = this.generation,
      roomId = this.roomId;
    if (!roomId) throw new Error("Select an available room.");
    const allowed = new Set(this.snapshot.room.entities.map((entity) => entity.entity_id));
    const check = () => {
      const registered = this.runDocuments.get(roomId);
      if (registered?.generation === generation)
        for (const run of registered.document.runs)
          for (const zone of run.zones)
            for (const id of [zone.vwc_sensor, zone.ec_sensor, ...(zone.probes ?? []).map((p) => p.entity_id)]) if (id) allowed.add(id);
      if (entityIds.some((id) => !allowed.has(id)))
        throw new Error("History is limited to this room's current or registered run sensors.");
    };
    if (
      entityIds.some((id) => !allowed.has(id)) &&
      this.runDocuments.get(roomId)?.generation !== generation
    )
      return this.operator<RunsDocument>("runs_get").then(check);
    check();
  }
  historyWindow = async (request: HistoryRequest): Promise<HistoryWindow> => {
    const generation = this.generation,
      roomId = this.roomId;
    const reading = this.checkRunSensors(request.entityIds);
    if (reading) await reading;
    const abort = new AbortController();
    const cancel = () => abort.abort();
    request.signal?.addEventListener("abort", cancel, { once: true });
    if (request.signal?.aborted) abort.abort();
    this.historyAborters.add(abort);
    try {
      if (!this.demo && (!this.client || this.connection !== "live"))
        throw new Error("Connect to Home Assistant to load recorded history.");
      const args = { ...request, signal: abort.signal };
      const result = this.demo
        ? await demoHistoryWindow(args)
        : await this.client!.historyWindow(args, roomId);
      if (generation !== this.generation || roomId !== this.roomId || abort.signal.aborted)
        throw new Error("Room or range changed; history request cancelled.");
      return result;
    } finally {
      this.historyAborters.delete(abort);
      request.signal?.removeEventListener("abort", cancel);
    }
  };
  /** Each sensor's low and high per local date over a run (Compare runs, by grow week): Home
   * Assistant's daily long-term statistics over its websocket inside Home Assistant, kept
   * indefinitely; standalone, and for a sensor without statistics, its recorded history. */
  sensorStatistics = async (request: HistoryRequest) => {
    const start = Date.parse(request.start), end = Date.parse(request.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || end - start > 180 * 86400000 || request.entityIds.length > 32)
      throw new Error("Hourly statistics require a bounded range and at most 32 sensors.");
    await this.checkRunSensors(request.entityIds);
    const generation = this.generation, roomId = this.roomId;
    if (!this.live?.sendMessagePromise || this.demo) return {};
    const result = await liveSensorStatistics(this.live, request);
    if (request.signal?.aborted || generation !== this.generation || roomId !== this.roomId)
      throw new Error("Room or range changed; hourly statistics cancelled.");
    return result;
  };
  dailyRanges = async (request: HistoryRequest): Promise<DailyRanges> => {
    const generation = this.generation,
      roomId = this.roomId;
    await this.checkRunSensors(request.entityIds);
    if (this.demo) {
      const window = await demoHistoryWindow(request);
      return {
        source: "demo",
        series: window.series.map(({ entityId, daily }) => ({ entityId, daily })),
        warnings: window.warnings,
      };
    }
    if (!this.client || this.connection !== "live")
      throw new Error("Connect to Home Assistant to load recorded history.");
    const series: DailyRanges["series"] = [];
    const warnings: string[] = [];
    if (this.live?.sendMessagePromise) {
      const statistics = await liveDailyStatistics(this.live, request);
      for (const entityId of request.entityIds)
        if (statistics[entityId]?.length) series.push({ entityId, daily: statistics[entityId] });
    }
    const missing = request.entityIds.filter((id) => !series.some((item) => item.entityId === id));
    if (missing.length) {
      const window = await this.historyWindow({ ...request, entityIds: missing });
      series.push(...window.series.map(({ entityId, daily }) => ({ entityId, daily })));
      warnings.push(...window.warnings);
      if (this.live?.sendMessagePromise)
        warnings.push(
          `No long-term statistics for ${missing.join(", ")}: its days come from recorded history, which reaches back only as far as the recorder keeps it.`,
        );
    }
    if (generation !== this.generation || roomId !== this.roomId)
      throw new Error("Room or range changed; history request cancelled.");
    return {
      source: missing.length === request.entityIds.length ? "history" : "statistics",
      series,
      warnings,
    };
  };
  history = async (entityIds: string[], hours: number, signal?: AbortSignal) => {
    if (!Number.isFinite(hours) || hours <= 0 || hours > 720)
      throw new Error("History range must be between 0 and 720 hours.");
    // The room's own entities, the probes its zones' readings combine, and the tank probes its
    // descriptor maps for display.
    const mapped = descriptor(this.states, this.snapshot.room.room)?.attributes;
    const allowed = new Set([
      ...this.snapshot.room.entities.map((e) => e.entity_id),
      ...roomProbeIds(this.snapshot.room.zones, this.states),
      ...[mapped?.tank_ec_sensor, mapped?.tank_ph_sensor].filter(
        (id): id is string => typeof id === "string" && !!id,
      ),
    ]);
    if (entityIds.some((id) => !allowed.has(id)))
      throw new Error("History is limited to entities in the selected room.");
    // Zone VWC follows the demo Journal's shots, so each shot's "after" agrees with its "before".
    if (this.demo) return demoJournalVwc(demoHistory(this.states, entityIds, hours), Date.now());
    if (!this.client || this.connection !== "live")
      throw new Error("Connect to Home Assistant to load recorded history.");
    const generation = this.generation;
    // A room change, reconnect or disconnect stops the rest of a long read, as does the caller.
    const abort = new AbortController();
    const cancel = () => abort.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) abort.abort();
    this.historyAborters.add(abort);
    try {
      const result = await this.client.history(entityIds, hours, this.states, abort.signal);
      if (generation !== this.generation)
        throw new Error("Room or connection changed; history request cancelled.");
      return result;
    } finally {
      this.historyAborters.delete(abort);
      signal?.removeEventListener("abort", cancel);
    }
  };
  /** The selected room's grow-day, once: over Home Assistant's websocket inside Home Assistant,
   * over REST standalone. Live updates extend it from there (day-timeline.ts appendLive). */
  timeline = async (request: TimelineRequest) => {
    const room = this.snapshot.room;
    const mapped = descriptor(this.states, room.room)?.attributes;
    const allowed = new Set([
      ...room.entities.map((entity) => entity.entity_id),
      ...room.zones.flatMap((zone) => (zone.valveEntity ? [zone.valveEntity] : [])),
      // The tank and pump its descriptor maps, charted on Equipment › Tank & feed.
      ...Object.values(TANK_KEYS).flatMap((key) => {
        const id = mapped?.[key];
        return typeof id === "string" && id ? [id] : [];
      }),
      // The main line and the lights: History › Timeline's equipment lanes (Settings › Display).
      ...(["mainline", "light_entity"] as const).flatMap((key) => {
        const id = mapped?.[key];
        return typeof id === "string" && id ? [id] : [];
      }),
      // Every sensor the zone page's history explorer offers: probes, climate, feed and tank.
      ...explorerSensors(room, this.states).map((sensor) => sensor.entityId),
    ]);
    const ids = [...request.entityIds, ...request.attributeIds];
    if (!ids.length || ids.some((id) => !allowed.has(id)))
      throw new Error("History is limited to entities in the selected room.");
    if (!(request.end > request.start) || request.end - request.start > 26 * 3_600_000)
      throw new Error("The day timeline covers at most one grow-day.");
    if (this.demo) return demoDay(this.states, request);
    if (!this.client || this.connection !== "live")
      throw new Error("Connect to Home Assistant to load recorded history.");
    const generation = this.generation;
    const result = this.live?.sendMessagePromise
      ? await liveHistory(this.live, request)
      : await this.client.timeline(request);
    if (generation !== this.generation)
      throw new Error("Room or connection changed; history request cancelled.");
    return result;
  };
  /** The selected room's water-today counters: Home Assistant's hourly long-term statistics over
   * its websocket inside Home Assistant; standalone, its recorded history over REST, which reaches
   * back only as far as the recorder keeps it. */
  waterRecord = async (request: WaterRecordRequest): Promise<WaterRecord> => {
    const allowed = new Set(this.snapshot.room.entities.map((entity) => entity.entity_id));
    if (!request.entityIds.length || request.entityIds.some((id) => !allowed.has(id)))
      throw new Error("Water records are limited to the selected room's sensors.");
    if (!(request.end > request.start))
      throw new Error("Water records need a start before their end.");
    if (this.demo) return { source: "demo", samples: demoWaterRecord(this.states, request) };
    if (!this.client || this.connection !== "live")
      throw new Error("Connect to Home Assistant to load recorded water.");
    const generation = this.generation;
    const result: WaterRecord = this.live?.sendMessagePromise
      ? { source: "statistics", samples: await liveStatistics(this.live, request) }
      : {
          source: "history",
          samples: historySamples(await this.client.timeline({ ...request, attributeIds: [] })),
        };
    if (generation !== this.generation)
      throw new Error("Room or connection changed; water request cancelled.");
    return result;
  };
}
function message(error: unknown): string {
  return error instanceof Error ? error.message : "Home Assistant request failed.";
}
export function useController(): Controller {
  const ref = useRef<ControllerStore | null>(null);
  if (!ref.current) ref.current = new ControllerStore();
  const store = ref.current;
  useEffect(store.start, [store]);
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}
