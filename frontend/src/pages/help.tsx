import { useEffect, useRef, useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import { Heading } from "@/components/dashboard";
import { WhatsNewButton } from "@/components/whats-new";
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

/** The words the dashboard uses, as a grower reads them. */
const glossary = [
  [
    "VWC (moisture)",
    "Volumetric water content: the share of the substrate’s volume that is water, in %. Every moisture target, the peak, the re-water point and the rescue level, is a VWC.",
  ],
  [
    "Pore EC",
    "The conductivity of the water in the substrate’s pores, in mS/cm: how much salt the roots sit in. It is read in the slab; the feed’s EC is a separate reading. Each stage has its pore EC range.",
  ],
  [
    "Dryback",
    "How far moisture falls from the day’s peak, as a share of the peak: from a 65% peak, a 20% dryback ends at 52%. A bigger dryback steers generative, a smaller one vegetative.",
  ],
  [
    "P0 · Morning dryback",
    "From lights-on to the first shot: the plants drink before the day’s watering starts. It ends at the latest first shot, or sooner if moisture falls to the re-water point.",
  ],
  [
    "P1 · Ramp-up",
    "The first shots of the day, spaced out, up to the peak target or the most P1 shots.",
  ],
  [
    "P2 · Maintenance",
    "Through the day, a shot fires whenever moisture reads below the re-water point. Shot size and the re-water point steer runoff and pore EC.",
  ],
  [
    "P3 · Overnight dryback",
    "From the day’s last shot to lights-on: no routine watering, only a rescue shot if moisture reads below the rescue level.",
  ],
  [
    "Steering",
    "Vegetative keeps the slab wetter, with smaller drybacks, more runoff and a lower pore EC, for growth; generative dries it further, with less runoff and a higher pore EC, for flowers.",
  ],
  [
    "Runoff",
    "The water that drains out of the slab, as a share of the water fed: it carries salt out. Athena gives 8–16% steering vegetative and 1–7% generative.",
  ],
];

/** Settings › Help: what an alert code means and what to do, and the words the dashboard uses. The
 * user guide (docs/USER_GUIDE.md) has the rest. */
export function Help({ controller }: { controller: Controller }) {
  return (
    <>
      <Heading title="Help" action={<WhatsNewButton controller={controller} />} />
      <ErrorCodes />
      <section className="panel" aria-labelledby="glossary-title">
        <div className="panel-heading">
          <div>
            <h2 id="glossary-title">Terms and phases</h2>
            <p>What the dashboard’s words mean for the crop</p>
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
            Every Crop Steering alert and Repairs card ends with a code such as CS-101 (the
            controller's regular status summary has none). Look it up here for what it means, what
            happens to watering meanwhile, and what to do.
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
