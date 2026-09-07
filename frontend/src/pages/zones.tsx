import { DailyWaterSummary } from "@/components/water-delivery";
import { useState } from "react";
import { ArrowUpRight, LayoutGrid, List, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Empty,
  Heading,
  LastIrrigation,
  MetricValue,
  Status,
  ZoneDetails,
  ZoneOperatingState,
  ZoneTable,
  type Page,
} from "@/components/dashboard";
import type { Controller } from "@/lib/types";

export function Zones({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: (page: Page, zoneId?: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [layout, setLayout] = useState<"table" | "cards">(() =>
    window.matchMedia("(max-width: 720px)").matches ? "cards" : "table",
  );
  const [selected, setSelected] = useState<number | null>(null);
  const zones = controller.room.zones.filter((zone) =>
    `${zone.name} ${zone.phase} ${zone.status}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <>
      <Heading
        title="Zones"
        description="Inspect each zone’s readings, phase and scheduling state."
        action={
          <Button variant="outline" onClick={() => navigate("strategy")}>
            Edit strategy <ArrowUpRight size={16} />
          </Button>
        }
      />
      <div className="toolbar">
        <div className="search-field">
          <Search size={17} />
          <Input
            aria-label="Search zones"
            placeholder="Search zones or phases…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <span className="muted small">
          {zones.length} {zones.length === 1 ? "zone" : "zones"}
        </span>
        <div className="segmented">
          <Button
            size="icon"
            variant={layout === "table" ? "secondary" : "ghost"}
            aria-label="Table view"
            aria-pressed={layout === "table"}
            onClick={() => setLayout("table")}
          >
            <List size={17} />
          </Button>
          <Button
            size="icon"
            variant={layout === "cards" ? "secondary" : "ghost"}
            aria-label="Card view"
            aria-pressed={layout === "cards"}
            onClick={() => setLayout("cards")}
          >
            <LayoutGrid size={17} />
          </Button>
        </div>
      </div>
      {!zones.length ? (
        <section className="panel">
          <Empty
            title={query ? "No matching zones" : "No zones discovered"}
            detail={
              query
                ? "Try a different zone name or phase."
                : "Connect your controller in Settings to discover configured zones."
            }
            action={
              query ? (
                <Button variant="outline" onClick={() => setQuery("")}>
                  Clear search
                </Button>
              ) : (
                <Button onClick={() => navigate("settings")}>Connection settings</Button>
              )
            }
          />
        </section>
      ) : layout === "table" ? (
        <section className="panel">
          <ZoneTable zones={zones} onSelect={(zone) => setSelected(zone.id)} />
        </section>
      ) : (
        <div className="zone-grid">
          {zones.map((zone) => (
            <section className="panel zone-card" key={zone.id}>
              <div className="split-row">
                <h2>{zone.name}</h2>
                <Status enabled={zone.enabled} />
              </div>
              <ZoneOperatingState zone={zone} showScheduling={false} />
              <div className="zone-irrigation-summary">
                <span className="small muted">Last irrigation</span>
                <LastIrrigation zone={zone} />
              </div>
              <div className="zone-card-moisture">
                <MetricValue metric={zone.vwc} />
                <span>Moisture · VWC</span>
              </div>
              <div className="zone-card-pair">
                <span>
                  {zone.target.label}
                  <strong>
                    <MetricValue metric={zone.target} />
                  </strong>
                </span>
                <span>
                  Root-zone EC
                  <strong>
                    <MetricValue metric={zone.ec} />
                  </strong>
                </span>
              </div>
              <Button variant="outline" className="full-width" onClick={() => setSelected(zone.id)}>
                View zone <ArrowUpRight size={16} />
              </Button>
            </section>
          ))}
        </div>
      )}
      <DailyWaterSummary controller={controller} zones={zones} />
      <ZoneDetails
        controller={controller}
        zone={controller.room.zones.find((zone) => zone.id === selected) || null}
        close={() => setSelected(null)}
        navigate={navigate}
      />
    </>
  );
}
