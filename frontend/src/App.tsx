import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Droplets, House } from "lucide-react";
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
import { useDisplayUnits } from "@/lib/display-units";
import { useKeepAwake, useWakeLock } from "@/lib/wake-lock";
import { useHaTheme } from "@/lib/ha-theme";
import { useHaShell } from "@/lib/ha-shell";
import { errorText } from "@/lib/utils";
import { discardDrafts } from "@/lib/drafts";
import { resolveRequestedRoom, runningVersions } from "@/lib/model";
import {
  canonicalHash,
  parseRoute,
  routeHash,
  sameRoute,
  SECTION_PAGES,
  sectionOf,
  ZONE_FOCUS_PAGES,
  zoneOnPage,
  type Page,
  type Route,
} from "@/lib/routes";
import { featureLabel, featureTargets, useHashFeature } from "@/lib/feature-focus";
import { NAV_TREE } from "@/lib/nav-tree";
import { AppHeader, StaleBanner } from "@/components/app-header";
import { UiTip } from "@/components/info-tip";
import { PageTabs, pageLabel } from "@/components/page-tabs";
import { NavTree } from "@/components/nav-tree";
import { RoomPickContext, RoomTree, type RoomPick } from "@/components/room-tree";
import { useNarrow } from "@/lib/use-narrow";
import { WaterViewProvider } from "@/lib/water-view";
import { WhatsNewOnUpdate } from "@/components/whats-new";
import { Tour } from "@/components/tour";
import { ZonePage } from "@/pages/zone";
import { AllZones } from "@/pages/all-zones";
import { initialRoute, readLandingView } from "@/lib/landing-view";
import { Today } from "@/pages/today";
import { type Drafts } from "@/pages/strategy";
import { Irrigation } from "@/pages/irrigation";
import { Explorer } from "@/pages/explorer";
import { Probes } from "@/pages/probes";
import { Settings } from "@/pages/settings";
import { Features } from "@/pages/features";
import { Notifications } from "@/pages/notifications";
import { Help } from "@/pages/help";
import { Setup } from "@/pages/setup";
import { Comparison } from "@/pages/comparison";
import { Grows } from "@/pages/grows";
import { DrybackDrivers } from "@/pages/drivers";
import { StockTanks } from "@/pages/stock";
import { Dosing } from "@/pages/dosing";
import { WaterUsePage } from "@/pages/water-use";
import { AiSettings, BrainPage } from "@/components/brain";
import { Watering } from "@/pages/watering";
import { Timers } from "@/pages/timers";
import { Changes } from "@/pages/changes";
import { changesHash, changesQuery } from "@/lib/changes";
import { pickKey } from "@/lib/facility";
import { PumpCalibration } from "@/pages/pump-calibration";
import { FeedCalibration } from "@/pages/feed-calibration";
import { AlertRules } from "@/pages/alert-rules";
import { SystemStatus } from "@/pages/system";

/** The page this address opens; an old or short form of it is rewritten in place (no new history
 * entry), keeping a Help link's `?code=`. */
/** Pages whose address query outlives a room pick (openRoomPage). */
const KEEPS_QUERY: Page[] = ["plan/watering"];

function readRoute(): Route {
  const next = canonicalHash(window.location.hash, window.location.search);
  if (next !== null) window.history.replaceState(null, "", next);
  return initialRoute(window.location.hash, window.location.search, readLandingView());
}

