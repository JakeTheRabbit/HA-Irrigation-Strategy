import { useState } from "react";
import { SensorContextCard, useSensorContext } from "@/components/sensor-context";
import { referenceLines } from "@/lib/sensor-context";
import { buildSetpointPreview } from "@/lib/setpoint-preview";
import type { Controller, Zone } from "@/lib/types";
import "@/pages/zone.css";

/** What the probes recorded over days, against the zone's targets: opened on request. */
export function RecordedBehaviour({ controller, zone }: { controller: Controller; zone: Zone }) {
  const [open, setOpen] = useState(false);
  const connected = ["live", "demo"].includes(controller.connection);
  const sensor = useSensorContext(controller, zone, open && connected);
  const preview = buildSetpointPreview(controller.room, controller.states, zone.id, {});
  return (
    <details
      className="zone-recorded"
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>Recorded behaviour against targets</summary>
      {open && (
        <SensorContextCard
          context={sensor}
          lines={referenceLines({
            draft: preview.saved.parameters,
            typicalDailyPeak: sensor.vwc.stats?.typicalDailyPeak ?? null,
            learnedPeak: zone.auto?.learnedPeak ?? null,
          })}
          subtitle="what the probes read, with the zone’s targets drawn over it"
          disabledNote="Recorded history loads while Home Assistant is connected."
        />
      )}
    </details>
  );
}
