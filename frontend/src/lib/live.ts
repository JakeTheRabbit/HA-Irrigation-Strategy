import type { EntityState, States } from "./types";

/** The part of Home Assistant's frontend websocket connection (`hass.connection`, from
 * home-assistant-js-websocket) this console uses when it runs inside Home Assistant. */
export interface LiveConnection {
  connected?: boolean;
  subscribeMessage<T>(
    callback: (message: T) => void,
    message: Record<string, unknown>,
  ): Promise<() => unknown>;
  addEventListener?(event: "ready", callback: () => void): void;
  removeEventListener?(event: "ready", callback: () => void): void;
}
export function liveConnection(session: { connection?: unknown } | undefined) {
  const connection = session?.connection as LiveConnection | undefined;
  return typeof connection?.subscribeMessage === "function" ? connection : null;
}

/** Home Assistant's compressed state, as `subscribe_entities` sends it (times in epoch seconds;
 * `lu` is left out when it equals `lc`). */
interface CompressedState {
  s?: string;
  a?: Record<string, unknown>;
  lc?: number;
  lu?: number;
}
export interface EntityUpdate {
  /** Added entities, and every subscribed entity in the first event of a subscription. */
  a?: Record<string, CompressedState>;
  /** Changed entities: "+" new values, "-" removed attribute keys. */
  c?: Record<string, { "+"?: CompressedState; "-"?: { a?: string[] } }>;
  /** Removed entities. */
  r?: string[];
}
const time = (seconds: number | undefined) =>
  typeof seconds === "number" ? new Date(seconds * 1000).toISOString() : undefined;

/** One subscribe_entities event applied to a snapshot, as home-assistant-js-websocket applies it.
 * Returns the same object when nothing changed. */
export function applyEntityUpdate(states: States, update: EntityUpdate): States {
  let next: States | null = null;
  const write = () => (next ??= { ...states });
  for (const [id, state] of Object.entries(update.a ?? {})) {
    const changed = time(state.lc);
    write()[id] = {
      entity_id: id,
      state: String(state.s ?? ""),
      attributes: state.a ?? {},
      last_changed: changed,
      last_updated: time(state.lu) ?? changed,
    };
  }
  for (const id of update.r ?? []) if (id in (next ?? states)) delete write()[id];
  for (const [id, diff] of Object.entries(update.c ?? {})) {
    const current = (next ?? states)[id];
    // A change to an entity never seen is dropped; the next full fetch brings it.
    if (!current) continue;
    const add = diff["+"],
      remove = diff["-"]?.a;
    const entity: EntityState = { ...current };
    if (add?.s !== undefined) entity.state = add.s;
    if (add?.lc !== undefined) entity.last_changed = entity.last_updated = time(add.lc);
    else if (add?.lu !== undefined) entity.last_updated = time(add.lu);
    if (add?.a || remove) {
      entity.attributes = { ...current.attributes, ...add?.a };
      for (const key of remove ?? []) delete entity.attributes[key];
    }
    write()[id] = entity;
  }
  return next ?? states;
}

// What the controller publishes (over REST, so these do not exist until it has posted them once:
// after a Home Assistant restart with the controller stopped they are missing, not stale).
const ROOM_SENSORS = ["ai_heartbeat", "app_status", "current_decision", "activity_log"];
const ZONE_SENSORS = [
  "phase",
  "status",
  "safety_status",
  "last_irrigation_app",
  "daily_water_app",
  "weekly_water_app",
  "irrigation_count_app",
  "auto_setpoints",
];
const ENTITY_ID = /^(?!.+__)(?!_)[\da-z_]+(?<!_)\.(?!_)[\da-z_]+(?<!_)$/;
/** Every entity this console reads: all crop_steering entities, whatever the room descriptors and
 * heartbeats point at (kill switches, pumps, valves, tank and feed sensors), and the controller's
 * sensors for every configured zone, including the ones it has not posted yet. */
export function watchedEntities(states: States): string[] {
  const ids = new Set<string>();
  const visit = (value: unknown): void => {
    if (typeof value === "string") {
      if (Object.hasOwn(states, value)) ids.add(value);
    } else if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === "object") Object.values(value).forEach(visit);
  };
  for (const [id, entity] of Object.entries(states)) {
    if (!/^[a-z_]+\.crop_steering_/.test(id)) continue;
    ids.add(id);
    if (/^sensor\.crop_steering_.*ai_heartbeat$/.test(id)) visit(entity.attributes.enable_flag);
    if (!/^sensor\.crop_steering_.*engine_config$/.test(id)) continue;
    visit(entity.attributes);
    const { prefix, num_zones } = entity.attributes;
    if (typeof prefix !== "string") continue;
    const root = `sensor.crop_steering_${prefix}`;
    for (const key of ROOM_SENSORS) ids.add(root + key);
    for (let zone = 1; zone <= Math.min(Number(num_zones) || 0, 64); zone++) {
      for (const key of ZONE_SENSORS) ids.add(`${root}zone_${zone}_${key}`);
      ids.add(`${root}vwc_zone_${zone}`);
      ids.add(`${root}ec_zone_${zone}`);
    }
  }
  // One malformed id would make Home Assistant reject the whole subscription.
  return [...ids].filter((id) => ENTITY_ID.test(id)).sort();
}

export interface PageEvents {
  hidden(): boolean;
  on(event: "visibilitychange" | "focus", handler: () => void): () => void;
}
function browserPage(): PageEvents {
  const page = typeof document === "undefined" ? undefined : document;
  const view = typeof window === "undefined" ? undefined : window;
  return {
    hidden: () => page?.hidden === true,
    on(event, handler) {
      const target = event === "focus" ? view : page;
      if (typeof target?.addEventListener !== "function") return () => {};
      target.addEventListener(event, handler);
      return () => target.removeEventListener(event, handler);
    },
  };
}
/** Runs `run` every `interval` ms while the page is visible, and at once when it is shown or
 * focused again: at most once per `gap` ms, as showing a tab also focuses it and focus comes and
 * goes. Returns stop. */
export function whileVisible(
  run: () => void,
  interval: number,
  page: PageEvents = browserPage(),
  gap = 10_000,
): () => void {
  let last = -Infinity;
  const tick = (resume: boolean) => {
    if (page.hidden() || (resume && Date.now() - last < gap)) return;
    last = Date.now();
    run();
  };
  const timer = setInterval(() => tick(false), interval);
  const off = [page.on("visibilitychange", () => tick(true)), page.on("focus", () => tick(true))];
  return () => {
    clearInterval(timer);
    off.forEach((stop) => stop());
  };
}
