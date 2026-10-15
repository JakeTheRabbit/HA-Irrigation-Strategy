import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  CalendarRange,
  Droplets,
  History,
  House,
  Settings2,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useController } from "@/lib/use-controller";
import { useHaTheme } from "@/lib/ha-theme";
import { useHaShell } from "@/lib/ha-shell";
import { errorText } from "@/lib/utils";
import { roomIsActive, runningVersions } from "@/lib/model";
import {
  canonicalHash,
  parseRoute,
  routeHash,
  sameRoute,
  sectionOf,
  type Page,
  type Route,
} from "@/lib/routes";
import { AppHeader } from "@/components/app-header";
import { PageTabs, pageLabel, SECTION_LABELS } from "@/components/page-tabs";
import { WaterViewProvider } from "@/lib/water-view";
import { WhatsNewOnUpdate } from "@/components/whats-new";
import { ZonePage } from "@/pages/zone";
import { Today } from "@/pages/today";
import { Strategy, type Drafts } from "@/pages/strategy";
import { Timeline } from "@/pages/timeline";
import { Probes } from "@/pages/probes";
import { Settings } from "@/pages/settings";
import { Notifications } from "@/pages/notifications";
import { Help } from "@/pages/help";
import { GrowPlanner } from "@/pages/grow-planner";
import { Setup } from "@/pages/setup";
import { Comparison } from "@/pages/comparison";
import { StockTanks } from "@/pages/stock";
import { Dosing } from "@/pages/dosing";
import { WaterUsePage } from "@/pages/water-use";
import { TankStatus } from "@/components/tank-status";
import { TankLevel } from "@/components/tank-level";

const navigation = [
  { page: "today", label: SECTION_LABELS.today, icon: House },
  { page: "plan/targets", label: SECTION_LABELS.plan, icon: CalendarRange },
  { page: "history/timeline", label: SECTION_LABELS.history, icon: History },
  { page: "equipment/probes", label: SECTION_LABELS.equipment, icon: Wrench },
  { page: "settings", label: SECTION_LABELS.settings, icon: Settings2 },
] as const satisfies readonly { page: Page; label: string; icon: unknown }[];

/** The page this address opens; an old or short form of it is rewritten in place (no new history
 * entry), keeping a Help link's `?code=`. */
function readRoute(): Route {
  const next = canonicalHash(window.location.hash, window.location.search);
  if (next !== null) window.history.replaceState(null, "", next);
  return parseRoute(window.location.hash, window.location.search).route;
}

