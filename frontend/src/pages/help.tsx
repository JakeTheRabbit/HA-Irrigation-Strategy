import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  BookOpen,
  CalendarRange,
  ChevronRight,
  Gauge,
  Map,
  Radio,
  Search,
} from "lucide-react";
import { Heading } from "@/components/dashboard";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  asCode,
  codeFromHash,
  errorCodeGroups,
  errorCodes,
  findErrorCodes,
  severityLabel,
} from "@/lib/error-codes";
import type { Controller } from "@/lib/types";
const glossary = [
  [
    "Water per zone and per plant",
    "Zone water is the total delivered estimate for all plants. Average per plant divides that total by plant count. Substrate litres describe the combined pot capacity; they are not water delivered. Runtime estimates multiply dripper flow by run time and respect the controller duration limit.",
  ],
  [
    "Run comparisons",
    "Choose a day, week, month or run-to-date to compare recorded VWC and EC. Previous runs align by grow age. Saved target references show when they were captured; backdating a run does not recreate old targets or readings removed by Recorder retention.",
  ],
  [
    "VWC",
    "Volumetric water content: the percentage of substrate volume occupied by water. Compare recorded readings with active targets; a nominal shot does not guarantee the same retained-water increase.",
  ],
  [
    "Root-zone EC",
    "Electrical conductivity of the substrate measurement, in mS/cm after normalization. Pore EC and bulk EC are different measurement bases; use targets appropriate to the mapped sensor. Feed-water EC is a separate reservoir measurement.",
  ],
  [
    "Dryback",
    "The controller uses relative loss from peak: (peak VWC − current VWC) ÷ peak VWC × 100. A 60% peak and 10% dryback target means 54% VWC, not 50%.",
  ],
  [
    "P0 · Morning wait",
    "After lights-on, the controller waits for dryback or its maximum-wait condition. Existing low-VWC and emergency safeguards can take precedence.",
  ],
  [
    "P1 · Ramp-up",
    "Progressive shots bring substrate moisture to the P1 target, subject to maximum shots, timing and safety limits.",
  ],
  [
    "P2 · Maintenance",
    "Maintenance shots respond to the VWC trigger. EC feedback may adjust the base threshold; the planning curve shows the base setpoints, not a measured prediction.",
  ],
  [
    "P3 · Overnight",
    "Routine irrigation stops. The configured emergency floor can permit a rescue shot. There is no independent scheduled P3 EC target.",
  ],
  [
    "Steering balance",
    "0% uses the vegetative endpoint; 100% uses the generative endpoint; intermediate values blend their explicit parameters. Pot size and dripper flow convert shot fractions to delivery volume and time.",
  ],
  [
    "Planning versus history",
    "The planning curve is a schematic drawn from targets. Recorded history comes from Home Assistant Recorder. Neither an event acknowledgement nor a modeled curve proves physical delivery.",
  ],
];
export function Help({ controller }: { controller: Controller }) {
  return (
    <>
      <Heading title="Help & tools" />
      <div className="help-intro">
        <BookOpen size={28} />
        <div>
          <h2>Map. Plan. Review. Verify.</h2>
          <p>
            Configure each room and zone, check sensor validity, set explicit endpoint profiles,
            then review the daily or weekly grow plan. Live targets and manual fallback values are
            kept distinct.
          </p>
          <h3 id="daily-routine">Daily routine</h3>
          <ol className="daily-routine">
            <li>
              <a href="#/overview">Check the room’s readings and alerts on the Overview</a>
            </li>
            <li>
              <a href="#/zones">Inspect any zone that needs attention</a>
            </li>
            <li>
              <a href="#/strategy">Review irrigation changes before applying them</a>
            </li>
          </ol>
        </div>
      </div>
      <div className="help-columns">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Terms & phases</h2>
              <p>What the controls mean in practice</p>
            </div>
          </div>
          <dl className="glossary">
            {glossary.map(([term, definition]) => (
              <div key={term}>
                <dt>{term}</dt>
                <dd>{definition}</dd>
              </div>
            ))}
          </dl>
        </section>
        <div>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Advanced workflows</h2>
                <p>Everything uses the same room context and layout.</p>
              </div>
            </div>
            <div className="specialist-links">
              {[
                {
                  route: "grow-plan",
                  title: "Irrigation plan · Schedule",
                  detail: "Schedule changes to zone targets by day or week.",
                  icon: CalendarRange,
                },
                {
                  route: "strategy",
                  title: "Irrigation plan · Today",
                  detail: "See current targets and edit them when a schedule is not active.",
                  icon: Gauge,
                },
                {
                  route: "compare",
                  title: "Compare runs & targets",
                  detail:
                    "Compare recorded days, weeks and complete runs against reference targets.",
                  icon: CalendarRange,
                },
                {
                  route: "insights",
                  title: "Insights & calibration",
                  detail: "Inspect delivery sizing, data quality and device mapping.",
                  icon: Radio,
                },
                {
                  route: "setup",
                  title: "Rooms, zones & installation",
                  detail: "Map sensors and hardware; add, archive or restore zones.",
                  icon: Map,
                },
              ].map((tool) => (
                <a href={"#/" + tool.route} key={tool.route}>
                  <tool.icon size={20} />
                  <span>
                    <strong>{tool.title}</strong>
                    <small>{tool.detail}</small>
                  </span>
                  <ArrowUpRight size={17} />
                </a>
              ))}
            </div>
          </section>
          <div className="help-note">
            <div>
              <h3>When changes take effect</h3>
              <p>
                Manual setpoint writes use fresh bounds and state readback. Grow plans are saved as
                drafts, explicitly armed, then activated at a local lights-on boundary. Disarming an
                active plan retains its targets until the next boundary.
              </p>
              <p>
                Mapping changes require disarmed engines and hardware OFF. Saving configuration
                confirms Home Assistant storage; wait for controller revision acknowledgement before
                enabling operation.
              </p>
            </div>
          </div>
          <div className="help-note">
            <div>
              <h3>What is not claimed</h3>
              <p>
                This controller does not regulate room climate or predict yield/potency. Historical
                manual-shot and phase-event services have no verified execution consumer in the
                shipped polling engine and are not exposed as operating buttons.
              </p>
              <p>
                Missing/stale readings remain unavailable. Your current room is{" "}
                {controller.room.room.name}.
              </p>
            </div>
          </div>
        </div>
      </div>
      <ErrorCodes />
    </>
  );
}

