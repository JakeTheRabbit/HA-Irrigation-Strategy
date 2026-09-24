import { DailyWaterSummary } from "@/components/water-delivery";
import { DayTimeline } from "@/components/day-timeline";
import { TankStatus } from "@/components/tank-status";
import { useState } from "react";
import { ArrowRight, ArrowUpRight, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Controller, Zone } from "@/lib/types";
import { leadingNotices } from "@/lib/model";
import { RoomPower } from "@/components/room-controls";
import {
  Empty,
  Heading,
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
  const notices = leadingNotices(room.alerts);
  return (
    <>
      <Heading
        title={controller.roomId ? `${room.room.name} overview` : "Overview"}
        action={
          <div className="heading-actions">
            <RoomPower controller={controller} />
            <Button variant="outline" onClick={() => navigate("grow-plan")}>
              Irrigation plan <ArrowUpRight size={16} />
            </Button>
          </div>
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
          {!room.roomActive
            ? "This room is off. Nothing will irrigate and no alerts are raised until it is switched back on."
            : room.engine.enabled === true
              ? "Follow zone readings and recorded activity below."
              : room.engine.enabled === false
                ? "Scheduling is paused. An active shot may still be running."
                : "Connect a controller to see scheduling state."}
        </p>
      </div>
      {!!room.alerts.length && (
        <div className="attention-list">
          {notices.map((notice) => (
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
          {room.alerts.length > notices.length && (
            <Button variant="ghost" onClick={() => navigate("sensors")}>
              Review {room.alerts.length - notices.length} more notices in Sensors{" "}
              <ArrowRight size={15} />
            </Button>
          )}
        </div>
      )}
      <Metrics metrics={room.metrics} />
      <TankStatus controller={controller} onConfigure={() => navigate("setup")} />
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Zones at a glance</h2>
            <p>Controller state, valve activity and the last recorded irrigation</p>
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
      <DailyWaterSummary controller={controller} />
      <DayTimeline controller={controller} />
      <ZoneDetails
        controller={controller}
        zone={room.zones.find((z) => z.id === selected) || null}
        close={() => setSelected(null)}
        navigate={navigate}
      />
    </>
  );
}
