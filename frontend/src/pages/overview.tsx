import { DayTimeline } from "@/components/day-timeline";
import { TankStatus } from "@/components/tank-status";
import { useState } from "react";
import { ArrowRight, ArrowUpRight, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Controller } from "@/lib/types";
import { leadingNotices } from "@/lib/model";
import { drybackTrend } from "@/lib/dryback";
import { useRecentMoisture } from "@/lib/use-recent-moisture";
import { coreWaterValue, waterParameters } from "@/lib/water-delivery";
import { RoomPower } from "@/components/room-controls";
import { Empty, Heading, Metrics, ZoneDetails, ZoneTable, type Page } from "@/components/dashboard";

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
  const moisture = useRecentMoisture(controller);
  const now = Date.now();
  const trends =
    moisture &&
    Object.fromEntries(
      room.zones.map((zone) => [
        zone.id,
        drybackTrend(
          moisture.find((series) => series.entityId === zone.vwc.entityId)?.points ?? [],
          zone.lastIrrigation.timestamp,
          zone.vwc.value,
          now,
        ),
      ]),
    );
  // The limit the controller enforces: the configured value inside its safety bounds.
  const limits = Object.fromEntries(
    room.zones.map((zone) => [
      zone.id,
      coreWaterValue("max_daily_volume", waterParameters(controller, zone.id).max_daily_volume)
        .value,
    ]),
  );
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
      <Metrics metrics={room.metrics} zones={room.zones} waterLimits={limits} />
      <DayTimeline controller={controller} />
      <div className="overview-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>Zones at a glance</h2>
            <Button variant="ghost" onClick={() => navigate("zones")}>
              All zones <ArrowRight size={16} />
            </Button>
          </div>
          {room.zones.length ? (
            <ZoneTable
              compact
              zones={room.zones}
              trends={trends}
              limits={limits}
              onSelect={(zone) => setSelected(zone.id)}
            />
          ) : (
            <Empty
              title="No zones discovered"
              detail="Connect Home Assistant in Settings. Zones are discovered from the controller entities available to your account."
              action={
                <Button onClick={() => navigate("settings")}>Open connection settings</Button>
              }
            />
          )}
        </section>
        <TankStatus controller={controller} onConfigure={() => navigate("setup")} />
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
