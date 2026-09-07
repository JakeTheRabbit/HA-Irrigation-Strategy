import type { HistoryRequest, HistoryWindow, RunsDocument } from "./comparison-types";
import { demoHistoryWindow } from "./comparison-demo";
import type { OperatorAction } from "./operator-types";
import { OperatorDemo } from "./operator-demo";
import { useEffect, useRef, useSyncExternalStore } from "react";
import type { Change, Controller, States, WriteResult } from "./types";
import { applyChanges, findSession, HaClient, haSessionToken } from "./client";
import { buildRoom, discoverRooms, emptyRoom, resolveRequestedRoom, validateChange } from "./model";
import { createDemo, demoHistory, isDemoLocation } from "./demo";

type Listener = () => void;
const SESSION_KEY = "crop-steering-connection-tab";
export class ControllerStore {
  private listeners = new Set<Listener>();
  private client: HaClient | null = null;
  private generation = 0;
  private requestId = 0;
  private interval?: ReturnType<typeof setInterval>;
  private states: States;
  private roomId = "";
  private connection: Controller["connection"];
  private error: string | null = null;
  private updated: number | null = null;
  private writing = false;
  readonly demo: boolean;
  private snapshot!: Controller;
  private operatorDemo?: OperatorDemo;
  private runDocuments = new Map<string, { generation: number; document: RunsDocument }>();
  private historyAborters = new Set<AbortController>();
  constructor(demo = typeof window !== "undefined" && isDemoLocation(window.location)) {
    this.demo = demo;
    this.states = demo ? createDemo() : {};
    this.connection = demo ? "demo" : "connecting";
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
      );
    const requested =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search).get("room")
        : null;
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
      connection: this.connection,
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
      operator: this.operator,
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
      const inheritedToken =
        typeof window !== "undefined" && base === window.location.origin ? haSessionToken() : "";
      try {
        this.client = new HaClient(base, saved.token || inheritedToken, session);
        void this.refresh();
      } catch (error) {
        this.connection = "offline";
        this.error = message(error);
        this.publish();
      }
    }
    if (!this.interval)
      this.interval = setInterval(() => {
        void this.refresh();
      }, 30_000);
    return this.stop;
  };
  stop = () => {
    clearInterval(this.interval);
    this.interval = undefined;
    this.historyAborters.forEach((abort) => abort.abort());
    this.historyAborters.clear();
    this.generation++;
    this.client?.dispose();
    this.client = null;
  };
  refresh = async () => {
    if (this.demo) {
      this.updated = Date.now();
      this.publish();
      return;
    }
    const client = this.client;
    if (!client) return;
    const generation = this.generation;
    const request = ++this.requestId;
    try {
      const states = await client.states();
      if (generation !== this.generation || request !== this.requestId) return;
      this.states = states;
      const rooms = discoverRooms(states);
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
    } catch (error) {
      if (generation !== this.generation || request !== this.requestId) return;
      this.connection = "offline";
      this.error = message(error);
    }
    this.publish();
  };
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
    void this.refresh();
  };
  connect = async (base: string, token: string) => {
    if (this.demo) return;
    const client = new HaClient(base, token.trim(), token.trim() ? undefined : findSession(base));
    this.historyAborters.forEach((abort) => abort.abort());
    this.historyAborters.clear();
    this.generation++;
    this.client?.dispose();
    this.client = client;
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
        const next = { ...this.states };
        for (const change of changes) {
          const reason = validateChange(this.snapshot.room, this.states, change);
          if (reason) result.failed.push({ entityId: change.entityId, reason });
          else {
            next[change.entityId] = {
              ...next[change.entityId],
              state:
                typeof change.value === "boolean"
                  ? change.value
                    ? "on"
                    : "off"
                  : String(change.value),
              last_updated: new Date().toISOString(),
            };
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
      // Fresh full-state preflight rechecks room membership, limits and availability.
      const fresh = await client.states();
      if (!isCurrent()) return fail("Room or connection changed; changes cancelled.");
      const currentRoom = discoverRooms(fresh).find((r) => r.id === roomId);
      if (!currentRoom) return fail("The selected room is no longer available.");
      const result = await applyChanges(
        client,
        buildRoom(fresh, currentRoom),
        fresh,
        changes,
        isCurrent,
      );
      if (isCurrent()) await this.refresh();
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
    const scoped = action.startsWith("strategy_") || action.startsWith("runs_");
    const payload = scoped ? { ...data, room_id: roomId } : data;
    if (scoped && !roomId) throw new Error("Select an available room.");
    const mutation = !["strategy_get", "strategy_preview", "setup_read", "runs_get"].includes(
      action,
    );
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
      if (action.startsWith("runs_")) {
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
  historyWindow = async (request: HistoryRequest): Promise<HistoryWindow> => {
    const generation = this.generation,
      roomId = this.roomId;
    if (!roomId) throw new Error("Select an available room.");
    const allowed = new Set(this.snapshot.room.entities.map((entity) => entity.entity_id));
    let registered = this.runDocuments.get(roomId);
    if (request.entityIds.some((id) => !allowed.has(id)) && registered?.generation !== generation) {
      await this.operator<RunsDocument>("runs_get");
      registered = this.runDocuments.get(roomId);
    }
    if (registered?.generation === generation)
      for (const run of registered.document.runs)
        for (const zone of run.zones)
          for (const id of [zone.vwc_sensor, zone.ec_sensor]) if (id) allowed.add(id);
    if (request.entityIds.some((id) => !allowed.has(id)))
      throw new Error("History is limited to this room's current or registered run sensors.");
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
        : await this.client!.historyWindow(args);
      if (generation !== this.generation || roomId !== this.roomId || abort.signal.aborted)
        throw new Error("Room or range changed; history request cancelled.");
      return result;
    } finally {
      this.historyAborters.delete(abort);
      request.signal?.removeEventListener("abort", cancel);
    }
  };
  history = async (entityIds: string[], hours: number) => {
    if (!Number.isFinite(hours) || hours <= 0 || hours > 168)
      throw new Error("History range must be between 0 and 168 hours.");
    const allowed = new Set(this.snapshot.room.entities.map((e) => e.entity_id));
    if (entityIds.some((id) => !allowed.has(id)))
      throw new Error("History is limited to entities in the selected room.");
    if (this.demo) return demoHistory(this.states, entityIds, hours);
    if (!this.client || this.connection !== "live")
      throw new Error("Connect to Home Assistant to load recorded history.");
    const generation = this.generation;
    const result = await this.client.history(entityIds, hours, this.states);
    if (generation !== this.generation)
      throw new Error("Room or connection changed; history request cancelled.");
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
