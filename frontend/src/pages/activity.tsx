import { useState } from "react";
import { Download, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Empty, Heading, time } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import type { Controller } from "@/lib/types";

export function ActivityPage({ controller }: { controller: Controller }) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [zoneId, setZoneId] = useState("all");
  const events = controller.room.events.filter(
    (event) =>
      (kind === "all" || event.type === kind) &&
      (zoneId === "all" || String(event.zoneId) === zoneId) &&
      event.message.toLowerCase().includes(query.toLowerCase()),
  );
  function exportCsv() {
    const cell = (value: string) => `"${value.replace(/^[=+@-]/, "'$&").replaceAll('"', '""')}"`;
    const csv = [
      ["Timestamp", "Room", "Zone", "Type", "Message"],
      ...events.map((e) => [
        e.timestamp,
        controller.room.room.name,
        e.zoneId === undefined ? "Room" : String(e.zoneId),
        e.type,
        e.message,
      ]),
    ]
      .map((row) => row.map(cell).join(","))
      .join("\r\n");
    const url = URL.createObjectURL(new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${
      controller.room.room.name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "") || "room"
    }-activity-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <>
      <Heading
        title="Activity"
        description="Search recorded controller events and export the current filtered view."
        action={
          <Button variant="outline" disabled={!events.length} onClick={exportCsv}>
            <Download size={16} />
            Export CSV
          </Button>
        }
      />
      <div className="toolbar">
        <div className="search-field">
          <Search size={17} />
          <Input
            aria-label="Search activity"
            placeholder="Search activity…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select
          aria-label="Filter activity type"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          <option value="all">All event types</option>
          <option value="water">Irrigation</option>
          <option value="phase">Phase changes</option>
          <option value="warning">Warnings</option>
          <option value="info">Information</option>
        </select>
        <select
          aria-label="Filter activity zone"
          value={zoneId}
          onChange={(e) => setZoneId(e.target.value)}
        >
          <option value="all">All zones</option>
          {controller.room.zones.map((zone) => (
            <option value={zone.id} key={zone.id}>
              {zone.name}
            </option>
          ))}
        </select>
        <span className="muted small">{events.length} records</span>
      </div>
      <section className="panel">
        {!events.length ? (
          <Empty
            title="No activity matches this view"
            detail={
              controller.room.events.length
                ? "Adjust the search or filters to see more records."
                : "No event records are available from the controller. This does not confirm that no irrigation occurred."
            }
            action={
              controller.room.events.length > 0 ? (
                <Button
                  variant="outline"
                  onClick={() => {
                    setQuery("");
                    setKind("all");
                    setZoneId("all");
                  }}
                >
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="table-scroll">
            <table className="data-table activity-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Event</th>
                  <th>Zone</th>
                  <th>Type</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    <td>
                      <time dateTime={event.timestamp}>
                        {time(event.timestamp)}
                        <span className="cell-subtext">
                          {Number.isFinite(new Date(event.timestamp).getTime())
                            ? new Date(event.timestamp).toLocaleDateString()
                            : "Date not recorded"}
                        </span>
                      </time>
                    </td>
                    <td>{event.message}</td>
                    <td>
                      {controller.room.zones.find((z) => z.id === event.zoneId)?.name || "Room"}
                    </td>
                    <td>
                      <Badge
                        variant="outline"
                        className={event.type === "warning" ? "status-paused" : ""}
                      >
                        {event.type}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <p className="footnote">
        Showing records exposed by the selected controller. Home Assistant’s full logbook may
        contain additional history.
      </p>
    </>
  );
}
