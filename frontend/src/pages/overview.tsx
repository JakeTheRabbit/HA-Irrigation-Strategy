import { DailyWaterSummary } from "@/components/water-delivery";
import { useState } from "react";
import { ArrowRight, ArrowUpRight, CircleCheck, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Controller, Zone } from "@/lib/types";
import {
  Empty,
  EventList,
  Heading,
  HistoryChart,
  Metrics,
  Status,
  ZoneDetails,
  ZoneTable,
  type Page,
} from "@/components/dashboard";

export function Overview({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: (page: Page, zoneId?: number) => void;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const room = controller.room;
  return (
    <>
      <Heading
        title="Room overview"
        description={`A clear view of ${room.room.name.toLowerCase()}: moisture, scheduling and recent activity.`}
        action={
          <Button variant="outline" onClick={() => navigate("grow-plan")}>
            Grow plan <ArrowUpRight size={16} />
          </Button>
        }
      />
      <div className="room-summary">
        <div>
          <span className="eyebrow">Controller scheduling</span>
          <div className="split-row">
            <Status enabled={room.engine.enabled} />
            <span className="muted">
              {room.zones.filter((z) => z.enabled).length} of {room.zones.length} zones enabled
            </span>
          </div>
        </div>
        <p>
          {room.engine.enabled === true
            ? "Follow zone readings and recorded activity below."
            : room.engine.enabled === false
              ? "Scheduling is paused. An active shot may still be running."
              : "Connect a controller to see scheduling state."}
        </p>
      </div>
      {!!room.alerts.length && (
        <div className="attention-list">
          {room.alerts.slice(0, 3).map((notice) => (
            <div className={`attention attention-${notice.severity}`} key={notice.id}>
              <TriangleAlert size={20} />
              <div>
                <strong>{notice.title}</strong>
                <p>{notice.detail}</p>
              </div>
              {notice.zoneId !== undefined && (
                <Button variant="ghost" onClick={() => setSelected(notice.zoneId!)}>
                  View zone <ArrowRight size={15} />
                </Button>
              )}
            </div>
          ))}
          {room.alerts.length > 3 && (
            <Button variant="ghost" onClick={() => navigate("sensors")}>
              Review {room.alerts.length - 3} more notices in Sensors <ArrowRight size={15} />
            </Button>
          )}
        </div>
      )}
      <Metrics metrics={room.metrics} />
      <DailyWaterSummary controller={controller} />
      <HistoryChart controller={controller} zones={room.zones} />
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Zones at a glance</h2>
            <p>Current measurements and configured targets</p>
          </div>
          <Button variant="ghost" onClick={() => navigate("zones")}>
            All zones <ArrowRight size={16} />
          </Button>
        </div>
        {room.zones.length ? (
          <ZoneTable zones={room.zones} onSelect={(zone) => setSelected(zone.id)} />
        ) : (
          <Empty
            title="No zones discovered"
            detail="Connect Home Assistant in Settings. Zones are discovered from the controller entities available to your account."
            action={<Button onClick={() => navigate("settings")}>Open connection settings</Button>}
          />
        )}
      </section>
      <div className="overview-bottom">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Recent activity</h2>
              <p>Latest controller records</p>
            </div>
            <Button variant="ghost" onClick={() => navigate("activity")}>
              View activity <ArrowRight size={16} />
            </Button>
          </div>
          <EventList events={room.events.slice(0, 5)} />
        </section>
        <section className="panel next-panel">
          <CircleCheck size={26} />
          <h2>Your daily workflow</h2>
          <p>
            Check readings, inspect any zone that needs attention, then review strategy changes
            before applying them.
          </p>
          <button onClick={() => navigate("zones")}>
            Inspect individual zones <ArrowRight size={16} />
          </button>
          <button onClick={() => navigate("strategy")}>
            Review irrigation settings <ArrowRight size={16} />
          </button>
          <button onClick={() => navigate("help")}>
            Understand phases & metrics <ArrowRight size={16} />
          </button>
        </section>
      </div>
      <ZoneDetails
        controller={controller}
        zone={room.zones.find((z) => z.id === selected) || null}
        close={() => setSelected(null)}
        navigate={navigate}
      />
    </>
  );
}