export default function App() {
  const controller = useController();
  const [route, setRoute] = useState<Route>(readRoute);
  const [mobile, setMobile] = useState(false);
  const [drafts, setDrafts] = useState<Drafts>({});
  /** The zone Plan › Targets starts on, or the one History › Timeline shows. */
  const [focusZone, setFocusZone] = useState<number | undefined>();
  const [workspaceDirty, setWorkspaceDirty] = useState(false);
  const [pending, setPending] = useState<(() => void) | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const theme = useHaTheme();
  const haShell = useHaShell();
  const routeRef = useRef(route);
  const dirtyRef = useRef(false);
  dirtyRef.current = Object.keys(drafts).length > 0 || workspaceDirty;
  routeRef.current = route;
  const page = route.page;
  function confirmNavigation(action: () => void) {
    if (dirtyRef.current) setPending(() => action);
    else action();
  }
  /** Opens a page. `zone` opens that zone's page, picks the zone Plan › Targets starts on, or the
   * zone History › Timeline shows. */
  function navigate(next: Page, zone?: number) {
    const target: Route = next === "zone" ? { page: "zone", zone: zone ?? null } : { page: next };
    const focused = next === "plan/targets" || next === "history/timeline";
    if (sameRoute(target, route) && (!focused || zone === undefined)) {
      setMobile(false);
      return;
    }
    confirmNavigation(() => {
      setRoute(target);
      setFocusZone(focused ? zone : undefined);
      window.history.pushState(null, "", routeHash(target));
      setMobile(false);
      window.scrollTo({ top: 0 });
    });
  }
  useEffect(() => {
    const hashChange = () => {
      const next = readRoute();
      if (sameRoute(next, routeRef.current)) return;
      if (dirtyRef.current) {
        window.history.replaceState(null, "", routeHash(routeRef.current));
        setPending(() => () => {
          setRoute(next);
          window.history.pushState(null, "", routeHash(next));
        });
      } else {
        setRoute(next);
        setFocusZone(undefined);
      }
    };
    window.addEventListener("hashchange", hashChange);
    window.addEventListener("popstate", hashChange);
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (dirtyRef.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => {
      window.removeEventListener("hashchange", hashChange);
      window.removeEventListener("popstate", hashChange);
      window.removeEventListener("beforeunload", beforeUnload);
    };
  }, []);
  const zoneName =
    page === "zone"
      ? (controller.room.zones.find((zone) => zone.id === route.zone) ?? controller.room.zones[0])
          ?.name
      : undefined;
  useEffect(() => {
    document.title = `${zoneName ?? pageLabel(page)} · ${controller.room.room.name} · Crop Steering`;
  }, [page, zoneName, controller.room.room.name]);
  async function refresh() {
    setRefreshing(true);
    setRefreshError("");
    try {
      await controller.refresh();
    } catch (error) {
      setRefreshError(errorText(error));
    } finally {
      setRefreshing(false);
    }
  }
  function selectRoom(id: string) {
    confirmNavigation(() => {
      setDrafts({});
      setFocusZone(undefined);
      controller.changeRoom(id);
      setMobile(false);
    });
  }
  const versions = runningVersions(controller.states, controller.room.room);
  const section = sectionOf(page);
  const sidebar = (variant: string) => (
    <>
      <a
        href="#/today"
        className="brand"
        onClick={(event) => {
          event.preventDefault();
          navigate("today");
        }}
      >
        <span className="brand-mark">
          <Droplets size={23} />
        </span>
        <span>
          Crop Steering<small>Irrigation control</small>
        </span>
      </a>
      <div className="room-selector">
        <label htmlFor={variant + "-room"}>Room</label>
        <select
          id={variant + "-room"}
          value={controller.roomId}
          disabled={!controller.rooms.length}
          onChange={(event) => selectRoom(event.target.value)}
        >
          {!controller.roomId && (
            <option value="" disabled>
              {controller.rooms.length ? "Room unavailable - choose a room" : "No room discovered"}
            </option>
          )}
          {controller.rooms.map((room) => (
            <option key={room.id} value={room.id}>
              {room.name}
              {roomIsActive(controller.states, room) ? "" : " · off"}
            </option>
          ))}
        </select>
      </div>
      <nav aria-label="Main navigation">
        {navigation.map((item) => (
          <button
            key={item.page}
            className={`${section === sectionOf(item.page) ? "active" : ""} ${item.page === "settings" ? "nav-separated" : ""}`}
            aria-current={section === sectionOf(item.page) ? "page" : undefined}
            onClick={() => navigate(item.page)}
          >
            <item.icon size={19} />
            <span>{item.label}</span>
            {item.page === "plan/targets" && Object.keys(drafts).length > 0 && (
              <i className="nav-draft-count">{Object.keys(drafts).length}</i>
            )}
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        {haShell.available && (
          <Button
            variant="outline"
            onClick={() => {
              setMobile(false);
              haShell.toggle();
            }}
          >
            <House size={17} /> Home Assistant
          </Button>
        )}
        <span className="small">
          {controller.demo
            ? "Demo data: changes stay in this tab."
            : "Every change is reviewed before it is written."}
        </span>
        {!controller.demo && (
          <dl
            className="sidebar-versions"
            aria-label="Running versions"
            title="Reported by the running integration and controller, not by this page"
          >
            <div>
              <dt>Integration</dt>
              <dd>{versions.integration ?? "not reported"}</dd>
            </div>
            <div>
              <dt>Controller</dt>
              <dd>{versions.controller ?? "not reported"}</dd>
            </div>
          </dl>
        )}
      </div>
    </>
  );
  const pageKey = controller.roomId;
  const shell = (
    <div className="app-shell">
      <a
        href="#main-content"
        className="skip-link"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        Skip to content
      </a>
      <aside className="desktop-sidebar">{sidebar("desktop")}</aside>
      <Sheet open={mobile} onOpenChange={setMobile}>
        <SheetContent side="left" className="mobile-sidebar">
          <SheetHeader className="sr-only">
            <SheetTitle>Navigation</SheetTitle>
            <SheetDescription>Choose a room or dashboard page.</SheetDescription>
          </SheetHeader>
          {sidebar("mobile")}
        </SheetContent>
      </Sheet>
      <div className="app-main">
        <AppHeader
          controller={controller}
          haMenu={haShell.available ? haShell.toggle : null}
          openNavigation={() => setMobile(true)}
          selectRoom={selectRoom}
          openLog={() => navigate("history/timeline")}
          refresh={() => void refresh()}
          refreshing={refreshing}
        />
        <main id="main-content" tabIndex={-1}>
          <div className="main-inner">
            {(controller.connection === "offline" || controller.error || refreshError) && (
              <div className="connection-banner" role="alert">
                <div>
                  <strong>
                    {controller.connection === "offline"
                      ? "Controller disconnected"
                      : "Connection needs attention"}
                  </strong>
                  <p>
                    {refreshError ||
                      controller.error ||
                      "Live updates are unavailable. Connect Home Assistant to continue."}
                    {controller.lastUpdated && controller.connection === "offline"
                      ? " Displayed values are the last received readings."
                      : ""}
                  </p>
                </div>
                {page !== "settings" && (
                  <Button variant="outline" onClick={() => navigate("settings")}>
                    Connection settings <ArrowUpRight size={16} />
                  </Button>
                )}
              </div>
            )}
            <PageTabs
              page={page}
              navigate={(next) => navigate(next)}
              badges={{ "plan/targets": Object.keys(drafts).length }}
            />
            {page === "today" && (
              <Today key={pageKey} controller={controller} navigate={navigate} />
            )}
            {page === "zone" && (
              <ZonePage
                key={pageKey}
                controller={controller}
                zoneId={route.zone ?? null}
                navigate={navigate}
              />
            )}
            {page === "plan/targets" && (
              <Strategy
                key={pageKey}
                controller={controller}
                drafts={drafts}
                setDrafts={setDrafts}
                selectedZone={focusZone}
                navigate={navigate}
              />
            )}
            {page === "plan/schedule" && (
              <GrowPlanner
                key={pageKey}
                controller={controller}
                onDirtyChange={setWorkspaceDirty}
              />
            )}
            {page === "history/timeline" && (
              <Timeline key={`${pageKey}:${focusZone}`} controller={controller} zone={focusZone} />
            )}
            {page === "history/water" && <WaterUsePage key={pageKey} controller={controller} />}
            {page === "history/compare" && (
              <Comparison key={pageKey} controller={controller} navigate={navigate} />
            )}
            {page === "equipment/probes" && (
              <Probes key={pageKey} controller={controller} navigate={navigate} />
            )}
            {page === "equipment/stock" && (
              <StockTanks key={pageKey} controller={controller} navigate={navigate} />
            )}
            {page === "equipment/tank" && (
              <>
                <TankStatus
                  key={pageKey}
                  controller={controller}
                  onConfigure={() => navigate("equipment/setup")}
                />
                <TankLevel
                  key={`${pageKey}:level`}
                  controller={controller}
                  onConfigure={() => navigate("equipment/setup")}
                />
              </>
            )}
            {page === "equipment/dosing" && (
              <Dosing
                key={pageKey}
                controller={controller}
                navigate={navigate}
                onDirtyChange={setWorkspaceDirty}
              />
            )}
            {page === "equipment/setup" && (
              <Setup key={pageKey} controller={controller} onDirtyChange={setWorkspaceDirty} />
            )}
            {page === "settings" && (
              <Settings
                controller={controller}
                theme={theme.preference}
                setTheme={theme.setPreference}
                themeSource={theme.source}
                onDirtyChange={setWorkspaceDirty}
              />
            )}
            {page === "settings/notifications" && (
              <Notifications
                key={pageKey}
                controller={controller}
                onDirtyChange={setWorkspaceDirty}
              />
            )}
            {page === "help" && <Help controller={controller} />}
          </div>
        </main>
      </div>
      <WhatsNewOnUpdate controller={controller} />
      <Dialog
        open={Boolean(pending)}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Discard unsaved workspace changes?</DialogTitle>
            <DialogDescription>
              You have unsaved changes in {controller.room.room.name}. Leaving this view or changing
              rooms will discard them.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPending(null)}>
              Keep editing
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                const action = pending;
                setDrafts({});
                setWorkspaceDirty(false);
                dirtyRef.current = false;
                setPending(null);
                action?.();
              }}
            >
              Discard and continue
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
  return <WaterViewProvider controller={controller}>{shell}</WaterViewProvider>;
}
