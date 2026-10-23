import { buildRoom, emptyRoom } from "./model";
import type { OperatorAction } from "./operator-types";
import type { Controller } from "./types";
import { ControllerStore } from "./use-controller";

const refuse = () => Promise.reject(new Error("Not used by this test."));

/** A controller with nothing in it, plus the overrides a test needs. Its `operator` may answer
 * anything, as a real service does. */
export function fakeController(
  overrides: Omit<Partial<Controller>, "operator"> & {
    operator?: (action: OperatorAction, data?: Record<string, unknown>) => Promise<unknown>;
  },
): Controller {
  return {
    demo: false,
    admin: true,
    connection: "live",
    timeZone: "Pacific/Auckland",
    error: null,
    lastUpdated: null,
    roomId: "room:",
    rooms: [],
    room: buildRoom({}, emptyRoom),
    states: {},
    refresh: () => Promise.resolve(),
    changeRoom: () => {},
    connect: () => Promise.resolve(),
    disconnect: () => {},
    write: () => Promise.resolve({ applied: [], failed: [] }),
    historyWindow: refuse,
    dailyRanges: refuse,
    history: refuse,
    timeline: refuse,
    waterRecord: refuse,
    operator: refuse,
    ...overrides,
  } as Controller;
}

/** The demo controller as a page with this query sees it, e.g. `?demo=1&backend=3.17`. */
export function demoController(search: string): Controller {
  return new ControllerStore(true, search).getSnapshot();
}
