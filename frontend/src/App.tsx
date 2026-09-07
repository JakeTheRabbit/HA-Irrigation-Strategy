import { useEffect, useRef, useState } from "react";
import {
  Activity,
  CalendarRange,
  ChartNoAxesCombined,
  Wrench,
  ArrowUpRight,
  ChevronRight,
  CircleHelp,
  Droplets,
  House,
  Layers,
  Menu,
  Radio,
  RefreshCw,
  Settings2,
  SlidersHorizontal,
  X,
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
import { time, type Page } from "@/components/dashboard";
import { Overview } from "@/pages/overview";
import { Zones } from "@/pages/zones";
import { Strategy, type Drafts } from "@/pages/strategy";
import { ActivityPage } from "@/pages/activity";
import { Sensors } from "@/pages/sensors";
import { Settings } from "@/pages/settings";
import { Help } from "@/pages/help";
import { GrowPlanner } from "@/pages/grow-planner";
import { Setup } from "@/pages/setup";
import { Insights } from "@/pages/insights";
import { Comparison } from "@/pages/comparison";

const navigation = [
  { id: "overview", label: "Overview", icon: House },
  { id: "zones", label: "Zones", icon: Layers },
  { id: "strategy", label: "Manual setpoints", icon: SlidersHorizontal },
  { id: "grow-plan", label: "Grow plan", icon: CalendarRange },
  { id: "compare", label: "Compare runs", icon: ChartNoAxesCombined },
  { id: "insights", label: "Insights", icon: ChartNoAxesCombined },
  { id: "activity", label: "Activity", icon: Activity },
  { id: "sensors", label: "Sensors", icon: Radio },
  { id: "setup", label: "Rooms & setup", icon: Wrench },
  { id: "settings", label: "Settings", icon: Settings2 },
  { id: "help", label: "Help & tools", icon: CircleHelp },
] as const;
function readPage(): Page {
  const hash = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  if (navigation.some((n) => n.id === hash)) return hash as Page;
  const view = new URLSearchParams(window.location.search).get("view") || "";
  return (
    (
      {
        dashboard: "overview",
        overview: "overview",
        zones: "zones",
        tune: "strategy",
        strategy: "strategy",
        logs: "activity",
        log: "activity",
        activity: "activity",
        sensors: "sensors",
        settings: "settings",
        help: "help",
        timeline: "grow-plan",
        climate: "sensors",
        control: "settings",
        substrate: "insights",
        analyze: "insights",
        floor: "setup",
        floorplan: "setup",
        recipes: "grow-plan",
      } as Record<string, Page>
    )[view] || "overview"
  );
}
export default function App() {
  const controller = useController();
  const [page, setPage] = useState<Page>(readPage);
  const [mobile, setMobile] = useState(false);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [zoneId, setZoneId] = useState<number | undefined>();
  const [workspaceDirty, setWorkspaceDirty] = useState(false);
  const [pending, setPending] = useState<(() => void) | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const theme = useHaTheme();
  const haShell = useHaShell();
  const pageRef = useRef(page);
  const dirtyRef = useRef(false);
  dirtyRef.current = Object.keys(drafts).length > 0 || workspaceDirty;
  pageRef.current = page;
  function confirmNavigation(action: () => void) {
    if (dirtyRef.current) setPending(() => action);
    else action();
  }
  function navigate(next: Page, nextZone?: number) {
    if (next === page && nextZone === undefined) {
      setMobile(false);
      return;
    }
    confirmNavigation(() => {
      setPage(next);
      setZoneId(nextZone);
      window.history.pushState(null, "", `#/${next}`);
      setMobile(false);
      window.scrollTo({ top: 0 });
    });
  }
  useEffect(() => {
    const hashChange = () => {
      const next = readPage();
      if (next === pageRef.current) return;
      if (dirtyRef.current) {
        window.history.replaceState(null, "", `#/${pageRef.current}`);
        setPending(() => () => {
          setPage(next);
          window.history.pushState(null, "", `#/${next}`);
        });
      } else {
        setPage(next);
        setZoneId(undefined);
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
  useEffect(() => {
    document.title = `${navigation.find((n) => n.id === page)?.label} · ${controller.room.room.name} · Crop Steering`;
  }, [page, controller.room.room.name]);
  async function refresh() {
    setRefreshing(true);
    setRefreshError("");
    try {
      await controller.refresh();
    } catch (error) {
      setRefreshError(error instanceof Error ? error.message : String(error));
    } finally {
      setRefreshing(false);
    }
  }
  const sidebar = (variant: string) => (
    <>
      <a
        href="#/overview"
        className="brand"
        onClick={(event) => {
          event.preventDefault();
          navigate("overview");
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
          onChange={(event) => {
            const id = event.target.value;
            confirmNavigation(() => {
              setDrafts({});
              setZoneId(undefined);
              controller.changeRoom(id);
              setMobile(false);
            });
          }}
        >
          {!controller.roomId && (
            <option value="" disabled>
              {controller.rooms.length ? "Room unavailable - choose a room" : "No room discovered"}
            </option>
          )}
          {controller.rooms.map((room) => (
            <option key={room.id} value={room.id}>
              {room.name}
            </option>
          ))}
        </select>
        <span>
          <span className={`connection-dot ${controller.connection}`} />
          {controller.demo ? "Isolated demo data" : "Home Assistant controller"}
        </span>
      </div>
      <nav aria-label="Main navigation">
        {navigation.map((item, index) => (
          <button
            key={item.id}
            className={`${page === item.id ? "active" : ""} ${item.id === "settings" ? "nav-separated" : ""}`}
            aria-current={page === item.id ? "page" : undefined}
            onClick={() => navigate(item.id)}
          >
            <item.icon size={19} />
            <span>{item.label}</span>
            {item.id === "strategy" && Object.keys(drafts).length > 0 && (
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
        <span className="small">Configuration changes require review.</span>
      </div>
    </>
  );
  return (
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
        <header className="topbar">
          {haShell.available && (
            <Button
              variant="ghost"
              size="icon"
              aria-label="Open Home Assistant menu"
              title="Home Assistant menu"
              onClick={haShell.toggle}
            >
              <House size={20} />
            </Button>
          )}
          <div className="breadcrumbs">
            <Button
              className="mobile-menu"
              variant="ghost"
              size="icon"
              aria-label="Open navigation"
              onClick={() => setMobile(true)}
            >
              <Menu size={21} />
            </Button>
            <span>{controller.room.room.name}</span>
            <ChevronRight size={14} />
            <strong>{navigation.find((n) => n.id === page)?.label}</strong>
          </div>
          <div className="connection-info">
            <span className={`connection-label ${controller.connection}`}>
              <span className={`connection-dot ${controller.connection}`} />
              {controller.connection === "live"
                ? "Connected"
                : controller.connection === "demo"
                  ? "Demo mode"
                  : controller.connection === "connecting"
                    ? "Connecting…"
                    : "Offline"}
            </span>
            <span className="last-updated">Updated {time(controller.lastUpdated)}</span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Refresh controller data"
              disabled={refreshing || controller.connection === "connecting"}
              onClick={refresh}
            >
              <RefreshCw size={17} className={refreshing ? "spin" : ""} />
            </Button>
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          <div className="main-inner">
            {controller.demo && (
              <div className="demo-banner">
                <span>
                  <strong>Demo data</strong> · Explore sample readings and try settings safely.
                  Changes stay in memory.
                </span>
                <span>No live equipment connected</span>
              </div>
            )}
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
            {page === "overview" && (
              <Overview key={controller.roomId} controller={controller} navigate={navigate} />
            )}
            {page === "zones" && (
              <Zones key={controller.roomId} controller={controller} navigate={navigate} />
            )}
            {page === "strategy" && (
              <Strategy
                key={controller.roomId}
                controller={controller}
                drafts={drafts}
                setDrafts={setDrafts}
                selectedZone={zoneId}
              />
            )}
            {page === "grow-plan" && (
              <GrowPlanner
                key={controller.roomId}
                controller={controller}
                onDirtyChange={setWorkspaceDirty}
              />
            )}
            {page === "compare" && (
              <Comparison
                key={controller.roomId}
                controller={controller}
                onDirtyChange={setWorkspaceDirty}
              />
            )}
            {page === "insights" && (
              <Insights key={controller.roomId} controller={controller} navigate={navigate} />
            )}
            {page === "setup" && (
              <Setup
                key={controller.roomId}
                controller={controller}
                onDirtyChange={setWorkspaceDirty}
              />
            )}
            {page === "activity" && (
              <ActivityPage key={controller.roomId} controller={controller} />
            )}
            {page === "sensors" && <Sensors key={controller.roomId} controller={controller} />}
            {page === "settings" && (
              <Settings
                controller={controller}
                theme={theme.preference}
                setTheme={theme.setPreference}
                themeSource={theme.source}
              />
            )}
            {page === "help" && <Help controller={controller} />}
          </div>
        </main>
        <footer className="page-footer">
          <span>Crop Steering</span>
          <span>{controller.room.room.name} · Controller-reported data</span>
        </footer>
      </div>
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
}
