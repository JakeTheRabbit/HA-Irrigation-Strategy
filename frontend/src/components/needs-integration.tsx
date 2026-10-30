import { InfoTip } from "./info-tip";
import "./needs-integration.css";

const HEADING = "Needs integration 3.18";
const body = (feature: string) =>
  `${feature} needs Crop Steering 3.18 or newer. Update the integration and the controller app together; the rest of this page keeps working.`;

/** In place of a part whose v2 service the connected integration does not have yet. */
export function NeedsIntegration({ feature, compact = false }: { feature: string; compact?: boolean }) {
  if (compact)
    return (
      <p className="needs-integration is-compact" data-needs-integration={feature}>
        <strong>{HEADING}</strong>
        <InfoTip label={HEADING} copy={{ tooltip: body(feature) }} />
      </p>
    );
  return (
    <section className="needs-integration" role="note" data-needs-integration={feature}>
      <h3>{HEADING}</h3>
      <p>{body(feature)}</p>
    </section>
  );
}
