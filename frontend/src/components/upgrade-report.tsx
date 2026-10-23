import { useParity } from "@/lib/parity-api";
import type { Controller } from "@/lib/types";
import { reportView, type UpgradeRow } from "@/lib/upgrade-report";
import "./upgrade-report.css";

/** Settings › System status › Upgrade report: one panel per room that came from an earlier
 * release, with what the update carried across and what needs a person (the Repairs card CS-616
 * points here). A fresh room, or an integration without migration_report, shows nothing. */
export function UpgradeReports({ controller }: { controller: Pick<Controller, "operator" | "rooms"> }) {
  return (
    <>
      {controller.rooms.map((room) => (
        <RoomUpgradeReport key={room.id} controller={controller} roomId={room.id} roomName={room.name} />
      ))}
    </>
  );
}

function RoomUpgradeReport({
  controller,
  roomId,
  roomName,
}: {
  controller: Pick<Controller, "operator">;
  roomId: string;
  roomName: string;
}) {
  const answer = useParity<unknown>(controller, "migration_report", { room_id: roomId }, [roomId]);
  const view = answer.state === "ready" ? reportView(answer.data) : null;
  if (!view) return null;
  const title = `upgrade-report-${roomId.replace(/[^a-z0-9_-]/gi, "-")}`;
  return (
    <section className="panel upgrade-report" aria-labelledby={title} data-upgrade-report={roomId}>
      <header className="upgrade-report-head">
        <h2 id={title}>Upgrade report · {roomName}</h2>
        <p>
          What the {view.release || "update"} update carried across from your settings, and what needs you.
          Watering carries on as before. Each line opens the page to change it and the section of the
          upgrade guide to read.
        </p>
      </header>
      <div className="upgrade-report-lists">
        <List label="Needs you" rows={view.needsYou} kind="needs_you" />
        <List label="Carried across" rows={view.carried} kind="carried" />
      </div>
    </section>
  );
}

function List({ label, rows, kind }: { label: string; rows: UpgradeRow[]; kind: "carried" | "needs_you" }) {
  return (
    <section className="upgrade-report-list" aria-label={label} data-upgrade-list={kind}>
      <h3>
        {label} <span className="upgrade-report-count">{rows.length}</span>
      </h3>
      {rows.length ? (
        <ul>
          {rows.map((row) => (
            <li key={row.id} data-upgrade-row={row.id}>
              <strong>{row.title}</strong>
              {row.detail && <span className="upgrade-report-detail">{row.detail}</span>}
              {(row.page || row.doc) && (
                <span className="upgrade-report-links">
                  {row.page && <a href={row.page}>Open the page</a>}
                  {row.doc && (
                    <a href={row.doc} target="_blank" rel="noreferrer">
                      How to set it up
                    </a>
                  )}
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="upgrade-report-none">{kind === "needs_you" ? "Nothing needs you." : "Nothing was carried across."}</p>
      )}
    </section>
  );
}
