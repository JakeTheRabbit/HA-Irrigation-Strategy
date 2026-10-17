import { useMemo, useState } from "react";
import { ExternalLink, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Heading } from "@/components/dashboard";
import { APP_OPTIONS, GROUPS, featureRows, matches, placementsFor } from "@/lib/features";
import { ownerOf, ownerHref } from "@/lib/config-owners";
import type { Controller } from "@/lib/types";
import "./features.css";

/** A read-only inventory. Every editable capability links to its sole workspace. */
export function Features({ controller }: { controller: Controller }) {
  const { room } = controller;
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("all");
  const [changedOnly, setChangedOnly] = useState(false);
  const rows = useMemo(
    () =>
      featureRows(
        controller.states,
        room.room.prefix,
        room.zones.map((z) => z.id),
        room.engine.entityId,
      ),
    [controller.states, room],
  );
  const visible = rows.filter(
    (r) =>
      (group === "all" || r.feature.group === group) &&
      (!changedOnly || r.changed) &&
      matches(r, query),
  );
  const placements = changedOnly ? [] : placementsFor(group, query);
  return (
    <>
      <Heading
        title="Capabilities"
        description="Current settings and their editing workspaces. Search by capability or setting name."
      />
      <div className="features-toolbar">
        <label className="features-search">
          <Search size={16} aria-hidden="true" />
          <Input
            type="search"
            aria-label="Search features"
            placeholder="Search features"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          aria-label="Group"
          value={group}
          onChange={(e) => setGroup(e.target.value)}
          className="features-group-select"
        >
          <option value="all">All groups</option>
          {GROUPS.map((g) => (
            <option key={g.id} value={g.id}>
              {g.label}
            </option>
          ))}
        </select>
        <label className="features-changed">
          <input
            type="checkbox"
            checked={changedOnly}
            onChange={(e) => setChangedOnly(e.target.checked)}
          />
          Changed from default
        </label>
      </div>
      {GROUPS.filter((g) => g.id !== "app").map((g) => {
        const list = visible.filter((r) => r.feature.group === g.id);
        return list.length ? (
          <section className="panel features-group" key={g.id}>
            <div className="panel-heading">
              <h2>{g.label}</h2>
              <p>{g.help}</p>
            </div>
            <ul className="features-list">
              {list.map((row) => (
                <li key={row.feature.id} className="features-row" data-feature={row.feature.id}>
                  <div className="features-name">
                    <strong>{row.feature.label}</strong>
                    <p>{row.feature.help}</p>
                    <span className="features-scope">
                      {row.changed ? "Changed from default" : "Default settings"}
                    </span>
                    <dl>
                      {[row.master, ...row.settings].flatMap((r) =>
                        r
                          ? [r.room, ...r.zones].flatMap((c) =>
                              c
                                ? [
                                    <div key={c.entityId}>
                                      <dt>
                                        {r.control.label ?? r.control.key.replaceAll("_", " ")} ·{" "}
                                        {c.zone === null
                                          ? "Room"
                                          : (room.zones.find((z) => z.id === c.zone)?.name ??
                                            `Zone ${c.zone}`)}
                                      </dt>
                                      <dd>
                                        {c.value === null
                                          ? "Unavailable"
                                          : typeof c.value === "boolean"
                                            ? c.value
                                              ? "On"
                                              : "Off"
                                            : String(c.value)}{" "}
                                        {String(c.entity.attributes.unit_of_measurement ?? "")}
                                      </dd>
                                    </div>,
                                  ]
                                : [],
                            )
                          : [],
                      )}
                    </dl>
                  </div>
                  <a className="features-also" href={ownerHref(row.feature)}>
                    Open {ownerOf(row.feature).label}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ) : null;
      })}
      {(group === "all" || group === "app") && !changedOnly && <AppOptions query={query} />}
      {placements.length > 0 && (
        <section className="panel features-group">
          <div className="panel-heading">
            <h2>Other settings and views</h2>
          </div>
          <ul className="features-list">
            {placements.map((row) => (
              <li className="features-row" key={`${row.id}:${row.entity}`}>
                <div className="features-name">
                  <strong>{row.label}</strong>
                  <p>{row.help}</p>
                </div>
                <a className="features-also" href={`#/${row.page}`}>
                  {row.location}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
      {!visible.length && !placements.length && group !== "app" && (
        <p className="features-empty">No feature matches.</p>
      )}
    </>
  );
}

function AppOptions({ query }: { query: string }) {
  const app = GROUPS.find((g) => g.id === "app")!;
  const q = query.trim().toLowerCase();
  const list = APP_OPTIONS.filter(
    (o) => !q || o.label.toLowerCase().includes(q) || o.key.includes(q),
  );
  if (!list.length) return null;
  return (
    <section className="panel features-group" aria-labelledby="fg-app">
      <div className="panel-heading">
        <h2 id="fg-app">{app.label}</h2>
        <p>{app.help}</p>
      </div>
      <ul className="features-list">
        {list.map((o) => (
          <li key={o.key} className="features-row is-readonly" data-option={o.key}>
            <div className="features-name">
              <strong>{o.label}</strong>
              <span className="features-scope">
                <code>{o.key}</code> · Default: {o.secret ? "not shown" : o.default}
              </span>
            </div>
          </li>
        ))}
      </ul>
      <p className="features-app-link">
        <a href="/hassio/dashboard" target="_top" rel="noreferrer">
          Open the apps in Home Assistant <ExternalLink size={14} aria-hidden="true" />
        </a>{" "}
        Then open the controller app and its Configuration tab.
      </p>
    </section>
  );
}