/** Every code a notification or Repairs card can end with, searchable, from docs/error-codes.json. */
function ErrorCodes() {
  const [query, setQuery] = useState(() => codeFromHash(window.location.hash) ?? "");
  const found = findErrorCodes(query);
  const exact = asCode(query);
  const section = useRef<HTMLElement>(null);
  useEffect(() => {
    // Opened as #/help?code=CS-101, or sent there while already on this page (the app does not
    // re-render a page for a change after its "?"): show that code and bring it into view.
    const follow = () => {
      const code = codeFromHash(window.location.hash);
      if (!code) return;
      setQuery(code);
      section.current?.scrollIntoView({ block: "start" });
    };
    follow();
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  return (
    <section ref={section} className="panel error-codes" aria-labelledby="error-codes-title">
      <div className="panel-heading">
        <div>
          <h2 id="error-codes-title">Error codes</h2>
          <p>
            Every Crop Steering notification and Repairs card ends with a code such as CS-101. Look
            it up here for what it means, what happens to watering meanwhile, and what to do.
          </p>
        </div>
      </div>
      <div className="error-codes-body">
        <div className="search-field">
          <Search size={17} />
          <Input
            aria-label="Search error codes"
            placeholder="A code or words, e.g. 101 or probe"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {found.length === 0 && (
          <p className="error-codes-empty">
            No code matches “{query.trim()}”. Codes run from {errorCodes[0].code} to{" "}
            {errorCodes[errorCodes.length - 1].code}.
          </p>
        )}
        {errorCodeGroups.map((group) => {
          const codes = found.filter((entry) => entry.code.startsWith(group.prefix));
          if (!codes.length) return null;
          return (
            <div className="error-code-group" key={group.prefix}>
              <h3>
                {group.name} <span>{group.prefix}xx</span>
              </h3>
              <p>{group.detail}</p>
              {codes.map((entry) => (
                <details
                  className="error-code"
                  id={entry.code.toLowerCase()}
                  key={`${entry.code}-${exact === entry.code}`}
                  open={exact === entry.code || undefined}
                >
                  <summary>
                    <code>{entry.code}</code>
                    <span className="error-code-title">{entry.title}</span>
                    <Badge variant="outline" className={`severity-${entry.severity}`}>
                      {severityLabel[entry.severity]}
                    </Badge>
                    <ChevronRight size={16} aria-hidden="true" className="error-code-chevron" />
                  </summary>
                  <dl>
                    <div>
                      <dt>What it means</dt>
                      <dd>{entry.meaning}</dd>
                    </div>
                    <div>
                      <dt>Watering meanwhile</dt>
                      <dd>{entry.watering}</dd>
                    </div>
                    <div>
                      <dt>Likely causes</dt>
                      <dd>
                        <ul>
                          {entry.causes.map((cause) => (
                            <li key={cause}>{cause}</li>
                          ))}
                        </ul>
                      </dd>
                    </div>
                    <div>
                      <dt>Suggested fixes</dt>
                      <dd>
                        <ul>
                          {entry.fixes.map((fix) => (
                            <li key={fix}>{fix}</li>
                          ))}
                        </ul>
                      </dd>
                    </div>
                  </dl>
                  <p className="error-code-source">
                    {entry.source === "repairs"
                      ? "Shown as a card under Settings → Repairs."
                      : "Shown as a Home Assistant notification from the controller app."}
                  </p>
                </details>
              ))}
            </div>
          );
        })}
      </div>
    </section>
  );
}