export default function App() {
  const controller = useController();
  useDisplayUnits(controller);
  // Settings › "Keep this screen on while open": a wall screen or tablet stays on.
  useWakeLock(useKeepAwake()[0]);
  const [route, setRoute] = useState<Route>(readRoute);
  const [mobile, setMobile] = useState(false);
  const [drafts, setDrafts] = useState<Drafts>({});
  /** The zone Plan › Targets starts on, or the one History › Explorer shows. */
  const [focusZone, setFocusZone] = useState<number | undefined>(() => route.zone ?? undefined);
  const [workspaceDirty, setWorkspaceDirty] = useState(false);
  const [pending, setPending] = useState<(() => void) | null>(null);
  // A page's room pick (Copy to room…): the sidebar's tree on desktop, a bottom sheet on a phone.
  const [roomPick, setRoomPick] = useState<RoomPick | null>(null);
  const phone = useNarrow(720);
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
   * zone History › Explorer shows. */
  function navigate(next: Page, zone?: number) {
    const focused = ZONE_FOCUS_PAGES.includes(next);
    const target: Route =
      next === "zone"
        ? { page: "zone", zone: zone ?? null }
        : zone !== undefined && focused
          ? { page: next, zone }
          : { page: next };
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
          setFocusZone(next.zone ?? undefined);
          window.history.pushState(null, "", routeHash(next));
        });
      } else {
        setRoute(next);
        setFocusZone(next.zone ?? undefined);
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
      ? (zoneOnPage(controller.room.zones, route.zone ?? null)?.name ??
        (controller.room.zones.length ? `Zone ${route.zone} not in this room` : undefined))
      : undefined;
  useEffect(() => {
    document.title = `${zoneName ?? pageLabel(page)} · ${controller.room.room.name} · Crop Steering`;
  }, [page, zoneName, controller.room.room.name]);
  // A `?feature=` link opens its page at the feature's control, once the control is on screen.
  // Keyboard focus moves to the control and a screen reader hears which feature it is.
  const roomRef = useRef(controller.room);
  roomRef.current = controller.room;
  const feature = useHashFeature();
  const [announce, setAnnounce] = useState("");
  useEffect(() => {
    document
      .querySelectorAll("[data-feature-focus]")
      .forEach((element) => element.removeAttribute("data-feature-focus"));
    const id = feature;
    if (!id) return;
    let landed: HTMLElement | null = null;
    // True once the control has keyboard focus; until then the page may still be loading it, or
    // have it disabled while it loads.
    const land = () => {
      if (!landed?.isConnected) {
        const { room, zones } = roomRef.current;
        landed =
          featureTargets(id, room.prefix, zones.map((zone) => zone.id))
            .map((item) => document.getElementById(item))
            .find((element) => element?.getClientRects().length) ?? null;
        if (!landed) return false;
        const target = landed;
        // A control inside a folded group (Setup's limits) is shown by opening the group.
        let fold = target.closest("details");
        while (fold) {
          fold.open = true;
          fold = fold.parentElement?.closest("details") ?? null;
        }
        target.setAttribute("data-feature-focus", id);
        if (!target.matches("a[href], button, input, select, textarea, [tabindex]"))
          target.setAttribute("tabindex", "-1");
        setAnnounce(`Opened at ${featureLabel(id) ?? id}`);
        requestAnimationFrame(() => centre(target));
      }
      landed.focus({ preventScroll: true });
      return document.activeElement === landed;
    };
    // The window, not scrollIntoView: a control inside a panel that clips its overflow does not
    // scroll the page.
    const centre = (target: HTMLElement) => {
      const box = target.getBoundingClientRect();
      window.scrollTo({ top: window.scrollY + box.top - (window.innerHeight - box.height) / 2 });
    };
    // The control can arrive later: the room's states, or a page's own data, still loading. The
    // grower's own click, key or wheel ends the wait, so focus is never taken back from them.
    const observer = new MutationObserver(() => land() && observer.disconnect());
    if (!land())
      observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["disabled"],
      });
    // Content above a landed control can still be loading (the AI instructions, say) and push it
    // out of view, so it is kept in the middle of the window while the page grows.
    const resize = new ResizeObserver(() => {
      if (landed?.isConnected && document.activeElement === landed) centre(landed);
    });
    resize.observe(document.body);
    const timer = setTimeout(() => stop(), 10_000);
    const stop = () => {
      observer.disconnect();
      resize.disconnect();
      clearTimeout(timer);
      window.removeEventListener("pointerdown", stop, true);
      window.removeEventListener("keydown", stop, true);
      window.removeEventListener("wheel", stop, true);
    };
    window.addEventListener("pointerdown", stop, true);
    window.addEventListener("keydown", stop, true);
    window.addEventListener("wheel", stop, true);
    return stop;
  }, [route, feature]);
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
  /** Drops Current day's drafts, with their stored copies, so a reload never brings them back. */
  function dropDrafts() {
    setDrafts({});
    // This tab's copies only: another tab may be editing another room.
    discardDrafts("targets:", false);
  }
  function openRoomPage(id: string, next: Page, zone?: number) {
    confirmNavigation(() => {
      const target: Route = next === "zone" ? { page: next, zone: zone ?? null } : { page: next };
      // The watering timeline shows every room: its choices (span, date, filters) stay in the address.
      const hash = window.location.hash;
      const kept = next === page && KEEPS_QUERY.includes(next) && hash.includes("?") ? hash.slice(hash.indexOf("?")) : "";
      dropDrafts();
      setWorkspaceDirty(false);
      setFocusZone(zone);
      controller.changeRoom(id);
      setRoute(target);
      window.history.pushState(null, "", routeHash(target) + kept);
      setMobile(false);
      window.scrollTo({ top: 0 });
    });
  }
  /** History › Changes: a room or zone picked in the room list narrows the page to it (its address
   * carries the pick), and selects that room. */
  function narrowChanges(id: string, zone?: number) {
    confirmNavigation(() => {
      if (id !== controller.roomId) {
        dropDrafts();
        controller.changeRoom(id);
      }
      const query = changesQuery(window.location.hash);
      window.location.hash = changesHash({ ...query, room: zone === undefined ? id : pickKey(id, zone), id: undefined });
      setMobile(false);
    });
  }
  /** Opens a room in the section already open: Status opens the room's own page, any other
   * section stays where it is. */
  function openRoom(id: string) {
    if (page === "history/changes") return narrowChanges(id);
    const next: Page = page === "all-zones" || page === "zone" ? "today" : page;
    if (id === controller.roomId) navigate(next);
    else openRoomPage(id, next);
  }
  // The selected room is part of the address (?room=f1), so a bookmark or a shared link opens it.
  useEffect(() => {
    if (!controller.roomId) return;
    const query = new URLSearchParams(window.location.search);
    if (resolveRequestedRoom(controller.rooms, query.get("room"))?.id === controller.roomId) return;
    // The room's short name where it has one (f1, room_b; f2 for the unprefixed room), else its id.
    const room = controller.room.room;
    const short = room.prefix ? room.prefix.replace(/_$/, "") : "f2";
    query.set(
      "room",
      resolveRequestedRoom(controller.rooms, short)?.id === controller.roomId ? short : controller.roomId,
    );
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}?${query.toString()}${window.location.hash}`,
    );
  }, [controller.roomId]);
  const versions = runningVersions(controller.states, controller.room.room);
  const section = sectionOf(page);
  const sidebar = (variant: string) => (
    <>
      <a
        href="#/all-zones"
        className="brand"
        onClick={(event) => {
          event.preventDefault();
          navigate("all-zones");
        }}
      >
        <span className="brand-mark">
          <Droplets size={23} />
        </span>
        <span>
          Crop Steering<small>Irrigation control</small>
        </span>
      </a>
      <NavTree
        page={page}
        navigate={(next) => navigate(next)}
        badges={{ "plan/targets": Object.keys(drafts).length }}
      />
      <RoomTree
        controller={controller}
        allRooms={page === "all-zones"}
        currentZone={page === "zone" ? (route.zone ?? controller.room.zones[0]?.id ?? null) : null}
        openRoom={openRoom}
        openZone={(room, zone) =>
          page === "history/changes"
            ? narrowChanges(room, zone)
            : room === controller.roomId
              ? navigate("zone", zone)
              : openRoomPage(room, "zone", zone)
        }
        pick={variant === "desktop" && !phone ? roomPick : null}
      />
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
            aria-label="Current versions"
            title="Reported versions. The integration and the controller report these versions. The dashboard does not calculate them."
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
  /** The open page's component; every page in RENDERED_PAGES has a case. */
  function renderPage() {
    switch (page) {
      case "all-zones":
        return <AllZones controller={controller} open={openRoomPage} />;
      case "today":
        return <Today key={pageKey} controller={controller} navigate={navigate} />;
      case "zone":
        return (
          <ZonePage
            key={pageKey}
            controller={controller}
            zoneId={route.zone ?? null}
            onDirtyChange={setWorkspaceDirty}
            navigate={navigate}
          />
        );
      case "today/ai":
        return <BrainPage key={pageKey} controller={controller} navigate={navigate} />;
      case "plan/targets":
      case "plan/schedule":
        return (
          <Irrigation
            key={controller.roomId}
            controller={controller}
            drafts={drafts}
            setDrafts={setDrafts}
            onDirtyChange={setWorkspaceDirty}
            zoneId={focusZone}
            initialView={page === "plan/schedule" ? "calendar" : "current"}
            navigate={navigate}
          />
        );
      case "plan/watering":
        return (
          <Watering
            key={pageKey}
            controller={controller}
            navigate={navigate}
            onDirtyChange={setWorkspaceDirty}
          />
        );
      case "plan/timers":
        return (
          <Timers
            key={pageKey}
            controller={controller}
            navigate={navigate}
            onDirtyChange={setWorkspaceDirty}
          />
        );
      case "history/explorer":
        return <Explorer key={pageKey} controller={controller} zone={focusZone} />;
      case "history/water":
        return <WaterUsePage key={pageKey} controller={controller} />;
      case "history/drivers":
        return <DrybackDrivers key={pageKey} controller={controller} />;
      case "history/compare":
        return <Comparison key={pageKey} controller={controller} navigate={navigate} />;
      case "history/changes":
        return (
          <Changes
            key={pageKey}
            controller={controller}
            navigate={navigate}
            onDirtyChange={setWorkspaceDirty}
          />
        );
      case "history/grows":
        return <Grows key={pageKey} controller={controller} onDirtyChange={setWorkspaceDirty} />;
      case "equipment/probes":
        return (
          <Probes
            key={pageKey}
            controller={controller}
            navigate={navigate}
            onDirtyChange={setWorkspaceDirty}
          />
        );
      case "equipment/stock":
        return <StockTanks key={pageKey} controller={controller} navigate={navigate} />;
      case "equipment/dosing":
        return (
          <Dosing
            key={pageKey}
            controller={controller}
            navigate={navigate}
            onDirtyChange={setWorkspaceDirty}
          />
        );
      case "equipment/pump-calibration":
        return (
          <PumpCalibration
            key={pageKey}
            controller={controller}
            navigate={navigate}
            onDirtyChange={setWorkspaceDirty}
          />
        );
      case "equipment/feed-calibration":
        return (
          <FeedCalibration
            key={pageKey}
            controller={controller}
            navigate={navigate}
            onDirtyChange={setWorkspaceDirty}
          />
        );
      case "equipment/setup":
        return <Setup key={pageKey} controller={controller} onDirtyChange={setWorkspaceDirty} />;
      case "settings":
        return (
          <Settings
            controller={controller}
            theme={theme.preference}
            setTheme={theme.setPreference}
            themeSource={theme.source}
            onDirtyChange={setWorkspaceDirty}
          />
        );
      case "settings/alerts":
        return (
          <AlertRules
            key={pageKey}
            controller={controller}
            navigate={navigate}
            onDirtyChange={setWorkspaceDirty}
          />
        );
      case "settings/notifications":
        return (
          <Notifications key={pageKey} controller={controller} onDirtyChange={setWorkspaceDirty} />
        );
      case "settings/system":
        return (
          <SystemStatus
            key={pageKey}
            controller={controller}
            navigate={navigate}
            onDirtyChange={setWorkspaceDirty}
          />
        );
      case "settings/ai":
        return (
          <AiSettings key={pageKey} controller={controller} onDirtyChange={setWorkspaceDirty} />
        );
      case "settings/features":
        return <Features key={pageKey} controller={controller} />;
      case "help":
        return <Help controller={controller} />;
      default: {
        const unrendered: never = page;
        return unrendered;
      }
    }
  }
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
            <SheetDescription>Choose a room, a zone or a dashboard page.</SheetDescription>
          </SheetHeader>
          {sidebar("mobile")}
        </SheetContent>
      </Sheet>
      <div className="app-main">
        <AppHeader
          controller={controller}
          title={zoneName ?? pageLabel(page)}
          roomName={controller.room.room.name}
          haMenu={haShell.available ? haShell.toggle : null}
          openNavigation={() => setMobile(true)}
          jump={(entry) => {
            // Another room's page opens in that room; an address with more than a page in it
            // (`?rule=new`) goes through the address, so the page reads it.
            const { route: target } = parseRoute(entry.hash);
            if (entry.room && entry.room !== controller.roomId)
              openRoomPage(entry.room, target.page, target.zone ?? undefined);
            else if (routeHash(target) !== entry.hash) window.location.hash = entry.hash;
            else navigate(target.page, target.zone ?? undefined);
          }}
          openLog={() => navigate("history/explorer")}
          openBrain={() => navigate("today/ai")}
          refresh={() => void refresh()}
          refreshing={refreshing}
        />
        <StaleBanner controller={controller} openProbes={() => navigate("equipment/probes")} />
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
            {renderPage()}
          </div>
        </main>
      </div>
      <nav className="bottom-nav" aria-label="Sections">
        {NAV_TREE.map((group) => {
          const target = SECTION_PAGES[group.section] ?? group.items[0].page;
          return (
            <button
              type="button"
              key={group.section}
              aria-current={section === group.section ? "page" : undefined}
              onClick={() => navigate(target)}
            >
              <span className="bottom-nav-icon">
                <group.icon size={21} aria-hidden="true" />
                {group.section === "plan" && Object.keys(drafts).length > 0 && (
                  <i className="nav-draft-count">{Object.keys(drafts).length}</i>
                )}
              </span>
              <span>{group.label}</span>
            </button>
          );
        })}
      </nav>
      <p id="feature-announce" className="sr-only" role="status">
        {announce}
      </p>
      {phone && roomPick && (
        <RoomTree
          controller={controller}
          allRooms={false}
          currentZone={null}
          openRoom={() => {}}
          openZone={() => {}}
          pick={roomPick}
        />
      )}

      <WhatsNewOnUpdate controller={controller} />
      <Tour navigate={navigate} />
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
                dropDrafts();
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
  return (
    <WaterViewProvider controller={controller}>
      <RoomPickContext.Provider value={setRoomPick}>{shell}</RoomPickContext.Provider>
    </WaterViewProvider>
  );
}
